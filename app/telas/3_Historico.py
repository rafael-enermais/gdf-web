# -*- coding: utf-8 -*-
"""GDF — Histórico: importações, status, desfazer/reativar e log de eventos. Nada é apagado."""
import pandas as pd
import streamlit as st

import db
import formatacao as F
from auth import usuario_atual
from fuso import fmt_br
from conexao import empresa_atual, flash, get_conn, mostrar_flash, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Histórico")
mostrar_flash()
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="hist_empresa")

def _rot_mes(i):
    return F.mes_br(f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}") + " — " + i["arquivo_nome"]


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
                             "Falhas": int(i["falhas"]), "Importado por": i["importado_por"], "Em": fmt_br(i["importado_em"])} for i in imps])
        st.dataframe(tab, hide_index=True, width="stretch")
        st.divider()
        # seleciona pelo NUMERO da importacao (o objeto muda a cada edicao e o Streamlit voltaria a selecao para a primeira linha)
        _por_id = {i["id"]: i for i in imps}
        _id = st.selectbox("Importação", list(_por_id), key="hist_escolha",
                           format_func=lambda n: f"#{n} — {_por_id[n]['arquivo_nome']} ({'ativa' if _por_id[n]['ativo'] else 'inativa'})")
        escolha = _por_id[_id]
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
        pend = [i for i in imps if i["ativo"] and i["tipo"] == "MENSAL" and i["status"] == "RASCUNHO" and int(i["falhas"]) == 0]
        if pend:
            with st.expander(f"Marcar vários meses como REVISADA ({len(pend)} em rascunho, sem falhas)"):
                st.caption("Marcar como revisada é a sua confirmação de que o balancete confere com a contabilidade. Só aparecem meses ativos sem conferência com falha; "
                           "os com falha são tratados um a um acima.")
                _pend_id = {i["id"]: i for i in pend}
                marcar = [_pend_id[n] for n in st.multiselect("Meses", list(_pend_id), default=list(_pend_id), key="hist_multi",
                                                                format_func=lambda n: _rot_mes(_pend_id[n]))]
                if st.checkbox("Conferi estes balancetes", key="hist_multi_ok") and marcar and st.button(f"Marcar {len(marcar)} como REVISADA", key="hist_multi_btn"):
                    for i in marcar:
                        db.definir_status(conn, i["id"], "REVISADA", usuario)
                    flash("ok", f"{len(marcar)} importação(ões) marcada(s) como REVISADA.")
                    st.rerun()
        with st.expander("Conferências desta importação"):
            conf = db.conferencias_da_importacao(conn, escolha["id"])
            if conf:
                st.dataframe(pd.DataFrame([{"": "✅" if c["ok"] else "❌", "Conferência": c["descricao"], "Detalhe": c["detalhe"]} for c in conf]),
                             hide_index=True, width="stretch")
            else:
                st.caption("Sem conferências gravadas.")
with aba_log:
    ev = db.listar_eventos(conn, emp["id"])
    if ev:
        st.dataframe(pd.DataFrame([{"Quando": fmt_br(e["criado_em"]), "Nível": e["nivel"], "Origem": e["origem"],
                                    "Mensagem": e["mensagem"], "Usuário": e["usuario"]} for e in ev]), hide_index=True, width="stretch")
    else:
        st.caption("Sem eventos.")
