# -*- coding: utf-8 -*-
"""Layout do PDF: o texto de apoio dos quadros (KPI) nunca pode escapar do quadro."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reportlab.pdfbase import pdfmetrics

import relatorio_pdf as RP


def _cabe(sub, larg, base, h, maxl):
    RP._registrar_fontes()
    lns, fs = RP._sub_cabe(sub, larg, base, h, maxl)
    ultima = base + (len(lns) - 1) * 8.6                      # linha de base da última linha, medida a partir do topo do quadro
    assert ultima <= h - 4, (sub, lns, ultima, h)
    for ln in lns:
        assert pdfmetrics.stringWidth(ln, "P", fs) <= larg + 0.5, (ln, fs)
    return lns, fs


def test_texto_curto_fica_em_uma_linha_com_fonte_normal():
    lns, fs = _cabe("Capital social + AFAC", 130, 47, 52, 2)
    assert lns == ["Capital social + AFAC"] and fs == 6.6


def test_texto_longo_em_quadro_baixo_nao_escapa():
    # caso real: 'Resultado financeiro' com texto de duas linhas num quadro de 52 pt
    lns, _ = _cabe("Receitas menos despesas financeiras do acumulado de janeiro a agosto", 126, 47, 52, 2)
    assert len(lns) == 1 and lns[0].endswith("…")


def test_quadro_alto_aceita_duas_linhas():
    lns, _ = _cabe("Custos de construção sem a receita correspondente (ver nota na página 4)", 230, 49, 66, 2)
    assert 1 <= len(lns) <= 2


