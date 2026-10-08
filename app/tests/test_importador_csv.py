# -*- coding: utf-8 -*-
import pytest

import importador_csv as I
from dados_sinteticos import csv_texto, gerar_meses

MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100)])


def test_mensal_ida_e_volta():
    raw = csv_texto(MESES["2026-01"], ini="01/01/2026", fim="31/01/2026")
    cab, contas = I.ler_bytes(raw, "jan.csv")
    assert (cab["tipo"], cab["periodo"], cab["cnpj"], cab["empresa"]) == ("MENSAL", "2026-01", "00.000.000/0001-91", "EMPRESA SINTETICA LTDA")
    assert len(contas) == len(MESES["2026-01"]) == cab["n_contas"]
    for a, b in zip(contas, MESES["2026-01"]):
        assert (a["cl"], a["sint"], a["id"]) == (b["cl"], b["sint"], b["id"])
        assert all(abs(a[k] - b[k]) < 0.005 for k in ("ant", "deb", "cred", "sal"))


def test_acumulado_e_hash_estavel():
    raw = csv_texto(MESES["2026-02"], ini="01/01/2026", fim="28/02/2026")
    cab, _ = I.ler_bytes(raw)
    assert cab["tipo"] == "ACUMULADO" and cab["periodo"] == "2026-02"
    assert cab["sha256"] == I.ler_bytes(raw)[0]["sha256"]
    assert str(cab["ini"]) == "2026-01-01" and str(cab["fim"]) == "2026-02-28"


@pytest.mark.parametrize("ini,fim", [("01/02/2026", "15/02/2026"), ("01/03/2026", "28/04/2026"), ("01/01/2026", "30/06/2026" if False else "29/06/2026")])
def test_periodo_nao_aceito(ini, fim):
    with pytest.raises(I.ErroImportacao):
        I.ler_bytes(csv_texto(MESES["2026-01"], ini=ini, fim=fim))


def test_arquivo_errado():
    with pytest.raises(I.ErroImportacao, match="Período"):
        I.ler_bytes(b"isto nao e' um balancete")
    with pytest.raises(I.ErroImportacao):
        I.ler_bytes(csv_texto([], ini="01/01/2026", fim="31/01/2026"))


def test_numero_invalido():
    raw = csv_texto(MESES["2026-01"], ini="01/01/2026", fim="31/01/2026").replace(b"1.000.000,00", b"1.000.000,0x", 1)
    with pytest.raises(I.ErroImportacao, match="Número"):
        I.ler_bytes(raw)


def test_linha_repetida_na_quebra_de_pagina_e_ignorada():
    c = MESES["2026-01"]
    cab, contas = I.ler_bytes(csv_texto(c + [c[0]], ini="01/01/2026", fim="31/01/2026"))
    assert len(contas) == len(c)


def test_negativo_com_parenteses_e_sinal():
    assert I._n("(1.234,56)") == -1234.56 and I._n("-1.234,56") == -1234.56 and I._n("1.234,56") == 1234.56 and I._n("") == 0.0
