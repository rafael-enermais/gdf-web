# -*- coding: utf-8 -*-
import pytest

import importador as ENTRADA
import importador_csv as ICSV
import importador_pdf as I
from dados_sinteticos import csv_texto, gerar_meses, pdf_balancete

MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100)])


@pytest.mark.parametrize("ult_mov", [False, True])
def test_pdf_mensal_ida_e_volta(ult_mov):
    raw = pdf_balancete(MESES["2026-01"], ini="01/01/2026", fim="31/01/2026", ult_mov=ult_mov, linhas_por_pagina=25)
    cab, contas = I.ler_bytes(raw, "jan.pdf")
    assert (cab["tipo"], cab["periodo"], cab["cnpj"], cab["empresa"], cab["formato"]) == ("MENSAL", "2026-01", "00.000.000/0001-91", "EMPRESA SINTETICA LTDA", "PDF")
    assert len(contas) == len(MESES["2026-01"]) == cab["n_contas"] and not cab["ignoradas"]
    for a, b in zip(contas, MESES["2026-01"]):
        assert (a["cl"], a["sint"], a["id"]) == (b["cl"], b["sint"], b["id"])
        assert all(abs(a[k] - b[k]) < 0.005 for k in ("ant", "deb", "cred", "sal"))


def test_pdf_e_csv_dao_o_mesmo_resultado():
    cp, c1 = I.ler_bytes(pdf_balancete(MESES["2026-02"], ini="01/01/2026", fim="28/02/2026"), "a.pdf")
    cc, c2 = ICSV.ler_bytes(csv_texto(MESES["2026-02"], ini="01/01/2026", fim="28/02/2026"), "a.csv")
    assert c1 == c2 and cp["tipo"] == cc["tipo"] == "ACUMULADO" and cp["periodo"] == cc["periodo"]
    assert cp["sha256"] != cc["sha256"]          # arquivos diferentes (a barreira de periodo ja ativo cobre o caso)


def test_entrada_unica_escolhe_pelo_conteudo():
    assert ENTRADA.ler_bytes(pdf_balancete(MESES["2026-01"]), "qualquer.coisa")[0]["formato"] == "PDF"
    assert ENTRADA.ler_bytes(csv_texto(MESES["2026-01"]), "jan.csv")[0]["formato"] == "CSV"
    # PDF renomeado como .csv continua sendo lido como PDF
    assert ENTRADA.ler_bytes(pdf_balancete(MESES["2026-01"]), "jan.csv")[0]["formato"] == "PDF"


def test_pdf_invalido():
    with pytest.raises(I.ErroImportacao, match="não é um PDF"):
        I.ler_bytes(b"texto qualquer")
    with pytest.raises(I.ErroImportacao, match="abrir o PDF"):
        I.ler_bytes(b"%PDF-1.4 lixo")
    with pytest.raises(I.ErroImportacao):
        I.ler_bytes(pdf_balancete(MESES["2026-01"], ini="01/01/2026", fim="15/01/2026"))


def test_pdf_sem_contas_ou_sem_periodo():
    with pytest.raises(I.ErroImportacao):
        I.ler_bytes(pdf_balancete([], ini="01/01/2026", fim="31/01/2026"))


def test_pdf_linha_que_parece_conta_mas_nao_casa_vai_para_ignoradas():
    raw = pdf_balancete(MESES["2026-01"], ini="01/01/2026", fim="31/01/2026", linhas_extras=("9999 1.1.99.001.001 Conta com valor quebrado 10,5 0,00 0,00 10,5",))
    cab, contas = I.ler_bytes(raw)
    assert len(contas) == len(MESES["2026-01"])
    assert len(cab["ignoradas"]) == 1 and "9999" in cab["ignoradas"][0]
