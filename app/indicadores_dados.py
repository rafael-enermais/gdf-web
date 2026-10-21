# -*- coding: utf-8 -*-
"""GDF V2 - indicadores financeiros e financiamentos do Painel da Diretoria (so' leitura, tudo do Sienge ja' gravado em pnl_*).
Sem streamlit: so' SQL + contas simples (testavel). Regras (combinadas com a contabilidade em 20/10/2026):
  - PMR / PMP: prazo entre emissao e vencimento, simples (media) e ponderado pelo valor; sem documentos de previsao, sem titulos desfeitos.
  - Ciclo financeiro = PMR - PMP (negativo = recebe antes de pagar). Necessidade de capital de giro = gasto diario x ciclo (so' quando positivo).
  - Capital de giro: gasto = baixas a pagar em dinheiro do mes (pagamento, adiantamento, pagamento via movimento bancario), sem previsao.
  - Inadimplencia: titulos vencidos e ainda nao pagos NA DATA DE POSICAO (hoje, ou fim do mes escolhido), sem previsao. O vencimento usado e' o
    ORIGINAL do Sienge quando a coluna existe (renegociacao nao esconde a divida); senao o vencimento do titulo.
  - Fornecedores de verdade (21/10/2026, Rafael): por padrao PMR/PMP e gasto IGNORAM o que nao e' operacao com fornecedor/cliente: lancamentos sem credor/cliente e os
    de movimento bancario/caixa (transferencias, tarifas), titulos de financiamento/capital de giro (planos 2.03 e 2.05) e operacoes com empresas do grupo ENERMAIS
    (grupo_enermais.py). A caixa "incluir tudo" volta ao calculo anterior para comparar. Dias saem em numero inteiro.
  - Financiamentos: planos 2.03.02 (juros), 2.03.04 (capital de giro bancario) e os planos 2.05 que a contabilidade separou (PLANOS_2_05_FINANCIAMENTO). Saldo = parcelas ainda nao pagas.
  - Investimentos (aba a parte, 13/10/2026 -> 20/10/2026): o restante do 2.05 ja' puxado. O contrato vai para o grupo do seu principal; os juros (2.03.02) seguem o contrato.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

import painel_db as P
from fuso import agora_br
from grupo_enermais import nucleos_do_grupo, sql_nucleo

# baixas a pagar que sao saida de caixa: 1 Pagamento, 10 Adiantamento, 1002 Movimento bancario: Pagamento (cancelamento/substituicao/abatimento nao sao dinheiro; 1030 e' transferencia)
TIPOS_CAIXA_PAGAR = (1, 10, 1002)
PLANO_JUROS = "2.03.02"
PLANOS_2_05_FINANCIAMENTO = ("2.05.01.01", "2.05.01.03.02", "2.05.01.03.04", "2.05.01.03.06", "2.05.01.03.07")   # contabilidade: so' estes do 2.05 sao financiamentos
PLANOS_PRINCIPAL = ("2.03.04", "2.05")
PLANOS_FINANCIAMENTO = (PLANO_JUROS,) + PLANOS_PRINCIPAL
GRUPOS = ("financiamentos", "investimentos")


def _sob_plano(cod: str, base: str) -> bool:
    return cod == base or cod.startswith(base + ".")


def grupo_do_plano(cod: str | None) -> str | None:
    """'financiamentos' ou 'investimentos' para uma linha de PRINCIPAL; None para os juros (2.03.02), que seguem o contrato."""
    cod = cod or ""
    if _sob_plano(cod, PLANO_JUROS):
        return None
    if _sob_plano(cod, "2.03.04") or any(_sob_plano(cod, p) for p in PLANOS_2_05_FINANCIAMENTO):
        return "financiamentos"
    return "investimentos"
PREFIXOS_SQL = " OR ".join(f"r.plano_cod LIKE '{p}%%'" for p in PLANOS_FINANCIAMENTO)


def _prev(incluir_previsao: bool) -> str:
    return "" if incluir_previsao else "AND COALESCE(upper(t.previsao),'') <> 'S'"


def _desfeitos() -> str:
    return P._filtro_distrato(True) + " " + P._filtro_desfeitos(True)


def _limites(mes: str) -> tuple:
    ano, m = int(mes[:4]), int(mes[5:7])
    ini = dt.date(ano, m, 1)
    fim = dt.date(ano, m, calendar.monthrange(ano, m)[1])
    return ini, fim, fim + dt.timedelta(days=1)


def _tem_coluna(conn, tabela: str, coluna: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s", (tabela, coluna))
        return cur.fetchone() is not None


def coluna_vencimento(conn) -> str:
    """Expressao SQL do vencimento para inadimplencia: o ORIGINAL quando a coluna existe (SQL-27), senao o vencimento atual.
    O Sienge nao expoe o vencimento original por API (testado: bulk-data, bills/installments e receivable-bills/installments so' trazem dueDate e baseDate);
    por isso o app guarda o PRIMEIRO vencimento que viu para cada titulo e nunca o sobrescreve."""
    if _tem_coluna(conn, "pnl_titulo", "data_vencimento_original"):
        return "COALESCE(t.data_vencimento_original, t.data_vencimento)"
    return "t.data_vencimento"


# ---------------------------------------------------------------- prazos medios, ciclo e capital de giro
ORIGENS_BANCO = ("BC", "CX")                    # lancamentos de banco/caixa (transferencias, tarifas): nao sao titulos de fornecedor/cliente
PLANOS_FINANCEIROS = ("2.03", "2.05")           # financiamento, juros, capital de giro e investimentos: emprestimo nao e' compra a prazo


def _so_fornecedores(grupo: list) -> tuple:
    """(sql, params) que tira do titulo `t` o que nao e' fornecedor/cliente: sem nome, banco/caixa, financiamento (so' a pagar) e empresas do grupo."""
    origens = ", ".join(f"'{o}'" for o in ORIGENS_BANCO)
    planos = " OR ".join(f"rf.plano_cod LIKE '{p}%%'" for p in PLANOS_FINANCEIROS)
    sql = (f"AND COALESCE(trim(t.contraparte_nome),'') <> '' AND COALESCE(upper(t.origem),'') NOT IN ({origens}) "
           f"AND NOT (t.lado='P' AND EXISTS (SELECT 1 FROM pnl_v_rateio rf WHERE rf.lado=t.lado AND rf.bill_id=t.bill_id AND rf.installment_id=t.installment_id AND ({planos}))) "
           f"AND {sql_nucleo('t.contraparte_nome')} <> ALL(%(grupo)s)")
    return sql, {"grupo": list(grupo) or ["(sem grupo)"]}


def _limites_periodo(mes_ini: str, mes_fim: str) -> tuple:
    ini, _, _ = _limites(mes_ini)
    _, fim, prox = _limites(mes_fim)
    return ini, fim, prox


def prazo_medio(conn, lado: str, mes: str, acumulado: bool = False, mes_ini: str | None = None, completo: bool = False) -> dict:
    """Prazo medio (dias entre emissao e vencimento) dos titulos EMITIDOS entre `mes_ini` e `mes` (so' o mes; ou de janeiro quando acumulado=True).
    Padrao: so' fornecedores/clientes de verdade (veja o topo do arquivo); completo=True conta tudo. Dias em numero inteiro.
    -> {'n','simples','ponderado','n_fora'} (n_fora = titulos que ficaram de fora; simples/ponderado None se nao ha titulos)."""
    if mes_ini is None:
        mes_ini = f"{mes[:4]}-01" if acumulado else mes
    ini, _, prox = _limites_periodo(mes_ini, mes)
    filtro, par = ("", {}) if completo else _so_fornecedores(nucleos_do_grupo(conn))
    par.update({"lado": lado, "ini": ini, "prox": prox})
    with conn.cursor() as cur:
        cur.execute(f"""SELECT count(*) FILTER (WHERE ok), avg(d) FILTER (WHERE ok), sum(d * v) FILTER (WHERE ok) / NULLIF(sum(v) FILTER (WHERE ok), 0), count(*) FILTER (WHERE NOT ok)
                        FROM (SELECT GREATEST(t.data_vencimento - t.data_emissao, 0)::float AS d, t.valor_original::float AS v,
                                     (true {filtro}) AS ok
                              FROM pnl_titulo t
                              WHERE t.lado=%(lado)s AND t.data_emissao >= %(ini)s AND t.data_emissao < %(prox)s AND t.data_vencimento IS NOT NULL AND t.valor_original > 0
                                {_prev(False)} {_desfeitos()}) x""", par)
        n, simples, pond, fora = cur.fetchone()
    return {"n": int(n or 0), "n_fora": int(fora or 0), "simples": None if simples is None else int(round(float(simples))),
            "ponderado": None if pond is None else int(round(float(pond)))}


def gasto_pago(conn, mes: str, hoje: dt.date | None = None, mes_ini: str | None = None, completo: bool = False) -> dict:
    """Gasto do periodo (`mes_ini` a `mes`; padrao so' o mes) = baixas a pagar em dinheiro, sem previsao; por padrao so' com fornecedores de verdade (como os prazos).
    Diario = total / dias (no periodo em andamento, dias decorridos ate hoje). {'mensal' (= total do periodo), 'total', 'diario', 'dias'}."""
    mes_ini = mes_ini or mes
    ini, fim, prox = _limites_periodo(mes_ini, mes)
    filtro, par = ("", {}) if completo else _so_fornecedores(nucleos_do_grupo(conn))
    par.update({"ini": ini, "prox": prox})
    with conn.cursor() as cur:
        cur.execute(f"""SELECT COALESCE(sum(b.liquido), 0) FROM pnl_v_baixa b
                        LEFT JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
                        WHERE b.lado='P' AND b.tipo_oper_id IN {TIPOS_CAIXA_PAGAR} AND b.data_pagamento >= %(ini)s AND b.data_pagamento < %(prox)s
                          {_prev(False)} {filtro}""", par)
        total = float(cur.fetchone()[0] or 0)
    hoje = hoje or agora_br().date()
    ate = fim if hoje > fim else max(hoje, ini)
    dias = (ate - ini).days + 1
    return {"mensal": round(total, 2), "total": round(total, 2), "diario": round(total / dias, 2) if dias else 0.0, "dias": dias}


def ciclo_e_capital(conn, mes: str, acumulado: bool = False, hoje: dt.date | None = None, mes_ini: str | None = None, completo: bool = False) -> dict:
    """PMR, PMP, ciclo (PMR - PMP) e necessidade de capital de giro nos cenarios simples e ponderado (dias inteiros; NCG = gasto diario x ciclo, so' se positivo)."""
    if mes_ini is None:
        mes_ini = f"{mes[:4]}-01" if acumulado else mes
    pmr = prazo_medio(conn, "R", mes, mes_ini=mes_ini, completo=completo)
    pmp = prazo_medio(conn, "P", mes, mes_ini=mes_ini, completo=completo)
    gasto = gasto_pago(conn, mes, hoje, mes_ini=mes_ini, completo=completo)
    out = {"pmr": pmr, "pmp": pmp, "gasto": gasto, "completo": completo, "mes_ini": mes_ini, "mes_fim": mes}
    for cen in ("simples", "ponderado"):
        r, p = pmr[cen], pmp[cen]
        ciclo = None if r is None or p is None else r - p
        out["ciclo_" + cen] = ciclo
        out["ncg_" + cen] = None if ciclo is None else round(gasto["diario"] * max(ciclo, 0), 2)
    return out


# ---------------------------------------------------------------- inadimplencia e receitas em aberto
FAIXAS = (("1 a 30 dias", 1, 30), ("31 a 60 dias", 31, 60), ("61 a 90 dias", 61, 90), ("Mais de 90 dias", 91, 10 ** 6))


def _sem_clientes_do_grupo(completo: bool) -> str:
    """Tira do A RECEBER os clientes que sao empresas do grupo ENERMAIS (nao e' cobranca de cliente de verdade). Usa o parametro %(grupo)s."""
    return "" if completo else f"AND NOT (t.lado='R' AND {sql_nucleo('t.contraparte_nome')} = ANY(%(grupo)s))"


def _abertos_sql(venc: str, incluir_previsao: bool, completo: bool = True) -> str:
    """CTE comum: titulos vencidos (vencimento <= %(venc_ate)s) e ainda nao quitados ate %(pago_ate)s, com o valor em aberto."""
    return f"""WITH pg AS (SELECT lado, bill_id, installment_id, sum(bruto) AS v FROM pnl_v_baixa WHERE data_pagamento <= %(pago_ate)s GROUP BY 1,2,3)
               SELECT t.lado, t.contraparte_nome, t.numero_doc, {venc} AS venc, t.valor_original - COALESCE(pg.v, 0) AS aberto
               FROM pnl_titulo t LEFT JOIN pg ON pg.lado=t.lado AND pg.bill_id=t.bill_id AND pg.installment_id=t.installment_id
               WHERE t.lado IN ('P','R') AND {venc} <= %(venc_ate)s AND t.valor_original - COALESCE(pg.v, 0) > 0.01
                 {_prev(incluir_previsao)} {_desfeitos()} {_sem_clientes_do_grupo(completo)}"""


def data_posicao(mes: str, hoje: dt.date | None = None, ate_hoje: bool = True) -> tuple:
    """(venc_ate, pago_ate) da posicao. Ao vivo ('ate hoje'): vence ate ontem, pago ate hoje (o que vence hoje ainda esta no prazo).
    Fim do mes: ambos o ultimo dia do mes escolhido."""
    hoje = hoje or agora_br().date()
    if ate_hoje:
        return hoje - dt.timedelta(days=1), hoje
    _, fim, _ = _limites(mes)
    return fim, fim


def inadimplencia(conn, venc_ate: dt.date, pago_ate: dt.date, incluir_previsao: bool = False, topo: int = 15, completo: bool = False) -> dict:
    """Vencidos e nao pagos na posicao: totais a receber e a pagar, por faixa de atraso e por cliente/credor. Por padrao o a receber nao inclui clientes do grupo ENERMAIS."""
    venc = coluna_vencimento(conn)
    with conn.cursor() as cur:
        cur.execute(_abertos_sql(venc, incluir_previsao, completo), {"venc_ate": venc_ate, "pago_ate": pago_ate, "grupo": nucleos_do_grupo(conn) or ["(sem grupo)"]})
        linhas = cur.fetchall()
    out = {"venc_ate": venc_ate, "pago_ate": pago_ate, "usa_vencimento_original": venc.startswith("COALESCE")}
    for lado, nome in (("R", "receber"), ("P", "pagar")):
        sel = [l for l in linhas if l[0] == lado]
        total = round(sum(float(l[4]) for l in sel), 2)
        faixas = []
        for rot, a, b in FAIXAS:
            f = [l for l in sel if a <= (venc_ate - l[3]).days + 1 <= b]
            faixas.append({"faixa": rot, "n": len(f), "valor": round(sum(float(l[4]) for l in f), 2)})
        por = {}
        for _, ct, _, v, ab in sel:
            d = por.setdefault(ct or "(sem nome)", {"nome": ct or "(sem nome)", "n": 0, "valor": 0.0, "mais_antigo": v})
            d["n"] += 1
            d["valor"] = round(d["valor"] + float(ab), 2)
            d["mais_antigo"] = min(d["mais_antigo"], v)
        top = sorted(por.values(), key=lambda d: -d["valor"])[:topo]
        out[nome] = {"total": total, "n": len(sel), "faixas": faixas, "top": top}
    return out


def receitas_em_aberto(conn, pago_ate: dt.date, incluir_previsao: bool = False, limite: int = 500, completo: bool = False) -> list:
    """Contas a receber ainda nao recebidas na posicao (vencidas e a vencer): cliente, nota, vencimento (original quando existe), valor em aberto.
    Por padrao sem clientes do grupo ENERMAIS (completo=True mostra todos)."""
    venc = coluna_vencimento(conn)
    sql = f"""WITH pg AS (SELECT lado, bill_id, installment_id, sum(bruto) AS v FROM pnl_v_baixa WHERE data_pagamento <= %s GROUP BY 1,2,3)
              SELECT t.contraparte_nome, t.numero_doc, {venc} AS venc, t.valor_original - COALESCE(pg.v, 0) AS aberto
              FROM pnl_titulo t LEFT JOIN pg ON pg.lado=t.lado AND pg.bill_id=t.bill_id AND pg.installment_id=t.installment_id
              WHERE t.lado='R' AND t.valor_original - COALESCE(pg.v, 0) > 0.01 {_prev(incluir_previsao)} {_desfeitos()} {_sem_clientes_do_grupo(completo)}
              ORDER BY venc NULLS LAST, t.contraparte_nome LIMIT %(limite)s"""
    sql = sql.replace("data_pagamento <= %s", "data_pagamento <= %(pago_ate)s")
    with conn.cursor() as cur:
        cur.execute(sql, {"pago_ate": pago_ate, "limite": limite, "grupo": nucleos_do_grupo(conn) or ["(sem grupo)"]})
        return [{"cliente": c or "(sem nome)", "nota": n or "", "vencimento": v, "valor": round(float(a), 2), "atraso": max((pago_ate - v).days, 0) if v else 0}
                for c, n, v, a in cur.fetchall()]


# ---------------------------------------------------------------- financiamentos
_RE_CONTRATO = re.compile(r"(?:\bct\b\.?|\bcontrato\b|\bcont\b\.?)\s*[:nº°.\s]*(\d[\d./-]{2,})", re.I)


def chave_contrato(plano_nome: str | None, plano_cod: str | None = None) -> str:
    """Numero do contrato dentro do nome do plano ('... Ct 38172', '... Contrato 300200'); sem numero, usa o proprio plano (codigo + nome)."""
    m = _RE_CONTRATO.search(plano_nome or "")
    if m:
        return re.sub(r"\D", "", m.group(1)) or (plano_nome or "").strip()
    return f"{plano_cod or ''} {plano_nome or ''}".strip()


_RE_VEICULO = re.compile(r"\b(caminh\w*|ve[ií]culo\w*|carro|van|pickup|hilux|strada|mobi|toro|bmw|nivus|placa)\b")
_RE_MAQUINA = re.compile(r"\b(maquin\w*|máquin\w*|equipament\w*|retro\w*|munk|guindaste|trator)\b")
_RE_IMOVEL = re.compile(r"\b(sala|im[óo]ve\w*|obras?|reforma\w*|mob[ií]lia|terreno)\b")


def classificar(plano_cod: str | None, plano_nome: str | None) -> tuple:
    """(categoria, objeto) do financiamento a partir do plano de contas e do nome. A contabilidade pode refinar depois (de-para por contrato)."""
    cod, nome = plano_cod or "", (plano_nome or "").strip()
    baixo = nome.lower()
    limpo = re.sub(r"\s*[-|]?\s*(?:fin\.?|financiamento)?\s*(?:ct\.?|contrato)\s*[:nº°.\s]*\d[\d./-]*\s*$", "", nome, flags=re.I).strip(" -|") or nome
    if cod.startswith("2.03.04"):
        return "Capital de giro", limpo
    if cod.startswith(PLANO_JUROS):
        return "Juros de financiamento", limpo
    if cod.startswith("2.05.03"):
        return "Aporte de capital", limpo
    if _RE_VEICULO.search(baixo):
        return "Veículo", limpo
    if _RE_MAQUINA.search(baixo):
        return "Máquinas e equipamentos", limpo
    if _RE_IMOVEL.search(baixo):
        return "Imóveis e obras", limpo
    if cod.startswith("2.05.01.01"):
        return "Veículo", limpo
    if cod.startswith("2.05.01.03"):
        return "Máquinas e equipamentos", limpo
    if cod.startswith("2.05.01.02"):
        return "Imóveis e obras", limpo
    return "Outros financiamentos", limpo


CATEGORIAS_FIN = ("Capital de giro", "Veículo", "Máquinas e equipamentos", "Imóveis e obras", "Aporte de capital", "Outros financiamentos")


def _meses_ate(hoje: dt.date, venc: dt.date) -> int:
    return max(1, (venc.year - hoje.year) * 12 + (venc.month - hoje.month))


def financiamentos(conn, hoje: dt.date | None = None, incluir_previsao: bool = False, grupo: str = "financiamentos") -> dict:
    """Carteira na data: KPIs, por credor, por contrato e curva mensal de desembolso. Valores = parcelas ainda nao pagas ate `hoje`.
    grupo: 'financiamentos' (padrao) ou 'investimentos' (o 2.05 que nao foi separado como financiamento). O contrato fica no grupo do seu principal;
    com principal nos dois, prevalece financiamentos; contrato so' de juros fica em financiamentos."""
    if grupo not in GRUPOS:
        raise ValueError("grupo deve ser financiamentos ou investimentos")
    hoje = hoje or agora_br().date()
    sql = f"""WITH pg AS (SELECT lado, bill_id, installment_id, sum(bruto) AS v FROM pnl_v_baixa WHERE data_pagamento <= %s GROUP BY 1,2,3)
              SELECT t.bill_id, t.installment_id, t.contraparte_nome, t.data_vencimento, t.valor_original, COALESCE(pg.v, 0), r.plano_cod, r.plano_nome, r.percentual
              FROM pnl_titulo t JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
              LEFT JOIN pg ON pg.lado=t.lado AND pg.bill_id=t.bill_id AND pg.installment_id=t.installment_id
              WHERE t.lado='P' AND ({PREFIXOS_SQL}) {_prev(incluir_previsao)} {_desfeitos()}"""
    with conn.cursor() as cur:
        cur.execute(sql, (hoje,))
        linhas = cur.fetchall()
    contratos = {}
    for bill, inst, credor, venc, valor, pago, cod, nome, pct in linhas:
        valor, pago, pct = float(valor or 0), float(pago or 0), float(pct or 0)
        rateio = valor * pct / 100.0
        aberto = rateio * (max(valor - pago, 0.0) / valor) if valor > 0 else 0.0
        eh_juros = (cod or "").startswith(PLANO_JUROS)
        chave = chave_contrato(nome, cod)
        c = contratos.setdefault(chave, {"chave": chave, "credores": {}, "docs": set(), "principal_total": 0.0, "principal_aberto": 0.0, "juros_aberto": 0.0,
                                         "parcelas_abertas": set(), "venc_abertos": [], "base": 0.0, "categoria": None, "objeto": None, "grupos": set(), "curva": {}})
        if credor:
            c["credores"][credor] = c["credores"].get(credor, 0.0) + max(rateio, 0.0)
        if not eh_juros:
            c["grupos"].add(grupo_do_plano(cod))
            c["principal_total"] += rateio
            if c["categoria"] is None or c["categoria"] == "Juros de financiamento":
                c["categoria"], c["objeto"] = classificar(cod, nome)
        elif c["categoria"] is None:
            c["categoria"], c["objeto"] = classificar(cod, nome)
        if aberto > 0.004:
            c["docs"].add(bill)
            c["parcelas_abertas"].add((bill, inst))
            if venc:
                c["venc_abertos"].append(venc)
            if eh_juros:
                c["juros_aberto"] += aberto
            else:
                c["principal_aberto"] += aberto
                if venc:
                    c["base"] += aberto * _meses_ate(hoje, venc)
            if venc:
                mes = f"{venc.year:04d}-{venc.month:02d}"
                d = c["curva"].setdefault(mes, {"principal": 0.0, "juros": 0.0})
                d["juros" if eh_juros else "principal"] += aberto
    lista = []
    manual = P.fin_bem_listar(conn)                  # "o que e" definido por uma pessoa (SQL-26); vale mais que a sugestao automatica
    curva = {}
    for c in contratos.values():
        if c["principal_aberto"] + c["juros_aberto"] <= 0.004:
            continue
        if ("investimentos" if c["grupos"] == {"investimentos"} else "financiamentos") != grupo:
            continue
        for mes, d0 in c["curva"].items():
            d = curva.setdefault(mes, {"principal": 0.0, "juros": 0.0})
            d["principal"] += d0["principal"]
            d["juros"] += d0["juros"]
        credor = max(c["credores"], key=c["credores"].get) if c["credores"] else "(sem credor)"
        sugestao_cat, sugestao_obj = c["categoria"] or "Outros financiamentos", c["objeto"] or c["chave"]
        m = manual.get(c["chave"])
        implicita = round(c["juros_aberto"] / c["base"], 4) if c["base"] > 0 and c["juros_aberto"] > 0 else None
        taxa_cad = m["taxa_mensal"] / 100.0 if m and m.get("taxa_mensal") is not None else None          # cadastro guarda em % ao mes
        lista.append({"chave": c["chave"], "grupo": grupo, "credor": credor, "categoria": (m["categoria"] if m and m["categoria"] else sugestao_cat),
                      "objeto": (m["objeto"] or sugestao_obj) if m else sugestao_obj, "observacao": m["observacao"] if m else None,
                      "origem": "Cadastro" if m and (m["categoria"] or m["objeto"]) else "Sugestão", "sugestao": sugestao_cat,
                      "taxa_contrato": taxa_cad, "taxa_implicita": implicita,
                      "documentos": len(c["docs"]), "parcelas": len(c["parcelas_abertas"]), "principal_total": round(c["principal_total"], 2),
                      "principal": round(c["principal_aberto"], 2), "juros": round(c["juros_aberto"], 2),
                      "proximo": min(c["venc_abertos"]) if c["venc_abertos"] else None, "encerramento": max(c["venc_abertos"]) if c["venc_abertos"] else None,
                      "taxa_mensal": taxa_cad if taxa_cad is not None else implicita, "taxa_origem": "Contrato" if taxa_cad is not None else ("Implícita" if implicita is not None else None)})
    lista.sort(key=lambda d: -(d["principal"] + d["juros"]))
    saldo = round(sum(d["principal"] for d in lista), 2)
    juros = round(sum(d["juros"] for d in lista), 2)
    por_credor = {}
    for d in lista:
        a = por_credor.setdefault(d["credor"], {"credor": d["credor"], "contratos": 0, "principal": 0.0, "juros": 0.0, "pxt": 0.0, "pbase": 0.0, "encerramento": None})
        a["contratos"] += 1
        a["principal"] = round(a["principal"] + d["principal"], 2)
        a["juros"] = round(a["juros"] + d["juros"], 2)
        if d["taxa_mensal"] is not None and d["principal"] > 0:           # taxa do credor = media das taxas dos contratos ponderada pelo saldo
            a["pxt"] += d["taxa_mensal"] * d["principal"]
            a["pbase"] += d["principal"]
        if d["encerramento"] and (a["encerramento"] is None or d["encerramento"] > a["encerramento"]):
            a["encerramento"] = d["encerramento"]
    credores = []
    for a in por_credor.values():
        a["pct_carteira"] = round(a["principal"] / saldo, 4) if saldo else None
        a["taxa_mensal"] = round(a["pxt"] / a["pbase"], 4) if a["pbase"] > 0 else None
        a.pop("pxt")
        a.pop("pbase")
        credores.append(a)
    credores.sort(key=lambda a: -a["principal"])
    fins = [d["encerramento"] for d in lista if d["encerramento"]]
    com_taxa = [d for d in lista if d["taxa_contrato"] is not None and d["principal"] > 0]
    if com_taxa:                          # contabilidade (20/10/2026): custo medio pela TAXA DE CADA CONTRATO quando houver; media ponderada pelo saldo
        custo = round(sum(d["taxa_contrato"] * d["principal"] for d in com_taxa) / sum(d["principal"] for d in com_taxa), 4)
        custo_origem = f"taxa cadastrada de {len(com_taxa)} de {len(lista)} contratos, ponderada pelo saldo"
    else:
        custo, custo_origem = (round(juros / saldo, 4) if saldo else None), "juros ÷ saldo devedor (sem taxa de contrato cadastrada)"
    return {"hoje": hoje, "grupo": grupo, "saldo_devedor": saldo, "juros_totais": juros, "desembolso_total": round(saldo + juros, 2), "contratos": len(lista),
            "documentos": sum(d["documentos"] for d in lista), "custo_medio": custo, "custo_medio_origem": custo_origem,
            "encerramento_mais_longo": max(fins) if fins else None, "por_contrato": lista, "por_credor": credores,
            "curva": [{"mes": m, "principal": round(v["principal"], 2), "juros": round(v["juros"], 2)} for m, v in sorted(curva.items())]}


def cobertura_abertos(conn):
    """Quando rodou a ultima carga SEMANAL de titulos em aberto por vencimento (None se nunca rodou): sem ela, vencidos antigos e contratos
    anteriores a janela da rotina diaria (365 dias) podem faltar."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(finalizado_em) FROM pnl_sync WHERE status='OK' AND tipo_data='D' AND lado='P'")
        return cur.fetchone()[0]
