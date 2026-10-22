# -*- coding: utf-8 -*-
"""GDF V2 - dados do Painel da Diretoria (replica do painel da contabilidade) que dependem do acumulado do ano: Despesas e Pessoas por conta -> credor -> obra,
e o PJ por colaborador. Tudo vem das CONTAS PAGAS (baixas de pagamento x rateio, mesmas regras da aba Despesas). So' leitura.

Como funciona, em linguagem simples:
- `pagos_detalhe` busca no banco quanto foi pago, mes a mes, por conta do plano, credor e obra (um unico select);
- as demais funcoes so' somam/filtram essa lista (nao tocam no banco), por isso sao faceis de testar;
- PJ por colaborador: a contabilidade definiu que a fonte e' a conta paga "Salarios PJ" (obra e administracao) e que nao ha regras para eles; cada credor PJ conta
  1 colaborador, alocado na obra onde ele recebeu mais naquele mes (ou na administracao).
Nomes de pessoas/credores so' aparecem na tela (com login) e ficam no banco; nada disso vai para o repositorio publico."""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

import periodo as PER
from grupo_enermais import nucleo as _nucleo_grupo

PESSOAS = ("2.01.02", "2.02.01")                                      # pessoal de obra e pessoal ADM (o painel mostra na aba Pessoas)
SALARIOS_E_PREMIACOES = ("2.01.02.01", "2.01.02.10", "2.01.02.11", "2.02.01.01", "2.02.01.02", "2.02.01.06")   # PJ, CLT e premiacoes: fora dos "custos prioritarios"
CONTAS_PJ = ("2.01.02.01", "2.02.01.01")
COLUNAS = ["mes", "plano_cod", "plano_nome", "credor", "cc", "obra", "grupo", "valor"]


def _sem_acento(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def eh_pj(cod: str, nome: str) -> bool:
    """Conta de salario de PJ: codigos conhecidos ou nome 'Salarios PJ | ...'."""
    return cod in CONTAS_PJ or _sem_acento(nome).startswith("salarios pj")


def nome_conta_pessoas(nome: str) -> str:
    """'Horas Extras | Obra' e 'Horas Extras | ADM' viram a mesma linha 'Horas Extras' (o painel da contabilidade une obra e administracao)."""
    n = re.sub(r"\s*\|\s*(Obra|ADM)\s*$", "", str(nome or "").strip(), flags=re.I).strip()
    return n or "(sem nome)"


def _excluido(cod: str, prefixos) -> bool:
    return any(cod == p or cod.startswith(p + ".") for p in prefixos)


# ------------------------------------------------------------------ banco
def pagos_detalhe(conn, mes_ini: str, mes_fim: str, sem_previsao: bool = False) -> list:
    """Pago (liquido da baixa x % do rateio) entre os meses 'AAAA-MM' (inclusive), por mes de pagamento, conta, credor, centro de custo e obra do de-para.
    Devolve [{'mes','plano_cod','plano_nome','credor','cc','obra','grupo','valor'}]. Sem o de-para de centros de custo, 'obra' e 'grupo' ficam vazios."""
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    base = """SELECT to_char(b.data_pagamento,'YYYY-MM'), r.plano_cod, max(r.plano_nome),
                     COALESCE(NULLIF(trim(t.contraparte_nome),''),'(sem credor)'),
                     COALESCE(NULLIF(trim(r.centro_custo_nome),''),'(sem centro de custo)'),
                     {obra}, {grupo}, sum(b.liquido * r.percentual / 100.0)
              FROM pnl_v_baixa b
              JOIN pnl_v_rateio r ON r.lado=b.lado AND r.bill_id=b.bill_id AND r.installment_id=b.installment_id
              JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
              {juncao}
              WHERE b.lado='P' AND b.data_pagamento >= %s::date AND b.data_pagamento < (%s::date + interval '1 month') {filtro}
              GROUP BY 1, 2, 4, 5, 6, 7"""
    par = (f"{mes_ini}-01", f"{mes_fim}-01")
    tentativas = (
        base.format(obra="COALESCE(g.codigo_obra,'')", grupo="COALESCE(g.grupo,'')", juncao="LEFT JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id", filtro=filtro),
        base.format(obra="''", grupo="''", juncao="", filtro=filtro),
    )
    for sql in tentativas:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, par)
                linhas = cur.fetchall()
            return [{"mes": m, "plano_cod": c, "plano_nome": n or "", "credor": cr, "cc": cc, "obra": ob, "grupo": gr, "valor": float(v or 0)}
                    for m, c, n, cr, cc, ob, gr, v in linhas]
        except Exception:                                           # noqa: BLE001  (sem a tabela do de-para: segue sem obra)
            try:
                conn.rollback()
            except Exception:                                       # noqa: BLE001
                pass
    return []


# ------------------------------------------------------------------ base em DataFrame
def para_df(linhas: list) -> pd.DataFrame:
    df = pd.DataFrame(linhas or [], columns=COLUNAS)
    if len(df):
        df["valor"] = df["valor"].astype(float)
    return df


def despesas_df(df: pd.DataFrame, prefixos_fora: list) -> pd.DataFrame:
    """Contas pagas SEM as contas excluidas pelas regras da aba Despesas (pessoal, encargos, transferencias...)."""
    if not len(df):
        return df
    return df[~df["plano_cod"].map(lambda c: _excluido(c, prefixos_fora))].copy()


def pessoas_df(df: pd.DataFrame) -> pd.DataFrame:
    """Custos prioritarios com pessoas: contas 2.01.02 e 2.02.01, SEM salarios CLT/PJ e premiacoes. 'plano_nome' ja vem sem o sufixo Obra/ADM."""
    if not len(df):
        return df
    m = df["plano_cod"].map(lambda c: _excluido(c, PESSOAS) and c not in SALARIOS_E_PREMIACOES)
    out = df[m].copy()
    out["plano_nome"] = out["plano_nome"].map(nome_conta_pessoas)
    return out


# ------------------------------------------------------------------ somas
def meses_do_ano(mes: str) -> list:
    """['AAAA-01', ..., mes]"""
    return [f"{mes[:4]}-{i:02d}" for i in range(1, int(mes[5:]) + 1)]


def total_por(df: pd.DataFrame, col: str = "plano_nome") -> list:
    """[(chave, acumulado)] do maior para o menor."""
    if not len(df):
        return []
    s = df.groupby(col)["valor"].sum().sort_values(ascending=False)
    return [(k, round(float(v), 2)) for k, v in s.items()]


def serie_mensal(df: pd.DataFrame, meses: list, conta: str | None = None) -> list:
    """Valor pago em cada mes de `meses` (0 onde nao houve), de uma conta (plano_nome) ou de todas."""
    d = df if conta is None else df[df["plano_nome"] == conta]
    por = d.groupby("mes")["valor"].sum().to_dict() if len(d) else {}
    return [round(float(por.get(m, 0.0)), 2) for m in meses]


def agrupar(df: pd.DataFrame, por: str, mes_ref: str, conta: str | None = None, credor: str | None = None, top: int = 15) -> dict:
    """Acumulado do periodo e valor do mes de referencia, agrupado por `por` ('credor' ou 'cc'), filtrado por conta e/ou credor.
    -> {'linhas': [{'chave','acumulado','mes'}] (top N), 'n': total de chaves, 'total': soma do filtro}"""
    d = df
    if conta is not None:
        d = d[d["plano_nome"] == conta]
    if credor is not None:
        d = d[d["credor"] == credor]
    if not len(d):
        return {"linhas": [], "n": 0, "total": 0.0}
    g = d.groupby(por)["valor"].sum()
    gm = d[d["mes"] == mes_ref].groupby(por)["valor"].sum()
    ordem = g.sort_values(ascending=False)
    linhas = [{"chave": k, "acumulado": round(float(v), 2), "mes": round(float(gm.get(k, 0.0)), 2)} for k, v in ordem.head(top).items()]
    return {"linhas": linhas, "n": int(len(ordem)), "total": round(float(g.sum()), 2)}


def tabela_pessoas(df_pess: pd.DataFrame, mes: str, colab_mes: int | None, colab_soma_antes: int | None, meses: list | None = None) -> list:
    """Linha por conta de pessoas: valor do mes, % do mes, R$/colab no mes, acumulado ate o mes anterior, R$/colab acumulado e variacao
    (R$/colab do mes ÷ R$/colab acumulado − 1). `colab_mes` = colaboradores do mes; `colab_soma_antes` = soma do headcount mensal dos meses anteriores do ano.
    Sem headcount, as colunas por colaborador ficam None."""
    if not len(df_pess):
        return []
    antes = [m for m in (meses if meses is not None else meses_do_ano(mes)) if m < mes]       # meses do periodo escolhido (padrao: o ano) antes do mes de referencia
    set_ = df_pess[df_pess["mes"] == mes].groupby("plano_nome")["valor"].sum()
    acu = df_pess[df_pess["mes"].isin(antes)].groupby("plano_nome")["valor"].sum()
    contas = sorted(set(set_.index) | set(acu.index), key=lambda c: -float(set_.get(c, 0.0)))
    tot_mes = float(set_.sum())
    out = []
    for c in contas:
        v, a = float(set_.get(c, 0.0)), float(acu.get(c, 0.0))
        rc_m = v / colab_mes if colab_mes else None
        rc_a = a / colab_soma_antes if colab_soma_antes else None
        rc_p = (v + a) / (colab_soma_antes + colab_mes) if colab_mes and colab_soma_antes else None            # periodo inteiro (meses antes + mes de referencia) por colaborador-mes
        out.append({"conta": c, "mes": round(v, 2), "pct_mes": round(v / tot_mes, 4) if abs(tot_mes) > 0.005 else None, "por_colab_mes": None if rc_m is None else round(rc_m, 2),
                    "acum_antes": round(a, 2), "por_colab_acum": None if rc_a is None else round(rc_a, 2),
                    "periodo": round(v + a, 2), "por_colab_periodo": None if rc_p is None else round(rc_p, 2),
                    "variacao": round(rc_m / rc_a - 1, 4) if rc_m is not None and rc_a else None})
    return out


def nome_fantasia(credor: str, mapa: dict | None) -> str:
    """Nome a mostrar para um colaborador PJ: o NOME FANTASIA do cadastro do credor (pedido da contabilidade, 21/10/2026); sem fantasia cadastrada, a razao social como veio."""
    if not mapa or not credor:
        return credor
    from painel_db import norm_credor
    return mapa.get(norm_credor(credor)) or credor


# ------------------------------------------------------------------ PJ por colaborador (fonte: contas pagas "Salarios PJ")
def pj_do_mes(df: pd.DataFrame, mes: str) -> dict:
    """PJ do mes a partir das contas pagas 'Salarios PJ': cada credor com valor positivo conta 1 colaborador, alocado onde recebeu mais (empate: obra).
    -> {'total','obra','adm','por_obra': {codigo_obra|'sem de-para': n}, 'colaboradores': [{'credor','destino','valor'}]}.
    Destino = codigo da obra (do de-para), 'ADM' (conta de pessoal ADM / centro do grupo ADM) ou 'sem de-para'."""
    vazio = {"total": 0, "obra": 0, "adm": 0, "por_obra": {}, "colaboradores": []}
    if not len(df):
        return vazio
    d = df[(df["mes"] == mes) & df.apply(lambda r: eh_pj(r["plano_cod"], r["plano_nome"]), axis=1)] if len(df) else df
    if not len(d):
        return vazio

    def destino(r) -> str:
        if r["plano_cod"].startswith("2.02.01") or r["grupo"] == "ADM":
            return "ADM"
        return r["obra"] or "sem de-para"

    d = d.assign(destino=d.apply(destino, axis=1))
    por = d.groupby(["credor", "destino"])["valor"].sum().reset_index()
    tot_credor = por.groupby("credor")["valor"].sum()
    colabs, n_obra = [], {}
    for credor, sub in por.groupby("credor"):
        if tot_credor[credor] <= 0.005:
            continue                                                    # estornos/zerados nao sao colaborador no mes
        sub = sub.assign(ord=sub["destino"].map(lambda x: 1 if x == "ADM" else 0)).sort_values(["valor", "ord"], ascending=[False, True])
        dest, val = sub.iloc[0]["destino"], float(tot_credor[credor])
        colabs.append({"credor": credor, "destino": dest, "valor": round(val, 2)})
        if dest != "ADM":
            n_obra[dest] = n_obra.get(dest, 0) + 1
    n_adm = sum(1 for c in colabs if c["destino"] == "ADM")
    return {"total": len(colabs), "obra": len(colabs) - n_adm, "adm": n_adm, "por_obra": n_obra, "colaboradores": sorted(colabs, key=lambda c: -c["valor"])}


def _destino_linha(r) -> str:
    """Destino de um pagamento: 'ADM' (conta de pessoal ADM ou centro do grupo ADM), codigo da obra do de-para ou 'sem de-para'."""
    if r["plano_cod"].startswith("2.02.01") or r["grupo"] == "ADM":
        return "ADM"
    return r["obra"] or "sem de-para"


def pj_por_obra(df: pd.DataFrame, mes: str) -> list:
    """Lista de PJ por obra no mes, como no painel da contabilidade: o PJ que recebeu em mais de uma obra aparece em cada uma, com o % do que recebeu naquela obra
    sobre o total dele no mes (obra + administracao). Estornos/zerados ficam fora; a administracao nao entra (o painel mostra so' as obras).
    -> [{'obra','credor','valor','pct'}] ordenado por obra e valor."""
    if not len(df):
        return []
    d = df[(df["mes"] == mes) & df.apply(lambda r: eh_pj(r["plano_cod"], r["plano_nome"]), axis=1)]
    if not len(d):
        return []
    d = d.assign(destino=d.apply(_destino_linha, axis=1))
    por = d.groupby(["credor", "destino"])["valor"].sum().reset_index()
    tot = por.groupby("credor")["valor"].sum()
    out = []
    for _, r in por.iterrows():
        t = float(tot[r["credor"]])
        if r["destino"] == "ADM" or t <= 0.005 or r["valor"] <= 0.005:
            continue
        out.append({"obra": r["destino"], "credor": r["credor"], "valor": round(float(r["valor"]), 2), "pct": round(float(r["valor"]) / t, 4)})
    return sorted(out, key=lambda x: (x["obra"], -x["valor"]))


def credores_da_obra(dd: pd.DataFrame, obras: list | None, mes_ref: str, top: int = 15) -> dict:
    """Principais credores das Despesas (sem pessoal) por obra. `obras` = codigos de obra do de-para (None = todas as obras, ate sem de-para).
    -> mesmo formato de `agrupar`: {'linhas': [{'chave','acumulado','mes'}], 'n', 'total'}."""
    if not len(dd):
        return {"linhas": [], "n": 0, "total": 0.0}
    d = dd if obras is None else dd[dd["obra"].isin(obras)]
    return agrupar(d, "credor", mes_ref, top=top)


# ------------------------------------------------------------------ listas de credores: PJ, grupo ENERMAIS, "Outros credores/Dir"
def credores_pj(df: pd.DataFrame) -> set:
    """Credores que sao colaboradores PJ: quem recebeu em conta de 'Salarios PJ' no periodo carregado. Saem da lista de credores das obras (a pessoa ja' esta em colaboradores)."""
    if not len(df):
        return set()
    m = df.apply(lambda r: eh_pj(r["plano_cod"], r["plano_nome"]), axis=1)
    return set(df.loc[m, "credor"])


def sem_credores(df: pd.DataFrame, credores) -> pd.DataFrame:
    """Linhas sem os credores informados (comparacao exata do nome)."""
    if not len(df) or not credores:
        return df
    return df[~df["credor"].isin(set(credores))].copy()


def sem_grupo_enermais(df: pd.DataFrame, nucleos) -> pd.DataFrame:
    """Linhas sem os credores que sao empresas do grupo ENERMAIS (nome comparado pelo nucleo: sem acento, LTDA etc.)."""
    if not len(df) or not nucleos:
        return df
    alvo = set(nucleos)
    return df[~df["credor"].map(lambda c: _nucleo_grupo(c) in alvo)].copy()


def marcar_outros_dir(df: pd.DataFrame, chaves: list, rotulo: str = "Outros credores/Dir") -> pd.DataFrame:
    """Coluna 'credor_exib': o proprio credor, ou `rotulo` quando o nome COMECA com uma das chaves do grupo 'Outros credores/Dir' (sem acento, maiusculas)."""
    out = df.copy()
    norm = lambda t: re.sub(r"\s+", " ", _sem_acento(t)).upper()                  # noqa: E731  (mesma regra do painel_db.norm_credor: espacos simples)
    ch = [c for c in (norm(k) for k in (chaves or [])) if c]
    out["credor_exib"] = out["credor"].map(lambda c: rotulo if any(norm(c).startswith(k) for k in ch) else c) if len(out) else []
    return out


def agrupar_pj_demais(colaboradores: list, chaves: list, rotulo: str = "Demais colaboradores-PJ") -> list:
    """Lista de PJ do mes com os credores do grupo 'Demais colaboradores-PJ' somados numa linha so' (o nome COMECA com uma das chaves, sem acento/maiuscula).
    -> mesma lista, sem esses credores + 1 linha {'credor': rotulo, 'destino': 'vários', 'valor': soma, 'n': quantos, 'agrupado': True} (nenhum nome aparece).
    A contagem de colaboradores nao muda: so' a forma de mostrar. Sem chaves ou sem ninguem casando, devolve a lista como veio."""
    norm = lambda t: re.sub(r"\s+", " ", _sem_acento(t)).upper()                  # noqa: E731
    ch = [c for c in (norm(k) for k in (chaves or [])) if c]
    if not ch or not colaboradores:
        return list(colaboradores or [])
    dentro = [c for c in colaboradores if any(norm(c["credor"]).startswith(k) for k in ch)]
    if not dentro:
        return list(colaboradores)
    fora = [c for c in colaboradores if c not in dentro]
    linha = {"credor": rotulo, "destino": "vários", "valor": round(sum(c["valor"] for c in dentro), 2), "n": len(dentro), "agrupado": True}
    return sorted(fora + [linha], key=lambda c: -c["valor"])


def rotular_obras(df: pd.DataFrame, nomes: dict) -> pd.DataFrame:
    """Coluna 'obra_rot' = a mesma linguagem da aba Obras: '<codigo> · <nome da obra>' para cada centro de custo ligado a uma obra pelo de-para;
    centros da administracao -> 'Administração'; codigo DEM -> 'Demais obras'; sem de-para -> 'Sem obra (<centro de custo>)'.
    Ex.: 'EE - ANASTACIO - LOTE 11' e 'CON - ANASTACIO - LOTE 11' caem na mesma obra."""
    out = df.copy()

    def rot(r) -> str:
        cod = (r["obra"] or "").strip()
        if r["grupo"] == "ADM" or cod in ("ADM", "99"):
            return "Administração"
        if cod == "DEM":
            return "Demais obras"
        if not cod or cod == "sem de-para":
            return f"Sem obra ({r['cc']})"
        nome = (nomes or {}).get(cod)
        return f"{cod} · {nome}" if nome else cod

    out["obra_rot"] = out.apply(rot, axis=1) if len(out) else []
    return out


# ------------------------------------------------------------------ Pessoas: evolucao do custo com hora extra x evolucao da receita
def _var(d: dict, m: str):
    a, b = d.get(m), d.get(PER.somar_meses(m, -1))
    return None if a is None or not b or b <= 0 else round(float(a) / float(b) - 1, 4)


def _soma(d: dict, meses: list):
    """Soma dos meses; None se faltar algum (nao compara periodo incompleto com periodo completo)."""
    v = [d.get(m) for m in meses]
    return None if not v or any(x is None for x in v) else round(sum(float(x) for x in v), 2)


def evolucao_he_receita(serie_he: list, serie_receita: list, meses: list) -> list:
    """Mes a mes: % de HE sobre a remuneracao, custo de HE (R$), receita (R$) e a variacao % de cada um sobre o mes anterior.
    `serie_he` = historico.serie_he_combinada; `serie_receita` = painel_db.receita_mensal. -> [{'mes','he_pct','he','var_he','receita','var_receita'}]"""
    he = {x["mes"]: x.get("he") for x in serie_he}
    pct = {x["mes"]: x.get("he_pct") for x in serie_he}
    rec = {x["mes"]: x["receita"] for x in serie_receita}
    return [{"mes": m, "he_pct": pct.get(m), "he": he.get(m), "var_he": _var(he, m), "receita": rec.get(m), "var_receita": _var(rec, m)} for m in meses]


def comparar_periodos(serie_he: list, serie_receita: list, mes_ini: str, mes_fim: str) -> dict:
    """Periodo escolhido x periodo anterior (mesmo tamanho): custo de HE e receita somados e a variacao %. Valor None quando falta algum mes de dado."""
    he = {x["mes"]: x.get("he") for x in serie_he}
    rec = {x["mes"]: x["receita"] for x in serie_receita}
    atual = PER.meses_entre(mes_ini, mes_fim)
    ant = PER.meses_entre(*PER.anterior(mes_ini, mes_fim))
    out = {"meses_atual": atual, "meses_anterior": ant}
    for nome, d in (("he", he), ("receita", rec)):
        a, b = _soma(d, atual), _soma(d, ant)
        out[nome + "_atual"], out[nome + "_anterior"] = a, b
        out["var_" + nome] = round(a / b - 1, 4) if a is not None and b else None
    return out
