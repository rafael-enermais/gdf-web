# -*- coding: utf-8 -*-
"""GDF V2 - tela da aba "Folha PJ" do Painel da Diretoria (so' leitura) e a secao de cargas (mapa de colaboradores, Flash, diretoria) das Importacoes V2.
Os calculos estao em folha_pj_dados.py (funcoes puras, testadas); aqui so' o desenho.

Ordem do painel (tudo reage em cascata): cards por empresa -> obras com maior custo -> filtros (chips) -> resumo por obra e centro de custo
-> colaboradores -> documentos lancados. Marcar uma linha numa tabela filtra a de baixo; "Limpar filtros" volta ao total."""
from __future__ import annotations

import datetime as dt
import hashlib
import zlib

import pandas as pd
import streamlit as st

import folha_pj_dados as FP
import formatacao as F
import importador_folha_pj as IP


# ------------------------------------------------------------------ pequenos formatadores
def _t(txt):                                       # o Streamlit trata $...$ como formula
    return txt.replace("$", "\\$") if isinstance(txt, str) else txt


def _m(v, vazio="–"):
    return F.moeda_br(v, vazio) if v is not None else vazio


def _mz(v):
    """Valor em R$; zero vira traco (tabelas largas ficam legiveis)."""
    return "–" if v is None or abs(v) < 0.005 else F.moeda_br(v)


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


def _chave(base: str, *dep) -> str:
    """Chave de um st.dataframe com selecao que muda quando muda o que o alimenta (a selecao por posicao nao fica 'grudada' em outra linha)."""
    return f"{base}_{zlib.crc32(repr(dep).encode()) % 100000}"


def _marcadas(ev, itens: list) -> list:
    """Itens (da lista que alimentou o st.dataframe) cujas caixinhas estao marcadas."""
    try:
        rows = [r for r in ev.selection.rows if r < len(itens)]
    except Exception:                              # noqa: BLE001
        rows = []
    return [itens[r] for r in rows]


def _cap(txt):
    st.caption(_t(txt))


def _md(txt):
    st.markdown(_t(txt))


def _tem_chip(opcao, marcadas) -> bool:
    return opcao in (marcadas or [])


# ------------------------------------------------------------------ dados (cache de 30 min, renovado pelo carimbo do banco)
@st.cache_data(ttl=1800, show_spinner="Lendo a folha PJ…")
def _dados(_conn, mes: str, carimbo: str) -> dict:
    return FP.dados_do_mes(_conn, mes)


def _ap(apr: list) -> str:
    return "; ".join(f"{a['centro']} ({a['pct']:g}%)" for a in apr)


def _limpar():
    """Volta todos os filtros e marcacoes ao inicio: troca o sufixo das chaves dos widgets (tabelas e chips nascem novos)."""
    st.session_state["fpj_rst"] = int(st.session_state.get("fpj_rst", 0)) + 1


def _definir(chave, valor):
    st.session_state[chave] = valor


# ------------------------------------------------------------------ aba
def aba_folha_pj(conn, mes: str, carimbo: str, rotulo_mes: str) -> None:
    d = _dados(conn, mes, carimbo)
    if not d["instalado"]:
        st.info("Falta executar o arquivo `sql/v2_folha_pj.sql` (SQL-40) no Supabase. Sem ele o painel já mostra os valores do Sienge, mas ainda não tem Flash, "
                "mapa de colaboradores, diretoria nem o desconto dos títulos em aberto.")
    if not d["pessoas"]:
        st.info(f"Não há contas PJ (Salários PJ, Premiações ou Multas Contratuais) pagas ou a pagar em {rotulo_mes}.")
        return
    rst = int(st.session_state.get("fpj_rst", 0))
    k = lambda nome: f"fpj_{nome}_{rst}"                                                   # noqa: E731
    pessoas, tot = d["pessoas"], d["totais"]
    faltas = [txt for cond, txt in ((d["sem_flash"], "Flash do mês"), (d["sem_mapa"], "mapa de colaboradores (função, centro de origem, novos)"),
                                    (d["sem_diretoria"], "credores da diretoria")) if cond and d["instalado"]]
    if faltas:
        _cap("Ainda não carregado: " + ", ".join(faltas) + ". Envie em Importações V2 > Folha PJ; até lá esses itens aparecem vazios (o custo vem só do Sienge).")

    # ---- cards por empresa (quem pagou); o valor da diretoria soma na empresa
    _md(f"**Custo PJ · {rotulo_mes}** (honorários + premiações + multa + ajuda de custo + vale alimentação − descontos)")
    itens = [("Total PJ", tot["custo_total"], f"{tot['n']} colaboradores", tot)] + \
            [(FP.nome_empresa_curto(c["empresa"]), c["total"]["custo_total"], f"{c['n']} colab. · diretoria {_mi(c['diretoria']['custo_total'])}", c["total"]) for c in d["cards"]]
    for i in range(0, len(itens), 4):
        cols = st.columns(4)
        for col, (nome, v, sub, t) in zip(cols, itens[i:i + 4]):
            col.metric(nome, _mi(v), sub, delta_color="off", border=True)
            col.caption(_t(f"Pago {_mi(t['pago'])} · a pagar {_mi(t['a_pagar'])}"))
    kk = st.columns(7)
    for col, (rot, v) in zip(kk, (("Honorários", tot["honorarios"]), ("Premiações", tot["premiacao"]), ("Ajuda de custo (Flash)", tot["ajuda_custo"]), ("Vale alimentação (Flash)", tot["alimentacao"]),
                                  ("Multa contratual", tot["multa"]), ("Descontos", tot["desconto"]), ("Documentos", None))):
        col.metric(rot, _mi(v) if v is not None else f"{tot['n_docs']:,}".replace(",", "."), border=True)

    # ---- obras com maior custo (sem diretoria)
    obras_nomes = [o["obra"] for o in d["obras"]]
    if d["top_obras"]:
        _md("**Obras com maior custo PJ** (sem a diretoria; o botão filtra as tabelas abaixo)")
        cs = st.columns(len(d["top_obras"]))
        for col, o in zip(cs, d["top_obras"]):
            col.metric(o["obra"][:42], _mi(o["custo_total"]), f"{o['n']} colaboradores", delta_color="off", border=True)
            col.button("Filtrar esta obra", key=k("top_" + o["obra"]), on_click=_definir, args=(k("obras"), [o["obra"]]), width="stretch")

    # ---- filtros (chips)
    st.divider()
    cf = st.columns([3, 3, 1])
    busca = cf[0].text_input("Pesquisar colaborador (nome ou função)", key=k("busca"))
    obras_f = cf[1].multiselect("Obra", obras_nomes, key=k("obras"), placeholder="Todas as obras")
    cf[2].button("Limpar filtros", key=k("limpar"), on_click=_limpar, width="stretch")
    emp_opts = sorted({p["empresa"] for p in pessoas if p["empresa"]})
    emp_f = st.pills("Empresa que pagou", emp_opts, selection_mode="multi", key=k("emp"), format_func=FP.nome_empresa_curto)
    sit_f = st.pills("Situação", list(FP.SITUACOES), selection_mode="multi", key=k("sit"))
    pes = FP.filtrar(pessoas, obras=obras_f, empresas=emp_f, situacoes=sit_f, busca=busca)
    if not pes:
        st.info("Nenhum colaborador com esses filtros.")
        return

    # ---- resumo por obra (nivel 1) e centro de custo (nivel 2)
    obras = FP.resumo_obras(pes)
    _md("**Resumo por obra e centro de custo**")
    cols_sel = st.pills("Colunas", ["Honorários", "Premiações", "Benefícios Flash"], selection_mode="multi", default=["Honorários", "Premiações", "Benefícios Flash"], key=k("cols"),
                        label_visibility="collapsed")

    def _linha(nome_col, nome, x, extra=None):
        r = {nome_col: nome, "Colab.": x["n"]}
        if _tem_chip("Honorários", cols_sel):
            r["Honorários"] = _mz(x["honorarios"])
        if _tem_chip("Premiações", cols_sel):
            r["Premiações"] = _mz(x["premiacao"])
        if _tem_chip("Benefícios Flash", cols_sel):
            r["Benefícios Flash"] = _mz(x["ajuda_custo"] + x["alimentacao"])
        r.update({"Multa": _mz(x["multa"]), "Descontos": _mz(x["desconto"]), "Custo total": _m(x["custo_total"]), "Pago": _mz(x["pago"]), "A pagar": _mz(x["a_pagar"])})
        return {**(extra or {}), **r}

    st.caption("Marque a caixinha de uma ou mais obras para abrir os centros de custo delas e filtrar os colaboradores; marque centros para afinar. "
               "Os botões de colunas escondem Honorários, Premiações ou Benefícios Flash (o Custo total continua completo).")
    ev_o = st.dataframe(pd.DataFrame([_linha("Obra / grupo", o["obra"], o) for o in obras]), hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                        key=_chave(k("t_obras"), mes, tuple(obras_f), tuple(emp_f or ()), tuple(sit_f or ()), busca, tuple(cols_sel or ())))
    marc_o = [o["obra"] for o in _marcadas(ev_o, obras)]
    abrir_todas = st.toggle("Abrir os centros de custo de todas as obras", key=k("abrir"))
    centros_sel = []
    if marc_o or abrir_todas:
        linhas_c = [{"obra": o["obra"], **c} for o in obras if abrir_todas or o["obra"] in marc_o for c in o["centros"]]
        ev_c = st.dataframe(pd.DataFrame([_linha("Centro de custo", c["centro"], c, {"Obra": c["obra"]}) for c in linhas_c]), hide_index=True, width="stretch", on_select="rerun",
                            selection_mode="multi-row", key=_chave(k("t_centros"), mes, tuple(marc_o), abrir_todas, tuple(obras_f), tuple(emp_f or ()), tuple(sit_f or ()), busca, tuple(cols_sel or ())))
        centros_sel = [c["centro"] for c in _marcadas(ev_c, linhas_c)]
    pes2 = FP.filtrar(pes, obras=marc_o, centros=centros_sel)

    # ---- colaboradores
    _md("**Colaboradores**")
    lista = FP.agrupar_diretoria(pes2)
    ev_p = st.dataframe(pd.DataFrame([{"Colaborador": p["nome"] + (" · novo" if p["novo"] else ""), "Função": p["funcao"], "Empresa": FP.nome_empresa_curto(p["empresa"]) if p["empresa"] else "–",
                                       "Centro de custo": p["centro"], "Honorários": _mz(p["honorarios"]), "Premiações": _mz(p["premiacao"]), "Ajuda de custo": _mz(p["ajuda_custo"]),
                                       "Vale alimentação": _mz(p["alimentacao"]), "Multa": _mz(p["multa"]), "Descontos": _mz(p["desconto"]), "Custo total": _m(p["custo_total"]),
                                       "Pago": _mz(p["pago"]), "A pagar": _mz(p["a_pagar"]), "Situação": p["situacao"]} for p in lista]),
                        hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                        key=_chave(k("t_pessoas"), mes, tuple(marc_o), tuple(centros_sel), tuple(obras_f), tuple(emp_f or ()), tuple(sit_f or ()), busca))
    sel_p = _marcadas(ev_p, lista)
    base = sel_p or lista
    tt = FP.somar([p for p in base])
    _cap(("Marcados" if sel_p else "Total da lista") + f": {len(base)} linhas · custo total {_m(tt['custo_total'])} · pago {_m(tt['pago'])} · a pagar {_m(tt['a_pagar'])}. "
         "“novo” = entrou na folha neste mês. A diretoria aparece numa linha só (“Demais credores - diretoria”), sempre por último.")

    # ---- documentos lancados
    _md("**Documentos lançados**")
    sit_d = st.pills("Documentos", ["Pago", "A pagar"], selection_mode="multi", key=k("sit_doc"), label_visibility="collapsed")
    docs = FP.filtrar_documentos(d["documentos"], base, situacoes=sit_d) if base else []
    if docs:
        st.dataframe(pd.DataFrame([{"Situação": x["situacao"], "Data": x["data"].strftime("%d/%m/%Y") if x["data"] else "–", "Documento": x["documento"], "Lançamento": x["lancamento"],
                                    "Colaborador": x["nome"], "Empresa": FP.nome_empresa_curto(x["empresa"]), "Conta": f"{x['plano']} {x['plano_nome']}".strip(),
                                    "Valor bruto": _m(x["bruto"]), "Desconto": _mz(x["desconto"]), "Valor líquido": _m(x["valor_liquido"]), "Apropriação": _ap(x["apropriacao"]),
                                    "Observação": (f"substitui {x['substitui']}" if x.get("substitui") else "")} for x in docs]), hide_index=True, width="stretch")
        _cap(f"{len(docs)} documentos · líquido {_m(sum(x['valor_liquido'] for x in docs))}. Um documento por linha; a apropriação mostra os centros de custo do Sienge e o percentual de cada um. "
             "Se o documento tem mais de uma conta (honorários e premiação, por exemplo), cada conta é uma linha.")
    else:
        _cap("Nenhum documento para a seleção.")
    if d["fora"]:
        with st.expander(f"Lançamentos que não contam ({len(d['fora'])}): substituições e abatimentos de adiantamento"):
            st.dataframe(pd.DataFrame([{"Lançamento": f["lancamento"], "Documento": f["documento"], "Valor": _m(f["valor"]), "Motivo": f["motivo"]} for f in d["fora"]]), hide_index=True, width="stretch")
            _cap("Títulos substitutos não entram no custo: o Sienge registra a troca (adiantamento/proforma pela nota) como outra baixa e contaria duas vezes.")
    _cap("Fonte: Sienge (contas Salários PJ, Premiações e Multas Contratuais PJ, de obra e administração), pago no mês e a pagar com vencimento até o fim do mês. "
         "Flash e mapa de colaboradores vêm das planilhas enviadas em Importações V2. Pago e a pagar são líquidos de desconto.")


# ------------------------------------------------------------------ cargas (Importacoes V2, so' editor)
def segredo() -> str:
    """Segredo do hash de CPF: PJ_CPF_SEGREDO nos Secrets do app (recomendado: fixo). Sem ele, deriva do DATABASE_URL (muda se a senha do banco mudar -> cruza so' pelo nome)."""
    try:
        s = st.secrets.get("PJ_CPF_SEGREDO") if hasattr(st.secrets, "get") else None
        if s:
            return str(s)
        base = st.secrets["DATABASE_URL"]
    except Exception:                              # noqa: BLE001
        return ""
    return hashlib.sha256(("gdf-pj|" + str(base)).encode()).hexdigest()


def _meses_opcoes() -> list:
    hoje = dt.date.today().replace(day=1)
    out = []
    for i in range(0, 14):
        m = hoje.month - i
        a = hoje.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        out.append(f"{a}-{m:02d}")
    return out


def upload_secao(conn, usuario) -> None:
    """Secao 'Folha PJ' das Importacoes V2: mapa de colaboradores, Flash e credores da diretoria. Nada e' apagado: reenviar troca/atualiza."""
    ok = FP.instalado(conn)
    with st.expander("Folha PJ: mapa de colaboradores, Flash e diretoria", expanded=False):
        if not ok:
            st.warning("Falta executar o arquivo `sql/v2_folha_pj.sql` (SQL-40) no Supabase para o app guardar estes cadastros. Você já pode ler os arquivos; só não dá para salvar.")
        seg = segredo()
        if not seg:
            st.caption("Sem segredo configurado: o CPF não será usado e o Flash cruza só pelo nome. (O CPF nunca é gravado; só um código irreversível dele, e só com o segredo.)")
        st.markdown("**1) Mapa de colaboradores PJ** (planilha da folha, aba do mês, ou o arquivo “Novos colaboradores PJ”)")
        _cap("O app acha as colunas pelo nome (NOME, CPF, CÓD. CREDOR SIENGE, FUNÇÃO, CENTRO DE CUSTO, EMPRESA, VÍNCULO). Só entram as linhas PJ com código de credor. Planilha com senha não abre: envie uma cópia sem senha.")
        arq = st.file_uploader("Planilha (xlsx)", type=["xlsx"], key="fpj_up_mapa")
        if arq is not None:
            b = arq.getvalue()
            try:
                nomes = IP.abas(b)
                aba = st.selectbox("Aba", nomes, index=nomes.index(IP.aba_padrao(nomes)), key="fpj_aba")
                lido = IP.ler_mapa_colaboradores(b, seg, aba)
                st.success(f"{len(lido['linhas'])} colaboradores PJ lidos da aba “{lido['aba']}”.")
                for av in lido["avisos"]:
                    st.caption(av)
                mes_n = st.selectbox("Mês do arquivo", _meses_opcoes(), key="fpj_mes_mapa")
                novos = st.checkbox("É o arquivo “Novos colaboradores PJ” (marcar como novos neste mês)", key="fpj_novos")
                if st.button("Salvar o mapa de colaboradores", type="primary", disabled=not ok, key="fpj_salvar_mapa"):
                    r = IP.gravar_colaboradores(conn, lido["linhas"], mes_n, usuario, novos=novos)
                    st.toast(f"Mapa salvo: {r['novos']} novos e {r['atualizados']} atualizados.", icon="✅")
                    st.rerun()
            except IP.ErroFolhaPJ as exc:
                st.error(str(exc))
        st.divider()
        st.markdown("**2) Flash** (um arquivo por empresa e mês)")
        _cap("Premiação no cartão entra como ajuda de custo; refeição/alimentação, como vale alimentação. Cruza com os colaboradores pelo CPF e, sem CPF, pelo nome.")
        c1, c2 = st.columns(2)
        mes_f = c1.selectbox("Mês do Flash", _meses_opcoes(), key="fpj_mes_flash")
        emp_f = c2.selectbox("Empresa do arquivo", list(FP.EMPRESAS.values()), key="fpj_emp_flash")
        arq_f = st.file_uploader("Arquivo do Flash (xlsx)", type=["xlsx"], key="fpj_up_flash")
        if arq_f is not None:
            try:
                fl = IP.ler_flash(arq_f.getvalue(), seg)
                cruz = IP.cruzar_flash(fl["linhas"], IP.colaboradores_cadastrados(conn), IP.fantasias_dos(conn, [c for c in IP.colaboradores_cadastrados(conn)]))
                st.success(f"{len(fl['linhas'])} pessoas no arquivo · premiação no cartão {_m(fl['total_premiacao'])} · refeição/alimentação {_m(fl['total_alimentacao'])}.")
                st.caption(_t(f"Casaram com um colaborador PJ: {len(cruz['casadas'])} · sem PJ correspondente (CLT, outra empresa ou fora do mapa): {cruz['sem_pj']} · nome repetido (não casou): {cruz['ambiguas']}."))
                for av in fl["avisos"]:
                    st.warning(av)
                if not IP.colaboradores_cadastrados(conn):
                    st.warning("O mapa de colaboradores ainda não foi enviado: sem ele o Flash não tem com quem cruzar.")
                if st.button(f"Salvar o Flash de {mes_f[5:]}/{mes_f[:4]} ({emp_f})", type="primary", disabled=not (ok and cruz["casadas"]), key="fpj_salvar_flash"):
                    r = IP.gravar_flash(conn, mes_f, emp_f, cruz["casadas"], usuario)
                    st.toast(f"Flash salvo: {r['pessoas']} pessoas.", icon="✅")
                    st.rerun()
            except IP.ErroFolhaPJ as exc:
                st.error(str(exc))
        st.divider()
        st.markdown("**3) Credores da diretoria** (aparecem numa linha só, com centro de custo “DIRETORIA”)")
        lista = IP.diretoria_listar(conn) if ok else []
        if lista:
            st.dataframe(pd.DataFrame([{"Código do credor": x["credor_id"], "Nome": x["nome"], "Alterado por": x["quem"] or "–"} for x in lista]), hide_index=True, width="stretch")
        d1, d2, d3 = st.columns([2, 3, 1])
        cod = d1.number_input("Código do credor no Sienge", min_value=0, step=1, value=0, key="fpj_dir_cod")
        nome = d2.text_input("Nome (opcional)", key="fpj_dir_nome")
        if d3.button("Adicionar", disabled=not (ok and cod), key="fpj_dir_add"):
            IP.diretoria_adicionar(conn, int(cod), nome, usuario)
            st.rerun()
        if lista:
            rem = st.selectbox("Remover da diretoria", [None] + [x["credor_id"] for x in lista], format_func=lambda c: "–" if c is None else str(c), key="fpj_dir_rem")
            if rem is not None and st.button("Remover", key="fpj_dir_rem_btn"):
                IP.diretoria_remover(conn, int(rem), usuario)
                st.rerun()
