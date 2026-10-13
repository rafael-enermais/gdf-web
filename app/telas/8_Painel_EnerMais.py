# -*- coding: utf-8 -*-
"""GDF V2 — Painel EnerMais (EM CONSTRUCAO): sincroniza o Sienge, confere com o CSV e mostra a previa da aba Despesas.
As demais abas (Resultado, Obras, Administracao, Pessoas) e o PDF entram nas proximas etapas."""
import pandas as pd
import datetime as dt

import streamlit as st

import formatacao as F
import painel_db as P
import sienge_api as S
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Painel EnerMais")
st.caption("Em construção (V2): aqui o painel de resultados do Grupo EnerMais passa a ser montado direto com os dados do Sienge. "
           "Por enquanto: sincronizar o Sienge, conferir com o CSV de contas pagas e ver uma prévia da aba Despesas.")

if not P.v2_instalado(conn):
    st.warning("As tabelas do Painel (V2) ainda não foram criadas no banco. Falta executar o arquivo `sql/v2_painel_schema.sql` "
               "no Supabase (SQL Editor). Depois disso esta tela passa a funcionar.")
    st.stop()

aba_sync, aba_desp, aba_regras = st.tabs(["Sincronizar com o Sienge", "Despesas (prévia)", "Regras"])

# ------------------------------------------------------------------ sincronizar
with aba_sync:
    st.markdown("Busca no Sienge as **contas pagas** e **a receber** do período e grava no banco (nada é apagado; cada busca fica registrada). "
                "O app só **consulta** o Sienge; nunca grava nada lá.")
    _hoje = dt.date.today()
    c1, c1b, c2 = st.columns([1, 1, 2])
    mes_sync = c1.text_input("De (AAAA-MM)", value=f"{_hoje.year - 1}-{_hoje.month:02d}", key="pn2_mes_sync")
    mes_ate = c1b.text_input("Até (AAAA-MM)", value=f"{_hoje.year}-{_hoje.month:02d}", key="pn2_mes_ate", help="Igual ao 'De' = um mês só. Mais de um mês = uma busca só para a janela inteira.")
    tipos = c2.multiselect("Tipos de data a buscar", ["P", "I", "D"], default=["P", "I"], key="pn2_tipos",
                           help="P = pagamento/recebimento (Despesas e Realizado) · I = emissão (DRE comprometido) · D = vencimento")
    b1, b2 = st.columns(2)
    if b1.button("Buscar no Sienge", type="primary", key="pn2_btn_sync"):
        try:
            user, pwd, base = S.credenciais(st.secrets)
            cli = S.Cliente(user, pwd, base)
            with st.spinner("Falando com o Sienge… (de 1 a 3 minutos; os últimos 365 dias são buscados de uma vez)"):
                res = P.sincronizar_mes(conn, cli, mes_sync, usuario, tipos=tuple(tipos), mes_fim=mes_ate if mes_ate >= mes_sync else mes_sync)
            for r in res:
                lado = "a pagar" if r["lado"] == "P" else "a receber"
                if r["ok"]:
                    st.success(f"{lado} · data {r['tipo']}: {r['titulos']} títulos, {r['baixas']} baixas, {r['rateios']} rateios (líquido das baixas {F.moeda_br(r['liquido'])}).")
                else:
                    st.error(f"{lado} · data {r['tipo']}: {r['erro']}")
        except S.ErroSienge as exc:
            st.error(str(exc))
    if b2.button("Atualizar cadastros (empresas, centros de custo, plano)", key="pn2_btn_cad"):
        try:
            user, pwd, base = S.credenciais(st.secrets)
            cli = S.Cliente(user, pwd, base)
            with st.spinner("Buscando cadastros…"):
                cont = P.gravar_cadastros(conn, S.normalizar_cadastros(S.buscar_cadastros(cli)))
            st.success("Cadastros atualizados: " + ", ".join(f"{k} {v}" for k, v in cont.items()) + ".")
        except S.ErroSienge as exc:
            st.error(str(exc))
    st.markdown("**Últimas sincronizações**")
    syncs = P.ultimas_syncs(conn)
    if syncs:
        st.dataframe(pd.DataFrame([{"#": s["id"], "Mês": s["mes"].strftime("%m/%Y"), "Lado": "pagar" if s["lado"] == "P" else "receber",
                                    "Data": s["tipo_data"], "Status": s["status"], "Títulos": s["n_titulos"], "Baixas": s["n_baixas"],
                                    "Rateios": s["n_rateios"], "Líquido": F.moeda_br(s["valor_liquido"]) if s["valor_liquido"] is not None else "–",
                                    "Quem": s["usuario"], "Erro": s["erro"] or ""} for s in syncs]), hide_index=True, width="stretch")
    else:
        st.info("Ainda não houve sincronização.")

# ------------------------------------------------------------------ despesas (previa)
with aba_desp:
    meses_ok = P.meses_com_dados(conn)
    if not meses_ok:
        st.info("Sincronize primeiro as contas pagas (data P) de um mês na aba ao lado.")
    else:
        mes = st.selectbox("Mês", meses_ok, index=len(meses_ok) - 1, key="pn2_mes_desp")
        regras = P.regras_ativas(conn, "DESPESAS")
        prefixos = P.prefixos_excluidos(regras)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT tipo_oper_id, tipo_oper_nome FROM pnl_baixa WHERE tipo_oper_id IS NOT NULL ORDER BY 1")
            opers = cur.fetchall()
            cur.execute("SELECT DISTINCT doc_id FROM pnl_titulo WHERE lado='P' AND doc_id IS NOT NULL ORDER BY 1")
            docs = [r[0] for r in cur.fetchall()]
        with st.expander("Filtros de conferência (só para esta tela; ainda não viram regra)"):
            op_fora = st.multiselect("Tirar tipos de operação da baixa", [o[0] for o in opers], format_func=lambda i: f"{i} · " + next(n for k, n in opers if k == i), key="pn2_op_fora")
            doc_fora = st.multiselect("Tirar tipos de documento", docs, key="pn2_doc_fora")
        linhas = P.despesas_do_mes(conn, mes, prefixos, op_fora, doc_fora)
        total = sum(l["valor"] for l in linhas)
        k1, k2, k3 = st.columns(3)
        k1.metric("Pago no mês (sem contas de pessoas/encargos/transferências)", F.moeda_br(total), border=True)
        top5 = sum(l["valor"] for l in linhas[:5])
        k2.metric("Top 5 do mês", F.pct_br(top5 / total) if total else "–", border=True)
        k3.metric("Contas com movimento", len(linhas), border=True)
        st.dataframe(pd.DataFrame([{"Conta": l["plano_cod"], "Nome": l["plano_nome"], "Valor": F.moeda_br(l["valor"]),
                                    "% do mês": F.pct_br(l["valor"] / total) if total else "–"} for l in linhas[:25]]), hide_index=True, width="stretch")
        st.caption("Regras aplicadas (aba Regras): " + ("; ".join(f"{r['valor']} ({r['status'].lower()})" for r in regras) or "nenhuma") + ".")
        st.markdown("**Conferir com o CSV do Sienge**")
        arq = st.file_uploader("ExportacaoContasPagas.csv do mês", type=["csv"], key="pn2_csv")
        if arq is not None:
            try:
                res_csv = P.despesas_do_csv(arq.getvalue(), prefixos)
                cmp = P.comparar_despesas(linhas, res_csv)
                a, b = st.columns(2)
                a.metric("Despesas pela API", F.moeda_br(cmp["total_api"]), border=True)
                b.metric("Despesas pelo CSV", F.moeda_br(cmp["total_csv"]), delta=F.moeda_br(cmp["total_api"] - cmp["total_csv"]), delta_color="off", border=True)
                if cmp["contas_com_diferenca"]:
                    st.warning(f"{len(cmp['contas_com_diferenca'])} conta(s) com diferença. As maiores:")
                    st.dataframe(pd.DataFrame([{"Conta": d["plano_cod"], "Nome": d["plano_nome"], "API": F.moeda_br(d["api"]), "CSV": F.moeda_br(d["csv"]),
                                                "Diferença": F.moeda_br(d["dif"])} for d in cmp["contas_com_diferenca"][:30]]), hide_index=True, width="stretch")
                else:
                    st.success("API e CSV batem em todas as contas.")
            except ValueError as exc:
                st.error(str(exc))

# ------------------------------------------------------------------ regras
with aba_regras:
    st.markdown("Regras usadas para montar cada aba do painel. As marcadas como **proposta** foram deduzidas dos arquivos de setembro e "
                "ainda precisam da confirmação da Suellen.")
    with conn.cursor() as cur:
        cur.execute("SELECT area, tipo, valor, descricao, status, alterado_por, alterado_em FROM pnl_regra WHERE ativo ORDER BY area, id")
        rg = cur.fetchall()
    st.dataframe(pd.DataFrame([{"Aba": a, "Regra": t, "Valor": v, "Descrição": d, "Status": s.lower(), "Quem": q, "Quando": e.strftime("%d/%m/%Y")}
                               for a, t, v, d, s, q, e in rg]), hide_index=True, width="stretch")
