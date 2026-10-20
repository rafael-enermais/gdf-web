# -*- coding: utf-8 -*-
"""GDF V2 - aba "Importacoes (V2)" do Painel EnerMais: TODOS os uploads da V2 num lugar so (DRE, folha, projecao, orcamento ADM), o historico unico de
importacoes, reverter sem apagar (marcar fora de uso / reativar), editar os valores importados (com registro do antes e do depois) e os cadastros.
A V1 (Importar balancete) nao passa por aqui. As demais abas do painel so mostram resultado."""
import datetime as dt

import pandas as pd
import streamlit as st

import formatacao as F
import historico
import importador_dre
import importador_folha
import importador_orcamento
import importador_projecao
import indicadores_dados as IND
import painel_db as P

TIPOS = {"DRE": "DRE oficial (PDF)", "FOLHA": "Folha (PDF)", "PROJECAO": "Projeção (xlsx)", "ORCAMENTO": "Orçamento ADM (PDF)", "HISTORICO": "Histórico do painel (HTML)"}
_BR = dt.timezone(dt.timedelta(hours=-3))


def _hora(x) -> str:
    return x.astimezone(_BR).strftime("%d/%m/%Y %H:%M") if x else "–"


def _ja_salvo(conn, tipo: str, conteudo: bytes) -> bool:
    """Se este arquivo ja esta salvo no banco, mostra o aviso (numero, mes, quem e quando) e devolve True: a tela nao oferece o botao Salvar de novo.
    Assim, depois de salvar (a pagina recarrega), o usuario continua vendo que gravou."""
    r = P.importacao_por_sha(conn, tipo, __import__("hashlib").sha256(conteudo).hexdigest())
    if not r:
        return False
    situacao = "em uso" if r["ativo"] else "substituída por uma importação mais nova"
    st.success(f"✅ Já salvo no banco: importação #{r['id']} (mês {r['mes'][5:]}/{r['mes'][:4]}, {r['linhas']} linhas) por {r['quem'] or '–'} em {_hora(r['quando'])} · {situacao}.")
    return True


# ---------------------------------------------------------------- uploads (ler -> conferir -> salvar), movidos das outras abas
def up_dre(conn, usuario):
    """Upload do PDF do DRE gerencial do Sienge (ler -> conferir -> salvar)."""
    with st.expander("Importar o PDF do DRE gerencial do Sienge", expanded=not P.meses_com_dre(conn)):
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
                if not _ja_salvo(conn, "DRE", pdf_bytes) and st.button(f"Salvar como DRE oficial de {mes_pdf}", type="primary", disabled=not (P.dre_instalado(conn) and mes_pdf), key="pn2_pdf_salvar"):
                    try:
                        res_g = P.gravar_dre(conn, lido_pdf, pdf_arq.name, __import__("hashlib").sha256(pdf_bytes).hexdigest(), usuario)
                        if res_g["repetido"]:
                            st.info(f"Este mesmo arquivo já foi importado antes (importação #{res_g['id']}, mês {res_g['mes']}).")
                        else:
                            st.toast(f"DRE de {res_g['mes']} salvo (importação #{res_g['id']}).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Não consegui salvar: {exc}")


def up_projecao(conn, usuario):
    """Upload da planilha de projecao de receitas (xlsx)."""
    with st.expander("Importar a planilha de projeção de receitas (xlsx)", expanded=not P.projecao_meses(conn)):
        st.caption("Planilha 'Projeções-Receitas-Obras' (colunas CONTRATO, CLIENTE, OBRA, ..., mês da projeção, CUSTOS, BDI). O mês vem do cabeçalho da coluna (ex.: set/26). O app só lê os valores.")
        arq_p = st.file_uploader("Planilha de projeção (xlsx)", type=["xlsx"], key="pn2_xlsx_proj")
        if arq_p is not None and str(getattr(arq_p, "name", "")).lower().endswith(".xlsx"):
            b_p = arq_p.getvalue()
            sha_p = P.sha256_curto(b_p)
            ch_p = f"pn2_proj_lida_{sha_p}"
            if ch_p not in st.session_state:
                try:
                    st.session_state[ch_p] = importador_projecao.ler_projecao_xlsx(b_p)
                except importador_projecao.ErroProjecao as exc:
                    st.session_state[ch_p] = str(exc)
                    P.registrar_log(conn, "PROJECAO_XLSX_ERRO", "ERRO", usuario, None, {"arquivo": arq_p.name, "sha256": sha_p, "erro": str(exc)[:300]})
            lido_p = st.session_state[ch_p]
            if isinstance(lido_p, str):
                st.error(lido_p)
            else:
                st.success(f"Planilha lida: projeção de {lido_p['mes'][5:]}/{lido_p['mes'][:4]} · {len(lido_p['linhas'])} linhas · receita prevista {F.moeda_br(lido_p['total']['valor_mes'])} · "
                           f"BDI previsto {F.moeda_br(lido_p['total']['bdi'])}.")
                for av in lido_p["avisos"]:
                    st.warning(av)
                if not _ja_salvo(conn, "PROJECAO", b_p) and st.button(f"Salvar como projeção de {lido_p['mes'][5:]}/{lido_p['mes'][:4]}", type="primary", key=f"pn2_proj_salvar_{sha_p}"):
                    try:
                        res_p = P.gravar_projecao(conn, lido_p, arq_p.name, __import__("hashlib").sha256(b_p).hexdigest(), usuario)
                        if res_p["repetido"]:
                            st.info(f"Esta mesma planilha já foi importada antes (importação #{res_p['id']}, mês {res_p['mes']}).")
                        else:
                            st.toast(f"Projeção de {res_p['mes']} salva (importação #{res_p['id']}).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Não consegui salvar: {exc}")


def up_orcamento(conn, usuario):
    """Upload do PDF do Orcamento ADM (Comparativo Orcado x Realizado)."""
    with st.expander("Importar o PDF do Orçamento ADM (Comparativo Orçado × Realizado)", expanded=P.orcamento_ativo(conn) is None):
        if not P.orcamento_instalado(conn):
            st.warning("Falta executar o arquivo `sql/v2_orcamento_adm.sql` (SQL-18) no Supabase para o app guardar o orçamento. Você já pode ler o PDF; só não dá para salvar.")
        st.caption("PDF 'Comparativo Orçado X Realizado Agrupado' do Sienge (agrupamento ORÇAMENTO TOTAL | ADMINISTRATIVO), com os meses lado a lado. Pode ser o acumulado do ano.")
        arq_o = st.file_uploader("PDF do Orçamento ADM", type=["pdf"], key="pn2_pdf_orc")
        if arq_o is not None and str(getattr(arq_o, "name", "")).lower().endswith(".pdf"):
            b_o = arq_o.getvalue()
            sha_o = P.sha256_curto(b_o)
            ch_o = f"pn2_orc_lido_{sha_o}"
            if ch_o not in st.session_state:
                try:
                    with st.spinner("Lendo o PDF… (cerca de 5 a 15 segundos)"):
                        st.session_state[ch_o] = importador_orcamento.ler_orcamento_adm_pdf(b_o)
                except importador_orcamento.ErroOrcamento as exc:
                    st.session_state[ch_o] = str(exc)
                    P.registrar_log(conn, "ORCAMENTO_ADM_ERRO", "ERRO", usuario, None, {"arquivo": arq_o.name, "sha256": sha_o, "erro": str(exc)[:300]})
            lido_o = st.session_state[ch_o]
            if isinstance(lido_o, str):
                st.error(lido_o)
            else:
                cab_o = lido_o["cabecalho"]
                st.success(f"PDF lido: {cab_o['inicio']} a {cab_o['fim']} · {len(lido_o['meses'])} meses · {len({l['codigo'] for l in lido_o['linhas']})} contas.")
                for av in lido_o["avisos"][:20]:
                    st.warning(av)
                if not lido_o["avisos"]:
                    st.caption("Conferido: cada total fecha com a soma das contas e o saldo fecha com realizado − orçado.")
                if not _ja_salvo(conn, "ORCAMENTO", b_o) and st.button("Salvar como Orçamento ADM", type="primary", disabled=not P.orcamento_instalado(conn), key=f"pn2_orc_salvar_{sha_o}"):
                    try:
                        res_o = P.gravar_orcamento(conn, lido_o, arq_o.name, __import__("hashlib").sha256(b_o).hexdigest(), usuario)
                        if res_o["repetido"]:
                            st.info(f"Este mesmo arquivo já foi importado antes (importação #{res_o['id']}).")
                        else:
                            st.toast(f"Orçamento ADM salvo (importação #{res_o['id']}, {res_o['linhas']} linhas).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Não consegui salvar: {exc}")


def up_folha(conn, usuario):
    """Upload dos PDFs de recibos de pagamento (folha)."""
    _folha_ok = P.folha_instalada(conn)
    with st.expander("Importar os recibos de pagamento (PDF)", expanded=not P.folha_meses(conn)):
        if not _folha_ok:
            st.warning("Falta executar o arquivo `sql/v2_folha.sql` (SQL-16) no Supabase para o app guardar a folha. Você já pode ler os PDFs e ver o resultado; só não dá para salvar.")
        st.caption("Envie o PDF 'Recibos de Pagamento' de cada empresa (Construtora e Energia). O app lê só o texto; o original não é alterado. Cada recibo vem duas vezes no PDF; conta uma só.")
        arqs_f = st.file_uploader("PDFs dos recibos (um ou mais)", type=["pdf"], accept_multiple_files=True, key="pn2_pdf_folha")
        arqs_f = arqs_f if isinstance(arqs_f, (list, tuple)) else ([arqs_f] if arqs_f else [])
        for arq_f in arqs_f:
            if not str(getattr(arq_f, "name", "")).lower().endswith(".pdf"):
                continue
            b_f = arq_f.getvalue()
            sha_f = P.sha256_curto(b_f)
            ch_f = f"pn2_folha_lida_{sha_f}"
            if ch_f not in st.session_state:
                try:
                    with st.spinner(f"Lendo “{arq_f.name}”… (pode levar de 10 segundos a 1 minuto)"):
                        st.session_state[ch_f] = importador_folha.ler_recibos_pdf(b_f)
                except importador_folha.ErroFolha as exc:
                    st.session_state[ch_f] = str(exc)
                    P.registrar_log(conn, "FOLHA_PDF_ERRO", "ERRO", usuario, None, {"arquivo": arq_f.name, "sha256": sha_f, "erro": str(exc)[:300]})
            lido_f = st.session_state[ch_f]
            if isinstance(lido_f, str):
                st.error(f"{arq_f.name}: {lido_f}")
                continue
            comp_f = lido_f["competencia"]
            st.success(f"{arq_f.name}: {len(lido_f['recibos'])} colaboradores · competência {comp_f[5:]}/{comp_f[:4]} · empresa(s) "
                       f"{', '.join(P.EMPRESAS_FOLHA.get(e, e) for e in lido_f['empresas'])} · {lido_f['paginas']} páginas.")
            for av in lido_f["avisos"][:20]:
                st.warning(av)
            if not lido_f["avisos"]:
                st.caption("Conferido: em todos os recibos a soma dos eventos fecha com o total de proventos e de descontos do recibo.")
            if not _ja_salvo(conn, "FOLHA", b_f) and st.button(f"Salvar a folha de {comp_f[5:]}/{comp_f[:4]} ({', '.join(P.EMPRESAS_FOLHA.get(e, e) for e in lido_f['empresas'])})", type="primary",
                                                               disabled=not (_folha_ok and comp_f), key=f"pn2_folha_salvar_{sha_f}"):
                try:
                    res_f = P.gravar_folha(conn, lido_f, arq_f.name, __import__("hashlib").sha256(b_f).hexdigest(), usuario)
                    if res_f["repetido"]:
                        st.info(f"Este mesmo arquivo já foi importado antes (importação #{res_f['id']}, mês {res_f['mes']}).")
                    else:
                        st.toast(f"Folha de {res_f['mes']} ({res_f['escopo']}) salva: {res_f['recibos']} colaboradores (importação #{res_f['id']}).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
                        st.rerun()
                except Exception as exc:
                    st.error(f"Não consegui salvar: {exc}")



def up_historico(conn, usuario):
    """Upload do HTML (ou JSON) do painel da contabilidade: guarda o historico do ano (acumulado, desvio mensal, recomposicao, HE, custos com pessoas) so' no banco."""
    atual = historico.ativo(conn) if historico.instalado(conn) else None
    with st.expander("Importar o histórico do painel da contabilidade (HTML)", expanded=atual is None):
        if not historico.instalado(conn):
            st.warning("Falta executar o arquivo `sql/v2_historico.sql` (SQL-21) no Supabase para o app guardar o histórico. Você já pode ler o arquivo e ver o resultado; só não dá para salvar.")
        st.caption("Envie o HTML do painel (ex.: “Painel EnerMais Setembro_2026.html”). O app lê só os números do ano (acumulado, desvio mensal, recomposição, horas extras e custos com pessoas); "
                   "nomes de colaboradores e credores do arquivo são descartados. Os números ficam só no banco, nunca no GitHub.")
        if atual:
            st.info(f"Em uso: histórico até {atual['mes'][5:]}/{atual['mes'][:4]} — “{atual['arquivo']}” (importação #{atual['id']}).")
        arq = st.file_uploader("HTML do painel (ou JSON do histórico)", type=["html", "htm", "json"], key="pn2_up_hist")
        if arq is not None:
            b = arq.getvalue()
            sha = P.sha256_curto(b)
            ch = f"pn2_hist_lido_{sha}"
            if ch not in st.session_state:
                try:
                    st.session_state[ch] = historico.ler_historico(b, arq.name)
                except historico.ErroHistorico as exc:
                    st.session_state[ch] = str(exc)
                    P.registrar_log(conn, "HISTORICO_ERRO", "ERRO", usuario, None, {"arquivo": arq.name, "sha256": sha, "erro": str(exc)[:300]})
            lido = st.session_state[ch]
            if isinstance(lido, str):
                st.error(lido)
                return
            ano_pad = dt.date.today().year
            ult = historico.MESES.index(lido["meses"][-1]) + 1 if lido["meses"] and lido["meses"][-1] in historico.MESES else 1
            c1, c2 = st.columns(2)
            ano = c1.number_input("Ano do painel", min_value=2024, max_value=2100, value=ano_pad, step=1, key=f"pn2_hist_ano_{sha}")
            mes_n = c2.selectbox("Último mês do painel", list(range(1, 13)), index=ult - 1, format_func=lambda i: historico.MESES[i - 1], key=f"pn2_hist_mes_{sha}")
            mes = f"{int(ano)}-{mes_n:02d}"
            h = {"mes": mes, "dados": lido["dados"]}
            r = historico.resumo(h)
            st.success(f"Painel lido: meses de desvio {', '.join(m['rotulo'] for m in r['desvio_meses'])} · acumulado do ano: receita {F.moeda_br(r['acumulado']['rec'])}, "
                       f"resultado {F.moeda_br(r['acumulado']['res'])} · recomposição out–dez: {len(r['recomposicao'])} meses · {len(r['serie_he'])} meses de horas extras.")
            for av in lido["avisos"]:
                st.warning(av)
            if not lido["avisos"]:
                st.caption("Conferido: receita − custo = BDI e BDI − administração = resultado, no mês e no acumulado.")
            if not _ja_salvo(conn, "HISTORICO", b) and st.button(f"Salvar como histórico até {mes_n:02d}/{int(ano)}", type="primary", disabled=not historico.instalado(conn),
                                                                 key=f"pn2_hist_salvar_{sha}"):
                try:
                    res = historico.gravar(conn, lido, mes, arq.name, usuario)
                    if res["repetido"]:
                        st.info(f"Este mesmo arquivo já foi importado antes (importação #{res['id']}, mês {res['mes']}).")
                    else:
                        P.registrar_log(conn, "HISTORICO_IMPORTADO", "INFO", usuario, mes, {"arquivo": arq.name, "sha256": lido["sha256"][:16], "importacao_id": res["id"], "meses": len(lido["meses"])})
                        st.toast(f"Histórico até {mes_n:02d}/{int(ano)} salvo (importação #{res['id']}).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
                        st.rerun()
                except Exception as exc:
                    st.error(f"Não consegui salvar: {exc}")


# ---------------------------------------------------------------- situacao, historico, reverter
def _situacao(conn):
    """Lista de conferencia do mes: o que ja foi importado (em uso) e o que falta."""
    imps = [i for i in P.importacoes_lista(conn) if i["ativo"]]
    meses = sorted({i["mes"] for i in imps if i["tipo"] != "ORCAMENTO"}, reverse=True)
    st.markdown("**O que está em uso, mês a mês**")
    if not meses:
        st.info("Nada importado ainda. Use os blocos de importação acima.")
        return
    linhas = []
    for m in meses:
        d = {"Mês": f"{m[5:]}/{m[:4]}"}
        d["DRE"] = "✅" if any(i["tipo"] == "DRE" and i["mes"] == m for i in imps) else "❌ falta"
        esc = {i["escopo"] for i in imps if i["tipo"] == "FOLHA" and i["mes"] == m}
        d["Folha Construtora"] = "✅" if "CONSTRUTORA" in esc else "❌ falta"
        d["Folha Energia"] = "✅" if "ENERGIA" in esc else "❌ falta"
        d["Projeção"] = "✅" if any(i["tipo"] == "PROJECAO" and i["mes"] == m for i in imps) else "❌ falta"
        linhas.append(d)
    orc = [i for i in imps if i["tipo"] == "ORCAMENTO"]
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
    st.caption("Orçamento ADM: " + (f"em uso — “{orc[0]['arquivo']}” (importação #{orc[0]['id']}, começa em {orc[0]['mes'][5:]}/{orc[0]['mes'][:4]})." if orc else "ainda não importado.")
               + " Os cadastros (de-para) ficam mais abaixo.")


def _historico(conn, usuario):
    st.markdown("**Histórico de importações**")
    lista = P.importacoes_lista(conn)
    if not lista:
        st.info("Nenhuma importação ainda.")
        return
    f1, f2 = st.columns(2)
    ft = f1.selectbox("Tipo", ["Todos"] + list(TIPOS), format_func=lambda t: "Todos" if t == "Todos" else TIPOS[t], key="pn2_imp_hist_tipo")
    fs = f2.selectbox("Situação", ["Todas", "Em uso", "Fora de uso"], key="pn2_imp_hist_sit")
    ver = [i for i in lista if (ft == "Todos" or i["tipo"] == ft) and (fs == "Todas" or (i["ativo"] == (fs == "Em uso")))]
    st.dataframe(pd.DataFrame([{"#": i["id"], "Tipo": TIPOS[i["tipo"]], "Mês": f"{i['mes'][5:]}/{i['mes'][:4]}", "Escopo": i["escopo"] or "–", "Arquivo": i["arquivo"],
                                "Quem": i["quem"] or "–", "Quando": _hora(i["quando"]), "Linhas": i["linhas"], "Edições": i["edicoes"],
                                "Situação": "em uso" if i["ativo"] else "fora de uso"} for i in ver]), hide_index=True, width="stretch")
    if not P.edicao_instalada(conn):
        st.warning("Falta executar o **SQL-19** (`sql/v2_edicao.sql`) no Supabase para poder reverter e editar. Até lá só dá para ver o histórico.")
        return
    st.markdown("**Reverter sem apagar**")
    if not ver:
        return
    esc = st.selectbox("Importação", [i["id"] for i in ver], key="pn2_imp_rev_id",
                       format_func=lambda k: next(f"#{i['id']} · {TIPOS[i['tipo']]} · {i['mes'][5:]}/{i['mes'][:4]} · {i['escopo'] or '–'} · {i['arquivo']} · {'em uso' if i['ativo'] else 'fora de uso'}" for i in ver if i["id"] == k))
    alvo = next(i for i in ver if i["id"] == esc)
    motivo = st.text_input("Motivo (fica registrado)", key="pn2_imp_rev_motivo")
    if alvo["ativo"]:
        st.caption("Marcar como fora de uso tira esta importação dos resultados do painel. Nada é apagado; dá para reativar depois.")
        if alvo["tipo"] == "DRE":
            st.warning("Sem DRE em uso no mês, as abas Resultado e Obras ficam sem dados desse mês.")
        if st.button("Marcar como fora de uso", key="pn2_imp_rev_off"):
            try:
                P.importacao_definir_ativo(conn, alvo["id"], False, usuario, motivo or None)
                st.rerun()
            except Exception as exc:
                st.error(f"Não consegui: {exc}")
    else:
        st.caption("Reativar põe esta importação em uso e tira de uso a que está ativa hoje no mesmo mês (e mesmo escopo).")
        if st.button("Reativar esta importação", type="primary", key="pn2_imp_rev_on"):
            try:
                P.importacao_definir_ativo(conn, alvo["id"], True, usuario, motivo or None)
                st.rerun()
            except Exception as exc:
                st.error(f"Não consegui: {exc}")


# ---------------------------------------------------------------- editar valores importados
def _norm(v):
    if v is None:
        return None
    try:
        if v != v:
            return None
    except Exception:
        pass
    if hasattr(v, "date") and not isinstance(v, dt.date):
        return v.date()
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, float):
        return round(v, 2)
    return v


def _col_cfg(cfg):
    out = {"id": None}
    for c, t in cfg["campos"]:
        if t == "num":
            out[c] = st.column_config.NumberColumn(c, format="%.2f", step=0.01)
        elif t == "int":
            out[c] = st.column_config.NumberColumn(c, format="%d", step=1)
        elif t == "date":
            out[c] = st.column_config.DateColumn(c, format="DD/MM/YYYY")
        else:
            out[c] = st.column_config.TextColumn(c)
    return out


def _editor(conn, usuario):
    st.markdown("**Editar os valores importados**")
    st.caption("Se a leitura errou ou a contabilidade quiser ajustar, é só editar a célula e salvar. Nada é apagado: o valor de antes e o de depois ficam no histórico de edições, com quem, quando e o motivo.")
    if not P.edicao_instalada(conn):
        st.warning("Falta executar o **SQL-19** (`sql/v2_edicao.sql`) no Supabase para poder editar.")
        return
    lista = [i for i in P.importacoes_lista(conn) if i["tipo"] in P.EDIT_CFG]   # o histórico do painel (HTML) não tem grade de edição: reverte-se pelo histórico de importações
    if not lista:
        st.info("Nenhuma importação para editar.")
        return
    ordem = sorted(lista, key=lambda i: (not i["ativo"], -i["id"]))
    esc = st.selectbox("Importação a editar", [i["id"] for i in ordem], key="pn2_ed_imp",
                       format_func=lambda k: next(f"#{i['id']} · {TIPOS[i['tipo']]} · {i['mes'][5:]}/{i['mes'][:4]} · {i['escopo'] or '–'} · {i['arquivo']} · {'em uso' if i['ativo'] else 'fora de uso'}" for i in ordem if i["id"] == k))
    imp = next(i for i in ordem if i["id"] == esc)
    cfg = P.EDIT_CFG[imp["tipo"]]
    dados = P.edicao_carregar(conn, imp["tipo"], imp["id"])
    st.caption(f"{cfg['nome']} · {len(dados)} linhas" + ("" if imp["ativo"] else " · atenção: esta importação está fora de uso (a edição não muda os resultados até reativá-la)."))
    if imp["tipo"] == "DRE":
        st.info("No DRE, as linhas de total (coluna *conta* vazia) são valores próprios: se corrigir uma conta, corrija também o total da linha correspondente.")
    elif imp["tipo"] == "ORCAMENTO":
        st.info("O **saldo** é automático (realizado − orçado) e os **totais dos grupos** (linhas T) acompanham: ao editar o orçado ou o realizado de uma conta, o app acerta o saldo e soma a diferença nos grupos acima, e registra esses acertos no histórico.")
    elif imp["tipo"] == "FOLHA":
        st.info("Aqui se editam os totais do recibo (salário, HE, DSR, proventos, descontos, FGTS). O detalhe evento a evento lido do PDF não é alterado.")
    df = pd.DataFrame(dados)
    filtro = st.text_input("Filtrar linhas (texto em qualquer coluna)", key=f"pn2_ed_filtro_{esc}")
    if filtro.strip() and not df.empty:
        mask = df.drop(columns=["id"]).astype(str).apply(lambda s: s.str.contains(filtro.strip(), case=False, regex=False)).any(axis=1)
        df = df[mask]
    campos = [c for c, _ in cfg["campos"]]
    editado = st.data_editor(df, key=f"pn2_ed_{esc}_{filtro}", hide_index=True, width="stretch", column_config=_col_cfg(cfg), disabled=["id"] + (["saldo"] if imp["tipo"] == "ORCAMENTO" else []), num_rows="fixed")
    alteracoes = []
    if not df.empty:
        orig = df.set_index("id")
        novo = editado.set_index("id")
        for lid in orig.index:
            for c in campos:
                a, b = _norm(orig.at[lid, c]), _norm(novo.at[lid, c])
                if a != b:
                    alteracoes.append((int(lid), c, b))
    mot = st.text_input("Motivo da edição (opcional, fica registrado)", key=f"pn2_ed_mot_{esc}")
    if st.button(f"Salvar {len(alteracoes)} alteração(ões)", type="primary", disabled=not alteracoes, key=f"pn2_ed_salvar_{esc}"):
        try:
            r = P.edicao_aplicar(conn, imp["tipo"], imp["id"], alteracoes, [], usuario, mot or None)
            st.toast(f"{r['editados']} célula(s) alterada(s). O antes e o depois estão no histórico de edições.", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
            st.rerun()
        except Exception as exc:
            st.error(f"Não consegui salvar: {exc}")
    with st.expander("Adicionar linhas que a leitura perdeu"):
        st.caption("Preencha uma linha por linha nova. Os campos obrigatórios aparecem no aviso se faltarem.")
        vazio = pd.DataFrame({c: pd.Series(dtype=("float64" if t in ("num", "int") else "object")) for c, t in cfg["campos"]})
        cc = _col_cfg(cfg)
        cc.pop("id", None)
        if imp["tipo"] == "ORCAMENTO":
            vazio = vazio.drop(columns=["saldo"])      # o saldo e' calculado
            cc.pop("saldo", None)
        novos = st.data_editor(vazio, key=f"pn2_ed_novos_{esc}", hide_index=True, width="stretch", column_config=cc, num_rows="dynamic")
        lin_novas = [{c: _norm(r[c]) for c in campos if c in novos.columns} for _, r in novos.iterrows()]
        lin_novas = [l for l in lin_novas if any(v is not None for v in l.values())]
        mot2 = st.text_input("Motivo (opcional)", key=f"pn2_ed_mot_novo_{esc}")
        if st.button(f"Adicionar {len(lin_novas)} linha(s)", disabled=not lin_novas, key=f"pn2_ed_add_{esc}"):
            try:
                r = P.edicao_aplicar(conn, imp["tipo"], imp["id"], [], lin_novas, usuario, mot2 or None)
                st.toast(f"{r['linhas_novas']} linha(s) adicionada(s).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
                st.rerun()
            except Exception as exc:
                st.error(f"Não consegui adicionar: {exc}")


# ---------------------------------------------------------------- cadastros e historico de edicoes
def _cadastros(conn, usuario):
    st.markdown("**Cadastro: departamento da folha → obra**")
    st.caption("Diz de qual obra é cada departamento dos recibos (ex.: 001.021 da Construtora). Pode corrigir ou acrescentar; nada é apagado. "
               "O de-para de credores está logo abaixo.")
    if not P.edicao_instalada(conn):
        st.warning("Falta executar o **SQL-19** (`sql/v2_edicao.sql`) no Supabase para poder editar o cadastro.")
        return
    atual = pd.DataFrame(P.depto_obra_listar(conn), columns=["empresa", "departamento", "subnivel_texto", "codigo_obra", "obra_nome"])
    ed = st.data_editor(atual, key="pn2_depto_ed", hide_index=True, width="stretch", num_rows="dynamic",
                        column_config={"empresa": st.column_config.TextColumn("Empresa (468 Construtora / 469 Energia)"), "departamento": st.column_config.TextColumn("Departamento"),
                                       "subnivel_texto": st.column_config.TextColumn("Subnível (texto do recibo)"), "codigo_obra": st.column_config.TextColumn("Código da obra"),
                                       "obra_nome": st.column_config.TextColumn("Nome da obra")})
    linhas = [{c: _norm(r[c]) for c in atual.columns} for _, r in ed.iterrows()]
    antes = {(l["empresa"], l["departamento"]): (l["subnivel_texto"], l["codigo_obra"], l["obra_nome"]) for l in P.depto_obra_listar(conn)}
    mudou = [l for l in linhas if any(v is not None for v in l.values()) and antes.get((l["empresa"], l["departamento"])) != (l["subnivel_texto"], l["codigo_obra"], l["obra_nome"])]
    if len(linhas) < len(antes):
        st.warning("Linhas removidas da tabela não são apagadas do banco (para tirar um departamento, aponte-o para a obra certa).")
    mot = st.text_input("Motivo (opcional)", key="pn2_depto_mot")
    if st.button(f"Salvar {len(mudou)} alteração(ões) no cadastro", type="primary", disabled=not mudou, key="pn2_depto_salvar"):
        try:
            r = P.depto_obra_salvar(conn, mudou, usuario, mot or None)
            st.toast(f"Cadastro salvo: {r['novos']} novo(s), {r['alterados']} alterado(s).", icon="✅")   # toast: sobrevive ao rerun (o success sumia)
            st.rerun()
        except Exception as exc:
            st.error(f"Não consegui salvar: {exc}")


def _cadastro_credores(conn, usuario):
    """De-para de credores: quem fica em 'Outros credores/Dir' (fora do ranking da Administracao). Antes ficava na aba Administracao."""
    st.markdown("**Cadastro: credores em “Outros credores/Dir” (fora do ranking da Administração)**")
    if not P.credor_grupo_instalado(conn):
        st.warning("Falta executar o **SQL-11** (`sql/v2_credor_grupo.sql`) no Supabase para poder agrupar credores. Até lá o ranking mostra todos.")
        return
    st.caption("O credor entra no grupo se o nome dele **começa com** o texto cadastrado (sem diferenciar acento ou maiúscula). Nada é apagado: remover só desativa.")
    atuais = P.credor_grupo_ativos(conn)
    if atuais:
        st.dataframe(pd.DataFrame([{"Cadastrado como": c["nome"], "Por": c["quem"] or "", "Quando": c["quando"].strftime("%d/%m/%Y")} for c in atuais]), hide_index=True, width="stretch")
    else:
        st.info("Nenhum credor cadastrado ainda neste grupo.")
    n1, n2 = st.columns([3, 1])
    novo_nome = n1.text_input("Adicionar credor ao grupo (nome ou começo do nome)", key="pn2_cg_nome")
    if n2.button("Adicionar", key="pn2_cg_add", disabled=not novo_nome.strip()):
        r_add = P.credor_grupo_adicionar(conn, novo_nome, usuario)
        if r_add["ok"]:
            st.rerun()
        else:
            st.error(r_add["erro"])
    if atuais:
        r1, r2 = st.columns([3, 1])
        rem = r1.selectbox("Tirar do grupo", [c["id"] for c in atuais], format_func=lambda i: next(c["nome"] for c in atuais if c["id"] == i), key="pn2_cg_rem")
        if r2.button("Tirar", key="pn2_cg_btn_rem"):
            P.credor_grupo_remover(conn, rem, usuario)
            st.rerun()


def _cadastro_financiamentos(conn, usuario):
    """De-para dos financiamentos: o que cada contrato financia (maquina, veiculo...). O painel sugere; aqui corrige. Aparece na aba Financiamentos da Diretoria."""
    st.markdown("**Cadastro: o que cada financiamento financia**")
    if not P.fin_bem_instalado(conn):
        st.warning("Falta executar o **SQL-26** (`sql/v2_financiamento_bem.sql`) no Supabase para poder cadastrar. Até lá a Diretoria mostra só a sugestão automática.")
        return
    st.caption("Só contratos com saldo em aberto. “Sugestão” é a classificação automática (o bem = o plano financeiro lançado); corrija a categoria ou o que foi financiado se precisar. "
               "A **taxa do contrato (% ao mês)** não vem do Sienge: se tiver, preencha e o custo médio passa a usar a taxa de cada contrato. Deixar tudo vazio volta para a sugestão. Nada é apagado.")
    try:
        f = IND.financiamentos(conn)
        inv = IND.financiamentos(conn, grupo="investimentos")
        f = {"por_contrato": f["por_contrato"] + inv["por_contrato"]}          # o cadastro vale para os dois grupos (Financiamentos e Investimentos)
    except Exception as exc:
        st.info(f"Não consegui listar os contratos agora: {exc}")
        return
    if not f["por_contrato"]:
        st.info("Nenhum contrato com saldo em aberto ainda (depende da carga semanal de títulos em aberto).")
        return
    base = pd.DataFrame([{"Contrato": c["chave"], "Aba": "Investimentos" if c.get("grupo") == "investimentos" else "Financiamentos", "Credor": c["credor"], "Saldo (principal)": c["principal"], "Sugestão": c["sugestao"],
                          "Categoria": c["categoria"] if c["origem"] == "Cadastro" else None, "Objeto": c["objeto"] if c["origem"] == "Cadastro" else None,
                          "Taxa do contrato (% a.m.)": (round(c["taxa_contrato"] * 100, 4) if c["taxa_contrato"] is not None else None),
                          "Observação": c.get("observacao")} for c in f["por_contrato"]])
    ed = st.data_editor(base, key="pn2_finbem_ed", hide_index=True, width="stretch", num_rows="fixed",
                        disabled=["Contrato", "Aba", "Credor", "Saldo (principal)", "Sugestão"],
                        column_config={"Saldo (principal)": st.column_config.NumberColumn(format="%.2f"),
                                       "Categoria": st.column_config.SelectboxColumn("Categoria (cadastro)", options=list(IND.CATEGORIAS_FIN)),
                                       "Objeto": st.column_config.TextColumn("O que foi financiado"), "Observação": st.column_config.TextColumn("Observação"),
                                       "Taxa do contrato (% a.m.)": st.column_config.NumberColumn(format="%.4f", min_value=0.0, max_value=100.0)})
    linhas, mudou = [], []
    for (_, r0), (_, r1) in zip(base.iterrows(), ed.iterrows()):
        cols = ("Categoria", "Objeto", "Observação", "Taxa do contrato (% a.m.)")
        n0 = tuple(_norm(r0[k]) for k in cols)
        n1 = tuple(_norm(r1[k]) for k in cols)
        if n0 != n1:
            mudou.append({"chave": r1["Contrato"], "categoria": n1[0], "objeto": n1[1], "observacao": n1[2], "taxa_mensal": n1[3]})
    if st.button(f"Salvar {len(mudou)} alteração(ões) dos financiamentos", type="primary", disabled=not mudou, key="pn2_finbem_salvar"):
        try:
            r = P.fin_bem_salvar(conn, mudou, usuario)
            st.cache_data.clear()
            st.toast(f"Financiamentos salvos: {r['novos']} novo(s), {r['alterados']} alterado(s), {r['limpos']} voltaram à sugestão.", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Não consegui salvar: {exc}")


def _log_edicoes(conn):
    st.markdown("**Histórico de edições**")
    if not P.edicao_instalada(conn):
        st.info("O histórico de edições aparece depois do SQL-19.")
        return
    ed = P.edicoes_lista(conn)
    if not ed:
        st.info("Nenhuma edição ainda.")
        return
    df = pd.DataFrame([{"Quando": _hora(e["quando"]), "Quem": e["quem"] or "–", "Importação": (f"#{e['importacao_id']}" if e["importacao_id"] else "cadastro"),
                        "Tipo": TIPOS.get(e["tipo"], "–"), "Ação": e["acao"].lower(), "Linha": e["linha_id"] or "", "Campo": e["campo"],
                        "Antes": e["antes"] or "", "Depois": e["depois"] or "", "Motivo": e["motivo"] or ""} for e in ed])
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("Baixar o histórico de edições (CSV)", df.to_csv(index=False).encode("utf-8-sig"), file_name="historico_edicoes.csv", mime="text/csv", key="pn2_dl_edicoes")


def render(conn, usuario):
    st.markdown("**Todas as importações da V2 num lugar só.** Envie os arquivos abaixo; as outras abas mostram o resultado. "
                "A importação do balancete (V1) continua na página própria, sem mistura.")
    _situacao(conn)
    st.divider()
    st.markdown("**Importar**")
    up_dre(conn, usuario)
    up_folha(conn, usuario)
    up_projecao(conn, usuario)
    up_orcamento(conn, usuario)
    up_historico(conn, usuario)
    st.divider()
    _historico(conn, usuario)
    st.divider()
    _editor(conn, usuario)
    st.divider()
    _cadastros(conn, usuario)
    st.divider()
    _cadastro_credores(conn, usuario)
    st.divider()
    _cadastro_financiamentos(conn, usuario)
    st.divider()
    _log_edicoes(conn)
