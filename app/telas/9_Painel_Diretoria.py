# -*- coding: utf-8 -*-
"""GDF V2 - Painel da Diretoria: visao interativa e so' de leitura do Painel EnerMais (unica pagina do papel VISUALIZADOR).
Em cascata: resumo do mes -> abas (Obras, Administracao, Despesas, Pessoas, Resultado) -> clique na linha para ver o detalhe -> busca.
Os dados vem do banco no momento da abertura (cache de 2 minutos; o botao Atualizar limpa), ou seja, refletem as sincronizacoes com o Sienge
e os uploads da contabilidade. Nao grava nada."""
import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import formatacao as F
import painel_db as P
import relatorio_painel_pdf as RPP
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape

NAVY, ORANGE, AZUL = "#171C60", "#EA9527", "#5C6091"

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()


@st.cache_data(ttl=120, show_spinner="Atualizando os dados…")
def _ctx(_conn, mes: str) -> dict:
    return RPP.montar_ctx(_conn, mes, dt.datetime.now().strftime("%d/%m/%Y %H:%M"))


@st.cache_data(ttl=120, show_spinner=False)
def _meses(_conn) -> list:
    return sorted(set(P.meses_com_dre(_conn)) | set(P.meses_confirmados(_conn)) | set(P.meses_com_dados(_conn)) | set(P.folha_meses(_conn)))


def _m(v, vazio="–"):
    return F.moeda_br(v, vazio) if v is not None else vazio


def _mi(v):
    """R$ em milhoes, compacto, para os cartoes."""
    if v is None:
        return "–"
    return ("−" if v < 0 else "") + "R$ " + f"{abs(v) / 1e6:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"


def _rot(m: str) -> str:
    return f"{m[5:]}/{m[:4]}"


def _selecionada(ev, df):
    """Linha clicada (dict) de um st.dataframe com selecao, ou None."""
    try:
        rows = ev.selection.rows
    except Exception:
        return None
    return df.iloc[rows[0]].to_dict() if rows and rows[0] < len(df) else None


def _busca(df, texto, colunas):
    if not texto.strip():
        return df
    t = texto.strip().lower()
    m = pd.Series(False, index=df.index)
    for c in colunas:
        m |= df[c].astype(str).str.lower().str.contains(t, regex=False)
    return df[m]


# ------------------------------------------------------------------ cabecalho
st.title("Painel da Diretoria")
meses = _meses(conn)
if not meses:
    st.info("Ainda não há dados no painel. Assim que a contabilidade importar e o Sienge sincronizar, eles aparecem aqui.")
    st.stop()
h1, h2, h3 = st.columns([1, 2, 1])
conf = P.meses_confirmados(conn)
padrao = conf[-1] if conf else meses[-1]
mes = h1.selectbox("Mês", meses, index=meses.index(padrao), format_func=_rot, key="dir_mes")
ctx = _ctx(conn, mes)
h2.caption(f"Dados do banco em {ctx['gerado_em']} · DRE: **{ctx['dre']['origem']}**" + (" · confirmado pela contabilidade" if ctx["dre"].get("quem") else " · ainda não confirmado"))
if h3.button("Atualizar agora", key="dir_atualizar"):
    st.cache_data.clear()
    st.rerun()

dre, ob, adm, proj, desp, pes = ctx["dre"], ctx["obras"], ctx["adm"], ctx.get("proj"), ctx["desp"], ctx["pessoas"]
v = dre["valores"]
rec = ob["total"]["receita"] if ob else v["01"]
cus = ob["total"]["custo"] if ob else v["04"]
bdi = ob["total"]["bdi"] if ob else v["05"]
adm_real = adm["orcamento"]["total"]["realizado"] if adm and adm.get("orcamento") else None
resultado = round(bdi - adm_real, 2) if adm_real is not None else None

# ------------------------------------------------------------------ 1) resumo do mes
k = st.columns(5)
d_rec = (f"{(rec - proj['receita_proj_total']) / proj['receita_proj_total'] * 100:+.1f}% vs projeção".replace(".", ",")
         if proj and abs(proj["receita_proj_total"]) > 0.005 else None)
k[0].metric("Receita", _mi(rec), d_rec, border=True)
k[1].metric("Custo direto", _mi(cus), None, border=True)
k[2].metric("BDI (receita − custo)", _mi(bdi), f"{bdi / rec * 100:.1f}% da receita".replace(".", ",") if abs(rec) > 0.005 else None, border=True)
d_adm = None
if adm and adm.get("orcamento") and adm["orcamento"]["total"]["desvio_pct"] is not None:
    d_adm = f"{adm['orcamento']['total']['desvio_pct'] * 100:+.1f}% vs orçado".replace(".", ",")
k[3].metric("Administração", _mi(adm_real), d_adm, delta_color="inverse", border=True)
k[4].metric("Resultado (BDI − adm.)", _mi(resultado), None, border=True)

g1, g2 = st.columns(2)
with g1:
    if adm_real is not None:
        st.markdown("**Do faturamento ao resultado**")
        etapas = [("Receita", rec, "total"), ("Custo direto", -abs(cus), "delta"), ("BDI", bdi, "total"), ("Administração", -abs(adm_real), "delta"), ("Resultado", resultado, "total")]
        linhas, nivel = [], 0.0
        for i, (nome, val, tipo) in enumerate(etapas):
            ini, fim = (nivel, nivel + val) if tipo == "delta" else (0.0, val)
            nivel = fim
            linhas.append({"Etapa": nome, "ini": ini / 1e6, "fim": fim / 1e6, "Valor (R$ mi)": val / 1e6, "ordem": i, "cor": "neg" if val < 0 else "pos"})
        dfc = pd.DataFrame(linhas)
        ch = alt.Chart(dfc).mark_bar(size=38).encode(
            x=alt.X("Etapa:N", sort=[e[0] for e in etapas], axis=alt.Axis(labelAngle=0, title=None)),
            y=alt.Y("ini:Q", title="R$ milhões"), y2="fim:Q",
            color=alt.Color("cor:N", scale=alt.Scale(domain=["pos", "neg"], range=[AZUL, ORANGE]), legend=None),
            tooltip=["Etapa", alt.Tooltip("Valor (R$ mi):Q", format=",.2f")])
        st.altair_chart(ch, width="stretch")
    else:
        st.info("A cascata aparece quando o DRE oficial por obra e o Orçamento ADM do mês estiverem importados.")
with g2:
    serie = ctx["serie"][-12:]
    if len(serie) >= 2:
        st.markdown("**Receita mês a mês**")
        rots = [_rot(x["mes"]) for x in serie]
        dfs = pd.DataFrame({"Mês": rots, "Receita (R$ mi)": [x["receita"] / 1e6 for x in serie], "Fonte": [x["fonte"] for x in serie], "destaque": [x["mes"] == mes for x in serie]})
        ch2 = alt.Chart(dfs).mark_bar().encode(
            x=alt.X("Mês:N", sort=rots, axis=alt.Axis(labelAngle=-60, title=None)), y=alt.Y("Receita (R$ mi):Q", title="R$ milhões"),
            color=alt.condition("datum.destaque", alt.value(NAVY), alt.value("#9A9CC4")), tooltip=["Mês", alt.Tooltip("Receita (R$ mi):Q", format=",.2f"), "Fonte"])
        st.altair_chart(ch2, width="stretch")
        if any(x["fonte"].startswith("API") for x in serie):
            st.caption("Meses cinza-claros com fonte “API (a conferir)” ainda não têm DRE oficial confirmado.")

# ------------------------------------------------------------------ 2) abas (cada uma desce em detalhe ao clicar)
t_ob, t_adm, t_desp, t_pes, t_dre = st.tabs(["Obras", "Administração", "Despesas", "Pessoas", "Resultado (DRE)"])

with t_ob:
    if not ob:
        st.info("Falta o DRE oficial em PDF deste mês.")
    else:
        busca = st.text_input("Pesquisar obra (código ou nome)", key="dir_ob_busca", placeholder="ex.: 104, lote 03, Eletrobras")
        nome_cheio = ob.get("nome_cheio", {})
        regs = []
        for l in ob["linhas"]:
            regs.append({"Obra": l["obra"], "Nome": RPP._nome_obra(l, nome_cheio), "Receita": l["receita"], "Custos": l["custo"], "BDI": l["bdi"],
                         "Margem": l["margem"], "Colab. CLT": ob["colab"].get(l["obra"], 0)})
        base = pd.DataFrame(regs)
        vis = _busca(base, busca, ["Obra", "Nome"]).reset_index(drop=True)
        mostra = pd.DataFrame({"Obra": vis["Obra"], "Nome": vis["Nome"], "Receita": vis["Receita"].map(_m), "Custos": vis["Custos"].map(_m), "BDI": vis["BDI"].map(_m),
                               "Margem": vis["Margem"].map(lambda x: F.pct_br(x) if x is not None else "–"), "Colab. CLT": vis["Colab. CLT"]})
        st.caption("Clique em uma linha para ver o detalhe da obra.")
        ev = st.dataframe(mostra, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_ob_df")
        sel = _selecionada(ev, vis)
        if sel:
            st.markdown(f"#### {sel['Obra']} · {sel['Nome']}")
            a, b, c, d = st.columns(4)
            a.metric("Receita", _mi(sel["Receita"]), border=True)
            b.metric("Custos diretos", _mi(sel["Custos"]), border=True)
            c.metric("BDI real", _mi(sel["BDI"]), F.pct_br(sel["Margem"]) + " de margem" if sel["Margem"] is not None else None, border=True)
            d.metric("Colaboradores CLT", int(sel["Colab. CLT"]), border=True)
            pr = next((x for x in (proj["linhas"] if proj else []) if x["codigo"] == sel["Obra"]), None)
            if pr:
                e1, e2, e3 = st.columns(3)
                e1.metric("Receita projetada", _mi(pr["receita_proj"]), border=True)
                e2.metric("Desvio da receita", _mi(pr["desvio"]), F.pct_br(pr["desvio_pct"]) if pr["desvio_pct"] is not None else None, border=True)
                e3.metric("BDI previsto × real", _mi(pr["bdi_proj"]), f"real {_mi(pr['bdi_real'])}", delta_color="off", border=True)
            else:
                st.caption("Esta obra não tem linha na projeção de receitas do mês.")
            if pes:
                po = pes["folha"]["por_obra"].get(sel["Obra"])
                if po:
                    f1, f2, f3 = st.columns(3)
                    f1.metric("Salários (folha CLT)", _mi(po["salarios"]), border=True)
                    f2.metric("HE + DSR", _mi(po["hora_extra"] + po["dsr_he"]), border=True)
                    f3.metric("Custo da folha por colaborador", _m(po["custo"] / po["colab"]) if po["colab"] else "–", border=True)
        if ob["top_prejuizo"]:
            st.markdown("**Obras com maior prejuízo no mês**")
            st.dataframe(pd.DataFrame([{"Obra": x["obra"], "Nome": RPP._nome_obra(x, nome_cheio), "BDI": _m(x["bdi"]), "Margem": F.pct_br(x["margem"]) if x["margem"] is not None else "–"}
                                       for x in ob["top_prejuizo"]]), hide_index=True, width="stretch")

with t_adm:
    if not adm:
        st.info("Falta sincronizar as contas pagas do mês e/ou importar o Orçamento ADM.")
    else:
        o = adm.get("orcamento")
        if o:
            ot = o["total"]
            a, b, c, d = st.columns(4)
            a.metric("Orçado", _mi(ot["orcado"]), border=True)
            b.metric("Realizado", _mi(ot["realizado"]), border=True)
            c.metric("Desvio", _mi(ot["desvio"]), F.pct_br(ot["desvio_pct"]) if ot["desvio_pct"] is not None else None, delta_color="inverse", border=True)
            ac = adm.get("acumulado")
            d.metric("Desvio acumulado no ano", _mi(ac["total"]["desvio"]) if ac else "–", F.pct_br(ac["total"]["desvio_pct"]) if ac and ac["total"]["desvio_pct"] is not None else None,
                     delta_color="inverse", border=True)
            so = adm.get("serie_orc") or []
            if len(so) > 1:
                st.markdown("**Desvio mês a mês (realizado − orçado)**")
                dso = pd.DataFrame({"Mês": [_rot(x["mes"]) for x in so], "Desvio (R$ mil)": [x["desvio"] / 1e3 for x in so], "cor": ["neg" if x["desvio"] > 0 else "pos" for x in so]})
                st.altair_chart(alt.Chart(dso).mark_bar().encode(
                    x=alt.X("Mês:N", sort=list(dso["Mês"]), axis=alt.Axis(labelAngle=-45, title=None)), y=alt.Y("Desvio (R$ mil):Q"),
                    color=alt.Color("cor:N", scale=alt.Scale(domain=["pos", "neg"], range=[AZUL, ORANGE]), legend=None),
                    tooltip=["Mês", alt.Tooltip("Desvio (R$ mil):Q", format=",.0f")]), width="stretch")
            st.markdown("**Contas que mais passaram do orçado**")
            st.dataframe(pd.DataFrame([{"Conta": f"{x['codigo']} · {x['conta']}", "Orçado": _m(x["orcado"]), "Realizado": _m(x["realizado"]), "Desvio": _m(x["desvio"])} for x in o["acima"]]),
                         hide_index=True, width="stretch")
        linhas_adm = adm.get("linhas") or []
        if linhas_adm:
            st.markdown("#### Quem recebeu: unidade → credor → contas")
            un = pd.DataFrame(linhas_adm).groupby("unidade", as_index=False)["valor"].sum().sort_values("valor", ascending=False).reset_index(drop=True)
            tot = un["valor"].sum()
            st.caption("1) Clique em uma unidade (ou deixe sem seleção para ver todas). 2) Clique em um credor para ver as contas dele.")
            un_m = pd.DataFrame({"Unidade": un["unidade"], "Pago": un["valor"].map(_m), "% do total": un["valor"].map(lambda x: F.pct_br(x / tot) if tot else "–")})
            ev_u = st.dataframe(un_m, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_adm_un")
            su = _selecionada(ev_u, un)
            df_l = pd.DataFrame(linhas_adm)
            if su:
                df_l = df_l[df_l["unidade"] == su["unidade"]]
                st.markdown(f"Credores em **{su['unidade']}**")
            bc = st.text_input("Pesquisar credor", key="dir_adm_busca")
            cr = df_l.groupby("credor", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
            cr = _busca(cr, bc, ["credor"]).reset_index(drop=True)
            tot_c = df_l["valor"].sum()
            cr_m = pd.DataFrame({"Credor": cr["credor"], "Pago": cr["valor"].map(_m), "% do filtro": cr["valor"].map(lambda x: F.pct_br(x / tot_c) if tot_c else "–")}).head(60)
            ev_c = st.dataframe(cr_m, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_adm_cr")
            sc = _selecionada(ev_c, cr)
            if sc:
                ct = df_l[df_l["credor"] == sc["credor"]].groupby(["plano_cod", "plano_nome"], as_index=False)["valor"].sum().sort_values("valor", ascending=False)
                st.markdown(f"Contas pagas a **{sc['credor']}**")
                st.dataframe(pd.DataFrame({"Conta": ct["plano_cod"] + " · " + ct["plano_nome"].fillna(""), "Pago": ct["valor"].map(_m)}), hide_index=True, width="stretch")

with t_desp:
    if not desp:
        st.info("Falta sincronizar as contas pagas do mês.")
    else:
        L, tot = desp["linhas"], desp["total"]
        a, b, c = st.columns(3)
        a.metric("Pago no mês", _mi(tot), border=True)
        top5 = sum(x["valor"] for x in L[:5])
        b.metric("Top 5 do mês", F.pct_br(top5 / tot) if tot else "–", _mi(top5), delta_color="off", border=True)
        c.metric("Contas com movimento", len(L), border=True)
        bd = st.text_input("Pesquisar conta (código ou nome)", key="dir_desp_busca")
        df_d = pd.DataFrame([{"Conta": x["plano_cod"], "Nome": x["plano_nome"] or "", "valor": x["valor"]} for x in L])
        df_d = _busca(df_d, bd, ["Conta", "Nome"]).reset_index(drop=True)
        top = df_d.head(12)
        if len(top):
            st.altair_chart(alt.Chart(top).mark_bar(color=AZUL).encode(
                y=alt.Y("Nome:N", sort="-x", title=None), x=alt.X("valor:Q", title="R$"), tooltip=["Conta", "Nome", alt.Tooltip("valor:Q", format=",.2f")]), width="stretch")
        st.dataframe(pd.DataFrame({"Conta": df_d["Conta"], "Nome": df_d["Nome"], "Valor": df_d["valor"].map(_m), "% do mês": df_d["valor"].map(lambda x: F.pct_br(x / tot) if tot else "–")}).head(80),
                     hide_index=True, width="stretch")
        st.caption("Sem pessoal, encargos e transferências entre empresas; sem documentos de previsão (mesmas regras do painel).")

with t_pes:
    if not pes:
        st.info("Faltam os recibos da folha deste mês.")
    else:
        fo = pes["folha"]
        t = fo["total"]
        a, b, c, d = st.columns(4)
        a.metric("Colaboradores CLT", t["colab"], border=True)
        b.metric("Salários (horas normais)", _mi(t["salarios"]), border=True)
        c.metric("Horas extras + DSR", _mi(t["hora_extra"] + t["dsr_he"]), border=True)
        d.metric("HE + DSR ÷ salários", F.pct_br(t["he_pct"]) if t["he_pct"] is not None else "–", border=True)
        st.caption("A base de salários desta razão (só horas normais) está em validação com a contabilidade; o percentual pode mudar.")
        st.dataframe(pd.DataFrame([{"Empresa": e["empresa"], "Colab.": e["colab"], "Salários": _m(e["salarios"]), "HE + DSR": _m(e["hora_extra"] + e["dsr_he"]),
                                    "HE ÷ salários": F.pct_br(e["he_pct"]) if e["he_pct"] is not None else "–", "Custo (proventos + FGTS)": _m(e["custo"])} for e in fo["por_empresa"]]),
                     hide_index=True, width="stretch")
        st.markdown("**Colaboradores por obra**")
        po = sorted(fo["por_obra"].values(), key=lambda x: -x["colab"])
        st.dataframe(pd.DataFrame([{"Obra": x["codigo"], "Nome": x["nome"], "Colab.": x["colab"], "Salários": _m(x["salarios"]), "HE + DSR": _m(x["hora_extra"] + x["dsr_he"]),
                                    "HE ÷ salários": F.pct_br(x["he_pct"]) if x["he_pct"] is not None else "–"} for x in po]), hide_index=True, width="stretch")
        sf = pes["serie"]
        if len(sf) >= 2:
            st.markdown("**HE + DSR ÷ salários, mês a mês**")
            dfh = pd.DataFrame({"Mês": [_rot(x["mes"]) for x in sf], "%": [round(x["he_pct"] * 100, 1) for x in sf]})
            st.altair_chart(alt.Chart(dfh).mark_line(point=True, color=NAVY).encode(x=alt.X("Mês:N", sort=list(dfh["Mês"]), axis=alt.Axis(labelAngle=-45, title=None)), y="%:Q",
                                                                                 tooltip=["Mês", "%"]), width="stretch")

with t_dre:
    rb = v["01"]
    rows = []
    for cod, nome, val in dre["linhas"]:
        rows.append({"Linha": cod, "Descrição": nome, "Valor": _m(val), "% da receita bruta": F.pct_br(val / rb) if abs(rb) > 0.005 and "." not in cod else "",
                     "Fonte": dre["fontes"].get(cod, "") if "." in cod else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=35 * 25)
    if dre["manuais"]:
        st.caption("Linhas ajustadas à mão pela contabilidade (com observação registrada): " + ", ".join(dre["manuais"]) + ".")
    for av in ctx["avisos"]:
        st.caption(f"Atenção: {av}")
