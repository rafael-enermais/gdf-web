# -*- coding: utf-8 -*-
"""Recibos REAIS de set/2026 (nao ficam no repositorio publico). Rodar: GDF_FOLHA_REAL=<pasta com os 2 PDFs> pytest -q app/tests/test_folha_dados_reais.py
Prova: os dois PDFs sao lidos sem aviso (soma dos eventos = total de cada recibo) e a conta de colaboradores/competencia fecha. Nada de nome/valor no codigo."""
import os
from pathlib import Path

import pytest

import importador_folha as IF

pytestmark = pytest.mark.dados_reais


@pytest.fixture(scope="module")
def pasta():
    p = os.environ.get("GDF_FOLHA_REAL")
    if not p or not Path(p).exists():
        pytest.skip("defina GDF_FOLHA_REAL=<pasta com os PDFs de recibos>")
    return Path(p)


def test_recibos_reais_sem_aviso(pasta):
    pdfs = sorted(pasta.glob("Recibos*.pdf"))
    assert len(pdfs) >= 1
    for pdf in pdfs:
        f = IF.ler_recibos_pdf(pdf.read_bytes())
        assert f["competencia"] == "2026-09"
        assert f["avisos"] == [], f["avisos"][:3]
        assert f["recibos_lidos"] >= 2 * len(f["recibos"])          # cada recibo vem em 2 vias (mais as folhas de continuacao)
        assert all(r["subnivel_texto"] for r in f["recibos"])
