# -*- coding: utf-8 -*-
"""Leitor da planilha de projecao de receitas das obras (xlsx) com planilha SINTETICA (valores inventados)."""
import io

import openpyxl
import pytest

import importador_projecao as IP


def _xlsx(linhas, cab_mes="set/26", total=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["CONTRATO", "CLIENTE", "OBRA", "CATEGORIA", "NATUREZA", "EMPRESA / FORNECEDOR", cab_mes, "CUSTOS", "BDI"])
    for l in linhas:
        ws.append(l)
    if total:
        r = sum(l[6] for l in linhas); c = sum(l[7] for l in linhas); b = sum(l[8] for l in linhas)
        ws.append([None, None, None, None, None, "TOTAL ", r, c, b])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LINHAS = [
    ["Contrato Um (PR)", "CLIENTE A", "LOTE 11", "INDIRETO", None, "CONSTRUTORA", 1000.0, 700.0, 300.0],
    ["Contrato Um (PR)", "CLIENTE A", "LOTE 11", "INDIRETO", None, "ENERGIA", 500.0, 350.0, 150.0],
    ["Contrato Dois (SP)", "CLIENTE B", " OPGW II", "INDIRETO", None, "ENERGIA", 2000.0, 1400.0, 600.0],
]


def test_le_mes_linhas_e_total():
    d = IP.ler_projecao_xlsx(_xlsx(LINHAS))
    assert d["mes"] == "2026-09" and len(d["linhas"]) == 3
    assert d["total"] == {"valor_mes": 3500.0, "custos": 2450.0, "bdi": 1050.0}
    assert d["total_planilha"] == d["total"] and d["avisos"] == []
    assert d["linhas"][0]["obra"] == "LOTE 11" and d["linhas"][0]["empresa"] == "CONSTRUTORA"


def test_agrupa_por_obra_e_casa_com_o_dre():
    d = IP.ler_projecao_xlsx(_xlsx(LINHAS))
    por = IP.projecao_por_obra(d["linhas"])
    assert [(o["obra"], o["receita"], o["bdi"]) for o in por] == [("OPGW II", 2000.0, 600.0), ("LOTE 11", 1500.0, 450.0)]
    dre = {"103": "ANASTACIO - LOTE 11 - 001/2024", "111": "ELETROBRAS - OPGW II - RJ | SP | ES", "118": "ELETROBRAS - CHESF - OPGW III NORDESTE"}
    assert IP.casar_obra_dre("OPGW II", dre) == "111"                       # 'OPGW II' nao casa com 'OPGW III'
    assert IP.casar_obra_dre("LOTE 11", dre) == "103"
    assert IP.casar_obra_dre("COAMO", dre) is None
    assert IP.casar_obra_dre("OPGW", dre) is None                           # mais de uma obra casa -> sem correspondencia


def test_avisos_quando_nao_fecha():
    errada = [list(l) for l in LINHAS]
    errada[0][8] = 310.0                                                    # receita != custos + BDI
    d = IP.ler_projecao_xlsx(_xlsx(errada, total=False))
    assert any("nao fecha com custos + BDI" in a for a in d["avisos"])


def test_mes_do_cabecalho_com_ano_de_quatro_digitos_e_outro_mes():
    assert IP.ler_projecao_xlsx(_xlsx(LINHAS, cab_mes="out/2026"))["mes"] == "2026-10"


def test_erros_em_portugues():
    with pytest.raises(IP.ErroProjecao, match="xlsx"):
        IP.ler_projecao_xlsx(b"nao e planilha")
    wb = openpyxl.Workbook(); wb.active.append(["A", "B"]); buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(IP.ErroProjecao, match="cabecalho"):
        IP.ler_projecao_xlsx(buf.getvalue())
    with pytest.raises(IP.ErroProjecao, match="mes da projecao"):
        IP.ler_projecao_xlsx(_xlsx(LINHAS, cab_mes="mes qualquer"))


def test_comparacao_usa_nomes_completos_quando_o_dre_so_tem_o_cliente():
    """No DRE real o nome da obra e' so' 'ELETROBRAS'; a planilha diz 'LOTE 03' / 'OPGW II'. Os nomes completos do de-para fazem o casamento."""
    import painel_db as P
    ob = {"linhas": [{"obra": "104", "nome": "ELETROBRAS", "receita": 100.0, "custo": -60.0, "bdi": 40.0},
                     {"obra": "111", "nome": "ELETROBRAS", "receita": 200.0, "custo": -150.0, "bdi": 50.0},
                     {"obra": "118", "nome": "ELETROBRAS", "receita": 300.0, "custo": -100.0, "bdi": 200.0}],
          "total": {"receita": 600.0}}
    proj = {"linhas": [{"obra": "LOTE 03", "cliente": "AXIA", "valor_mes": 150.0, "custos": 100.0, "bdi": 50.0},
                       {"obra": "OPGW II", "cliente": "AXIA", "valor_mes": 250.0, "custos": 170.0, "bdi": 80.0}]}
    sem = P.projecao_x_realizado(proj, ob)
    assert sem["linhas"] == [] and len(sem["sem_correspondencia"]) == 2                      # so' com o nome do cliente nao casa
    extra = {"104": "AXIA — Lote 03 ELETROBRAS - SPE NOVA ERA - LOTE 03 - 001/2024", "111": "AXIA — OPGW RJ|SP|ES ELETROBRAS - OPGW II - RJ | SP | ES",
             "118": "ELETROBRAS - CHESF - OPGW III NORDESTE"}
    r = P.projecao_x_realizado(proj, ob, extra)
    por = {x["codigo"]: x for x in r["linhas"]}
    assert set(por) == {"104", "111"} and r["sem_correspondencia"] == []                      # OPGW II nao casa com OPGW III (118)
    assert por["104"]["desvio"] == -50.0 and por["111"]["desvio"] == -50.0
