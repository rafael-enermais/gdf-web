# -*- coding: utf-8 -*-
"""GDF - estilo que faz o painel se adaptar ao tamanho da tela (computador, notebook, tablet, celular), sem cortar palavras.

Como funciona (em linguagem simples): o Streamlit espreme as colunas lado a lado ate o texto virar "R." ou "Ano ate o me". Aqui cada linha de colunas
ganha uma LARGURA MINIMA (maior quando ha poucas colunas, menor quando ha muitas); quando nao cabe, a coluna desce para a linha de baixo. A medida usada
e' a largura da area do painel (nao a da janela), entao tambem funciona com o menu lateral aberto ou fechado."""
from __future__ import annotations

import streamlit as st

CSS_LOGO = """
<style>
/* logo da EnerMais maior (menu lateral, tela de login e topo quando o menu esta fechado) */
[data-testid="stSidebarLogo"], [data-testid="stLogo"], [data-testid="stHeaderLogo"]{ height: 4.4rem !important; max-width: 100% !important; width: auto !important; object-fit: contain; }
[data-testid="stSidebarHeader"]{ height: auto !important; min-height: 5.6rem; padding-top: 1.1rem; padding-bottom: .6rem; align-items: flex-start; }
</style>
"""

CSS_PAINEL = """
<style>
/* a area do painel e' a "medida": as regras @container abaixo olham a largura dela, nao a da janela */
[data-testid="stMainBlockContainer"]{ container-type: inline-size; container-name: gdfmain; max-width: 100% !important;
  padding-left: clamp(1rem, 3vw, 3.2rem) !important; padding-right: clamp(1rem, 3vw, 3.2rem) !important; }

/* colunas: cada linha de colunas "dobra" conforme a largura da area do painel (container query), sem espremer o texto.
   6 cartoes: 6 | 3 por linha | 2 | 1     5 cartoes: 5 | 3 | 2 | 1     4 cartoes: 4 | 2 | 1     3 colunas: 3 | 1     2 colunas: 2 | 1 */
[data-testid="stMain"] [data-testid="stHorizontalBlock"]{ row-gap: .85rem; }
[data-testid="stMain"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{ min-width: min(100%, 9rem); }
[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(2):last-child) > [data-testid="stColumn"]{ min-width: min(100%, 25rem); }
@container gdfmain (max-width: 1150px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(6):last-child) > [data-testid="stColumn"]{ flex: 1 1 calc(33.333% - 1rem) !important; min-width: 0 !important; }
}
@container gdfmain (max-width: 1000px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child) > [data-testid="stColumn"]{ flex: 1 1 calc(33.333% - 1rem) !important; min-width: 0 !important; }
}
@container gdfmain (max-width: 860px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(4):last-child) > [data-testid="stColumn"]{ flex: 1 1 calc(50% - 1rem) !important; min-width: 0 !important; }
}
@container gdfmain (max-width: 760px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3):last-child) > [data-testid="stColumn"]{ flex: 1 1 100% !important; min-width: 0 !important; }
}
@container gdfmain (max-width: 700px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child) > [data-testid="stColumn"],
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(6):last-child) > [data-testid="stColumn"]{ flex: 1 1 calc(50% - 1rem) !important; }
}
@container gdfmain (max-width: 440px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(4):last-child) > [data-testid="stColumn"],
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child) > [data-testid="stColumn"],
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(6):last-child) > [data-testid="stColumn"]{ flex: 1 1 100% !important; }
}

/* filtros do topo (Periodo | De | Ate | Atualizar): campos nunca menores que o necessario para ler "Ano ate o mes" e "09/2026" */
.st-key-dir_cab [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{ min-width: min(100%, 10.5rem) !important; }
.gdf-periodo-txt{ color:#5C6091; font-size:.92rem; padding-bottom:.55rem; line-height:1.25; }

/* conta Receita - Custos = BDI - Administracao = Resultado: 5 cartoes + 4 sinais; sem espaco os sinais somem e os cartoes dobram (3 | 2 | 1 por linha) */
.st-key-dir_formula [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(odd){ min-width: min(100%, 9.5rem) !important; }
.st-key-dir_formula [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(even){ min-width: 0 !important; }
@container gdfmain (max-width: 1050px){
  .st-key-dir_formula [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(even){ display: none; }
  .st-key-dir_formula [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(odd){ flex: 1 1 calc(33.333% - 1rem) !important; min-width: 0 !important; }
}
@container gdfmain (max-width: 700px){
  .st-key-dir_formula [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(odd){ flex: 1 1 calc(50% - 1rem) !important; }
}
@container gdfmain (max-width: 440px){
  .st-key-dir_formula [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(odd){ flex: 1 1 100% !important; }
}

/* cartoes (st.metric): o texto quebra em vez de virar "Re..." ; o numero encolhe com a largura */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; overflow-wrap: anywhere; line-height: 1.25; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] *{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; overflow-wrap: anywhere; }
[data-testid="stMetricValue"]{ font-size: clamp(1.3rem, .95rem + 1.1cqw, 2.1rem) !important; line-height: 1.2; }
[data-testid="stMetricDelta"], [data-testid="stMetricDelta"] *{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }

/* titulo e abas */
[data-testid="stMainBlockContainer"] h1{ font-size: clamp(1.8rem, 1.3rem + 1.8cqw, 2.8rem) !important; line-height: 1.15; }

/* graficos e tabelas sempre dentro da coluna */
[data-testid="stVegaLiteChart"], [data-testid="stDataFrame"]{ max-width: 100%; }
@container gdfmain (max-width: 640px){
  [data-testid="stMetricValue"]{ font-size: 1.5rem !important; }
}
</style>
"""


def logo_maior() -> None:
    st.markdown(CSS_LOGO, unsafe_allow_html=True)


def painel_adaptavel() -> None:
    st.markdown(CSS_PAINEL, unsafe_allow_html=True)


def altair(chart, **kw) -> None:
    """st.altair_chart que nao corta texto: legenda e titulo dos eixos ganham limite folgado (o padrao do Vega corta com "…")."""
    st.altair_chart(chart.configure_axis(labelLimit=260, titleLimit=500).configure_legend(labelLimit=520, titleLimit=500, symbolLimit=0), **kw)
