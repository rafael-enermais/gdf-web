# -*- coding: utf-8 -*-
"""Diagnostico dos impostos sobre o faturamento: so' nomes, contagens e proporcoes (o log do Actions e' publico)."""
import importlib.util
import json
from pathlib import Path

from dados_sienge import income

_ESPEC = importlib.util.spec_from_file_location("diag_imp", Path(__file__).resolve().parents[2] / "scripts" / "diagnostico_receita_impostos_gdf.py")
D = importlib.util.module_from_spec(_ESPEC)
_ESPEC.loader.exec_module(D)


def _regs():
    r = income()
    r[0]["taxAmount"] = 155.0                                   # campo hipotetico no nivel do titulo
    r.append(dict(r[0], billId=51, installmentId=1, originalAmount=3000.0, taxAmount=0.0))
    return r


def test_resumo_traz_campos_e_proporcoes():
    res = D.resumir(_regs())
    assert res["titulos"] == 2 and "taxAmount" in res["campos_do_titulo"]
    assert res["numericos_do_titulo_pct_do_original"]["taxAmount"] == (3.1, 1)                   # 155 / (2000 + 3000) = 3,1 %
    rec = res["listas"]["receipts"]
    assert rec["itens"] == 2 and "taxAmount" in rec["campos"]
    assert rec["numericos_pct_do_original"]["taxAmount"] == (8.0, 2)   # 400 / 5000
    assert res["contas_do_plano_nas_categorias"] == {"1.01.01.01": 2}


def test_resumo_nao_imprime_valores_em_reais_nem_nomes():
    txt = json.dumps(D.resumir(_regs()), ensure_ascii=False)
    for proibido in ("CLIENTE TESTE", "CONSTRUTORA", "ENERGIA", "2000.0", "3000.0", "5000"):
        assert proibido not in txt


def test_resumo_lista_vazia_nao_quebra():
    assert D.resumir([])["titulos"] == 0
