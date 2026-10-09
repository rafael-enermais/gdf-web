# -*- coding: utf-8 -*-
"""
GDF - Importador do balancete em PDF ("Balancete – Societário" do sistema contabil).

O PDF e' lido so' como TEXTO (pdfplumber, Python puro): o arquivo original nunca e' alterado, regravado ou assinado de novo.
Cada linha de conta tem:   Conta [S] Classificacao Nome [Ult. Mov. dd/mm/aa] Saldo Ant. Debito Credito Saldo
(a coluna "Ult. Mov." aparece em alguns balancetes e em outros nao; os dois jeitos sao aceitos).
Devolve o MESMO formato do importador CSV: (cabecalho, contas) -> pode ser usado no lugar dele, com as mesmas conferencias.
Sem banco, sem rede.
"""
from __future__ import annotations

import hashlib
import io
import re

from importador_csv import ErroImportacao, _data, _n, classificar_periodo

_NUM = r"\(?-?[\d\.]*\d,\d{2}\)?"
_LINHA = re.compile(
    r"^\s*(\d+)\s+(S\s+)?(\d(?:\.\d+)*)\s+(.*?)\s+(?:(\d{2}/\d{2}/\d{2})\s+)?(" + _NUM + r")\s+(" + _NUM + r")\s+(" + _NUM + r")\s+(" + _NUM + r")\s*$"
)
# linha que "parece" conta (comeca com codigo + classificacao) mas nao casou com o padrao acima
_PARECE_CONTA = re.compile(r"^\s*\d+\s+(S\s+)?\d(?:\.\d+)+\s")


def _texto_pdf(raw: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as exc:                                   # pragma: no cover
        raise ErroImportacao("A leitura de PDF não está instalada neste ambiente (falta o pacote pdfplumber).") from exc
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if not pdf.pages:
                raise ErroImportacao("O PDF não tem páginas.")
            partes = [(p.extract_text() or "") for p in pdf.pages]
    except ErroImportacao:
        raise
    except Exception as exc:
        raise ErroImportacao("Não consegui abrir o PDF (arquivo danificado ou protegido).") from exc
    return "\n".join(partes)


def ler_bytes(raw: bytes, nome_arquivo: str = "balancete.pdf"):
    """Le o PDF (bytes). Retorna (cabecalho, contas). Levanta ErroImportacao se nao for o balancete esperado."""
    if not raw.startswith(b"%PDF"):
        raise ErroImportacao("Este arquivo não é um PDF.")
    sha = hashlib.sha256(raw).hexdigest()
    txt = _texto_pdf(raw)
    if not txt.strip():
        raise ErroImportacao("O PDF não tem texto selecionável (parece ser uma imagem escaneada). Envie o PDF original do sistema contábil ou o CSV.")
    cab = {"arquivo": nome_arquivo, "sha256": sha, "formato": "PDF"}
    m = re.search(r"CNPJ:\s*([\d\./-]+)", txt)
    cab["cnpj"] = m.group(1) if m else None
    m = re.search(r"Per\S*odo:\s*(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})", txt)
    if not m:
        raise ErroImportacao("Não achei a linha 'Período: dd/mm/aaaa a dd/mm/aaaa' no PDF. Este é o balancete do sistema contábil?")
    cab["ini"], cab["fim"] = _data(m.group(1)), _data(m.group(2))
    cab["tipo"], cab["periodo"] = classificar_periodo(cab["ini"], cab["fim"])
    m = re.search(r"^\s*\d+\s+(.+?)\s+\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+P[aá]g", txt, re.M)
    cab["empresa"] = m.group(1).strip() if m else None
    if not cab["cnpj"]:
        raise ErroImportacao("Não achei o CNPJ da empresa no cabeçalho do PDF.")
    contas, vistos, ignoradas = [], set(), []
    for ln in txt.splitlines():
        r = _LINHA.match(ln)
        if not r:
            if _PARECE_CONTA.match(ln):
                ignoradas.append(ln.strip())
            continue
        cid, s, cl, nome, _um, a, d, c, sl = r.groups()
        chave = (cid, cl)
        if chave in vistos:                      # linha repetida (quebra de pagina)
            continue
        vistos.add(chave)
        contas.append({"id": cid, "sint": bool(s), "cl": cl, "nome": nome.strip(),
                       "ant": _n(a), "deb": _n(d), "cred": _n(c), "sal": _n(sl)})
    if not contas:
        raise ErroImportacao("Não encontrei nenhuma conta no PDF. Confira se é o 'Balancete – Societário' (Débito/Crédito).")
    cab["n_contas"] = len(contas)
    cab["ignoradas"] = ignoradas
    return cab, contas


def ler_pdf(caminho: str):
    with open(caminho, "rb") as f:
        raw = f.read()
    return ler_bytes(raw, caminho.replace("\\", "/").split("/")[-1])
