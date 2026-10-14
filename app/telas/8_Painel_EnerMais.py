# -*- coding: utf-8 -*-
"""GDF V2 — Painel EnerMais (EM CONSTRUCAO): sincroniza o Sienge, confere com o CSV e mostra a previa da aba Despesas.
As demais abas (Resultado, Obras, Administracao, Pessoas) e o PDF entram nas proximas etapas."""
import pandas as pd
import datetime as dt

import streamlit as st

import formatacao as F
import importador_dre
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

aba_sync, aba_desp, aba_res, aba_obras, aba_regras, aba_log = st.tabs(["Sincronizar com o Sienge", "Despesas (prévia)", "Resultado (prévia)", "Obras (prévia)", "Regras", "Histórico e logs"])

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
        st.info("Importe o PDF do DRE gerencial do Sienge (abaixo) ou sincronize as contas por data de emissão (tipo I) na primeira aba.")
    _hj = f"{dt.date.today().year}-{dt.date.today().month:02d}"
    _fech = [m for m in meses_r_opts if m < _hj] or meses_r_opts
    r1, r2, r3, r4 = st.columns([1, 2, 2, 2])
    mes_r = r1.selectbox("Mês", meses_r_opts or [_hj], index=(meses_r_opts.index(_fech[-1]) if meses_r_opts else 0), key="pn2_mes_res")
    sem_prev_r = r2.checkbox("Tirar documentos de previsão (PRV, PCT, PPC, FOPA)", value=True, key="pn2_res_prev",
                             help="Mesma regra das Despesas (confirmada pela Suellen). Vale para a conferência pela API.")
    sem_dist_r = r4.checkbox("Tirar NFs desfeitas (distrato)", value=True, key="pn2_res_distrato",
                             help="Título a receber cujas baixas do tipo Distrato somam o valor todo: o Sienge ainda o lista na API, mas o DRE dele não conta. Conferido em set/2026.")
    _cg = P.centro_grupo_instalado(conn)
    so_obras = r3.checkbox("Só centros de custo de obra (sem ADM)", value=_cg, disabled=not _cg, key="pn2_res_obras",
                           help="O DRE gerencial 'por obra' do Sienge não traz os centros de custo da Administração. Usa o de-para centro de custo → obra validado pela Suellen.")
    if not _cg:
        st.info("O de-para de centros de custo ainda não está no banco; falta executar o SQL do de-para (veja o handoff do projeto). Até lá o filtro de obra fica desligado.")

    # ---- importar o PDF
    with st.expander("Importar o PDF do DRE gerencial do Sienge", expanded=not P.dre_importacao_ativa(conn, mes_r)):
        if not P.dre_instalado(conn):
            st.warning("Falta executar o arquivo `sql/v2_dre_pdf.sql` no Supabase (SQL Editor) para o app guardar o DRE lido do PDF. Você já pode ler o PDF e ver o resultado; só não dá para salvar.")
        pdf_arq = st.file_uploader("PDF 'DRE GERENCIAL – composição das contas' (Sienge)", type=["pdf"], key="pn2_pdf_dre")
        if pdf_arq is not None:
            pdf_bytes = pdf_arq.getvalue()
            pdf_sha = P.sha256_curto(pdf_bytes)
            chave_pdf = f"pn2_dre_lido_{pdf_sha}"
            if chave_pdf not in st.session_state:
                try:
                    with st.spinner("Lendo o PDF… (cerca de 10 a 30 segundos)"):
                        st.session_state[chave_pdf] = importador_dre.ler_dre_pdf(pdf_bytes)
                except importador_dre.ErroDRE as exc:
                    st.session_state[chave_pdf] = str(exc)
                    P.registrar_log(conn, "DRE_PDF_ERRO", "ERRO", usuario, None, {"arquivo": pdf_arq.name, "sha256": pdf_sha, "erro": str(exc)[:300]})
            lido_pdf = st.session_state[chave_pdf]
            if isinstance(lido_pdf, str):
                st.error(lido_pdf)
            else:
                per = lido_pdf["periodo"]
                mes_pdf = (per.get("inicio") or "")[:7]
                st.success(f"PDF lido: período {per.get('inicio')} a {per.get('fim')} · {per.get('analise')} · seleção por {per.get('selecao')} · "
                           f"{len(lido_pdf['obras'])} obras · {len(lido_pdf['valores'])} valores.")
                for av in lido_pdf["avisos"]:
                    st.warning(av)
                if not lido_pdf["avisos"]:
                    st.caption("Conferido: a soma das contas fecha com cada linha do DRE e a soma das obras fecha com a coluna Total do PDF.")
                if mes_pdf and mes_pdf != mes_r:
                    st.info(f"Este PDF é de {mes_pdf}; ao salvar, ele vira o DRE oficial de {mes_pdf} (o mês escolhido acima é {mes_r}).")
                if st.button(f"Salvar como DRE oficial de {mes_pdf}", type="primary", disabled=not (P.dre_instalado(conn) and mes_pdf), key="pn2_pdf_salvar"):
                    try:
                        res_g = P.gravar_dre(conn, lido_pdf, pdf_arq.name, __import__("hashlib").sha256(pdf_bytes).hexdigest(), usuario)
                        if res_g["repetido"]:
                            st.info(f"Este mesmo arquivo já foi importado antes (importação #{res_g['id']}, mês {res_g['mes']}).")
                        else:
                            st.success(f"DRE de {res_g['mes']} salvo (importação #{res_g['id']}).")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Não consegui salvar: {exc}")

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
    _api_f = P.dre_do_mes(P.resultado_por_conta(conn, mes_r, sem_previsao=sem_prev_r, so_obras=so_obras, sem_distrato=sem_dist_r))["valores"] if mes_r in meses_em else None
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
        cab = st.columns([3, 2, 2, 2, 2])
        for c_, t_ in zip(cab, ["Linha do DRE", "API", "PDF", "Diferença", "Fonte adotada"]):
            c_.markdown(f"**{t_}**")
        escolha = {}
        for k_, n_ in _folhas:
            cols = st.columns([3, 2, 2, 2, 2])
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
            ini_ = salvo if salvo in _fontes else _padrao
            escolha[k_] = cols[4].selectbox("Fonte", list(_fontes), index=list(_fontes).index(ini_), key=f"pn2_fonte_{mes_r}_{k_}", label_visibility="collapsed")
        adotado = {k_: _fontes[escolha[k_]].get(k_, 0.0) for k_, _ in _folhas}
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
                resumo = {"lucro_liquido_adotado": fv["14"], "lucro_liquido_api": (P.dre_de_folhas({k_: _api_f.get(k_, 0.0) for k_, _ in _folhas})["valores"]["14"] if _api_f else None),
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
        contas_r = P.resultado_por_conta(conn, mes_r, sem_previsao=sem_prev_r, so_obras=so_obras, sem_distrato=sem_dist_r)
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
                    api_obras = P.resultado_por_obra_api(conn, mes_r, sem_previsao=sem_prev_r, sem_distrato=sem_dist_r)
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
            chave_r = f"pn2_logado_res_{nome_ref}_{mes_r}_{int(v['14'] * 100)}_{int(ref_dre['14'] * 100)}_{int(sem_prev_r)}_{int(so_obras)}_{int(sem_dist_r)}"
            if not st.session_state.get(chave_r):
                st.session_state[chave_r] = P.registrar_log(
                    conn, "CONFERENCIA_RESULTADO", "INFO" if not cmp_r["contas_com_diferenca"] else "AVISO", usuario, mes_r,
                    {"referencia": nome_ref, "importacao_id": imp["id"] if imp else None, "arquivo": (imp["arquivo"] if imp else (arq_r.name if arq_r is not None else None)),
                     "contas": len(cmp_r["contas"]), "contas_com_diferenca": len(cmp_r["contas_com_diferenca"]), "diferenca_resultado_final": tot_dif,
                     "sem_previsao": bool(sem_prev_r), "so_obras": bool(so_obras), "sem_distrato": bool(sem_dist_r), "resultado": "bate" if not cmp_r["contas_com_diferenca"] else "difere"})
        with st.expander("De onde vem o valor: por centro de custo (diagnóstico)"):
            pc = P.resultado_por_centro(conn, mes_r, sem_previsao=sem_prev_r, sem_distrato=sem_dist_r)
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
        st.info("Ainda não há DRE oficial importado. Importe o PDF do Sienge na aba Resultado e volte aqui.")
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
        st.dataframe(pd.DataFrame([{"Obra": l["obra"], "Nome": l["nome"], "Receita": F.moeda_br(l["receita"]), "Custos": F.moeda_br(l["custo"]), "BDI real": F.moeda_br(l["bdi"]),
                                    "Margem (BDI/receita)": pct(l["margem"]), "Colab.": "–", "Fat./colab.": "–", "Custo/colab.": "–"} for l in ob["linhas"]]),
                     hide_index=True, width="stretch")
        st.caption("Colab., Fat./colab. e Custo/colab. dependem da folha de pagamento do mês (CLT) e dos PJ pagos nas obras; entram na próxima etapa, quando a folha for importada.")
        c_l, c_p = st.columns(2)
        c_l.markdown("**5 obras com maior BDI**")
        c_l.dataframe(pd.DataFrame([{"Obra": l["obra"], "Nome": l["nome"], "BDI real": F.moeda_br(l["bdi"]), "Margem": pct(l["margem"])} for l in ob["top_lucro"]]), hide_index=True, width="stretch")
        c_p.markdown("**5 obras com maior prejuízo**")
        if ob["top_prejuizo"]:
            c_p.dataframe(pd.DataFrame([{"Obra": l["obra"], "Nome": l["nome"], "BDI real": F.moeda_br(l["bdi"]), "Margem": pct(l["margem"])} for l in ob["top_prejuizo"]]), hide_index=True, width="stretch")
        else:
            c_p.success("Nenhuma obra com BDI negativo neste mês.")
        st.caption(f"Fonte: DRE oficial importado do arquivo “{ob['arquivo']}” (importação #{ob['importacao_id']}).")

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
