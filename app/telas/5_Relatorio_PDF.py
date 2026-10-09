# -*- coding: utf-8 -*-
"""GDF — Relatório PDF: gera o relatório (layout padrão Enermais) do mês escolhido, com textos editáveis, assinantes e histórico de versões."""
import hashlib
from datetime import date, datetime

import pandas as pd
import streamlit as st

import contexto
import db
import formatacao as F
import motor
import relatorio_dados
import relatorio_pdf
from auth import usuario_atual
from conexao import empresa_atual, get_conn, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Relatório PDF")
st.caption("Gera o relatório em PDF (layout padrão Enermais) com os mesmos números da tela Demonstrativos. "
           "Cada geração fica registrada como **RASCUNHO**; um relatório assinado nunca é regravado.")
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
with st.expander("Assinantes"):
    ass0 = ctx["empresa"]["assinantes"]
    a1, a2 = st.columns(2)
    n1 = a1.text_input("Nome (1)", value=ass0[0][0], key=f"ass_n1_{emp['id']}")
    c1 = a1.text_input("Cargo (1)", value=ass0[0][1], key=f"ass_c1_{emp['id']}")
    n2 = a2.text_input("Nome (2)", value=ass0[1][0] if len(ass0) > 1 else "", key=f"ass_n2_{emp['id']}")
    c2 = a2.text_input("Cargo (2)", value=ass0[1][1] if len(ass0) > 1 else "", key=f"ass_c2_{emp['id']}")
    salvar_ass = st.checkbox("Guardar como padrão desta empresa", value=False, key="ass_salvar")
assinantes = [{"nome": n1.strip(), "cargo": c1.strip()}, {"nome": n2.strip(), "cargo": c2.strip()}]

liberar = True
if falhas:
    liberar = st.checkbox(f"Gerar mesmo com {len(falhas)} conferência(s) com falha (o relatório sai como RASCUNHO)", key="pdf_forcar")
if st.button("Gerar PDF (rascunho)", type="primary", disabled=not liberar, key="pdf_gerar"):
    try:
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        ctx["empresa"]["assinantes"] = [(a["nome"], a["cargo"]) for a in assinantes]
        pdf = relatorio_pdf.gerar_pdf(ctx, editados, "RASCUNHO", agora)
        sha = hashlib.sha256(pdf).hexdigest()
        ano_m, mes_m = int(mes_ref[:4]), int(mes_ref[5:7])
        rid, ver = db.registrar_relatorio(conn, emp["id"], date(ano_m, mes_m, 1), sha, editados, assinantes, usuario,
                                          {"importacoes_revisadas": n_rev, "importacoes_rascunho": n_ras, "conferencias_falhas": len(falhas)})
        if salvar_ass:
            db.salvar_config_empresa(conn, emp["id"], {"assinantes": assinantes}, usuario)
        st.session_state["pdf_pronto"] = {"bytes": pdf, "nome": f"GDF_{emp['codigo']}_{mes_ref}_v{ver}_RASCUNHO.pdf", "ver": ver, "sha": sha, "mes": mes_ref, "emp": emp["id"]}
    except Exception as exc:
        db.registrar_evento(conn, "relatorio", "erro", f"Falha ao gerar PDF {mes_ref}: {exc}", empresa_id=emp["id"], usuario=usuario)
        st.error(f"Não consegui gerar o PDF ({exc}). Nada foi alterado nos dados.")
pronto = st.session_state.get("pdf_pronto")
if pronto and pronto["mes"] == mes_ref and pronto["emp"] == emp["id"]:
    st.success(f"Relatório v{pronto['ver']} gerado e registrado como RASCUNHO (código {pronto['sha'][:8]}).")
    st.download_button("Baixar o PDF", data=pronto["bytes"], file_name=pronto["nome"], mime="application/pdf", key="pdf_baixar")
rels = db.listar_relatorios(conn, emp["id"], date(int(mes_ref[:4]), int(mes_ref[5:7]), 1))
if rels:
    st.markdown("**Relatórios já gerados deste mês**")
    st.dataframe(pd.DataFrame([{"Versão": f"v{r['versao']}", "Status": r["status"], "Gerado por": r["gerado_por"], "Em": r["gerado_em"].strftime("%d/%m/%Y %H:%M"),
                                "Código": (r["pdf_sha256"] or "")[:8]} for r in rels]), hide_index=True, use_container_width=True)
