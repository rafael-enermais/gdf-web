# -*- coding: utf-8 -*-
"""GDF V2 - periodos do Painel da Diretoria (sem streamlit). O painel trabalha com um intervalo de meses 'AAAA-MM' (inicio, fim), os dois inclusive.
Modos: Mes, Ultimos 3 meses, Ultimos 6 meses, Ano ate o mes (padrao, como era o painel), Ultimos 12 meses, Personalizado (de - ate)."""
from __future__ import annotations

MES, TRI, SEM, ANO, DOZE, PERSONALIZADO = "Mês", "Últimos 3 meses", "Últimos 6 meses", "Ano até o mês", "Últimos 12 meses", "Personalizado"
MODOS = (MES, TRI, SEM, ANO, DOZE, PERSONALIZADO)
PADRAO = ANO


def _n(m: str) -> int:
    return int(m[:4]) * 12 + int(m[5:7]) - 1


def _m(n: int) -> str:
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def somar_meses(m: str, k: int) -> str:
    return _m(_n(m) + k)


def meses_entre(ini: str, fim: str) -> list:
    """['AAAA-MM', ...] de ini a fim (inclusive). Vazio se ini > fim."""
    return [_m(i) for i in range(_n(ini), _n(fim) + 1)]


def resolver(modo: str, fim: str, de: str | None = None) -> tuple:
    """(ini, fim) do periodo. `fim` = mes de referencia (ou o 'ate' do personalizado); `de` = inicio do personalizado (se maior que o fim, vale o fim)."""
    if modo == MES:
        return fim, fim
    if modo == TRI:
        return somar_meses(fim, -2), fim
    if modo == SEM:
        return somar_meses(fim, -5), fim
    if modo == DOZE:
        return somar_meses(fim, -11), fim
    if modo == PERSONALIZADO:
        ini = de or fim
        return (ini if ini <= fim else fim), fim
    return f"{fim[:4]}-01", fim                                     # Ano ate o mes (padrao)


def anterior(ini: str, fim: str) -> tuple:
    """Periodo imediatamente anterior, do mesmo tamanho (ex.: out-dez -> jul-set)."""
    k = _n(fim) - _n(ini) + 1
    return somar_meses(ini, -k), somar_meses(ini, -1)


def rot(m: str) -> str:
    return f"{m[5:7]}/{m[:4]}"


def rotulo(ini: str, fim: str) -> str:
    """'10/2026' (um mes) ou '01/2026 a 10/2026'."""
    return rot(fim) if ini == fim else f"{rot(ini)} a {rot(fim)}"


def curto(ini: str, fim: str) -> str:
    """Rotulo curto para cabecalho de coluna: 'Out/26' ou 'Jan–Out/26' ou 'Jan/25–Out/26'."""
    nomes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    a, b = f"{nomes[int(ini[5:7]) - 1]}", f"{nomes[int(fim[5:7]) - 1]}/{fim[2:4]}"
    if ini == fim:
        return b
    return f"{a}–{b}" if ini[:4] == fim[:4] else f"{a}/{ini[2:4]}–{b}"
