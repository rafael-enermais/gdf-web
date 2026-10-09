# -*- coding: utf-8 -*-
"""Composicao de saldos + dados e PDF do relatorio (sem banco, dados sinteticos)."""
import io
import re

import pdfplumber
import pytest

import composicao as C
import motor
import relatorio_dados as RD
import relatorio_pdf as RP
from dados_sinteticos import gerar_meses

MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)])
EMP = {"id": 1, "codigo": "TESTE", "razao_social": "Empresa Sintetica Ltda", "cnpj": "00.000.000/0001-91"}


def _conta(cl, nome, sal, sint=False):
    return {"id": "1", "sint": sint, "cl": cl, "nome": nome, "ant": 0.0, "deb": 0.0, "cred": 0.0, "sal": sal}


def test_composicao_so_saldo_diferente_de_zero_e_total():
    contas = [_conta("1.1.01.002.001", "Banco  A", 100.0), _conta("1.1.01.002.001", "Banco B", 0.0), _conta("1.1.01.003.001", "Banco A", 50.0),
              _conta("1.1.01.002", "Sintetica", 150.0, sint=True)]
    g = C.calcular(contas)[0]
    assert g["chave"] == "caixa" and g["total"] == 150.0
    nomes = [n for n, _ in g["itens"]]
    assert nomes == ["Banco A", "Banco A (aplicação)"] and [v for _, v in g["itens"]] == [100.0, 50.0]      # B (zero) e sintetica ficam fora


def test_composicao_apelido_e_acionista_capital_mais_afac():
    contas = [_conta("2.4.01.001.900", "Alfa Holding Ltda", 1000.0), _conta("2.4.01.001.909", "Afac - Alfa Holding Ltda", 500.0),
              _conta("2.4.01.001.901", "Beta Ltda", 200.0)]
    cap = [g for g in C.calcular(contas, apelidos={"beta ltda": "Beta"}) if g["chave"] == "capital"][0]
    assert cap["itens"] == [("Alfa Holding Ltda", 1500.0), ("Beta", 200.0)] and cap["total"] == 1700.0


def test_composicao_demais_agrupa_o_resto_e_total_inclui_tudo():
    contas = [_conta("2.1.03.001.001", f"Forn {i:02d}", 100.0 * (i + 1)) for i in range(15)]
    g = [x for x in C.calcular(contas) if x["chave"] == "fornec"][0]
    assert len(g["itens"]) == 11 and g["itens"][-1][0] == "Demais fornecedores (5)" and g["demais"]      # 10 maiores + "demais" (igual ao Excel da contadora)
    assert g["total"] == sum(100.0 * (i + 1) for i in range(15)) and g["n_itens"] == 15
    assert round(sum(v for _, v in g["itens"]), 2) == g["total"]


def test_composicao_divida_por_prazo():
    contas = [_conta("2.1.01.001.001", "Banco X", 10.0), _conta("2.2.01.001.001.001", "Banco X", 90.0)]
    g = [x for x in C.calcular(contas) if x["chave"] == "divida"][0]
    assert g["itens"] == [("Curto prazo", 10.0), ("Longo prazo", 90.0)]


def _ctx(mes="2026-03", **kw):
    per = {k: v for k, v in MESES.items() if k <= mes}
    b = motor.Balancetes(per)
    return RD.montar(EMP, b, mes, motor.balanco(b, mes), motor.dre(b, mes), per[mes], **kw)


def test_dados_do_relatorio_batem_com_o_motor():
    x = _ctx()
    b = motor.Balancetes(MESES)
    bp = motor.balanco(b, "2026-03")
    assert x["bp"]["ativo"][2] == bp["mes_ref"]["ativo"] and x["bp"]["ativo"][0] == bp["abertura"]["ativo"]
    assert abs(x["dre"]["res_liq"][2] - motor.dre(b, "2026-03")["acumulado"]["res_liq"]) < 0.005
    s = x["serie"]
    assert s["rotulos"] == ["Dez/25", "Jan/26", "Fev/26", "Mar/26"] and len(s["caixa"]) == len(s["pl"]) == len(s["bndes"]) == 4
    assert abs(sum(s["resultado_mes"]) - x["dre"]["res_liq"][2]) < 0.05
    assert x["data_base"] == "31/03/2026" and x["periodo_curto"] == "JAN–MAR/2026"


def test_textos_padrao_sem_chaves_vazias_e_com_valores():
    t = RD.textos_padrao(_ctx())
    assert t["dest_1"].startswith("Em 31/03/2026") and "R$" in t["dest_2"]
    assert all(isinstance(v, str) for v in t.values()) and not any(re.search(r"\b(None|nan)\b", v) for v in t.values())


@pytest.mark.parametrize("mes", ["2026-01", "2026-03"])
def test_pdf_gera_11_paginas_deterministico_e_com_status(mes):
    x = _ctx(mes, config={"assinantes": [{"nome": "Pessoa Teste", "cargo": "Contador"}]})
    pdf = RP.gerar_pdf(x, {}, "RASCUNHO", "09/10/2026 10:00")
    assert pdf[:5] == b"%PDF-"
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        assert len(p.pages) == 11
        todo = "\n".join(pg.extract_text() or "" for pg in p.pages)
    assert "RASCUNHO · gerado em 09/10/2026 10:00" in todo and "Empresa Sintetica Ltda" in todo and "Pessoa Teste" in todo
    assert "BALANÇO PATRIMONIAL".lower() in todo.lower() and "ESBOÇO" not in todo
    assert RP.gerar_pdf(x, {}, "RASCUNHO", "09/10/2026 10:00") == pdf          # mesmo dado, mesmo arquivo


def test_pdf_usa_texto_editado_e_ignora_chave_desconhecida():
    x = _ctx()
    pdf = RP.gerar_pdf(x, {"dest_1": "Texto ajustado pela contadora XYZ.", "nao_existe": "lixo"}, "RASCUNHO")
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        todo = "\n".join(pg.extract_text() or "" for pg in p.pages)
    assert "Texto ajustado pela contadora XYZ." in todo and "lixo" not in todo
