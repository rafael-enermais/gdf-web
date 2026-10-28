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


_TIPOS = {"flash": "Flash", "mapa": "Mapa de colaboradores", "novos": "Novos colaboradores PJ", "ignorar": "Ignorar"}


def _salvo_agora(conn) -> None:
    """Mostra o que JA esta gravado (a prova de que salvou): mapa e Flash por mes/empresa."""
    try:
        r = IP.resumo_salvo(conn)
    except Exception:                                  # noqa: BLE001  (SQL-40 ainda nao rodou)
        return
    quando = r["quando"].strftime("%d/%m %H:%M") if r["quando"] else "–"
    st.markdown("**Já salvo no app**")
    st.caption(f"Mapa de colaboradores: {r['colaboradores']} pessoas (última alteração {quando}).")
    if r["flash"]:
        st.dataframe(pd.DataFrame([{"Mês": f"{x['mes'][5:]}/{x['mes'][:4]}", "Empresa": x["empresa"], "Pessoas": x["pessoas"], "Premiação no cartão (ajuda de custo)": _m(x["premiacao"]),
                                    "Refeição/alimentação (vale)": _m(x["alimentacao"]), "Enviado por": x["quem"] or "–",
                                    "Quando": x["quando"].strftime("%d/%m %H:%M") if x["quando"] else "–"} for x in r["flash"]]), hide_index=True, width="stretch")
    else:
        st.caption("Nenhum Flash salvo ainda.")


def _arquivos_do_mes(conn, ok: bool, seg: str, usuario) -> None:
    """Um envio so' para tudo: mapa de colaboradores e/ou Flash, varios arquivos juntos. O app descobre o que cada arquivo e' (e a empresa do Flash), mostra o que entendeu
    e so' grava depois do 'Confirmar'. Mapa entra antes do Flash (o Flash cruza com ele). Depois de salvar mostra o resultado e esvazia o campo de envio."""
    st.markdown("**1) Arquivos do mês** (mapa de colaboradores PJ e/ou Flash: pode enviar vários de uma vez)")
    _cap("O app descobre sozinho o que é cada arquivo e a empresa do Flash (pelo nome do arquivo); você confere e confirma. Premiação no cartão entra como ajuda de custo; "
         "refeição/alimentação, como vale alimentação. O Flash cruza com o mapa pelo CPF e, sem CPF, pelo nome. Planilha com senha não abre: envie uma cópia sem senha.")
    resultado = st.session_state.pop("fpj_resultado", None)
    if resultado:
        for linha in resultado:
            st.success(_t(linha), icon="✅")
    v = st.session_state.get("fpj_up_v", 0)
    arqs = st.file_uploader("Arquivos (xlsx)", type=["xlsx"], accept_multiple_files=True, key=f"fpj_up_{v}")
    if arqs is not None and not isinstance(arqs, (list, tuple)):
        arqs = [arqs]
    if arqs:
        lidos = []                                      # [{nome, tipo, aba, empresa, lido, bytes}]
        for i, a in enumerate(arqs):
            b = a.getvalue()
            try:
                det = IP.detectar(b, a.name)
            except IP.ErroFolhaPJ as exc:
                st.error(f"{a.name}: {exc}")
                continue
            tipos = list(_TIPOS)
            c1, c2, c3 = st.columns([3, 2, 3])
            c1.markdown(_t(f"**{a.name}**"))
            tipo = c2.selectbox("O que é", tipos, index=tipos.index(det["tipo"]) if det["tipo"] in tipos else tipos.index("ignorar"), format_func=_TIPOS.get,
                                key=f"fpj_tipo_{v}_{i}", label_visibility="collapsed")
            aba, emp = det["aba"], None
            if tipo == "flash":
                emps = list(FP.EMPRESAS.values())
                emp = c3.selectbox("Empresa do Flash", emps, index=emps.index(det["empresa"]) if det["empresa"] in emps else None,
                                   placeholder="Escolha a empresa", key=f"fpj_emp_{v}_{i}", label_visibility="collapsed")
            elif tipo in ("mapa", "novos") and len(det["abas"]) > 1:
                aba = c3.selectbox("Aba", det["abas"], index=det["abas"].index(det["aba"]), key=f"fpj_aba_{v}_{i}", label_visibility="collapsed")
            if tipo == "ignorar":
                continue
            try:
                lido = IP.ler_flash(b, seg) if tipo == "flash" else IP.ler_mapa_colaboradores(b, seg, aba)
            except IP.ErroFolhaPJ as exc:
                st.error(f"{a.name}: {exc}")
                continue
            lidos.append({"nome": a.name, "tipo": tipo, "aba": aba, "empresa": emp, "lido": lido})
        if lidos:
            abas_mes = [x["aba"] for x in lidos if x["tipo"] in ("mapa", "novos") and len(x["aba"]) == 7 and x["aba"][2] == "-"]
            opcoes = _meses_opcoes()
            dica = f"{abas_mes[0][3:]}-{abas_mes[0][:2]}" if abas_mes else opcoes[0]
            mes_n = st.selectbox("Mês dos arquivos", opcoes, index=opcoes.index(dica) if dica in opcoes else 0, format_func=lambda m: f"{m[5:]}/{m[:4]}", key=f"fpj_mes_{v}")
            cad = dict(IP.colaboradores_cadastrados(conn))
            for x in lidos:                              # o mapa deste envio vale para o cruzamento da previa
                if x["tipo"] in ("mapa", "novos"):
                    for l in x["lido"]["linhas"]:
                        cad[l["credor_id"]] = {"cpf_hash": l["cpf_hash"], "chave": FP.chave_nome(l["nome"])}
            fant = IP.fantasias_dos(conn, list(cad))
            linhas_prev, falta_emp = [], False
            for x in lidos:
                if x["tipo"] == "flash":
                    cruz = IP.cruzar_flash(x["lido"]["linhas"], cad, fant)
                    x["cruz"] = cruz
                    falta_emp = falta_emp or not x["empresa"]
                    linhas_prev.append({"Arquivo": x["nome"], "O que é": "Flash", "Empresa / aba": x["empresa"] or "⚠ escolher a empresa", "Pessoas no arquivo": len(x["lido"]["linhas"]),
                                        "Casaram com PJ": len(cruz["casadas"]), "Sem PJ (CLT/outra empresa)": cruz["sem_pj"],
                                        "Ajuda de custo (casadas)": _m(sum(c["premiacao"] for c in cruz["casadas"])), "Vale alimentação (casadas)": _m(sum(c["alimentacao"] for c in cruz["casadas"]))})
                else:
                    linhas_prev.append({"Arquivo": x["nome"], "O que é": _TIPOS[x["tipo"]], "Empresa / aba": f"aba {x['aba']}", "Pessoas no arquivo": len(x["lido"]["linhas"]),
                                        "Casaram com PJ": None, "Sem PJ (CLT/outra empresa)": None, "Ajuda de custo (casadas)": "–", "Vale alimentação (casadas)": "–"})
            st.dataframe(pd.DataFrame(linhas_prev), hide_index=True, width="stretch")
            for x in lidos:
                for av in x["lido"]["avisos"]:
                    st.caption(_t(f"{x['nome']}: {av}"))
            empresas_flash = [x["empresa"] for x in lidos if x["tipo"] == "flash" and x["empresa"]]
            if len(empresas_flash) != len(set(empresas_flash)):
                st.warning("Há dois arquivos de Flash da mesma empresa neste envio: vale o último da lista.")
            if falta_emp:
                st.warning("Escolha a empresa dos arquivos de Flash marcados com ⚠ para poder salvar.")
            if any(x["tipo"] == "flash" for x in lidos) and not cad:
                st.warning("O mapa de colaboradores ainda não foi enviado: sem ele o Flash não tem com quem cruzar.")
            pode = ok and not falta_emp
            if st.button(f"Confirmar e salvar {len(lidos)} arquivo(s) de {mes_n[5:]}/{mes_n[:4]}", type="primary", disabled=not pode, key=f"fpj_confirma_{v}"):
                msgs = []
                try:
                    for x in (y for y in lidos if y["tipo"] in ("mapa", "novos")):
                        r = IP.gravar_colaboradores(conn, x["lido"]["linhas"], mes_n, usuario, novos=(x["tipo"] == "novos"))
                        msgs.append(f"{x['nome']}: mapa salvo ({r['novos']} novos e {r['atualizados']} atualizados).")
                    cad2 = IP.colaboradores_cadastrados(conn)
                    fant2 = IP.fantasias_dos(conn, list(cad2))
                    for x in (y for y in lidos if y["tipo"] == "flash"):
                        cz = IP.cruzar_flash(x["lido"]["linhas"], cad2, fant2)
                        r = IP.gravar_flash(conn, mes_n, x["empresa"], cz["casadas"], usuario)
                        msgs.append(f"{x['nome']}: Flash de {mes_n[5:]}/{mes_n[:4]} ({x['empresa']}) salvo: {r['pessoas']} pessoas, ajuda de custo {_m(r['premiacao'])} e "
                                    f"vale alimentação {_m(r['alimentacao'])}.")
                except Exception as exc:                 # noqa: BLE001
                    st.error(f"Não consegui salvar: {type(exc).__name__}. Nada foi marcado como salvo; confira o bloco “Já salvo no app” abaixo.")
                else:
                    st.session_state["fpj_resultado"] = msgs
                    st.session_state["fpj_up_v"] = v + 1           # esvazia o campo de envio
                    st.rerun()
    st.divider()
    _salvo_agora(conn)


def upload_secao(conn, usuario) -> None:
    """Secao 'Folha PJ' das Importacoes V2: mapa de colaboradores, Flash e credores da diretoria. Nada e' apagado: reenviar troca/atualiza."""
    ok = FP.instalado(conn)
    with st.expander("Folha PJ: mapa de colaboradores, Flash e diretoria", expanded=False):
        if not ok:
            st.warning("Falta executar o arquivo `sql/v2_folha_pj.sql` (SQL-40) no Supabase para o app guardar estes cadastros. Você já pode ler os arquivos; só não dá para salvar.")
        seg = segredo()
        if not seg:
            st.caption("Sem segredo configurado: o CPF não será usado e o Flash cruza só pelo nome. (O CPF nunca é gravado; só um código irreversível dele, e só com o segredo.)")
        _arquivos_do_mes(conn, ok, seg, usuario)
        st.divider()
        st.markdown("**2) Credores da diretoria** (aparecem numa linha só, com centro de custo “DIRETORIA”)")
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
