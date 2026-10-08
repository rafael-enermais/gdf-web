# -*- coding: utf-8 -*-
"""GDF — Histórico: importações, status, desfazer/reativar e log de eventos. Nada é apagado."""
import pandas as pd
import streamlit as st

import db
import formatacao as F
from auth import usuario_atual
from conexao import empresa_atual, flash, get_conn, mostrar_flash, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Histórico")
mostrar_flash()
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="hist_empresa")

aba_imp, aba_log = st.tabs(["Importações", "Log de eventos"])
with aba_imp:
    imps = db.listar_importacoes(conn, emp["id"])
    if not imps:
        st.info("Nenhuma importação ainda.")
    else:
        tab = pd.DataFrame([{"#": i["id"], "Tipo": "Mês" if i["tipo"] == "MENSAL" else "Acumulado",
                             "Período": F.mes_br(f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}") if i["tipo"] == "MENSAL"
                             else f"{i['periodo_ini']:%d/%m/%Y} a {i['periodo_fim']:%d/%m/%Y}",
                             "Arquivo": i["arquivo_nome"], "Status": i["status"], "Ativa": "sim" if i["ativo"] else "não (desfeita)",
                             "Falhas": int(i["falhas"]), "Importado por": i["importado_por"], "Em": i["importado_em"].strftime("%d/%m/%Y %H:%M")} for i in imps])
        st.dataframe(tab, hide_index=True, use_container_width=True)
        st.divider()
        escolha = st.selectbox("Importação", imps, format_func=lambda i: f"#{i['id']} — {i['arquivo_nome']} ({'ativa' if i['ativo'] else 'inativa'})", key="hist_escolha")
        col1, col2, col3 = st.columns(3)
        if escolha["ativo"]:
            if col1.button("Desfazer (inativar)", key="hist_desfazer"):
                db.definir_ativo(conn, escolha["id"], False, usuario)
                flash("ok", f"Importação #{escolha['id']} desfeita. Os dados ficam guardados e dá para reativar.")
                st.rerun()
        else:
            if col1.button("Reativar", key="hist_reativar"):
                try:
                    db.definir_ativo(conn, escolha["id"], True, usuario)
                    flash("ok", f"Importação #{escolha['id']} reativada.")
                except db.PeriodoJaImportado as exc:
                    flash("warn", f"{exc} Desfaça a outra antes de reativar esta.")
                st.rerun()
        novo = "REVISADA" if escolha["status"] == "RASCUNHO" else "RASCUNHO"
        if col2.button(f"Marcar como {novo.lower()}", key="hist_status"):
            db.definir_status(conn, escolha["id"], novo, usuario)
            st.rerun()
        with st.expander("Conferências desta importação"):
            conf = db.conferencias_da_importacao(conn, escolha["id"])
            if conf:
                st.dataframe(pd.DataFrame([{"": "✅" if c["ok"] else "❌", "Conferência": c["descricao"], "Detalhe": c["detalhe"]} for c in conf]),
                             hide_index=True, use_container_width=True)
            else:
                st.caption("Sem conferências gravadas.")
with aba_log:
    ev = db.listar_eventos(conn, emp["id"])
    if ev:
        st.dataframe(pd.DataFrame([{"Quando": e["criado_em"].strftime("%d/%m/%Y %H:%M"), "Nível": e["nivel"], "Origem": e["origem"],
                                    "Mensagem": e["mensagem"], "Usuário": e["usuario"]} for e in ev]), hide_index=True, use_container_width=True)
    else:
        st.caption("Sem eventos.")
