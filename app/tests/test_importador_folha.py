# -*- coding: utf-8 -*-
"""Leitor dos recibos de pagamento (folha) com PDF SINTETICO (pessoas e valores inventados)."""
import pytest

import importador_folha as IF
from folha_sintetica import pdf_folha_sintetico


@pytest.fixture(scope="module")
def folha():
    return IF.ler_recibos_pdf(pdf_folha_sintetico())


def test_le_tres_colaboradores_e_ignora_a_segunda_via(folha):
    assert folha["competencia"] == "2026-09"
    assert folha["empresas"] == ["468"]
    assert folha["paginas"] == 4
    assert folha["recibos_lidos"] == 8                       # 4 paginas x 2 vias
    assert [r["cadastro"] for r in folha["recibos"]] == ["10", "11", "12"]     # a colaboradora C tem 2 folhas e conta uma so'
    assert folha["avisos"] == []


def test_cabecalho_do_recibo(folha):
    a = folha["recibos"][0]
    assert (a["nome"], a["cbo"], a["empresa"], a["local"], a["departamento"], a["fl"]) == ("ANA FICTICIA SILVA", "724205", "468", "1", "001.004", "01")
    assert a["cargo"] == "MONTADOR" and a["admissao"] == "2025-02-02"
    assert a["subnivel_texto"] == "OBRA TESTE UM"
    assert (a["total_proventos"], a["total_descontos"], a["liquido"], a["fgts_mes"]) == (3600.00, 300.00, 3300.00, 288.00)


def test_linha_informativa_nao_entra_na_soma(folha):
    a = folha["recibos"][0]
    inf = [e for e in a["eventos"] if e["informativo"]]
    assert [e["ev"] for e in inf] == [840] and inf[0]["provento"] == 0.0
    assert sum(e["provento"] for e in a["eventos"]) == 3600.00
    assert sum(e["desconto"] for e in a["eventos"]) == 300.00


def test_evento_com_valor_na_linha_de_baixo(folha):
    b = folha["recibos"][1]
    consultas = [e for e in b["eventos"] if e["ev"] == 1817]
    assert len(consultas) == 1 and consultas[0]["desconto"] == 90.00
    assert round(sum(e["desconto"] for e in b["eventos"]), 2) == 490.00


def test_recibo_em_duas_folhas_junta_os_eventos_e_acha_o_informativo_pelo_total(folha):
    c = folha["recibos"][2]
    assert {e["ev"] for e in c["eventos"]} == {1, 49, 200, 1031, 1950}
    assert c["total_proventos"] == 3300.00 and c["fgts_mes"] == 264.00
    e200 = [e for e in c["eventos"] if e["ev"] == 200][0]
    assert e200["informativo"] and e200["provento"] == 0.0           # o auxilio doenca aparece no recibo mas nao soma no total
    assert round(sum(e["provento"] for e in c["eventos"]), 2) == 3300.00


def test_resumo_hora_extra_dsr_e_salario(folha):
    a, b, c = (IF.resumo_por_recibo(r) for r in folha["recibos"])
    assert (a["salario"], a["hora_extra"], a["dsr_he"]) == (3000.00, 500.00, 100.00)
    assert (b["salario"], b["hora_extra"], b["dsr_he"]) == (4000.00, 200.00, 0.0)         # 110% = evento 1029
    assert (c["salario"], c["hora_extra"]) == (3000.00, 300.00)                           # 100% = evento 49


def test_arquivo_que_nao_e_pdf_da_erro_em_portugues():
    with pytest.raises(IF.ErroFolha, match="e' um PDF"):
        IF.ler_recibos_pdf(b"isto nao e pdf")
    with pytest.raises(IF.ErroFolha):
        IF.ler_recibos_pdf(b"")


def test_pdf_que_nao_e_de_recibos_da_erro():
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 750, "Outro relatorio qualquer")
    c.showPage()
    c.save()
    with pytest.raises(IF.ErroFolha, match="recibos"):
        IF.ler_recibos_pdf(buf.getvalue())
