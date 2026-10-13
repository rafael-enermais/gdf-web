# -*- coding: utf-8 -*-
"""GDF - graficos do Painel com numeros no padrao brasileiro (1.234.567,89), tanto nos eixos quanto na dica (tooltip).
O st.line_chart/st.bar_chart mostram o eixo no padrao americano (1,234,567); aqui o mesmo grafico e' montado em Altair com rotulos proprios."""
from __future__ import annotations

import altair as alt
import pandas as pd

import formatacao as F


def _rotulo_eixo(casas: int) -> str:
    """Expressao Vega: formata o numero do eixo e troca , e . (americano -> brasileiro)."""
    fmt = f",.{casas}f"
    return ("replace(replace(replace(format(datum.value, '" + fmt + "'), regexp(',', 'g'), '§'), regexp('[.]', 'g'), ','), regexp('§', 'g'), '.')")


def _texto(v, casas: int, sufixo: str) -> str:
    return F.num_br(v, casas) + sufixo if pd.notna(v) else "n/d"


def grafico(d: pd.DataFrame, tipo: str, cores: list, casas: int = 0, casas_tip: int = 2, sufixo: str = "", agrupado: bool = False, altura: int = 300) -> alt.Chart:
    """d: colunas = series, indice = meses (categorico ordenado). tipo: 'linha' | 'barra'. Devolve um grafico Altair."""
    ordem = [str(x) for x in d.index.categories] if hasattr(d.index, "categories") else [str(x) for x in d.index]
    longo = d.copy()
    longo.index = [str(x) for x in longo.index]
    longo.index.name = "Mês"
    longo = longo.reset_index().melt(id_vars="Mês", var_name="Série", value_name="Valor")
    longo["Valor (texto)"] = [_texto(v, casas_tip, sufixo) for v in longo["Valor"]]
    series = list(d.columns)
    esc = alt.Scale(domain=series, range=list(cores))
    x = alt.X("Mês:N", sort=ordem, axis=alt.Axis(labelAngle=-60, title=None))
    y = alt.Y("Valor:Q", axis=alt.Axis(labelExpr=_rotulo_eixo(casas), title=None, tickCount=6))
    cor = alt.Color("Série:N", scale=esc, legend=alt.Legend(orient="bottom", title=None))
    dica = [alt.Tooltip("Mês:N"), alt.Tooltip("Série:N"), alt.Tooltip("Valor (texto):N", title="Valor")]
    base = alt.Chart(longo)
    if tipo == "linha":
        gr = base.mark_line(point=alt.OverlayMarkDef(size=40)).encode(x=x, y=y, color=cor, tooltip=dica)
    else:
        enc = dict(x=x, y=y, color=cor, tooltip=dica)
        if agrupado and len(series) > 1:
            enc["xOffset"] = alt.XOffset("Série:N")
        gr = base.mark_bar().encode(**enc)
    return gr.properties(height=altura)
