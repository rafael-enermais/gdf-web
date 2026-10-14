# -*- coding: utf-8 -*-
"""Leitor do PDF do DRE gerencial do Sienge: PDF sintetico (sem dados reais)."""
import pytest

from dre_pdf_sintetico import pdf_sintetico
import importador_dre as D


def test_le_periodo_obras_e_valores():
    r = D.ler_dre_pdf(pdf_sintetico())
    assert r["periodo"]["inicio"] == "2026-09-01" and r["periodo"]["fim"] == "2026-09-30" and r["periodo"]["analise"] == "Comprometido"
    assert [o["cod"] for o in r["obras"]] == ["100", "101", "102"]
    assert r["avisos"] == [], r["avisos"]
    contas = {(v["obra"], v["conta"]): v["valor"] for v in r["valores"] if v["conta"]}
    assert contas[("100", "1.01.01.01")] == 1000.0 and contas[("102", "1.01.01.01")] == 250.0
    # a conta da pagina seguinte continua na secao 04.01 e a de valor zero nao entra
    enc = [v for v in r["valores"] if v["conta"] == "2.01.02.02"]
    assert {v["obra"]: v["valor"] for v in enc} == {"100": -200.0, "101": -150.0} and all(v["linha"] == "04.01" for v in enc)
    assert ("102", "2.01.02.02") not in contas
    assert any(v["linha"] == "04" and v["obra"] == "101" and v["conta"] is None and v["valor"] == -200.0 for v in r["valores"])


def test_aviso_quando_total_do_pdf_nao_fecha_com_as_obras():
    r = D.ler_dre_pdf(pdf_sintetico(com_total_errado=True))
    assert any("coluna Total" in a for a in r["avisos"])


def test_arquivo_que_nao_e_pdf_e_pdf_de_outro_relatorio():
    with pytest.raises(D.ErroDRE, match="PDF"):
        D.ler_dre_pdf(b"isto nao e pdf")
    import io
    from reportlab.pdfgen import canvas
    b = io.BytesIO(); c = canvas.Canvas(b); c.drawString(50, 800, "Outro relatorio qualquer"); c.save()
    with pytest.raises(D.ErroDRE, match="Não achei valores"):
        D.ler_dre_pdf(b.getvalue())
