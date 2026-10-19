# -*- coding: utf-8 -*-
"""Testes do leitor do PDF 'Comparativo Orcado X Realizado Agrupado' (Orcamento ADM). PDF SINTETICO (valores inventados); sem banco."""
import pytest

from dre_pdf_sintetico import pdf_sintetico
from importador_orcamento import ErroOrcamento, ler_orcamento_adm_pdf
from orcamento_sintetico import pdf_orcamento_sintetico


def _linha(r, cod, mes):
    achadas = [l for l in r["linhas"] if l["codigo"] == cod and l["mes"] == mes]
    return achadas[0] if achadas else None


def test_cabecalho_e_meses():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico())
    assert r["cabecalho"] == {"inicio": "2026-01-01", "fim": "2026-06-30", "agrupamento": "11 - ORÇAMENTO TOTAL | ADMINISTRATIVO | 2026"}
    assert r["meses"] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]     # a coluna Total nao vira mes


def test_valores_de_folha_e_total():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico())
    sal = _linha(r, "2.01.01", "2026-04")
    assert (sal["conta"], sal["tipo"], sal["orcado"], sal["realizado"], sal["saldo"]) == ("Salarios de teste | ADM", "R", 1100.0, 1250.75, 150.75)
    tot = _linha(r, "2", "2026-01")                              # 1.050,50 + 500 + 0 = 1.550,50 realizado; orcado 1.500
    assert (tot["tipo"], tot["orcado"], tot["realizado"], tot["saldo"]) == ("T", 1500.0, 1550.5, 50.5)
    assert _linha(r, "2.02.01", "2026-03")["tipo"] == "M"
    assert r["avisos"] == []


def test_conta_com_algum_valor_traz_todos_os_meses_e_conta_zerada_nao_aparece():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico())
    assert {l["mes"] for l in r["linhas"] if l["codigo"] == "1.01.01"} == set(r["meses"])      # R com valor em Jan, Mar e Jun -> 6 meses
    assert _linha(r, "1.01.01", "2026-02")["realizado"] == 0.0
    assert not [l for l in r["linhas"] if l["codigo"] == "1.01.02"]                             # R sempre zerada fica de fora
    assert {l["mes"] for l in r["linhas"] if l["codigo"] == "2.02"} == {"2026-03"}              # T so' nos meses com valor


def test_meses_em_blocos_diferentes_nao_se_misturam():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico())
    assert _linha(r, "2.01.01", "2026-01")["realizado"] == 1050.5       # bloco 1, pagina 2
    assert _linha(r, "2.01.01", "2026-06")["realizado"] == 1210.0       # bloco 2, pagina 2
    assert len(r["linhas"]) == len({(l["codigo"], l["mes"]) for l in r["linhas"]})


def test_rodape_diferenca_e_acumulada():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico())
    # Jan: entradas 10,00 - saidas 1.550,50 (realizado); orcado 0 - 1.500
    assert r["resumo"]["2026-01"]["diferenca"] == {"orcado": -1500.0, "realizado": -1540.5, "saldo": -40.5}
    assert r["resumo"]["2026-02"]["diferenca_acumulada"]["orcado"] == -3000.0
    assert set(r["resumo"]) == set(r["meses"])


def test_sem_coluna_total_tambem_le():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico(com_total=False))
    assert r["meses"][-1] == "2026-06" and r["avisos"] == []


def test_aviso_quando_total_nao_bate_com_os_filhos():
    r = ler_orcamento_adm_pdf(pdf_orcamento_sintetico(com_filho_errado=True))
    assert any("2.01" in a and "2026-01" in a and "realizado" in a for a in r["avisos"])


def test_erros_em_portugues():
    with pytest.raises(ErroOrcamento, match="PDF"):
        ler_orcamento_adm_pdf(b"isto nao e um pdf")
    with pytest.raises(ErroOrcamento, match="Comparativo Orçado X Realizado"):
        ler_orcamento_adm_pdf(pdf_sintetico())                      # PDF de outro relatorio (DRE gerencial)

