# -*- coding: utf-8 -*-
"""GDF — Painel: KPIs e evolução mensal para estudo e acompanhamento de histórico (mesmos números dos Demonstrativos)."""
import pandas as pd
import streamlit as st

import contexto
import db
import formatacao as F
import fontes
import motor
import painel as P
from auth import usuario_atual
from conexao import empresa_atual, get_conn, sidebar_rodape

usuario_atual()
conn = get_conn()
sidebar_rodape()

AZUL, VERDE, LARANJA, ROXO = "#1F6FEB", "#2EA043", "#E9962A", "#8957E5"

st.title("Painel")
st.caption("KPIs e evolução mês a mês, calculados pelo mesmo motor dos Demonstrativos. Serve para estudo e acompanhamento do histórico.")
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="pn_empresa")

meses = contexto.meses_com_dados(conn, emp["id"])
if not meses:
    st.info("Ainda não há balancete importado para esta empresa. Use **Importar balancete**.")
    st.stop()

anos = sorted({m[:4] for m in meses}, reverse=True)
ano = st.selectbox("Ano", anos, key="pn_ano") if len(anos) > 1 else anos[0]
ultimo = max(m for m in meses if m[:4] == ano)
try:
    mensais, acum, mapa = contexto.carregar_base(conn, emp["id"])
    dados = fontes.calcular(mensais, acum, mapa, ultimo)
    linhas = P.serie_com_lacunas(mensais, acum, mapa, ultimo)
except motor.ErroDados as exc:
    st.error(str(exc))
    st.stop()
sem_dado = [f"{m:02d}/{ano}" for m in range(1, int(ultimo[5:7]) + 1) if f"{ano}-{m:02d}" not in {l["periodo"] for l in linhas}]
if sem_dado:
    st.info("Meses sem nenhum balancete (ficam fora dos gráficos): " + ", ".join(sem_dado) + ". Importe-os quando tiver; nada aqui trava.")

st.caption(f"Janeiro a {F.mes_br(ultimo)} de {ano} — {len(linhas)} mês(es) com balancete. Valores em R$; negativos com “−”; “–” = não calculável (faltam balancetes).")

# ------------------------------------------------------------------ cartoes do ultimo mes
atual = linhas[-1]
CARTOES = [("Caixa e aplicações", "caixa", "R$", "normal"), ("Dívida líquida", "divida_liquida", "R$", "inverse"),
           ("Patrimônio líquido", "pl", "R$", "normal"), ("Resultado acumulado no ano", "resultado_acum", "R$", "normal"),
           ("Custo de construção no mês", "custo_constr_mes", "R$", "off"), ("Liquidez corrente", "liq_corrente", "x", "normal")]
cols = st.columns(3)
for n, (rot, chave, tipo, cor) in enumerate(CARTOES):
    v, dv = P.variacao(linhas, chave)
    valor = P.fmt_kpi(v) if tipo == "R$" else P.fmt(v, tipo)
    cols[n % 3].metric(rot, valor, delta=P.delta_txt(dv, tipo), delta_color=cor, border=True)
st.caption(f"Cartões em {F.mes_br(ultimo)}; a variação é contra o mês anterior." if len(linhas) > 1 else f"Cartões em {F.mes_br(ultimo)}; ainda não há mês anterior para comparar.")

aba_evo, aba_ind, aba_tab, aba_q = st.tabs(["Evolução", "Indicadores", "Tabela mensal", "Qualidade dos dados"])
df = pd.DataFrame(linhas).set_index("rotulo")
df[list(P.COLUNAS)] = df[list(P.COLUNAS)].apply(pd.to_numeric, errors="coerce")      # n/d vira vazio nos gráficos
ordem = list(df.index)


def _serie(chaves, cores):
    d = df[chaves].rename(columns={c: P.COLUNAS[c][0] for c in chaves})
    d.index = pd.CategoricalIndex(d.index, categories=ordem, ordered=True)
    return d, cores


with aba_evo:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Caixa × dívida líquida**")
        d_, cores = _serie(["caixa", "divida_liquida"], [AZUL, LARANJA])
        st.line_chart(d_, color=cores)
    with c2:
        st.markdown("**Patrimônio líquido e capital aportado**")
        d_, cores = _serie(["pl", "capital_aportado"], [VERDE, ROXO])
        st.line_chart(d_, color=cores)
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Custo de construção no mês**")
        d_, cores = _serie(["custo_constr_mes"], [AZUL])
        st.bar_chart(d_, color=cores)
    with c4:
        st.markdown("**Resultado líquido acumulado no ano**")
        d_, cores = _serie(["resultado_acum"], [LARANJA])
        st.bar_chart(d_, color=cores)
    st.caption("O resultado intermediário reflete só os custos incorridos: a receita de construção e a remuneração do ativo de contrato "
               "entram ao final do exercício e/ou na entrada em operação da obra. Por isso o resultado do ano tende a ser negativo até lá.")

with aba_ind:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Liquidez (vezes)**")
        d_, cores = _serie(["liq_corrente", "liq_imediata"], [AZUL, VERDE])
        st.line_chart(d_, color=cores)
    with c2:
        st.markdown("**Endividamento geral e PL / Ativo**")
        d_ = df[["endiv_geral", "pl_ativo"]].mul(100).rename(columns={"endiv_geral": "Endividamento geral (%)", "pl_ativo": "PL / Ativo (%)"})
        d_.index = pd.CategoricalIndex(d_.index, categories=ordem, ordered=True)
        st.line_chart(d_, color=[LARANJA, VERDE])
    st.markdown("**Variação mensal do caixa e aportes de capital**")
    d_, cores = _serie(["variacao_caixa", "aporte_mes"], [AZUL, ROXO])
    st.bar_chart(d_, color=cores, stack=False)
    st.caption("Variação do caixa = quanto o caixa e as aplicações subiram ou caíram no mês. Aportes = variação do capital social + AFAC no mês.")

with aba_tab:
    tabela = pd.DataFrame({"Indicador": [P.COLUNAS[k][0] for k in P.COLUNAS]})
    for ln in linhas:
        tabela[ln["rotulo"]] = [P.fmt(ln[k], P.COLUNAS[k][1]) for k in P.COLUNAS]
    st.dataframe(tabela, hide_index=True, width="stretch", height=35 * (len(tabela) + 1) + 3)
    bruto = pd.DataFrame([{**{"Mês": ln["periodo"]}, **{P.COLUNAS[k][0]: ln[k] for k in P.COLUNAS}} for ln in linhas])
    st.download_button("Baixar a tabela (CSV)", data=bruto.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                       file_name=f"GDF_{emp['codigo']}_{ano}_painel.csv", mime="text/csv", key="pn_csv")
    st.caption("O CSV traz os valores sem formatação (decimal com vírgula), pronto para abrir no Excel.")

with aba_q:
    status = contexto.status_por_periodo(conn, emp["id"])
    falhas_por = {}
    for c in dados["conf"]:
        if not c["ok"]:
            falhas_por[c["periodo"]] = falhas_por.get(c["periodo"], 0) + 1
    rows = [{"Mês": F.mes_br(l["periodo"]), "Balancete mensal": status.get(("MENSAL", l["periodo"]), "–"),
             "Acumulado até o mês": status.get(("ACUMULADO", l["periodo"]), "–"),
             "Relatório do mês": {"completo": "completo", "alternativo": "completo (usa acumulado)"}.get(l["fonte"], f"parcial: n/d em {l['n_nd']} item(ns)"),
             "Conferências com falha": falhas_por.get(l["periodo"], 0)} for l in linhas]
    nomes = {l["periodo"] for l in linhas}
    for k, v in {k: v for k, v in falhas_por.items() if k not in nomes}.items():
        rows.append({"Mês": k, "Balancete mensal": "–", "Acumulado até o mês": "–", "Relatório do mês": "–", "Conferências com falha": v})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    n_ras = sum(1 for (t, m), s_ in status.items() if m[:4] == ano and m <= ultimo and s_ != "REVISADA")
    tot_f = sum(falhas_por.values())
    if n_ras or tot_f:
        st.warning(f"{n_ras} balancete(s) ainda em RASCUNHO e {tot_f} conferência(s) com falha. Use os números do painel como acompanhamento, não como fechamento.")
    else:
        st.success("Todos os balancetes estão REVISADA e todas as conferências passaram.")
