# -*- coding: utf-8 -*-
"""GDF - Porta unica de entrada dos balancetes: CSV ou PDF do sistema contabil (mesmo resultado, mesmas conferencias)."""
from __future__ import annotations

import importador_csv
import importador_pdf
from importador_csv import ErroImportacao

EXTENSOES = ("csv", "pdf")


def ler_bytes(raw: bytes, nome_arquivo: str):
    """Escolhe o leitor pelo conteudo (assinatura %PDF) e, na duvida, pela extensao. Retorna (cabecalho, contas)."""
    nome = (nome_arquivo or "").lower()
    if raw[:5] == b"%PDF-" or nome.endswith(".pdf"):
        cab, contas = importador_pdf.ler_bytes(raw, nome_arquivo)
    elif nome.endswith(".csv") or raw[:5] != b"%PDF-":
        cab, contas = importador_csv.ler_bytes(raw, nome_arquivo)
        cab.setdefault("formato", "CSV")
    else:                                                          # pragma: no cover
        raise ErroImportacao("Formato não aceito: envie o balancete em CSV ou PDF.")
    return cab, contas
