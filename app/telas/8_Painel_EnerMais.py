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

aba_sync, aba_desp, aba_regras, aba_log = st.tabs(["Sincronizar com o Sienge", "Despesas (prévia)", "Regras", "Histórico e logs"])

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
    com_banco = st.checkbox("Incluir o movimento bancário (juros, tarifas e outros avisos de lançamento)", value=True, key="pn2_banco",
                            help="Esses lançamentos não vêm nas contas pagas; entram como documento AV (aviso de lançamento) e contam nas Despesas.")
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
            if com_banco:
                with st.spinner("Buscando o movimento bancário…"):
                    rb = P.sincronizar_banco(conn, cli, mes_sync, usuario, mes_fim=mes_ate if mes_ate >= mes_sync else mes_sync)
                if rb["ok"]:
                    st.success(f"movimento bancário: {rb['titulos']} lançamentos sem título, {rb['rateios']} rateios (líquido {F.moeda_br(rb['liquido'])}).")
                else:
                    st.error(f"movimento bancário: {rb['erro']}")
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
                                    "Data": {"M": "M (banco)"}.get(s["tipo_data"], s["tipo_data"]), "Status": s["status"], "Títulos": s["n_titulos"], "Baixas": s["n_baixas"],
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
        _fechados = [m for m in meses_ok if m < f"{dt.date.today().year}-{dt.date.today().month:02d}"] or meses_ok      # padrao: ultimo mes FECHADO
        mes = st.selectbox("Mês", meses_ok, index=meses_ok.index(_fechados[-1]), key="pn2_mes_desp")
        P.garantir_regras_padrao(conn)                   # cria a regra EXCLUI_PREVISAO (proposta) se ainda nao existir
        regras = P.regras_ativas(conn, "DESPESAS")
        prefixos = P.prefixos_excluidos(regras)
        sem_prev = P.exclui_previsao(regras)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT tipo_oper_id, tipo_oper_nome FROM pnl_baixa WHERE tipo_oper_id IS NOT NULL ORDER BY 1")
            opers = cur.fetchall()
            cur.execute("SELECT DISTINCT doc_id FROM pnl_titulo WHERE lado='P' AND doc_id IS NOT NULL ORDER BY 1")
            docs = [r[0] for r in cur.fetchall()]
        with st.expander("Filtros de conferência (só para esta tela; ainda não viram regra)"):
            op_fora = st.multiselect("Tirar tipos de operação da baixa", [o[0] for o in opers], format_func=lambda i: f"{i} · " + next(n for k, n in opers if k == i), key="pn2_op_fora")
            doc_fora = st.multiselect("Tirar tipos de documento", docs, key="pn2_doc_fora")
        with st.expander("O que foi pago neste mês, por tipo de documento, origem, previsão e operação (para achar o que sai)"):
            docs_mes = P.documentos_do_mes(conn, mes)
            st.dataframe(pd.DataFrame([{"Documento": d["doc_id"], "Nome": d["doc_nome"], "Origem": d["origem"], "Previsão": d["previsao"],
                                        "Operação": d["tipo_oper"], "Títulos": d["titulos"], "Baixas": d["baixas"], "Líquido": F.moeda_br(d["liquido"])}
                                       for d in docs_mes]), hide_index=True, width="stretch")
        linhas = P.despesas_do_mes(conn, mes, prefixos, op_fora, doc_fora, sem_previsao=sem_prev)
        total = sum(l["valor"] for l in linhas)
        if sem_prev:
            com_prev = sum(l["valor"] for l in P.despesas_do_mes(conn, mes, prefixos, op_fora, doc_fora, sem_previsao=False))
            st.caption(f"Regra de previsão ligada: já estão fora {F.moeda_br(com_prev - total)} de documentos de previsão (PRV, PCT, PPC, FOPA).")
        k1, k2, k3 = st.columns(3)
        k1.metric("Pago no mês (sem contas de pessoas/encargos/transferências)", F.moeda_br(total), border=True)
        top5 = sum(l["valor"] for l in linhas[:5])
        k2.metric("Top 5 do mês", F.pct_br(top5 / total) if total else "–", border=True)
        k3.metric("Contas com movimento", len(linhas), border=True)
        st.dataframe(pd.DataFrame([{"Conta": l["plano_cod"], "Nome": l["plano_nome"], "Valor": F.moeda_br(l["valor"]),
                                    "% do mês": F.pct_br(l["valor"] / total) if total else "–"} for l in linhas[:25]]), hide_index=True, width="stretch")
        st.caption("Regras aplicadas (aba Regras): " + ("; ".join(f"{r['tipo'].replace('EXCLUI_', '').replace('PLANO_PREFIXO', 'plano')} {r['valor']} ({r['status'].lower()})" for r in regras) or "nenhuma") + ".")
        st.markdown("**Conferir com o CSV do Sienge**")
        arq = st.file_uploader("ExportacaoContasPagas.csv do mês", type=["csv"], key="pn2_csv")
        if arq is not None:
            conteudo = arq.getvalue()
            sha = P.sha256_curto(conteudo)
            try:
                res_csv = P.despesas_do_csv(conteudo, prefixos)
            except ValueError as exc:
                st.error(str(exc))
                P.registrar_log(conn, "CSV_ERRO", "ERRO", usuario, mes, {"arquivo": arq.name, "sha256": sha, "erro": str(exc)[:300]})
                res_csv = None
            if res_csv is not None:
                lido = res_csv.get("mes_dominante")
                opcoes = sorted(set(meses_ok) | ({lido} if lido else set()))
                padrao = lido or mes
                mes_cmp = st.selectbox("Mês da comparação (lido do CSV pela data de pagamento; pode trocar)", opcoes, index=opcoes.index(padrao),
                                       key=f"pn2_mes_cmp_{sha}", help="O app lê o mês no próprio arquivo e já compara com esse mês do Sienge. Se leu errado, escolha o mês certo aqui.")
                if len(res_csv.get("meses", {})) > 1:
                    st.info("Este CSV tem pagamentos de mais de um mês: " + "; ".join(f"{m}: {n} linhas" for m, n in sorted(res_csv["meses"].items())) +
                            f". O mês com mais linhas ({lido}) foi escolhido; confira se é o que você quer.")
                if lido and lido != mes_cmp:
                    st.warning(f"Você escolheu {mes_cmp}, mas o CSV é majoritariamente de {lido}. Se os valores não baterem, é provavelmente por isso.")
                if mes_cmp not in meses_ok:
                    st.error(f"Ainda não há dados do Sienge para {mes_cmp} no banco. Sincronize esse mês na primeira aba.")
                else:
                    linhas_cmp = linhas if mes_cmp == mes else P.despesas_do_mes(conn, mes_cmp, prefixos, op_fora, doc_fora, sem_previsao=sem_prev)
                    cmp = P.comparar_despesas(linhas_cmp, res_csv)
                    dif_total = round(cmp["total_api"] - cmp["total_csv"], 2)
                    a_, b_ = st.columns(2)
                    a_.metric(f"Despesas pela API ({mes_cmp})", F.moeda_br(cmp["total_api"]), border=True)
                    b_.metric("Despesas pelo CSV", F.moeda_br(cmp["total_csv"]), delta=F.moeda_br(dif_total), delta_color="off", border=True)
                    if cmp["contas_com_diferenca"]:
                        st.warning(f"{len(cmp['contas_com_diferenca'])} conta(s) com diferença (aparecem primeiro na tabela).")
                    else:
                        st.success("API e CSV batem em todas as contas.")
                    ordem = sorted(cmp["contas"], key=lambda d: (-abs(d["dif"]) if abs(d["dif"]) > 0.5 else 0, d["plano_cod"]))
                    st.dataframe(pd.DataFrame([{"Conta": d["plano_cod"], "Nome": d["plano_nome"], "API": F.moeda_br(d["api"]), "CSV": F.moeda_br(d["csv"]),
                                                "Diferença": F.moeda_br(d["dif"]), "Confere": "sim" if abs(d["dif"]) <= 0.5 else "NÃO"} for d in ordem]),
                                 hide_index=True, width="stretch")
                    st.download_button("Baixar o resultado da conferência (CSV)", P.csv_conferencia(cmp, mes_cmp), file_name=f"conferencia_despesas_{mes_cmp}.csv",
                                       mime="text/csv", key="pn2_dl_conf")
                    chave_log = f"pn2_logado_{sha}_{mes_cmp}_{int(cmp['total_api'] * 100)}"
                    if not st.session_state.get(chave_log):         # uma linha por arquivo/mes/resultado (nao repete a cada clique na tela)
                        st.session_state[chave_log] = P.registrar_log(
                            conn, "CONFERENCIA_DESPESAS", "INFO" if not cmp["contas_com_diferenca"] else "AVISO", usuario, mes_cmp,
                            {"arquivo": arq.name, "sha256": sha, "mes_lido_do_csv": lido, "mes_comparado": mes_cmp, "total_api": cmp["total_api"], "total_csv": cmp["total_csv"],
                             "diferenca": dif_total, "contas": len(cmp["contas"]), "contas_com_diferenca": len(cmp["contas_com_diferenca"]),
                             "resultado": "bate" if not cmp["contas_com_diferenca"] else "difere", "regra_previsao": bool(sem_prev),
                             "prefixos_excluidos": prefixos, "filtros_tela": {"operacao": list(op_fora), "documento": list(doc_fora)}})

# ------------------------------------------------------------------ regras
with aba_regras:
    st.markdown("Regras usadas para montar cada aba do painel. As marcadas como **proposta** foram deduzidas dos arquivos de setembro e "
                "ainda precisam da confirmação da Suellen.")
    with conn.cursor() as cur:
        cur.execute("SELECT id, area, tipo, valor, descricao, status, alterado_por, alterado_em FROM pnl_regra WHERE ativo ORDER BY area, id")
        rg = cur.fetchall()
    st.dataframe(pd.DataFrame([{"Aba": a, "Regra": t, "Valor": v, "Descrição": d, "Status": s.lower(), "Quem": q, "Quando": e.strftime("%d/%m/%Y")}
                               for _, a, t, v, d, s, q, e in rg]), hide_index=True, width="stretch")
    pend = [(i, f"{a} · {t} · {v}") for i, a, t, v, d, s, q, e in rg if s != "CONFIRMADA"]
    if pend:
        esc = st.multiselect("Confirmar regras (só depois de conferir com o CSV ou com a Suellen)", [i for i, _ in pend],
                             format_func=lambda i: next(n for k, n in pend if k == i), key="pn2_rg_conf")
        if st.button("Confirmar as regras escolhidas", disabled=not esc, key="pn2_rg_btn"):
            n = P.confirmar_regras(conn, esc, usuario or "app")
            st.success(f"{n} regra(s) confirmada(s).")
            st.rerun()
    else:
        st.success("Todas as regras estão confirmadas.")

# ------------------------------------------------------------------ historico e logs
with aba_log:
    st.markdown("Tudo o que o painel faz fica registrado aqui: conferências com o CSV, sincronizações, regras confirmadas e erros. "
                "Só entram contagens, totais, nomes de arquivo e um código de verificação do arquivo (nada de dado de pessoa).")
    if not P.log_instalado(conn):
        st.warning("O histórico ainda não foi ativado no banco. Falta executar o arquivo `sql/v2_log.sql` no Supabase (SQL Editor). "
                   "Até lá o painel funciona normalmente, só não registra.")
    else:
        f1, f2 = st.columns(2)
        nivel = f1.selectbox("Nível", ["Todos", "ERRO", "AVISO", "INFO"], key="pn2_log_nivel")
        acoes = ["Todas"] + sorted({l["acao"] for l in P.ultimos_logs(conn, limite=1000)})
        acao = f2.selectbox("Ação", acoes, key="pn2_log_acao")
        logs = P.ultimos_logs(conn, None if nivel == "Todos" else nivel, None if acao == "Todas" else acao)
        if logs:
            st.dataframe(pd.DataFrame([{"Quando": l["quando"].strftime("%d/%m/%Y %H:%M"), "Quem": l["usuario"] or "", "Nível": l["nivel"], "Ação": l["acao"],
                                        "Mês": l["mes"].strftime("%m/%Y") if l["mes"] else "", "Detalhe": "; ".join(f"{k}={v}" for k, v in l["detalhe"].items())}
                                       for l in logs]), hide_index=True, width="stretch")
            st.download_button("Baixar o histórico (CSV)", P.csv_logs(logs), file_name="historico_painel.csv", mime="text/csv", key="pn2_dl_log")
        else:
            st.info("Nada registrado ainda.")
