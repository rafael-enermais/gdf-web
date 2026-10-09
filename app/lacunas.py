# -*- coding: utf-8 -*-
"""
GDF - ver as lacunas: o que cada mês tem de balancete e o que acontece (n/d) se o relatório for gerado assim.
Nada aqui trava o uso do app: só informa. As funções de cálculo são puras; as de tela usam Streamlit.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import fontes
import formatacao as F
import motor


def cobertura(mensais: dict, acumulados: dict, mapa, status: dict | None = None) -> list:
    """Uma linha por mês (de janeiro até o último mês com dado de cada ano): o que foi importado e como sairia o relatório daquele mês."""
    status = status or {}
    linhas = []
    for ano in sorted({m[:4] for m in list(mensais) + list(acumulados)}):
        ultimo = max(int(m[5:7]) for m in list(mensais) + list(acumulados) if m[:4] == ano)
        for n in range(1, ultimo + 1):
            m = f"{ano}-{n:02d}"
            tem_m, tem_a = m in mensais, m in acumulados
            if not (tem_m or tem_a):
                rel = "— sem balancete deste mês: o relatório deste mês não pode ser gerado"
            else:
                try:
                    r = fontes.calcular(mensais, acumulados, mapa, m)
                    if r["fonte"] == "completo":
                        rel = "✅ completo"
                    elif r["fonte"] == "alternativo":
                        rel = "✅ completo (calculado também com balancete acumulado)"
                    else:
                        rel = f"⚠️ sai com n/d em {len(r['lacunas'])} item(ns)"
                except motor.ErroDados as exc:
                    rel = f"— {exc}"
            linhas.append({"Mês": f"{n:02d}/{ano}",
                           "Balancete mensal": ("✅ " + status.get(("MENSAL", m), "")).strip() if tem_m else "—",
                           "Balancete acumulado (jan até o mês)": ("✅ " + status.get(("ACUMULADO", m), "")).strip() if tem_a else "—",
                           "Relatório deste mês": rel})
    return linhas


def mostrar_cobertura(conn, emp: dict) -> None:
    """Quadro 'Cobertura do ano' da tela Importar. Nunca quebra a tela."""
    try:
        mensais, acum = db.periodos_mensais_ativos(conn, emp["id"]), db.acumulados_ativos(conn, emp["id"])
        if not mensais and not acum:
            return
        st_ = {(i["tipo"], f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}"): i["status"] for i in db.listar_importacoes(conn, emp["id"]) if i["ativo"]}
        linhas = cobertura(mensais, acum, db.mapa_vigente(conn, emp["id"]), st_)
    except Exception as exc:            # a cobertura é informativa
        st.caption(f"Não consegui montar a cobertura agora ({exc}).")
        return
    st.subheader("Cobertura do ano")
    st.caption("O ideal é ter todos os meses (relatório completo), mas **nada trava**: com meses faltando o app usa o balancete acumulado quando possível e marca **n/d** "
               "só no que não dá para calcular, sempre explicando o motivo.")
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")


def mostrar_lacunas(dados: dict, expandido: bool = True) -> None:
    """Aviso + lista do que está n/d (e como resolver) + de onde vêm os números. Usado em Demonstrativos e Relatório PDF."""
    lac = dados["lacunas"]
    if lac:
        st.warning(f"Este relatório sai com **n/d em {len(lac)} item(ns)** (faltam balancetes). O que foi calculado está correto; o que não dá para calcular não é inventado.")
        with st.expander("O que falta e o que acontece se gerar assim", expanded=expandido):
            for l in lac:
                st.markdown(f"- **{l['onde']}** ficará n/d — {l['motivo']}.  \n  *Para resolver:* {l['resolver']}.")
    elif dados["fonte"] != "completo":
        st.info("Todas as colunas foram calculadas, mas parte vem de balancete acumulado em vez da soma dos meses (veja “De onde vêm os números”).")
    for n in dados["notas"]:
        st.caption(n)
    if dados["fontes"]:
        per = dados.get("ini", 1) > 1
        ROT = {"bp_abertura": "Balanço — abertura do período" if per else "Balanço — 31/12 anterior", "bp_ant": "Balanço — mês anterior", "bp_ref": "Balanço — mês de referência",
               "dre_ate_ant": "DRE — acumulado até o mês anterior", "dre_mes": "DRE — mês", "dre_acum": "DRE — acumulado do período" if per else "DRE — acumulado do ano"}
        with st.expander("De onde vêm os números"):
            for k in ROT:
                if k in dados["fontes"]:
                    st.markdown(f"- **{ROT[k]}:** {dados['fontes'][k]}")


_AB = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def escolher_periodo(conn, empresa_id: int, mes_ref: str, dados: dict, key: str) -> tuple:
    """Quando faltam balancetes mensais no ano, deixa a usuária escolher COMO gerar (nada trava, e cada caminho diz o que entrega):
    ano completo com n/d · só o período depois da lacuna · até o último mês completo antes da lacuna.
    Devolve (mês de referência a usar, 1º mês do período, dados calculados para essa escolha)."""
    import contexto
    op = fontes.opcoes_periodo(dados, mes_ref)
    if not op:
        return mes_ref, 1, dados
    ano, M = mes_ref[:4], int(mes_ref[5:7])
    faltam = ", ".join(F.mes_br(m) for m in op["faltam"])
    descr = {"ano": (f"Ano completo (jan–{_AB[M - 1]}/{ano}), com n/d onde faltar",
                     f"Mostra o ano todo. A DRE acumulada e o que depende dela ficam **n/d** por falta de {faltam}; o Balanço sai completo. Quando importar o que falta, basta gerar de novo.")}
    if op["apos"]:
        s = int(op["apos"][5:7])
        descr["apos"] = ((f"Só o período depois da lacuna: {_AB[s - 1]}–{_AB[M - 1]}/{ano}" if s < M else f"Só {_AB[M - 1]}/{ano} (o mês depois da lacuna)") + " — completo, sem n/d",
                         f"Balanço com abertura no fim de {_AB[s - 2]}/{ano} e DRE somando só {'os meses de ' + _AB[s - 1] + ' a ' + _AB[M - 1] if s < M else _AB[M - 1]}. "
                         f"O resultado de jan–{_AB[s - 2]} não entra nas colunas de resultado (já está no patrimônio líquido de abertura). O relatório diz isso na página “Fontes dos números”.")
    if op["ate"]:
        e = int(op["ate"][5:7])
        descr["ate"] = (f"Até o último mês completo: jan–{_AB[e - 1]}/{ano} (relatório de {F.mes_br(op['ate'])}) — completo, sem n/d",
                        f"Gera o relatório de {F.mes_br(op['ate'])}, que tem todos os meses de janeiro a {_AB[e - 1]}. O mês {F.mes_br(mes_ref)} não entra.")
    st.warning(f"**Faltam os balancetes mensais de {faltam}.** Escolha como gerar este relatório (nada trava):")
    esc = st.radio("Período do relatório", list(descr), format_func=lambda k: descr[k][0], key=f"{key}_per_{empresa_id}_{mes_ref}")
    st.caption(descr[esc][1])
    try:
        if esc == "apos":
            ini = int(op["apos"][5:7])
            return mes_ref, ini, contexto.carregar(conn, empresa_id, mes_ref, ini)
        if esc == "ate":
            return op["ate"], 1, contexto.carregar(conn, empresa_id, op["ate"])
    except motor.ErroDados as exc:
        st.error(str(exc))
    return mes_ref, 1, dados
