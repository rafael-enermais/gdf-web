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
