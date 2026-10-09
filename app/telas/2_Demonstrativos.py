# -*- coding: utf-8 -*-
"""GDF — Demonstrativos: Balanço, DRE, Indicadores e conferências calculados pelo motor a partir dos balancetes ativos."""
import hashlib
from datetime import date, datetime

import streamlit as st

import composicao
import db
import formatacao as F
import motor
import relatorio_dados
import relatorio_pdf
import tabelas
from auth import usuario_atual
from conexao import empresa_atual, get_conn, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Demonstrativos")
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="dem_empresa")

meses = db.listar_meses_ativos(conn, emp["id"])
validos = [m for m in meses if all(f"{m[:4]}-{i:02d}" in meses for i in range(1, int(m[5:7]) + 1))]
if not meses:
    st.info("Ainda não há balancete mensal importado para esta empresa. Use **Importar balancete**.")
    st.stop()
if not validos:
    st.warning("Há balancetes importados, mas falta o mês de janeiro (ou um mês no meio). Os demonstrativos precisam da sequência "
               "completa de janeiro até o mês escolhido. Meses importados: " + ", ".join(F.mes_br(m) for m in meses) + ".")
    st.stop()

mes_ref = st.selectbox("Mês de referência", validos, index=len(validos) - 1, format_func=F.mes_br, key="dem_mes")
if len(validos) < len(meses):
    st.caption("Meses que não aparecem na lista não têm todos os meses anteriores importados: " + ", ".join(F.mes_br(m) for m in meses if m not in validos) + ".")

mapa = db.mapa_vigente(conn, emp["id"])
periodos = {m: v for m, v in db.periodos_mensais_ativos(conn, emp["id"]).items() if m <= mes_ref}
b = motor.Balancetes(periodos, mapa)
try:
    i = b.ordem.index(mes_ref)
    mes_ant = b.ordem[i - 1] if i > 0 else mes_ref
    bp = motor.balanco(b, mes_ref, mes_ant)
    d = motor.dre(b, mes_ref)
    conf = motor.conferencias(b)
    for ate, contas in db.acumulados_ativos(conn, emp["id"]).items():
        if ate <= mes_ref and ate in b.ordem:
            conf += motor.conferir_acumulado(motor.Balancetes({m: periodos[m] for m in b.ordem if m <= ate}, mapa), contas, ate)
except motor.ErroDados as exc:
    st.error(str(exc))
    st.stop()

# status das importacoes mensais usadas (RASCUNHO / REVISADA)
_st = {f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}": i["status"] for i in db.listar_importacoes(conn, emp["id"]) if i["ativo"] and i["tipo"] == "MENSAL"}
usados = [m for m in b.ordem if m <= mes_ref]
n_rev = sum(1 for m in usados if _st.get(m) == "REVISADA")
n_ras = len(usados) - n_rev
if n_ras == 0:
    st.success(f"Status dos balancetes: todos os {len(usados)} meses (janeiro a {F.mes_br(mes_ref)}) estão **REVISADA**.")
else:
    pend = ", ".join(F.mes_br(m) for m in usados if _st.get(m) != "REVISADA")
    st.info(f"Status dos balancetes: {n_rev} **REVISADA** e {n_ras} **RASCUNHO** (ainda não revisados: {pend}). Marque como revisada no **Histórico**.")

falhas = [c for c in conf if not c["ok"]]
if falhas:
    st.warning(f"{len(falhas)} de {len(conf)} conferências com falha. Veja a aba **Conferências** antes de usar estes números.")
else:
    st.success(f"Todas as {len(conf)} conferências passaram.")

aba_bp, aba_dre, aba_ind, aba_comp, aba_conf, aba_pdf = st.tabs(["Balanço Patrimonial", "DRE", "Indicadores", "Composição de Saldos", "Conferências", "Relatório PDF"])
with aba_bp:
    st.caption(f"Em R$ — posição em 31/12/{int(mes_ref[:4]) - 1}, {tabelas._data_fim_mes(mes_ant)} e {tabelas._data_fim_mes(mes_ref)}. O resultado do período compõe o patrimônio líquido.")
    for df, est in tabelas.tabela_balanco(bp, mes_ref, mes_ant):
        st.dataframe(tabelas.estilizar(df, est), hide_index=True, use_container_width=True, height=min(35 * (len(df) + 1) + 3, 760))
with aba_dre:
    st.caption(f"Em R$ — período de 01/01/{mes_ref[:4]} a {tabelas._data_fim_mes(mes_ref)}.")
    df, est = tabelas.tabela_dre(d, mes_ref)
    st.dataframe(tabelas.estilizar(df, est), hide_index=True, use_container_width=True, height=min(35 * (len(df) + 1) + 3, 1100))
    aj = d["acumulado"]["ajustes"]
    notas = ["A receita de construção e a remuneração do ativo de contrato são reconhecidas ao final do exercício e/ou na entrada em operação da obra "
             "de concessão; o resultado intermediário reflete apenas os custos incorridos e não é representativo do resultado anual."]
    if abs(aj) >= 0.005:
        notas.append(f"'Outros ajustes líquidos' (R$ {F.num_br(aj)} no acumulado): estornos de centavos apurados no encerramento do mês.")
    for n in notas:
        st.caption(n)
with aba_ind:
    st.caption("Calculados a partir do Balanço e da DRE. Resultados são acumulados no ano.")
    df, est = tabelas.tabela_indicadores(bp, d, mes_ref, mes_ant)
    st.dataframe(tabelas.estilizar(df, est), hide_index=True, use_container_width=True, height=min(35 * (len(df) + 1) + 3, 900))
    st.caption("PMR, PMP e ICSD não são calculados enquanto não houver receita de construção/remuneração reconhecida.")
with aba_conf:
    import pandas as pd
    if conf:
        tab = pd.DataFrame([{"": "✅" if c["ok"] else "❌", "Período": F.mes_br(c["periodo"]) if c["periodo"][:2] == "20" else c["periodo"],
                             "Grupo": c["grupo"], "Conferência": c["descricao"], "Detalhe": c["detalhe"]} for c in conf])
        so_falhas = st.checkbox("Mostrar só as que falharam", value=bool(falhas), key="dem_so_falhas")
        st.dataframe(tab[tab[""] == "❌"] if so_falhas else tab, hide_index=True, use_container_width=True)


# ------------------------------------------------------------------ Composição de Saldos + apelidos
contas_ref = periodos[mes_ref]
apelidos = db.listar_apelidos(conn, emp["id"])
comp = composicao.calcular(contas_ref, composicao.GRUPOS_PADRAO, apelidos)
with aba_comp:
    st.caption(f"Em R$ — posição em {tabelas._data_fim_mes(mes_ref)}. Só aparecem contas com saldo diferente de zero; capital aportado = capital social + AFAC de cada acionista.")
    for g in comp:
        st.markdown(f"**{g['titulo']}**")
        if not g["itens"]:
            st.caption("Sem saldo nesta data.")
            continue
        import pandas as pd
        tot = g["total"]
        df = pd.DataFrame([{"Nome": n, "Saldo (R$)": F.num_br(v), "% do grupo": F.pct_br(v / tot) if abs(tot) >= 0.005 else "–"} for n, v in g["itens"]]
                          + [{"Nome": "Total", "Saldo (R$)": F.num_br(tot), "% do grupo": "100,0%"}])
        st.dataframe(df, hide_index=True, use_container_width=True, height=35 * (len(df) + 1) + 3)
    with st.expander("Apelidos — nomes que aparecem no relatório"):
        st.caption("O sistema usa o nome da conta do balancete (às vezes abreviado ou cortado). Digite um apelido para aparecer no relatório; "
                   "ele fica salvo e é reaproveitado todo mês. Apague o apelido para voltar ao nome original.")
        import pandas as pd
        linhas = {}
        for g_ in composicao.GRUPOS_PADRAO:
            if g_["modo"] != "prefixo":
                for nome, _v in composicao.nomes_do_grupo(contas_ref, g_):
                    linhas.setdefault(nome, apelidos.get(composicao.chave_apelido(nome), ""))
        base = pd.DataFrame({"Nome no balancete": list(linhas), "Apelido": list(linhas.values())})
        editado = st.data_editor(base, hide_index=True, use_container_width=True, disabled=["Nome no balancete"], key=f"apel_{emp['id']}_{mes_ref}", num_rows="fixed")
        if st.button("Salvar apelidos", key="apel_salvar"):
            mud = {r["Nome no balancete"]: (r["Apelido"] or "") for _, r in editado.iterrows()}
            n_mud = db.salvar_apelidos(conn, emp["id"], mud, usuario)
            st.success(f"{n_mud} apelido(s) atualizado(s)." if n_mud else "Nenhuma mudança.")
            if n_mud:
                st.rerun()

# ------------------------------------------------------------------ Relatório PDF
with aba_pdf:
    st.caption("Gera o relatório em PDF (layout padrão Enermais) com os números desta tela. Cada geração fica registrada como **RASCUNHO**; "
               "um relatório assinado nunca é regravado.")
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
        n1 = a1.text_input("Nome (1)", value=ass0[0][0], key=f"ass_n1_{emp['id']}"); c1 = a1.text_input("Cargo (1)", value=ass0[0][1], key=f"ass_c1_{emp['id']}")
        n2 = a2.text_input("Nome (2)", value=ass0[1][0] if len(ass0) > 1 else "", key=f"ass_n2_{emp['id']}"); c2 = a2.text_input("Cargo (2)", value=ass0[1][1] if len(ass0) > 1 else "", key=f"ass_c2_{emp['id']}")
        salvar_ass = st.checkbox("Guardar como padrão desta empresa", value=False, key="ass_salvar")
    assinantes = [{"nome": n1.strip(), "cargo": c1.strip()}, {"nome": n2.strip(), "cargo": c2.strip()}]
    liberar = True
    if falhas:
        liberar = st.checkbox(f"Gerar mesmo com {len(falhas)} conferência(s) com falha (o relatório sai como RASCUNHO)", key="pdf_forcar")
    if n_ras:
        st.caption("Há balancetes ainda em RASCUNHO; o PDF sai como RASCUNHO de qualquer forma.")
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
        import pandas as pd
        st.markdown("**Relatórios já gerados deste mês**")
        st.dataframe(pd.DataFrame([{"Versão": f"v{r['versao']}", "Status": r["status"], "Gerado por": r["gerado_por"], "Em": r["gerado_em"].strftime("%d/%m/%Y %H:%M"),
                                    "Código": (r["pdf_sha256"] or "")[:8]} for r in rels]), hide_index=True, use_container_width=True)
