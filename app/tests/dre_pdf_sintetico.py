# -*- coding: utf-8 -*-
"""Gera um PDF SINTETICO no layout do 'DRE gerencial - composicao das contas' do Sienge (valores inventados)."""
import io

from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas


def br(v):
    """Formato brasileiro com milhar, como no PDF do Sienge."""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pagina(c, cabecalho, linhas):
    y = 560
    for t in ["Demonstrativo de Resultado - Agrupado por Obra - DRE GERENCIAL", "Período 01/09/2026 a 30/09/2026",
              "Tipo de análise Comprometido", "Seleção por Data de emissão", cabecalho] + linhas + ["SIENGE / STARIAN"]:
        c.drawString(20, y, t)
        y -= 14
    c.showPage()


def pdf_sintetico(com_total_errado: bool = False) -> bytes:
    """2 grupos de colunas: (100, 101) e (102 + Total). Receita e custo; a conta de custo continua na pagina seguinte do grupo 1."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    cab1 = "Código Conta 100 - OBRA UM - 101 - OBRA DOIS"
    cab2 = "Código Conta 102 - OBRA TRES Total"
    tot_rec = 1750.00 + (5.0 if com_total_errado else 0)
    _pagina(c, cab1, ["01 (+) RECEITA OPERACIONAL BRUTA 1.000,00 500,00",
                      "01.01 Receita de Serviços 1.000,00 500,00",
                      "1.01.01.01 - Receitas de contrato 1.000,00 500,00",
                      "04 (-) CUSTOS OPERACIONAIS DIRETOS -300,00 -200,00",
                      "04.01 Mão de Obra Direta -300,00 -200,00",
                      "2.01.02.01 - Salarios -100,00 -50,00"])
    _pagina(c, cab1, ["2.01.02.02 - Encargos -200,00 -150,00"])           # continuacao da secao 04.01 na pagina seguinte
    _pagina(c, cab2, ["01 (+) RECEITA OPERACIONAL BRUTA 250,00 " + br(tot_rec),
                      "01.01 Receita de Serviços 250,00 " + br(tot_rec),
                      "1.01.01.01 - Receitas de contrato 250,00 " + br(tot_rec),
                      "04 (-) CUSTOS OPERACIONAIS DIRETOS -100,00 -600,00",
                      "04.01 Mão de Obra Direta -100,00 -600,00",
                      "2.01.02.01 - Salarios -100,00 -250,00",
                      "2.01.02.02 - Encargos 0,00 -350,00"])
    c.save()
    return buf.getvalue()
