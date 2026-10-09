# -*- coding: utf-8 -*-
"""Telas do GDF com streamlit.testing (AppTest) + Postgres descartavel. Login simulado; upload simulado."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import db
import importador_csv as I
import motor
from dados_sinteticos import csv_texto, gerar_meses, pdf_balancete

pytestmark = pytest.mark.pg
APP = Path(__file__).resolve().parent.parent
CNPJ = "54.800.488/0001-60"                      # CNPJ da empresa inicial (so' o numero publico; dados sinteticos)
MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)])
SESSAO = SimpleNamespace(user=SimpleNamespace(email="usuaria@teste"))


def _app(tela, conn):
    at = AppTest.from_file(str(APP / "telas" / tela), default_timeout=30)
    at.session_state["auth_session"] = SESSAO
    return at


@pytest.fixture()
def patch_conn(conn):
    with patch("conexao.get_conn", return_value=conn):
        yield conn


def _semear(conn, meses=(1, 2, 3)):
    emp_id = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    db.garantir_mapa(conn, emp_id)
    for m in meses:
        ult = {1: "31", 2: "28", 3: "31"}[m]
        cab, contas = I.ler_bytes(csv_texto(MESES[f"2026-{m:02d}"], cnpj=CNPJ, ini=f"01/{m:02d}/2026", fim=f"{ult}/{m:02d}/2026"), f"{m}.csv")
        db.inserir_importacao(conn, emp_id, cab, contas, "seed", motor.conferencias_arquivo(contas, db.mapa_vigente(conn, emp_id), cab["periodo"]))
    return emp_id


def _textos(at):
    return " ".join([m.value for m in at.markdown] + [m.value for m in at.success] + [m.value for m in at.warning] + [m.value for m in at.info] + [m.value for m in at.error])


def test_demonstrativos_sem_dados(patch_conn):
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert not at.exception
    assert any("Ainda não há balancete" in i.value for i in at.info)


def test_demonstrativos_com_dados(patch_conn):
    _semear(patch_conn)
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert not at.exception, at.exception
    assert any("conferências passaram" in s.value for s in at.success)
    assert len(at.tabs) == 5 and len(at.dataframe) >= 4
    assert at.selectbox(key="dem_mes").value == "2026-03"
    at.selectbox(key="dem_mes").select("2026-02").run()
    assert not at.exception


def test_demonstrativos_mes_sem_janeiro(patch_conn):
    _semear(patch_conn, meses=(2, 3))
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert not at.exception
    assert any("falta o mês de janeiro" in w.value for w in at.warning)


def test_historico_desfazer_e_reativar(patch_conn):
    emp_id = _semear(patch_conn, meses=(1,))
    at = _app("3_Historico.py", patch_conn).run()
    assert not at.exception
    at.button(key="hist_desfazer").click().run()
    assert not at.exception and db.listar_meses_ativos(patch_conn, emp_id) == []
    at = _app("3_Historico.py", patch_conn).run()
    at.button(key="hist_reativar").click().run()
    assert db.listar_meses_ativos(patch_conn, emp_id) == ["2026-01"]


def test_mapa_de_contas(patch_conn):
    _semear(patch_conn, meses=(1,))
    at = _app("4_Mapa_de_Contas.py", patch_conn).run()
    assert not at.exception and len(at.dataframe) >= 1
    assert any("Toda conta com saldo" in s.value for s in at.success)


class _Upload:
    def __init__(self, nome, dados):
        self.name, self._d = nome, dados

    def getvalue(self):
        return self._d


def _importar(conn, arquivos):
    at = _app("1_Importar_Balancete.py", conn)
    with patch("streamlit.file_uploader", return_value=arquivos):
        at.run()
        return at


def test_importar_fluxo_completo(patch_conn):
    arqs = [_Upload(f"{m}.csv", csv_texto(MESES[f"2026-0{m}"], cnpj=CNPJ, ini=f"01/0{m}/2026", fim={1: "31", 2: "28", 3: "31"}[m] + f"/0{m}/2026")) for m in (1, 2)]
    at = _importar(patch_conn, arqs)
    assert not at.exception, at.exception
    botao = [b for b in at.button if "Importar 2 arquivo" in b.label]
    assert botao, [b.label for b in at.button]
    with patch("streamlit.file_uploader", return_value=arqs):
        botao[0].click().run()
    assert not at.exception
    emp = db.empresa_por_cnpj(patch_conn, CNPJ)
    assert db.listar_meses_ativos(patch_conn, emp["id"]) == ["2026-01", "2026-02"]
    # reenviar os mesmos arquivos: avisa que ja' foram importados, nao oferece importar de novo e oferece confirmar (ainda sao RASCUNHO)
    at2 = _importar(patch_conn, arqs)
    assert any("já está importado" in i.value for i in at2.info)
    assert not [b for b in at2.button if "Importar" in b.label and "arquivo" in b.label]
    conf = [b for b in at2.button if "como REVISADA" in b.label]
    assert len(conf) == 2
    with patch("streamlit.file_uploader", return_value=arqs):
        conf[0].click().run()
    assert not at2.exception, at2.exception
    sts = {i["periodo_fim"].month: i["status"] for i in db.listar_importacoes(patch_conn, emp["id"])}
    assert sorted(sts.values()) == ["RASCUNHO", "REVISADA"]
    at3 = _importar(patch_conn, arqs)                      # a confirmada agora diz "Nada a fazer"; a outra ainda oferece confirmar
    assert any("Nada a fazer" in i.value for i in at3.info)
    assert len([b for b in at3.button if "como REVISADA" in b.label]) == 1


def test_importar_mesmo_arquivo_inativo_oferece_reativar_trocando(patch_conn):
    v1 = _Upload("jan_a.csv", csv_texto(MESES["2026-01"], cnpj=CNPJ, ini="01/01/2026", fim="31/01/2026"))
    outras = [dict(c) for c in MESES["2026-01"]]
    outras[0] = {**outras[0], "nome": outras[0]["nome"] + " (v2)"}
    v2 = _Upload("jan_b.csv", csv_texto(outras, cnpj=CNPJ, ini="01/01/2026", fim="31/01/2026"))
    at = _importar(patch_conn, [v1])
    with patch("streamlit.file_uploader", return_value=[v1]):
        [b for b in at.button if "Importar 1 arquivo" in b.label][0].click().run()
    emp = db.empresa_por_cnpj(patch_conn, CNPJ)
    at = _importar(patch_conn, [v2])                       # outro arquivo, mesmo periodo -> Substituir
    [c for c in at.checkbox if "Substituir" in c.label][0].check()
    with patch("streamlit.file_uploader", return_value=[v2]):
        at.run()
        [b for b in at.button if "Importar 1 arquivo" in b.label][0].click().run()
    imps = {i["arquivo_nome"]: i for i in db.listar_importacoes(patch_conn, emp["id"])}
    assert not imps["jan_a.csv"]["ativo"] and imps["jan_b.csv"]["ativo"]
    at = _importar(patch_conn, [v1])                       # o primeiro de volta: nao reimporta, oferece reativar
    assert any("hoje inativa" in i.value for i in at.info)
    assert not [b for b in at.button if "Importar" in b.label and "arquivo" in b.label]
    with patch("streamlit.file_uploader", return_value=[v1]):
        [b for b in at.button if "Usar este arquivo de novo" in b.label][0].click().run()
    assert not at.exception, at.exception
    imps = {i["arquivo_nome"]: i for i in db.listar_importacoes(patch_conn, emp["id"])}
    assert imps["jan_a.csv"]["ativo"] and not imps["jan_b.csv"]["ativo"] and len(imps) == 2      # troca, nada apagado
    with patch_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM balancete_linha WHERE importacao_id IN (%s,%s)", (imps["jan_a.csv"]["id"], imps["jan_b.csv"]["id"]))
        assert cur.fetchone()[0] > 0


def test_importar_cnpj_desconhecido_e_arquivo_invalido(patch_conn):
    db.garantir_empresa(patch_conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    desconhecido = _Upload("x.csv", csv_texto(MESES["2026-01"], cnpj="11.111.111/0001-11", ini="01/01/2026", fim="31/01/2026"))
    lixo = _Upload("lixo.csv", b"nada a ver")
    at = _importar(patch_conn, [desconhecido, lixo])
    erros = " ".join(e.value for e in at.error)
    assert "não está cadastrado" in erros and "Período" in erros
    assert not at.button


def test_importar_com_falha_exige_confirmacao(patch_conn):
    db.garantir_empresa(patch_conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    contas = [dict(c) for c in MESES["2026-01"]]
    for c in contas:
        if c["cl"] == "1.1.01.002.001":
            c["sal"] += 99.0
    arq = _Upload("ruim.csv", csv_texto(contas, cnpj=CNPJ, ini="01/01/2026", fim="31/01/2026"))
    at = _importar(patch_conn, [arq])
    assert any("com falha" in w.value for w in at.warning)
    assert not [b for b in at.button if "Importar" in b.label and "arquivo" in b.label]      # sem confirmar, nao importa
    at.checkbox[0].check()
    with patch("streamlit.file_uploader", return_value=[arq]):
        at.run()
    assert [b for b in at.button if "Importar 1 arquivo" in b.label]


def test_historico_mostra_periodo_do_acumulado_com_janeiro(patch_conn):
    """Acumulado deve aparecer como 01/01 a fim do mes (bug visto em producao: aparecia 01/08 a 31/08)."""
    emp_id = _semear(patch_conn, meses=(1, 2))
    cab, contas = I.ler_bytes(csv_texto(MESES["2026-02"], cnpj=CNPJ, ini="01/01/2026", fim="28/02/2026"), "acum.csv")
    db.inserir_importacao(patch_conn, emp_id, cab, contas, "seed", [])
    at = _app("3_Historico.py", patch_conn).run()
    assert not at.exception
    periodos = [str(v) for df in at.dataframe for v in df.value.get("Período", [])]
    assert "01/01/2026 a 28/02/2026" in periodos
    assert not any(p.startswith("01/02/2026 a") for p in periodos)


def test_importar_pdf_e_depois_csv_do_mesmo_periodo(patch_conn):
    """PDF e CSV entram pelo mesmo caminho; o 2o formato do mesmo periodo pede confirmacao para substituir (nada e' apagado)."""
    pdf = _Upload("01.2026 - Balancete.pdf", pdf_balancete(MESES["2026-01"], cnpj=CNPJ, ini="01/01/2026", fim="31/01/2026"))
    at = _importar(patch_conn, [pdf])
    assert not at.exception, at.exception
    assert any("PDF" in m.value and "mês isolado" in m.value for m in at.markdown)
    botao = [b for b in at.button if "Importar 1 arquivo" in b.label]
    assert botao, [b.label for b in at.button]
    with patch("streamlit.file_uploader", return_value=[pdf]):
        botao[0].click().run()
    emp = db.empresa_por_cnpj(patch_conn, CNPJ)
    assert db.listar_meses_ativos(patch_conn, emp["id"]) == ["2026-01"]
    csv = _Upload("01.csv", csv_texto(MESES["2026-01"], cnpj=CNPJ, ini="01/01/2026", fim="31/01/2026"))
    at2 = _importar(patch_conn, [csv])
    assert not at2.exception
    assert [c for c in at2.checkbox if "Substituir" in c.label]
    assert not [b for b in at2.button if "Importar" in b.label and "arquivo" in b.label]


def _semear_ate(conn, n=3):
    return _semear(conn, meses=tuple(range(1, n + 1)))


def test_demonstrativos_mostra_status_e_abas_novas(patch_conn):
    emp_id = _semear_ate(patch_conn)
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert not at.exception, at.exception
    assert any("RASCUNHO" in i.value and "Status dos balancetes" in i.value for i in at.info)
    assert [t.label for t in at.tabs] == ["Balanço Patrimonial", "DRE", "Indicadores", "Composição de Saldos", "Conferências"]
    imps = db.listar_importacoes(patch_conn, emp_id)
    for i in imps:
        db.definir_status(patch_conn, i["id"], "REVISADA", "t")
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert any("estão **REVISADA**" in s.value for s in at.success)


def test_gerar_pdf_registra_rascunho_e_oferece_download(patch_conn):
    emp_id = _semear_ate(patch_conn)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert not at.exception, at.exception
    botao = [b for b in at.button if b.label == "Gerar PDF (rascunho)"]
    assert botao and not botao[0].disabled
    botao[0].click().run()
    assert not at.exception, at.exception
    assert any("gerado e registrado como RASCUNHO" in s.value for s in at.success)
    rels = db.listar_relatorios(patch_conn, emp_id)
    assert len(rels) == 1 and rels[0]["status"] == "RASCUNHO" and rels[0]["versao"] == 1 and len(rels[0]["pdf_sha256"]) == 64
    at.button(key="pdf_gerar").click().run()                    # segunda geracao = versao 2
    assert [r["versao"] for r in db.listar_relatorios(patch_conn, emp_id)] == [2, 1]


def test_apelido_salvo_aparece_na_composicao(patch_conn):
    emp_id = _semear_ate(patch_conn)
    db.salvar_apelidos(patch_conn, emp_id, {"Acionista Gama Ltda": "Gama"}, "t")
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert not at.exception, at.exception
    assert any("Gama" in str(df.value.to_dict()) for df in at.dataframe)


def test_mapa_editar_linha_pela_tela(patch_conn):
    emp_id = _semear_ate(patch_conn, 1)
    at = _app("4_Mapa_de_Contas.py", patch_conn).run()
    assert not at.exception, at.exception
    at.selectbox(key="mapa_linha").set_value("fretes").run()
    at.text_input[0].set_value("(−) Fretes e transportes")
    at.text_input[2].set_value("teste de edição")
    [b for b in at.button if b.label == "Salvar alteração"][0].click().run()
    assert not at.exception, at.exception
    assert {m[0]: m for m in db.mapa_vigente(patch_conn, emp_id)}["fretes"][1] == "(−) Fretes e transportes"


def test_relatorio_pdf_sem_dados_e_sem_janeiro(patch_conn):
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert not at.exception and any("Ainda não há balancete" in i.value for i in at.info)
    _semear(patch_conn, meses=(2, 3))
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert not at.exception and any("falta o mês de janeiro" in w.value for w in at.warning)


def test_relatorio_pdf_troca_de_mes(patch_conn):
    _semear_ate(patch_conn)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert at.selectbox(key="pdf_mes").value == "2026-03"
    at.selectbox(key="pdf_mes").select("2026-02").run()
    assert not at.exception, at.exception


def test_painel_sem_dados_e_com_dados(patch_conn):
    at = _app("6_Painel.py", patch_conn).run()
    assert not at.exception and any("Ainda não há balancete" in i.value for i in at.info)
    _semear_ate(patch_conn)
    at = _app("6_Painel.py", patch_conn).run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Evolução", "Indicadores", "Tabela mensal", "Qualidade dos dados"]
    rotulos = [m.label for m in at.metric]
    assert "Caixa e aplicações" in rotulos and "Dívida líquida" in rotulos and len(rotulos) == 6
    caixa = [m for m in at.metric if m.label == "Caixa e aplicações"][0]
    assert caixa.value.startswith("R$ 1,0 mi") and caixa.delta is not None
    tabelas_ = [df.value for df in at.dataframe]
    assert any("Indicador" in t.columns and "Mar/26" in t.columns for t in tabelas_)


def test_painel_com_um_mes_so(patch_conn):
    _semear_ate(patch_conn, 1)
    at = _app("6_Painel.py", patch_conn).run()
    assert not at.exception, at.exception
    assert any("ainda não há mês anterior" in c.value for c in at.caption)


# ------------------------------------------------------------------ v0.4.0: ciclo do relatorio, ajuda, inicio, conexao
def _revisar_todas(conn, emp_id):
    for i in db.listar_importacoes(conn, emp_id):
        db.definir_status(conn, i["id"], "REVISADA", "t")


def test_versao_final_bloqueada_ate_revisar_e_ter_assinante(patch_conn):
    emp_id = _semear_ate(patch_conn)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert not at.exception, at.exception
    assert at.button(key="pdf_final").disabled
    texto = " ".join(m.value for m in at.markdown)
    assert "❌ Balancetes de janeiro a 03/2026 todos **REVISADA**" in texto and "faltam: 01/2026, 02/2026, 03/2026" in texto and "❌ Assinantes" in texto
    _revisar_todas(patch_conn, emp_id)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert at.button(key="pdf_final").disabled                                  # ainda sem nome de assinante
    db.salvar_config_empresa(patch_conn, emp_id, {"assinantes": [{"nome": "Fulano de Tal", "cargo": "Diretor"}, {"nome": "Beltrano", "cargo": "Contador"},
                                                                  {"nome": "Ciclana", "cargo": "Conselheira"}]}, "t")        # padrao salvo da empresa (3 assinantes)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    assert not at.button(key="pdf_final").disabled
    at.button(key="pdf_final").click().run()
    assert not at.exception, at.exception
    rels = db.listar_relatorios(patch_conn, emp_id)
    assert len(rels) == 1 and rels[0]["status"] == "REVISADO" and rels[0]["meta"]["importacoes"]
    assert any("VERSÃO FINAL" in s.value for s in at.success)


def test_relatorio_fica_desatualizado_quando_o_balancete_muda(patch_conn):
    emp_id = _semear_ate(patch_conn)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    at.button(key="pdf_gerar").click().run()
    tab = [d.value for d in at.dataframe if "Dados" in d.value.columns][0]
    assert tab.iloc[0]["Dados"] == "atuais"
    # o contador retifica marco: a importacao antiga fica inativa e entra outra (arquivo diferente)
    marco = [i for i in db.listar_importacoes(patch_conn, emp_id) if i["periodo_fim"].month == 3][0]
    contas = [dict(c) for c in MESES["2026-03"]]
    for c in contas:
        if c["cl"] == "1.1.01.002.001":
            c["sal"] += 5.0
    cab, lidas = I.ler_bytes(csv_texto(contas, cnpj=CNPJ, ini="01/03/2026", fim="31/03/2026"), "marco_retificado.csv")
    db.inserir_importacao(patch_conn, emp_id, cab, lidas, "t", [], substituir=True)
    assert marco["id"] not in db.ids_importacoes_mensais(patch_conn, emp_id, "2026-03")
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    tab = [d.value for d in at.dataframe if "Dados" in d.value.columns][0]
    assert tab.iloc[0]["Dados"].startswith("desatualizados")


def test_registrar_assinatura_regras(patch_conn):
    emp_id = _semear_ate(patch_conn)
    from datetime import date
    per = date(2026, 3, 1)
    r1, _ = db.registrar_relatorio(patch_conn, emp_id, per, "a" * 64, {}, [], "t")                      # rascunho
    r2, v2 = db.registrar_relatorio(patch_conn, emp_id, per, "b" * 64, {}, [], "t", status="REVISADO")
    assert v2 == 2
    with pytest.raises(db.AssinaturaInvalida, match="versão final"):
        db.registrar_assinatura(patch_conn, r1, "x.pdf", "c" * 64, "t")
    with pytest.raises(db.AssinaturaInvalida, match="idêntico"):
        db.registrar_assinatura(patch_conn, r2, "x.pdf", "b" * 64, "t")
    db.registrar_assinatura(patch_conn, r2, "assinado.pdf", "c" * 64, "t")
    rel = {r["id"]: r for r in db.listar_relatorios(patch_conn, emp_id)}
    assert rel[r2]["status"] == "ASSINADO" and rel[r2]["pdf_sha256"] == "b" * 64
    # sem trava: mesmo arquivo de novo -> avisa; outro arquivo -> substitui e o anterior vai para o historico
    with pytest.raises(db.AssinaturaInvalida, match="mesmo arquivo"):
        db.registrar_assinatura(patch_conn, r2, "assinado.pdf", "c" * 64, "t")
    assert [x["versao"] for x in db.assinaturas_registradas(patch_conn, emp_id, per)] == [2]
    db.registrar_assinatura(patch_conn, r2, "assinado_v2.pdf", "d" * 64, "t")
    with patch_conn.cursor() as cur:
        cur.execute("SELECT textos->'_assinatura'->>'arquivo', jsonb_array_length(textos->'_assinaturas_anteriores') FROM relatorio WHERE id=%s", (r2,))
        assert cur.fetchone() == ("assinado_v2.pdf", 1)
    db.desfazer_assinatura(patch_conn, r2, "t")
    rel = {r["id"]: r for r in db.listar_relatorios(patch_conn, emp_id)}
    assert rel[r2]["status"] == "REVISADO" and db.assinaturas_registradas(patch_conn, emp_id, per) == []
    with patch_conn.cursor() as cur:
        cur.execute("SELECT textos ? '_assinatura', jsonb_array_length(textos->'_assinaturas_anteriores') FROM relatorio WHERE id=%s", (r2,))
        assert cur.fetchone() == (False, 2)                       # nada se perde: os dois registros ficam guardados
    db.registrar_assinatura(patch_conn, r2, "assinado_v3.pdf", "e" * 64, "t")              # e da' para assinar de novo
    assert [x["arquivo"] for x in db.assinaturas_registradas(patch_conn, emp_id, per)] == ["assinado_v3.pdf"]
    db.definir_status_relatorio(patch_conn, r2, "RASCUNHO", "t")                           # sem trava: pode ate' voltar a rascunho
    assert {r["id"]: r for r in db.listar_relatorios(patch_conn, emp_id)}[r2]["status"] == "RASCUNHO"
    with pytest.raises(ValueError):
        db.registrar_relatorio(patch_conn, emp_id, per, "e" * 64, {}, [], "t", status="ASSINADO")


def test_ids_das_importacoes_usadas(patch_conn):
    emp_id = _semear_ate(patch_conn)
    ids = db.ids_importacoes_mensais(patch_conn, emp_id, "2026-02")
    todos = [i["id"] for i in db.listar_importacoes(patch_conn, emp_id) if i["periodo_fim"].month <= 2]
    assert ids == sorted(todos) and len(ids) == 2
    assert len(db.ids_importacoes_mensais(patch_conn, emp_id, "2026-03")) == 3 and db.ids_importacoes_mensais(patch_conn, emp_id, "2025-12") == []


def test_ajuda_e_inicio(patch_conn):
    at = _app("7_Ajuda.py", patch_conn).run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Fluxo do mês", "Quando algo não bate", "Glossário"]
    at.selectbox(key="ajuda_grupo").select("Mapa de contas").run()
    assert not at.exception and any("sem chave" in m.value or "Mapa de contas" in m.value for m in at.markdown)
    _semear_ate(patch_conn, 2)
    at = AppTest.from_file(str(APP / "app.py"), default_timeout=30)
    at.session_state["auth_session"] = SESSAO
    with patch("conexao.get_conn", return_value=patch_conn):
        at.run()
    assert not at.exception, at.exception
    assert any("Situação do ano" in s.value for s in at.subheader)
    assert any("Gere o relatório" in m.value or "REVISADA" in m.value for m in at.markdown)


def test_rodape_tem_versao_e_contato(patch_conn):
    import conexao
    at = _app("7_Ajuda.py", patch_conn).run()
    corpo = " ".join(m.value for m in at.sidebar.markdown)
    assert f"v{conexao.APP_VERSION}" in corpo and conexao.CONTATO in corpo


def test_conexao_viva_e_reabre(patch_conn):
    import conexao
    assert conexao.conexao_viva(patch_conn) is True and conexao.conexao_viva(None) is False
    assert conexao.conexao_viva(SimpleNamespace(closed=1)) is False                       # fechada
    quebrada = SimpleNamespace(closed=0, cursor=lambda: (_ for _ in ()).throw(RuntimeError("server closed the connection")))
    assert conexao.conexao_viva(quebrada) is False                                        # o banco derrubou a conexao ociosa


def test_historico_marcar_varios_como_revisada(patch_conn):
    emp_id = _semear_ate(patch_conn)
    at = _app("3_Historico.py", patch_conn).run()
    assert not at.exception, at.exception
    at.checkbox(key="hist_multi_ok").check().run()
    at.button(key="hist_multi_btn").click().run()
    assert not at.exception, at.exception
    assert {i["status"] for i in db.listar_importacoes(patch_conn, emp_id)} == {"REVISADA"}


def test_assinantes_padrao_da_empresa_persistem_e_vao_no_pdf(patch_conn):
    import io
    import pdfplumber
    emp_id = _semear_ate(patch_conn)
    _revisar_todas(patch_conn, emp_id)
    db.salvar_config_empresa(patch_conn, emp_id, {"assinantes": [{"nome": f"Pessoa {n}", "cargo": f"Cargo {n}"} for n in range(1, 6)]}, "t")
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    at.button(key="pdf_final").click().run()
    assert not at.exception, at.exception
    with pdfplumber.open(io.BytesIO(st_pdf(at))) as p:
        texto = p.pages[-1].extract_text()
    assert all(f"Pessoa {n}" in texto for n in range(1, 6)) and "assinatura digital dos responsáveis" in texto


def st_pdf(at):
    return at.session_state["pdf_pronto"]["bytes"]


def test_importar_com_confirmacao_entra_revisada_e_sem_confirmacao_rascunho(patch_conn):
    """v0.4.3: 'Revisei e confirmo' na propria tela de importar grava REVISADA (com o nome no log); sem marcar, fica RASCUNHO."""
    arqs = [_Upload(f"{m}.csv", csv_texto(MESES[f"2026-0{m}"], cnpj=CNPJ, ini=f"01/0{m}/2026", fim={1: "31", 2: "28", 3: "31"}[m] + f"/0{m}/2026")) for m in (1, 2)]
    at = _importar(patch_conn, arqs)
    assert not at.exception, at.exception
    caixas = [c for c in at.checkbox if "Revisei os números" in c.label]
    assert len(caixas) == 2 and not any(c.value for c in caixas)                      # nunca vem marcada de fabrica
    caixas[0].check()                                                                  # confirma so' o primeiro arquivo (janeiro)
    with patch("streamlit.file_uploader", return_value=arqs):
        at.run()
    botao = [b for b in at.button if "Importar 2 arquivo" in b.label]
    with patch("streamlit.file_uploader", return_value=arqs):
        botao[0].click().run()
    assert not at.exception
    emp = db.empresa_por_cnpj(patch_conn, CNPJ)
    st_ = {i["periodo_fim"].month: i["status"] for i in db.listar_importacoes(patch_conn, emp["id"])}
    assert st_ == {1: "REVISADA", 2: "RASCUNHO"}
    assert any("confirmado como REVISADA" in e["mensagem"] for e in db.listar_eventos(patch_conn, emp["id"]))


def test_relatorio_fica_desatualizado_quando_o_mapa_muda(patch_conn):
    """v0.4.5: editar o mapa de contas (ou um apelido) muda o relatorio sem mudar nenhum balancete; a lista precisa avisar."""
    emp_id = _semear_ate(patch_conn)
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    at.button(key="pdf_gerar").click().run()
    tab = [d.value for d in at.dataframe if "Dados" in d.value.columns][0]
    assert tab.iloc[0]["Dados"] == "atuais"
    db.salvar_mapa_linha(patch_conn, emp_id, "dep_vista", "Depósitos bancários à vista", ["1.1.01.002"], None, "t", "teste de mapa")
    at = _app("5_Relatorio_PDF.py", patch_conn).run()
    tab = [d.value for d in at.dataframe if "Dados" in d.value.columns][0]
    assert tab.iloc[0]["Dados"].startswith("desatualizados") and "mapa" in tab.iloc[0]["Dados"]
    at.button(key="pdf_gerar").click().run()                                           # gerar de novo volta a "atuais" na versao nova
    tab = [d.value for d in at.dataframe if "Dados" in d.value.columns][0]
    assert tab.iloc[0]["Dados"] == "atuais" and tab.iloc[1]["Dados"].startswith("desatualizados")


def test_historico_mesma_sessao_rotulos_acompanham_o_status(patch_conn):
    """v0.4.5 (bug visto ao vivo): na MESMA sessao (como no navegador) o botao nao pode ficar um passo atras do status."""
    emp_id = _semear(patch_conn, meses=(1, 2))
    at = _app("3_Historico.py", patch_conn).run()
    assert at.button(key="hist_status").label == "Marcar como revisada"
    at.button(key="hist_status").click().run()
    assert at.button(key="hist_status").label == "Marcar como rascunho"                  # acompanha o novo status
    at.button(key="hist_status").click().run()
    assert at.button(key="hist_status").label == "Marcar como revisada"
    assert {i["status"] for i in db.listar_importacoes(patch_conn, emp_id) if i["periodo_fim"].month == 2} == {"RASCUNHO"}
    # desfazer -> o mesmo seletor passa a oferecer "Reativar" na hora
    at.button(key="hist_desfazer").click().run()
    assert at.button(key="hist_reativar") is not None and not [b for b in at.button if b.key == "hist_desfazer"]
    at.button(key="hist_reativar").click().run()
    assert [b for b in at.button if b.key == "hist_desfazer"]


def test_mapa_mesma_sessao_formulario_mostra_o_valor_novo_apos_salvar(patch_conn):
    emp_id = _semear_ate(patch_conn, 1)
    at = _app("4_Mapa_de_Contas.py", patch_conn).run()
    at.selectbox(key="mapa_linha").set_value("fretes").run()
    at.text_input[0].set_value("(−) Fretes e transportes")
    at.text_input[2].set_value("teste de edição")
    [b for b in at.button if b.label == "Salvar alteração"][0].click().run()
    assert not at.exception, at.exception
    assert at.selectbox(key="mapa_linha").value == "fretes"
    assert at.text_input[0].value == "(−) Fretes e transportes"                           # o formulario ja mostra a linha nova, nao a antiga


def test_historico_a_selecao_nao_pula_para_outra_importacao_apos_editar(patch_conn):
    """v0.4.5: editar a importacao escolhida (nao a primeira da lista) nao pode trocar a selecao para outra linha."""
    emp_id = _semear(patch_conn, meses=(1, 2, 3))
    ids = sorted(i["id"] for i in db.listar_importacoes(patch_conn, emp_id))
    alvo = ids[0]                                                                        # janeiro (ultima linha da tabela)
    at = _app("3_Historico.py", patch_conn).run()
    at.selectbox(key="hist_escolha").set_value(alvo).run()
    at.button(key="hist_status").click().run()
    assert at.selectbox(key="hist_escolha").value == alvo
    st_ = {i["id"]: i["status"] for i in db.listar_importacoes(patch_conn, emp_id)}
    assert st_[alvo] == "REVISADA" and all(st_[n] == "RASCUNHO" for n in ids[1:])      # so' a escolhida mudou
    at.button(key="hist_desfazer").click().run()
    assert at.selectbox(key="hist_escolha").value == alvo and [b for b in at.button if b.key == "hist_reativar"]


# ---------------------------------------------------------------- v0.4.8: assinatura opcional e sem trava + avisos
def test_importar_substituir_mes_validado_avisa_e_lista_relatorios_afetados(patch_conn):
    from datetime import date
    emp_id = _semear_ate(patch_conn)
    for i in db.listar_importacoes(patch_conn, emp_id):
        db.definir_status(patch_conn, i["id"], "REVISADA", "t")
    db.registrar_relatorio(patch_conn, emp_id, date(2026, 3, 1), "a" * 64, {}, [], "t", status="REVISADO")
    contas = [dict(c) for c in MESES["2026-02"]]
    contas[0] = {**contas[0], "nome": contas[0]["nome"] + " (novo)"}
    novo = _Upload("fev_novo.csv", csv_texto(contas, cnpj=CNPJ, ini="01/02/2026", fim="28/02/2026"))
    at = _importar(patch_conn, [novo])
    assert not at.exception, at.exception
    avisos = " ".join(w.value for w in at.warning)
    assert "já está **validado**" in avisos and "03/2026 v1 REVISADO" in avisos and "desatualizados" in avisos
    assert [c for c in at.checkbox if "Substituir" in c.label]


def test_tela_assinatura_opcional_sem_trava(patch_conn):
    from datetime import date
    emp_id = _semear_ate(patch_conn)
    rid, _ = db.registrar_relatorio(patch_conn, emp_id, date(2026, 3, 1), "b" * 64, {}, [], "t", status="REVISADO")
    db.registrar_assinatura(patch_conn, rid, "primeiro.pdf", "c" * 64, "t")
    pdf2 = _Upload("segundo.pdf", b"%PDF-1.4 /ByteRange [0 1 2 3] segundo")
    at = _app("5_Relatorio_PDF.py", patch_conn)
    with patch("streamlit.file_uploader", return_value=pdf2):
        at.run()
        assert not at.exception, at.exception
        textos = " ".join(i.value for i in at.info) + " " + " ".join(w.value for w in at.warning)
        assert "Já há PDF assinado registrado" in textos and "substitui o registro anterior" in textos
        assert [b for b in at.button if "Desfazer o registro" in b.label]
        at.button(key="ass_registrar").click().run()
    assert not at.exception, at.exception
    assert [x["arquivo"] for x in db.assinaturas_registradas(patch_conn, emp_id, date(2026, 3, 1))] == ["segundo.pdf"]
    at = _app("5_Relatorio_PDF.py", patch_conn)
    with patch("streamlit.file_uploader", return_value=None):
        at.run()
        at.button(key="ass_desfazer").click().run()
    assert {r["id"]: r for r in db.listar_relatorios(patch_conn, emp_id)}[rid]["status"] == "REVISADO"
