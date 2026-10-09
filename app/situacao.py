# -*- coding: utf-8 -*-
"""
GDF - situacao do ano (quadro do Inicio): para cada mes, se o balancete foi importado, o status, as falhas e o relatorio gerado.
Modulo puro (recebe as listas do banco). Serve para a pessoa saber 'onde estou e o que falta' sem abrir cada tela.
"""
from __future__ import annotations

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
ORDEM_REL = {"RASCUNHO": 1, "REVISADO": 2, "ASSINADO": 3}


def anos_com_dados(imps: list) -> list:
    return sorted({i["periodo_fim"].year for i in imps if i["tipo"] == "MENSAL" and i["ativo"]}, reverse=True)


def quadro(ano: int, imps: list, rels: list) -> list[dict]:
    """12 linhas (jan..dez): mes, importado, status, falhas, relatorio (melhor versao do mes)."""
    por_mes = {i["periodo_fim"].month: i for i in imps if i["tipo"] == "MENSAL" and i["ativo"] and i["periodo_fim"].year == ano}
    rel_mes: dict = {}
    for r in rels:
        if r["periodo"].year != ano:
            continue
        atual = rel_mes.get(r["periodo"].month)
        chave = (ORDEM_REL.get(r["status"], 0), r["versao"])
        if atual is None or chave > (ORDEM_REL.get(atual["status"], 0), atual["versao"]):
            rel_mes[r["periodo"].month] = r
    linhas = []
    for m in range(1, 13):
        i, r = por_mes.get(m), rel_mes.get(m)
        linhas.append({"mes": m, "rotulo": f"{MESES[m - 1]}/{str(ano)[2:]}", "importado": i is not None,
                       "status": i["status"] if i else "–", "falhas": int(i["falhas"]) if i else None,
                       "relatorio": f"v{r['versao']} {r['status']}" if r else "–"})
    return linhas


def proxima_acao(linhas: list[dict]) -> str:
    """Uma frase com o proximo passo mais provavel."""
    imp = [l["mes"] for l in linhas if l["importado"]]
    if not imp:
        return "Importe o balancete de janeiro (menu **Importar balancete**)."
    ultimo = max(imp)
    buraco = [l["rotulo"] for l in linhas if l["mes"] < ultimo and not l["importado"]]
    if buraco:
        return "Faltam balancetes no meio do ano: " + ", ".join(buraco) + ". Os demonstrativos precisam de todos os meses de janeiro até o mês escolhido."
    ras = [l["rotulo"] for l in linhas if l["importado"] and l["status"] != "REVISADA"]
    com_falha = [l["rotulo"] for l in linhas if l["importado"] and (l["falhas"] or 0) > 0]
    if com_falha:
        return "Há conferências com falha em " + ", ".join(com_falha) + ". Veja o **Histórico** (conferências da importação) e o guia em **Ajuda**."
    if ras:
        return "Confira e marque como **REVISADA** no Histórico: " + ", ".join(ras) + "."
    ref = next(l for l in linhas if l["mes"] == ultimo)
    if ref["relatorio"] == "–":
        return f"Balancetes até {ref['rotulo']} revisados. Gere o relatório de {ref['rotulo']} (menu **Relatório PDF**)."
    if "ASSINADO" not in ref["relatorio"]:
        return f"Relatório de {ref['rotulo']} já gerado ({ref['relatorio']}). Falta a versão final e a assinatura, ou importar o mês seguinte."
    return f"Tudo em dia até {ref['rotulo']}. Próximo: importar o balancete do mês seguinte."
