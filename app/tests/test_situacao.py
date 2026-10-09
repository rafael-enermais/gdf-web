# -*- coding: utf-8 -*-
"""Quadro de situacao do ano, guia de ajuda e textos padrao em casos-limite (modulos puros, sem banco)."""
from datetime import date

import ajuda
import importador_csv as I
import motor
import relatorio_dados as RD
import situacao
from dados_sinteticos import csv_texto, gerar_meses

CNPJ = "54.800.488/0001-60"


def _imp(mes, status="REVISADA", falhas=0, ativo=True, tipo="MENSAL", ano=2026):
    return {"tipo": tipo, "periodo_fim": date(ano, mes, 28), "ativo": ativo, "status": status, "falhas": falhas}


def _rel(mes, versao, status):
    return {"periodo": date(2026, mes, 1), "versao": versao, "status": status}


def test_quadro_doze_meses_e_melhor_relatorio():
    q = situacao.quadro(2026, [_imp(1), _imp(2, "RASCUNHO", 2), _imp(3, ativo=False)], [_rel(1, 1, "RASCUNHO"), _rel(1, 2, "ASSINADO"), _rel(1, 3, "RASCUNHO")])
    assert len(q) == 12 and q[0]["rotulo"] == "Jan/26"
    assert q[0]["importado"] and q[0]["relatorio"] == "v2 ASSINADO"          # melhor status vence a versao mais nova
    assert q[1]["status"] == "RASCUNHO" and q[1]["falhas"] == 2
    assert not q[2]["importado"] and q[2]["status"] == "–" and q[2]["falhas"] is None
    assert situacao.anos_com_dados([_imp(1), _imp(1, ano=2025), _imp(2, tipo="ACUMULADO", ano=2027)]) == [2026, 2025]


def test_proxima_acao_cobre_cada_situacao():
    def acao(imps, rels=()):
        return situacao.proxima_acao(situacao.quadro(2026, imps, list(rels)))
    assert "janeiro" in acao([])
    assert "Faltam balancetes no meio" in acao([_imp(1), _imp(3)]) and "Fev/26" in acao([_imp(1), _imp(3)])
    assert "conferências com falha" in acao([_imp(1, falhas=1)])
    assert "REVISADA" in acao([_imp(1, "RASCUNHO")])
    assert "Gere o relatório de Fev/26" in acao([_imp(1), _imp(2)])
    assert "versão final" in acao([_imp(1)], [_rel(1, 1, "RASCUNHO")])
    assert "em dia" in acao([_imp(1)], [_rel(1, 1, "ASSINADO")])
    assert "em dia" in acao([_imp(1)], [_rel(1, 1, "REVISADO")])             # assinatura e' opcional


def test_guia_cobre_todos_os_grupos_de_conferencia():
    M = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100)])
    per = {}
    for m in (1, 2):
        _, per[f"2026-{m:02d}"] = I.ler_bytes(csv_texto(M[f"2026-{m:02d}"], cnpj=CNPJ, ini=f"01/{m:02d}/2026", fim=f"{'31' if m == 1 else '28'}/{m:02d}/2026"), "x.csv")
    b = motor.Balancetes(per)
    grupos = {c["grupo"] for c in motor.conferencias(b)} | {"arquivo"}
    _, acum = I.ler_bytes(csv_texto(M["2026-02"], cnpj=CNPJ, ini="01/01/2026", fim="28/02/2026"), "a.csv")
    grupos |= {c["grupo"] for c in motor.conferir_acumulado(b, acum, "2026-02")}
    assert grupos <= set(ajuda.GUIA_CONFERENCIAS), grupos - set(ajuda.GUIA_CONFERENCIAS)
    assert all(len(v) == 3 and all(v) for v in ajuda.GUIA_CONFERENCIAS.values())


def _ctx(spec, meses, extra=None):
    M = gerar_meses(spec)
    per = {}
    for m in range(1, meses + 1):
        ult = {1: "31", 2: "28", 3: "31"}[m]
        _, per[f"2026-{m:02d}"] = I.ler_bytes(csv_texto(M[f"2026-{m:02d}"], cnpj=CNPJ, ini=f"01/{m:02d}/2026", fim=f"{ult}/{m:02d}/2026"), "x.csv")
    b = motor.Balancetes(per)
    ref = b.ordem[-1]
    ant = b.ordem[-2] if meses > 1 else ref
    emp = {"cnpj": CNPJ, "razao_social": "Anastácio Transmissora de Energia S.A.", "codigo": "A"}
    return RD.montar(emp, b, ref, motor.balanco(b, ref, ant), motor.dre(b, ref), per[ref], {}, None, {}, None)


def test_textos_nao_dizem_passou_de_x_para_x_nem_caixa_repetido():
    t = RD.textos_padrao(_ctx([(100_000, 5_000, 200), (80_000, 4_000, 100)], 2))
    assert "permaneceu em" in t["dest_2"] and "passou de R$ 3.000.000,00 para R$ 3.000.000,00" not in " ".join(t.values())
    assert "aumento de" in t["dest_2"] and "menor saldo" not in t["evo_1"]
    assert "AFAC de R$ 0,00" not in t["dest_3"] and "dez/25 para R$ 1.000.000,00 em dez/25" not in t["evo_1"]
    assert "O único fornecedor" in t["comp_2"]
