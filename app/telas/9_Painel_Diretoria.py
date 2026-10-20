# -*- coding: utf-8 -*-
"""GDF V2 - Painel da Diretoria: replica do painel da contabilidade (Resultado, Obras, Administracao, Despesas, Pessoas), interativo e so' de leitura.
Unica pagina do papel VISUALIZADOR. Cada aba abre com o resumo (formula / KPIs) e desce em detalhe ao clicar numa linha (conta -> credor -> obra).
Os dados vem do banco no momento da abertura (cache de 2 a 5 minutos; o botao Atualizar limpa), ou seja, refletem as sincronizacoes com o Sienge e os
uploads da contabilidade. Nao grava nada. So' a aba aberta e' calculada (as abas de Despesas/Pessoas leem o ano todo)."""
import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import diretoria_dados as DD
import formatacao as F
import historico as HIST
import painel_db as P
import relatorio_painel_pdf as RPP
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape

NAVY, ORANGE, AZUL, CINZA = "#171C60", "#F99D20", "#5C6091", "#B9C3D4"
BOM, RUIM = "#1F8A55", "#C0392B"

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()


def _sem_latex(f):
    """O Streamlit trata '$...$' como formula: 'R$ 9,29 mi · custos R$ 9,36 mi' vira texto verde. Escapa o cifrao nos textos corridos (so' nesta pagina)."""
    def _f(body, *a, **k):
        return f(body.replace("$", "\\$") if isinstance(body, str) else body, *a, **k)
    return _f


_cap, _md, _info, _warn = _sem_latex(st.caption), _sem_latex(st.markdown), _sem_latex(st.info), _sem_latex(st.warning)


@st.cache_data(ttl=120, show_spinner="Atualizando os dados…")
def _ctx(_conn, mes: str) -> dict:
    return RPP.montar_ctx(_conn, mes, dt.datetime.now().strftime("%d/%m/%Y %H:%M"))


@st.cache_data(ttl=120, show_spinner=False)
def _meses(_conn) -> list:
    return sorted(set(P.meses_com_dre(_conn)) | set(P.meses_confirmados(_conn)) | set(P.meses_com_dados(_conn)) | set(P.folha_meses(_conn)))


@st.cache_data(ttl=300, show_spinner="Lendo as contas pagas do ano…")
def _pagos(_conn, mes: str):
    """Contas pagas de janeiro ate o mes (credor, centro de custo, obra) + as contas excluidas das Despesas pelas regras. Devolve (linhas, prefixos_fora)."""
    regras = P.regras_ativas(_conn, "DESPESAS")
    linhas = DD.pagos_detalhe(_conn, f"{mes[:4]}-01", mes, sem_previsao=P.exclui_previsao(regras))
    return linhas, P.prefixos_excluidos(regras)


def _m(v, vazio="–"):
    return F.moeda_br(v, vazio) if v is not None else vazio


def _mi(v, sinal=False):
    """R$ em milhoes (ou mil), compacto, para os cartoes. Com sinal=True mostra '+'/'-' (usa hifen para a cor do delta do st.metric)."""
    if v is None:
        return "–"
    a = abs(v)
    s = ("-" if v < 0 else ("+" if sinal and v > 0 else "")) if sinal else ("−" if v < 0 else "")
    if a >= 1e6:
        return s + "R$ " + f"{a / 1e6:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"
    if a >= 1e3:
        return s + "R$ " + f"{a / 1e3:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mil"
    return s + "R$ " + f"{a:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


def _delta(real, prev):
    """Texto do desvio (real - previsto) para o st.metric: '+R$ 1,00 mi · +3,2%'."""
    if real is None or prev is None:
        return None
    dv = real - prev
    p = f" · {F.pct_br(dv / abs(prev), 1).replace('−', '-')}" if abs(prev) > 0.005 else ""
    return _mi(dv, True) + p


def _barras_mes(rotulos, valores, titulo_y="R$ milhões", cor=NAVY, destaque=None, divisor=1e6, altura=240):
    df = pd.DataFrame({"Mês": rotulos, "v": [x / divisor for x in valores], "dest": [(i == destaque) for i in range(len(valores))]})
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("Mês:N", sort=rotulos, axis=alt.Axis(labelAngle=0, title=None)), y=alt.Y("v:Q", title=titulo_y),
        color=alt.condition("datum.dest", alt.value(ORANGE), alt.value(cor)), tooltip=["Mês", alt.Tooltip("v:Q", title=titulo_y, format=",.2f")]).properties(height=altura)


# ------------------------------------------------------------------ cabecalho
st.title("Painel da Diretoria")
meses = _meses(conn)
if not meses:
    _info("Ainda não há dados no painel. Assim que a contabilidade importar e o Sienge sincronizar, eles aparecem aqui.")
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
hist = ctx.get("hist")
v = dre["valores"]
rec = ob["total"]["receita"] if ob else v["01"]
cus = abs(ob["total"]["custo"]) if ob else abs(v["04"])
bdi = ob["total"]["bdi"] if ob else v["05"]
orc_mes = adm["orcamento"] if adm and adm.get("orcamento") else None
adm_real = orc_mes["total"]["realizado"] if orc_mes else None
adm_orc = orc_mes["total"]["orcado"] if orc_mes else None
resultado = round(bdi - adm_real, 2) if adm_real is not None else None

_TODAS = bool(st.session_state.get("dir_todas_abas"))        # so' os testes ligam: renderiza todas as abas de uma vez
aba_res, aba_ob, aba_adm, aba_desp, aba_pes = st.tabs(["Resultado", "Obras", "Administração", "Despesas", "Pessoas"], key="dir_abas", on_change="rerun")


# ------------------------------------------------------------------ dados compartilhados entre abas (PJ e colaboradores)
def _pagos_df():
    linhas, fora = _pagos(conn, mes)
    return DD.para_df(linhas), fora


def _colaboradores():
    """Colaboradores do mes: CLT (recibos da folha) + PJ (contas pagas 'Salarios PJ'). -> dict com total, obra, adm, pj, por_obra_pj; None onde falta fonte."""
    df, _ = _pagos_df()
    pj = DD.pj_do_mes(df, mes)
    clt = pes["folha"]["total"]["colab"] if pes else None
    return {"pj": pj, "clt": clt}


# ------------------------------------------------------------------ 1) RESULTADO
def _termos(modo: str):
    """Receita - Custo = BDI - Administracao = Resultado: [(chave, rotulo, real, previsto, quanto_maior_melhor)]. Previsto None quando nao ha fonte."""
    rec_p = bdi_p = cus_p = None
    if proj and abs(proj["receita_proj_total"]) > 0.005:
        rec_p = proj["receita_proj_total"]
        bdi_p = proj["total"]["bdi_proj"]
        cus_p = round(rec_p - bdi_p, 2)
    res_p = round(bdi_p - adm_orc, 2) if bdi_p is not None and adm_orc is not None else None
    atual = {"rec": (rec, rec_p), "cus": (cus, cus_p), "bdi": (bdi, bdi_p), "adm": (adm_real, adm_orc), "res": (resultado, res_p)}
    if modo == "mes":
        return atual
    if not hist:
        return None
    ate, ac, dev = hist["ate"], hist["acumulado"], hist.get("desvio_acumulado", {})
    ant = f"{int(mes[:4]) - (1 if mes[5:] == '01' else 0)}-{(int(mes[5:]) - 2) % 12 + 1:02d}"
    if ate != mes and ate != ant:
        return None
    out = {}
    for k in ("rec", "cus", "bdi", "adm", "res"):
        real_h = ac.get(k)
        prev_h = (real_h - dev[k]) if real_h is not None and k in dev else None
        if ate == mes:
            out[k] = (real_h, prev_h)
        else:                                                     # historico ate o mes anterior + o mes atual
            r_m, p_m = atual[k]
            out[k] = (None if real_h is None or r_m is None else real_h + r_m, None if prev_h is None or p_m is None else prev_h + p_m)
    return out


def _formula(modo: str):
    termos = _termos(modo)
    if not termos:
        _info("O acumulado do ano aparece quando o histórico do painel da contabilidade cobre o mês escolhido (Importações (V2) → Histórico do painel).")
        return
    rot = [("rec", "Receita (base-line)", True), ("cus", "Custos diretos", False), ("bdi", "BDI", True), ("adm", "Administração", False), ("res", "Resultado", True)]
    cols = st.columns([5, 1, 5, 1, 5, 1, 5, 1, 5], vertical_alignment="center")
    for i, (k, nome, maior_melhor) in enumerate(rot):
        real_, prev_ = termos[k]
        with cols[i * 2]:
            with st.container(border=True):
                st.metric(nome, _mi(real_), _delta(real_, prev_), delta_color="normal" if maior_melhor else "inverse")
                _cap(f"previsto {_mi(prev_)}" if prev_ is not None else "previsto n/d")
        if i < 4:
            cols[i * 2 + 1].markdown(f"<div style='text-align:center;font-size:1.6rem;font-weight:800;color:#7A859A'>{'−' if i % 2 == 0 else '='}</div>", unsafe_allow_html=True)
    # frase do que aconteceu (calculada, nao fixa)
    partes = []
    for k, nome, maior_melhor in rot:
        real_, prev_ = termos[k]
        if real_ is None or prev_ is None:
            continue
        dv = real_ - prev_
        if abs(dv) < 0.005:
            continue
        acima = dv > 0
        partes.append(f"{nome.split(' (')[0].lower()} {_mi(abs(dv)).replace('−', '')} {'acima' if acima else 'abaixo'} do previsto")
    if partes:
        _cap("Em relação ao previsto: " + "; ".join(partes) + ". Para custos e administração, acima do previsto é estouro.")


if aba_res.open or _TODAS:
    with aba_res:
        modo_lbl = st.radio("Período", ["Mês", "Acumulado no ano"], horizontal=True, key="dir_periodo")
        _formula("mes" if modo_lbl == "Mês" else "acc")
        g1, g2 = st.columns(2)
        with g1:
            _md("**Desvio mensal (realizado − previsto)**")
            if hist and hist["desvio_linhas"]:
                linhas_h = list(hist["desvio_linhas"])
                sel_h = st.selectbox("Métrica", linhas_h, index=len(linhas_h) - 1, key="dir_ano_linha", label_visibility="collapsed")
                ml = [m["rotulo"] for m in hist["desvio_meses"]]
                vals_h = hist["desvio_linhas"][sel_h]
                estouro = sel_h in ("Custos", "Despesas ADM")        # nessas linhas, positivo = gastou mais que o previsto (ruim)
                dfd = pd.DataFrame({"Mês": ml, "Desvio (R$ mi)": [x / 1e6 for x in vals_h]})
                dfd["cor"] = ["bom" if ((x >= 0) != estouro) else "ruim" for x in vals_h]
                st.altair_chart(alt.Chart(dfd).mark_bar().encode(
                    x=alt.X("Mês:N", sort=ml, axis=alt.Axis(labelAngle=0, title=None)), y=alt.Y("Desvio (R$ mi):Q", title="R$ milhões"),
                    color=alt.Color("cor:N", scale=alt.Scale(domain=["bom", "ruim"], range=[BOM, RUIM]), legend=None),
                    tooltip=["Mês", alt.Tooltip("Desvio (R$ mi):Q", format=",.2f")]).properties(height=240), width="stretch")
                _cap("Para Custos e Despesas ADM, valor positivo indica estouro. Janeiro = desvio acumulado menos a soma de fevereiro em diante.")
            else:
                _info("O desvio mensal aparece quando o histórico do painel da contabilidade é importado.")
        with g2:
            _md("**Recomposição out–dez**")
            if hist and hist["recomposicao"]:
                rc = hist["recomposicao"]
                st.dataframe(pd.DataFrame([{"Mês": r["rotulo"], "Projeção": _m(r["projecao"]), "Para cobrir o déficit": _m(r["para_cobrir"])} for r in rc]
                                          + [{"Mês": "Out–Dez", "Projeção": _m(sum(r["projecao"] for r in rc)), "Para cobrir o déficit": _m(sum(r["para_cobrir"] for r in rc))}]),
                             hide_index=True, width="stretch")
                _cap("Faturamento necessário para cobrir o déficit acumulado de base-line, distribuído proporcionalmente à projeção.")
            else:
                _info("A recomposição aparece quando o histórico do painel da contabilidade é importado.")
        serie = ctx["serie"][-12:]
        if len(serie) >= 2:
            _md("**Receita mês a mês**")
            rots = [_rot(x["mes"]) for x in serie]
            dfs = pd.DataFrame({"Mês": rots, "Receita (R$ mi)": [x["receita"] / 1e6 for x in serie], "Fonte": [x["fonte"] for x in serie], "destaque": [x["mes"] == mes for x in serie]})
            st.altair_chart(alt.Chart(dfs).mark_bar().encode(
                x=alt.X("Mês:N", sort=rots, axis=alt.Axis(labelAngle=-60, title=None)), y=alt.Y("Receita (R$ mi):Q", title="R$ milhões"),
                color=alt.condition("datum.destaque", alt.value(NAVY), alt.value("#9A9CC4")), tooltip=["Mês", alt.Tooltip("Receita (R$ mi):Q", format=",.2f"), "Fonte"]).properties(height=220), width="stretch")
            if any(x["fonte"].startswith("API") for x in serie):
                _cap("Meses cinza-claros com fonte “API (a conferir)” ainda não têm DRE oficial confirmado.")
        with st.expander("DRE do mês (linha a linha)"):
            rb = v["01"]
            rows = []
            for cod, nome, val in dre["linhas"]:
                rows.append({"Linha": cod, "Descrição": nome, "Valor": _m(val), "% da receita bruta": F.pct_br(val / rb) if abs(rb) > 0.005 and "." not in cod else "",
                             "Fonte": dre["fontes"].get(cod, "") if "." in cod else ""})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=35 * 25)
            if dre["manuais"]:
                _cap("Linhas ajustadas à mão pela contabilidade (com observação registrada): " + ", ".join(dre["manuais"]) + ".")
            for av in ctx["avisos"]:
                _cap(f"Atenção: {av}")


# ------------------------------------------------------------------ 2) OBRAS
if aba_ob.open or _TODAS:
    with aba_ob:
        if not ob:
            _info("Falta o DRE oficial em PDF deste mês.")
        else:
            colab_info = _colaboradores()
            dfp_pj, _fora_pj = _pagos_df()
            pj_linhas = DD.pj_por_obra(dfp_pj, mes)                                   # cada PJ aparece em todas as obras em que recebeu (com o %)
            pj_obra = {}
            for _x in pj_linhas:
                pj_obra.setdefault(_x["obra"], set()).add(_x["credor"])
            nome_cheio = ob.get("nome_cheio", {})
            proprias = {l["obra"] for l in ob["linhas"] if l["obra"] != "DEM"}
            prev_por_obra = {x["codigo"]: x for x in (proj["linhas"] if proj else [])}
            regs = []
            for l in ob["linhas"]:
                clt = ob["colab"].get(l["obra"], 0)
                pj_n = (len(set().union(*[cr for c, cr in pj_obra.items() if c not in proprias and c not in ("ADM", "99", "sem de-para")]))
                        if l["obra"] == "DEM" else len(pj_obra.get(l["obra"], ())))
                pr = prev_por_obra.get(l["obra"])
                hc = clt + pj_n
                regs.append({"Obra": l["obra"], "Nome": RPP._nome_obra(l, nome_cheio), "Receita": l["receita"], "Custos": abs(l["custo"]), "BDI previsto": pr["bdi_proj"] if pr else None,
                             "BDI real": l["bdi"], "Desvio BDI": (l["bdi"] - pr["bdi_proj"]) / abs(pr["bdi_proj"]) if pr and abs(pr["bdi_proj"]) > 0.005 else None,
                             "CLT": clt, "PJ": pj_n, "Colab.": hc, "Fat./colab.": (l["receita"] / hc) if hc and l["obra"] != "DEM" else None,
                             "Custo/colab.": (abs(l["custo"]) / hc) if hc and l["obra"] != "DEM" else None,
                             "Margem": l["margem"], "receita_proj": pr["receita_proj"] if pr else None})
            base = pd.DataFrame(regs)
            main = base[base["Obra"] != "DEM"]
            tr, tc, tb = ob["total"]["receita"], abs(ob["total"]["custo"]), ob["total"]["bdi"]
            rec_p = proj["receita_proj_total"] if proj else None
            bdi_p = proj["total"]["bdi_proj"] if proj else None
            cus_p = (rec_p - bdi_p) if rec_p is not None and bdi_p is not None else None
            neg = int((main["BDI real"] < 0).sum())
            k = st.columns(6)
            k[0].metric("Receita realizada", _mi(tr), _delta(tr, rec_p), border=True)
            k[1].metric("Custos", _mi(tc), _delta(tc, cus_p), delta_color="inverse", border=True)
            k[2].metric("BDI", _mi(tb), _delta(tb, bdi_p), border=True)
            k[3].metric("Obras com prejuízo", f"{neg} de {len(main)}", "BDI negativo no mês", delta_color="off", border=True)
            if len(main):
                mx, mn = main.loc[main["BDI real"].idxmax()], main.loc[main["BDI real"].idxmin()]
                k[4].metric("Maior BDI", str(mx["Nome"] or mx["Obra"])[:22], _mi(mx["BDI real"], True), border=True)
                k[5].metric("Menor BDI", str(mn["Nome"] or mn["Obra"])[:22], _mi(mn["BDI real"], True), border=True)
            busca = st.text_input("Pesquisar obra (código ou nome)", key="dir_ob_busca", placeholder="ex.: 104, lote 03, Eletrobras")
            vis = _busca(base, busca, ["Obra", "Nome"]).reset_index(drop=True)
            _cap("Clique em uma linha para ver o detalhe da obra; clique no cabeçalho para ordenar. Previsto = projeção de receitas do mês.")
            mostra = vis[["Obra", "Nome", "Receita", "Custos", "BDI previsto", "BDI real", "Desvio BDI", "Margem", "Colab.", "Fat./colab.", "Custo/colab."]]
            cfg = {c: st.column_config.NumberColumn(c, format="localized") for c in ("Receita", "Custos", "BDI previsto", "BDI real", "Fat./colab.", "Custo/colab.")}
            cfg["Desvio BDI"] = st.column_config.NumberColumn("Desvio BDI", format="percent")
            cfg["Margem"] = st.column_config.NumberColumn("Margem", format="percent")
            ev = st.dataframe(mostra, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_ob_df", column_config=cfg)
            sel = _selecionada(ev, vis)
            _cap(f"Total: receita {_mi(tr)} · custos {_mi(tc)} · BDI {_mi(tb)} · {int(base['Colab.'].sum())} colaboradores nas obras.")
            if sel:
                _md(f"#### {sel['Obra']} · {sel['Nome']}")
                a, b, c, d = st.columns(4)
                a.metric("Receita realizada", _mi(sel["Receita"]), border=True)
                b.metric("Receita prevista", _mi(sel["receita_proj"]) if pd.notna(sel["receita_proj"]) else "sem projeção", border=True)
                c.metric("Custos diretos", _mi(sel["Custos"]), border=True)
                d.metric("BDI real", _mi(sel["BDI real"]), F.pct_br(sel["Margem"]) + " de margem" if sel["Margem"] is not None else None, border=True)
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("Colaboradores", int(sel["Colab."]), f"{int(sel['CLT'])} CLT + {int(sel['PJ'])} PJ", delta_color="off", border=True)
                e2.metric("Faturamento por colaborador", _mi(sel["Fat./colab."]) if pd.notna(sel["Fat./colab."]) else "–", border=True)
                e3.metric("Custo por colaborador", _mi(sel["Custos"] / sel["Colab."]) if sel["Colab."] else "–", border=True)
                po = pes["folha"]["por_obra"].get(sel["Obra"]) if pes else None
                e4.metric("Custo da folha CLT por colaborador", _m(po["custo"] / po["colab"]) if po and po["colab"] else "–", border=True)
            _cap("Colaboradores = CLT da folha do mês + PJ alocado na obra onde mais recebeu em “Salários PJ” (contas pagas). Obras sem projeção não têm BDI previsto.")

            # ---- cascata da obra clicada: principais credores + colaboradores alocados (o clique na linha escolhe a obra nos dois blocos)
            dfp_ob, fora_ob = _pagos_df()
            nomes_ob = {l["obra"]: (RPP._nome_obra(l, nome_cheio) or l["obra"]) for l in ob["linhas"]}
            nao_obra = ("ADM", "99", "")
            proprias_l = sorted(proprias)

            def _destino_ob(cod: str):
                """Codigo do de-para -> opcao da lista: obra propria, 'DEM' (demais obras) ou None (administracao / sem de-para ficam fora)."""
                if cod in proprias:
                    return cod
                return None if cod in nao_obra or cod == "sem de-para" else "DEM"

            regs_c = [{"Nome": c["nome"], "Função": c["cargo"], "Tipo": "CLT", "dest": _destino_ob(c["obra"])} for c in P.folha_colaboradores(conn, mes)]
            for x in DD.pj_por_obra(dfp_ob, mes):
                regs_c.append({"Nome": x["credor"], "Função": f"Prestador de serviço (PJ) — {round(x['pct'] * 100)}% nesta obra", "Tipo": "PJ", "dest": _destino_ob(x["obra"])})
            col_df = pd.DataFrame([r for r in regs_c if r["dest"]], columns=["Nome", "Função", "Tipo", "dest"])
            opcoes = ["ALL"] + [c for c in [*proprias_l, "DEM"] if len(col_df) and (col_df["dest"] == c).any()]
            nome_op = lambda c: "Todas as obras" if c == "ALL" else ("Demais obras" if c == "DEM" else f"{c} · {nomes_ob.get(c, c)}")      # noqa: E731
            cod_sel = sel["Obra"] if sel else None
            if st.session_state.get("dir_ob_ultima") != cod_sel:                    # linha nova clicada (ou limpa): leva a lista para a mesma obra
                st.session_state["dir_ob_ultima"] = cod_sel
                st.session_state["dir_col_obra"] = cod_sel if cod_sel in opcoes else "ALL"
            if st.session_state.get("dir_col_obra") not in opcoes:
                st.session_state["dir_col_obra"] = "ALL"

            _md(f"**Principais credores · {nomes_ob.get(cod_sel, cod_sel) if cod_sel and cod_sel != 'DEM' else ('demais obras' if cod_sel == 'DEM' else 'todas as obras')}**")
            dd_ob = DD.despesas_df(dfp_ob, fora_ob)
            if cod_sel == "DEM":
                alvo = [c for c in dd_ob["obra"].unique() if c not in proprias and c not in nao_obra] if len(dd_ob) else []
            else:
                alvo = [cod_sel] if cod_sel else None
            cr_ob = DD.credores_da_obra(dd_ob, alvo, mes)
            if cr_ob["linhas"]:
                st.dataframe(pd.DataFrame({"Credor": [x["chave"] for x in cr_ob["linhas"]], "Acumulado no ano": [_m(x["acumulado"]) for x in cr_ob["linhas"]],
                                           "%": [F.pct_br(x["acumulado"] / cr_ob["total"]) if cr_ob["total"] else "–" for x in cr_ob["linhas"]],
                                           _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in cr_ob["linhas"]]}), hide_index=True, width="stretch")
                _cap(("Todos os credores." if cr_ob["n"] <= len(cr_ob["linhas"]) else f"Top {len(cr_ob['linhas'])} de {cr_ob['n']} credores.")
                           + " Contas pagas, sem pessoal e encargos (estão na lista de colaboradores e na aba Pessoas). Obra pelo centro de custo do lançamento.")
            else:
                _cap("Sem contas pagas para esta seleção (ou falta o de-para de centros de custo → obra).")

            _md(f"**Colaboradores alocados nas obras — {_rot(mes)}**")
            f1, f2 = st.columns([2, 3])
            obra_col = f1.selectbox("Obra", opcoes, format_func=nome_op, key="dir_col_obra")
            q_col = f2.text_input("Buscar nome ou função", key="dir_col_busca", placeholder="ex.: engenheiro, silva")
            lista = col_df if obra_col == "ALL" else col_df[col_df["dest"] == obra_col]
            lista = _busca(lista, q_col, ["Nome", "Função"]) if len(lista) else lista
            if len(lista):
                mostra_c = lista[["Nome", "Função"]].copy()
                if obra_col == "ALL":
                    mostra_c["Obra"] = lista["dest"].map(lambda c: "Demais obras" if c == "DEM" else f"{c} · {nomes_ob.get(c, c)}")
                st.dataframe(mostra_c, hide_index=True, width="stretch", height=min(35 * (len(mostra_c) + 1) + 3, 420))
                n_clt = int((lista["Tipo"] == "CLT").sum())
                n_pj = int(lista.loc[lista["Tipo"] == "PJ", "Nome"].nunique())
                linhas_pj = int((lista["Tipo"] == "PJ").sum())
                _cap(f"{n_clt + n_pj} colaboradores ({n_clt} CLT + {n_pj} PJ)"
                           + (f"; {linhas_pj - n_pj} linhas a mais porque PJ que atendem mais de uma obra aparecem em cada uma, com o % do valor pago naquela obra" if linhas_pj > n_pj else "")
                           + ". CLT pelos recibos da folha do mês; PJ pelos credores de “Salários PJ” pagos no mês. Administração fora da lista.")
            else:
                _cap("Sem colaboradores para esta seleção (folha do mês ainda não importada ou obra sem pessoal).")
            if ob["top_prejuizo"]:
                _md("**Obras com maior prejuízo no mês**")
                st.dataframe(pd.DataFrame([{"Obra": x["obra"], "Nome": RPP._nome_obra(x, nome_cheio), "BDI": _m(x["bdi"]), "Margem": F.pct_br(x["margem"]) if x["margem"] is not None else "–"}
                                           for x in ob["top_prejuizo"]]), hide_index=True, width="stretch")


# ------------------------------------------------------------------ 3) ADMINISTRACAO
if aba_adm.open or _TODAS:
    with aba_adm:
        if not adm:
            _info("Falta sincronizar as contas pagas do mês e/ou importar o Orçamento ADM.")
        else:
            o = adm.get("orcamento")
            ac = adm.get("acumulado")
            so = adm.get("serie_orc") or []
            if o:
                ot = o["total"]
                k = st.columns(5)
                k[0].metric(f"Orçado {_rot(mes)}", _mi(ot["orcado"]), border=True)
                k[1].metric(f"Realizado {_rot(mes)}", _mi(ot["realizado"]), _delta(ot["realizado"], ot["orcado"]), delta_color="inverse", border=True)
                k[2].metric("Orçado no ano", _mi(ac["total"]["orcado"]) if ac else "–", border=True)
                k[3].metric("Realizado no ano", _mi(ac["total"]["realizado"]) if ac else "–", _delta(ac["total"]["realizado"], ac["total"]["orcado"]) if ac else None, delta_color="inverse", border=True)
                acima_n = sum(1 for x in so if x["realizado"] > x["orcado"])
                k[4].metric("Meses acima do orçado", f"{acima_n} de {len(so)}" if so else "–", "realizado > orçado", delta_color="off", border=True)
                if len(so) > 1:
                    _md("**Despesas ADM — orçado × realizado por mês**")
                    linhas_g = []
                    for x in so:
                        linhas_g.append({"Mês": _rot(x["mes"]), "Série": "Orçado", "v": x["orcado"] / 1e6})
                        linhas_g.append({"Mês": _rot(x["mes"]), "Série": "Realizado acima do orçado" if x["realizado"] > x["orcado"] else "Realizado", "v": x["realizado"] / 1e6})
                    dg = pd.DataFrame(linhas_g)
                    ordem_m = [_rot(x["mes"]) for x in so]
                    st.altair_chart(alt.Chart(dg).mark_bar().encode(
                        x=alt.X("Mês:N", sort=ordem_m, axis=alt.Axis(labelAngle=0, title=None)), xOffset=alt.XOffset("Série:N"),
                        y=alt.Y("v:Q", title="R$ milhões"),
                        color=alt.Color("Série:N", scale=alt.Scale(domain=["Orçado", "Realizado", "Realizado acima do orçado"], range=[CINZA, NAVY, RUIM]), legend=alt.Legend(orient="bottom", title=None)),
                        tooltip=["Mês", "Série", alt.Tooltip("v:Q", title="R$ mi", format=",.2f")]).properties(height=260), width="stretch")
                # por grupo de despesa (orcado x realizado, mes e acumulado no ano); clicar filtra os credores abaixo
                _md("**Por grupo de despesa**")
                gm = {g["codigo"]: g for g in o["grupos"]}
                ga = {g["codigo"]: g for g in (ac["grupos"] if ac else [])}
                linhas_grp = []
                for cod in sorted(gm):
                    g1_, g2_ = gm[cod], ga.get(cod)
                    linhas_grp.append({"Código": cod, "Grupo": ("   " * cod.count(".")) + (g1_["conta"] or cod),
                                       f"Orçado {_rot(mes)}": g1_["orcado"], f"Realizado {_rot(mes)}": g1_["realizado"], f"Desvio {_rot(mes)}": g1_["desvio"],
                                       "Orçado no ano": g2_["orcado"] if g2_ else None, "Realizado no ano": g2_["realizado"] if g2_ else None, "Desvio no ano": g2_["desvio"] if g2_ else None})
                grp = pd.DataFrame(linhas_grp)
                grp_sel = None
                if len(grp):
                    cfg_g = {c: st.column_config.NumberColumn(c, format="localized") for c in grp.columns if c not in ("Código", "Grupo")}
                    _cap("Clique em um grupo para filtrar os credores abaixo (clique de novo para voltar ao total). Desvio = realizado − orçado: positivo é estouro. O orçamento está consolidado das unidades.")
                    ev_g = st.dataframe(grp, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_adm_grp", column_config=cfg_g)
                    grp_sel = _selecionada(ev_g, grp)
                _md("**Contas que mais passaram do orçado**")
                st.dataframe(pd.DataFrame([{"Conta": f"{x['codigo']} · {x['conta']}", "Orçado": _m(x["orcado"]), "Realizado": _m(x["realizado"]), "Desvio": _m(x["desvio"])} for x in o["acima"]]),
                             hide_index=True, width="stretch")
            else:
                grp_sel = None
            linhas_adm = adm.get("linhas") or []
            if linhas_adm:
                filtro_cod = grp_sel["Código"] if grp_sel else None
                _no_grupo = lambda c: (not filtro_cod) or c == filtro_cod or c.startswith(filtro_cod + ".")      # noqa: E731
                df_l = pd.DataFrame(linhas_adm)
                df_l = df_l[df_l["plano_cod"].map(_no_grupo)]
                df_a = pd.DataFrame(adm.get("linhas_ano") or linhas_adm)
                df_a = df_a[df_a["plano_cod"].map(_no_grupo)]
                _md("#### Quem recebeu: unidade → credor → contas" + (f" · grupo {filtro_cod}" if filtro_cod else ""))
                if not len(df_l) and not len(df_a):
                    _info("Nenhum pagamento da administração neste grupo no ano.")
                else:
                    un_mes = df_l.groupby("unidade")["valor"].sum() if len(df_l) else pd.Series(dtype=float)
                    un_ano = df_a.groupby("unidade")["valor"].sum() if len(df_a) else pd.Series(dtype=float)
                    un = pd.DataFrame({"unidade": sorted(set(un_mes.index) | set(un_ano.index))})
                    un["mes"] = un["unidade"].map(lambda u: float(un_mes.get(u, 0.0)))
                    un["ano"] = un["unidade"].map(lambda u: float(un_ano.get(u, 0.0)))
                    un = un.sort_values(["ano", "mes"], ascending=False).reset_index(drop=True)
                    tot_u = float(un["ano"].sum())
                    _cap(f"Pago nas unidades da administração (contas pagas, inclui pessoal). 1) Clique em uma unidade (ou deixe sem seleção para ver todas). 2) Clique em um credor para ver as contas dele. "
                               f"Mês = {_rot(mes)}; ano = jan–{mes[5:]}.")
                    un_m = pd.DataFrame({"Unidade": un["unidade"], _rot(mes): un["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–"), f"Jan–{mes[5:]}": un["ano"].map(_m),
                                         "% do ano": un["ano"].map(lambda x: F.pct_br(x / tot_u) if tot_u else "–")})
                    ev_u = st.dataframe(un_m, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_adm_un")
                    su = _selecionada(ev_u, un)
                    if su:
                        df_l = df_l[df_l["unidade"] == su["unidade"]]
                        df_a = df_a[df_a["unidade"] == su["unidade"]]
                        _md(f"Credores em **{su['unidade']}**")
                    bc = st.text_input("Pesquisar credor", key="dir_adm_busca")
                    c_mes = df_l.groupby("credor")["valor"].sum() if len(df_l) else pd.Series(dtype=float)
                    c_ano = df_a.groupby("credor")["valor"].sum() if len(df_a) else pd.Series(dtype=float)
                    cr = pd.DataFrame({"credor": sorted(set(c_mes.index) | set(c_ano.index))})
                    cr["mes"] = cr["credor"].map(lambda c: float(c_mes.get(c, 0.0)))
                    cr["ano"] = cr["credor"].map(lambda c: float(c_ano.get(c, 0.0)))
                    cr = _busca(cr.sort_values(["ano", "mes"], ascending=False), bc, ["credor"]).reset_index(drop=True)
                    tot_c = float(df_a["valor"].sum())
                    cr_m = pd.DataFrame({"Credor": cr["credor"], _rot(mes): cr["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–"), f"Jan–{mes[5:]}": cr["ano"].map(_m),
                                         "% do filtro": cr["ano"].map(lambda x: F.pct_br(x / tot_c) if tot_c else "–")}).head(60)
                    ev_c = st.dataframe(cr_m, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_adm_cr")
                    sc = _selecionada(ev_c, cr)
                    if sc:
                        ct_a = df_a[df_a["credor"] == sc["credor"]].groupby(["plano_cod", "plano_nome"], as_index=False)["valor"].sum().sort_values("valor", ascending=False)
                        ct_m = df_l[df_l["credor"] == sc["credor"]].groupby("plano_cod")["valor"].sum()
                        _md(f"Contas pagas a **{sc['credor']}**")
                        st.dataframe(pd.DataFrame({"Conta": ct_a["plano_cod"] + " · " + ct_a["plano_nome"].fillna(""), _rot(mes): ct_a["plano_cod"].map(lambda c: _m(ct_m.get(c)) if abs(float(ct_m.get(c, 0.0))) > 0.005 else "–"),
                                                   f"Jan–{mes[5:]}": ct_a["valor"].map(_m)}), hide_index=True, width="stretch")
                    _cap("Conferência: o Realizado do orçamento (tabela de grupos) vem do relatório de Orçamento ADM importado; aqui é o valor efetivamente pago no Sienge (contas pagas). "
                               "Podem diferir por competência × caixa, previsões e reapropriações.")
            _cap("Orçamento ADM consolidado das unidades. O orçado por unidade ainda não vem do banco (só o consolidado); o realizado por unidade vem das contas pagas.")


# ------------------------------------------------------------------ 4) DESPESAS (acumulado do ano, em cascata conta -> credor -> obra)
if aba_desp.open or _TODAS:
    with aba_desp:
        dfp, fora = _pagos_df()
        if not len(dfp):
            _info("Falta sincronizar as contas pagas do ano.")
        else:
            dd = DD.despesas_df(dfp, fora)
            ms = DD.meses_do_ano(mes)
            rots = [m[5:] + "/" + m[2:4] for m in ms]
            tot_ano = float(dd["valor"].sum()) if len(dd) else 0.0
            dm = dd[dd["mes"] == mes]
            tot_mes = float(dm["valor"].sum()) if len(dm) else 0.0
            contas_ano = DD.total_por(dd)
            contas_mes = DD.total_por(dm)
            top5 = sum(x[1] for x in contas_mes[:5])
            top12 = sum(x[1] for x in contas_ano[:12])
            k = st.columns(4)
            k[0].metric(f"Pago em {_rot(mes)}", _mi(tot_mes), "exceto contas de pessoas", delta_color="off", border=True)
            k[1].metric(f"Top 5 de {_rot(mes)}", F.pct_br(top5 / tot_mes) if tot_mes else "–", "do total do mês", delta_color="off", border=True)
            k[2].metric(f"Pago jan–{ms[-1][5:]}", _mi(tot_ano), "exceto contas de pessoas", delta_color="off", border=True)
            k[3].metric(f"Top 12 jan–{ms[-1][5:]}", F.pct_br(top12 / tot_ano) if tot_ano else "–", "do total do período", delta_color="off", border=True)
            e1, e2 = st.columns(2)
            with e1:
                _md(f"**Top 12 contas — acumulado jan–{ms[-1][5:]}**")
                top = contas_ano[:12]
                df_top = pd.DataFrame({"Conta": [x[0] for x in top], "Acumulado": [x[1] for x in top]})
                _cap("Clique em uma conta para detalhar (evolução, credores e obras); clique de novo para voltar ao total.")
                ev_t = st.dataframe(pd.DataFrame({"Conta": df_top["Conta"], "Acumulado": df_top["Acumulado"].map(_mi), "% do período": df_top["Acumulado"].map(lambda x: F.pct_br(x / tot_ano) if tot_ano else "–")}),
                                    hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_desp_top")
                conta_sel = _selecionada(ev_t, df_top)
                conta = conta_sel["Conta"] if conta_sel else None
                _md(f"**Top 5 de {_rot(mes)}**")
                st.dataframe(pd.DataFrame({"Conta": [x[0] for x in contas_mes[:5]], _rot(mes): [_m(x[1]) for x in contas_mes[:5]],
                                           "% do mês": [F.pct_br(x[1] / tot_mes) if tot_mes else "–" for x in contas_mes[:5]]}), hide_index=True, width="stretch")
                _cap("Contas pagas, exceto as contas de pessoas e encargos (aba Pessoas). Conforme as regras da aba “Regras” do Painel EnerMais.")
            with e2:
                _md(f"**Evolução mensal · {conta or 'todas as contas'}**")
                vals = DD.serie_mensal(dd, ms, conta)
                st.altair_chart(_barras_mes(rots, vals, destaque=len(ms) - 1), width="stretch")
                cr = DD.agrupar(dd, "credor", mes, conta=conta)
                _md(f"**Principais credores · {conta or 'todas as contas'}**")
                cr_df = pd.DataFrame({"Credor": [x["chave"] for x in cr["linhas"]], "ac": [x["acumulado"] for x in cr["linhas"]], "mes": [x["mes"] for x in cr["linhas"]]})
                cr_sel = None
                if len(cr_df):
                    ev_cr = st.dataframe(pd.DataFrame({"Credor": cr_df["Credor"], f"Jan–{ms[-1][5:]}": cr_df["ac"].map(_m), "% do filtro": cr_df["ac"].map(lambda x: F.pct_br(x / cr["total"]) if cr["total"] else "–"),
                                                       _rot(mes): cr_df["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–")}),
                                         hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_desp_cr")
                    cr_sel = _selecionada(ev_cr, cr_df)
                    _cap(("Todos os credores da conta." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores") + " Clique em um credor para filtrar as obras abaixo.")
                cred = cr_sel["Credor"] if cr_sel else None
                ob_ = DD.agrupar(dd, "cc", mes, conta=conta, credor=cred)
                _md(f"**Por obra / centro de custo · {cred or conta or 'todas as contas'}**")
                if ob_["linhas"]:
                    st.dataframe(pd.DataFrame({"Obra / centro de custo": [x["chave"] for x in ob_["linhas"]], f"Jan–{ms[-1][5:]}": [_m(x["acumulado"]) for x in ob_["linhas"]],
                                               "%": [F.pct_br(x["acumulado"] / ob_["total"]) if ob_["total"] else "–" for x in ob_["linhas"]],
                                               _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in ob_["linhas"]]}), hide_index=True, width="stretch")
                    _cap("Obra pelo centro de custo do lançamento no pagamento." + ("" if ob_["n"] <= len(ob_["linhas"]) else f" Top {len(ob_['linhas'])} de {ob_['n']}."))


# ------------------------------------------------------------------ 5) PESSOAS
if aba_pes.open or _TODAS:
    with aba_pes:
        dfp, _fora = _pagos_df()
        info = _colaboradores()
        pj = info["pj"]
        clt = info["clt"]
        ms = DD.meses_do_ano(mes)
        n_mes = (clt + pj["total"]) if clt is not None and (pj["total"] or len(dfp)) else None
        hc_hist = list(hist["headcount"]) if hist and hist.get("headcount") else []
        idx = int(mes[5:])
        if n_mes is None and len(hc_hist) >= idx:
            n_mes = hc_hist[idx - 1]
        # headcount mensal: historico do painel (jan..) e, onde falta, o do app (CLT da folha + PJ pago)
        hc_serie = hc_hist[:idx - 1] if len(hc_hist) >= idx - 1 else []
        soma_antes = sum(hc_serie) if len(hc_serie) == idx - 1 and idx > 1 else None
        if not pes and not len(dfp) and not hc_hist:
            _info("Faltam os recibos da folha e as contas pagas deste mês.")
        else:
            rec_ref = rec
            k = st.columns(5)
            if n_mes:
                k[0].metric(f"Colaboradores {_rot(mes)}", f"{int(n_mes):,}".replace(",", "."), (f"{clt} CLT + {pj['total']} PJ" if clt is not None else None), delta_color="off", border=True)
                k[1].metric("Receita por colaborador", _mi(rec_ref / n_mes), border=True)
                k[2].metric("Custo por colaborador", _mi(cus / n_mes), border=True)
                k[3].metric("BDI por colaborador", _mi(bdi / n_mes), border=True)
            if pes:
                t = pes["folha"]["total"]
                k[4].metric(f"Horas extras + DSR {_rot(mes)}", _mi(t["hora_extra"] + t["dsr_he"]), (F.pct_br(t["he_pct"]) + " da remuneração") if t["he_pct"] is not None else None, delta_color="off", border=True)
            c1, c2 = st.columns(2)
            with c1:
                _md("**Colaboradores ativos**")
                serie_hc = list(hc_hist[:idx]) if len(hc_hist) >= idx else (hc_serie + ([n_mes] if n_mes else []))
                if len(serie_hc) >= 1:
                    rots_hc = [m[5:] + "/" + m[2:4] for m in ms[:len(serie_hc)]]
                    st.altair_chart(_barras_mes(rots_hc, serie_hc, titulo_y="colaboradores", destaque=len(serie_hc) - 1, divisor=1, altura=220), width="stretch")
                _cap(f"Colaboradores = CLT pelos recibos da folha + PJ pelos credores de “Salários PJ” pagos no mês" + (f" ({pj['obra']} em obras e {pj['adm']} na administração)." if pj["total"] else "."))
            with c2:
                _md("**Horas extras ÷ remuneração**")
                sf = HIST.serie_he_combinada(hist, pes["serie"] if pes else [])
                if len(sf) >= 2:
                    dfh = pd.DataFrame({"Mês": [_rot(x["mes"]) for x in sf], "%": [round(x["he_pct"] * 100, 1) for x in sf]})
                    st.altair_chart(alt.Chart(dfh).mark_line(point=True, color=ORANGE).encode(x=alt.X("Mês:N", sort=list(dfh["Mês"]), axis=alt.Axis(labelAngle=-45, title=None)), y=alt.Y("%:Q", title="% HE / remuneração"),
                                                                                           tooltip=["Mês", "%"]).properties(height=220), width="stretch")
                    if {x["origem"] for x in sf} == {"historico", "app"}:
                        _cap("Atenção à comparação: os meses do histórico (painel da contabilidade) usam como base proventos menos HE, sem descontar INSS/IRRF etc.; "
                                   "os meses com folha no app usam a remuneração líquida (menos todos os descontos), como a contabilidade pediu em 20/10/2026. Por isso pode haver um degrau entre as duas fontes.")
                elif pes:
                    _cap("A série mensal de HE aparece com 2 ou mais meses de folha (ou com o histórico do painel).")
            # custos prioritarios com pessoas, por colaborador
            if len(dfp):
                pdf_ = DD.pessoas_df(dfp)
                _md("**Custos prioritários com pessoas — por colaborador**")
                tabp = DD.tabela_pessoas(pdf_, mes, n_mes, soma_antes)
                todas = st.radio("Linhas", ["Top 5", "Todas"], horizontal=True, key="dir_pes_linhas", label_visibility="collapsed")
                tabp_v = [x for x in tabp if x["mes"] or x["acum_antes"]] if todas == "Todas" else tabp[:5]
                if tabp_v:
                    tdf = pd.DataFrame(tabp_v)
                    tot_m = sum(x["mes"] for x in tabp)
                    _cap("Clique em uma conta para ver credores e obras; clique de novo para voltar ao total.")
                    ev_p = st.dataframe(pd.DataFrame({"Conta": tdf["conta"], _rot(mes): tdf["mes"].map(_m), "% do mês": tdf["pct_mes"].map(lambda x: F.pct_br(x, 2)),
                                                      "R$/colab. mês": tdf["por_colab_mes"].map(_m), "Acum. até mês anterior": tdf["acum_antes"].map(_m),
                                                      "R$/colab. acum.": tdf["por_colab_acum"].map(_m), "Variação": tdf["variacao"].map(lambda x: F.pct_br(x) if x is not None else "N/A")}),
                                        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_pes_tab")
                    p_sel = _selecionada(ev_p, tdf.rename(columns={"conta": "Conta"}))
                    conta_p = p_sel["Conta"] if p_sel else None
                    _cap(f"Contas de pessoal de obra (2.01.02) e ADM (2.02.01), sem salários CLT/PJ e premiações. Total do mês (todas as contas): {_m(tot_m)}. "
                               "R$/colab. acumulado = acumulado até o mês anterior ÷ soma do headcount mensal desses meses" + ("." if soma_antes else " (indisponível sem o headcount dos meses anteriores)."))
                    d1, d2 = st.columns(2)
                    with d1:
                        cr = DD.agrupar(pdf_, "credor", mes, conta=conta_p)
                        _md(f"**Principais credores · {conta_p or 'todas as contas'}**")
                        cr_df = pd.DataFrame({"Credor": [x["chave"] for x in cr["linhas"]], "ac": [x["acumulado"] for x in cr["linhas"]], "mes": [x["mes"] for x in cr["linhas"]]})
                        cr_sel = None
                        if len(cr_df):
                            ev_cr = st.dataframe(pd.DataFrame({"Credor": cr_df["Credor"], f"Jan–{ms[-1][5:]}": cr_df["ac"].map(_m), "%": cr_df["ac"].map(lambda x: F.pct_br(x / cr["total"]) if cr["total"] else "–"),
                                                               _rot(mes): cr_df["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–")}),
                                                 hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="dir_pes_cr")
                            cr_sel = _selecionada(ev_cr, cr_df)
                            _cap(("Todos os credores." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores.") + " Clique em um credor para filtrar as obras.")
                    with d2:
                        cred_p = cr_sel["Credor"] if cr_sel else None
                        ob_ = DD.agrupar(pdf_, "cc", mes, conta=conta_p, credor=cred_p)
                        _md(f"**Por obra / centro de custo · {cred_p or conta_p or 'todas as contas'}**")
                        if ob_["linhas"]:
                            st.dataframe(pd.DataFrame({"Obra / centro de custo": [x["chave"] for x in ob_["linhas"]], f"Jan–{ms[-1][5:]}": [_m(x["acumulado"]) for x in ob_["linhas"]],
                                                       "%": [F.pct_br(x["acumulado"] / ob_["total"]) if ob_["total"] else "–" for x in ob_["linhas"]],
                                                       _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in ob_["linhas"]]}), hide_index=True, width="stretch")
                            _cap("Obra pelo centro de custo do lançamento.")
            # folha CLT por empresa / obra (recibos) e PJ do mes
            if pes:
                fo = pes["folha"]
                with st.expander("Folha CLT do mês: por empresa e por obra"):
                    st.dataframe(pd.DataFrame([{"Empresa": e["empresa"], "Colab.": e["colab"], "Remuneração": _m(e["base_he"]), "HE + DSR": _m(e["hora_extra"] + e["dsr_he"]),
                                                "HE ÷ remuneração": F.pct_br(e["he_pct"]) if e["he_pct"] is not None else "–", "Custo (proventos + FGTS)": _m(e["custo"])} for e in fo["por_empresa"]]),
                                 hide_index=True, width="stretch")
                    po = sorted(fo["por_obra"].values(), key=lambda x: -x["colab"])
                    st.dataframe(pd.DataFrame([{"Obra": x["codigo"], "Nome": x["nome"], "Colab.": x["colab"], "Remuneração": _m(x["base_he"]), "HE + DSR": _m(x["hora_extra"] + x["dsr_he"]),
                                                "HE ÷ remuneração": F.pct_br(x["he_pct"]) if x["he_pct"] is not None else "–"} for x in po]), hide_index=True, width="stretch")
            if pj["colaboradores"]:
                with st.expander(f"PJ do mês: {pj['total']} colaboradores (fonte: contas pagas “Salários PJ”)"):
                    st.dataframe(pd.DataFrame([{"Colaborador PJ": c["credor"], "Alocado em": c["destino"], "Pago no mês": _m(c["valor"])} for c in pj["colaboradores"]]), hide_index=True, width="stretch")
                    _cap("Regra (contabilidade, 20/10/2026): a fonte do PJ são as contas pagas, sem regras próprias. Cada credor com valor positivo conta 1 colaborador, alocado na obra (ou na administração) "
                               "onde recebeu mais no mês.")
