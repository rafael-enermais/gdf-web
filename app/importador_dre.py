# -*- coding: utf-8 -*-
"""
GDF V2 - leitor do PDF do Sienge "Demonstrativo de Resultado - Agrupado por Obra - DRE GERENCIAL" (versao com a composicao das contas).
O PDF vem em paginas: cada grupo de paginas repete um bloco de colunas de obra (100, 101, ... e, no ultimo, "Total"). Cada linha do DRE
(01, 01.01, 04.03...) e cada conta do plano (1.01.01.01, 2.01.02.01...) traz um valor por coluna.
Le so' TEXTO (pdfplumber); o arquivo original nunca e' alterado. Sem streamlit, sem banco.
Devolve as linhas de valor diferente de zero + avisos de consistencia (soma das contas = linha do DRE; soma das obras = coluna Total).
"""
from __future__ import annotations

import io
import re

NUM = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
_RE_NUM = re.compile(rf"^{NUM}$")
_RE_CONTA = re.compile(r"^(\d\.\d\d(?:\.\d\d)+)\s+-\s+(.*)$")
_RE_LINHA = re.compile(r"^(\d\d(?:\.\d\d)?)\s+(.*)$")
_RE_PERIODO = re.compile(r"Per[ií]odo\s*(\d\d)/(\d\d)/(\d{4})\s*a\s*(\d\d)/(\d\d)/(\d{4})")


class ErroDRE(ValueError):
    """Mensagem em portugues simples, pronta para mostrar na tela."""


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _cabecalho(texto: str) -> dict:
    m = _RE_PERIODO.search(texto)
    analise = re.search(r"Tipo de an[aá]lise\s*(\w+)", texto)
    selecao = re.search(r"Sele[cç][aã]o por\s*(.+)", texto)
    return {"inicio": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None, "fim": f"{m.group(6)}-{m.group(5)}-{m.group(4)}" if m else None,
            "analise": analise.group(1) if analise else None, "selecao": selecao.group(1).strip() if selecao else None}


def _tokens_numericos_finais(partes: list, n: int):
    """Se os n ultimos tokens sao numeros no formato brasileiro, devolve (texto_sem_numeros, [valores]); senao None."""
    if len(partes) < n + 1 or not all(_RE_NUM.match(p) for p in partes[-n:]):
        return None
    return " ".join(partes[:-n]), [_num(p) for p in partes[-n:]]


def ler_dre_pdf(conteudo: bytes) -> dict:
    """Le o PDF e devolve {'periodo': {...}, 'obras': [{'cod','nome'}], 'valores': [{'obra','linha','conta','nome','valor'}], 'avisos': [...]}.
    'linha' = linha folha do DRE a que a conta pertence (ex.: '04.01'); linhas de DRE sem conta vem com conta=None."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ErroDRE("A leitura de PDF não está instalada neste ambiente (falta o pacote pdfplumber).") from exc
    try:
        pdf = pdfplumber.open(io.BytesIO(conteudo))
    except Exception as exc:
        raise ErroDRE("Não consegui abrir este arquivo como PDF.") from exc
    obras_nome, valores, avisos = {}, [], []
    totais_pdf = {}                       # (linha_ou_conta) -> valor da coluna Total
    periodo, vistas_linhas = None, 0
    secao = None                          # linha do DRE em curso; atravessa a quebra de pagina (a pagina seguinte continua as contas)
    with pdf:
        for npag, pag in enumerate(pdf.pages, 1):
            texto = pag.extract_text() or ""
            if "Demonstrativo de Resultado" not in texto:
                continue
            if periodo is None:
                periodo = _cabecalho(texto)
            linhas = texto.splitlines()
            ih = next((i for i, l in enumerate(linhas) if l.startswith("Código Conta")), None)
            if ih is None:
                continue
            cab = linhas[ih]
            codigos = re.findall(r"(\d{3,5}) - ", cab)
            tem_total = bool(re.search(r"\bTotal\s*$", cab))
            n = len(codigos) + (1 if tem_total else 0)
            if not codigos:
                continue
            # nome parcial de cada obra: texto entre o codigo e o proximo codigo, na linha do cabecalho
            partes_cab = re.split(r"\d{3,5} - ", cab.split("Código Conta", 1)[1])
            for cod, nome in zip(codigos, partes_cab[1:]):
                obras_nome.setdefault(cod, re.sub(r"\s*\bTotal\s*$", "", nome).strip(" -"))
            for lin in linhas[ih + 1:]:
                if lin.startswith("12/") or "SIENGE / STARIAN" in lin:
                    continue
                partes = lin.split()
                conta = _RE_CONTA.match(lin)
                if conta:
                    r = _tokens_numericos_finais(partes, n)
                    if not r:
                        continue                          # linha de continuacao do nome
                    nome = re.sub(r"^\d\.\d\d(?:\.\d\d)+\s+-\s+", "", r[0])
                    codc = conta.group(1)
                    for i, v in enumerate(r[1]):
                        if i < len(codigos):
                            if abs(v) > 0.004:
                                valores.append({"obra": codigos[i], "linha": secao, "conta": codc, "nome": nome, "valor": v})
                        else:
                            totais_pdf[codc] = v
                    vistas_linhas += 1
                    continue
                lm = _RE_LINHA.match(lin)
                if lm:
                    r = _tokens_numericos_finais(partes, n)
                    if not r:
                        continue
                    codl = lm.group(1)
                    nome = re.sub(r"^\d\d(?:\.\d\d)?\s+(?:_+\s*)?", "", r[0])
                    if "." in codl:
                        secao = codl
                    else:
                        secao = None
                    for i, v in enumerate(r[1]):
                        if i < len(codigos):
                            if abs(v) > 0.004:
                                valores.append({"obra": codigos[i], "linha": codl, "conta": None, "nome": nome, "valor": v})
                        else:
                            totais_pdf[codl] = v
    if not valores:
        raise ErroDRE("Não achei valores neste PDF. Ele precisa ser o relatório do Sienge 'Demonstrativo de Resultado – Agrupado por Obra – "
                      "DRE GERENCIAL' (a versão com a composição das contas, uma coluna por obra).")
    if not periodo or not periodo["inicio"]:
        avisos.append("Não consegui ler o período no cabeçalho do PDF.")
    elif periodo["inicio"][:7] != periodo["fim"][:7]:
        avisos.append(f"O PDF cobre mais de um mês ({periodo['inicio']} a {periodo['fim']}); o app trabalha com um mês por arquivo.")
    avisos += _conferir(valores, totais_pdf)
    obras = [{"cod": c, "nome": n} for c, n in obras_nome.items()]
    return {"periodo": periodo or {}, "obras": obras, "valores": valores, "avisos": avisos, "linhas_lidas": vistas_linhas}


def _conferir(valores: list, totais_pdf: dict) -> list:
    """Duas checagens: (1) soma das contas de cada obra = linha do DRE da obra; (2) soma das obras = coluna Total do PDF."""
    avisos = []
    contas = {}
    secoes = {}
    for v in valores:
        if v["conta"]:
            contas[(v["linha"], v["obra"])] = contas.get((v["linha"], v["obra"]), 0.0) + v["valor"]
        elif "." in v["linha"]:
            secoes[(v["linha"], v["obra"])] = v["valor"]
    dif = [(k, round(secoes.get(k, 0.0) - contas.get(k, 0.0), 2)) for k in set(secoes) | set(contas) if abs(secoes.get(k, 0.0) - contas.get(k, 0.0)) > 0.05]
    if dif:
        avisos.append(f"{len(dif)} combinação(ões) obra × linha em que a soma das contas não fecha com a linha do DRE (maior diferença R$ {max(abs(d) for _, d in dif):,.2f}).".replace(",", "X").replace(".", ",").replace("X", "."))
    por_total = {}
    for v in valores:
        chave = v["conta"] or v["linha"]
        por_total[chave] = por_total.get(chave, 0.0) + v["valor"]
    fora = [k for k, t in totais_pdf.items() if abs(por_total.get(k, 0.0) - t) > 0.05]
    if fora:
        avisos.append(f"{len(fora)} linha(s)/conta(s) em que a soma das obras difere da coluna Total do PDF.")
    return avisos
