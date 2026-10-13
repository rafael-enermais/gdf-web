# -*- coding: utf-8 -*-
"""V2 Painel EnerMais: gravacao do Sienge (dados SINTETICOS) + regras + conferencia com CSV, contra Postgres descartavel."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import painel_db as P
import sienge_api as S
from dados_sienge import income, outcome

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
        assert len(at.tabs) == 3
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
