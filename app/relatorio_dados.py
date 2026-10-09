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
from relatorio_fmt import ND, brl, fnum, mm, pct, razao

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
    "res_fin": "Receitas menos despesas financeiras, acumulado {escopo}.",
    "ebit_ebitda": "Sem depreciação/amortização no período, o EBITDA é igual ao EBIT.",
    "res_liq": "Resultado líquido acumulado {no_escopo}.",
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
            "logo_grupo_capa": bool(cfg.get("logo_grupo_capa", base.get("logo_grupo_capa", False))),
            "tipo": cfg.get("tipo") or base.get("tipo", ""), "nota_resultado": cfg.get("nota_resultado", base.get("nota_resultado", "")),
            "assinantes": ass or [("", "Administrador"), ("", "Contador")]}


def _linha(v0, v1, v2):
    """[abertura, mes anterior, mes ref, var R$, var %]; ND ("n/d") = coluna sem balancete (nao da' para calcular); None = sem base de comparacao."""
    v0, v1, v2 = (ND if v is None else v for v in (v0, v1, v2))
    var = ND if ND in (v0, v2) else round(v2 - v0, 2)
    return [v0, v1, v2, var, ND if var == ND else (None if abs(v0) < 0.005 else var / abs(v0))]


def _pontos_de(b: motor.Balancetes, mes_ref: str) -> list:
    """Pontos mensais (balanço e resultado do mês) a partir dos balancetes completos de janeiro até o mês de referência."""
    return [{"per": m, "bp": motor.coluna_bp(b, m), "dre_mes": motor.dre_calcular(motor.dre_bruta(b, [m]))} for m in b.ordem if m <= mes_ref]


def montar(emp: dict, b: motor.Balancetes, mes_ref: str, bp: dict, d: dict, contas_ref: list, apelidos=None, grupos=None,
           config: dict | None = None, mapa=None, dados: dict | None = None) -> dict:
    """Tudo que o gerador de PDF precisa (numeros prontos, sem calculo no desenho).
    `dados` = resultado de fontes.calcular (meses faltando: colunas None = n/d, pontos so' dos meses com balancete, lacunas explicadas);
    sem ele, usa `b` como antes (sequencia completa de janeiro ate o mes)."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    ini = int(dados.get("ini", 1)) if dados is not None else 1             # 1o mes do periodo do relatorio (1 = ano inteiro)
    if dados is not None:
        pontos, mes_ant, lacunas, fontes_ = [p for p in dados["pontos"] if int(p["per"][5:7]) >= ini], dados["mes_ant"], dados["lacunas"], dados["fontes"]
    else:
        pontos = _pontos_de(b, mes_ref)
        ordem = [m for m in b.ordem if m <= mes_ref]
        mes_ant = ordem[ordem.index(mes_ref) - 1] if ordem.index(mes_ref) > 0 else mes_ref
        lacunas, fontes_ = [], {}
    rot = dict(motor.ROTULOS)
    rot.update({m[0]: m[1] for m in (mapa or [])})
    cb = [bp["abertura"], bp["mes_ant"], bp["mes_ref"]]
    cd = [d["ate_mes_ant"], d["mes"], d["acumulado"]]
    kb = list(next(c for c in cb if c is not None))
    kd = list(next(c for c in cd if c is not None))
    bpv = {k: _linha(*(c[k] if c is not None else None for c in cb)) for k in kb}
    drv = {k: [c[k] if c is not None else ND for c in cd] for k in kd}
    i0, i1, i2 = (motor.indicadores(bp["abertura"], None), motor.indicadores(bp["mes_ant"], d["ate_mes_ant"]),
                  motor.indicadores(bp["mes_ref"], d["acumulado"]))
    def _ci(i, k, col, dre_col, abertura=False):             # n/d quando a coluna do balanco (ou, nos de resultado, a da DRE) nao existe
        return ND if col is None or (k in ("res_fin", "ebit_ebitda", "res_liq") and dre_col is None and not abertura) else i[k]
    ind = {k: [_ci(i0, k, bp["abertura"], None, True), _ci(i1, k, bp["mes_ant"], d["ate_mes_ant"]), _ci(i2, k, bp["mes_ref"], d["acumulado"])] for k in i2}
    # serie: abertura (31/12 anterior, se houver) + cada mes que tem balancete ate' o de referencia
    ab = bp["abertura"]
    ab_rot = f"Dez/{str(ano - 1)[2:]}" if ini == 1 else f"{MESES_ABREV[ini - 2]}/{str(ano)[2:]}"
    ate_ab = [(ab_rot, ab)] if ab is not None else []
    rot_pts = ate_ab + [(f"{MESES_ABREV[int(p['per'][5:7]) - 1]}/{str(ano)[2:]}", p["bp"]) for p in pontos]
    serie = {
        "meses": [MESES_ABREV[int(p["per"][5:7]) - 1] for p in pontos],
        "rotulos": [r for r, _ in rot_pts], "tem_abertura": ab is not None,
        "sem_posicao": [f"{MESES_ABREV[m - 1].lower()}/{str(ano)[2:]}" for m in range(ini, mes + 1) if m not in {int(p["per"][5:7]) for p in pontos}],
        "caixa": [c["caixa_eq"] for _, c in rot_pts],
        "bndes": [round(c["bndes_cp"] + c["bndes_lp"], 2) for _, c in rot_pts],
        "pl": [c["pl"] for _, c in rot_pts],
        "fornec": [c["fornec"] for _, c in rot_pts],
        "custo_constr": [None if p["dre_mes"] is None else round(-p["dre_mes"]["custo_constr"], 2) for p in pontos],     # None = mes sem balancete mensal
        "resultado_mes": [None if p["dre_mes"] is None else p["dre_mes"]["res_liq"] for p in pontos],
    }
    tem_ant = mes > ini                                                       # ha' "mes anterior" dentro do periodo?
    per_ext = f"{MESES_EXT[ini - 1]} a {MESES_EXT[mes - 1]}" if tem_ant else MESES_EXT[mes - 1]
    return {
        "empresa": info_empresa(emp, config), "mes_ref": mes_ref, "mes_ant": mes_ant, "ano": ano, "mes": mes, "ini": ini, "tem_ant": tem_ant,
        "data_base": data_fim(mes_ref), "data_ant": data_fim(mes_ant),
        "abertura": f"31/12/{ano - 1}" if ini == 1 else data_fim(f"{ano}-{ini - 1:02d}"), "abertura_rot": ab_rot,
        "data_base_ext": f"{calendar.monthrange(ano, mes)[1]} de {MESES_EXT[mes - 1]} de {ano}",
        "periodo": ((f"Acumulado de janeiro a {MESES_EXT[mes - 1]} de {ano}" if ini == 1 else f"Período de {per_ext} de {ano}") if tem_ant
                    else (f"Janeiro de {ano}" if ini == 1 else f"{MESES_EXT[mes - 1].capitalize()} de {ano}")),
        "periodo_curto": (f"{MESES_ABREV[ini - 1].upper()}–{MESES_ABREV[mes - 1].upper()}/{ano}" if tem_ant else f"{MESES_ABREV[mes - 1].upper()}/{ano}"),
        "periodo_ext": per_ext, "acum_rot": (f"{MESES_ABREV[ini - 1]}–{MESES_ABREV[mes - 1]}" if tem_ant else MESES_ABREV[mes - 1]),
        "ate_ant_rot": (f"{MESES_ABREV[ini - 1]}–{MESES_ABREV[mes - 2]}" if mes - 1 > ini else (MESES_ABREV[ini - 1] if tem_ant else "")),
        "escopo": "do ano" if ini == 1 else "do período", "no_escopo": "no ano" if ini == 1 else "no período",
        "mes_nome": MESES_EXT[mes - 1], "mes_abrev": MESES_ABREV[mes - 1], "ini_nome": MESES_EXT[ini - 1], "ini_abrev": MESES_ABREV[ini - 1],
        "rot": rot, "bp": bpv, "dre": drv, "ind": ind, "serie": serie, "n_meses": mes - ini + 1,
        "comp": composicao.calcular(contas_ref, grupos, apelidos),
        "ajustes": d["acumulado"]["ajustes"] if d["acumulado"] is not None else ND,
        "lacunas": lacunas, "fontes": fontes_, "fonte": (dados["fonte"] if dados is not None else "completo"), "usa_acum": bool(dados["usados_acum"]) if dados is not None else False,
    }


def _seguro(fn) -> str:
    """Texto automatico que depende de numero que pode estar n/d: se nao der para escrever com correcao, o paragrafo e' omitido (nunca inventado)."""
    try:
        return fn() or ""
    except (TypeError, ZeroDivisionError, ValueError, IndexError, KeyError):
        return ""


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
    x = dict(x, acum_ate=(f"até {per}" if x.get("ini", 1) == 1 else f"de {x['ini_nome']} a {per}"))
    t = {}
    t["dest_1"] = _seguro(lambda: (f"Em {db}, o ativo total da {E['curto']} era de {brl(atv)}" +
                   (f", dos quais {brl(conc)} ({pct(razao(conc, atv))}) correspondem ao ativo de concessão líquido." if abs(conc) >= 0.005 else ".")))
    if isinstance(caixa0, str) or isinstance(divb0, str):                      # sem a abertura (31/12) não há comparação: só a posição
        t["dest_2"] = _seguro(lambda: f"O caixa e equivalentes totalizou {brl(caixa)}; a dívida bruta é de {brl(divb)} e a dívida líquida (dívida bruta menos caixa) é de {brl(divl)}.")
    else:
        t["dest_2"] = _seguro(lambda: (f"O caixa e equivalentes totalizou {brl(caixa)}, {_variacao(caixa0, caixa)}"
                   + (f" ({pct(razao(abs(caixa - caixa0), abs(caixa0)))})" if abs(caixa0) >= 0.005 and abs(caixa - caixa0) >= 0.005 else "") + f" em relação a {x['abertura']}. "
                   f"No mesmo período, a dívida bruta {_de_para(divb0, divb)}; a dívida líquida (dívida bruta menos caixa) é de {brl(divl)}."))
    t["dest_3"] = _seguro(lambda: (f"O resultado líquido acumulado {x['acum_ate']} foi de {brl(res)}, composto por custo de construção de {brl(-custo)}, "
                   f"demais custos e despesas de {brl(-(D('deducoes') + D('fretes') + D('desp_adm')))} e resultado financeiro de {brl(resf)}. "
                   f"O patrimônio líquido {_de_para(pl0, pl)}" + (f", com variação de AFAC de {brl(B('afac', 3))} no período." if abs(B('afac', 3)) >= 0.005 else ".")))
    n = len(S["caixa"])
    mn_i = min(range(n), key=lambda i: S["caixa"][i])
    meio = 0 < mn_i < n - 1 and S["caixa"][mn_i] < min(S["caixa"][0], S["caixa"][-1])
    parcial_serie = x["n_meses"] > len(S["meses"])             # ha' meses sem balancete: a serie mostra so' os que existem
    t["evo_1"] = _seguro(lambda: n >= 2 and (f"O caixa e equivalentes passou de {brl(S['caixa'][0])} em {S['rotulos'][0].lower()} para {brl(S['caixa'][-1])} em {S['rotulos'][-1].lower()}"
                  + (f", com o menor saldo do período em {S['rotulos'][mn_i].lower()} ({brl(S['caixa'][mn_i])})" if meio else "") + ". "
                  f"A dívida bruta {_de_para(S['bndes'][0], S['bndes'][-1])} no período."))
    cc = [(m, v) for m, v in zip(S["meses"], S["custo_constr"]) if v is not None]        # so' os meses com balancete mensal
    total_cc = None if isinstance(custo, str) else -custo                                       # acumulado do ano (vale mesmo com meses faltando)
    def _evo2():
        if total_cc is None:
            return f"Nos meses com balancete mensal, o custo de construção do ativo de concessão somou {brl(sum(v for _, v in cc))}." if cc and sum(v for _, v in cc) > 0 else ""
        if total_cc <= 0:
            return "Não houve custo de construção do ativo de concessão no período."
        pm, vm = max(cc, key=lambda mv: mv[1]) if cc else (None, None)
        return (f"O custo de construção do ativo de concessão somou {brl(total_cc)} {x['no_escopo']} (média mensal de {brl(total_cc / max(x['n_meses'], 1))})"
                + (f"; o maior valor mensal foi o de {pm.lower()} ({brl(vm)})" + (" entre os meses com balancete mensal" if parcial_serie else "") if pm else "") + ".")
    t["evo_2"] = _seguro(_evo2)
    plm = S["pl"]
    mudou = next((i for i in range(1, len(plm)) if plm[i - 1] >= 0 > plm[i]), None)
    t["evo_3"] = _seguro(lambda: len(plm) >= 2 and (f"O patrimônio líquido passou de {brl(plm[0])} em {S['rotulos'][0].lower()} para {brl(plm[-1])} em {S['rotulos'][-1].lower()}." +
                  (f" A mudança de sinal ocorre em {S['rotulos'][mudou].lower()} ({brl(plm[mudou])})." if mudou else "")))
    t["res_1"] = _seguro(lambda: (f"O resultado líquido acumulado {x['acum_ate']} foi de {brl(res)}. O custo de construção do ativo de concessão, de {brl(-custo)}, "
                  + (f"equivale a {pct(razao(custo, res))} desse valor; " if res < -0.005 else "") + f"as deduções da receita (PIS e COFINS) somaram {brl(-dedu)}."))
    t["res_2"] = _seguro(lambda: (f"As despesas operacionais somaram {brl(-opex)} e o resultado financeiro líquido foi de {brl(resf)}, formado por rendimentos de aplicações "
                  f"financeiras de {brl(D('rend_aplic'))} e receitas de aplicações (NT) de {brl(D('rec_nt'))}, entre outros."))
    exig = B("pc") + B("pnc")
    if x.get("lacunas"):
        t["dest_9"] = ("Atenção: este relatório foi gerado com dados incompletos. Os itens marcados “n/d” não puderam ser calculados porque faltam balancetes "
                       "(veja a página “Dados incompletos”); o que está calculado está correto.")
    t["bal_1"] = _seguro(lambda: ((f"O ativo de concessão líquido ({brl(conc)}) representa {pct(razao(conc, atv))} do ativo total. " if abs(conc) >= 0.005 else "") +
                  f"O passivo exigível soma {brl(exig)}, sendo {brl(B('bndes_lp'))} de empréstimos do BNDES no longo prazo e {brl(B('trib_dif'))} de tributos diferidos."))
    t["bal_2"] = _seguro(lambda: (f"O patrimônio líquido de {brl(pl)} resulta de capital social de {brl(B('capital'))}, AFAC de {brl(B('afac'))}, reservas de {brl(B('res_legal') + B('res_ret'))} "
                  f"e resultado acumulado do período de {brl(B('prej'))}. O ativo circulante ({brl(B('ac'))}) é "
                  f"{'inferior' if B('ac') < B('pc') else 'superior'} ao passivo circulante ({brl(B('pc'))})."))
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
    t["comp_1"] = _seguro(lambda: " ".join(p1))
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
    t["comp_2"] = _seguro(lambda: " ".join(p2))
    return t
