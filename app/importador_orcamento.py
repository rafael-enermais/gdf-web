# -*- coding: utf-8 -*-
"""
GDF V2 - leitor do PDF do Sienge "Comparativo Orcado X Realizado Agrupado" (Orcamento ADM).
Cada pagina traz os mesmos blocos de colunas (Orcado / Realizado / Saldo) de ate 4 meses; as contas descem por varias paginas e o MESMO conjunto de
meses se repete em todas as paginas daquele bloco (ex.: paginas 1-5 = Jan-Abr, 6-10 = Mai-Ago, 11-15 = Set). Colunas sem mes (grupos vazios do ultimo
bloco) sao ignoradas. Le so' TEXTO (pdfplumber), usando a POSICAO das palavras (nao o texto "em layout"); o arquivo original nunca e' alterado.
Sem streamlit, sem banco.

Devolve {'cabecalho', 'meses', 'linhas', 'resumo', 'avisos'} (ver `ler_orcamento_adm_pdf`).
"""
from __future__ import annotations

import io
import re

NUM = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
_RE_NUM = re.compile(rf"^{NUM}$")
_RE_COD = re.compile(r"^\d(?:\.\d{2})*$")
_RE_MES = re.compile(r"^(Jan|Fev|Mar|Abr|Mai|Jun|Jul|Ago|Set|Out|Nov|Dez)/(\d{4})$", re.I)
_MESES = {m: i + 1 for i, m in enumerate(["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"])}
_RE_PERIODO = re.compile(r"Per[ií]odo\s*(\d\d)/(\d\d)/(\d{4})\s*a\s*(\d\d)/(\d\d)/(\d{4})")
_COLS = ("orcado", "realizado", "saldo")


class ErroOrcamento(ValueError):
    """Mensagem em portugues simples, pronta para mostrar na tela."""


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _br(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _agrupar_linhas(palavras: list, tol: float = 2.5) -> list:
    """Agrupa palavras na mesma linha (mesma altura, com tolerancia); devolve [(top, [palavras ordenadas por x])]."""
    linhas = []
    for w in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
        if linhas and abs(linhas[-1][0] - w["top"]) <= tol:
            linhas[-1][1].append(w)
        else:
            linhas.append((w["top"], [w]))
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in linhas]


def _colunas_da_pagina(palavras: list) -> list:
    """Lê os cabecalhos da pagina: devolve [(rotulo_mes, {'orcado': x1, 'realizado': x1, 'saldo': x1})] so' dos grupos que tem mes (ou 'Total')."""
    meses = [w for w in palavras if _RE_MES.match(w["text"]) or w["text"].lower() == "total" and 150 < w["top"] < 175]
    meses = sorted([w for w in meses if 150 < w["top"] < 175], key=lambda w: w["x0"])
    if not meses:
        return []
    topo = min(w["top"] for w in palavras if w["text"] in ("Orçado", "Orcado") and w["top"] > 160) if any(
        w["text"] in ("Orçado", "Orcado") and w["top"] > 160 for w in palavras) else None
    if topo is None:
        return []
    cab = sorted([w for w in palavras if abs(w["top"] - topo) <= 3 and w["text"] in ("Orçado", "Orcado", "Realizado", "Saldo")], key=lambda w: w["x0"])
    grupos = [cab[i:i + 3] for i in range(0, len(cab), 3)]
    saida = []
    for i, m in enumerate(meses):
        if i >= len(grupos) or len(grupos[i]) < 3:
            raise ErroOrcamento("Não consegui casar as colunas Orçado/Realizado/Saldo com os meses do cabeçalho. O arquivo é o relatório 'Comparativo Orçado X Realizado Agrupado' do Sienge?")
        saida.append((m["text"], {c: grupos[i][j]["x1"] for j, c in enumerate(_COLS)}))
    return saida


def _rotulo_para_mes(rot: str):
    """'Jan/2026' -> '2026-01'; 'Total' -> 'TOTAL'."""
    if rot.lower() == "total":
        return "TOTAL"
    m = _RE_MES.match(rot)
    return f"{m.group(2)}-{_MESES[m.group(1).lower()]:02d}"


def _cabecalho(texto: str) -> dict:
    m = _RE_PERIODO.search(texto)
    agr = re.search(r"Agrupamento\s*(\d+\s*-.+)", texto)
    return {"inicio": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None, "fim": f"{m.group(6)}-{m.group(5)}-{m.group(4)}" if m else None,
            "agrupamento": agr.group(1).strip() if agr else None}


def ler_orcamento_adm_pdf(conteudo: bytes) -> dict:
    """Lê o PDF e devolve:
    {'cabecalho': {'inicio','fim','agrupamento'},
     'meses': ['2026-01', ...] (sem a coluna Total),
     'linhas': [{'codigo','conta','tipo' ('T' total | 'R' conta folha | 'M' conta folha de outro tipo, ex.: canteiros),'mes' 'AAAA-MM','orcado','realizado','saldo'}],
        -- conta R/M com algum valor != 0 em qualquer mes traz TODOS os meses; as demais so' os meses com valor != 0;
     'resumo': {'AAAA-MM': {'diferenca': {orcado, realizado, saldo}, 'diferenca_acumulada': {...}}}  (rodape do relatorio),
     'avisos': [texto em portugues]}.
    Avisos: saldo != realizado - orcado; linha T != soma dos filhos diretos; soma dos meses != coluna Total (se houver)."""
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(conteudo))
    except Exception as e:
        raise ErroOrcamento(f"Não consegui abrir o PDF ({e.__class__.__name__}). O arquivo está íntegro?")
    vals = {}      # (codigo, mes) -> {orcado, realizado, saldo}
    info = {}      # codigo -> (conta, tipo)
    ordem = []     # codigos na ordem em que aparecem
    resumo = {}
    cab = {"inicio": None, "fim": None, "agrupamento": None}
    achou_titulo = False
    with pdf:
        for pag in pdf.pages:
            texto = pag.extract_text() or ""
            if "Comparativo" in texto and "Realizado" in texto:
                achou_titulo = True
            if cab["inicio"] is None and _RE_PERIODO.search(texto):
                cab = _cabecalho(texto)
            palavras = pag.extract_words()
            colunas = _colunas_da_pagina(palavras)
            if not colunas:
                continue
            primeiro_x = min(c[1]["orcado"] for c in colunas) - 40
            for _top, ws in _agrupar_linhas([w for w in palavras if w["top"] > 183]):
                txt0 = ws[0]["text"]
                numeros = [w for w in ws if _RE_NUM.match(w["text"]) and w["x0"] > primeiro_x - 15]
                # rodape: "Diferenca" e "Diferenca acumulada" (3 numeros por mes)
                if txt0 in ("Diferença", "Diferenca"):
                    chave = "diferenca_acumulada" if len(ws) > 1 and ws[1]["text"].lower().startswith("acumulada") else "diferenca"
                    for rot, xs in colunas:
                        mes = _rotulo_para_mes(rot)
                        if mes == "TOTAL":
                            continue
                        item = {}
                        for c in _COLS:
                            cand = [w for w in numeros if abs(w["x1"] - xs[c]) <= 6]
                            if cand:
                                item[c] = _num(cand[0]["text"])
                        if len(item) == 3:
                            resumo.setdefault(mes, {})[chave] = item
                    continue
                if not (_RE_COD.match(txt0) and ws[0]["x0"] < 80):
                    continue
                tipo_w = [w for w in ws if w["text"] in ("T", "R", "M") and 235 < w["x0"] < primeiro_x]
                if not tipo_w:
                    continue
                tipo = tipo_w[0]["text"]
                conta = " ".join(w["text"] for w in ws[1:] if w["x0"] < tipo_w[0]["x0"] - 1)
                if txt0 not in info:
                    info[txt0] = (conta, tipo)
                    ordem.append(txt0)
                for rot, xs in colunas:
                    mes = _rotulo_para_mes(rot)
                    item = {}
                    for c in _COLS:
                        cand = [w for w in numeros if abs(w["x1"] - xs[c]) <= 6]
                        if cand:
                            item[c] = _num(cand[0]["text"])
                    if len(item) == 3:
                        vals[(txt0, mes)] = item
    if not achou_titulo or not vals:
        raise ErroOrcamento("Este PDF não parece o relatório 'Comparativo Orçado X Realizado Agrupado' do Sienge (Orçamento ADM). "
                            "Exporte esse relatório com a periodicidade mensal e tente de novo.")
    meses = sorted({m for (_c, m) in vals if m != "TOTAL"})
    linhas = []
    for cod in ordem:
        conta, tipo = info[cod]
        por_mes = {m: vals[(cod, m)] for m in meses if (cod, m) in vals}
        algum = any(abs(v[c]) > 0.004 for v in por_mes.values() for c in _COLS)
        for m, v in por_mes.items():
            if tipo != "T" and algum or any(abs(v[c]) > 0.004 for c in _COLS):
                linhas.append({"codigo": cod, "conta": conta, "tipo": tipo, "mes": m, "orcado": v["orcado"], "realizado": v["realizado"], "saldo": v["saldo"]})
    return {"cabecalho": cab, "meses": meses, "linhas": linhas, "resumo": resumo, "avisos": _conferir(vals, info, ordem, meses)}


def _conferir(vals: dict, info: dict, ordem: list, meses: list) -> list:
    """Avisos de consistencia (nunca derrubam a leitura)."""
    avisos = []
    # 1) saldo = realizado - orcado
    ruins = [(c, m) for (c, m), v in vals.items() if m != "TOTAL" and abs((v["realizado"] - v["orcado"]) - v["saldo"]) > 0.02]
    if ruins:
        exs = ", ".join(f"{c} ({m})" for c, m in ruins[:5])
        avisos.append(f"Saldo diferente de Realizado − Orçado em {len(ruins)} célula(s): {exs}.")
    # 2) linha T = soma dos filhos diretos (codigo pai + 1 nivel)
    filhos = {}
    for cod in ordem:
        if "." in cod:
            filhos.setdefault(cod.rsplit(".", 1)[0], []).append(cod)
    for pai in ordem:
        if info[pai][1] != "T" or pai not in filhos:
            continue
        for m in meses:
            if (pai, m) not in vals:
                continue
            for c in ("orcado", "realizado"):
                soma = sum(vals[(f, m)][c] for f in filhos[pai] if (f, m) in vals)
                if abs(soma - vals[(pai, m)][c]) > 0.05 + 0.01 * len(filhos[pai]):
                    avisos.append(f"Conta {pai} ({m}, {c}): total {_br(vals[(pai, m)][c])} difere da soma das contas filhas {_br(soma)}.")
    # 3) soma dos meses = coluna Total (se o PDF trouxer)
    for cod in ordem:
        if (cod, "TOTAL") in vals:
            for c in ("orcado", "realizado"):
                soma = sum(vals[(cod, m)][c] for m in meses if (cod, m) in vals)
                if abs(soma - vals[(cod, "TOTAL")][c]) > 0.05 + 0.01 * len(meses):
                    avisos.append(f"Conta {cod} ({c}): soma dos meses difere da coluna Total.")
    return avisos
