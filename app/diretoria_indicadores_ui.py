# -*- coding: utf-8 -*-
"""GDF V2 - abas "Indicadores financeiros" e "Financiamentos" do Painel da Diretoria (so' leitura). Calculos em indicadores_dados.py.
Cada resultado fica em cache (30 min) com o 'carimbo' do banco e a DATA de hoje na chave: renova sozinho quando entra carga/upload e quando o dia vira
(a inadimplencia anda com o calendario mesmo sem dado novo)."""
import altair as alt
import pandas as pd
import streamlit as st

import formatacao as F
import fuso
import indicadores_dados as I

NAVY, ORANGE, AZUL, CINZA = "#171C60", "#F99D20", "#5C6091", "#B9C3D4"


def hoje():
    return fuso.agora_br().date()


def _t(txt):                                   # o Streamlit trata $...$ como formula
    return txt.replace("$", "\\$")


def _m(v, vazio="–"):
    return F.moeda_br(v, vazio) if v is not None else vazio


def _mi(v):
    if v is None:
        return "–"
    a = abs(v)
    s = "−" if v < 0 else ""
    fm = lambda x, c: f"{x:,.{c}f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    if a >= 1e6:
        return f"{s}R$ {fm(a / 1e6, 2)} mi"
    if a >= 1e3:
        return f"{s}R$ {fm(a / 1e3, 0)} mil"
    return f"{s}R$ {fm(a, 0)}"


def _dias(v):
    return "–" if v is None else F.num_br(v, 1) + " dias"


def _data(d):
    return d.strftime("%d/%m/%Y") if d else "–"


def _pct(v, casas=1):
    return F.pct_br(v, casas) if v is not None else "–"


def _fmt_num(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", ".")


@st.cache_data(ttl=1800, show_spinner="Calculando os indicadores…")
def _ind(_conn, mes, acumulado, carimbo, dia):
    return I.ciclo_e_capital(_conn, mes, acumulado, dia)


@st.cache_data(ttl=1800, show_spinner=False)
def _inad(_conn, venc_ate, pago_ate, previsao, carimbo):
    return I.inadimplencia(_conn, venc_ate, pago_ate, previsao)


@st.cache_data(ttl=1800, show_spinner=False)
def _receitas(_conn, pago_ate, previsao, carimbo):
    return I.receitas_em_aberto(_conn, pago_ate, previsao)


@st.cache_data(ttl=1800, show_spinner="Calculando os financiamentos…")
def _fin(_conn, dia, previsao, carimbo):
    return I.financiamentos(_conn, dia, previsao)


@st.cache_data(ttl=1800, show_spinner=False)
def _cobertura(_conn, carimbo):
    return I.cobertura_abertos(_conn)


def _aviso_cobertura(conn, carimbo):
    quando = _cobertura(conn, carimbo)
    if quando is None:
        st.warning("A carga semanal de títulos em aberto (por vencimento) ainda não rodou: vencidos anteriores a out/2025 e contratos antigos podem estar incompletos. "
                   "Até lá, os números cobrem os últimos 365 dias da rotina diária.", icon=":material/info:")
    else:
        st.caption(f"Títulos em aberto completos até a última carga semanal: {fuso.fmt_br(quando)}.")


@st.fragment                                    # clicar/filtrar aqui recalcula so' esta aba (nao a pagina inteira)
def aba_indicadores(conn, mes, carimbo):
    dia = hoje()
    c1, c2, c3 = st.columns([1, 1, 1])
    per = c1.radio("Período dos prazos", ["Mês", "Acumulado no ano"], horizontal=True, key="ind_per")
    pos = c2.radio("Posição da inadimplência", ["Até hoje", "Fim do mês escolhido"], horizontal=True, key="ind_pos")
    prev = c3.checkbox("Incluir documentos de previsão", value=False, key="ind_prev", help="Padrão: fora (como combinado com a contabilidade).")
    acum = per != "Mês"
    ind = _ind(conn, mes, acum, carimbo, dia)
    pmr, pmp, g = ind["pmr"], ind["pmp"], ind["gasto"]

    st.markdown("#### Prazo médio e ciclo financeiro")
    k = st.columns(4)
    k[0].metric("PMR simples", _dias(pmr["simples"]), f"{pmr['n']} títulos a receber", delta_color="off", border=True)
    k[1].metric("PMR ponderado", _dias(pmr["ponderado"]), "pelo valor do título", delta_color="off", border=True)
    k[2].metric("PMP simples", _dias(pmp["simples"]), f"{pmp['n']} títulos a pagar", delta_color="off", border=True)
    k[3].metric("PMP ponderado", _dias(pmp["ponderado"]), "pelo valor do título", delta_color="off", border=True)
    k = st.columns(2)
    k[0].metric("Ciclo financeiro · simples (PMR − PMP)", _dias(ind["ciclo_simples"]), "negativo = recebe antes de pagar", delta_color="off", border=True)
    k[1].metric("Ciclo financeiro · ponderado (PMR − PMP)", _dias(ind["ciclo_ponderado"]), "negativo = recebe antes de pagar", delta_color="off", border=True)
    st.caption(_t("Prazo = dias entre a emissão e o vencimento dos títulos EMITIDOS no período, sem documentos de previsão nem títulos desfeitos (cancelados, substituídos, distratos). "
                  "Ponderado = cada título pesa pelo seu valor."))

    st.markdown("#### Capital de giro")
    k = st.columns(4)
    k[0].metric(f"Gasto do mês · {mes[5:]}/{mes[:4]}", _mi(g["mensal"]), f"{g['dias']} dias", delta_color="off", border=True)
    k[1].metric("Gasto diário", _mi(g["diario"]), "gasto do mês ÷ dias", delta_color="off", border=True)
    k[2].metric("Necessidade · ponderado", _mi(ind["ncg_ponderado"]), f"{_m(g['diario'])} × {_dias(ind['ciclo_ponderado'])}" if ind["ciclo_ponderado"] is not None else None, delta_color="off", border=True)
    k[3].metric("Necessidade · simples", _mi(ind["ncg_simples"]), f"{_m(g['diario'])} × {_dias(ind['ciclo_simples'])}" if ind["ciclo_simples"] is not None else None, delta_color="off", border=True)
    st.caption(_t("Gasto = pagamentos feitos no mês (pagamento, adiantamento e pagamento por movimento bancário), sem previsão e sem transferências entre contas. "
                  "Necessidade = gasto diário × ciclo financeiro; só aparece valor quando o ciclo é positivo (paga antes de receber)."))

    st.markdown("#### Inadimplência")
    venc_ate, pago_ate = I.data_posicao(mes, dia, ate_hoje=(pos == "Até hoje"))
    ina = _inad(conn, venc_ate, pago_ate, prev, carimbo)
    k = st.columns(2)
    k[0].metric("Vencido a receber", _mi(ina["receber"]["total"]), f"{ina['receber']['n']} títulos", delta_color="off", border=True)
    k[1].metric("Vencido a pagar", _mi(ina["pagar"]["total"]), f"{ina['pagar']['n']} títulos", delta_color="off", border=True)
    st.caption(f"Posição: vencidos até {_data(venc_ate)} e não pagos até {_data(pago_ate)}. "
               + ("Vencimento ORIGINAL (o primeiro vencimento registrado; prorrogação não esconde a dívida)." if ina["usa_vencimento_original"] else "Vencimento atual do título (o vencimento original ainda não foi ativado no banco)."))
    d1, d2 = st.columns(2)
    for col, chave, rot, quem in ((d1, "receber", "a receber", "Cliente"), (d2, "pagar", "a pagar", "Credor")):
        with col:
            st.markdown(f"**Por faixa de atraso · {rot}**")
            st.dataframe(pd.DataFrame([{"Faixa": f["faixa"], "Títulos": f["n"], "Valor": f["valor"]} for f in ina[chave]["faixas"]]).style.format({"Valor": _fmt_num}),
                         hide_index=True, width="stretch")
            if ina[chave]["top"]:
                st.markdown(f"**Maiores · {rot}**")
                st.dataframe(pd.DataFrame([{quem: x["nome"], "Títulos": x["n"], "Vencido há mais tempo": x["mais_antigo"], "Valor": x["valor"]} for x in ina[chave]["top"]])
                             .style.format({"Valor": _fmt_num, "Vencido há mais tempo": lambda d: _data(d)}), hide_index=True, width="stretch")

    st.markdown("#### Receitas em aberto")
    rec = _receitas(conn, pago_ate, prev, carimbo)
    if not rec:
        st.info("Nenhuma conta a receber em aberto na posição escolhida.")
    else:
        df = pd.DataFrame(rec).rename(columns={"cliente": "Cliente", "nota": "Nota", "vencimento": "Vencimento", "valor": "Em aberto", "atraso": "Dias de atraso"})
        busca = st.text_input("Pesquisar cliente ou nota", key="ind_rec_busca")
        if busca.strip():
            t = busca.strip().lower()
            df = df[df["Cliente"].str.lower().str.contains(t, regex=False) | df["Nota"].astype(str).str.lower().str.contains(t, regex=False)]
        st.dataframe(df.style.format({"Em aberto": _fmt_num, "Vencimento": lambda d: _data(d)}), hide_index=True, width="stretch")
        st.caption(_t(f"{len(df)} contas · total em aberto {_m(float(df['Em aberto'].sum()))}. Clique no cabeçalho para ordenar."))
    _aviso_cobertura(conn, carimbo)


@st.fragment                                    # clicar numa linha do credor atualiza so' esta aba
def aba_financiamentos(conn, carimbo):
    dia = hoje()
    prev = st.checkbox("Incluir documentos de previsão", value=False, key="fin_prev", help="Padrão: fora.")
    f = _fin(conn, dia, prev, carimbo)
    k = st.columns(6)
    k[0].metric("Saldo devedor", _mi(f["saldo_devedor"]), "capital de giro + financiamentos (2.03.04 + 2.05)", delta_color="off", border=True)
    k[1].metric("Juros a pagar", _mi(f["juros_totais"]), "2.03.02", delta_color="off", border=True)
    k[2].metric("Desembolso restante", _mi(f["desembolso_total"]), "principal + juros", delta_color="off", border=True)
    k[3].metric("Contratos ativos", f"{f['contratos']}", f"{f['documentos']} documentos lançados", delta_color="off", border=True)
    k[4].metric("Custo médio", _pct(f["custo_medio"]), f["custo_medio_origem"], delta_color="off", border=True)
    k[5].metric("Encerramento mais longo", f["encerramento_mais_longo"].strftime("%m/%Y") if f["encerramento_mais_longo"] else "–", "última parcela em aberto", delta_color="off", border=True)
    st.caption(_t(f"Posição em {_data(dia)}: parcelas ainda não pagas dos planos 2.03.02 (juros), 2.03.04 (capital de giro bancário) e 2.05 (financiamentos e imobilizado). "
                  "Contrato = número “Ct/Contrato” do nome do plano."))
    if not f["por_contrato"]:
        st.info("Nenhum financiamento em aberto na posição.")
        _aviso_cobertura(conn, carimbo)
        return

    cur = pd.DataFrame(f["curva"])
    if len(cur):
        st.markdown("**Curva de endividamento — desembolso por mês de vencimento**")
        long = pd.concat([pd.DataFrame({"Mês": cur["mes"], "Parte": "Principal", "R$ mil": cur["principal"] / 1e3}),
                          pd.DataFrame({"Mês": cur["mes"], "Parte": "Juros", "R$ mil": cur["juros"] / 1e3})])
        st.altair_chart(alt.Chart(long).mark_bar().encode(
            x=alt.X("Mês:N", sort=list(cur["mes"]), axis=alt.Axis(labelAngle=-45, title=None)), y=alt.Y("R$ mil:Q", title="R$ mil"),
            color=alt.Color("Parte:N", scale=alt.Scale(domain=["Principal", "Juros"], range=[NAVY, ORANGE]), legend=alt.Legend(orient="top", title=None)),
            tooltip=["Mês", "Parte", alt.Tooltip("R$ mil:Q", format=",.1f")]).properties(height=260), width="stretch")

    cat = {}
    for c in f["por_contrato"]:
        a = cat.setdefault(c["categoria"], {"Categoria": c["categoria"], "Contratos": 0, "Principal": 0.0, "Juros": 0.0})
        a["Contratos"] += 1
        a["Principal"] += c["principal"]
        a["Juros"] += c["juros"]
    st.markdown("**O que está financiado**")
    st.dataframe(pd.DataFrame(sorted(cat.values(), key=lambda x: -x["Principal"])).style.format({"Principal": _fmt_num, "Juros": _fmt_num}), hide_index=True, width="stretch")

    st.markdown("**Por credor (banco / financiadora)** — clique para filtrar os contratos")
    cr = pd.DataFrame([{"Credor": x["credor"], "Contratos": x["contratos"], "Principal": x["principal"], "Juros": x["juros"], "% da carteira": x["pct_carteira"],
                        "Taxa mensal": x["taxa_mensal"], "Encerramento": x["encerramento"]} for x in f["por_credor"]])
    ev = st.dataframe(cr.style.format({"Principal": _fmt_num, "Juros": _fmt_num, "% da carteira": lambda v: _pct(v), "Taxa mensal": lambda v: _pct(v, 2),
                                       "Encerramento": lambda d: d.strftime("%m/%Y") if d else "–"}, na_rep="–"),
                      hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="fin_cr")
    try:
        sel = cr.iloc[ev.selection.rows[0]]["Credor"] if ev.selection.rows else None
    except Exception:
        sel = None
    st.caption("Taxa mensal = taxa cadastrada do contrato (Importações → Financiamentos); sem cadastro, usa a aproximação implícita (juros a pagar ÷ saldo de cada parcela × meses até vencer). Credor = média ponderada pelo saldo.")

    ct = pd.DataFrame([{"Credor": c["credor"], "Categoria": c["categoria"], "Objeto": c["objeto"], "Origem": c["origem"], "Contrato": c["chave"], "Parcelas": c["parcelas"], "Principal": c["principal"],
                        "Juros": c["juros"], "Próximo vencimento": c["proximo"], "Encerramento": c["encerramento"], "Taxa mensal": c["taxa_mensal"], "Taxa": c["taxa_origem"]} for c in f["por_contrato"]])
    if sel:
        ct = ct[ct["Credor"] == sel]
    st.markdown(f"**Contratos{' · ' + sel if sel else ''}**")
    st.dataframe(ct.style.format({"Principal": _fmt_num, "Juros": _fmt_num, "Próximo vencimento": lambda d: _data(d), "Encerramento": lambda d: d.strftime("%m/%Y") if d else "–",
                                  "Taxa mensal": lambda v: _pct(v, 2)}, na_rep="–"), hide_index=True, width="stretch")
    st.caption("Origem “Sugestão” = classificação automática pelo plano de contas e pelo nome do lançamento; “Cadastro” = definida por uma pessoa no Painel EnerMais (Importações → Financiamentos).")
    _aviso_cobertura(conn, carimbo)
