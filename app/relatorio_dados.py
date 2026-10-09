# -*- coding: utf-8 -*-
"""
GDF - prepara os dados do relatorio PDF a partir do motor (Balanco, DRE, indicadores, serie mensal, composicao de saldos)
e os TEXTOS DE LEITURA padrao (modelos deterministas preenchidos com os valores; a contadora pode editar antes de gerar).
Modulo puro (sem banco, sem streamlit, sem reportlab).
"""
from __future__ import annotations

import calendar

import composicao
import motor
import tabelas
from relatorio_fmt import brl, fnum, mm, pct, razao

MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_EXT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Slot por empresa (so' informacao publica). Assinantes ficam no banco (empresa.config), nao no codigo.
NOTA_CONCESSAO = ("A receita de construção e a receita de remuneração do ativo de contrato são reconhecidas ao final do exercício e/ou na entrada em operação "
                  "da obra de concessão. Por isso, o resultado intermediário reflete apenas os custos de construção incorridos no período, sem a respectiva receita, "
                  "e não é representativo do resultado anual da concessão.")
EMPRESAS_RELATORIO = {
    "54.800.488/0001-60": dict(curto="Anastácio", logo="anastacio.png",
                               tipo="SPE de transmissão de energia — ativo de concessão em construção", nota_resultado=NOTA_CONCESSAO),
}
KINDS = {"x": "x", "%": "p", "R$": "R"}
EXPLICACAO = {
    "liq_corrente": "Quanto há para receber/converter em até 12 meses para cada R$ 1,00 a pagar no mesmo prazo.",
    "liq_imediata": "Quanto há em caixa e aplicações para cada R$ 1,00 a pagar em até 12 meses.",
    "liq_geral": "Todos os recursos (curto e longo prazo) frente a todas as obrigações; o ativo de concessão não entra.",
    "ccl": "Sobra (ou falta) de recursos de curto prazo depois de pagar o que vence em até 12 meses.",
    "div_bruta": "Total devido ao BNDES, somando curto e longo prazo.",
    "caixa_neg": "Dinheiro disponível (caixa e aplicações de liquidez imediata).",
    "div_liquida": "Dívida bruta menos caixa: quanto da dívida não está coberto pelo caixa.",
    "div_cp_sobre_bruta": "Fatia da dívida que vence em até 12 meses.",
    "div_bruta_ativo": "Quanto do ativo total está financiado por dívida do BNDES.",
    "div_liq_sobre_concessao": "Dívida líquida em relação ao principal ativo da empresa (concessão).",
    "endiv_geral": "Obrigações totais em relação ao ativo; acima de 100% = obrigações maiores que o ativo.",
    "comp_endiv_cp": "Fatia das obrigações com vencimento em até 12 meses.",
    "pl_ativo": "Fatia do ativo financiada por capital dos sócios; negativo = prejuízos superam o capital.",
    "capital_aportado": "Capital social somado aos adiantamentos para futuro aumento de capital (AFAC).",
    "res_fin": "Receitas menos despesas financeiras, acumulado no ano.",
    "ebit_ebitda": "Sem depreciação/amortização no período, o EBITDA é igual ao EBIT.",
    "res_liq": "Resultado líquido acumulado no ano.",
}


def data_fim(mes: str) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    return f"{calendar.monthrange(a, m)[1]:02d}/{m:02d}/{a}"


def info_empresa(emp: dict, config: dict | None = None) -> dict:
    """Slot da empresa para o relatorio: razao social, CNPJ, nome curto, logo, tipo, nota e assinantes (do banco)."""
    base = EMPRESAS_RELATORIO.get(emp["cnpj"], {})
    cfg = config or {}
    curto = cfg.get("curto") or base.get("curto") or emp["razao_social"].split()[0].title()
    ass = [(a.get("nome", "").strip(), a.get("cargo", "").strip()) for a in (cfg.get("assinantes") or []) if isinstance(a, dict)]
    return {"nome": emp["razao_social"], "curto": curto, "cnpj": emp["cnpj"], "logo": cfg.get("logo") or base.get("logo"),
            "tipo": cfg.get("tipo") or base.get("tipo", ""), "nota_resultado": cfg.get("nota_resultado", base.get("nota_resultado", "")),
            "assinantes": ass or [("", "Administrador"), ("", "Contador")]}


def _linha(v0, v1, v2):
    var = round(v2 - v0, 2)
    return [v0, v1, v2, var, None if abs(v0) < 0.005 else var / abs(v0)]


def montar(emp: dict, b: motor.Balancetes, mes_ref: str, bp: dict, d: dict, contas_ref: list, apelidos=None, grupos=None,
           config: dict | None = None, mapa=None) -> dict:
    """Tudo que o gerador de PDF precisa (numeros prontos, sem calculo no desenho)."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    ordem = [m for m in b.ordem if m <= mes_ref]
    mes_ant = ordem[ordem.index(mes_ref) - 1] if ordem.index(mes_ref) > 0 else mes_ref
    rot = dict(motor.ROTULOS)
    rot.update({m[0]: m[1] for m in (mapa or [])})
    bpv = {k: _linha(bp["abertura"][k], bp["mes_ant"][k], bp["mes_ref"][k]) for k in bp["mes_ref"]}
    drv = {k: [d["ate_mes_ant"][k], d["mes"][k], d["acumulado"][k]] for k in d["acumulado"]}
    i0, i1, i2 = (motor.indicadores(bp["abertura"], None), motor.indicadores(bp["mes_ant"], d["ate_mes_ant"]),
                  motor.indicadores(bp["mes_ref"], d["acumulado"]))
    ind = {k: [i0[k], i1[k], i2[k]] for k in i2}
    # serie mensal: abertura (31/12 anterior) + cada mes ate' o de referencia
    def pontos(f_ab, f_m):
        return [f_ab] + [f_m(m) for m in ordem]
    sal = b.saldo
    def pl(m): return round(sum(sal(m, k) for k in ("capital", "afac", "res_legal", "res_ret", "prej")), 2)
    serie = {
        "meses": [MESES_ABREV[int(m[5:7]) - 1] for m in ordem],
        "rotulos": [f"Dez/{str(ano - 1)[2:]}"] + [f"{MESES_ABREV[int(m[5:7]) - 1]}/{str(ano)[2:]}" for m in ordem],
        "caixa": pontos(bp["abertura"]["caixa_eq"], lambda m: round(sal(m, "dep_vista") + sal(m, "aplic"), 2)),
        "bndes": pontos(round(bp["abertura"]["bndes_cp"] + bp["abertura"]["bndes_lp"], 2), lambda m: round(sal(m, "bndes_cp") + sal(m, "bndes_lp"), 2)),
        "pl": pontos(bp["abertura"]["pl"], pl),
        "fornec": pontos(bp["abertura"]["fornec"], lambda m: sal(m, "fornec")),
        "custo_constr": [-b.mov(m, "custo_constr") for m in ordem],
        "resultado_mes": [motor.dre(b, m)["mes"]["res_liq"] for m in ordem],
    }
    return {
        "empresa": info_empresa(emp, config), "mes_ref": mes_ref, "mes_ant": mes_ant, "ano": ano, "mes": mes,
        "data_base": data_fim(mes_ref), "data_ant": data_fim(mes_ant), "abertura": f"31/12/{ano - 1}",
        "data_base_ext": f"{calendar.monthrange(ano, mes)[1]} de {MESES_EXT[mes - 1]} de {ano}",
        "periodo": (f"Acumulado de janeiro a {MESES_EXT[mes - 1]} de {ano}" if mes > 1 else f"Janeiro de {ano}"),
        "periodo_curto": (f"JAN–{MESES_ABREV[mes - 1].upper()}/{ano}" if mes > 1 else f"JAN/{ano}"),
        "mes_nome": MESES_EXT[mes - 1], "mes_abrev": MESES_ABREV[mes - 1],
        "rot": rot, "bp": bpv, "dre": drv, "ind": ind, "serie": serie, "n_meses": len(ordem),
        "comp": composicao.calcular(contas_ref, grupos, apelidos),
        "ajustes": d["acumulado"]["ajustes"],
    }


# ------------------------------------------------------------------ textos de leitura (modelos preenchidos com os valores)
def _variacao(v0, v1, d=2):
    """Frase curta e correta para qualquer sinal: 'aumento de R$ X', 'redução de R$ X' ou 'sem variação'."""
    dv = round(v1 - v0, d)
    if abs(dv) < 0.005:
        return "sem variação"
    return ("aumento de " if dv > 0 else "redução de ") + brl(abs(dv))


def _de_para(v0, v1):
    """'passou de A para B' ou 'permaneceu em A' quando nao mudou."""
    return f"permaneceu em {brl(v1)}" if abs(v1 - v0) < 0.005 else f"passou de {brl(v0)} para {brl(v1)}"


def textos_padrao(x: dict) -> dict:
    """{chave: texto}. Cada paragrafo e' separado por linha em branco; a contadora pode editar qualquer um antes de gerar."""
    E = x["empresa"]; bp = x["bp"]; dr = x["dre"]; ind = x["ind"]; S = x["serie"]
    B = lambda k, i=2: bp[k][i]
    D = lambda k, i=2: dr[k][i]
    atv, atv0 = B("ativo"), B("ativo", 0)
    caixa, caixa0 = B("caixa_eq"), B("caixa_eq", 0)
    conc = B("conc_liq")
    divb, divb0, divl = ind["div_bruta"][2], ind["div_bruta"][0], ind["div_liquida"][2]
    pl, pl0 = B("pl"), B("pl", 0)
    res, resf = D("res_liq"), D("res_fin")
    custo, fretes = D("custo_constr"), D("fretes")
    dedu, opex = D("deducoes"), D("desp_adm")
    db, per = x["data_base"], x["mes_nome"]
    t = {}
    t["dest_1"] = (f"Em {db}, o ativo total da {E['curto']} era de {brl(atv)}" +
                   (f", dos quais {brl(conc)} ({pct(razao(conc, atv))}) correspondem ao ativo de concessão líquido." if abs(conc) >= 0.005 else "."))
    t["dest_2"] = (f"O caixa e equivalentes totalizou {brl(caixa)}, {_variacao(caixa0, caixa)}"
                   + (f" ({pct(razao(abs(caixa - caixa0), abs(caixa0)))})" if abs(caixa0) >= 0.005 and abs(caixa - caixa0) >= 0.005 else "") + f" em relação a {x['abertura']}. "
                   f"No mesmo período, a dívida bruta {_de_para(divb0, divb)}; a dívida líquida (dívida bruta menos caixa) é de {brl(divl)}.")
    t["dest_3"] = (f"O resultado líquido acumulado até {per} foi de {brl(res)}, composto por custo de construção de {brl(-custo)}, "
                   f"demais custos e despesas de {brl(-(D('deducoes') + D('fretes') + D('desp_adm')))} e resultado financeiro de {brl(resf)}. "
                   f"O patrimônio líquido {_de_para(pl0, pl)}" + (f", com variação de AFAC de {brl(B('afac', 3))} no período." if abs(B('afac', 3)) >= 0.005 else "."))
    n = len(S["caixa"])
    mn_i = min(range(n), key=lambda i: S["caixa"][i])
    meio = 0 < mn_i < n - 1 and S["caixa"][mn_i] < min(S["caixa"][0], S["caixa"][-1])
    t["evo_1"] = (f"O caixa e equivalentes passou de {brl(S['caixa'][0])} em {S['rotulos'][0].lower()} para {brl(S['caixa'][-1])} em {S['rotulos'][-1].lower()}"
                  + (f", com o menor saldo do período em {S['rotulos'][mn_i].lower()} ({brl(S['caixa'][mn_i])})" if meio else "") + ". "
                  f"A dívida bruta {_de_para(S['bndes'][0], S['bndes'][-1])} no período.")
    cc = S["custo_constr"]
    imax = max(range(len(cc)), key=lambda i: cc[i]) if cc else 0
    t["evo_2"] = (f"O custo de construção do ativo de concessão somou {brl(sum(cc))} no ano (média mensal de {brl(sum(cc) / max(len(cc), 1))}); "
                  f"o maior valor mensal foi o de {S['meses'][imax].lower()} ({brl(cc[imax])})." if cc and sum(cc) > 0 else
                  "Não houve custo de construção do ativo de concessão no período.")
    plm = S["pl"]
    mudou = next((i for i in range(1, len(plm)) if plm[i - 1] >= 0 > plm[i]), None)
    t["evo_3"] = (f"O patrimônio líquido passou de {brl(plm[0])} em {S['rotulos'][0].lower()} para {brl(plm[-1])} em {S['rotulos'][-1].lower()}." +
                  (f" A mudança de sinal ocorre em {S['rotulos'][mudou].lower()} ({brl(plm[mudou])})." if mudou else ""))
    t["res_1"] = (f"O resultado líquido acumulado até {per} foi de {brl(res)}. O custo de construção do ativo de concessão, de {brl(-custo)}, "
                  + (f"equivale a {pct(razao(custo, res))} desse valor; " if res < -0.005 else "") + f"as deduções da receita (PIS e COFINS) somaram {brl(-dedu)}.")
    t["res_2"] = (f"As despesas operacionais somaram {brl(-opex)} e o resultado financeiro líquido foi de {brl(resf)}, formado por rendimentos de aplicações "
                  f"financeiras de {brl(D('rend_aplic'))} e receitas de aplicações (NT) de {brl(D('rec_nt'))}, entre outros.")
    exig = B("pc") + B("pnc")
    t["bal_1"] = ((f"O ativo de concessão líquido ({brl(conc)}) representa {pct(razao(conc, atv))} do ativo total. " if abs(conc) >= 0.005 else "") +
                  f"O passivo exigível soma {brl(exig)}, sendo {brl(B('bndes_lp'))} de empréstimos do BNDES no longo prazo e {brl(B('trib_dif'))} de tributos diferidos.")
    t["bal_2"] = (f"O patrimônio líquido de {brl(pl)} resulta de capital social de {brl(B('capital'))}, AFAC de {brl(B('afac'))}, reservas de {brl(B('res_legal') + B('res_ret'))} "
                  f"e resultado acumulado do período de {brl(B('prej'))}. O ativo circulante ({brl(B('ac'))}) é "
                  f"{'inferior' if B('ac') < B('pc') else 'superior'} ao passivo circulante ({brl(B('pc'))}).")
    c = {g["chave"]: g for g in x["comp"]}
    p1 = []
    cx = c.get("caixa")
    if cx and cx["itens"] and abs(cx["total"]) >= 0.005:
        top = max(cx["itens"], key=lambda kv: kv[1])
        p1.append(f"{top[0]} representa {pct(razao(top[1], cx['total']))} do caixa e equivalentes ({brl(cx['total'])}).")
    dv = c.get("divida")
    if dv and dv["itens"] and abs(dv["total"]) >= 0.005:
        lp = next((v for n_, v in dv["itens"] if n_ == "Longo prazo"), None)
        if lp is not None:
            p1.append(f"A parcela de longo prazo corresponde a {pct(razao(lp, dv['total']))} da dívida com o BNDES ({brl(dv['total'])}).")
    ad = c.get("adiant")
    if ad and ad["itens"] and abs(ad["total"]) >= 0.005:
        top = max(ad["itens"], key=lambda kv: kv[1])
        p1.append(f"O maior saldo de adiantamentos é o de {top[0]} ({pct(razao(top[1], ad['total']))} de {brl(ad['total'])}).")
    t["comp_1"] = " ".join(p1)
    p2 = []
    fo = c.get("fornec")
    if fo and fo["itens"] and abs(fo["total"]) >= 0.005:
        reais = [v for n_, v in fo["itens"] if not (fo["demais"] and n_.startswith("Demais"))][:3]
        quem = "Os três maiores fornecedores representam" if len(reais) >= 3 else ("O único fornecedor com saldo representa" if len(reais) == 1 else f"Os {len(reais)} fornecedores com saldo representam")
        p2.append(f"{quem} {pct(razao(sum(reais), fo['total']))} do saldo de fornecedores ({brl(fo['total'])}).")
    cp = c.get("capital")
    if cp and cp["itens"] and abs(cp["total"]) >= 0.005:
        top = max(cp["itens"], key=lambda kv: kv[1])
        p2.append(f"{top[0]} concentra {pct(razao(top[1], cp['total']))} do capital aportado.")
    t["comp_2"] = " ".join(p2)
    return t
