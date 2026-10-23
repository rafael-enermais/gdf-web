# -*- coding: utf-8 -*-
"""GDF - Obras e contratos (so' editores): contratos de SUPRIMENTOS do Sienge por obra e por credor, com caixinhas de varias linhas e filtro em cascata
(marcar obras filtra credores e contratos; marcar credores filtra os contratos; marcar contratos mostra medicoes e anexos). Somente leitura: os dados
vem direto da API (guardados 1 hora; botao 'Atualizar do Sienge'). A Dexie le a mesma base (ferramenta `contratos`)."""
import pandas as pd
import streamlit as st

import acesso
import contratos_sienge as CS
import estilo
import selecao as SEL
import sienge_api as S
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Obras e contratos")
estilo.painel_adaptavel()

try:
    _papel = acesso.papel(conn, usuario)
except Exception:                                           # noqa: BLE001  (banco fora do ar: nao libera)
    _papel = None
if _papel is None:
    st.error("Não foi possível verificar o seu acesso agora (banco indisponível). Tente novamente em instantes.")
    st.stop()
if _papel != acesso.EDITOR:
    st.error("Esta página é só para quem edita o GDF.")
    st.stop()

st.caption("Contratos de **suprimentos** do Sienge (somente leitura). Marque a caixinha de **uma ou mais linhas**: tudo desce na mesma tela — obras filtram credores, credores filtram contratos, "
           "e contratos marcados mostram medições e anexos.")

# ------------------------------------------------------------------ dados (API; guardados 1 hora)
topo = st.columns([3, 1], vertical_alignment="bottom")
if topo[1].button("Atualizar do Sienge", key="oc_atualizar", help="Busca tudo de novo no Sienge (leva alguns segundos)."):
    CS.limpar()
try:
    with st.spinner("Buscando contratos e medições no Sienge… (a primeira vez do dia leva uns 15 segundos)"):
        dados = CS.carregar()
except S.ErroSienge as exc:
    st.error(f"Não consegui buscar os contratos no Sienge: {exc}")
    st.stop()
topo[0].caption(f"Dados do Sienge buscados em {dados['quando']} · {len(dados['contratos'])} contratos e {len(dados['medicoes'])} medições (guardados por 1 hora).")
if not dados["contratos"]:
    st.info("O Sienge não devolveu nenhum contrato de suprimentos.")
    st.stop()

NOMES_OBRA = {o["id"]: o["nome"] for c in dados["contratos"] for o in c["obras"]}

# ------------------------------------------------------------------ filtros gerais (valem para as tres tabelas)
f1, f2 = st.columns([2, 1])
busca = f1.text_input("Buscar (credor, obra, objeto ou nº do contrato)", key="oc_busca", placeholder="ex.: terraplenagem, 104, Lote 03")
situacoes = f2.multiselect("Situação do contrato", sorted({c["situacao"] for c in dados["contratos"]}), key="oc_sit", placeholder="todas")
base = {"contratos": CS.filtrar(dados, situacoes=situacoes, busca=busca), "medicoes": dados["medicoes"]}
if not base["contratos"]:
    st.info("Nenhum contrato com esses filtros.")
    st.stop()


def _tabela(df, chave, colunas, altura=None):
    """st.dataframe com caixinhas de varias linhas, numeros em formato local (dinheiro sem centavos)."""
    exib = df[colunas].copy()
    cfg = {}
    for c in colunas:
        if c == "% medido":
            cfg[c] = st.column_config.NumberColumn(c, format="percent")
        elif exib[c].dtype.kind == "f":
            exib[c] = exib[c].round(0)
            cfg[c] = st.column_config.NumberColumn(c, format="localized")
        elif exib[c].dtype.kind == "i":
            cfg[c] = st.column_config.NumberColumn(c, format="localized")
    return st.dataframe(exib, hide_index=True, width="stretch", height=altura or min(35 * (len(exib) + 1) + 3, 420), on_select="rerun", selection_mode="multi-row", key=chave,
                        column_config=cfg)


def _mi(v) -> str:
    return "R$ " + f"{v / 1e6:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"


# ------------------------------------------------------------------ obras (1º passo do fluxo; tudo na mesma tela, de cima para baixo)
df_o = CS.df_obras(base)
st.markdown("### 1 · Obras")
ev_o = _tabela(df_o, SEL.chave("oc_obras", busca, tuple(situacoes)), ["Obra", "Contratos", "Compartilhados", "Credores", "Contratado", "Medido", "% medido"], altura=300)
st.caption("Contratado = soma dos contratos que incluem a obra (contrato com mais de uma obra conta inteiro em cada uma; coluna “Compartilhados”). "
           "Medido = soma das medições lançadas na obra (mão de obra + material). Marque obras para filtrar os credores e contratos logo abaixo.")
sel_o = SEL.selecionadas(ev_o, df_o)
ob_ids = list(sel_o["_id"])
ROT_O = SEL.rotulo(sel_o["Obra"], "todas as obras")

# ------------------------------------------------------------------ credores
df_c = CS.df_credores(base, ob_ids)
st.markdown(f"### 2 · Credores · {ROT_O}")
ev_c = _tabela(df_c, SEL.chave("oc_cred", busca, tuple(situacoes), tuple(ob_ids)), ["Credor", "Contratos", "Obras", "Contratado", "Medido", "% medido"], altura=300)
st.caption("Com obras marcadas, só contam os contratos dessas obras e o medido é o dessas obras. Marque credores para filtrar os contratos logo abaixo.")
sel_c = SEL.selecionadas(ev_c, df_c)
cr_ids = list(sel_c["_id"])
ROT_C = SEL.rotulo(sel_c["Credor"], "todos os credores")

# ------------------------------------------------------------------ contratos
lista = CS.filtrar(base, obras=ob_ids, credores=cr_ids)
df_k = CS.df_contratos(lista, dados["medicoes"], ob_ids)
st.markdown(f"### 3 · Contratos · {ROT_O} · {ROT_C}")
k = st.columns(4)
tot, med, nmed = float(df_k["Total"].sum()), float(df_k["Medido"].sum()), int(df_k["Medições"].sum())
k[0].metric("Contratos", f"{len(df_k)}", border=True)
k[1].metric("Contratado", _mi(tot), border=True)
k[2].metric("Medido", _mi(med), delta=(f"{med / tot:.0%} do contratado" if tot > 0.005 else None), delta_color="off", border=True)
k[3].metric("Medições lançadas", f"{nmed}", border=True)
ev_k = _tabela(df_k, SEL.chave("oc_contr", busca, tuple(situacoes), tuple(ob_ids), tuple(cr_ids)),
               ["Contrato", "Credor", "Obras", "Situação", "Início", "Fim", "Mão de obra", "Material", "Total", "Medido", "Saldo", "Medições"], altura=380)
st.caption("Saldo = Total − Medido (não aparece com obras marcadas, porque o total do contrato não se divide por obra). Marque contratos para ver o detalhe, as medições e os anexos.")
sel_k = SEL.selecionadas(ev_k, df_k)
if len(sel_k):
    st.markdown(f"### 4 · Detalhe · {SEL.rotulo(sel_k['Contrato'], '', ate=3)}")
    por_chave = {c["chave"]: c for c in lista}
    for ch in list(sel_k["_chave"])[:5]:
        c = por_chave[ch]
        st.markdown(f"**{c['chave']}** · {c['credor']} · {c['situacao']} · {c['empresa']}  \n"
                    f"Vigência {c['inicio'] or '—'} a {c['fim'] or '—'} · {c['tipo'] or 'tipo não informado'}  \n"
                    f"Objeto: {c['objeto'][:300] or '—'}")
    if len(sel_k) > 5:
        st.caption(f"Mostrando os dados de 5 dos {len(sel_k)} contratos marcados; as medições abaixo somam todos.")
    df_m = CS.df_medicoes(dados["medicoes"], list(sel_k["_chave"]), ob_ids, NOMES_OBRA)
    st.markdown("**Medições dos contratos marcados**")
    if df_m.empty:
        st.caption("Nenhuma medição lançada.")
    else:
        m1 = df_m.copy()
        for col in ("Mão de obra", "Material", "Valor líquido"):
            m1[col] = m1[col].round(0)
        st.dataframe(m1.drop(columns=["A liberar"]), hide_index=True, width="stretch", height=min(35 * (len(m1) + 1) + 3, 360),
                     column_config={c: st.column_config.NumberColumn(c, format="localized") for c in ("Mão de obra", "Material", "Valor líquido")})
    st.markdown("**Anexos**")
    achados = st.session_state.setdefault("oc_anexos", {})
    if st.button("Listar anexos dos contratos marcados", key="oc_anexos_btn", help="Busca no Sienge só os nomes dos anexos (até 10 contratos por vez); não baixa arquivos."):
        for _, r in list(sel_k.iterrows())[:10]:
            try:
                achados[r["_chave"]] = CS.anexos(r["_doc"], r["_num"])
            except S.ErroSienge as exc:
                achados[r["_chave"]] = f"erro: {exc}"
    linhas = []
    for _, r in sel_k.iterrows():
        v = achados.get(r["_chave"])
        if isinstance(v, str):
            st.warning(f"{r['_chave']}: não consegui listar os anexos ({v}).")
        elif v is not None:
            linhas += [{"Contrato": r["_chave"], "Nº": a["n"], "Nome": a["nome"], "Descrição": a["descricao"]} for a in v] or [{"Contrato": r["_chave"], "Nº": "", "Nome": "(sem anexos)", "Descrição": ""}]
    if linhas:
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
    else:
        st.caption("Clique em “Listar anexos…” para ver quais anexos cada contrato marcado tem.")
