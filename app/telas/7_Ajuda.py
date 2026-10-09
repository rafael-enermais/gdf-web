# -*- coding: utf-8 -*-
"""GDF — Ajuda: fluxo do mês, o que fazer quando uma conferência falha, glossário dos indicadores e contato."""
import pandas as pd
import streamlit as st

import ajuda
import relatorio_dados as RD
import tabelas
from auth import usuario_atual
from conexao import CONTATO, sidebar_rodape

usuario_atual()
sidebar_rodape()

st.title("Ajuda")
st.caption("Guia rápido do fluxo, o que fazer quando algo não bate e o significado dos indicadores.")

aba_fluxo, aba_conf, aba_gloss = st.tabs(["Fluxo do mês", "Quando algo não bate", "Glossário"])
with aba_fluxo:
    for n, (titulo, texto) in enumerate(ajuda.FLUXO, 1):
        st.markdown(f"**{n}. {titulo}** — {texto}")
    st.info("Nada é apagado no GDF: importações desfeitas ficam guardadas, edições do mapa ficam no histórico e cada relatório gerado vira uma versão nova.")
with aba_conf:
    st.caption("As conferências rodam sozinhas na importação e nos Demonstrativos. Escolha o grupo que apareceu com ❌.")
    grupo = st.selectbox("Grupo da conferência", list(ajuda.GUIA_CONFERENCIAS), key="ajuda_grupo")
    sig, causa, fazer = ajuda.GUIA_CONFERENCIAS[grupo]
    st.markdown(f"**O que significa:** {sig}")
    st.markdown(f"**Causas prováveis:** {causa}")
    st.markdown(f"**O que fazer:** {fazer}")
    st.divider()
    st.markdown(ajuda.QUANDO_PEDIR_AJUDA)
    st.markdown(f"Contato: **{CONTATO}**")
with aba_gloss:
    exp = RD.EXPLICACAO
    linhas = [{"Indicador": rot, "Como é calculado": formula, "Para que serve": exp.get(chave, "")}
              for rot, chave, _k, formula in tabelas.INDICADORES_LINHAS if chave]
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch", height=35 * (len(linhas) + 1) + 3)
    st.caption("Resultados são acumulados no ano. A receita de construção e a remuneração do ativo de contrato só entram ao final do exercício e/ou na entrada em operação da obra.")
