# -*- coding: utf-8 -*-
"""GDF — Métricas do mês: calcula os indicadores do painel de metas (I03, I22, I27) e grava o registro mensal. Só para editores (o menu do visualizador não tem esta tela)."""
import pandas as pd
import streamlit as st

import formatacao as F
import metricas_registro as M
import periodo as PER
from auth import usuario_atual
from conexao import flash, get_conn, mostrar_flash, sidebar_rodape
from fuso import agora_br, fmt_br

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Métricas do mês")
mostrar_flash()
st.caption("Calcula os indicadores que o GDF entrega ao painel de metas e guarda o resultado mês a mês. "
           "O que já foi gravado só muda se o número mudar, e toda mudança fica no histórico. Linhas corrigidas à mão não são sobrescritas.")

if not M.instalado(conn):
    st.warning("As tabelas do registro mensal ainda não existem no banco (rode o SQL-34 no Supabase).")
    st.stop()

hoje = agora_br().date()
atual = f"{hoje.year}-{hoje.month:02d}"
meses = [PER.somar_meses(atual, -k) for k in range(0, 13)]
mes = st.selectbox("Mês", meses, format_func=F.mes_br, key="met_mes")
if mes == atual:
    st.info("Mês em andamento: as posições de contas a pagar e a receber são **ao vivo** (até hoje). Quando o mês fechar, grave de novo para fixar o fim do mês.")


def _pct(v):
    """O registro guarda o % em pontos (43.8 = 43,8%); o formatador do app espera fração (0.438)."""
    return F.pct_br(None if v is None else float(v) / 100.0)


def _quadro(linhas: list) -> pd.DataFrame:
    def valor(l):
        if l["item_id"] == "I03":
            return _pct(l["realizado"])
        return F.moeda_br(None if l["realizado"] is None else float(l["realizado"]))
    return pd.DataFrame([{"Item": l["item_id"], "Dono (área)": l["pessoa"], "Meta": l["meta"] or "–", "Realizado": valor(l),
                          "% atingimento": _pct(l["pct_atingimento"]), "Status": l["status"], "Origem": l["origem"]} for l in linhas])


col1, col2 = st.columns(2)
if col1.button("Calcular (sem gravar)", key="met_calc"):
    linhas, erros = M.calcular_mes(conn, mes)
    st.session_state["met_previa"] = {"mes": mes, "linhas": linhas, "erros": erros}
if col2.button("Calcular e gravar no registro", type="primary", key="met_grava"):
    res = M.registrar_mes(conn, mes, usuario)
    partes = [f"{res['novas']} nova(s)", f"{res['atualizadas']} atualizada(s)", f"{res['iguais']} sem mudança"]
    if res["preservadas_manual"]:
        partes.append(f"{res['preservadas_manual']} preservada(s) por estarem corrigidas à mão")
    flash("ok", f"Registro de {F.mes_br(mes)} gravado: " + ", ".join(partes) + ".")
    for item, msg in res["erros"].items():
        flash("warn", f"{item} não foi calculado: {msg}")
    st.session_state.pop("met_previa", None)
    st.rerun()

previa = st.session_state.get("met_previa")
if previa and previa["mes"] == mes:
    st.subheader("Prévia (ainda não gravada)")
    st.dataframe(_quadro(previa["linhas"]), hide_index=True, width="stretch")
    for item, msg in previa["erros"].items():
        st.warning(f"{item} não foi calculado: {msg}")

st.subheader(f"Registro gravado — {F.mes_br(mes)}")
gravado = M.ler_registro(conn, mes)
if not gravado:
    st.info("Nada gravado para este mês ainda.")
else:
    st.dataframe(_quadro(gravado), hide_index=True, width="stretch")
    st.caption("Última gravação: " + fmt_br(max(l["atualizado_em"] for l in gravado)) + " por " + max(gravado, key=lambda l: l["atualizado_em"])["atualizado_por"])
    with st.expander("Detalhe de cada linha"):
        for l in gravado:
            st.markdown(f"**{l['item_id']}** — {l['detalhe'] or '–'}")
    hist = M.ler_historico(conn, mes)
    with st.expander(f"Histórico de mudanças ({len(hist)})"):
        if hist:
            st.dataframe(pd.DataFrame([{"Item": h["item_id"], "Campo": h["campo"], "Antes": h["valor_anterior"], "Depois": h["valor_novo"], "Motivo": h["motivo"],
                                        "Quem": h["alterado_por"], "Quando": fmt_br(h["alterado_em"])} for h in hist]), hide_index=True, width="stretch")
        else:
            st.caption("Nenhuma mudança depois da primeira gravação.")
