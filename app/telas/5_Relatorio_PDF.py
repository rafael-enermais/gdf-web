# -*- coding: utf-8 -*-
"""GDF — Relatório PDF: gera o relatório (layout padrão Enermais) do mês escolhido, com textos editáveis, assinantes e histórico de versões."""
import hashlib
from datetime import date

import pandas as pd
import streamlit as st

import contexto
import db
import formatacao as F
import motor
import relatorio_dados
import relatorio_pdf
from auth import usuario_atual
from fuso import agora_br, fmt_br
from conexao import empresa_atual, flash, get_conn, mostrar_flash, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Relatório PDF")
mostrar_flash()
st.caption("Gera o relatório em PDF (layout padrão Enermais) com os mesmos números da tela Demonstrativos. Caminho: **rascunho** (para revisar) → "
           "**versão final** (sem marca de rascunho, para assinar no Autentique) → **registrar assinatura**. Cada geração vira uma versão nova; "
           "um relatório assinado nunca é regravado.")
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="pdf_empresa")

meses = db.listar_meses_ativos(conn, emp["id"])
validos = contexto.meses_validos(meses)
if not meses:
    st.info("Ainda não há balancete mensal importado para esta empresa. Use **Importar balancete**.")
    st.stop()
if not validos:
    st.warning("Há balancetes importados, mas falta o mês de janeiro (ou um mês no meio). O relatório precisa da sequência completa de "
               "janeiro até o mês escolhido. Meses importados: " + ", ".join(F.mes_br(m) for m in meses) + ".")
    st.stop()

mes_ref = st.selectbox("Mês de referência", validos, index=len(validos) - 1, format_func=F.mes_br, key="pdf_mes")
try:
    dados = contexto.carregar(conn, emp["id"], mes_ref)
except motor.ErroDados as exc:
    st.error(str(exc))
    st.stop()
b, bp, d, mapa, periodos, falhas = dados["b"], dados["bp"], dados["d"], dados["mapa"], dados["periodos"], dados["falhas"]

_st = contexto.status_por_mes(conn, emp["id"])
usados = [m for m in b.ordem if m <= mes_ref]
n_rev = sum(1 for m in usados if _st.get(m) == "REVISADA")
n_ras = len(usados) - n_rev
if n_ras == 0:
    st.success(f"Balancetes de janeiro a {F.mes_br(mes_ref)}: todos os {len(usados)} meses estão **REVISADA**.")
else:
    st.info(f"Balancetes de janeiro a {F.mes_br(mes_ref)}: {n_rev} **REVISADA** e {n_ras} **RASCUNHO**. O PDF sai como RASCUNHO de qualquer forma.")
if falhas:
    st.warning(f"{len(falhas)} de {len(dados['conf'])} conferências com falha. Veja a aba Conferências em **Demonstrativos** antes de usar estes números.")
else:
    st.success(f"Todas as {len(dados['conf'])} conferências passaram.")

contas_ref = periodos[mes_ref]
apelidos = db.listar_apelidos(conn, emp["id"])
cfg = db.config_empresa(conn, emp["id"])
ctx = relatorio_dados.montar(emp, b, mes_ref, bp, d, contas_ref, apelidos, None, cfg, mapa)
padrao = relatorio_dados.textos_padrao(ctx)
ROT = {"dest_1": "Destaques — parágrafo 1", "dest_2": "Destaques — parágrafo 2", "dest_3": "Destaques — parágrafo 3",
       "evo_1": "Evolução — caixa e dívida", "evo_2": "Evolução — custo de construção", "evo_3": "Evolução — patrimônio líquido",
       "res_1": "Resultado — parágrafo 1", "res_2": "Resultado — parágrafo 2", "bal_1": "Balanço — parágrafo 1", "bal_2": "Balanço — parágrafo 2",
       "comp_1": "Composição (1/2)", "comp_2": "Composição (2/2)"}
with st.expander("Textos de leitura (editáveis)"):
    st.caption("O texto já vem preenchido com os valores do mês. Ajuste o que quiser; se apagar tudo, vale o texto automático.")
    textos = {}
    for k, rot in ROT.items():
        if k in padrao and padrao[k]:
            kk = f"txt_{emp['id']}_{mes_ref}_{k}_{hashlib.md5(padrao[k].encode()).hexdigest()[:6]}"
            textos[k] = st.text_area(rot, value=padrao[k], key=kk, height=110)
    editados = {k: v for k, v in textos.items() if v.strip() and v.strip() != padrao[k].strip()}
st.subheader("Assinantes")
st.caption("Quem assina o relatório (até 6). Use a última linha vazia da tabela (**+**) para adicionar e a caixa à esquerda da linha para remover. "
           "Clique em **Salvar como padrão** para o GDF lembrar nos próximos relatórios desta empresa.")
ass0 = [{"Nome": n, "Cargo": c_} for n, c_ in ctx["empresa"]["assinantes"]]
ed = st.data_editor(pd.DataFrame(ass0 or [{"Nome": "", "Cargo": ""}], columns=["Nome", "Cargo"]), hide_index=True, num_rows="dynamic",
                    width="stretch", key=f"ass_ed_{emp['id']}_{hashlib.md5(str(ass0).encode()).hexdigest()[:6]}")
assinantes = [{"nome": (r["Nome"] or "").strip(), "cargo": (r["Cargo"] or "").strip()} for _, r in ed.iterrows() if (r["Nome"] or "").strip() or (r["Cargo"] or "").strip()][:6]
if st.button("Salvar como padrão desta empresa", key="ass_salvar"):
    db.salvar_config_empresa(conn, emp["id"], {"assinantes": assinantes}, usuario)
    flash("ok", "Assinantes salvos como padrão desta empresa.")
    st.rerun()

liberar = True
if falhas:
    liberar = st.checkbox(f"Gerar rascunho mesmo com {len(falhas)} conferência(s) com falha", key="pdf_forcar")
nomes_ok = any(a["nome"] for a in assinantes) and all(a["nome"] for a in assinantes if a["cargo"])
final_ok = n_ras == 0 and not falhas and nomes_ok
ids_usados = db.ids_importacoes_mensais(conn, emp["id"], mes_ref)
regras = db.ids_regras_ativas(conn, emp["id"])
periodo_rel = date(int(mes_ref[:4]), int(mes_ref[5:7]), 1)


def _gerar(status: str):
    try:
        agora = agora_br().strftime("%d/%m/%Y %H:%M")
        ver = db.proxima_versao_relatorio(conn, emp["id"], periodo_rel)
        ctx["empresa"]["assinantes"] = [(a["nome"], a["cargo"]) for a in assinantes]
        pdf = relatorio_pdf.gerar_pdf(ctx, editados, status, agora, ver)
        sha = hashlib.sha256(pdf).hexdigest()
        rid, ver = db.registrar_relatorio(conn, emp["id"], periodo_rel, sha, editados, assinantes, usuario,
                                          {"importacoes": ids_usados, "mapa": regras["mapa"], "apelidos": regras["apelidos"], "importacoes_revisadas": n_rev, "importacoes_rascunho": n_ras, "conferencias_falhas": len(falhas)},
                                          status=status, versao=ver)
        marca = "RASCUNHO" if status == "RASCUNHO" else "FINAL"
        st.session_state["pdf_pronto"] = {"bytes": pdf, "nome": f"GDF_{emp['codigo']}_{mes_ref}_v{ver}_{marca}.pdf", "ver": ver, "sha": sha, "mes": mes_ref,
                                          "emp": emp["id"], "status": status}
    except Exception as exc:
        db.registrar_evento(conn, "relatorio", "erro", f"Falha ao gerar PDF {mes_ref}: {exc}", empresa_id=emp["id"], usuario=usuario)
        st.error(f"Não consegui gerar o PDF ({exc}). Nada foi alterado nos dados.")


b1, b2 = st.columns(2)
if b1.button("Gerar PDF (rascunho)", type="primary" if not final_ok else "secondary", disabled=not liberar, key="pdf_gerar"):
    _gerar("RASCUNHO")
if b2.button("Gerar versão final (para assinatura)", type="primary" if final_ok else "secondary", disabled=not final_ok, key="pdf_final"):
    _gerar("REVISADO")
with st.container(border=True):
    st.markdown("**Para liberar a versão final**")
    pend_rev = [F.mes_br(m) for m in usados if _st.get(m) != "REVISADA"]
    st.markdown(f"{'✅' if not pend_rev else '❌'} Balancetes de janeiro a {F.mes_br(mes_ref)} todos **REVISADA**"
                + ("" if not pend_rev else f" — faltam: {', '.join(pend_rev)} (marque no **Histórico**)"))
    st.markdown(f"{'✅' if not falhas else '❌'} Conferências sem falha" + ("" if not falhas else f" — {len(falhas)} com falha"))
    st.markdown(f"{'✅' if nomes_ok else '❌'} Assinantes com nome preenchido" + ("" if nomes_ok else " — preencha a tabela acima"))
pronto = st.session_state.get("pdf_pronto")
if pronto and pronto["mes"] == mes_ref and pronto["emp"] == emp["id"]:
    tipo = "RASCUNHO" if pronto["status"] == "RASCUNHO" else "VERSÃO FINAL (REVISADO)"
    st.success(f"Relatório v{pronto['ver']} gerado e registrado como {tipo} (código {pronto['sha'][:8]}).")
    st.download_button("Baixar o PDF", data=pronto["bytes"], file_name=pronto["nome"], mime="application/pdf", key="pdf_baixar")

rels = db.listar_relatorios(conn, emp["id"], periodo_rel)
if rels:
    def _dados(r):
        usados = (r["meta"] or {}).get("importacoes")
        if usados is None:
            return "–"
        meta = r["meta"] or {}
        if usados != ids_usados:
            return "desatualizados (os balancetes mudaram depois)"
        if "mapa" in meta and (meta["mapa"] != regras["mapa"] or meta.get("apelidos") != regras["apelidos"]):
            return "desatualizados (mapa de contas ou apelidos mudaram depois)"
        return "atuais"
    st.markdown("**Relatórios já gerados deste mês**")
    st.dataframe(pd.DataFrame([{"Versão": f"v{r['versao']}", "Status": r["status"], "Dados": _dados(r), "Gerado por": r["gerado_por"],
                                "Em": fmt_br(r["gerado_em"]), "Código": (r["pdf_sha256"] or "")[:8]} for r in rels]),
                 hide_index=True, width="stretch")
    finais = [r for r in rels if r["status"] == "REVISADO"]
    if finais:
        with st.expander("Registrar assinatura (PDF que voltou do Autentique)"):
            st.caption("O GDF não assina. Depois de assinar fora, envie aqui o PDF assinado só para registrar: o sistema guarda o nome e o código (SHA-256) do arquivo, "
                       "não o guarda nem o altera, e a versão passa a ASSINADO (não muda mais).")
            alvo = st.selectbox("Versão assinada", finais, format_func=lambda r: f"v{r['versao']} (código {(r['pdf_sha256'] or '')[:8]})", key="ass_versao")
            arq = st.file_uploader("PDF assinado", type=["pdf"], key="ass_arquivo")
            if arq is not None:
                raw = arq.getvalue()
                sem_assinatura = b"/ByteRange" not in raw
                if sem_assinatura:
                    st.warning("Não encontrei assinatura digital dentro deste PDF. Confirme que é o arquivo assinado.")
                ok_conf = st.checkbox("Confirmo que é o PDF assinado desta versão", key="ass_confirma") if sem_assinatura else True
                if ok_conf and st.button("Registrar como assinado", key="ass_registrar"):
                    try:
                        db.registrar_assinatura(conn, alvo["id"], arq.name, hashlib.sha256(raw).hexdigest(), usuario)
                        flash("ok", f"Versão v{alvo['versao']} registrada como ASSINADO.")
                        st.rerun()
                    except db.AssinaturaInvalida as exc:
                        st.error(str(exc))
