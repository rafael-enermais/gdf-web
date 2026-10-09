# -*- coding: utf-8 -*-
"""GDF — Demonstrativos: Balanço, DRE, Indicadores, Composição e conferências calculados pelo motor a partir dos balancetes ativos.
O relatório em PDF fica na página própria "Relatório PDF"."""
import streamlit as st

import composicao
import contexto
import db
import formatacao as F
import motor
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
validos = contexto.meses_validos(meses)
if not meses:
    st.info("Ainda não há balancete mensal importado para esta empresa. Use **Importar balancete**.")
    st.stop()
if not validos:
    st.warning("Há balancetes importados, mas a sequência de janeiro até o último mês está incompleta. Os números somam os meses do ano, então precisam de todos eles. Faltam: " + ", ".join(F.mes_br(m) for m in contexto.meses_faltantes(meses))
               + ". Importe o que falta, em qualquer ordem; já importados: " + ", ".join(F.mes_br(m) for m in meses) + ".")
    st.stop()

mes_ref = st.selectbox("Mês de referência", validos, index=len(validos) - 1, format_func=F.mes_br, key="dem_mes")
if len(validos) < len(meses):
    st.caption("Meses que não aparecem na lista não têm todos os meses anteriores importados: " + ", ".join(F.mes_br(m) for m in meses if m not in validos)
               + ". Para incluí-los, importe os meses que faltam: " + ", ".join(F.mes_br(m) for m in contexto.meses_faltantes(meses)) + ".")

try:
    ctx_dados = contexto.carregar(conn, emp["id"], mes_ref)
except motor.ErroDados as exc:
    st.error(str(exc))
    st.stop()
mapa, periodos, b, mes_ant = ctx_dados["mapa"], ctx_dados["periodos"], ctx_dados["b"], ctx_dados["mes_ant"]
bp, d, conf = ctx_dados["bp"], ctx_dados["d"], ctx_dados["conf"]

# status das importacoes mensais usadas (RASCUNHO / REVISADA)
_st = contexto.status_por_mes(conn, emp["id"])
usados = [m for m in b.ordem if m <= mes_ref]
n_rev = sum(1 for m in usados if _st.get(m) == "REVISADA")
n_ras = len(usados) - n_rev
if n_ras == 0:
    st.success(f"Status dos balancetes: todos os {len(usados)} meses (janeiro a {F.mes_br(mes_ref)}) estão **REVISADA**.")
else:
    pend = ", ".join(F.mes_br(m) for m in usados if _st.get(m) != "REVISADA")
    st.info(f"Status dos balancetes: {n_rev} **REVISADA** e {n_ras} **RASCUNHO** (ainda não revisados: {pend}). Marque como revisada no **Histórico**.")

falhas = ctx_dados["falhas"]
if falhas:
    st.warning(f"{len(falhas)} de {len(conf)} conferências com falha. Veja a aba **Conferências** antes de usar estes números.")
else:
    st.success(f"Todas as {len(conf)} conferências passaram.")

try:
    st.page_link("telas/5_Relatorio_PDF.py", label="Gerar o relatório em PDF deste mês", icon="📄")
except Exception:      # fora do menu (testes isolados) o link nao existe
    st.caption("O relatório em PDF está no menu **📄 Relatório PDF**.")

aba_bp, aba_dre, aba_ind, aba_comp, aba_conf = st.tabs(["Balanço Patrimonial", "DRE", "Indicadores", "Composição de Saldos", "Conferências"])
with aba_bp:
    st.caption(f"Em R$ — posição em 31/12/{int(mes_ref[:4]) - 1}, {tabelas._data_fim_mes(mes_ant)} e {tabelas._data_fim_mes(mes_ref)}. O resultado do período compõe o patrimônio líquido.")
    for df, est in tabelas.tabela_balanco(bp, mes_ref, mes_ant):
        st.dataframe(tabelas.estilizar(df, est), hide_index=True, width="stretch", height=min(35 * (len(df) + 1) + 3, 760))
with aba_dre:
    st.caption(f"Em R$ — período de 01/01/{mes_ref[:4]} a {tabelas._data_fim_mes(mes_ref)}.")
    df, est = tabelas.tabela_dre(d, mes_ref)
    st.dataframe(tabelas.estilizar(df, est), hide_index=True, width="stretch", height=min(35 * (len(df) + 1) + 3, 1100))
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
    st.dataframe(tabelas.estilizar(df, est), hide_index=True, width="stretch", height=min(35 * (len(df) + 1) + 3, 900))
    st.caption("PMR, PMP e ICSD não são calculados enquanto não houver receita de construção/remuneração reconhecida.")
with aba_conf:
    import pandas as pd
    if conf:
        tab = pd.DataFrame([{"": "✅" if c["ok"] else "❌", "Período": F.mes_br(c["periodo"]) if c["periodo"][:2] == "20" else c["periodo"],
                             "Grupo": c["grupo"], "Conferência": c["descricao"], "Detalhe": c["detalhe"]} for c in conf])
        so_falhas = st.checkbox("Mostrar só as que falharam", value=bool(falhas), key="dem_so_falhas")
        st.dataframe(tab[tab[""] == "❌"] if so_falhas else tab, hide_index=True, width="stretch")


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
        st.dataframe(df, hide_index=True, width="stretch", height=35 * (len(df) + 1) + 3)
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
        editado = st.data_editor(base, hide_index=True, width="stretch", disabled=["Nome no balancete"], key=f"apel_{emp['id']}_{mes_ref}", num_rows="fixed")
        if st.button("Salvar apelidos", key="apel_salvar"):
            mud = {r["Nome no balancete"]: db.txt(r["Apelido"]) for _, r in editado.iterrows()}
            n_mud = db.salvar_apelidos(conn, emp["id"], mud, usuario)
            st.success(f"{n_mud} apelido(s) atualizado(s)." if n_mud else "Nenhuma mudança.")
            if n_mud:
                st.rerun()
