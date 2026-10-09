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
    assert len(at.tabs) == 6 and len(at.dataframe) >= 4
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
    # reenviar os mesmos arquivos: avisa que ja' foram importados e nao oferece importar de novo
    at2 = _importar(patch_conn, arqs)
    assert any("já foi importado" in i.value for i in at2.info)
    assert not [b for b in at2.button if "Importar" in b.label and "arquivo" in b.label]


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
    assert [t.label for t in at.tabs] == ["Balanço Patrimonial", "DRE", "Indicadores", "Composição de Saldos", "Conferências", "Relatório PDF"]
    imps = db.listar_importacoes(patch_conn, emp_id)
    for i in imps:
        db.definir_status(patch_conn, i["id"], "REVISADA", "t")
    at = _app("2_Demonstrativos.py", patch_conn).run()
    assert any("estão **REVISADA**" in s.value for s in at.success)


def test_gerar_pdf_registra_rascunho_e_oferece_download(patch_conn):
    emp_id = _semear_ate(patch_conn)
    at = _app("2_Demonstrativos.py", patch_conn).run()
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
    at.selectbox(key="mapa_linha").set_value([m for m in db.mapa_vigente(patch_conn, emp_id) if m[0] == "fretes"][0]).run()
    at.text_input[0].set_value("(−) Fretes e transportes")
    at.text_input[2].set_value("teste de edição")
    [b for b in at.button if b.label == "Salvar alteração"][0].click().run()
    assert not at.exception, at.exception
    assert {m[0]: m for m in db.mapa_vigente(patch_conn, emp_id)}["fretes"][1] == "(−) Fretes e transportes"
