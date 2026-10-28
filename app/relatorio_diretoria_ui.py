# -*- coding: utf-8 -*-
"""GDF V2 - tela do GERADOR DE RELATORIO do Painel da Diretoria (v0.54.0). Um quadro "Gerar relatório em PDF" logo acima das abas.

Como usar (linguagem simples): escolhe um modelo pronto (Completo, Só PJ, Só CLT...) ou marca a mao cada informacao de cada aba; opcionalmente restringe a
obras especificas, a empresa que pagou e a situacao (PJ); clica em "Gerar" e baixa o PDF. Periodo = o do topo do painel. Nada e' gravado: o PDF fica so' na
memoria desta sessao."""
from __future__ import annotations

import streamlit as st

import folha_pj_dados as FP
import relatorio_diretoria as RD
import relatorio_diretoria_dados as RDD

_P = "rel_k_"                                           # chave das caixinhas de cada informacao
_A = "rel_a_"                                           # chave da caixinha "marcar a aba toda"
_O = "rel_o_"                                           # chave da caixa de observacao de cada aba


@st.cache_data(ttl=1800, show_spinner=False)
def _obras_opcoes(_conn, mes_ini: str, mes: str, carimbo: str) -> list:
    return RDD.opcoes_obras(_conn, mes_ini, mes)


def _aplicar_modelo() -> None:
    """Ao trocar o modelo, marca exatamente as informacoes dele (Personalizado nao mexe em nada)."""
    nome = st.session_state.get("rel_modelo")
    if nome in RDD.MODELOS:
        ligadas = set(RDD.MODELOS[nome])
        for k in RDD.TODAS_CHAVES:
            st.session_state[_P + k] = k in ligadas
        for a, _rot, itens in RDD.CATALOGO:
            st.session_state[_A + a] = all(k in ligadas for k, *_ in itens)


def _marcou_a_mao() -> None:
    st.session_state["rel_modelo"] = RDD.PERSONALIZADO


def _marcar_aba(aba: str) -> None:
    ligar = bool(st.session_state.get(_A + aba))
    for k, *_ in RDD.ABAS[aba][1]:
        st.session_state[_P + k] = ligar
    st.session_state["rel_modelo"] = RDD.PERSONALIZADO


def _sincroniza_aba(aba: str) -> None:
    st.session_state["rel_modelo"] = RDD.PERSONALIZADO
    st.session_state[_A + aba] = all(st.session_state.get(_P + k, False) for k, *_ in RDD.ABAS[aba][1])


def _assinatura(blocos: list, obras: list, empresas: list, situacoes: list, mes_ini: str, mes: str, modo: str, obs: dict | None = None) -> tuple:
    return (tuple(blocos), tuple(obras), tuple(empresas), tuple(situacoes), mes_ini, mes, modo, tuple(sorted((obs or {}).items())))


def _nome_arquivo(mes: str, obras: list) -> str:
    base = f"relatorio_painel_diretoria_{mes}"
    if obras:
        base += "_obras-" + "-".join(str(o) for o in obras[:4]) + ("-etc" if len(obras) > 4 else "")
    return base + ".pdf"


def secao_relatorio(conn, mes_ini: str, mes: str, modo_per: str, ctx: dict, mostra_inv: bool, usuario, carimbo: str, eh_editor: bool = False) -> None:
    """Quadro recolhido 'Gerar relatório em PDF' (fica acima das abas do painel). So' para o EDITOR: o visualizador (diretoria) so' ve os paineis."""
    if not eh_editor:
        return
    S = st.session_state
    for k in RDD.TODAS_CHAVES:                                     # primeira vez: o padrao (completo, sem as listas longas)
        S.setdefault(_P + k, k in RDD.PADRAO)
    for a, _rot, itens in RDD.CATALOGO:
        S.setdefault(_A + a, all(S.get(_P + k, False) for k, *_ in itens))
    S.setdefault("rel_modelo", "Completo")
    abas = [(a, rot, itens) for a, rot, itens in RDD.CATALOGO if mostra_inv or a != "inv"]
    with st.expander("Gerar relatório em PDF (escolha o que entra)", expanded=False):
        st.caption("PDF no layout Enermais, com todas as abas que você marcar. O período é o do topo do painel; abaixo você pode restringir a obras específicas, "
                   "à empresa que pagou ou à situação (Folha PJ). Nada fica salvo: o arquivo só existe nesta sessão.")
        st.radio("Modelo", [*RDD.MODELOS.keys(), RDD.PERSONALIZADO], horizontal=True, key="rel_modelo", on_change=_aplicar_modelo,
                 help="Modelos já marcam as caixinhas certas; depois você ainda pode ligar ou desligar qualquer informação (vira Personalizado).")
        try:
            opc = _obras_opcoes(conn, mes_ini, mes, carimbo)
        except Exception:                                          # noqa: BLE001
            opc = []
        rot_obra = dict(opc)
        f1, f2, f3 = st.columns([1.6, 1, 1])
        obras = f1.multiselect("Obras (vazio = geral)", [c for c, _ in opc], format_func=lambda c: rot_obra.get(c, c), key="rel_obras",
                               help="Vale para as informações que têm filtro por obra nas abas Obras, Despesas, Pessoas, Folha PJ e Folha CLT. Resultado, Administração, Indicadores e Financiamentos são do grupo todo.")
        empresas = f2.multiselect("Empresa que pagou (PJ)", list(FP.EMPRESAS.values()), format_func=FP.nome_empresa_curto, key="rel_empresas", help="Só afeta a Folha PJ.")
        situacoes = f3.multiselect("Situação (PJ)", list(FP.SITUACOES), key="rel_situacoes", help="Só afeta a Folha PJ.")
        st.markdown("**O que entra, aba por aba**")
        cols = st.columns(3)
        for i, (a, rot, itens) in enumerate(abas):
            with cols[i % 3].container(border=True):
                st.checkbox(f"{rot} (aba toda)", key=_A + a, on_change=_marcar_aba, args=(a,))
                for k, rotulo, _padrao, segue_obra, _t in itens:
                    st.checkbox(rotulo, key=_P + k, on_change=_sincroniza_aba, args=(a,),
                                help=("Segue o filtro de obras." if segue_obra else "Do grupo todo (não muda com o filtro de obras)."))
                st.text_area(f"Observação no rodapé de {rot} (opcional)", key=_O + a, height=84, max_chars=RDD.OBS_MAX, placeholder="Vazio = nada é impresso.",
                             help="Texto livre que entra numa caixa “Observação” no fim desta aba do PDF. Só aparece se a aba tiver alguma informação marcada. Fica só nesta sessão.")
        blocos = [k for a, _r, itens in abas for k, *_ in itens if S.get(_P + k)]
        com_blocos = {a for a, _r, itens in abas if any(S.get(_P + k) for k, *_ in itens)}
        obs = {a: str(S.get(_O + a) or "").strip() for a, *_ in abas if a in com_blocos and str(S.get(_O + a) or "").strip()}
        sig = _assinatura(blocos, obras, empresas, situacoes, mes_ini, mes, modo_per, obs)
        c1, c2 = st.columns([1, 2], vertical_alignment="center")
        gerar = c1.button("Gerar relatório", key="rel_gerar", type="primary", disabled=not blocos)
        c2.caption(f"{len(blocos)} informação(ões) marcada(s) · período {mes_ini[5:]}/{mes_ini[:4]} a {mes[5:]}/{mes[:4]} · " + (f"{len(obras)} obra(s)" if obras else "todas as obras"))
        if gerar:
            with st.spinner("Montando o relatório…"):
                dados = RDD.montar(conn, mes_ini, mes, blocos, modo_per, {"obras": obras, "empresas": empresas, "situacoes": situacoes}, ctx, str(usuario or ""), mostra_inv, observacoes=obs)
                S["rel_pdf"] = {"bytes": RD.gerar_pdf(dados), "sig": sig, "nome": _nome_arquivo(mes, obras), "n": dados["meta"]["n_blocos"]}
        pdf = S.get("rel_pdf")
        if pdf and pdf["sig"] == sig:
            st.success(f"Relatório pronto: {pdf['n']} informação(ões).")
            st.download_button("Baixar o PDF", pdf["bytes"], pdf["nome"], "application/pdf", key="rel_baixar")
        elif pdf:
            st.info("O que está marcado mudou desde o último relatório. Clique em “Gerar relatório” de novo para atualizar o PDF.")
