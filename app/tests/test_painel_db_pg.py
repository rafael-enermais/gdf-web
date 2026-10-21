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
    at.session_state["pn2_todas_abas"] = True
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
        assert len(at.tabs) == 10
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
    P.confirmar_regras(conn, ids, "contabilidade@x")
    assert any(l["acao"] == "REGRA_CONFIRMADA" and l["usuario"] == "contabilidade@x" for l in P.ultimos_logs(conn))
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
        assert at.tabs[8].label == "Histórico e logs"
        cmp_sel = [sb for sb in at.selectbox if sb.key and sb.key.startswith("pn2_mes_cmp_")][0]
        assert cmp_sel.value == "2026-09"                                       # mes lido do CSV
        tabelas = [df.value for df in at.tabs[2].dataframe]
        assert any("Confere" in df.columns and len(df) == 2 for df in tabelas)  # tabela por conta aparece mesmo
        logs = P.ultimos_logs(conn, acao="CONFERENCIA_DESPESAS")
        assert len(logs) == 1 and logs[0]["detalhe"]["resultado"] == "difere" and logs[0]["detalhe"]["mes_lido_do_csv"] == "2026-09"
        at.run()                                                                # nova execucao nao duplica o log
        assert len(P.ultimos_logs(conn, acao="CONFERENCIA_DESPESAS")) == 1
        at = _tela(conn).run()
        assert any("CONFERENCIA_DESPESAS" in set(df.value["Ação"]) for df in at.tabs[8].dataframe)


# ------------------------------------------------------------------ Resultado (DRE comprometido por emissao)
def test_resultado_por_emissao_e_dre(conn):
    regs = outcome()
    regs[3]["forecastDocument"] = "S"                      # o titulo de agosto vira documento de previsao
    _ingerir(conn, regs=regs, lado="P", tipo="I", mes="2026-08")   # a janela da carga comeca em agosto
    _ingerir(conn, regs=income(), lado="R", tipo="I", mes="2026-08")
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
        assert any("2.000,00" in m.value for m in at.tabs[3].metric)
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
        assert any("PDF lido" in s.value for s in at.tabs[1].success)                  # o upload fica na aba Importacoes (V2)
        at.button(key="pn2_pdf_salvar").click().run()
        assert not at.exception, at.exception
        assert P.meses_com_dre(conn) == ["2026-09"]
        at.run()
        assert not at.exception, at.exception
        assert any("DRE oficial de 2026-09" in c.value for c in at.tabs[3].caption)
        assert any(l["acao"] == "CONFERENCIA_RESULTADO" and l["detalhe"].get("referencia") == "PDF" for l in P.ultimos_logs(conn))


def test_tela_resultado_pdf_invalido_mostra_erro_e_registra_log(conn):
    falso = SimpleNamespace(name="x.pdf", getvalue=lambda: b"nao e pdf")
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({"pn2_pdf_dre": falso})):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    assert any("PDF" in e.value for e in at.tabs[1].error)
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
        at.selectbox(key="pn2_fonte_2026-09_01.01").select("API").run()                 # a contabilidade escolhe a API so' para a receita
        at.text_input(key="pn2_conf_obs_2026-09").input("receita pela API").run()
        at.button(key="pn2_confirmar_2026-09").click().run()
        assert not at.exception, at.exception
    c = P.confirmacao_ativa(conn, "2026-09")
    assert c["fontes"]["01.01"] == "API" and c["fontes"]["04.01"] == "PDF" and c["observacao"] == "receita pela API"
    assert c["valores"]["01.01"] == 2000.0 and c["valores"]["04.01"] == -600.0        # receita da API; custo do PDF (soma das 3 obras)
    assert c["resumo"]["lucro_liquido_pdf"] is not None


def test_valores_adotados_e_resumo_manuais():
    fd = {"API": {"01.01": 2000.0, "04.01": -300.0}, "PDF": {"01.01": 1000.0, "04.01": -600.0}}
    esc = {"01.01": "MANUAL", "04.01": "PDF"}
    ad = P.valores_adotados(fd, esc, {"01.01": 1234.567, "04.01": 9.0})
    assert ad == {"01.01": 1234.57, "04.01": -600.0}                       # manual so' vale na linha MANUAL
    assert P.resumo_manuais(esc, ad, fd) == {"01.01": {"manual": 1234.57, "API": 2000.0, "PDF": 1000.0}}


def test_confirmacao_manual_exige_observacao_e_fica_registrada(conn):
    f, v = {"01.01": "MANUAL", "04.01": "API"}, {"01.01": 1500.0, "04.01": -300.0}
    with pytest.raises(ValueError):
        P.gravar_confirmacao(conn, "2026-09", f, v, "teste@x", "  ")
    assert P.confirmacao_ativa(conn, "2026-09") is None                     # nada gravado
    P.gravar_confirmacao(conn, "2026-09", f, v, "teste@x", "PDF leu errado a receita", {"manuais": {"01.01": {"manual": 1500.0}}})
    c = P.confirmacao_ativa(conn, "2026-09")
    assert c["fontes"]["01.01"] == "MANUAL" and c["valores"]["01.01"] == 1500.0 and c["resumo"]["manuais"]["01.01"]["manual"] == 1500.0


def test_tela_resultado_ajuste_manual_de_uma_linha(conn):
    import hashlib
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert at.number_input(key="pn2_manual_2026-09_01.01").disabled                 # so' edita com MANUAL
        at.selectbox(key="pn2_fonte_2026-09_01.01").select("MANUAL").run()
        assert not at.number_input(key="pn2_manual_2026-09_01.01").disabled
        at.number_input(key="pn2_manual_2026-09_01.01").set_value(1777.77).run()
        at.button(key="pn2_confirmar_2026-09").click().run()                            # sem observacao: recusa
        assert any("observação" in e.value for e in at.error)
        assert P.confirmacao_ativa(conn, "2026-09") is None
        at.text_input(key="pn2_conf_obs_2026-09").input("corrigido a mao").run()
        at.button(key="pn2_confirmar_2026-09").click().run()
        assert not at.exception, at.exception
    c = P.confirmacao_ativa(conn, "2026-09")
    assert c["fontes"]["01.01"] == "MANUAL" and c["valores"]["01.01"] == 1777.77 and c["fontes"]["04.01"] == "PDF"
    assert c["resumo"]["manuais"]["01.01"]["manual"] == 1777.77


def test_resultado_traz_imposto_do_titulo_no_dre_02_02(conn):
    """taxAmount do titulo de receita = impostos da NF (DRE 02.02); mesmos filtros da receita (previsao e distrato)."""
    regs = [{**income()[0], "billId": 50, "taxAmount": 150.0},
            {**income()[0], "billId": 51, "taxAmount": 300.0, "receipts": [{"sequencialNumber": 1, "paymentDate": "2026-09-25", "netAmount": 2000.0,
                                                                          "grossAmount": 2000.0, "operationTypeId": 7, "operationTypeName": "Distrato"}]},
            {**income()[0], "billId": 53, "taxAmount": 50.0, "documentForecast": "S"}]
    _ingerir(conn, regs=regs, lado="R", tipo="I")
    imp = lambda **k: {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09", **k)}.get("1.01.02.01")  # noqa: E731
    assert imp(sem_previsao=True) == -150.0                       # sem a previsao (53) e sem o distrato (51)
    assert imp(sem_previsao=True, sem_distrato=False) == -450.0
    assert imp() == -200.0                                        # com previsao, sem distrato
    dre = P.dre_do_mes(P.resultado_por_conta(conn, "2026-09", sem_previsao=True))
    assert dre["valores"]["02.02"] == -150.0


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


def test_resultado_tira_titulos_a_pagar_desfeitos_e_multas_aej(conn):
    from dados_sienge import _c, _pg
    base = {"billId": 60, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "NFS ",
            "forecastDocument": "N", "creditorId": 77, "creditorName": "FORNECEDOR TESTE", "issueDate": "2026-09-10", "dueDate": "2026-09-30",
            "originalAmount": 100.0, "payments": [_pg(1, "2026-09-30", 100.0)], "paymentsCategories": [_c("2010104", "Material de Consumo | Obra", 100, 1049)]}
    regs = [base,                                                                                                                       # 100: fica
            {**base, "billId": 61, "documentIdentificationId": "AEJ ", "originalAmount": 700.0, "payments": [_pg(1, "2026-09-30", 700.0)]},   # multa: sai
            {**base, "billId": 62, "originalAmount": 400.0, "payments": [_pg(1, "2026-09-12", 400.0, 8, "Abatimento de adiantamento")]},      # abatido total: sai
            {**base, "billId": 63, "originalAmount": 400.0, "payments": [_pg(1, "2026-09-12", 100.0, 5, "Substituicao")]},                    # substituido so' em parte: fica
            {**base, "billId": 64, "originalAmount": 250.0, "payments": [_pg(1, "2026-09-12", 250.0, 3, "Cancelamento")]},                    # cancelado total: sai
            {**base, "billId": 65, "originalAmount": 150.0, "payments": [_pg(1, "2026-09-30", 150.0)]}]                                      # 150: fica
    _ingerir(conn, regs=regs, lado="P", tipo="I")
    custo = lambda **k: {c["plano_cod"]: c["valor"] for c in P.resultado_por_conta(conn, "2026-09", **k)}["2.01.01.04"]  # noqa: E731
    assert custo() == -(100 + 400 + 150)                                                 # padrao: ligado (regra confirmada pela contabilidade em 19/10)
    assert custo(sem_desfeitos=False) == -(100 + 700 + 400 + 400 + 250 + 150)           # desligado: tudo conta
    assert custo(sem_desfeitos=True) == -(100 + 400 + 150)                              # tira AEJ, abatido e cancelado
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra) VALUES (1049,'A','OBRA','121')")
    assert sum(a["custo"] for a in P.resultado_por_centro(conn, "2026-09", sem_desfeitos=True)) == -650.0
    assert P.resultado_por_obra_api(conn, "2026-09", sem_desfeitos=True)["121"]["04.02"] == -650.0


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
    assert at.tabs[4].label == "Obras (prévia)"
    tab = at.tabs[4].dataframe[0].value
    assert list(tab["Obra"]) == ["100", "101", "102"] and "Margem (BDI/receita)" in tab.columns and "Custo/colab." in tab.columns
    assert "70,0%" in set(tab["Margem (BDI/receita)"])


# ---------------------------------------------------------------- Folha de pagamento (recibos; SQL-16)
def _depara_folha(conn):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO pnl_folha_depto_obra (empresa, departamento, subnivel_texto, codigo_obra, obra_nome) VALUES
                       ('468', '001.004', 'OBRA TESTE UM', '103', 'OBRA UM'), ('468', '001.010', 'OBRA TESTE DOIS', '104', 'OBRA DOIS')""")


def test_gravar_folha_ativa_repetido_e_totais(conn):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    assert P.folha_instalada(conn)
    _depara_folha(conn)
    folha = IF.ler_recibos_pdf(pdf_folha_sintetico())
    r = P.gravar_folha(conn, folha, "recibos.pdf", "a" * 64, "teste@x")
    assert r["repetido"] is False and r["mes"] == "2026-09" and r["escopo"] == "CONSTRUTORA" and r["recibos"] == 3
    assert P.gravar_folha(conn, folha, "recibos.pdf", "a" * 64, "teste@x")["repetido"] is True        # mesmo arquivo: nao grava de novo
    assert _contar(conn, "pnl_folha_recibo") == 3
    assert P.folha_meses(conn) == ["2026-09"]
    f = P.folha_do_mes(conn, "2026-09")
    t = f["total"]
    assert t["colab"] == 3 and t["salarios"] == 10000.00                                   # 3.000 + 4.000 + 3.000
    assert round(t["hora_extra"], 2) == 1000.00 and t["dsr_he"] == 100.00                  # 500 + 200 + 300 ; DSR 100
    assert t["descontos"] == 1060.00 and t["base_he"] == 8940.00                           # base = 11.100 - 1.100 (HE+DSR) - 1.060 (todos os descontos; contabilidade 20/10)
    assert t["he_pct"] == 0.123                                                            # (1000 + 100) / 8940
    assert t["proventos"] == 11100.00 and t["fgts"] == 888.00 and t["custo"] == 11988.00
    assert f["por_obra"]["103"]["colab"] == 2 and f["por_obra"]["104"]["colab"] == 1
    assert f["sem_depara"] == []
    assert f["por_empresa"][0]["empresa"] == "CONSTRUTORA"
    # os eventos guardam a linha informativa (vale alimentacao) com valor zero
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), sum(provento) FILTER (WHERE informativo) FROM pnl_folha_evento")
        n_ev, soma_inf = cur.fetchone()
    assert n_ev >= 12 and float(soma_inf or 0) == 0.0


def test_folha_colaboradores_lista_nome_cargo_e_obra(conn):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    assert P.folha_colaboradores(conn, "2026-09") == []                                    # sem folha: lista vazia
    _depara_folha(conn)
    P.gravar_folha(conn, IF.ler_recibos_pdf(pdf_folha_sintetico()), "r.pdf", "d" * 64, "teste@x")
    lst = P.folha_colaboradores(conn, "2026-09")
    assert len(lst) == 3 and all(x["nome"] and x["empresa"] == "CONSTRUTORA" for x in lst)
    assert sorted(x["obra"] for x in lst) == ["103", "103", "104"]                         # mesmo de-para da folha_do_mes
    assert P.folha_colaboradores(conn, "2025-01") == []


def test_folha_nova_do_mesmo_mes_substitui_a_antiga_e_log_sem_nomes(conn):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    folha = IF.ler_recibos_pdf(pdf_folha_sintetico())
    P.gravar_folha(conn, folha, "v1.pdf", "b" * 64, "teste@x")
    P.gravar_folha(conn, folha, "v2.pdf", "c" * 64, "teste@x")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE ativo), count(*) FROM pnl_importacao WHERE tipo='FOLHA'")
        assert cur.fetchone() == (1, 2)
    assert P.folha_do_mes(conn, "2026-09")["total"]["colab"] == 3                       # so a ativa conta (nao dobra)
    with conn.cursor() as cur:
        cur.execute("SELECT detalhe::text FROM pnl_log WHERE acao='FOLHA_PDF_IMPORTADA'")
        logs = " ".join(r[0] for r in cur.fetchall())
    assert "FICTICIA" not in logs and "IMAGINARIO" not in logs                              # o historico nao guarda nome de pessoa


def test_folha_sem_de_para_aparece_na_lista_e_colab_por_linha_obras(conn):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    P.gravar_folha(conn, IF.ler_recibos_pdf(pdf_folha_sintetico()), "r.pdf", "d" * 64, "teste@x")
    f = P.folha_do_mes(conn, "2026-09")                                                   # sem de-para: tudo cai em 'sem de-para'
    assert {x["departamento"] for x in f["sem_depara"]} == {"001.004", "001.010"}
    _depara_folha(conn)
    f = P.folha_do_mes(conn, "2026-09")
    linhas = [{"obra": "103"}, {"obra": "DEM"}]
    assert P.colab_por_linha_obras(linhas, f) == {"103": 2, "DEM": 1}                     # obra 104 nao tem linha propria: entra em Demais obras
    assert P.colab_por_linha_obras(linhas, None) == {}
    assert P.folha_do_mes(conn, "2025-01") is None


# ---------------------------------------------------------------- Projecao de receitas (xlsx) e Orcamento ADM (PDF)
def _ob_falso():
    return {"linhas": [{"obra": "103", "nome": "ANASTACIO - LOTE 11 - 001/2024", "receita": 1200.0, "custo": -800.0, "bdi": 400.0},
                       {"obra": "111", "nome": "ELETROBRAS - OPGW II - RJ | SP | ES", "receita": 2500.0, "custo": -1700.0, "bdi": 800.0},
                       {"obra": "DEM", "nome": "Demais obras (2)", "receita": 300.0, "custo": -100.0, "bdi": 200.0}],
            "total": {"receita": 4000.0, "custo": -2600.0, "bdi": 1400.0, "margem": 0.35}}


def test_gravar_projecao_e_comparar_com_o_dre(conn):
    import io
    import openpyxl
    import importador_projecao as IP
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CONTRATO", "CLIENTE", "OBRA", "CATEGORIA", "NATUREZA", "EMPRESA / FORNECEDOR", "set/26", "CUSTOS", "BDI"])
    ws.append(["C1", "CLI A", "LOTE 11", "INDIRETO", None, "CONSTRUTORA", 1000.0, 700.0, 300.0])
    ws.append(["C1", "CLI A", "LOTE 11", "INDIRETO", None, "ENERGIA", 500.0, 350.0, 150.0])
    ws.append(["C2", "CLI B", "OPGW II", "INDIRETO", None, "ENERGIA", 2000.0, 1400.0, 600.0])
    ws.append(["C3", "CLI C", "OBRA SEM DRE", "INDIRETO", None, "ENERGIA", 100.0, 70.0, 30.0])
    buf = io.BytesIO(); wb.save(buf)
    proj = IP.ler_projecao_xlsx(buf.getvalue())
    r = P.gravar_projecao(conn, proj, "proj.xlsx", "e" * 64, "teste@x")
    assert r["repetido"] is False and r["mes"] == "2026-09" and r["linhas"] == 4
    assert P.gravar_projecao(conn, proj, "proj.xlsx", "e" * 64, "teste@x")["repetido"] is True
    P.gravar_projecao(conn, proj, "proj2.xlsx", "f" * 64, "teste@x")                         # nova do mesmo mes substitui a antiga
    assert P.projecao_meses(conn) == ["2026-09"]
    pm = P.projecao_do_mes(conn, "2026-09")
    assert pm["arquivo"] == "proj2.xlsx" and len(pm["linhas"]) == 4 and P.projecao_do_mes(conn, "2025-01") is None
    cmp_ = P.projecao_x_realizado(pm, _ob_falso())
    por = {x["codigo"]: x for x in cmp_["linhas"]}
    assert por["103"]["receita_proj"] == 1500.0 and por["103"]["desvio"] == -300.0 and por["103"]["bdi_proj"] == 450.0 and por["103"]["desvio_bdi"] == -50.0
    assert por["111"]["receita_proj"] == 2000.0 and por["111"]["desvio"] == 500.0 and por["111"]["desvio_pct"] == 0.25
    assert [o["obra"] for o in cmp_["sem_correspondencia"]] == ["OBRA SEM DRE"]
    assert cmp_["receita_proj_total"] == 3600.0 and cmp_["receita_real_total"] == 4000.0
    assert cmp_["receita_sem_projecao"] == 300.0                                              # Demais obras (sem projecao)


def test_gravar_orcamento_e_resumo_mes_e_acumulado(conn):
    from orcamento_sintetico import pdf_orcamento_sintetico
    import importador_orcamento as IO
    assert P.orcamento_instalado(conn)
    orc = IO.ler_orcamento_adm_pdf(pdf_orcamento_sintetico())
    r = P.gravar_orcamento(conn, orc, "orc.pdf", "1" * 64, "teste@x")
    assert r["repetido"] is False and r["mes"] == "2026-01"
    assert P.gravar_orcamento(conn, orc, "orc.pdf", "1" * 64, "teste@x")["repetido"] is True
    ativo = P.orcamento_ativo(conn)
    assert ativo["arquivo"] == "orc.pdf" and ativo["meses"][0] == "2026-01" and len(ativo["meses"]) == 6
    jan = P.orcamento_resumo(conn, ativo["id"], "2026-01")
    assert (jan["total"]["orcado"], jan["total"]["realizado"], jan["total"]["desvio"]) == (1500.0, 1550.5, 50.5)
    assert [g["codigo"] for g in jan["grupos"]] == ["2.01"]                                 # 2.02 so tem valor a partir de março
    ac = P.orcamento_resumo(conn, ativo["id"], "2026-03", acumulado=True)                    # jan + fev + mar
    assert (ac["total"]["orcado"], ac["total"]["realizado"], ac["total"]["desvio"]) == (4600.0, 4650.5, 50.5)
    assert [(c["codigo"], c["desvio"]) for c in ac["acima"]] == [("2.02.01", 80.0), ("2.01.02", 20.0)]
    assert [(c["codigo"], c["desvio"]) for c in ac["abaixo"]] == [("2.01.01", -49.5)]
    assert ac["total"]["desvio_pct"] == round(50.5 / 4600.0, 4)
    assert [g["codigo"] for g in ac["grupos"]] == ["2.01", "2.02"]
    serie = P.orcamento_serie_mensal(conn, ativo["id"])                                      # desvio mes a mes + acumulado
    assert [x["mes"] for x in serie] == ativo["meses"] and len(serie) == 6
    assert (serie[0]["orcado"], serie[0]["realizado"], serie[0]["desvio"], serie[0]["desvio_acum"]) == (1500.0, 1550.5, 50.5, 50.5)
    assert serie[2]["desvio_acum"] == 50.5 and round(sum(x["desvio"] for x in serie), 2) == serie[-1]["desvio_acum"]
    assert serie[0]["desvio_pct"] == round(50.5 / 1500.0, 4)


def test_importacao_por_sha_acha_arquivo_salvo(conn):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    assert P.importacao_por_sha(conn, "FOLHA", "d" * 64) is None
    P.gravar_folha(conn, IF.ler_recibos_pdf(pdf_folha_sintetico()), "r.pdf", "d" * 64, "teste@x")
    r = P.importacao_por_sha(conn, "FOLHA", "d" * 64)
    assert r["ativo"] is True and r["mes"] == "2026-09" and r["quem"] == "teste@x" and r["linhas"] == 3
    assert P.importacao_por_sha(conn, "PROJECAO", "d" * 64) is None                         # tipo diferente nao confunde


def _folha_gravada(conn, sha="a" * 64):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    return P.gravar_folha(conn, IF.ler_recibos_pdf(pdf_folha_sintetico()), "r.pdf", sha, "teste@x")


def test_converter_valor_edicao():
    import datetime as dt
    c = P.converter_valor_edicao
    assert c("num", "1.234,56") == c("num", 1234.56) and str(c("num", 10)) == "10.00" and c("num", None) is None and c("num", float("nan")) is None
    assert c("text", "  abc ") == "abc" and c("text", "") is None and c("int", 3.0) == 3
    assert c("date", "2026-09-01") == dt.date(2026, 9, 1) and c("date", dt.datetime(2026, 9, 1, 3, 0)) == dt.date(2026, 9, 1)
    with pytest.raises(ValueError):
        c("num", "abc")
    with pytest.raises(ValueError):
        c("date", "01/09/2026")


def test_editar_orcamento_acerta_saldo_e_totais_dos_grupos_e_registra(conn):
    """v0.21.3: ao editar orcado/realizado de uma conta, o saldo (realizado - orcado) e os totais dos grupos acima (2.01 e 2) acompanham, tudo em pnl_edicao."""
    from orcamento_sintetico import pdf_orcamento_sintetico
    import importador_orcamento as IO
    ro = P.gravar_orcamento(conn, IO.ler_orcamento_adm_pdf(pdf_orcamento_sintetico()), "o.pdf", "2" * 64, "teste@x")
    lin = {(l["codigo"], l["mes"].strftime("%Y-%m")): l for l in P.edicao_carregar(conn, "ORCAMENTO", ro["id"])}
    sal = lin[("2.01.01", "2026-04")]                          # orcado 1100, realizado 1250,75, saldo 150,75
    t201, t2 = lin[("2.01", "2026-04")], lin[("2", "2026-04")]
    res = P.edicao_aplicar(conn, "ORCAMENTO", ro["id"], [(sal["id"], "realizado", 1300.75), (sal["id"], "orcado", 1000.0)], [], "teste@x", "ajuste")
    assert res["editados"] == 2 and res["automaticos"] >= 5
    dep = {(l["codigo"], l["mes"].strftime("%Y-%m")): l for l in P.edicao_carregar(conn, "ORCAMENTO", ro["id"])}
    assert dep[("2.01.01", "2026-04")]["saldo"] == 300.75                                    # 1300,75 - 1000
    assert dep[("2.01", "2026-04")]["realizado"] == round(t201["realizado"] + 50.0, 2)       # +50 no realizado
    assert dep[("2.01", "2026-04")]["orcado"] == round(t201["orcado"] - 100.0, 2)            # -100 no orcado
    assert dep[("2", "2026-04")]["realizado"] == round(t2["realizado"] + 50.0, 2) and dep[("2", "2026-04")]["orcado"] == round(t2["orcado"] - 100.0, 2)
    assert dep[("2", "2026-04")]["saldo"] == round(dep[("2", "2026-04")]["realizado"] - dep[("2", "2026-04")]["orcado"], 2)
    assert dep[("2.01.02", "2026-04")] == lin[("2.01.02", "2026-04")]                       # irma nao muda
    assert dep[("2.01", "2026-05")] == lin[("2.01", "2026-05")]                             # outro mes nao muda
    assert dep[("1.01", "2026-01")] == lin[("1.01", "2026-01")]                             # outro grupo nao muda
    # o "Administracao" enxerga o total novo
    assert P.orcamento_resumo(conn, ro["id"], "2026-04")["total"]["realizado"] == dep[("2", "2026-04")]["realizado"]
    # tudo registrado: 2 celulas editadas + acertos automaticos (marcados como automatico)
    eds = P.edicoes_lista(conn, ro["id"])
    assert len(eds) == res["editados"] + res["automaticos"] and sum(1 for e in eds if "automático" in (e["motivo"] or "")) == res["automaticos"]
    # o saldo nao se edita na mao
    with pytest.raises(ValueError, match="saldo"):
        P.edicao_aplicar(conn, "ORCAMENTO", ro["id"], [(sal["id"], "saldo", 1.0)], [], "teste@x")
    # editar sem mudar nada nao mexe em nada
    assert P.edicao_aplicar(conn, "ORCAMENTO", ro["id"], [(sal["id"], "realizado", 1300.75)], [], "teste@x")["automaticos"] == 0
    # linha nova: saldo calculado e grupo acima soma
    antes_t = dep[("2.01", "2026-06")]["realizado"]
    P.edicao_aplicar(conn, "ORCAMENTO", ro["id"], [], [{"codigo": "2.01.99", "conta": "Nova", "tipo": "R", "mes": "2026-06-01", "orcado": 10, "realizado": 25}], "teste@x")
    dep2 = {(l["codigo"], l["mes"].strftime("%Y-%m")): l for l in P.edicao_carregar(conn, "ORCAMENTO", ro["id"])}
    assert dep2[("2.01.99", "2026-06")]["saldo"] == 15.0 and dep2[("2.01", "2026-06")]["realizado"] == round(antes_t + 25, 2)
    # grupo zerado no mes (o PDF nao traz a linha): a linha do total e' criada ao lancar valor numa conta filha
    assert ("1.01", "2026-04") not in dep2
    P.edicao_aplicar(conn, "ORCAMENTO", ro["id"], [], [{"codigo": "1.01.01", "conta": "Receita de teste", "tipo": "R", "mes": "2026-04-01", "orcado": 0, "realizado": 40}], "teste@x")
    dep3 = {(l["codigo"], l["mes"].strftime("%Y-%m")): l for l in P.edicao_carregar(conn, "ORCAMENTO", ro["id"])}
    assert dep3[("1.01", "2026-04")]["realizado"] == 40.0 and dep3[("1.01", "2026-04")]["saldo"] == 40.0 and dep3[("1", "2026-04")]["realizado"] == 40.0


def test_editar_folha_guarda_antes_e_depois_e_reflete_nos_totais(conn):
    assert P.edicao_instalada(conn)
    r = _folha_gravada(conn)
    linhas = P.edicao_carregar(conn, "FOLHA", r["id"])
    assert len(linhas) == 3 and "id" in linhas[0] and isinstance(linhas[0]["salario"], float)
    antes = P.folha_do_mes(conn, "2026-09")["total"]["salarios"]
    alvo = linhas[0]
    res = P.edicao_aplicar(conn, "FOLHA", r["id"], [(alvo["id"], "salario", alvo["salario"] + 100.0), (alvo["id"], "nome", alvo["nome"])], [], "teste@x", "leitura errada")
    assert res == {"editados": 1, "linhas_novas": 0, "automaticos": 0}                                         # nome igual: nao conta nem grava
    assert round(P.folha_do_mes(conn, "2026-09")["total"]["salarios"] - antes, 2) == 100.0   # a tela le da mesma tabela
    ed = P.edicoes_lista(conn, r["id"])
    assert len(ed) == 1 and ed[0]["campo"] == "salario" and ed[0]["acao"] == "EDITOU" and ed[0]["motivo"] == "leitura errada" and ed[0]["quem"] == "teste@x"
    assert float(ed[0]["depois"]) - float(ed[0]["antes"]) == 100.0
    assert P.importacoes_lista(conn)[0]["edicoes"] == 1


def test_editar_rejeita_campo_invalido_vazio_obrigatorio_e_linha_de_outra_importacao(conn):
    r = _folha_gravada(conn)
    lid = P.edicao_carregar(conn, "FOLHA", r["id"])[0]["id"]
    for alt in ([(lid, "importacao_id", 1)], [(lid, "cadastro", "")], [(lid, "salario", "abc")], [(lid + 999, "salario", 1)]):
        with pytest.raises(ValueError):
            P.edicao_aplicar(conn, "FOLHA", r["id"], alt, [], "teste@x")
    assert P.edicoes_lista(conn, r["id"]) == []                                              # nada ficou gravado pela metade


def test_adicionar_linha_nova_incrementa_n_linhas_e_valida_obrigatorios(conn):
    r = _folha_gravada(conn)
    with pytest.raises(ValueError):
        P.edicao_aplicar(conn, "FOLHA", r["id"], [], [{"nome": "Sem cadastro"}], "teste@x")
    res = P.edicao_aplicar(conn, "FOLHA", r["id"], [], [{"empresa": "468", "cadastro": "9999", "nome": "Manual", "departamento": "001.001", "salario": 1000, "total_proventos": 1000},
                                                       {"empresa": None}], "teste@x", "recibo que a leitura perdeu")
    assert res == {"editados": 0, "linhas_novas": 1, "automaticos": 0}
    assert len(P.edicao_carregar(conn, "FOLHA", r["id"])) == 4
    assert P.importacoes_lista(conn)[0]["linhas"] == 4
    assert P.edicoes_lista(conn, r["id"])[0]["acao"] == "ADICIONOU"


def test_editar_dre_projecao_e_orcamento(conn):
    import io
    import openpyxl
    import importador_projecao as IP
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CONTRATO", "CLIENTE", "OBRA", "CATEGORIA", "NATUREZA", "EMPRESA / FORNECEDOR", "set/26", "CUSTOS", "BDI"])
    ws.append(["C1", "CLI A", "LOTE 11", "INDIRETO", None, "CONSTRUTORA", 1000.0, 700.0, 300.0])
    buf = io.BytesIO(); wb.save(buf)
    rp = P.gravar_projecao(conn, IP.ler_projecao_xlsx(buf.getvalue()), "p.xlsx", "e" * 64, "teste@x")
    lp = P.edicao_carregar(conn, "PROJECAO", rp["id"])
    P.edicao_aplicar(conn, "PROJECAO", rp["id"], [(lp[0]["id"], "valor_mes", "1.500,50")], [], "teste@x")
    assert P.projecao_do_mes(conn, "2026-09")["linhas"][0]["valor_mes"] == 1500.50
    from orcamento_sintetico import pdf_orcamento_sintetico
    import importador_orcamento as IO
    ro = P.gravar_orcamento(conn, IO.ler_orcamento_adm_pdf(pdf_orcamento_sintetico()), "o.pdf", "1" * 64, "teste@x")
    lo = P.edicao_carregar(conn, "ORCAMENTO", ro["id"])
    import datetime as dt
    assert isinstance(lo[0]["mes"], dt.date)
    P.edicao_aplicar(conn, "ORCAMENTO", ro["id"], [(lo[0]["id"], "orcado", 5.0)], [], "teste@x")
    assert P.edicao_carregar(conn, "ORCAMENTO", ro["id"])[0]["orcado"] == 5.0
    with conn.cursor() as cur:                                                                 # DRE: uma linha qualquer
        cur.execute("INSERT INTO pnl_importacao (tipo, mes, escopo, arquivo_nome, arquivo_sha256) VALUES ('DRE','2026-09-01','','d.pdf',%s) RETURNING id", ("d" * 64,))
        did = cur.fetchone()[0]
        cur.execute("INSERT INTO pnl_dre_valor (importacao_id, obra_cod, linha, valor) VALUES (%s,'103','01',100)", (did,))
    ld = P.edicao_carregar(conn, "DRE", did)
    P.edicao_aplicar(conn, "DRE", did, [(ld[0]["id"], "valor", 250)], [], "teste@x")
    assert P.edicao_carregar(conn, "DRE", did)[0]["valor"] == 250.0
    assert {e["tipo"] for e in P.edicoes_lista(conn)} == {"PROJECAO", "ORCAMENTO", "DRE"}


def test_reverter_e_reativar_importacao_sem_apagar(conn):
    from folha_sintetica import pdf_folha_sintetico
    import importador_folha as IF
    folha = IF.ler_recibos_pdf(pdf_folha_sintetico())
    a = P.gravar_folha(conn, folha, "v1.pdf", "b" * 64, "teste@x")
    b = P.gravar_folha(conn, folha, "v2.pdf", "c" * 64, "teste@x")                          # v2 substitui v1 (v1 fica ativo=false)
    ativos = {i["id"]: i["ativo"] for i in P.importacoes_lista(conn)}
    assert ativos == {a["id"]: False, b["id"]: True}
    r = P.importacao_definir_ativo(conn, a["id"], True, "teste@x", "v2 estava errada")       # reativa a v1 e tira a v2 de uso
    assert r["mudou"] and r["substituiu"] == b["id"]
    ativos = {i["id"]: i["ativo"] for i in P.importacoes_lista(conn)}
    assert ativos == {a["id"]: True, b["id"]: False}
    assert P.folha_do_mes(conn, "2026-09")["importacoes"][0]["arquivo"] == "v1.pdf"
    assert P.importacao_definir_ativo(conn, a["id"], True, "teste@x")["mudou"] is False      # ja estava ativa
    P.importacao_definir_ativo(conn, a["id"], False, "teste@x")                               # fora de uso, sem substituta
    assert P.folha_meses(conn) == []
    assert _contar(conn, "pnl_folha_recibo") == 6                                              # nada foi apagado (3 recibos de cada importacao)
    assert {"DESATIVOU", "REATIVOU"} <= {e["acao"] for e in P.edicoes_lista(conn)}


def test_depara_depto_obra_cria_altera_e_registra(conn):
    assert P.depto_obra_salvar(conn, [{"empresa": "468", "departamento": "001.050", "codigo_obra": "103", "obra_nome": "A"}], "teste@x") == {"novos": 1, "alterados": 0}
    assert P.depto_obra_salvar(conn, [{"empresa": "468", "departamento": "001.050", "codigo_obra": "103", "obra_nome": "A"}], "teste@x") == {"novos": 0, "alterados": 0}
    assert P.depto_obra_salvar(conn, [{"empresa": "468", "departamento": "001.050", "codigo_obra": "104", "obra_nome": "B"}], "teste@x", "corrigido") == {"novos": 0, "alterados": 1}
    assert P.depto_obra_listar(conn)[0]["codigo_obra"] == "104"
    assert [e["acao"] for e in P.edicoes_lista(conn)] == ["CADASTRO", "CADASTRO"]
    with pytest.raises(ValueError):
        P.depto_obra_salvar(conn, [{"empresa": "468", "departamento": "001.051"}], "teste@x")


# ------------------------------------------------------------------ aba Importacoes (V2)
def test_tela_importacoes_mostra_situacao_historico_e_reverte(conn):
    r1 = _folha_gravada(conn, "a" * 64)
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert at.tabs[1].label == "Importações (V2)"
        tabs_df = [df.value for df in at.tabs[1].dataframe]
        sit = [d for d in tabs_df if "Folha Construtora" in d.columns][0]
        assert sit.iloc[0]["Folha Construtora"] == "✅" and sit.iloc[0]["Folha Energia"].startswith("❌") and sit.iloc[0]["DRE"].startswith("❌")
        hist = [d for d in tabs_df if "Situação" in d.columns][0]
        assert list(hist["#"]) == [r1["id"]] and hist.iloc[0]["Situação"] == "em uso"
        at.button(key="pn2_imp_rev_off").click().run()                                       # marcar como fora de uso
        assert not at.exception, at.exception
        assert P.importacoes_lista(conn)[0]["ativo"] is False and P.folha_meses(conn) == []
        at.button(key="pn2_imp_rev_on").click().run()                                        # reativar
        assert not at.exception, at.exception
        assert P.importacoes_lista(conn)[0]["ativo"] is True and P.folha_meses(conn) == ["2026-09"]
        assert {e["acao"] for e in P.edicoes_lista(conn)} == {"DESATIVOU", "REATIVOU"}


def test_tela_importacoes_cadastro_de_credores_adiciona_e_tira(conn):
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        at.text_input(key="pn2_cg_nome").input("Fulano de Tal").run()
        at.button(key="pn2_cg_add").click().run()
        assert not at.exception, at.exception
        assert [c["chave"] for c in P.credor_grupo_ativos(conn)] == ["FULANO DE TAL"]
        at.button(key="pn2_cg_btn_rem").click().run()
        assert P.credor_grupo_ativos(conn) == []


def test_tela_importacoes_sem_sql_19_avisa_e_nao_quebra(conn):
    _folha_gravada(conn, "a" * 64)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE gdf.pnl_edicao RENAME TO pnl_edicao_off")                  # simula o banco antes do SQL-19
    try:
        with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
            at = _tela(conn).run()
        assert not at.exception, at.exception
        assert any("SQL-19" in w.value for w in at.tabs[1].warning)
        assert P.edicoes_lista(conn) == [] and P.importacoes_lista(conn)[0]["edicoes"] == 0
    finally:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE gdf.pnl_edicao_off RENAME TO pnl_edicao")


def test_relatorio_pdf_do_painel_rascunho(conn):
    """O PDF do painel sai com DRE confirmado, avisa o que falta (obras/adm/pessoas) e o botao da ultima aba entrega o arquivo."""
    import hashlib
    import relatorio_painel_pdf as RPP
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    ctx = RPP.montar_ctx(conn, "2026-09", "19/10/2026 10:00")
    assert ctx["dre"]["origem"].startswith("DRE oficial") and ctx["pessoas"] is None and ctx["obras"] is not None
    pdf = RPP.gerar_pdf_painel(ctx, gerado_em="19/10/2026 10:00")
    assert pdf[:5] == b"%PDF-" and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 10
    # mes sem nada: nenhuma pagina estoura, todas viram aviso
    vazio = RPP.gerar_pdf_painel(RPP.montar_ctx(conn, "2024-01"))
    assert vazio[:5] == b"%PDF-"
    with patch("conexao.get_conn", return_value=conn), patch("streamlit.file_uploader", side_effect=_uploader_por_chave({})):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        at.button(key="pn2_btn_pdf").click().run()
        assert not at.exception, at.exception
        assert any("pronto" in s.value for s in at.success)


def test_obras_do_sienge_gravar_conferir_e_nome_so_onde_falta(conn):
    """SQL-24: grava as obras do cadastro do Sienge, mostra a conferencia codigo x nome e usa o nome do Sienge so' onde o painel nao tem nome."""
    import relatorio_painel_pdf as RPP
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra, obra_nome) VALUES
                       (1,'A','OBRA','103','ANASTACIO LOTE 11'), (2,'B','OBRA','121',NULL), (3,'C','OBRA','130',NULL), (4,'D','ADM','ADM',NULL)""")
    assert P.obras_sienge_instalado(conn)
    obras = S.normalizar_obras([{"id": 103, "name": "NOME SIENGE 103"}, {"id": 121, "name": "ENERGISA GUAPORE", "commercialName": "Guapore"}, {"id": 999, "name": "NAO USADA"}])
    assert P.gravar_obras_sienge(conn, obras) == {"obras": 3}
    assert P.gravar_obras_sienge(conn, obras) == {"obras": 3}                          # repetir nao duplica
    assert _contar(conn, "pnl_obra_sienge") == 3
    conf = {c["codigo"]: c for c in P.obras_sienge_conferencia(conn)}
    assert set(conf) == {"103", "121", "130"}                                          # ADM/DEM nao entram
    assert conf["103"]["nome_sienge"] == "NOME SIENGE 103" and conf["103"]["nome_atual"] == "ANASTACIO LOTE 11"
    assert conf["121"]["nome_sienge"] == "ENERGISA GUAPORE" and conf["121"]["nome_atual"] is None
    assert conf["130"]["nome_sienge"] is None
    nomes = RPP._nomes_obras(conn)
    assert nomes["103"] == "ANASTACIO LOTE 11"                                        # nome validado do de-para tem prioridade
    assert nomes["121"] == "ENERGISA GUAPORE" and "130" not in nomes                  # Sienge so' onde faltava
    assert "ENERGISA GUAPORE" in P.nomes_obras_extra(conn)["121"]
    assert P.gravar_obras_sienge(conn, []) == {"obras": 0}


def test_obras_do_sienge_sem_a_tabela_avisa_em_vez_de_quebrar(conn):
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE pnl_obra_sienge RENAME TO pnl_obra_sienge_x")
    try:
        assert not P.obras_sienge_instalado(conn)
        assert "SQL-24" in P.gravar_obras_sienge(conn, [{"id": 1}])["erro"]
        assert P.obras_sienge_conferencia(conn) == [] and P.nomes_obras_extra(conn) == {}
    finally:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE pnl_obra_sienge_x RENAME TO pnl_obra_sienge")


def test_botao_atualizar_cadastros_grava_obras_e_mostra_conferencia(conn):
    """O botao atualiza empresas/centros/plano e TAMBEM as obras do Sienge; falha nas obras avisa sem desfazer o resto."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, grupo, codigo_obra) VALUES (1049,'A','OBRA','103')")

    class Cli:
        def __init__(self, obras_ok=True):
            self.obras_ok = obras_ok

        def get(self, caminho, params=None):
            if caminho == "v1/enterprises":
                if not self.obras_ok:
                    raise S.ErroSienge("Sienge respondeu HTTP 403 (a chave não tem permissão para este recurso) em v1/enterprises.")
                return {"results": [{"id": 103, "name": "NOME DA OBRA 103"}]}
            if caminho == "v1/companies":
                return [{"id": 5, "name": "CONSTRUTORA", "cnpj": "00"}]
            if caminho == "v1/cost-centers":
                return [{"id": 1049, "name": "CON - X", "idCompany": 5}]
            return []

    for ok in (True, False):
        with patch("conexao.get_conn", return_value=conn), patch("sienge_api.credenciais", return_value=("u", "p", "http://x")), patch("sienge_api.Cliente", return_value=Cli(ok)):
            at = _tela(conn).run()
            at.button(key="pn2_btn_cad").click().run()
        assert not at.exception, at.exception
        assert any("Cadastros atualizados" in s.value for s in at.success)             # empresas/centros gravados nos dois casos
        if ok:
            assert any("Obras do Sienge atualizadas: 1" in s.value for s in at.success)
            assert any("batem" in e.label for e in at.expander)
        else:
            assert any("Não consegui ler as obras do Sienge" in w.value for w in at.warning)
    assert _contar(conn, "pnl_empresa_sienge") == 1 and _contar(conn, "pnl_obra_sienge") == 1


def test_carimbo_muda_quando_entra_carga_ou_regra(conn):
    c0 = P.carimbo_dados(conn)
    assert c0 and c0 == P.carimbo_dados(conn)                # estavel enquanto nada muda
    _ingerir(conn)                                           # carga do Sienge
    c1 = P.carimbo_dados(conn)
    assert c1 != c0
    P.registrar_log(conn, "TESTE_CARIMBO")                   # qualquer evento registrado
    assert P.carimbo_dados(conn) != c1


def test_carimbo_devolve_vazio_se_o_banco_falhar():
    class Quebrada:
        def cursor(self):
            raise RuntimeError("sem banco")
    assert P.carimbo_dados(Quebrada()) == ""


# ---------------------------------------------------------------- 21/10/2026: periodo livre em Resultado e Obras (soma de meses) e orcamento por periodo
def _ob(linhas):
    for l in linhas:
        l["bdi"] = round(l["receita"] + l["custo"], 2)
    return {"linhas": linhas, "total": {"receita": sum(l["receita"] for l in linhas), "custo": sum(l["custo"] for l in linhas)}}


def test_somar_obras_de_varios_meses():
    m1 = _ob([{"obra": "103", "nome": "ANASTACIO", "receita": 1000.0, "custo": -600.0}, {"obra": "DEM", "nome": "Demais obras (2)", "receita": 200.0, "custo": -250.0, "n": 2}])
    m2 = _ob([{"obra": "103", "nome": "ANASTACIO", "receita": 500.0, "custo": -700.0}, {"obra": "104", "nome": "LOTE 3", "receita": 300.0, "custo": -100.0},
              {"obra": "DEM", "nome": "Demais obras (3)", "receita": 100.0, "custo": -50.0, "n": 3}])
    s = P.somar_obras([m1, None, m2])
    por = {l["obra"]: l for l in s["linhas"]}
    assert s["meses"] == 2 and por["103"]["receita"] == 1500.0 and por["103"]["custo"] == -1300.0 and por["103"]["bdi"] == 200.0 and por["103"]["margem"] == round(200 / 1500, 4)
    assert por["104"]["bdi"] == 200.0 and por["DEM"]["receita"] == 300.0 and por["DEM"]["n"] == 3
    assert s["total"]["receita"] == 2100.0 and s["total"]["custo"] == -1700.0 and s["total"]["bdi"] == 400.0           # soma de tudo, inclusive 'DEM'
    assert s["linhas"][-1]["obra"] == "DEM"                                                                          # demais obras sempre por ultimo
    assert P.somar_obras([]) is None and P.somar_obras([None]) is None
    g = P.agrupar_demais_obras(s, {"104"})                                                   # a regra das 5 maiores vale sobre o periodo somado
    assert {l["obra"] for l in g["linhas"]} >= {"103", "104", "DEM"} and g["total"] == s["total"]


def test_somar_projecoes_e_termos():
    p1 = {"linhas": [{"codigo": "103", "nome": "A", "receita_proj": 1000.0, "receita_real": 900.0, "bdi_proj": 300.0, "bdi_real": 250.0}], "total": {"receita_proj": 1000.0, "receita_real": 900.0, "bdi_proj": 300.0},
          "receita_proj_total": 1000.0, "receita_real_total": 900.0}
    p2 = {"linhas": [{"codigo": "103", "nome": "A", "receita_proj": 500.0, "receita_real": 600.0, "bdi_proj": 100.0, "bdi_real": 150.0}], "total": {"receita_proj": 500.0, "receita_real": 600.0, "bdi_proj": 100.0},
          "receita_proj_total": 500.0, "receita_real_total": 600.0}
    s = P.somar_projecoes([p1, None, p2])
    x = s["linhas"][0]
    assert s["meses"] == 2 and x["receita_proj"] == 1500.0 and x["receita_real"] == 1500.0 and x["desvio"] == 0.0 and x["bdi_real"] == 400.0 and x["desvio_bdi"] == 0.0
    assert s["receita_proj_total"] == 1500.0 and s["total"]["bdi_proj"] == 400.0 and P.somar_projecoes([None]) is None
    t1 = {"mes": "2026-08", "rec": 1000.0, "cus": 700.0, "bdi": 300.0, "adm_real": 100.0, "adm_orc": 90.0, "rec_p": 1100.0, "bdi_p": 330.0}
    t2 = {"mes": "2026-09", "rec": 2000.0, "cus": 1500.0, "bdi": 500.0, "adm_real": 150.0, "adm_orc": 160.0, "rec_p": 1900.0, "bdi_p": 400.0}
    z = P.somar_termos([t1, t2, None])
    assert z["meses"] == ["2026-08", "2026-09"] and z["rec"] == (3000.0, 3000.0) and z["cus"] == (2200.0, 3000.0 - 730.0)
    assert z["bdi"] == (800.0, 730.0) and z["adm"] == (250.0, 250.0) and z["res"] == (550.0, 480.0)
    sem_orc = P.somar_termos([t1, {**t2, "adm_real": None, "adm_orc": None, "rec_p": None, "bdi_p": None}])
    assert sem_orc["adm"] == (None, None) and sem_orc["res"] == (None, None) and sem_orc["rec"] == (3000.0, None) and sem_orc["cus"][1] is None     # falta 1 mes: n/d
    assert P.somar_termos([]) is None


def test_orcamento_resumo_por_periodo_e_contas_do_grupo(conn):
    import importador_orcamento as IO
    from orcamento_sintetico import pdf_orcamento_sintetico
    ro = P.gravar_orcamento(conn, IO.ler_orcamento_adm_pdf(pdf_orcamento_sintetico()), "o.pdf", "9" * 64, "teste@x")
    meses = P.orcamento_ativo(conn)["meses"]
    tudo = P.orcamento_resumo(conn, ro["id"], meses[-1], acumulado=True)
    so_ultimos = P.orcamento_resumo(conn, ro["id"], meses[-1], acumulado=True, mes_ini=meses[-2])
    ultimo = P.orcamento_resumo(conn, ro["id"], meses[-1])
    pen = P.orcamento_resumo(conn, ro["id"], meses[-2])
    assert tudo["total"]["orcado"] > so_ultimos["total"]["orcado"] > 0
    assert round(so_ultimos["total"]["orcado"], 2) == round(ultimo["total"]["orcado"] + pen["total"]["orcado"], 2)       # periodo = soma dos meses
    assert so_ultimos["total"]["realizado"] == round(ultimo["total"]["realizado"] + pen["total"]["realizado"], 2)
    assert P.orcamento_resumo(conn, ro["id"], meses[-1], acumulado=True, mes_ini=meses[-1])["total"] == ultimo["total"]
    assert len(tudo["contas"]) >= len(tudo["acima"]) and all(c["tipo"] in ("R", "M") for c in tudo["contas"])
    assert [c["desvio"] for c in tudo["contas"]] == sorted((c["desvio"] for c in tudo["contas"]), reverse=True)           # maiores estouros primeiro
