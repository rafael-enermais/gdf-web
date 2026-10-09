# -*- coding: utf-8 -*-
"""
GDF - Painel: serie mensal de KPIs para estudo e acompanhamento de historico.
Modulo puro (sem banco, sem streamlit): recebe os Balancetes do ano e devolve uma linha por mes.
Cada mes usa o mesmo motor dos Demonstrativos (Balanco, DRE e indicadores), entao os numeros batem com as outras telas.
"""
from __future__ import annotations

import fontes
import motor

MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# chave -> (rotulo, tipo). tipo: R$ | x | %
COLUNAS = {
    "ativo": ("Ativo total", "R$"),
    "caixa": ("Caixa e aplicações", "R$"),
    "divida_bruta": ("Dívida bruta (BNDES)", "R$"),
    "divida_liquida": ("Dívida líquida", "R$"),
    "pl": ("Patrimônio líquido", "R$"),
    "capital_aportado": ("Capital aportado (capital + AFAC)", "R$"),
    "fornec": ("Fornecedores", "R$"),
    "ativo_concessao": ("Ativo de concessão líquido", "R$"),
    "ccl": ("Capital circulante líquido", "R$"),
    "liq_corrente": ("Liquidez corrente", "x"),
    "liq_imediata": ("Liquidez imediata", "x"),
    "endiv_geral": ("Endividamento geral", "%"),
    "pl_ativo": ("PL / Ativo", "%"),
    "custo_constr_mes": ("Custo de construção no mês", "R$"),
    "resultado_mes": ("Resultado líquido do mês", "R$"),
    "resultado_acum": ("Resultado líquido acumulado no ano", "R$"),
    "res_fin_acum": ("Resultado financeiro acumulado no ano", "R$"),
    "variacao_caixa": ("Variação do caixa no mês", "R$"),
    "aporte_mes": ("Aportes de capital no mês", "R$"),
}


def rotulo_mes(chave: str) -> str:
    """'2026-03' -> 'Mar/26'."""
    return f"{MESES_ABREV[int(chave[5:7]) - 1]}/{chave[2:4]}"


def serie_mensal(b: motor.Balancetes, ate: str | None = None) -> list[dict]:
    """Uma linha por mes (janeiro ate' 'ate'). Levanta motor.ErroDados se a sequencia estiver incompleta."""
    meses = [m for m in b.ordem if ate is None or m <= ate]
    if not meses:
        return []
    abertura = None
    linhas = []
    for i, m in enumerate(meses):
        ant = meses[i - 1] if i > 0 else m
        bpm = motor.balanco(b, m, ant)
        bp = bpm["mes_ref"]
        if abertura is None:
            abertura = bpm["abertura"]
        d = motor.dre(b, m)
        ind = motor.indicadores(bp, d["acumulado"])
        ref = linhas[-1] if linhas else {"caixa": abertura["caixa_eq"], "capital_aportado": round(abertura["capital"] + abertura["afac"], 2)}
        caixa = bp["caixa_eq"]
        cap = ind["capital_aportado"]
        linhas.append({
            "periodo": m, "rotulo": rotulo_mes(m),
            "ativo": bp["ativo"], "caixa": caixa,
            "divida_bruta": ind["div_bruta"], "divida_liquida": ind["div_liquida"],
            "pl": bp["pl"], "capital_aportado": cap, "fornec": bp["fornec"], "ativo_concessao": bp["conc_liq"],
            "ccl": ind["ccl"], "liq_corrente": ind["liq_corrente"], "liq_imediata": ind["liq_imediata"],
            "endiv_geral": ind["endiv_geral"], "pl_ativo": ind["pl_ativo"],
            "custo_constr_mes": round(-b.mov(m, "custo_constr"), 2),
            "resultado_mes": d["mes"]["res_liq"], "resultado_acum": d["acumulado"]["res_liq"],
            "res_fin_acum": d["acumulado"]["res_fin"],
            "variacao_caixa": round(caixa - ref["caixa"], 2), "aporte_mes": round(cap - ref["capital_aportado"], 2),
        })
    return linhas


def serie_com_lacunas(mensais: dict, acumulados: dict, mapa, ate: str) -> list[dict]:
    """Igual a serie_mensal, mas sem exigir todos os meses: uma linha por mês do ano (até `ate`) que tenha balancete mensal ou acumulado.
    Cada linha usa fontes.calcular (os mesmos números dos Demonstrativos); o que não dá para calcular fica None (n/d), nunca um valor chutado."""
    ano = ate[:4]
    meses = sorted({m for m in list(mensais) + list(acumulados) if m[:4] == ano and m <= ate})
    linhas = []
    for m in meses:
        r = fontes.calcular(mensais, acumulados, mapa, m)
        bp, d = r["bp"]["mes_ref"], r["d"]
        ant = r["bp"]["abertura"] if m[5:7] == "01" else r["bp"]["mes_ant"]
        ind = motor.indicadores(bp, d["acumulado"])
        caixa, cap = bp["caixa_eq"], ind["capital_aportado"]
        mes_d = d["mes"]
        linhas.append({
            "periodo": m, "rotulo": rotulo_mes(m),
            "ativo": bp["ativo"], "caixa": caixa,
            "divida_bruta": ind["div_bruta"], "divida_liquida": ind["div_liquida"],
            "pl": bp["pl"], "capital_aportado": cap, "fornec": bp["fornec"], "ativo_concessao": bp["conc_liq"],
            "ccl": ind["ccl"], "liq_corrente": ind["liq_corrente"], "liq_imediata": ind["liq_imediata"],
            "endiv_geral": ind["endiv_geral"], "pl_ativo": ind["pl_ativo"],
            "custo_constr_mes": None if mes_d is None else round(-mes_d["custo_constr"], 2),
            "resultado_mes": None if mes_d is None else mes_d["res_liq"],
            "resultado_acum": None if d["acumulado"] is None else d["acumulado"]["res_liq"],
            "res_fin_acum": None if d["acumulado"] is None else d["acumulado"]["res_fin"],
            "variacao_caixa": None if ant is None else round(caixa - ant["caixa_eq"], 2),
            "aporte_mes": None if ant is None else round(cap - (ant["capital"] + ant["afac"]), 2),
            "fonte": r["fonte"], "n_nd": len(r["lacunas"]),
        })
    return linhas


def variacao(linhas: list[dict], chave: str):
    """(valor do ultimo mes, variacao absoluta contra o mes anterior ou None se so' houver um mes)."""
    if not linhas:
        return None, None
    atual = linhas[-1][chave]
    if len(linhas) < 2 or atual is None or linhas[-2][chave] is None:
        return atual, None
    return atual, round(atual - linhas[-2][chave], 4)


def fmt(v, tipo: str) -> str:
    """Formato pt-BR para exibicao (negativo com '−')."""
    import formatacao as F
    if v is None:
        return "–"
    if tipo == "R$":
        return F.moeda_br(v)
    if tipo == "x":
        return F.razao_br(v)
    return F.pct_br(v)


def fmt_kpi(v) -> str:
    """Valor para cartao: a partir de R$ 1 milhao 'R$ 12,3 mi'; abaixo disso o valor cheio."""
    if v is None:
        return "–"
    if abs(v) >= 1e6:
        txt = f"{abs(v) / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return ("−" if v < 0 else "") + f"R$ {txt} mi"
    return fmt(v, "R$")


def delta_txt(v, tipo: str) -> str | None:
    """Texto do delta do st.metric (ASCII '+'/'-' para o Streamlit pintar verde/vermelho)."""
    if v is None:
        return None
    corpo = fmt_kpi(abs(v)) if tipo == "R$" else fmt(abs(v), tipo)
    if round(abs(v), 4) == 0:
        return corpo
    return ("-" if v < 0 else "+") + corpo
