# -*- coding: utf-8 -*-
"""GDF - formatos pt-BR usados no relatorio PDF e nos textos de leitura (modulo puro). Negativo sempre com "−"."""
from __future__ import annotations


def _n(v, d=2):
    return f"{abs(v):,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def neg(v, d=2):
    return isinstance(v, (int, float)) and round(v, d) < 0


def fnum(v, d=2):
    if v is None or isinstance(v, str):
        return "–"
    return ("−" if neg(v, d) else "") + _n(v, d)


def brl(v, d=2):
    return ("−" if neg(v, d) else "") + "R$ " + _n(v, d)


def mm(v, d=2, sign=False):
    return ("−" if neg(v / 1e6, d) else ("+" if sign and v > 0 else "")) + "R$ " + _n(v / 1e6, d) + " MM"


def mmn(v, d=1):
    return ("−" if neg(v / 1e6, d) else "") + _n(v / 1e6, d)


def pct(v, d=1, sign=False):
    if v is None:
        return "–"
    return ("−" if neg(v * 100, d) else ("+" if sign and v > 0 else "")) + _n(v * 100, d) + "%"


def varp(v):
    if v is None or isinstance(v, str):
        return "–"
    if abs(v) > 9.99:
        return "n.s."
    return pct(v, 1, sign=True)


def razao(a, b):
    """a / b ou None quando b e' zero."""
    return None if (b is None or abs(b) < 0.005) else a / b
