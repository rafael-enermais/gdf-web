# -*- coding: utf-8 -*-
import pytest

import motor
from dados_sinteticos import gerar_meses

OPS = [(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)]


@pytest.fixture(scope="module")
def mensal():
    return motor.Balancetes(gerar_meses(OPS))


@pytest.fixture(scope="module")
def encerrado():
    return motor.Balancetes(gerar_meses(OPS, encerrar_ultimo=True))


def test_conferencias_passam(mensal, encerrado):
    for b in (mensal, encerrado):
        falhas = [c for c in motor.conferencias(b) if not c["ok"]]
        assert not falhas, falhas


def test_balanco_fecha_e_valores(mensal):
    bp = motor.balanco(mensal, "2026-03")
    # abertura: ativo 6.000.000 = BNDES 3.000.000 + capital 3.000.000
    assert bp["abertura"]["ativo"] == bp["abertura"]["passivo_pl"] == 6_000_000
    ref = bp["mes_ref"]
    assert ref["ativo"] == ref["passivo_pl"]
    # resultado acumulado: (5000-100000-200) + (4000-80000-100) + (3000-60000-50) = -228.350
    assert ref["prej"] == -228_350
    assert ref["pl"] == 3_000_000 - 228_350
    assert ref["fornec"] == 240_000


def test_dre_colunas(mensal):
    d = motor.dre(mensal, "2026-03")
    assert d["ate_mes_ant"]["res_liq"] == -171_300
    assert d["mes"]["res_liq"] == -57_050
    assert d["acumulado"]["res_liq"] == -228_350
    assert d["acumulado"]["custo_constr"] == -240_000
    assert d["acumulado"]["rec_fin"] == 12_000
    assert d["acumulado"]["ajustes"] == 0


def test_mes_encerrado_mesmo_resultado(mensal, encerrado):
    assert encerrado.encerrado("2026-03") and not mensal.encerrado("2026-03")
    a, b = motor.dre(mensal, "2026-03"), motor.dre(encerrado, "2026-03")
    assert a["mes"] == b["mes"] and a["acumulado"] == b["acumulado"]
    pa, pb = motor.balanco(mensal, "2026-03"), motor.balanco(encerrado, "2026-03")
    assert pa["mes_ref"]["pl"] == pb["mes_ref"]["pl"]          # o resultado migra da conta 8 para 2.4.13, o PL e' o mesmo


def test_indicadores(mensal):
    bp = motor.balanco(mensal, "2026-03")["mes_ref"]
    d = motor.dre(mensal, "2026-03")["acumulado"]
    ind = motor.indicadores(bp, d)
    assert ind["ccl"] == bp["ac"] - bp["pc"]
    assert ind["div_bruta"] == 3_000_000
    assert ind["liq_corrente"] == pytest.approx(bp["ac"] / bp["pc"])
    assert ind["capital_aportado"] == 3_000_000
    assert ind["res_liq"] == -228_350 and ind["ebit_ebitda"] == d["ebit"]
    assert motor.indicadores(motor.balanco(mensal, "2026-03")["abertura"], None)["res_liq"] is None


def test_sequencia_incompleta_bloqueia():
    meses = gerar_meses(OPS)
    sem_fev = motor.Balancetes({k: v for k, v in meses.items() if k != "2026-02"})
    with pytest.raises(motor.ErroDados, match="02/2026"):
        motor.balanco(sem_fev, "2026-03")
    sem_jan = motor.Balancetes({k: v for k, v in meses.items() if k != "2026-01"})
    with pytest.raises(motor.ErroDados, match="01/2026"):
        motor.dre(sem_jan, "2026-03")
    assert motor.meses_faltando(["2026-01", "2026-04"]) == ["2026-02", "2026-03"]


def test_conferencia_detecta_erro():
    meses = gerar_meses(OPS)
    for c in meses["2026-02"]:
        if c["cl"] == "1.1.01.002.001":
            c["sal"] += 10.0                     # saldo adulterado: nao fecha com o movimento nem com o ativo
    falhas = [c["grupo"] for c in motor.conferencias(motor.Balancetes(meses)) if not c["ok"]]
    assert {"Movimento", "Soma das contas", "Balanço calculado"} <= set(falhas)


def test_conta_sem_mapa_e_apontada():
    meses = gerar_meses(OPS)
    meses["2026-01"].append({"id": "9999", "sint": False, "cl": "1.1.04.099.001", "nome": "Conta nova", "ant": 0, "deb": 0, "cred": 0, "sal": 50.0})
    r = motor.conferencias_arquivo(meses["2026-01"], periodo="2026-01")
    assert any(c["grupo"] == "Mapa de contas" and not c["ok"] and "1.1.04.099.001" in c["detalhe"] for c in r)


def test_acumulado_confere_com_mensais(mensal):
    ate = "2026-03"
    acum = []
    # acumulado sintetico: soma dos 3 meses nas contas de resultado; saldos de balanco do ultimo mes
    ult = {c["id"]: c for c in mensal.p[ate]}
    for c in mensal.p[ate]:
        x = dict(c)
        if c["cl"][0] in "45" or c["cl"] == "8":
            x["deb"] = round(sum(m_["deb"] for p in mensal.ordem for m_ in mensal.p[p] if m_["id"] == c["id"] and m_["cl"] == c["cl"]), 2)
            x["cred"] = round(sum(m_["cred"] for p in mensal.ordem for m_ in mensal.p[p] if m_["id"] == c["id"] and m_["cl"] == c["cl"]), 2)
            x["sal"] = round(sum(m_["sal"] for p in mensal.ordem for m_ in mensal.p[p] if m_["id"] == c["id"] and m_["cl"] == c["cl"]), 2)
        acum.append(x)
    r = motor.conferir_acumulado(mensal, acum, ate)
    assert all(c["ok"] for c in r), r
    # adultera 1 conta de resultado: a diferenca nao e' ajuste -> falha
    for x in acum:
        if x["cl"] == "5.1.05.001.001":
            x["deb"] += 500.0
            x["sal"] += 500.0
    assert any(not c["ok"] for c in motor.conferir_acumulado(mensal, acum, ate))


def test_mapa_alterado_muda_calculo():
    meses = gerar_meses(OPS)
    mapa = [(k, r, s, list(p), n) for k, r, s, p, n in motor.MAPA_PADRAO]
    sem_juros = [m for m in mapa if m[0] != "dep_vista"]      # tira a chave do caixa: a conta fica sem mapa
    b = motor.Balancetes(meses, sem_juros)
    assert motor.balanco(b, "2026-01")["mes_ref"]["dep_vista"] == 0
    assert any(not c["ok"] for c in motor.conferencias(b) if c["grupo"] == "Mapa de contas")
