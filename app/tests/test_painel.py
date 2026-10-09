# -*- coding: utf-8 -*-
"""Painel (serie mensal de KPIs): modulo puro, sem banco. Confere contra o motor e a formatacao."""
import importador_csv as I
import motor
import painel as P
from dados_sinteticos import csv_texto, gerar_meses

CNPJ = "54.800.488/0001-60"
MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)])


def _b(n=3):
    per = {}
    for m in range(1, n + 1):
        ult = {1: "31", 2: "28", 3: "31"}[m]
        _, contas = I.ler_bytes(csv_texto(MESES[f"2026-{m:02d}"], cnpj=CNPJ, ini=f"01/{m:02d}/2026", fim=f"{ult}/{m:02d}/2026"), "x.csv")
        per[f"2026-{m:02d}"] = contas
    return motor.Balancetes(per)


def test_serie_bate_com_o_motor_em_cada_mes():
    b = _b()
    linhas = P.serie_mensal(b)
    assert [l["periodo"] for l in linhas] == ["2026-01", "2026-02", "2026-03"]
    for i, l in enumerate(linhas):
        m = l["periodo"]
        bp = motor.balanco(b, m, linhas[i - 1]["periodo"] if i else m)["mes_ref"]
        d = motor.dre(b, m)
        assert l["ativo"] == bp["ativo"] and l["pl"] == bp["pl"] and l["caixa"] == bp["caixa_eq"]
        assert l["resultado_acum"] == d["acumulado"]["res_liq"] and l["resultado_mes"] == d["mes"]["res_liq"]
        assert abs(l["ativo"] - (bp["pc"] + bp["pnc"] + bp["pl"])) < 0.01


def test_resultado_acumulado_e_soma_dos_meses_e_caixa_encadeia():
    linhas = P.serie_mensal(_b())
    assert round(sum(l["resultado_mes"] for l in linhas), 2) == linhas[-1]["resultado_acum"]
    assert round(sum(l["variacao_caixa"] for l in linhas[1:]), 2) == round(linhas[-1]["caixa"] - linhas[0]["caixa"], 2)
    assert [l["rotulo"] for l in linhas] == ["Jan/26", "Fev/26", "Mar/26"]


def test_ate_corta_a_serie_e_vazio():
    assert [l["periodo"] for l in P.serie_mensal(_b(), "2026-02")] == ["2026-01", "2026-02"]
    assert P.serie_mensal(motor.Balancetes({})) == []


def test_sem_janeiro_levanta_erro():
    b = _b()
    b2 = motor.Balancetes({k: v for k, v in b.p.items() if k != "2026-01"})
    try:
        P.serie_mensal(b2)
        assert False
    except motor.ErroDados:
        pass


def test_variacao_e_formatos():
    linhas = P.serie_mensal(_b())
    v, dv = P.variacao(linhas, "caixa")
    assert v == linhas[-1]["caixa"] and dv == round(linhas[-1]["caixa"] - linhas[-2]["caixa"], 4)
    assert P.variacao(linhas[:1], "caixa")[1] is None and P.variacao([], "caixa") == (None, None)
    assert P.fmt_kpi(12_345_678) == "R$ 12,3 mi" and P.fmt_kpi(-3_200_000) == "−R$ 3,2 mi" and P.fmt_kpi(1234.5) == "R$ 1.234,50"
    assert P.delta_txt(-3_200_000, "R$") == "-R$ 3,2 mi" and P.delta_txt(2950, "R$") == "+R$ 2.950,00" and P.delta_txt(None, "R$") is None
    assert P.delta_txt(0.05, "x") == "+0,05x" and P.fmt(0.5163, "%") == "51,6%" and P.fmt(None, "x") == "–"
