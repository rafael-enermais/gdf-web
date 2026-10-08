# -*- coding: utf-8 -*-
"""
GDF - formatacao numerica no padrao brasileiro (ponto = milhar, virgula = decimal).
Negativos sempre com o sinal "−" (U+2212), como no padrao de layout do relatorio.
Modulo puro (sem streamlit/db).
"""
from __future__ import annotations

MENOS = "−"
COR_NEG = "#E9962A"          # laranja dos negativos (padrao de layout)


def _vazio(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)


def num_br(v, casas: int = 2) -> str:
    """1234.5 -> '1.234,50'; -1234.5 -> '−1.234,50'; None -> '–'."""
    if _vazio(v):
        return "–"
    txt = f"{abs(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if round(abs(v), casas) == 0:
        return txt
    return (MENOS if v < 0 else "") + txt


def moeda_br(v, vazio: str = "–") -> str:
    """1234.5 -> 'R$ 1.234,50'; -1234.5 -> '−R$ 1.234,50'."""
    if _vazio(v):
        return vazio
    txt = num_br(abs(v))
    return (MENOS if v < 0 and round(abs(v), 2) != 0 else "") + "R$ " + txt


def pct_br(v, casas: int = 1, vazio: str = "–") -> str:
    """0.949 -> '94,9%'."""
    if _vazio(v):
        return vazio
    return num_br(v * 100, casas) + "%"


def razao_br(v, casas: int = 2, vazio: str = "–") -> str:
    """Indice em 'vezes': 1.348 -> '1,35x'."""
    if _vazio(v):
        return vazio
    return num_br(v, casas) + "x"


def var_pct(novo, base, vazio: str = "–"):
    """Variacao percentual (novo - base) / |base| (vazio quando a base e' zero)."""
    if _vazio(novo) or _vazio(base) or abs(base) < 0.005:
        return vazio
    return pct_br((novo - base) / abs(base))


def mes_br(chave: str) -> str:
    """'2026-08' -> '08/2026'."""
    return f"{chave[5:7]}/{chave[:4]}"
