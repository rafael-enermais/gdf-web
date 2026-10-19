# -*- coding: utf-8 -*-
"""GDF V2 — Painel EnerMais (EM CONSTRUCAO): sincroniza o Sienge, confere com o CSV e mostra a previa da aba Despesas.
O PDF do relatorio (rascunho) fica na ultima aba. Todos os uploads ficam na aba Importacoes (V2)."""
import altair as alt
import pandas as pd
import datetime as dt

import streamlit as st

import formatacao as F
import importacoes_ui
import painel_db as P
import sienge_api as S
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape



def _grafico_meses(valores: list, meses: list, nome: str, linha: bool = False):
    """Grafico por mes na ORDEM CRONOLOGICA (o st.bar_chart ordena o texto 'MM/AAAA' em ordem alfabetica e embaralha os anos). Rotulo MM/AAAA."""
    rot = [f"{m[5:]}/{m[:4]}" for m in meses]
    df = pd.DataFrame({"Mês": rot, nome: valores})
    base = alt.Chart(df).encode(x=alt.X("Mês:N", sort=rot, axis=alt.Axis(labelAngle=-90)), y=alt.Y(f"{nome}:Q", title=nome),
                                tooltip=["Mês", alt.Tooltip(f"{nome}:Q", format=",.2f")])
    st.altair_chart((base.mark_line(point=True) if linha else base.mark_bar()), width="stretch")

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

aba_sync, aba_imp, aba_desp, aba_res, aba_obras, aba_adm, aba_pess, aba_regras, aba_log, aba_pdf = st.tabs(
    ["Sincronizar com o Sienge", "Importações (V2)", "Despesas (prévia)", "Resultado (prévia)", "Obras (prévia)", "Administração (prévia)", "Pessoas (prévia)", "Regras", "Histórico e logs",
     "Relatório PDF (rascunho)"])

# ------------------------------------------------------------------ importacoes (todos os uploads da V2, historico, reverter, editar)
with aba_imp:
    importacoes_ui.render(conn, usuario)

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

# ------------------------------------------------------------------ resultado (previa)
with aba_res:
    st.markdown("**DRE oficial** = o PDF do Sienge *Demonstrativo de Resultado – Agrupado por Obra – DRE GERENCIAL* (versão com a composição das contas), lido pelo app. "
                "**Conferência** = o app recalcula o mesmo DRE direto da API do Sienge (títulos **emitidos** no mês) e mostra onde difere, por conta e por obra.")
    meses_em = P.meses_com_emissao(conn)
    meses_dre = P.meses_com_dre(conn)
    meses_r_opts = sorted(set(meses_em) | set(meses_dre))
    if not meses_r_opts:
        st.info("Importe o PDF do DRE gerencial do Sienge na aba **Importações (V2)** ou sincronize as contas por data de emissão (tipo I) na primeira aba.")
    _hj = f"{dt.date.today().year}-{dt.date.today().month:02d}"
    _fech = [m for m in meses_r_opts if m < _hj] or meses_r_opts
    r1, r2, r3, r4 = st.columns([1, 2, 2, 2])
    mes_r = r1.selectbox("Mês", meses_r_opts or [_hj], index=(meses_r_opts.index(_fech[-1]) if meses_r_opts else 0), key="pn2_mes_res")
    sem_prev_r = r2.checkbox("Tirar documentos de previsão (PRV, PCT, PPC, FOPA)", value=True, key="pn2_res_prev",
                             help="Mesma regra das Despesas (confirmada pela contabilidade). Vale para a conferência pela API.")
    sem_dist_r = r4.checkbox("Tirar NFs desfeitas (distrato)", value=True, key="pn2_res_distrato",
                             help="Título a receber cujas baixas do tipo Distrato somam o valor todo: o Sienge ainda o lista na API, mas o DRE dele não conta. Conferido em set/2026.")
    sem_desf_r = st.checkbox("Tirar títulos a pagar desfeitos e multas (cancelados, substituídos, abatidos com adiantamento e tipo AEJ) — regra confirmada pela contabilidade",
                             value=True, key="pn2_res_desfeitos",
                             help="O DRE do Sienge não conta título a pagar cujas baixas de Cancelamento, Substituição ou Abatimento de adiantamento somam o valor todo, nem multas (documento AEJ). "
                                  "Em set/2026 isso reduz a diferença de custo entre a API e o PDF em cerca de R$ 200 mil (sem contar INSS/FGTS em guia). Regra confirmada pela contabilidade em 19/10/2026 (a guia de INSS/FGTS entra depois da emissão do PDF e fica).")
    _cg = P.centro_grupo_instalado(conn)
    so_obras = r3.checkbox("Só centros de custo de obra (sem ADM)", value=_cg, disabled=not _cg, key="pn2_res_obras",
                           help="O DRE gerencial 'por obra' do Sienge não traz os centros de custo da Administração. Usa o de-para centro de custo → obra validado pela contabilidade.")
    if not _cg:
        st.info("O de-para de centros de custo ainda não está no banco; falta executar o SQL do de-para (veja o handoff do projeto). Até lá o filtro de obra fica desligado.")

    # ---- importar o PDF
    imp = P.dre_importacao_ativa(conn, mes_r)
    if imp:
        st.caption(f"DRE oficial de {mes_r}: PDF “{imp['arquivo']}”, importado por {imp['quem'] or '–'} em {imp['quando']:%d/%m/%Y %H:%M} (importação #{imp['id']}).")
        oficial = P.dre_do_mes([{"plano_cod": c, "plano_nome": "", "valor": x} for c, x in P.dre_contas_importadas(conn, imp["id"]).items()])["valores"]
        st.markdown("**DRE oficial (PDF do Sienge)**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Receita bruta", F.moeda_br(oficial["01"]), border=True)
        m2.metric("Custos diretos", F.moeda_br(oficial["04"]), border=True)
        m3.metric("Lucro bruto", F.moeda_br(oficial["05"]), border=True)
        m4.metric("Lucro líquido após investimentos", F.moeda_br(oficial["14"]), border=True)
        st.caption("Resultado das obras (a Administração central vem em outra aba, nas próximas etapas).")

    # ---- confirmar o DRE do mes: por linha, escolher a fonte (API ou PDF)
    st.markdown("**Confirmar o DRE do mês** — escolha, linha a linha, de qual fonte vem o valor")
    from dre_mapa import LINHAS as _LIN
    _folhas = [(k, n) for k, n, t in _LIN if t == "folha"]
    _api_f = P.dre_do_mes(P.resultado_por_conta(conn, mes_r, sem_previsao=sem_prev_r, so_obras=so_obras, sem_distrato=sem_dist_r, sem_desfeitos=sem_desf_r))["valores"] if mes_r in meses_em else None
    _pdf_f = P.dre_do_mes([{"plano_cod": c, "plano_nome": "", "valor": x} for c, x in P.dre_contas_importadas(conn, imp["id"]).items()])["valores"] if imp else None
    _fontes = {}
    if _api_f is not None:
        _fontes["API"] = _api_f
    if _pdf_f is not None:
        _fontes["PDF"] = _pdf_f
    if not _fontes:
        st.info("Sem fonte para este mês: importe o PDF do DRE ou sincronize as contas emitidas (tipo I).")
    else:
        if st.session_state.get("pn2_conf_ok"):
            st.toast(st.session_state["pn2_conf_ok"])
            st.success(st.session_state.pop("pn2_conf_ok"))
        conf = P.confirmacao_ativa(conn, mes_r)
        _padrao = "PDF" if "PDF" in _fontes else "API"
        if not P.confirmacao_instalada(conn):
            st.warning("Falta executar o **SQL-10** (`sql/v2_dre_confirmacao.sql`) no Supabase para gravar a confirmação. Você já pode escolher as fontes e ver o resultado.")
        if conf:
            st.success(f"DRE de {mes_r} confirmado por {conf['quem'] or '–'} em {conf['quando']:%d/%m/%Y %H:%M} (confirmação #{conf['id']})"
                       + (f" — {conf['observacao']}" if conf["observacao"] else "") + ". Se mudar alguma escolha e confirmar de novo, a anterior fica guardada no histórico.")
        def _todos(fonte, mes_=mes_r):
            for k_, _ in _folhas:
                st.session_state[f"pn2_fonte_{mes_}_{k_}"] = fonte
        b1, b2, _ = st.columns([1, 1, 3])
        if "PDF" in _fontes:
            b1.button("Usar PDF em todas", key=f"pn2_todos_pdf_{mes_r}", on_click=_todos, args=("PDF",))
        if "API" in _fontes:
            b2.button("Usar API em todas", key=f"pn2_todos_api_{mes_r}", on_click=_todos, args=("API",))
        st.caption("Se a leitura do PDF falhar (ou você quiser corrigir um valor), escolha **MANUAL** na linha e digite o valor. Só vale para o resultado gerado aqui; "
                   "os dados que vêm da API não são editados. Todo ajuste manual exige uma observação e fica registrado (quem, quando, valor da API e do PDF).")
        cab = st.columns([3, 2, 2, 2, 2, 2])
        for c_, t_ in zip(cab, ["Linha do DRE", "API", "PDF", "Diferença", "Fonte adotada", "Valor manual"]):
            c_.markdown(f"**{t_}**")
        escolha, manuais = {}, {}
        for k_, n_ in _folhas:
            cols = st.columns([3, 2, 2, 2, 2, 2])
            cols[0].write(f"{k_} · {n_}")
            va, vp = (_api_f or {}).get(k_), (_pdf_f or {}).get(k_)
            cols[1].write(F.moeda_br(va) if va is not None else "–")
            cols[2].write(F.moeda_br(vp) if vp is not None else "–")
            if va is not None and vp is not None:
                dif_ = round(va - vp, 2)
                cols[3].write(F.moeda_br(dif_) if abs(dif_) > 0.5 else "confere")
            else:
                cols[3].write("–")
            salvo = ((conf or {}).get("fontes") or {}).get(k_)
            _opcoes = list(_fontes) + ["MANUAL"]
            ini_ = salvo if salvo in _opcoes else _padrao
            escolha[k_] = cols[4].selectbox("Fonte", _opcoes, index=_opcoes.index(ini_), key=f"pn2_fonte_{mes_r}_{k_}", label_visibility="collapsed")
            _ini_man = float(((conf or {}).get("valores") or {}).get(k_, 0.0)) if salvo == "MANUAL" else float(va if va is not None else (vp or 0.0))
            manuais[k_] = cols[5].number_input("Valor manual", value=_ini_man, step=0.01, format="%.2f", key=f"pn2_manual_{mes_r}_{k_}",
                                               disabled=(escolha[k_] != "MANUAL"), label_visibility="collapsed")
        adotado = P.valores_adotados(_fontes, escolha, manuais)
        final = P.dre_de_folhas(adotado)
        fv = final["valores"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Receita bruta (adotada)", F.moeda_br(fv["01"]), border=True)
        m2.metric("Custos diretos (adotado)", F.moeda_br(fv["04"]), border=True)
        m3.metric("Lucro bruto (adotado)", F.moeda_br(fv["05"]), border=True)
        m4.metric("Lucro líquido após investimentos (adotado)", F.moeda_br(fv["14"]), border=True)
        with st.expander("DRE completo com as fontes escolhidas"):
            st.dataframe(pd.DataFrame([{"Linha": k_, "DRE": n_, "Valor adotado": F.moeda_br(x_)} for k_, n_, x_ in final["linhas"]]), hide_index=True, width="stretch")
        obs = st.text_input("Observação (opcional): por que escolheu essas fontes", key=f"pn2_conf_obs_{mes_r}")
        if st.button(f"Confirmar o DRE de {mes_r}", type="primary", disabled=not P.confirmacao_instalada(conn), key=f"pn2_confirmar_{mes_r}"):
            try:
                resumo = {"manuais": P.resumo_manuais(escolha, adotado, _fontes), "lucro_liquido_adotado": fv["14"], "lucro_liquido_api": (P.dre_de_folhas({k_: _api_f.get(k_, 0.0) for k_, _ in _folhas})["valores"]["14"] if _api_f else None),
                          "lucro_liquido_pdf": (_pdf_f or {}).get("14")}
                res_c = P.gravar_confirmacao(conn, mes_r, escolha, adotado, usuario, obs, resumo, imp["id"] if imp else None)
                st.session_state["pn2_conf_ok"] = f"DRE de {mes_r} confirmado (confirmação #{res_c['id']})." + (f" Substituiu a #{res_c['substituiu']}." if res_c["substituiu"] else "")
                st.rerun()
            except Exception as exc:
                st.error(f"Não consegui confirmar: {exc}")

    # ---- conferência pela API
    st.markdown("**Conferência: o mesmo DRE recalculado pela API do Sienge**")
    if mes_r not in meses_em:
        st.info(f"Ainda não há contas emitidas em {mes_r} no banco. Sincronize esse mês (tipo I) na primeira aba para conferir.")
    else:
        contas_r = P.resultado_por_conta(conn, mes_r, sem_previsao=sem_prev_r, so_obras=so_obras, sem_distrato=sem_dist_r, sem_desfeitos=sem_desf_r)
        dre = P.dre_do_mes(contas_r)
        v = dre["valores"]
        if not imp:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Receita bruta (API)", F.moeda_br(v["01"]), border=True)
            m2.metric("Custos diretos (API)", F.moeda_br(v["04"]), border=True)
            m3.metric("Lucro bruto (API)", F.moeda_br(v["05"]), border=True)
            m4.metric("Lucro líquido após investimentos (API)", F.moeda_br(v["14"]), border=True)
        ref, nome_ref, arq_r = None, "", None
        if imp:
            ref = P.dre_contas_importadas(conn, imp["id"])
            nome_ref = "PDF"
        else:
            arq_r = st.file_uploader("Sem PDF importado: conferir com um CSV de referência (colunas: conta; total) — opcional", type=["csv"], key="pn2_csv_res")
            if arq_r is not None:
                try:
                    ref = P.ler_referencia_dre(arq_r.getvalue())
                    nome_ref = "CSV"
                except ValueError as exc:
                    st.error(str(exc))
                    P.registrar_log(conn, "CSV_ERRO", "ERRO", usuario, mes_r, {"arquivo": arq_r.name, "erro": str(exc)[:300]})
        if ref:
            ref_dre = P.dre_do_mes([{"plano_cod": k, "plano_nome": "", "valor": x} for k, x in ref.items()])["valores"]
            linhas_t = [{"Linha": k, "DRE": n, "API": F.moeda_br(x), nome_ref: F.moeda_br(ref_dre[k]), "Diferença": F.moeda_br(round(x - ref_dre[k], 2)),
                         "Confere": "sim" if abs(x - ref_dre[k]) <= 0.5 else "NÃO"} for k, n, x in dre["linhas"]]
        else:
            linhas_t = [{"Linha": k, "DRE": n, "Valor (API)": F.moeda_br(x)} for k, n, x in dre["linhas"]]
        st.dataframe(pd.DataFrame(linhas_t), hide_index=True, width="stretch")
        if ref:
            cmp_r = P.comparar_resultado(contas_r, ref)
            tot_dif = round(v["14"] - ref_dre["14"], 2)
            if cmp_r["contas_com_diferenca"]:
                st.warning(f"{len(cmp_r['contas_com_diferenca'])} conta(s) com diferença (diferença no resultado final: {F.moeda_br(tot_dif)}).")
            else:
                st.success("API e DRE oficial batem em todas as contas.")
            with st.expander("Conta a conta (diferenças primeiro)", expanded=bool(cmp_r["contas_com_diferenca"])):
                ordem = sorted(cmp_r["contas"], key=lambda d: (-abs(d["dif"]) if abs(d["dif"]) > 0.5 else 0, d["plano_cod"]))
                st.dataframe(pd.DataFrame([{"Conta": d["plano_cod"], "Nome": d["plano_nome"], "API": F.moeda_br(d["api"]), nome_ref: F.moeda_br(d["ref"]),
                                            "Diferença": F.moeda_br(d["dif"]), "Confere": "sim" if abs(d["dif"]) <= 0.5 else "NÃO"} for d in ordem]), hide_index=True, width="stretch")
            if imp:
                with st.expander("Conferência por obra (PDF × API, usando o de-para de centros de custo)"):
                    pdf_obras = P.dre_por_obra_importado(conn, imp["id"])
                    api_obras = P.resultado_por_obra_api(conn, mes_r, sem_previsao=sem_prev_r, sem_distrato=sem_dist_r, sem_desfeitos=sem_desf_r)
                    if not api_obras:
                        st.info("Sem o de-para de centros de custo no banco não dá para agrupar a API por obra.")
                    else:
                        codigos_api = set(api_obras) - {"DEM", "sem de-para"}
                        linhas_o = []
                        for cod in sorted(set(pdf_obras) | codigos_api, key=lambda c: (len(c), c)):
                            p_ = pdf_obras.get(cod, {}).get("linhas", {})
                            a_ = api_obras.get(cod, {})
                            linhas_o.append({"Obra": cod, "Nome (PDF)": pdf_obras.get(cod, {}).get("nome", ""), "Receita PDF": p_.get("01", 0.0), "Receita API": a_.get("01", 0.0),
                                             "Custo PDF": p_.get("04", 0.0), "Custo API": a_.get("04", 0.0)})
                        resto = {c: o for c, o in pdf_obras.items() if c not in codigos_api}
                        dem_api = api_obras.get("DEM", {})
                        if dem_api or resto:
                            linhas_o = [x for x in linhas_o if x["Obra"] in codigos_api]
                            linhas_o.append({"Obra": "DEM", "Nome (PDF)": f"{len(resto)} obras do PDF sem código próprio no de-para", "Receita PDF": round(sum(o['linhas'].get('01', 0.0) for o in resto.values()), 2),
                                             "Receita API": dem_api.get("01", 0.0), "Custo PDF": round(sum(o['linhas'].get('04', 0.0) for o in resto.values()), 2), "Custo API": dem_api.get("04", 0.0)})
                        tab_o = pd.DataFrame(linhas_o)
                        tab_o["Dif. receita"] = tab_o["Receita API"] - tab_o["Receita PDF"]
                        tab_o["Dif. custo"] = tab_o["Custo API"] - tab_o["Custo PDF"]
                        tab_o["_o"] = tab_o[["Dif. receita", "Dif. custo"]].abs().max(axis=1)
                        tab_o = tab_o.sort_values("_o", ascending=False).drop(columns="_o")
                        for c in ("Receita PDF", "Receita API", "Custo PDF", "Custo API", "Dif. receita", "Dif. custo"):
                            tab_o[c] = tab_o[c].map(F.moeda_br)
                        st.dataframe(tab_o, hide_index=True, width="stretch")
                        st.caption("Obras com diferença primeiro. 'sem de-para' = centros de custo que ainda não estão no de-para.")
            chave_r = f"pn2_logado_res_{nome_ref}_{mes_r}_{int(v['14'] * 100)}_{int(ref_dre['14'] * 100)}_{int(sem_prev_r)}_{int(so_obras)}_{int(sem_dist_r)}_{int(sem_desf_r)}"
            if not st.session_state.get(chave_r):
                st.session_state[chave_r] = P.registrar_log(
                    conn, "CONFERENCIA_RESULTADO", "INFO" if not cmp_r["contas_com_diferenca"] else "AVISO", usuario, mes_r,
                    {"referencia": nome_ref, "importacao_id": imp["id"] if imp else None, "arquivo": (imp["arquivo"] if imp else (arq_r.name if arq_r is not None else None)),
                     "contas": len(cmp_r["contas"]), "contas_com_diferenca": len(cmp_r["contas_com_diferenca"]), "diferenca_resultado_final": tot_dif,
                     "sem_previsao": bool(sem_prev_r), "so_obras": bool(so_obras), "sem_distrato": bool(sem_dist_r), "sem_desfeitos": bool(sem_desf_r), "resultado": "bate" if not cmp_r["contas_com_diferenca"] else "difere"})
        with st.expander("De onde vem o valor: por centro de custo (diagnóstico)"):
            pc = P.resultado_por_centro(conn, mes_r, sem_previsao=sem_prev_r, sem_distrato=sem_dist_r, sem_desfeitos=sem_desf_r)
            if pc:
                grupos = {}
                for a in pc:
                    g = grupos.setdefault(a["grupo"], {"receita": 0.0, "custo": 0.0, "n": 0})
                    g["receita"] += a["receita"]; g["custo"] += a["custo"]; g["n"] += 1
                st.dataframe(pd.DataFrame([{"Grupo do de-para": k, "Centros": v_["n"], "Receita (1.01.01)": F.moeda_br(v_["receita"]), "Custo obra (2.01.*)": F.moeda_br(v_["custo"])}
                                           for k, v_ in sorted(grupos.items())]), hide_index=True, width="stretch")
                st.caption("Os 30 maiores centros de custo do mês (contas de receita e de custo de obra):")
                st.dataframe(pd.DataFrame([{"Centro": a["centro_id"], "Nome": a["centro"], "Grupo": a["grupo"], "Obra": a["codigo"], "Receita": F.moeda_br(a["receita"]),
                                            "Custo": F.moeda_br(a["custo"])} for a in pc[:30]]), hide_index=True, width="stretch")
            else:
                st.info("Sem dados.")
        with st.expander("Contas fora do mapa do DRE (têm movimento no mês mas não entram em nenhuma linha)"):
            if dre["fora_do_mapa"]:
                st.dataframe(pd.DataFrame([{"Conta": c["plano_cod"], "Nome": c["plano_nome"], "Valor": F.moeda_br(c["valor"])} for c in dre["fora_do_mapa"]]), hide_index=True, width="stretch")
                st.caption("Normal para pessoal ADM, transferências entre empresas e contas da Administração central; conta nova do plano também cai aqui.")
            else:
                st.success("Todas as contas com movimento estão no mapa.")

# ------------------------------------------------------------------ regras
with aba_obras:
    st.markdown("Resultado **por obra** a partir do **DRE oficial** (PDF do Sienge importado na aba Resultado). "
                "**BDI real** = receita bruta − custos diretos; **margem de contribuição** = BDI ÷ receita. Obras sem código próprio no de-para entram juntas em *Demais obras*.")
    meses_o = P.meses_com_dre(conn)
    if not meses_o:
        st.info("Ainda não há DRE oficial importado. Importe o PDF do Sienge na aba **Importações (V2)** e volte aqui.")
    else:
        mes_o = st.selectbox("Mês", meses_o, index=len(meses_o) - 1, key="pn2_mes_obras")
        ob = P.obras_do_dre(conn, mes_o)
        t = ob["total"]
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("Receita bruta", F.moeda_br(t["receita"]), border=True)
        o2.metric("Custos diretos", F.moeda_br(t["custo"]), border=True)
        o3.metric("BDI real", F.moeda_br(t["bdi"]), border=True)
        o4.metric("Margem de contribuição", f"{t['margem'] * 100:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".") if t["margem"] is not None else "–", border=True)
        pct = lambda m: (f"{m * 100:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".") if m is not None else "–")
        _folha_o = P.folha_do_mes(conn, mes_o)
        _colab = P.colab_por_linha_obras(ob["linhas"], _folha_o)
        def _por_colab(v, n):
            return F.moeda_br(v / n) if n else "–"
        st.dataframe(pd.DataFrame([{"Obra": l["obra"], "Nome": l["nome"], "Receita": F.moeda_br(l["receita"]), "Custos": F.moeda_br(l["custo"]), "BDI real": F.moeda_br(l["bdi"]),
                                    "Margem (BDI/receita)": pct(l["margem"]),
                                    "Colab. (CLT)": (str(_colab.get(l["obra"], 0)) if _folha_o else "–"),
                                    "Fat./colab.": (_por_colab(l["receita"], _colab.get(l["obra"], 0)) if _folha_o else "–"),
                                    "Custo/colab.": (_por_colab(-l["custo"], _colab.get(l["obra"], 0)) if _folha_o else "–")} for l in ob["linhas"]]),
                     hide_index=True, width="stretch")
        if _folha_o:
            st.caption(f"Colaboradores CLT pelos recibos de {mes_o[5:]}/{mes_o[:4]} (obra pelo departamento do recibo e o de-para de departamentos). "
                       "Fat./colab. = receita ÷ colaboradores; Custo/colab. = custos diretos ÷ colaboradores. Ainda não entram os PJ pagos nas obras."
                       + (f" Atenção: {sum(x['colab'] for x in _folha_o['sem_depara'])} recibo(s) sem de-para de departamento (veja a aba Pessoas; o cadastro de departamentos fica na aba Importações (V2))." if _folha_o["sem_depara"] else ""))
        else:
            st.caption("Colab., Fat./colab. e Custo/colab. aparecem quando os recibos da folha do mês forem importados (aba Importações (V2)).")
        c_l, c_p = st.columns(2)
        c_l.markdown("**5 obras com maior BDI**")
        c_l.dataframe(pd.DataFrame([{"Obra": l["obra"], "Nome": l["nome"], "BDI real": F.moeda_br(l["bdi"]), "Margem": pct(l["margem"])} for l in ob["top_lucro"]]), hide_index=True, width="stretch")
        c_p.markdown("**5 obras com maior prejuízo**")
        if ob["top_prejuizo"]:
            c_p.dataframe(pd.DataFrame([{"Obra": l["obra"], "Nome": l["nome"], "BDI real": F.moeda_br(l["bdi"]), "Margem": pct(l["margem"])} for l in ob["top_prejuizo"]]), hide_index=True, width="stretch")
        else:
            c_p.success("Nenhuma obra com BDI negativo neste mês.")
        st.caption(f"Fonte: DRE oficial importado do arquivo “{ob['arquivo']}” (importação #{ob['importacao_id']}).")

        # ---- projecao de receitas (xlsx) x realizado
        st.divider()
        st.markdown("**Projeção de receitas × realizado**")
        _proj = P.projecao_do_mes(conn, mes_o)
        if _proj is None:
            st.info(f"Ainda não há projeção importada para {mes_o[5:]}/{mes_o[:4]}. Importe a planilha na aba **Importações (V2)**.")
        else:
            cmp_ = P.projecao_x_realizado(_proj, ob, P.nomes_obras_extra(conn))
            _pr = lambda v: (F.pct_br(v) if v is not None else "–")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Receita projetada", F.moeda_br(cmp_["receita_proj_total"]), border=True)
            p2.metric("Receita real (DRE)", F.moeda_br(cmp_["receita_real_total"]), border=True)
            _dv = cmp_["receita_real_total"] - cmp_["receita_proj_total"]
            p3.metric("Desvio", F.moeda_br(_dv), delta=F.pct_br(_dv / cmp_["receita_proj_total"]) if abs(cmp_["receita_proj_total"]) > 0.005 else None, border=True)
            p4.metric("BDI previsto", F.moeda_br(cmp_["total"]["bdi_proj"]), border=True)
            st.dataframe(pd.DataFrame([{"Obra (projeção)": x["obra_proj"], "Obra (DRE)": f"{x['codigo']} · {x['nome']}", "Receita projetada": F.moeda_br(x["receita_proj"]),
                                        "Receita real": F.moeda_br(x["receita_real"]), "Desvio": F.moeda_br(x["desvio"]), "Desvio %": _pr(x["desvio_pct"]),
                                        "BDI previsto": F.moeda_br(x["bdi_proj"]), "BDI real": F.moeda_br(x["bdi_real"]), "Desvio BDI": F.moeda_br(x["desvio_bdi"])} for x in cmp_["linhas"]]),
                         hide_index=True, width="stretch")
            if cmp_["sem_correspondencia"]:
                st.warning("Obras da projeção sem correspondência única no DRE (confira o nome): "
                           + "; ".join(f"{o['obra']} ({F.moeda_br(o['receita'])})" for o in cmp_["sem_correspondencia"]))
            if abs(cmp_["receita_sem_projecao"]) > 0.005:
                st.caption(f"Receita do DRE em obras sem projeção neste mês: {F.moeda_br(cmp_['receita_sem_projecao'])}.")
            st.caption(f"Projeção do arquivo “{_proj['arquivo']}” (importação #{_proj['id']}). BDI real = receita bruta − custos diretos do DRE; BDI previsto = receita − custos previstos da planilha.")

with aba_adm:
    st.markdown("Despesas **pagas** nas unidades administrativas (centros de custo do grupo **ADM** no de-para), por credor, conta e unidade. "
                "Mesmas regras da aba Despesas: sem pessoal, encargos e transferências entre empresas, e sem documentos de previsão.")
    meses_a = P.meses_com_dados(conn)
    if not meses_a:
        st.info("Sincronize primeiro as contas pagas (data P) na primeira aba.")
    elif not P.centro_grupo_instalado(conn):
        st.warning("Falta o de-para centro de custo → grupo (OBRA/ADM) no banco; sem ele o app não sabe quais centros são administrativos.")
    else:
        _hoje_a = f"{dt.date.today().year}-{dt.date.today().month:02d}"
        _fech_a = [m for m in meses_a if m < _hoje_a] or meses_a
        ca1, ca2 = st.columns([1, 2])
        mes_a = ca1.selectbox("Mês", meses_a, index=meses_a.index(_fech_a[-1]), key="pn2_mes_adm")
        visao = ca2.radio("Período", ["No mês", "Acumulado do ano (janeiro até o mês)"], horizontal=True, key="pn2_adm_visao")
        P.garantir_regras_padrao(conn)
        regras_a = P.regras_ativas(conn, "DESPESAS")
        pref_a, prev_a = P.prefixos_excluidos(regras_a), P.exclui_previsao(regras_a)
        ini_a = mes_a
        if visao.startswith("Acumulado"):
            ini_a = max(f"{mes_a[:4]}-01", meses_a[0])
        grupo_ok = P.credor_grupo_instalado(conn)
        outros_cfg = P.credor_grupo_ativos(conn) if grupo_ok else []
        linhas_a = P.adm_linhas(conn, ini_a, mes_a, pref_a, sem_previsao=prev_a)
        if not linhas_a:
            st.info("Nenhum pagamento em centros de custo ADM neste período (confira o de-para de centros e se o mês foi sincronizado).")
        else:
            res_a = P.adm_resumo(linhas_a, [c["chave"] for c in outros_cfg], P.nomes_plano(conn))
            if ini_a != mes_a:
                st.caption(f"Acumulado de {ini_a[5:]}/{ini_a[:4]} a {mes_a[5:]}/{mes_a[:4]}" + (" (o banco só tem dados a partir daí)." if ini_a != f"{mes_a[:4]}-01" else "."))
            m1, m2, m3 = st.columns(3)
            m1.metric("Pago nas unidades ADM", F.moeda_br(res_a["total"]), border=True)
            m2.metric("Credores no período", res_a["n_credores"], border=True)
            m3.metric("Outros credores/Dir (fora do ranking)", F.moeda_br(res_a["outros"]["valor"]), border=True)
            fmt = lambda lst, rot: pd.DataFrame([{rot: a["nome"], "Valor": F.moeda_br(a["valor"]), "% do total": F.pct_br(a["pct"]) if a["pct"] is not None else "–"} for a in lst])
            g1, g2 = st.columns(2)
            g1.markdown("**Por grupo de despesa**")
            g1.dataframe(fmt(res_a["por_grupo"], "Grupo"), hide_index=True, width="stretch")
            g2.markdown("**Por unidade**")
            g2.dataframe(fmt(res_a["por_unidade"], "Unidade"), hide_index=True, width="stretch")
            st.markdown("**Maiores contas (12)**")
            st.dataframe(fmt(res_a["top_contas"], "Conta"), hide_index=True, width="stretch")
            st.markdown("**Credores (ranking)**")
            tab_cred = [{"Credor": a["credor"], "Valor": F.moeda_br(a["valor"]), "% do total": F.pct_br(a["pct"]) if a["pct"] is not None else "–"} for a in res_a["ranking"][:15]]
            if outros_cfg:
                tab_cred.append({"Credor": "Outros credores/Dir (fora do ranking)", "Valor": F.moeda_br(res_a["outros"]["valor"]),
                                 "% do total": F.pct_br(res_a["outros"]["pct"]) if res_a["outros"]["pct"] is not None else "–"})
            st.dataframe(pd.DataFrame(tab_cred), hide_index=True, width="stretch")
            if res_a["outros"]["credores"]:
                with st.expander(f"Quem está em Outros credores/Dir neste período ({len(res_a['outros']['credores'])})"):
                    st.dataframe(pd.DataFrame([{"Credor": a["credor"], "Valor": F.moeda_br(a["valor"])} for a in res_a["outros"]["credores"]]), hide_index=True, width="stretch")
            if outros_cfg and res_a["chaves_sem_credor"]:
                st.caption(f"{len(res_a['chaves_sem_credor'])} cadastro(s) do grupo Outros credores/Dir sem pagamento neste período "
                           "(normal se o credor não recebeu; se o nome estiver diferente do Sienge, ajuste o texto no de-para abaixo).")
            evo = P.adm_evolucao(conn, meses_a[0], mes_a, pref_a, sem_previsao=prev_a)
            if len(evo) > 1:
                st.markdown("**Evolução mensal (pago nas unidades ADM)**")
                _grafico_meses([e["valor"] for e in evo], [e["mes"] for e in evo], "Pago (R$)")
    st.caption("Para mudar quem fica em “Outros credores/Dir”, use o cadastro de credores na aba **Importações (V2)**.")

    # ---- Orcamento ADM (orcado x realizado), PDF do Sienge
    st.divider()
    st.markdown("**Orçamento ADM: orçado × realizado**")
    _orc = P.orcamento_ativo(conn)
    if not _orc:
        st.info("Orçado × realizado aparece depois de importar o PDF do Orçamento ADM na aba **Importações (V2)**.")
    if _orc:
        oa1, oa2 = st.columns([1, 2])
        mes_orc = oa1.selectbox("Mês", _orc["meses"], index=len(_orc["meses"]) - 1, key="pn2_mes_orc")
        acum_orc = oa2.toggle("Acumulado do ano até este mês", value=False, key="pn2_acum_orc")
        res_orc = P.orcamento_resumo(conn, _orc["id"], mes_orc, acumulado=acum_orc)
        tot_o = res_orc["total"]
        _prc = lambda v: (F.pct_br(v) if v is not None else "–")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Orçado", F.moeda_br(tot_o["orcado"]), border=True)
        r2.metric("Realizado", F.moeda_br(tot_o["realizado"]), border=True)
        r3.metric("Desvio (realizado − orçado)", F.moeda_br(tot_o["desvio"]), border=True)
        r4.metric("Desvio %", _prc(tot_o["desvio_pct"]), border=True)
        st.dataframe(pd.DataFrame([{"Código": g["codigo"], "Grupo": g["conta"], "Orçado": F.moeda_br(g["orcado"]), "Realizado": F.moeda_br(g["realizado"]),
                                    "Desvio": F.moeda_br(g["desvio"]), "Desvio %": _prc(g["desvio_pct"])} for g in res_orc["grupos"]]), hide_index=True, width="stretch")
        ca_, cb_ = st.columns(2)
        ca_.markdown("**Contas que mais passaram do orçado**")
        ca_.dataframe(pd.DataFrame([{"Conta": f"{c['codigo']} · {c['conta']}", "Orçado": F.moeda_br(c["orcado"]), "Realizado": F.moeda_br(c["realizado"]), "Desvio": F.moeda_br(c["desvio"])} for c in res_orc["acima"]]),
                      hide_index=True, width="stretch")
        cb_.markdown("**Contas que mais sobraram do orçado**")
        cb_.dataframe(pd.DataFrame([{"Conta": f"{c['codigo']} · {c['conta']}", "Orçado": F.moeda_br(c["orcado"]), "Realizado": F.moeda_br(c["realizado"]), "Desvio": F.moeda_br(c["desvio"])} for c in res_orc["abaixo"]]),
                      hide_index=True, width="stretch")
        # protecao: se o servidor ainda tiver o painel_db antigo em memoria logo apos um deploy, o resto da aba continua funcionando
        serie_o = P.orcamento_serie_mensal(conn, _orc["id"]) if hasattr(P, "orcamento_serie_mensal") else []
        if len(serie_o) > 1:
            st.markdown("**Desvio mês a mês (todos os meses do arquivo)**")
            st.dataframe(pd.DataFrame([{"Mês": f"{x['mes'][5:]}/{x['mes'][:4]}", "Orçado": F.moeda_br(x["orcado"]), "Realizado": F.moeda_br(x["realizado"]),
                                        "Desvio": F.moeda_br(x["desvio"]), "Desvio %": _prc(x["desvio_pct"]), "Desvio acumulado": F.moeda_br(x["desvio_acum"])} for x in serie_o]),
                         hide_index=True, width="stretch")
            _grafico_meses([x["desvio"] for x in serie_o], [x["mes"] for x in serie_o], "Desvio do mês (R$)")
        st.caption(f"Fonte: PDF “{_orc['arquivo']}” (importação #{_orc['id']}), valores do Realizado do próprio Sienge (seleção do relatório). Só despesas (contas 2.*); desvio positivo = gastou mais que o orçado.")

with aba_pess:
    st.markdown("**Folha de pagamento (CLT)** pelos recibos em PDF e a evolução do **faturamento** mês a mês.")
    _folha_ok = P.folha_instalada(conn)
    _meses_folha = P.folha_meses(conn)
    if not _meses_folha:
        st.info("Colaboradores, HE e custo da folha aparecem depois de importar os PDFs de recibos na aba **Importações (V2)**.")
    if _meses_folha:
        mes_f = st.selectbox("Mês da folha", _meses_folha, index=len(_meses_folha) - 1, key="pn2_mes_folha")
        fo = P.folha_do_mes(conn, mes_f)
        tt = fo["total"]
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Colaboradores CLT", f"{tt['colab']}", border=True)
        q2.metric("Remuneração (base da HE)", F.moeda_br(tt["base_he"]), border=True)
        q3.metric("Horas extras + DSR", F.moeda_br(tt["hora_extra"] + tt["dsr_he"]), border=True)
        q4.metric("HE + DSR ÷ remuneração", F.pct_br(tt["he_pct"]) if tt["he_pct"] is not None else "–", border=True)
        st.dataframe(pd.DataFrame([{"Empresa": e["empresa"], "Colab.": e["colab"], "Remuneração": F.moeda_br(e["base_he"]), "HE + DSR": F.moeda_br(e["hora_extra"] + e["dsr_he"]),
                                    "HE ÷ remuneração": F.pct_br(e["he_pct"]) if e["he_pct"] is not None else "–", "Custo (proventos + FGTS)": F.moeda_br(e["custo"])} for e in fo["por_empresa"]]),
                     hide_index=True, width="stretch")
        st.markdown("**Colaboradores por obra**")
        st.dataframe(pd.DataFrame([{"Obra": o["codigo"], "Nome": o["nome"], "Colab.": o["colab"], "Remuneração": F.moeda_br(o["base_he"]), "HE + DSR": F.moeda_br(o["hora_extra"] + o["dsr_he"]),
                                    "HE ÷ remuneração": F.pct_br(o["he_pct"]) if o["he_pct"] is not None else "–", "Custo (proventos + FGTS)": F.moeda_br(o["custo"])}
                                   for o in sorted(fo["por_obra"].values(), key=lambda o: -o["colab"])]), hide_index=True, width="stretch")
        if fo["sem_depara"]:
            st.warning("Departamentos da folha sem de-para com obra (cadastre em `pnl_folha_depto_obra`): "
                       + "; ".join(f"{x['empresa']} {x['departamento']} ({x['subnivel'] or '–'}, {x['colab']} colab.)" for x in fo["sem_depara"]))
        st.caption("Remuneração (base da HE, definição da contabilidade) = proventos que não são HE nem DSR s/ HE, menos descontos de faltas; “Salários” = só o evento 1 (horas normais). Horas extras = eventos de HE 50/60/80/100/110% (inclui HE de mês anterior) + DSR s/ HE, como a contabilidade pediu. "
                   "Custo = total de proventos + FGTS do mês (não inclui INSS patronal, férias/13º provisionados nem os PJ). Fonte: "
                   + "; ".join(f"“{i['arquivo']}” ({i['escopo']}, importação #{i['id']})" for i in fo["importacoes"]) + ".")
        _sf = [x for x in P.folha_serie(conn) if x["he_pct"] is not None]
        if len(_sf) >= 2:
            st.markdown("**HE + DSR ÷ remuneração CLT por mês**")
            _grafico_meses([round(x["he_pct"] * 100, 1) for x in _sf], [x["mes"] for x in _sf], "HE ÷ remuneração (%)", linha=True)
    st.divider()
    st.markdown("Evolução do **faturamento** mês a mês.")
    _mes_cur = f"{dt.date.today().year}-{dt.date.today().month:02d}"
    serie = P.receita_mensal(conn, mes_atual=_mes_cur)
    if not serie:
        st.info("Ainda não há receita para mostrar. Sincronize o Sienge (data de emissão) ou importe o DRE oficial na aba Resultado.")
    else:
        rotulo = lambda m: f"{m[5:]}/{m[:4]}"
        st.markdown("**Receita bruta por mês**")
        _grafico_meses([x["receita"] for x in serie], [x["mes"] for x in serie], "Receita (R$)")
        com_var = [x for x in serie if x["var"] is not None]
        if com_var:
            st.markdown("**Receita: variação % sobre o mês anterior**")
            _grafico_meses([round(x["var"] * 100, 1) for x in com_var], [x["mes"] for x in com_var], "Variação (%)", linha=True)
        st.dataframe(pd.DataFrame([{"Mês": rotulo(x["mes"]), "Receita bruta": F.moeda_br(x["receita"]),
                                    "Var. % s/ mês anterior": (F.pct_br(x["var"]) if x["var"] is not None else "–"), "Fonte": x["fonte"]} for x in serie]),
                     hide_index=True, width="stretch")
        if any(x["fonte"].startswith("API") for x in serie):
            st.caption("Meses marcados “API (a conferir)” foram reconstruídos pelo Sienge (sem previsão e sem NF desfeita) e ainda não têm DRE oficial importado/confirmado; "
                       "para fechar o painel, importe o DRE desses meses na aba Resultado. Meses anteriores à primeira sincronização do Sienge só aparecem quando têm DRE importado/confirmado.")

with aba_regras:
    st.markdown("Regras usadas para montar cada aba do painel. As marcadas como **proposta** foram deduzidas dos arquivos de setembro e "
                "ainda precisam da confirmação da contabilidade.")
    with conn.cursor() as cur:
        cur.execute("SELECT id, area, tipo, valor, descricao, status, alterado_por, alterado_em FROM pnl_regra WHERE ativo ORDER BY area, id")
        rg = cur.fetchall()
    st.dataframe(pd.DataFrame([{"Aba": a, "Regra": t, "Valor": v, "Descrição": d, "Status": s.lower(), "Quem": q, "Quando": e.strftime("%d/%m/%Y")}
                               for _, a, t, v, d, s, q, e in rg]), hide_index=True, width="stretch")
    pend = [(i, f"{a} · {t} · {v}") for i, a, t, v, d, s, q, e in rg if s != "CONFIRMADA"]
    if pend:
        esc = st.multiselect("Confirmar regras (só depois de conferir com o CSV ou com a contabilidade)", [i for i, _ in pend],
                             format_func=lambda i: next(n for k, n in pend if k == i), key="pn2_rg_conf")
        if st.button("Confirmar as regras escolhidas", disabled=not esc, key="pn2_rg_btn"):
            n = P.confirmar_regras(conn, esc, usuario or "app")
            st.success(f"{n} regra(s) confirmada(s).")
            st.rerun()
    else:
        st.success("Todas as regras estão confirmadas.")

    # ---- acessos: quem e' visualizador (so' o Painel da Diretoria) -- SQL-20
    st.divider()
    st.markdown("**Acessos: quem só visualiza o Painel da Diretoria**")
    import acesso
    if not acesso.instalado(conn):
        st.warning("Falta executar o arquivo `sql/v2_acesso.sql` (SQL-20) no Supabase para cadastrar visualizadores. Até lá todos os usuários têm acesso completo, como hoje.")
    else:
        st.caption("O login continua no Supabase (Authentication → Users): crie o usuário lá e cadastre o e-mail aqui como VISUALIZADOR. "
                   "Quem não estiver na lista continua com acesso completo. Para tirar o acesso: desative aqui e/ou exclua o usuário no Authentication.")
        ac = acesso.listar(conn)
        if ac:
            st.dataframe(pd.DataFrame([{"E-mail": a["email"], "Papel": a["papel"].lower(), "Ativo": "sim" if a["ativo"] else "não", "Por": a["alterado_por"] or "",
                                        "Em": a["alterado_em"].strftime("%d/%m/%Y %H:%M")} for a in ac]), hide_index=True, width="stretch")
        c_a1, c_a2, c_a3 = st.columns([3, 1.4, 1])
        em_ac = c_a1.text_input("E-mail do usuário", key="pn2_ac_email")
        pa_ac = c_a2.selectbox("Papel", ["VISUALIZADOR", "EDITOR"], key="pn2_ac_papel")
        at_ac = c_a3.checkbox("Ativo", value=True, key="pn2_ac_ativo")
        if st.button("Salvar acesso", key="pn2_ac_btn", disabled=not em_ac.strip()):
            try:
                r_ac = acesso.definir(conn, em_ac, pa_ac, at_ac, usuario)
                P.registrar_log(conn, "ACESSO_DEFINIDO", "INFO", usuario, None, {"papel": r_ac["papel"], "ativo": r_ac["ativo"], "novo": r_ac["novo"]})
                st.success(f"{r_ac['email']}: {r_ac['papel'].lower()} ({'ativo' if r_ac['ativo'] else 'inativo'}).")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

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

# ------------------------------------------------------------------ relatorio PDF (rascunho)
with aba_pdf:
    st.markdown("PDF do **Painel EnerMais** do mês, no padrão visual dos demonstrativos (capa, resumo, DRE, obras, administração, pessoas e notas). "
                "É um **rascunho**: o layout ainda será validado e pode mudar. Usa os mesmos números das abas; a parte que ainda não tem dado vira um aviso do que falta importar.")
    _m_pdf = sorted(set(P.meses_com_dre(conn)) | set(P.meses_confirmados(conn)) | set(P.meses_com_dados(conn)) | set(P.folha_meses(conn)))
    if not _m_pdf:
        st.info("Ainda não há dados no painel para montar o relatório.")
    else:
        _conf_pdf = P.meses_confirmados(conn)
        _padrao = _conf_pdf[-1] if _conf_pdf else _m_pdf[-1]
        mes_pdf = st.selectbox("Mês do relatório", _m_pdf, index=_m_pdf.index(_padrao), key="pn2_mes_pdf")
        if st.button("Gerar o PDF", type="primary", key="pn2_btn_pdf"):
            import relatorio_painel_pdf as RPP
            _agora = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
            with st.spinner("Montando o relatório…"):
                _ctx_pdf = RPP.montar_ctx(conn, mes_pdf, _agora)
                st.session_state["pn2_pdf"] = (mes_pdf, RPP.gerar_pdf_painel(_ctx_pdf, gerado_em=_agora), _ctx_pdf["dre"]["origem"])
            P.registrar_log(conn, "RELATORIO_PAINEL_PDF", "INFO", usuario, mes_pdf, {"origem_dre": _ctx_pdf["dre"]["origem"], "rascunho": True})
        _pdf = st.session_state.get("pn2_pdf")
        if _pdf and _pdf[0] == mes_pdf:
            st.success(f"Relatório de {_pdf[0][5:]}/{_pdf[0][:4]} pronto. DRE: {_pdf[2]}.")
            st.download_button("Baixar o PDF (rascunho)", _pdf[1], file_name=f"painel_enermais_{_pdf[0]}_rascunho.pdf", mime="application/pdf", key="pn2_dl_pdf")
