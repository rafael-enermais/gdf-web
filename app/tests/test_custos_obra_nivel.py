"""Custos por obra em 7 categorias (relatorio da contabilidade, nivel resumido): mapa de contas + soma + consulta ao banco."""
import pytest

import custos_obra_nivel as C
import painel_db as P

pg = pytest.mark.pg


def test_mapa_cobre_as_categorias_do_relatorio():
    assert len(C.MAPA) == 383 and set(C.MAPA.values()) == {"01.01", "02.01", "03.01", "03.02", "04.01", "05.03", "05.04", "06.01", "06.02", "06.03", "06.04", "07.01"}
    assert C.MAPA["2.01.02.01"] == "01.01" and C.MAPA["2.01.02.16"] == "05.03" and C.MAPA["2.01.04.01"] == "02.01"
    assert {c for c, _ in C.CATEGORIAS if "." in c} >= set(C.MAPA.values())                    # toda categoria usada tem nome na tabela


def test_soma_filtra_por_obra_e_mes_e_agrupa_demais():
    linhas = [("100", "2026-09", "2.01.02.01", -100.0), ("100", "2026-08", "2.01.04.01", -50.0), ("X", "2026-09", "2.01.02.01", -10.0),
              ("sem de-para", "2026-09", "2.01.02.01", -1.0), ("100", "2026-09", "9.99.99", -5.0)]                  # conta fora do mapa nao entra
    dest = lambda o: o if o == "100" else "DEM"                                                                          # noqa: E731
    assert C.por_categoria(linhas) == {"01.01": 111.0, "02.01": 50.0, "01": 111.0, "02": 50.0, "03": 0, "04": 0, "05": 0, "06": 0, "07": 0, "00": 161.0}
    assert C.por_categoria(linhas, ["DEM"], dest)["00"] == 11.0                                                          # so' "Demais obras"
    assert C.por_categoria(linhas, ["100"], dest, mes="2026-09")["00"] == 100.0
    assert C.por_categoria(linhas, ["100", "DEM"], dest)["00"] == 161.0                                                  # varias marcadas somam
    tab = C.tabela(linhas, ["100"], dest, "2026-09")
    assert tab[0]["codigo"] == "00" and tab[0]["periodo"] == 150.0 and tab[0]["mes"] == 100.0 and round(tab[0]["pct"], 4) == 1.0
    assert [x["codigo"] for x in tab if "." in x["codigo"]] == ["01.01", "02.01"]                                       # subcategorias sem valor saem
    assert C.tabela([]) and C.tabela([])[0]["periodo"] == 0.0


@pg
def test_consulta_do_banco_so_traz_contas_das_categorias(conn):
    from test_painel_db_pg import _ingerir
    _ingerir(conn, lado="P", tipo="P")
    linhas = P.custos_obra_linhas(conn, "2026-09", "2026-09")
    assert isinstance(linhas, list)
    assert all(len(x) == 4 and x[2] in C.MAPA and x[1] == "2026-09" for x in linhas)
    assert P.custos_obra_linhas(conn, "2019-01", "2019-01") == []


def test_contas_das_categorias_marcar_pai_inclui_filhos():
    assert C.contas_das_categorias([]) == set()
    assert C.contas_das_categorias(["00"]) == set(C.MAPA)
    assert C.contas_das_categorias(["01.01"]) == set(C.CONTAS_POR_CATEGORIA["01.01"])
    assert C.contas_das_categorias(["05"]) == set(C.CONTAS_POR_CATEGORIA["05.03"]) | set(C.CONTAS_POR_CATEGORIA["05.04"])
    # marcar so' uma subcategoria nao puxa a irma
    assert not (C.contas_das_categorias(["05.04"]) & set(C.CONTAS_POR_CATEGORIA["05.03"]))


def test_obras_custo_no_padrao_da_contabilidade_e_bdi_acompanha():
    """Custos = DRE 04+06+08+09+10+12 (ou 'CP' da API); BDI = receita + custos; custo_04 guarda so' a linha 04."""
    por_obra = {
        "100": {"nome": "A", "linhas": {"01": 1000.0, "04": -400.0, "06": -10.0, "08": -5.0, "09": -1.0, "10": -4.0, "12": -20.0}},   # PDF: soma das linhas
        "101": {"nome": "B", "linhas": {"01": 500.0, "04": -100.0, "CP": -130.0}},                                                        # API: CP pronto
        "999": {"nome": "fora", "linhas": {"01": 10.0, "04": -2.0, "CP": -3.0}},                                                          # sem de-para proprio -> Demais
    }
    ob = P._montar_obras(por_obra, {"100", "101"}, None, "x", "API")
    por = {l["obra"]: l for l in ob["linhas"]}
    assert por["100"]["custo"] == -440.0 and por["100"]["custo_04"] == -400.0 and por["100"]["bdi"] == 560.0
    assert por["101"]["custo"] == -130.0 and por["101"]["bdi"] == 370.0
    assert por["DEM"]["custo"] == -3.0 and por["DEM"]["custo_04"] == -2.0
    assert ob["total"]["custo"] == -573.0 and ob["total"]["custo_04"] == -502.0
    assert ob["total"]["bdi"] == round(1510.0 - 573.0, 2)
    # varios meses somados mantem o padrao e o custo_04
    soma = P.somar_obras([ob, ob])
    assert soma["total"]["custo"] == -1146.0 and soma["total"]["custo_04"] == -1004.0 and soma["total"]["bdi"] == round(3020.0 - 1146.0, 2)
