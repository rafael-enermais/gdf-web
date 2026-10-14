# -*- coding: utf-8 -*-
"""V2 Painel EnerMais: gravacao do Sienge (dados SINTETICOS) + regras + conferencia com CSV, contra Postgres descartavel."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import painel_db as P
import sienge_api as S
from dados_sienge import income, movimentos_banco, outcome

pytestmark = pytest.mark.pg
APP = Path(__file__).resolve().parent.parent
PREF = ["2.01.02", "2.02.01", "2.04.02", "1.03.02.02"]


def _ingerir(conn, regs=None, lado="P", tipo="P", mes="2026-09"):
    sid = P.criar_sync(conn, mes, lado, tipo, "teste@x")
    cont = P.gravar_normalizado(conn, sid, S.normalizar_titulos(lado, regs if regs is not None else outcome()))
    P.finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    return sid, cont


def _contar(conn, tab):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {tab}")
        return cur.fetchone()[0]


def test_v2_instalado_e_regras_iniciais(conn):
    assert P.v2_instalado(conn)
    assert set(P.prefixos_excluidos(P.regras_ativas(conn, "DESPESAS"))) == set(PREF)


def test_regra_previsao_nasce_proposta_e_confirma(conn):
    assert P.garantir_regras_padrao(conn) == 1                       # cria EXCLUI_PREVISAO
    assert P.garantir_regras_padrao(conn) == 0                       # segunda vez nao duplica
    regras = P.regras_ativas(conn, "DESPESAS")
    assert P.exclui_previsao(regras)
    prev = next(r for r in regras if r["tipo"] == "EXCLUI_PREVISAO")
    assert prev["status"] == "PROPOSTA"
    assert P.confirmar_regras(conn, [prev["id"]], "teste@x") == 1
    assert P.confirmar_regras(conn, [prev["id"]], "teste@x") == 0    # ja confirmada
    assert next(r for r in P.regras_ativas(conn, "DESPESAS") if r["tipo"] == "EXCLUI_PREVISAO")["status"] == "CONFIRMADA"
    assert P.confirmar_regras(conn, [], "teste@x") == 0


def test_despesas_sem_documentos_de_previsao(conn):
    regs = outcome()
    regs[0]["forecastDocument"] = "S"                                # o titulo 1 (material + combustivel) vira previsao
    _ingerir(conn, regs)
    com = {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", PREF)}
    assert com == {"2.01.01.04": 600.0, "2.01.04.04": 400.0}         # sem a regra a previsao entra
    sem = P.despesas_do_mes(conn, "2026-09", PREF, sem_previsao=True)
    assert sem == []                                                 # com a regra sai
    ago = P.despesas_do_mes(conn, "2026-08", PREF, sem_previsao=True)
    assert [(l["plano_cod"], l["valor"]) for l in ago] == [("2.01.01.04", 700.0)]   # titulo sem marca (nulo) nao e' previsao


def test_movimento_bancario_entra_nas_despesas(conn):
    _ingerir(conn)
    antes = {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", PREF)}
    r = P.sincronizar_banco(conn, None, "2026-09", "teste@x", buscar=lambda c, m, mes_fim=None: movimentos_banco())
    assert r["ok"] and (r["titulos"], r["baixas"], r["rateios"], r["liquido"]) == (2, 2, 3, 1100.0)
    depois = {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", PREF)}
    assert depois["2.03.01.02"] == 100.0 and depois["2.03.01.04"] == 600.0 and depois["2.03.04.09"] == 400.0
    assert {k: v for k, v in depois.items() if k in antes} == antes                  # o que ja existia nao mudou
    assert any(d["doc_id"] == "AV" and d["origem"] == "BC" for d in P.documentos_do_mes(conn, "2026-09"))
    P.sincronizar_banco(conn, None, "2026-09", "teste@x", buscar=lambda c, m, mes_fim=None: movimentos_banco())   # de novo: nao duplica
    assert {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", PREF)} == depois
    com_prev = P.despesas_do_mes(conn, "2026-09", PREF, sem_previsao=True)           # AV tem previsao N: a regra de previsao nao tira
    assert {l["plano_cod"]: l["valor"] for l in com_prev}["2.03.01.02"] == 100.0


def test_movimento_bancario_com_erro_registra_e_nao_derruba(conn):
    def falha(c, m, mes_fim=None):
        raise RuntimeError("Sienge respondeu HTTP 500")
    r = P.sincronizar_banco(conn, None, "2026-09", "teste@x", buscar=falha)
    assert r == {"ok": False, "erro": "Sienge respondeu HTTP 500"}
    assert P.ultimas_syncs(conn, 1)[0]["tipo_data"] == "M" and P.ultimas_syncs(conn, 1)[0]["status"] == "ERRO"


def test_ingestao_e_idempotencia(conn):
    _, cont = _ingerir(conn)
    assert cont == {"titulos": 4, "baixas": 5, "rateios": 5, "liquido": 2550.0}
    _ingerir(conn)                                   # mesma busca de novo: nao duplica
    assert (_contar(conn, "pnl_titulo"), _contar(conn, "pnl_baixa"), _contar(conn, "pnl_rateio")) == (4, 5, 5)
    assert _contar(conn, "pnl_sync") == 2


def test_despesas_do_mes_aplica_regras(conn):
    _ingerir(conn)
    linhas = P.despesas_do_mes(conn, "2026-09", PREF)
    assert {l["plano_cod"]: l["valor"] for l in linhas} == {"2.01.01.04": 600.0, "2.01.04.04": 400.0}
    assert linhas[0]["plano_cod"] == "2.01.01.04"                     # ordenado do maior para o menor
    sem_regra = {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", [])}
    assert sem_regra["2.01.02.01"] == 500.0 and sem_regra["1.03.02.02"] == 350.0   # soma o liquido como vem (300 pagamento + 50 cancelamento); o filtro de operacao serve p/ tirar tipos
    sem_canc = {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", [], tipo_oper_fora=[3])}
    assert sem_canc["1.03.02.02"] == 300.0
    fora = P.despesas_do_mes(conn, "2026-09", PREF, doc_fora=["NFS"])
    assert fora == []
    ago = P.despesas_do_mes(conn, "2026-08", PREF)
    assert [(l["plano_cod"], l["valor"]) for l in ago] == [("2.01.01.04", 700.0)]


def test_view_esconde_rateio_antigo(conn):
    _ingerir(conn)
    novo = outcome()
    novo[0]["paymentsCategories"] = novo[0]["paymentsCategories"][:1]
    novo[0]["paymentsCategories"][0]["financialCategoryRate"] = 100
    _ingerir(conn, novo)                              # o titulo 1 agora tem 1 so' rateio
    assert _contar(conn, "pnl_rateio") == 5           # a linha antiga continua guardada (nada se apaga)...
    linhas = {l["plano_cod"]: l["valor"] for l in P.despesas_do_mes(conn, "2026-09", PREF)}
    assert linhas == {"2.01.01.04": 1000.0}           # ...mas a leitura so' enxerga a ultima sincronizacao


def test_receber_e_cadastros(conn):
    _, cont = _ingerir(conn, income(), lado="R")
    assert cont["titulos"] == 1 and cont["baixas"] == 1 and cont["rateios"] == 1 and cont["liquido"] == 1800.0
    cad = S.normalizar_cadastros({"empresas": [{"id": 5, "name": "CONSTRUTORA", "cnpj": "00"}],
                                  "centros_custo": [{"id": 1049, "name": "CON - X", "idCompany": 5}],
                                  "plano": [{"id": 2010104, "name": "Material", "tpConta": "D", "flRedutora": "N", "flAtiva": "S"}],
                                  "tipos_negocio": [{"businessTypeId": 10, "description": "OBRAS"}]})
    assert P.gravar_cadastros(conn, cad) == {"empresas": 1, "centros_custo": 1, "plano": 1, "tipos_negocio": 1}
    P.gravar_cadastros(conn, cad)
    assert _contar(conn, "pnl_plano_conta") == 1


def test_sincronizar_mes_com_erro_registrado(conn):
    def buscar(cli, lado, mes, tipo):
        if lado == "R":
            raise S.ErroSienge("Sienge respondeu HTTP 403 (sem permissao)")
        return outcome()
    res = P.sincronizar_mes(conn, None, "2026-09", "teste@x", lados=("P", "R"), tipos=("P",), buscar=buscar)
    assert [r["ok"] for r in res] == [True, False] and "403" in res[1]["erro"]
    st = {s["lado"]: s["status"] for s in P.ultimas_syncs(conn)}
    assert st == {"P": "OK", "R": "ERRO"}


CSV = ("Código plano fin;Desc plano fin;Valor aprop fin;Outra\n"
       "2.01.01.04;Material de Consumo | Obra;600,00;x\n"
       "2.01.04.04;Combustível | Obra;350,00;x\n"
       "2.01.02.01;Salários PJ | Obra;500,00;x\n").encode("utf-8")


def test_conferencia_com_csv(conn):
    _ingerir(conn)
    linhas = P.despesas_do_mes(conn, "2026-09", PREF)
    res = P.despesas_do_csv(CSV, PREF)
    assert res["total_bruto"] == 1450.0 and res["total_despesas"] == 950.0 and res["linhas"] == 3
    cmp = P.comparar_despesas(linhas, res)
    assert cmp["total_api"] == 1000.0 and cmp["total_csv"] == 950.0
    assert [(d["plano_cod"], d["dif"]) for d in cmp["contas_com_diferenca"]] == [("2.01.04.04", 50.0)]
    assert res["mes_dominante"] is None                                  # este CSV de teste nao tem Data pagamento
    assert [(c["plano_cod"], c["api"], c["csv"], c["dif"]) for c in cmp["contas"]] == [("2.01.01.04", 600.0, 600.0, 0.0), ("2.01.04.04", 400.0, 350.0, 50.0)]
    txt = P.csv_conferencia(cmp, "2026-09").decode("utf-8-sig").splitlines()
    assert txt[0].startswith("mes;conta;nome") and txt[1].endswith("600,00;600,00;0,00;sim") and txt[2].endswith("400,00;350,00;50,00;nao")
    assert txt[-1] == "2026-09;TOTAL;;1000,00;950,00;50,00;nao"
    res2 = P.despesas_do_csv(("Código plano fin;Desc plano fin;Valor aprop fin;Data pagamento\n"
                              "2.01.01.04;Material;10,00;2026-09-03\n2.01.01.04;Material;5,00;2026-09-20\n2.01.01.04;Material;1,00;2026-10-01\n").encode("utf-8"), PREF)
    assert res2["meses"] == {"2026-09": 2, "2026-10": 1} and res2["mes_dominante"] == "2026-09"
    with pytest.raises(ValueError):
        P.despesas_do_csv(b"a;b\n1;2\n", PREF)


# ------------------------------------------------------------------ tela
SESSAO = SimpleNamespace(user=SimpleNamespace(email="usuaria@teste"))


def _tela(conn):
    at = AppTest.from_file(str(APP / "telas" / "8_Painel_EnerMais.py"), default_timeout=30)
    at.session_state["auth_session"] = SESSAO
    return at


def test_tela_sem_v2_instalado_avisa(conn):
    with patch("conexao.get_conn", return_value=conn), patch("painel_db.v2_instalado", return_value=False):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    assert any("ainda não foram criadas" in w.value for w in at.warning) and len(at.tabs) == 0


def test_tela_com_dados_mostra_despesas(conn):
    _ingerir(conn)
    with patch("conexao.get_conn", return_value=conn):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert len(at.tabs) == 6
        assert at.selectbox(key="pn2_mes_desp").value == "2026-09"
        valores = [m.value for m in at.metric]
        assert any("1.000,00" in v for v in valores)


def test_tela_sem_secrets_mostra_erro_amigavel(conn, monkeypatch):
    monkeypatch.delenv("SIENGE_USER", raising=False)
    monkeypatch.delenv("SIENGE_PASSWORD", raising=False)
    with patch("conexao.get_conn", return_value=conn):
        at = _tela(conn).run()
        at.button(key="pn2_btn_sync").click().run()
    assert not at.exception, at.exception
    assert any("SIENGE_USER" in e.value for e in at.error)


def test_documentos_do_mes_e_meses_com_dados(conn):
    sid = P.criar_sync(conn, "2026-08", "P", "P", "teste")
    P.gravar_normalizado(conn, sid, S.normalizar_titulos("P", outcome()))
    P.finalizar_sync(conn, sid, "OK")
    docs = P.documentos_do_mes(conn, "2026-08")
    assert docs and {"doc_id", "doc_nome", "origem", "previsao", "tipo_oper", "titulos", "baixas", "liquido"} <= set(docs[0])
    assert all(isinstance(d["liquido"], float) for d in docs)
    assert P.meses_com_dados(conn) == sorted(P.meses_com_dados(conn))


# ------------------------------------------------------------------ logs
def test_log_registra_lista_e_exporta(conn):
    assert P.log_instalado(conn)
    assert P.registrar_log(conn, "CONFERENCIA_DESPESAS", "AVISO", "teste@x", "2026-09", {"total_api": 10.5, "arquivo": "a;b.csv"})
    assert P.registrar_log(conn, "SYNC_ERRO", "ERRO", None, None, {"erro": "HTTP 429"})
    todos = P.ultimos_logs(conn)
    assert [l["acao"] for l in todos] == ["SYNC_ERRO", "CONFERENCIA_DESPESAS"]          # mais recente primeiro
    assert todos[1]["detalhe"]["total_api"] == 10.5 and todos[1]["mes"].strftime("%Y-%m") == "2026-09"
    assert [l["acao"] for l in P.ultimos_logs(conn, nivel="ERRO")] == ["SYNC_ERRO"]
    assert [l["acao"] for l in P.ultimos_logs(conn, acao="CONFERENCIA_DESPESAS")] == ["CONFERENCIA_DESPESAS"]
    txt = P.csv_logs(todos).decode("utf-8-sig").splitlines()
    assert txt[0] == "quando;usuario;nivel;acao;mes;detalhe" and len(txt) == 3 and txt[2].count(";") == 5


def test_log_nunca_derruba_a_tela():
    class Quebrada:
        def cursor(self):
            raise RuntimeError("sem tabela")
    assert P.registrar_log(Quebrada(), "X") is False
    assert P.ultimos_logs(Quebrada()) == [] and P.log_instalado(Quebrada()) is False


def test_regra_confirmada_e_sync_gravam_log(conn):
    P.garantir_regras_padrao(conn)
    ids = [r["id"] for r in P.regras_ativas(conn, "DESPESAS")]
    P.confirmar_regras(conn, ids, "suellen@x")
    assert any(l["acao"] == "REGRA_CONFIRMADA" and l["usuario"] == "suellen@x" for l in P.ultimos_logs(conn))
    def falha(c, l, m, t):
        raise RuntimeError("boom")
    P.sincronizar_mes(conn, None, "2026-09", "u@x", lados=("P",), tipos=("P",), buscar=falha)
    P.sincronizar_mes(conn, None, "2026-09", "u@x", lados=("P",), tipos=("I",), buscar=lambda c, l, m, t: outcome())
    acoes = [l["acao"] for l in P.ultimos_logs(conn)]
    assert "SYNC_ERRO" in acoes and "SYNC_OK" in acoes


def test_tela_historico_e_mes_do_csv_automatico(conn):
    _ingerir(conn)                                      # API: 2026-09 com 1000,00 nas 2 contas de teste
    csv_set = ("Código plano fin;Desc plano fin;Valor aprop fin;Data pagamento\n"
               "2.01.01.04;Material;600,00;2026-09-03\n2.01.04.04;Outros;350,00;2026-09-20\n").encode("utf-8")
    falso = SimpleNamespace(name="ExportacaoContasPagas.csv", getvalue=lambda: csv_set)
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", return_value=falso):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert at.tabs[5].label == "Histórico e logs"
        cmp_sel = [sb for sb in at.selectbox if sb.key and sb.key.startswith("pn2_mes_cmp_")][0]
        assert cmp_sel.value == "2026-09"                                       # mes lido do CSV
        tabelas = [df.value for df in at.tabs[1].dataframe]
        assert any("Confere" in df.columns and len(df) == 2 for df in tabelas)  # tabela por conta aparece mesmo
        logs = P.ultimos_logs(conn, acao="CONFERENCIA_DESPESAS")
        assert len(logs) == 1 and logs[0]["detalhe"]["resultado"] == "difere" and logs[0]["detalhe"]["mes_lido_do_csv"] == "2026-09"
        at.run()                                                                # nova execucao nao duplica o log
        assert len(P.ultimos_logs(conn, acao="CONFERENCIA_DESPESAS")) == 1
        at = _tela(conn).run()
        assert any("CONFERENCIA_DESPESAS" in set(df.value["Ação"]) for df in at.tabs[5].dataframe)


# ------------------------------------------------------------------ Resultado (DRE comprometido por emissao)
def test_resultado_por_emissao_e_dre(conn):
    regs = outcome()
    regs[3]["forecastDocument"] = "S"                      # o titulo de agosto vira documento de previsao
    _ingerir(conn, regs=regs, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    assert P.meses_com_emissao(conn) == ["2026-08", "2026-09"]
    contas = {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09")}
    assert contas == {"1.01.01.01": 2000.0, "2.01.02.01": -500.0, "1.03.02.02": -300.0}       # agosto fora; custo negativo; receita positiva
    assert {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-08")} == {"2.01.01.04": -1000.0 * 0.6 - 700.0, "2.01.04.04": -400.0}
    dre = P.dre_do_mes(P.resultado_por_conta(conn, "2026-09"))
    v = dre["valores"]
    assert v["01"] == 2000.0 and v["04.01"] == -500.0 and v["04"] == -500.0 and v["05"] == 1500.0 and v["14"] == 1500.0
    assert [c["plano_cod"] for c in dre["fora_do_mapa"]] == ["1.03.02.02"]
    # previsao fora (documento PCT emitido em agosto)
    ago = {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-08", sem_previsao=True)}
    assert ago == {"2.01.01.04": -600.0, "2.01.04.04": -400.0}


def test_resultado_referencia_e_comparacao(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    contas = P.resultado_por_conta(conn, "2026-09")
    ref = P.ler_referencia_dre("conta;nome;linha_dre;total_set_2026\n1.01.01.01;Receitas;01.01;2000,00\n2.01.02.01;Sal;04.01;-450,00\n".encode("utf-8-sig"))
    assert ref == {"1.01.01.01": 2000.0, "2.01.02.01": -450.0}
    cmp = P.comparar_resultado(contas, ref)
    assert [(d["plano_cod"], d["dif"]) for d in cmp["contas_com_diferenca"]][:2] == [("1.03.02.02", -300.0), ("2.01.02.01", -50.0)]
    with pytest.raises(ValueError):
        P.ler_referencia_dre(b"a;b\n1;2\n")


def test_tela_resultado_mostra_dre_e_confere(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    csv_ref = "conta;nome;linha_dre;total_set_2026\n1.01.01.01;Receitas;01.01;2000,00\n2.01.02.01;Sal;04.01;-500,00\n1.03.02.02;Transf;;-300,00\n".encode("utf-8-sig")
    falso = SimpleNamespace(name="ref.csv", getvalue=lambda: csv_ref)
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", return_value=falso):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert at.selectbox(key="pn2_mes_res").value == "2026-09"
        assert any("2.000,00" in m.value for m in at.tabs[2].metric)
        assert any(l["acao"] == "CONFERENCIA_RESULTADO" for l in P.ultimos_logs(conn))


def test_resultado_so_obras_usa_o_de_para(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    assert not P.centro_grupo_instalado(conn)                                   # tabela existe mas ainda sem dados
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra) VALUES (1,'SEDE','ADM','ADM'),(1049,'ANASTACIO','OBRA','103')")
    assert P.centro_grupo_instalado(conn)
    todas = {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09")}
    obras = {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09", so_obras=True)}
    assert todas["2.01.02.01"] == -500.0 and obras == {"1.01.01.01": 2000.0}   # custo no centro ADM sai; receita no centro de obra fica
    pc = P.resultado_por_centro(conn, "2026-09")
    assert {(a["centro_id"], a["grupo"]) for a in pc} == {(1049, "OBRA"), (1, "ADM")}
    assert [a["receita"] for a in pc if a["centro_id"] == 1049] == [2000.0] and [a["custo"] for a in pc if a["centro_id"] == 1] == [-500.0]


# ------------------------------------------------------------------ DRE oficial lido do PDF (PDF sintetico)
def _pdf_lido(com_total_errado=False):
    from dre_pdf_sintetico import pdf_sintetico
    import importador_dre
    b = pdf_sintetico(com_total_errado)
    return b, importador_dre.ler_dre_pdf(b)


def test_gravar_dre_ativa_repetido_e_consultas(conn):
    import hashlib
    assert P.dre_instalado(conn) and P.meses_com_dre(conn) == []
    b, dre = _pdf_lido()
    sha = hashlib.sha256(b).hexdigest()
    r = P.gravar_dre(conn, dre, "dre_set.pdf", sha, "teste@x")
    assert r["repetido"] is False and r["mes"] == "2026-09" and P.meses_com_dre(conn) == ["2026-09"]
    assert _contar(conn, "pnl_dre_valor") == len(dre["valores"])
    imp = P.dre_importacao_ativa(conn, "2026-09")
    assert imp["arquivo"] == "dre_set.pdf" and imp["quem"] == "teste@x" and imp["id"] == r["id"]
    contas = P.dre_contas_importadas(conn, imp["id"])
    assert contas["1.01.01.01"] == 1750.0 and contas["2.01.02.01"] == -250.0 and contas["2.01.02.02"] == -350.0
    obras = P.dre_por_obra_importado(conn, imp["id"])
    assert obras["101"]["linhas"]["01"] == 500.0 and obras["101"]["linhas"]["04"] == -200.0 and obras["100"]["nome"] == "OBRA UM"
    # mesmo arquivo de novo: nao duplica
    r2 = P.gravar_dre(conn, dre, "dre_set.pdf", sha, "teste@x")
    assert r2["repetido"] is True and _contar(conn, "pnl_dre_valor") == len(dre["valores"])
    # arquivo diferente do mesmo mes: o novo vira o ativo, o antigo fica guardado como inativo
    r3 = P.gravar_dre(conn, dre, "dre_set_v2.pdf", "f" * 64, "teste@x")
    assert r3["repetido"] is False and P.dre_importacao_ativa(conn, "2026-09")["id"] == r3["id"]
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pnl_importacao WHERE tipo='DRE' AND NOT ativo")
        assert cur.fetchone()[0] == 1
    assert {l["acao"] for l in P.ultimos_logs(conn)} >= {"DRE_PDF_IMPORTADO"}


def test_gravar_dre_sem_periodo_nao_grava(conn):
    _, dre = _pdf_lido()
    dre["periodo"] = {}
    with pytest.raises(ValueError, match="período"):
        P.gravar_dre(conn, dre, "x.pdf", "a" * 64, None)
    assert _contar(conn, "pnl_dre_valor") == 0


def test_resultado_por_obra_api_usa_o_de_para(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    assert P.resultado_por_obra_api(conn, "2026-09") == {} or isinstance(P.resultado_por_obra_api(conn, "2026-09"), dict)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra) VALUES (1,'SEDE','ADM','ADM'),(1049,'ANASTACIO','OBRA','103')")
    r = P.resultado_por_obra_api(conn, "2026-09")
    assert r["103"]["01"] == 2000.0


def _uploader_por_chave(arquivos):
    """Substitui st.file_uploader: devolve o arquivo falso conforme a chave (key) do campo; sem arquivo -> None."""
    def _f(*a, **kw):
        return arquivos.get(kw.get("key"))
    return _f


def test_tela_resultado_importa_pdf_e_confere_com_a_api(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, _ = _pdf_lido()
    falso = SimpleNamespace(name="dre.pdf", getvalue=lambda: b)
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({"pn2_pdf_dre": falso})):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert any("PDF lido" in s.value for s in at.tabs[2].success)
        at.button(key="pn2_pdf_salvar").click().run()
        assert not at.exception, at.exception
        assert P.meses_com_dre(conn) == ["2026-09"]
        at.run()
        assert not at.exception, at.exception
        assert any("DRE oficial de 2026-09" in c.value for c in at.tabs[2].caption)
        assert any(l["acao"] == "CONFERENCIA_RESULTADO" and l["detalhe"].get("referencia") == "PDF" for l in P.ultimos_logs(conn))


def test_tela_resultado_pdf_invalido_mostra_erro_e_registra_log(conn):
    falso = SimpleNamespace(name="x.pdf", getvalue=lambda: b"nao e pdf")
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({"pn2_pdf_dre": falso})):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    assert any("PDF" in e.value for e in at.tabs[2].error)
    assert any(l["acao"] == "DRE_PDF_ERRO" for l in P.ultimos_logs(conn))


# ------------------------------------------------------------------ descontos das baixas e confirmacao do DRE (fonte por linha)
def test_dre_de_folhas_formulas():
    r = P.dre_de_folhas({"01.01": 1000.0, "02.01": -10.0, "02.02": -90.0, "04.01": -300.0, "04.02": -100.0, "06.04": -50.0, "08.02": 5.0, "10.01": -20.0, "12.01": -10.0})
    v = r["valores"]
    assert v["01"] == 1000.0 and v["02"] == -100.0 and v["03"] == 900.0 and v["04"] == -400.0 and v["05"] == 500.0
    assert v["07"] == 450.0 and v["11"] == 435.0 and v["14"] == 425.0 and dict((k, x) for k, _, x in r["linhas"])["14"] == 425.0


def test_descontos_das_baixas_entram_como_conta_1_01_03_01(conn):
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    assert "1.01.03.01" not in {c["plano_cod"] for c in P.resultado_por_conta(conn, "2026-09")}          # sem desconto, nada aparece
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_baixa SET desconto = 125.50 WHERE lado='R'")
    c = {x["plano_cod"]: x["valor"] for x in P.resultado_por_conta(conn, "2026-09")}
    assert c["1.01.03.01"] == -125.50
    v = P.dre_do_mes(P.resultado_por_conta(conn, "2026-09"))["valores"]
    assert v["02.01"] == -125.50 and v["01.01"] == 2000.0 and v["03"] == 1874.50


def test_confirmacao_grava_substitui_e_guarda_historico(conn):
    assert P.confirmacao_instalada(conn) and P.confirmacao_ativa(conn, "2026-09") is None and P.meses_confirmados(conn) == []
    f1, v1 = {"01.01": "PDF", "04.01": "API"}, {"01.01": 1000.0, "04.01": -300.0}
    r1 = P.gravar_confirmacao(conn, "2026-09", f1, v1, "teste@x", "primeira", {"lucro_liquido_adotado": 700.0})
    assert r1["substituiu"] is None
    a = P.confirmacao_ativa(conn, "2026-09")
    assert a["fontes"] == f1 and a["valores"]["04.01"] == -300.0 and a["quem"] == "teste@x" and a["observacao"] == "primeira" and a["resumo"]["lucro_liquido_adotado"] == 700.0
    r2 = P.gravar_confirmacao(conn, "2026-09", {"01.01": "API", "04.01": "API"}, {"01.01": 900.0, "04.01": -300.0}, "outro@x")
    assert r2["substituiu"] == r1["id"] and P.confirmacao_ativa(conn, "2026-09")["id"] == r2["id"] and P.meses_confirmados(conn) == ["2026-09"]
    assert _contar(conn, "pnl_dre_confirmacao") == 2                                   # a antiga fica guardada
    with pytest.raises(ValueError):
        P.gravar_confirmacao(conn, "2026-09", {"01.01": "API"}, {"04.01": 1.0}, None)
    assert {l["acao"] for l in P.ultimos_logs(conn)} >= {"DRE_CONFIRMADO"}


def test_tela_resultado_confirma_dre_escolhendo_fonte_por_linha(conn):
    import hashlib
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert at.selectbox(key="pn2_fonte_2026-09_01.01").value == "PDF"               # com PDF importado, o padrao e' o PDF
        at.selectbox(key="pn2_fonte_2026-09_01.01").select("API").run()                 # a Suellen escolhe a API so' para a receita
        at.text_input(key="pn2_conf_obs_2026-09").input("receita pela API").run()
        at.button(key="pn2_confirmar_2026-09").click().run()
        assert not at.exception, at.exception
    c = P.confirmacao_ativa(conn, "2026-09")
    assert c["fontes"]["01.01"] == "API" and c["fontes"]["04.01"] == "PDF" and c["observacao"] == "receita pela API"
    assert c["valores"]["01.01"] == 2000.0 and c["valores"]["04.01"] == -600.0        # receita da API; custo do PDF (soma das 3 obras)
    assert c["resumo"]["lucro_liquido_pdf"] is not None


def test_resultado_tira_nf_desfeita_por_distrato(conn):
    dois = income() + [{**income()[0], "billId": 51, "receipts": [{"sequencialNumber": 1, "paymentDate": "2026-09-25", "netAmount": 2000.0, "grossAmount": 2000.0,
                                                                  "operationTypeId": 7, "operationTypeName": "Distrato"}]},
                       {**income()[0], "billId": 52, "receipts": [{"sequencialNumber": 1, "paymentDate": "2026-09-25", "netAmount": 500.0, "grossAmount": 500.0,
                                                                  "operationTypeId": 7, "operationTypeName": "Distrato"}]}]   # 52: distrato so' parcial -> continua
    _ingerir(conn, regs=dois, lado="R", tipo="I")
    com = {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09", sem_distrato=False)}
    sem = {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09")}
    assert com["1.01.01.01"] == 6000.0 and sem["1.01.01.01"] == 4000.0             # sai so' a NF 51 (distrato total)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra) VALUES (1049,'A','OBRA','121')")
    assert P.resultado_por_obra_api(conn, "2026-09")["121"]["01"] == 4000.0
    assert P.resultado_por_obra_api(conn, "2026-09", sem_distrato=False)["121"]["01"] == 6000.0
    assert [a["receita"] for a in P.resultado_por_centro(conn, "2026-09")] == [4000.0]


def test_obras_do_dre_calcula_bdi_margem_dem_e_top(conn):
    import hashlib
    assert P.obras_do_dre(conn, "2026-09") is None                                   # sem PDF importado
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    with conn.cursor() as cur:                                                       # 100 e 101 tem codigo proprio; 102 vira "demais obras"
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra) VALUES (1,'A','OBRA','100'),(2,'B','OBRA','101'),(3,'C','DEMAIS_MES','DEM')")
    o = P.obras_do_dre(conn, "2026-09")
    l = {x["obra"]: x for x in o["linhas"]}
    assert set(l) == {"100", "101", "DEM"} and o["linhas"][-1]["obra"] == "DEM"
    assert (l["100"]["receita"], l["100"]["custo"], l["100"]["bdi"], l["100"]["margem"]) == (1000.0, -300.0, 700.0, 0.7)
    assert (l["DEM"]["receita"], l["DEM"]["custo"], l["DEM"]["bdi"]) == (250.0, -100.0, 150.0) and l["DEM"]["nome"].startswith("Demais obras")
    assert o["total"]["receita"] == 1750.0 and o["total"]["bdi"] == 1750.0 - 600.0 and [x["obra"] for x in o["top_lucro"]] == ["100", "101"] and o["top_prejuizo"] == []
    with conn.cursor() as cur:                                                       # sem de-para: todas separadas
        cur.execute("TRUNCATE pnl_centro_grupo")
    assert {x["obra"] for x in P.obras_do_dre(conn, "2026-09")["linhas"]} == {"100", "101", "102"}


def test_tela_obras_mostra_tabela(conn):
    import hashlib
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    assert at.tabs[3].label == "Obras (prévia)"
    tab = at.tabs[3].dataframe[0].value
    assert list(tab["Obra"]) == ["100", "101", "102"] and "Margem (BDI/receita)" in tab.columns and "Custo/colab." in tab.columns
    assert "70,0%" in set(tab["Margem (BDI/receita)"])
