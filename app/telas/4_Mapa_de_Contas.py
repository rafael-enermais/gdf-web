# -*- coding: utf-8 -*-
"""GDF — Mapa de contas (somente leitura nesta versão): como cada conta do balancete vira uma linha do demonstrativo."""
import pandas as pd
import streamlit as st

import db
import formatacao as F
import motor
from auth import usuario_atual
from conexao import empresa_atual, get_conn, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Mapa de contas")
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="mapa_empresa")
mapa = db.mapa_vigente(conn, emp["id"])
st.caption("Cada chave soma as contas do balancete cujo código começa com os prefixos indicados (vale o prefixo mais específico). "
           "A edição do mapa pela tela será uma próxima versão; por ora o mapa é o v1.0 validado com a contabilidade.")
st.dataframe(pd.DataFrame([{"Chave": k, "Linha do demonstrativo": r, "Seção": "Balanço" if s == "BP" else "DRE", "Prefixos": ", ".join(p),
                            "Natureza": {"D": "despesa/custo", "C": "receita", None: ""}[n]} for k, r, s, p, n in mapa]), hide_index=True, use_container_width=True)

st.subheader("Contas sem chave no mapa")
meses = db.listar_meses_ativos(conn, emp["id"])
if not meses:
    st.caption("Importe um balancete para conferir.")
else:
    mes = st.selectbox("Mês", meses, index=len(meses) - 1, format_func=F.mes_br, key="mapa_mes")
    per = db.periodos_mensais_ativos(conn, emp["id"])[mes]
    b = motor.Balancetes({mes: per}, mapa)
    sem = [c for c in b._an[mes] if b.chave(c["cl"]) is None and c["cl"][0] in "1245" and
           ((abs(c["sal"]) > motor.TOL) if c["cl"][0] in "12" else (abs(c["deb"]) > motor.TOL or abs(c["cred"]) > motor.TOL))]
    if sem:
        st.warning(f"{len(sem)} conta(s) com saldo ou movimento sem chave no mapa — não entram nos demonstrativos.")
        st.dataframe(pd.DataFrame([{"Classificação": c["cl"], "Nome": c["nome"], "Saldo": F.num_br(c["sal"])} for c in sem]), hide_index=True, use_container_width=True)
    else:
        st.success("Toda conta com saldo ou movimento tem chave no mapa.")
