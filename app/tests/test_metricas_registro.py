# -*- coding: utf-8 -*-
"""Registro mensal das metricas (metricas_registro.py + tela 11_Metricas): regras puras, calculo contra Postgres descartavel (dados SINTETICOS) e a tela."""
import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import metricas_registro as M
import painel_db as P
import sienge_api as S
from dados_sienge import _pg
from test_indicadores_pg import HOJE, _gravar, _rec, _tit

APP = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- regras puras (sem banco)
@pytest.mark.parametrize("pct,esperado", [(None, "Sem lançamento"), (100, "No alvo"), (130.5, "No alvo"), (99.9, "Atenção"), (50, "Atenção"), (49.9, "Fora da meta"), (0, "Fora da meta")])
def test_status_por_pct(pct, esperado):
    assert M.status_por_pct(pct) == esperado


def test_pct_zero_regra_do_zero_em_atraso():
    assert M.pct_zero(None, 1000) is None                    # sem dado = sem lancamento
    assert M.pct_zero(0, 5000) == 100.0                      # nada vencido
    assert M.pct_zero(0, None) == 100.0                      # nada vencido e sem total: continua 100%
    assert M.pct_zero(700, 7900) == 91.1                     # proporcional ao total
    assert M.pct_zero(500, 500) == 0.0                       # tudo vencido
    assert M.pct_zero(300, None) == 0.0 and M.pct_zero(300, 0) == 0.0     # falha e sem total: 0%
    assert M.pct_zero(900, 800) == 0.0                       # nunca abaixo de zero


def test_razao_pct():
    assert M.razao_pct(40, 100) == 40.0 and M.razao_pct(1, 3) == 33.3
    assert M.razao_pct(None, 100) is None and M.razao_pct(10, 0) is None and M.razao_pct(10, None) is None


def test_posicao_do_mes_ao_vivo_fim_do_mes_e_futuro():
    assert M.posicao_do_mes("2026-10", HOJE) == (dt.date(2026, 10, 19), dt.date(2026, 10, 20), True)
    assert M.posicao_do_mes("2026-09", HOJE) == (dt.date(2026, 9, 30), dt.date(2026, 9, 30), False)
    with pytest.raises(ValueError):
        M.posicao_do_mes("2026-11", HOJE)


def test_linha_padrao_nao_leva_nome_de_pessoa_nem_de_credor():
    ln = M._linha("I22", "2026-10", M.DONOS["I22"], realizado=1.0)
    assert ln["empresa"] == ln["obra"] == ln["un"] == "" and ln["app_origem"] == "GDF" and ln["origem"] == "medido" and ln["status"] == "Sem lançamento"
    assert set(M.DONOS) == set(M.CALCULADORES)


def test_i03_calcula_mc_pct_e_atingimento_contra_o_previsto(monkeypatch):
    monkeypatch.setattr(M, "_termos_mes", lambda conn, mes: {"rec": 1000.0, "bdi": 400.0, "rec_p": 1000.0, "bdi_p": 500.0, "fonte": "teste"})
    ln = M.calcular_I03(None, "2026-09")[0]
    assert ln["realizado"] == 40.0 and ln["previsto"] == 50.0 and ln["numerador"] == 400.0 and ln["denominador"] == 1000.0
    assert ln["pct_atingimento"] == 80.0 and ln["status"] == "Atenção"


def test_i03_sem_previsto_mostra_o_valor_mas_fica_sem_lancamento_e_sem_dre_nao_inventa(monkeypatch):
    monkeypatch.setattr(M, "_termos_mes", lambda conn, mes: {"rec": 2000.0, "bdi": 500.0, "rec_p": None, "bdi_p": None, "fonte": "teste"})
    ln = M.calcular_I03(None, "2026-09")[0]
    assert ln["realizado"] == 25.0 and ln["pct_atingimento"] is None and ln["status"] == "Sem lançamento"
    monkeypatch.setattr(M, "_termos_mes", lambda conn, mes: None)
    ln = M.calcular_I03(None, "2026-09")[0]
    assert ln["realizado"] is None and ln["status"] == "Sem lançamento"


def test_termos_mes_cai_para_o_dre_resolvido(monkeypatch):
    monkeypatch.setattr(P, "termos_do_mes", lambda conn, mes: None)
    monkeypatch.setattr(M, "_dre_resolvido", lambda conn, mes: ({"valores": {"01": 1000.0, "05": 250.0}}, "Reconstruido pela API do Sienge (a conferir)"))
    t = M._termos_mes(None, "2026-09")
    assert t["rec"] == 1000.0 and t["bdi"] == 250.0 and t["rec_p"] is None and "API" in t["fonte"]
    monkeypatch.setattr(M, "_dre_resolvido", lambda conn, mes: ({"valores": {}}, "Reconstruido pela API do Sienge (a conferir)"))
    assert M._termos_mes(None, "2026-09") is None


def test_um_indicador_que_falha_nao_derruba_os_outros(monkeypatch):
    def quebra(conn, mes, hoje=None):
        raise RuntimeError("banco fora do ar")
    monkeypatch.setitem(M.CALCULADORES, "I22", quebra)
    monkeypatch.setitem(M.CALCULADORES, "I27", lambda conn, mes, hoje=None: [M._linha("I27", mes, M.DONOS["I27"], realizado=0.0, pct_atingimento=100.0)])
    monkeypatch.setitem(M.CALCULADORES, "I03", lambda conn, mes, hoje=None: [])
    linhas, erros = M.calcular_mes(None, "2026-09")
    assert [l["item_id"] for l in linhas] == ["I27"] and list(erros) == ["I22"] and "banco fora do ar" in erros["I22"]


# ---------------------------------------------------------------- contra Postgres descartavel
@pytest.fixture()
def dados(conn):
    rec = lambda cod, nome: [{"financialCategoryId": cod, "financialCategoryName": nome, "financialCategoryRate": 100, "costCenterId": 1, "costCenterName": "CC"}]  # noqa: E731
    receber = [
        _tit(1, 1, "R", "CLIENTE A", "2026-09-01", "2026-09-30", 1000.0, rec("1010101", "Receita"), numero="NF-A"),
        _tit(2, 1, "R", "CLIENTE B", "2026-09-10", "2026-10-30", 500.0, rec("1010101", "Receita"),
             baixas=[{"sequencialNumber": 1, "paymentDate": "2026-10-05", "netAmount": 500.0, "grossAmount": 500.0, "operationTypeId": 2}]),
        _tit(3, 1, "R", "CLIENTE C", "2026-08-01", "2026-09-01", 900.0, rec("1010101", "Receita"), previsao="S"),
        _tit(4, 1, "R", "CLIENTE D", "2026-09-05", "2026-12-15", 200.0, rec("1010101", "Receita")),
    ]
    pagar = [
        _tit(10, 1, "P", "FORN 1", "2026-09-01", "2026-09-11", 100.0, rec("2010104", "Material"), baixas=[_pg(1, "2026-09-11", 100.0)]),
        _tit(11, 1, "P", "FORN 2", "2026-09-01", "2026-09-21", 300.0, rec("2010104", "Material"), baixas=[_pg(1, "2026-09-21", 300.0)]),
        _tit(12, 1, "P", "FORN 3", "2026-08-01", "2026-09-15", 700.0, rec("2010104", "Material")),
    ]
    for i, (venc, pago) in enumerate((("2026-10-01", True), ("2026-11-01", False), ("2026-12-01", False)), start=1):
        pagar.append(_tit(100, i, "P", "TRATON", "2026-01-10", venc, 1000.0, rec("2050101", "Fin. Caminhao Ct 1"), baixas=[_pg(1, venc, 1000.0)] if pago else [], numero="CT1"))
    for i, venc in enumerate(("2026-11-01", "2026-12-01"), start=1):
        pagar.append(_tit(101, i, "P", "TRATON", "2026-01-10", venc, 100.0, rec("2030201", "Juros s/ Fin. Caminhao Ct 1"), numero="CT1J"))
    pagar.append(_tit(102, 1, "P", "BANCO SANTANDER", "2026-03-10", "2027-03-10", 5000.0, rec("2030405", "Banco | Capital de Giro | Ct. 4455667")))
    pagar.append(_tit(103, 1, "P", "BANCO X", "2026-03-10", "2027-03-10", 777.0, rec("2030405", "Banco X | Capital de Giro | Ct. 9999"), previsao="S"))
    _gravar(conn, "R", receber)
    _gravar(conn, "P", pagar)


def test_a_vencer_separa_o_que_vence_nos_proximos_30_dias(conn, dados):
    import indicadores_dados as ID
    r = ID.a_vencer(conn, HOJE - dt.timedelta(days=1), HOJE, 30)
    assert r["receber"]["total"] == 200.0 and r["receber"]["proximos"] == 0.0           # D vence em dezembro
    assert r["pagar"]["total"] == 7200.0 and r["pagar"]["proximos"] == 1100.0 and r["pagar"]["n_proximos"] == 2   # parcela e juros de 01/11; previsao fora
    f = ID.a_vencer(conn, dt.date(2026, 9, 30), dt.date(2026, 9, 30), 30)                # fim de setembro: B ainda nao tinha sido recebido
    assert f["receber"]["total"] == 700.0 and f["receber"]["proximos"] == 500.0
    assert f["pagar"]["proximos"] == 1000.0 and f["pagar"]["n_proximos"] == 1            # parcela de 01/10


def test_i22_e_i27_no_mes_em_andamento(conn, dados):
    r22 = M.calcular_I22(conn, "2026-10", HOJE)[0]
    assert r22["realizado"] == 1000.0 and r22["denominador"] == 1200.0 and r22["status"] == "Sem lançamento" and r22["pct_atingimento"] is None
    det = M.json.loads(r22["detalhe"])
    assert det["posicao"].startswith("ao vivo") and det["n_vencidos"] == 1 and det["a_vencer_total"] == 200.0 and len(det["faixas"]) == 4
    r27 = M.calcular_I27(conn, "2026-10", HOJE)[0]
    assert r27["realizado"] == 700.0 and r27["denominador"] == 7900.0 and r27["pct_atingimento"] == 91.1 and r27["status"] == "Atenção"
    d27 = M.json.loads(r27["detalhe"])
    assert d27["a_vencer_30d"] == 1100.0 and d27["n_a_vencer_30d"] == 2 and d27["n_vencidos"] == 1
    assert "FORN" not in r27["detalhe"] and "CLIENTE" not in r22["detalhe"] and "TRATON" not in r27["detalhe"]      # sem nome de credor/cliente


def test_mes_fechado_usa_o_fim_do_mes(conn, dados):
    r22 = M.calcular_I22(conn, "2026-09", HOJE)[0]
    assert r22["realizado"] == 1000.0 and r22["denominador"] == 1700.0                  # B (500) e D (200) ainda a vencer em 30/09
    assert M.json.loads(r22["detalhe"])["posicao"] == "fim do mês"
    assert M.calcular_I27(conn, "2026-09", HOJE)[0]["denominador"] == 8900.0


def _contar(conn, tabela):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {tabela}")
        return cur.fetchone()[0]


def test_gravar_e_regravar_nao_duplica_e_so_registra_o_que_mudou(conn, dados):
    r1 = M.registrar_mes(conn, "2026-10", "ana@x", HOJE, itens=["I22", "I27"])
    assert (r1["novas"], r1["atualizadas"], r1["iguais"]) == (2, 0, 0) and _contar(conn, "metrica_registro") == 2
    r2 = M.registrar_mes(conn, "2026-10", "ana@x", HOJE, itens=["I22", "I27"])
    assert (r2["novas"], r2["atualizadas"], r2["iguais"]) == (0, 0, 2) and _contar(conn, "metrica_registro_hist") == 0
    # a FORN 3 paga a parcela: o vencido a pagar zera
    _gravar(conn, "P", [_tit(12, 1, "P", "FORN 3", "2026-08-01", "2026-09-15", 700.0, _rec("2010104", "Material"), baixas=[_pg(1, "2026-10-10", 700.0)])], mes="2026-02")
    r3 = M.registrar_mes(conn, "2026-10", "bia@x", HOJE, itens=["I22", "I27"])
    assert (r3["novas"], r3["atualizadas"], r3["iguais"]) == (0, 1, 1) and r3["mudancas"][0]["item_id"] == "I27"
    reg = {l["item_id"]: l for l in M.ler_registro(conn, "2026-10")}
    assert reg["I27"]["realizado"] == 0 and reg["I27"]["pct_atingimento"] == 100 and reg["I27"]["status"] == "No alvo" and reg["I27"]["atualizado_por"] == "bia@x"
    hist = M.ler_historico(conn, "2026-10")
    campos = {h["campo"] for h in hist}
    assert {"realizado", "pct_atingimento", "status"} <= campos and all(h["alterado_por"] == "bia@x" and h["item_id"] == "I27" for h in hist)
    antes = next(h for h in hist if h["campo"] == "realizado")
    assert float(antes["valor_anterior"]) == 700.0 and float(antes["valor_novo"]) == 0.0


def test_linha_corrigida_a_mao_nao_e_sobrescrita(conn, dados):
    M.registrar_mes(conn, "2026-10", "ana@x", HOJE, itens=["I27"])
    with conn.cursor() as cur:
        cur.execute("UPDATE metrica_registro SET origem='manual', realizado=123, atualizado_por='diretoria' WHERE item_id='I27'")
    r = M.registrar_mes(conn, "2026-10", "ana@x", HOJE, itens=["I27"])
    assert r["preservadas_manual"] == 1 and r["atualizadas"] == 0
    reg = M.ler_registro(conn, "2026-10")[0]
    assert reg["origem"] == "manual" and reg["realizado"] == 123 and reg["atualizado_por"] == "diretoria"


def test_chave_unica_por_item_mes_e_dimensao(conn):
    import psycopg2
    base = M._linha("I22", "2026-10", "x", realizado=1.0)
    M.gravar_registro(conn, [base, {**base, "obra": "OBRA-1"}], "ana@x")                    # a mesma metrica por obra e' outra linha
    assert _contar(conn, "metrica_registro") == 2
    with conn.cursor() as cur, pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("INSERT INTO metrica_registro (item_id, periodo, pessoa) VALUES ('I22','2026-10','x')")
    with conn.cursor() as cur, pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("INSERT INTO metrica_registro (item_id, periodo, pessoa, obra) VALUES ('I22','2026-13','x','o')")


def test_instalado(conn):
    assert M.instalado(conn) is True


# ---------------------------------------------------------------- tela
SESSAO = SimpleNamespace(user=SimpleNamespace(email="usuaria@teste"))


def _tela(conn):
    at = AppTest.from_file(str(APP / "telas" / "11_Metricas.py"), default_timeout=30)
    at.session_state["auth_session"] = SESSAO
    return at


def _textos(at):
    return " ".join([m.value for m in at.markdown] + [m.value for m in at.success] + [m.value for m in at.warning] + [m.value for m in at.info] + [m.value for m in at.error])


def test_tela_calcula_sem_gravar_e_depois_grava(conn, dados, monkeypatch):
    monkeypatch.setattr(M, "_termos_mes", lambda c, mes: {"rec": 1000.0, "bdi": 400.0, "rec_p": 1000.0, "bdi_p": 500.0, "fonte": "teste"})
    agora = dt.datetime(2026, 10, 20, 10, 0)
    with patch("conexao.get_conn", return_value=conn), patch("fuso.agora_br", return_value=agora), patch("metricas_registro.agora_br", return_value=agora):
        at = _tela(conn).run()
        assert not at.exception, at.exception
        assert at.selectbox(key="met_mes").value == "2026-10" and any("ao vivo" in i.value for i in at.info)
        at.button(key="met_calc").click().run()
        assert not at.exception, at.exception
        assert any("Prévia" in s.value for s in at.subheader) and _contar(conn, "metrica_registro") == 0         # so' calculou
        previa = at.dataframe[0].value.set_index("Item")
        assert previa.loc["I27", "% atingimento"] == "91,1%" and previa.loc["I27", "Realizado"] == "R$ 700,00" and previa.loc["I22", "Realizado"] == "R$ 1.000,00"
        assert previa.loc["I03", "Realizado"] == "40,0%" and previa.loc["I03", "% atingimento"] == "80,0%"      # pontos -> %, sem multiplicar por 100 de novo
        at.button(key="met_grava").click().run()
        assert not at.exception, at.exception
        assert _contar(conn, "metrica_registro") == 3 and "Registro de 10/2026 gravado" in _textos(at)
        assert {l["item_id"] for l in M.ler_registro(conn, "2026-10")} == {"I03", "I22", "I27"}


def test_tela_avisa_quando_o_sql_34_nao_foi_rodado(conn):
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE metrica_ocorrencia RENAME TO metrica_ocorrencia_x")
    try:
        with patch("conexao.get_conn", return_value=conn):
            at = _tela(conn).run()
        assert not at.exception and any("SQL-34" in w.value for w in at.warning)
    finally:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE metrica_ocorrencia_x RENAME TO metrica_ocorrencia")
