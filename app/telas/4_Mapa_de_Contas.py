# -*- coding: utf-8 -*-
"""GDF — Mapa de contas: como cada conta do balancete vira uma linha do demonstrativo. Editar = nova linha; a anterior fica inativa (com motivo)."""
import pandas as pd
import streamlit as st

import db
import formatacao as F
import motor
from auth import usuario_atual
from conexao import empresa_atual, flash, get_conn, mostrar_flash, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Mapa de contas")
mostrar_flash()
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="mapa_empresa")
mapa = db.mapa_vigente(conn, emp["id"])
st.caption("Cada chave soma as contas do balancete cujo código começa com os prefixos indicados (vale o prefixo mais específico). "
           "O mapa inicial (v1.0) foi validado com a contabilidade. Ao editar, a linha antiga fica guardada como inativa, com o motivo.")
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

st.subheader("Editar uma linha do mapa")
st.caption("Use quando surgir conta nova ou mudar o plano de contas. A alteração vale para os próximos cálculos dos demonstrativos desta empresa (os balancetes importados não mudam).")
escolha = st.selectbox("Linha", mapa, format_func=lambda m: f"{m[0]} — {m[1]}", key="mapa_linha")
k, rot0, sec0, pref0, nat0 = escolha
with st.form(f"mapa_form_{emp['id']}_{k}"):
    rot_n = st.text_input("Nome da linha no demonstrativo", value=rot0)
    pref_n = st.text_input("Prefixos das contas (separados por vírgula)", value=", ".join(pref0))
    nat_n = None
    if sec0 == "DRE":
        nat_n = st.radio("Natureza", ["D", "C"], index=0 if nat0 != "C" else 1, format_func=lambda x: "despesa / custo" if x == "D" else "receita", horizontal=True)
    motivo = st.text_input("Motivo da alteração (obrigatório)")
    if st.form_submit_button("Salvar alteração"):
        try:
            db.salvar_mapa_linha(conn, emp["id"], k, rot_n, [p for p in pref_n.split(",")], nat_n, usuario, motivo)
            flash("ok", f"Linha '{k}' atualizada. A versão anterior ficou guardada no histórico do mapa.")
            st.rerun()
        except db.MapaInvalido as exc:
            st.error(str(exc))

with st.expander("Histórico de alterações do mapa"):
    hist = db.historico_mapa(conn, emp["id"])
    st.dataframe(pd.DataFrame([{"Chave": h["chave"], "Linha": h["rotulo"], "Prefixos": ", ".join(h["prefixos"]), "Situação": "ativa" if h["ativo"] else "anterior (inativa)",
                                "Por": h["alterado_por"], "Em": h["alterado_em"].strftime("%d/%m/%Y %H:%M"), "Motivo": h["motivo"]} for h in hist]),
                 hide_index=True, use_container_width=True)
