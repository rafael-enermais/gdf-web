# -*- coding: utf-8 -*-
"""
GDF - monta as tabelas de exibicao (Balanco, DRE, Indicadores) a partir do resultado do motor.
Modulo puro (pandas, sem streamlit/db): cada tabela e' um DataFrame de TEXTO ja formatado em padrao brasileiro,
mais a lista de linhas "de secao/total" para o estilo. Mesma ordem e rotulos do Excel da contadora (agosto/2026).
"""
from __future__ import annotations

import pandas as pd

import formatacao as F
import motor

# (rotulo, id do motor | None para titulo de secao, tipo: 'item' | 'total' | 'secao')
BP_ATIVO_LINHAS = [
    ("Ativo circulante", None, "secao"),
    (None, "dep_vista", "item"), (None, "aplic", "item"), (None, "caixa_eq", "total"),
    (None, "adiant", "item"), (None, "trib_rec", "item"), (None, "desp_ant_cp", "item"), (None, "ac", "total"),
    ("Ativo não circulante", None, "secao"),
    (None, "dep_jud", "item"), (None, "desp_ant_lp", "item"), (None, "rlp", "total"),
    (None, "conc_bruto", "item"), (None, "conc_red", "item"), (None, "conc_liq", "total"),
    (None, "anc", "total"), (None, "ativo", "total"),
]
BP_PASSIVO_LINHAS = [
    ("Passivo circulante", None, "secao"),
    (None, "bndes_cp", "item"), (None, "fornec", "item"), (None, "prov_constr", "item"), (None, "imp_rec", "item"),
    (None, "trib_ret", "item"), (None, "pc", "total"),
    ("Passivo não circulante", None, "secao"),
    (None, "bndes_lp", "item"), (None, "trib_dif", "item"), (None, "pnc", "total"),
    ("Patrimônio líquido", None, "secao"),
    (None, "capital", "item"), (None, "afac", "item"), (None, "res_legal", "item"), (None, "res_ret", "item"),
    (None, "prej", "item"), (None, "pl", "total"), (None, "passivo_pl", "total"),
]
DRE_LINHAS_EXIBIR = [
    (None, "pis", "item"), (None, "cofins", "item"), (None, "deducoes", "total"), (None, "rec_liq", "total"),
    (None, "custo_constr", "item"), (None, "fretes", "item"), (None, "custos_serv", "total"), (None, "res_bruto", "total"),
    ("Despesas operacionais", None, "secao"),
    (None, "serv_prof", "item"), (None, "cartorio", "item"), (None, "seguro", "item"), (None, "importacao", "item"),
    (None, "ajustes", "item"), (None, "desp_adm", "total"), (None, "ebit", "total"),
    ("Resultado financeiro", None, "secao"),
    (None, "rend_aplic", "item"), (None, "rec_nt", "item"), (None, "descontos", "item"), (None, "rec_fin", "total"),
    (None, "desp_banc", "item"), (None, "juros", "item"), (None, "desp_fin", "total"), (None, "res_fin", "total"),
    (None, "res_antes_ir", "total"), (None, "ir_cs", "item"), (None, "res_liq", "total"),
]
# (rotulo, chave do motor, formato, formula) ; None = titulo de grupo
INDICADORES_LINHAS = [
    ("Liquidez", None, None, None),
    ("Liquidez corrente", "liq_corrente", "x", "Ativo circulante ÷ Passivo circulante"),
    ("Liquidez imediata", "liq_imediata", "x", "Caixa e equivalentes ÷ Passivo circulante"),
    ("Liquidez geral", "liq_geral", "x", "(AC + Realizável LP) ÷ (PC + PNC)"),
    ("Capital circulante líquido (R$)", "ccl", "R$", "Ativo circulante − Passivo circulante"),
    ("Endividamento bancário", None, None, None),
    ("Dívida bruta (R$)", "div_bruta", "R$", "Empréstimos BNDES curto + longo prazo"),
    ("(−) Caixa e equivalentes (R$)", "caixa_neg", "R$", "Disponibilidades + aplicações de liquidez imediata"),
    ("Dívida líquida (R$)", "div_liquida", "R$", "Dívida bruta − Caixa e equivalentes"),
    ("Dívida de curto prazo / Dívida bruta", "div_cp_sobre_bruta", "%", "Parcela da dívida com vencimento em até 12 meses"),
    ("Dívida bruta / Ativo total", "div_bruta_ativo", "%", "Participação do financiamento no ativo"),
    ("Dívida líquida / Ativo de concessão líquido", "div_liq_sobre_concessao", "%", "Alavancagem sobre o principal ativo da SPE"),
    ("Estrutura de capital", None, None, None),
    ("Endividamento geral", "endiv_geral", "%", "(PC + PNC) ÷ Ativo total"),
    ("Composição do endividamento (CP)", "comp_endiv_cp", "%", "PC ÷ (PC + PNC)"),
    ("Patrimônio líquido / Ativo total", "pl_ativo", "%", "Participação de capital próprio"),
    ("Capital aportado pelos sócios (R$)", "capital_aportado", "R$", "Capital social + AFAC"),
    ("Resultado (acumulado no ano)", None, None, None),
    ("Resultado financeiro líquido (R$)", "res_fin", "R$", "Receitas − despesas financeiras (acumulado do ano)"),
    ("EBIT / EBITDA (R$)", "ebit_ebitda", "R$", "Sem depreciação/amortização no período: EBITDA = EBIT"),
    ("Resultado líquido (R$)", "res_liq", "R$", "Resultado líquido acumulado do ano"),
]


def _fmt(kind, v):
    return {"x": F.razao_br, "%": F.pct_br, "R$": F.num_br}[kind](v)


def _rotulo(lid, rot):
    return rot if rot is not None else motor.ROTULOS.get(lid, lid)


def _data_fim_mes(chave: str) -> str:
    import calendar
    a, m = int(chave[:4]), int(chave[5:7])
    return f"{calendar.monthrange(a, m)[1]:02d}/{m:02d}/{a}"


ND = "n/d"          # coluna que não pôde ser calculada (faltam balancetes): sempre explicado em "O que falta"


def _col_mes_ant(mes_ant: str, mes_ref: str) -> str:
    """Rótulo da coluna do mês anterior. Em janeiro o mês anterior é dezembro (= a abertura): o rótulo precisa ser diferente do da abertura, senão o Streamlit quebra."""
    return _data_fim_mes(mes_ant) if mes_ant != mes_ref else "Mês anterior (= abertura)"


def _v(col, lid):
    """Valor de uma linha numa coluna do Balanço/DRE; None quando a coluna inteira não pôde ser calculada."""
    return None if col is None else col[lid]


def _nd(col, lid):
    return ND if col is None else F.num_br(col[lid])


def tabela_balanco(bp: dict, mes_ref: str, mes_ant: str):
    """Duas tabelas (ativo, passivo+PL). Colunas: 31/12 anterior, mes anterior, mes atual, Var R$ e Var % (abertura -> atual)."""
    ano_ant = int(mes_ref[:4]) - 1
    cols = [f"31/12/{ano_ant}", _col_mes_ant(mes_ant, mes_ref), _data_fim_mes(mes_ref), "Var. R$", "Var. %"]
    out = []
    for titulo, linhas in (("ATIVO", BP_ATIVO_LINHAS), ("PASSIVO E PATRIMÔNIO LÍQUIDO", BP_PASSIVO_LINHAS)):
        rows, estilos = [], []
        for rot, lid, tipo in linhas:
            if tipo == "secao":
                rows.append([rot, "", "", "", "", ""]); estilos.append("secao"); continue
            a, m, r = _v(bp["abertura"], lid), _v(bp["mes_ant"], lid), _v(bp["mes_ref"], lid)
            rows.append([_rotulo(lid, rot), _nd(bp["abertura"], lid), _nd(bp["mes_ant"], lid), _nd(bp["mes_ref"], lid),
                         ND if a is None or r is None else F.num_br(r - a), ND if a is None or r is None else F.var_pct(r, a)])
            estilos.append(tipo)
        df = pd.DataFrame(rows, columns=[titulo] + cols)
        out.append((df, estilos))
    return out


def tabela_dre(d: dict, mes_ref: str):
    ano, mes = mes_ref[:4], int(mes_ref[5:7])
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    c1 = f"Jan–{meses[mes - 2].capitalize()}/{ano}" if mes > 1 else "—"
    cols = [c1, f"{meses[mes - 1].capitalize()}/{ano}", f"Acumulado Jan–{meses[mes - 1].capitalize()}/{ano}"]
    rows, estilos = [], []
    for rot, lid, tipo in DRE_LINHAS_EXIBIR:
        if tipo == "secao":
            rows.append([rot, "", "", ""]); estilos.append("secao"); continue
        rows.append([_rotulo(lid, rot), (_nd(d["ate_mes_ant"], lid) if mes > 1 else "–"), _nd(d["mes"], lid), _nd(d["acumulado"], lid)])
        estilos.append(tipo)
    return pd.DataFrame(rows, columns=["Demonstração do Resultado"] + cols), estilos


def tabela_indicadores(bp: dict, d: dict, mes_ref: str, mes_ant: str):
    ano_ant = int(mes_ref[:4]) - 1
    cols = [f"31/12/{ano_ant}", _col_mes_ant(mes_ant, mes_ref), _data_fim_mes(mes_ref)]
    i0 = motor.indicadores(bp["abertura"], None)
    i1 = motor.indicadores(bp["mes_ant"], d["ate_mes_ant"])
    i2 = motor.indicadores(bp["mes_ref"], d["acumulado"])
    rows, estilos = [], []
    resultado = ("res_fin", "ebit_ebitda", "res_liq")
    def cel(i, chave, kind, bpc, dre_col, abertura=False):
        if bpc is None or (chave in resultado and dre_col is None and not abertura):
            return ND                                          # coluna sem dados: não dá para calcular (diferente de "–" = divisão por zero)
        return _fmt(kind, i[chave])
    for rot, chave, kind, formula in INDICADORES_LINHAS:
        if chave is None:
            rows.append([rot, "", "", "", ""]); estilos.append("secao"); continue
        rows.append([rot, cel(i0, chave, kind, bp["abertura"], None, True), cel(i1, chave, kind, bp["mes_ant"], d["ate_mes_ant"]),
                     cel(i2, chave, kind, bp["mes_ref"], d["acumulado"]), formula]); estilos.append("item")
    return pd.DataFrame(rows, columns=["Indicador"] + cols + ["Fórmula"]), estilos


def estilizar(df: pd.DataFrame, estilos: list):
    """Styler: totais/secoes em negrito, negativos em laranja (padrao de layout)."""
    def linha(row):
        i = row.name
        base = "font-weight:700;" if estilos[i] in ("total", "secao") else ""
        if estilos[i] == "secao":
            base += "background-color:rgba(100,110,160,0.18);"
        return [base + (f"color:{F.COR_NEG};" if isinstance(v, str) and v.startswith(F.MENOS) else "") for v in row]
    return df.style.apply(linha, axis=1)
