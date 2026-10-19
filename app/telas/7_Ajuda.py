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

aba_fluxo, aba_conf, aba_gloss, aba_v2 = st.tabs(["Fluxo do mês", "Quando algo não bate", "Glossário", "Painel EnerMais (V2)"])
with aba_fluxo:
    for n, (titulo, texto) in enumerate(ajuda.FLUXO, 1):
        st.markdown(f"**{n}. {titulo}** — {texto}")
        for item in ajuda.FLUXO_DETALHES.get(titulo, []):
            st.markdown(f"- {item}")
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
    exp = {k: v.replace("{no_escopo}", "no ano").replace("{escopo}", "do ano") for k, v in RD.EXPLICACAO.items()}      # glossario fala do ano inteiro
    linhas = [{"Indicador": tabelas.escopo_txt(rot), "Como é calculado": tabelas.escopo_txt(formula), "Para que serve": exp.get(chave, "")}
              for rot, chave, _k, formula in tabelas.INDICADORES_LINHAS if chave]
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch", height=35 * (len(linhas) + 1) + 3)
    st.caption("Resultados são acumulados no ano. A receita de construção e a remuneração do ativo de contrato só entram ao final do exercício e/ou na entrada em operação da obra.")
with aba_v2:
    st.caption("O Painel EnerMais é separado do balancete: aqui valem os dados do Sienge e os arquivos enviados na aba Importações (V2).")
    for n, (titulo, texto) in enumerate(ajuda.FLUXO_V2, 1):
        st.markdown(f"**{n}. {titulo}** — {texto}")
    st.divider()
    st.markdown("**Quando algo não bate no Painel EnerMais**")
    situ = st.selectbox("O que aconteceu", list(ajuda.GUIA_V2), key="ajuda_v2_situ")
    sig2, causa2, fazer2 = ajuda.GUIA_V2[situ]
    st.markdown(f"**O que significa:** {sig2}")
    st.markdown(f"**Causas prováveis:** {causa2}")
    st.markdown(f"**O que fazer:** {fazer2}")
    st.info("Nada é apagado: importações desfeitas ficam guardadas, edições ficam registradas (antes, depois, quem, quando) e confirmações antigas do DRE continuam no histórico.")
