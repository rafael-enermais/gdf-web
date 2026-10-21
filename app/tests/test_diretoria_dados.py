# -*- coding: utf-8 -*-
"""Painel da Diretoria (dados do acumulado, pessoas e PJ): funcoes puras com dados SINTETICOS + leitura no Postgres descartavel."""
import pytest

import diretoria_dados as DD
import painel_db as P
import sienge_api as S
from dados_sienge import outcome


def _l(mes, cod, nome, credor, cc, obra, grupo, valor):
    return {"mes": mes, "plano_cod": cod, "plano_nome": nome, "credor": credor, "cc": cc, "obra": obra, "grupo": grupo, "valor": valor}


BASE = [
    _l("2026-08", "2.01.01.04", "Material | Obra", "FORN A", "CC 1", "103", "OBRA", 100.0),
    _l("2026-09", "2.01.01.04", "Material | Obra", "FORN A", "CC 1", "103", "OBRA", 300.0),
    _l("2026-09", "2.01.01.04", "Material | Obra", "FORN B", "CC 2", "104", "OBRA", 200.0),
    _l("2026-09", "2.03.01.02", "Tarifas | ADM", "BANCO", "SEDE", "ADM", "ADM", 50.0),
    _l("2026-09", "2.01.02.01", "Salários PJ | Obra", "PJ UM", "CC 1", "103", "OBRA", 5000.0),
    _l("2026-09", "2.01.02.01", "Salários PJ | Obra", "PJ UM", "CC 2", "104", "OBRA", 1000.0),      # recebe mais na 103 -> alocado na 103
    _l("2026-09", "2.01.02.01", "Salários PJ | Obra", "PJ DOIS", "CC 2", "104", "OBRA", 4000.0),
    _l("2026-09", "2.02.01.01", "Salários PJ | ADM", "PJ TRES", "SEDE", "ADM", "ADM", 7000.0),
    _l("2026-09", "2.02.01.01", "Salários PJ | ADM", "PJ ESTORNO", "SEDE", "ADM", "ADM", 0.0),
    _l("2026-09", "2.01.02.03", "Horas Extras | Obra", "COLAB X", "CC 1", "103", "OBRA", 800.0),
    _l("2026-09", "2.02.01.07", "Vale Alimentação | ADM", "VR", "SEDE", "ADM", "ADM", 200.0),
    _l("2026-09", "2.01.02.03", "Horas Extras | ADM", "COLAB Y", "SEDE", "ADM", "ADM", 100.0),
    _l("2026-08", "2.01.02.03", "Horas Extras | Obra", "COLAB X", "CC 1", "103", "OBRA", 400.0),
]


def test_nome_e_pj():
    assert DD.nome_conta_pessoas("Horas Extras | Obra") == "Horas Extras" == DD.nome_conta_pessoas("Horas Extras | ADM")
    assert DD.nome_conta_pessoas("Seguros de vida | pessoas | Obra") == "Seguros de vida | pessoas"
    assert DD.eh_pj("2.01.02.01", "x") and DD.eh_pj("9.9.9", "Salários PJ | Obra") and not DD.eh_pj("2.01.02.10", "Salários CLT | Obra")


def test_despesas_e_pessoas_separadas():
    df = DD.para_df(BASE)
    desp = DD.despesas_df(df, ["2.01.02", "2.02.01"])
    assert set(desp["plano_cod"]) == {"2.01.01.04", "2.03.01.02"}
    assert DD.total_por(desp)[0] == ("Material | Obra", 600.0)
    pes = DD.pessoas_df(df)
    assert set(pes["plano_nome"]) == {"Horas Extras", "Vale Alimentação"}              # PJ/CLT/premiacoes fora; sufixo Obra/ADM unido
    assert DD.serie_mensal(pes, ["2026-08", "2026-09", "2026-10"], "Horas Extras") == [400.0, 900.0, 0.0]


def test_drill_credor_e_obra():
    desp = DD.despesas_df(DD.para_df(BASE), ["2.01.02", "2.02.01"])
    cr = DD.agrupar(desp, "credor", "2026-09", conta="Material | Obra")
    assert cr["total"] == 600.0 and cr["n"] == 2
    assert cr["linhas"][0] == {"chave": "FORN A", "acumulado": 400.0, "mes": 300.0}
    ob = DD.agrupar(desp, "cc", "2026-09", conta="Material | Obra", credor="FORN A")
    assert ob["linhas"] == [{"chave": "CC 1", "acumulado": 400.0, "mes": 300.0}]
    assert DD.agrupar(desp, "cc", "2026-09", conta="nao existe") == {"linhas": [], "n": 0, "total": 0.0}


def test_tabela_pessoas_por_colaborador():
    pes = DD.pessoas_df(DD.para_df(BASE))
    t = DD.tabela_pessoas(pes, "2026-09", colab_mes=10, colab_soma_antes=40)
    he = next(x for x in t if x["conta"] == "Horas Extras")
    assert he["mes"] == 900.0 and he["acum_antes"] == 400.0 and he["por_colab_mes"] == 90.0 and he["por_colab_acum"] == 10.0
    assert he["variacao"] == pytest.approx(8.0) and he["pct_mes"] == pytest.approx(900 / 1100, abs=1e-4)
    assert t[0]["conta"] == "Horas Extras"                                              # ordenado pelo valor do mes
    sem = DD.tabela_pessoas(pes, "2026-09", None, None)
    assert sem[0]["por_colab_mes"] is None and sem[0]["variacao"] is None and sem[0]["mes"] == 900.0


def test_pj_por_colaborador_aloca_onde_recebeu_mais():
    pj = DD.pj_do_mes(DD.para_df(BASE), "2026-09")
    assert (pj["total"], pj["obra"], pj["adm"]) == (3, 2, 1)                            # estorno zerado nao conta
    assert pj["por_obra"] == {"103": 1, "104": 1}
    assert {c["credor"]: c["destino"] for c in pj["colaboradores"]} == {"PJ UM": "103", "PJ DOIS": "104", "PJ TRES": "ADM"}
    assert pj["colaboradores"][0]["credor"] == "PJ TRES" and pj["colaboradores"][0]["valor"] == 7000.0
    assert next(c for c in pj["colaboradores"] if c["credor"] == "PJ UM")["valor"] == 6000.0     # soma dos dois centros
    assert DD.pj_do_mes(DD.para_df([]), "2026-09") == {"total": 0, "obra": 0, "adm": 0, "por_obra": {}, "colaboradores": []}
    assert DD.pj_do_mes(DD.para_df(BASE), "2026-07")["total"] == 0


def test_meses_do_ano():
    assert DD.meses_do_ano("2026-03") == ["2026-01", "2026-02", "2026-03"]


@pytest.mark.pg
def test_pagos_detalhe_no_banco(conn):
    sid = P.criar_sync(conn, "2026-09", "P", "P", "teste@x")
    cont = P.gravar_normalizado(conn, sid, S.normalizar_titulos("P", outcome()))
    P.finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    linhas = DD.pagos_detalhe(conn, "2026-08", "2026-09")
    assert {l["mes"] for l in linhas} == {"2026-08", "2026-09"}
    mat = [l for l in linhas if l["plano_cod"] == "2.01.01.04" and l["mes"] == "2026-09"]
    assert sorted(l["valor"] for l in mat) == [600.0]                                   # 60% de 1000 no centro 1049
    assert {l["cc"] for l in mat} == {"CON - ANASTACIO - LOTE 11"}
    pj = [l for l in linhas if l["plano_cod"] == "2.01.02.01"]
    assert len(pj) == 1 and pj[0]["credor"] == "COLABORADOR TESTE" and pj[0]["valor"] == 500.0
    assert all(l["obra"] == "" for l in linhas)                                         # sem de-para de centros no banco de teste (ou vazio)
    assert DD.pagos_detalhe(conn, "2026-01", "2026-02") == []
    # PJ do mes com os dados do banco
    pjm = DD.pj_do_mes(DD.para_df(linhas), "2026-09")
    assert pjm["total"] == 1 and pjm["colaboradores"][0]["credor"] == "COLABORADOR TESTE"


def test_pj_por_obra_aparece_em_cada_obra_com_percentual():
    lst = DD.pj_por_obra(DD.para_df(BASE), "2026-09")
    assert [(x["obra"], x["credor"], x["pct"]) for x in lst] == [("103", "PJ UM", 0.8333), ("104", "PJ DOIS", 1.0), ("104", "PJ UM", 0.1667)]
    assert DD.pj_por_obra(DD.para_df([]), "2026-09") == [] and DD.pj_por_obra(DD.para_df(BASE), "2026-07") == []      # ADM e estorno ficam de fora


def test_credores_da_obra():
    dd = DD.despesas_df(DD.para_df(BASE), ["2.01.02", "2.02.01"])
    c103 = DD.credores_da_obra(dd, ["103"], "2026-09")
    assert c103["linhas"] == [{"chave": "FORN A", "acumulado": 400.0, "mes": 300.0}] and c103["total"] == 400.0
    assert DD.credores_da_obra(dd, ["104"], "2026-09")["linhas"] == [{"chave": "FORN B", "acumulado": 200.0, "mes": 200.0}]
    assert DD.credores_da_obra(dd, None, "2026-09")["total"] == 650.0                                                  # todas as obras, inclusive ADM
    assert DD.credores_da_obra(dd, ["999"], "2026-09") == {"linhas": [], "n": 0, "total": 0.0}


def test_agrupar_demais_obras_cinco_lucros_cinco_prejuizos_e_com_projecao():
    def _o(cod, rec, cus):
        return {"obra": cod, "nome": f"OBRA {cod}", "receita": rec, "custo": -cus, "bdi": rec - cus, "margem": (rec - cus) / rec if rec else None}
    linhas = [_o(str(i), 1000.0 + i, 500.0) for i in range(1, 8)]                 # 7 obras com lucro: ficam as 5 maiores (7,6,5,4,3)
    linhas += [_o(str(100 + i), 100.0, 300.0 + i) for i in range(1, 8)]           # 7 com prejuizo: ficam as 5 piores (107..103)
    linhas += [_o("1026", 50.0, 10.0), _o("500", 0.0, 5.0)]                       # 1026 sempre em Demais; 500 sem projecao
    dem0 = {"obra": "DEM", "nome": "Demais obras (2)", "receita": 10.0, "custo": -4.0, "n": 2, "bdi": 6.0, "margem": 0.6}
    ob = {"linhas": linhas + [dem0], "total": {"receita": 1, "custo": 1, "bdi": 0, "margem": None}}
    r = P.agrupar_demais_obras(ob, {"1", "500", "1026"})                           # 1 e 500 tem projecao (ficam); 1026 continua em Demais
    cods = [l["obra"] for l in r["linhas"]]
    assert set(cods) == {"7", "6", "5", "4", "3", "107", "106", "105", "104", "103", "1", "500", "DEM"} and cods[-1] == "DEM"
    dem = r["linhas"][-1]
    assert dem["n"] == 6 and dem["nome"] == "Demais obras (6)"                      # obra 2 (lucro) + 102 e 101 (prejuizo) + 1026 + as 2 que ja estavam em DEM
    assert round(sum(l["receita"] for l in r["linhas"]), 2) == round(sum(l["receita"] for l in ob["linhas"]), 2)       # totais nao mudam
    assert round(sum(l["custo"] for l in r["linhas"]), 2) == round(sum(l["custo"] for l in ob["linhas"]), 2)
    assert len(ob["linhas"]) == 17 and ob["linhas"][-1]["obra"] == "DEM"           # a entrada nao e alterada


# ---------------------------------------------------------------- 21/10/2026: pedidos da contabilidade (PJ nas obras, grupo ENERMAIS, Outros/Dir, obras na aba Pessoas, HE x receita)
def test_credores_pj_saem_da_lista_das_obras():
    df = DD.para_df(BASE + [_l("2026-09", "2.01.01.04", "Material | Obra", "PJ UM", "CC 1", "103", "OBRA", 90.0)])     # o PJ UM tambem recebeu por material
    pj = DD.credores_pj(df)
    assert pj == {"PJ UM", "PJ DOIS", "PJ TRES", "PJ ESTORNO"}
    desp = DD.sem_credores(DD.despesas_df(df, ["2.01.02", "2.02.01"]), pj)
    assert "PJ UM" not in set(desp["credor"]) and {"FORN A", "FORN B"} <= set(desp["credor"])
    assert DD.sem_credores(df, set()) is df and DD.credores_pj(DD.para_df([])) == set()


def test_credores_do_grupo_enermais_fora_das_listas():
    df = DD.para_df([_l("2026-09", "2.01.02.03", "Horas Extras | Obra", "ENERMAIS CONSTRUTORA LTDA", "CC 1", "103", "OBRA", 10.0),
                     _l("2026-09", "2.01.02.03", "Horas Extras | Obra", "Enermais Soluções Ltda - CNPJ 1", "CC 1", "103", "OBRA", 20.0),
                     _l("2026-09", "2.01.02.03", "Horas Extras | Obra", "COLAB X", "CC 1", "103", "OBRA", 30.0)])
    nuc = ["ENERMAIS CONSTRUTORA", "ENERMAIS SOLUCOES"]
    assert list(DD.sem_grupo_enermais(df, nuc)["credor"]) == ["COLAB X"]
    assert DD.sem_grupo_enermais(df, []) is df


def test_outros_credores_dir_vira_uma_linha_so():
    ch = ["CREDOR DIR UM", "CREDOR DIR DOIS"]
    df = DD.para_df([_l("2026-09", "2.03.01", "Honorários", "Credor Dir Um", "SEDE", "ADM", "ADM", 100.0),
                     _l("2026-09", "2.03.01", "Honorários", "CREDOR DIR DOIS LTDA", "SEDE", "ADM", "ADM", 50.0),
                     _l("2026-09", "2.03.01", "Honorários", "FORN A", "SEDE", "ADM", "ADM", 10.0),
                     _l("2026-09", "2.03.01", "Honorários", "Credor  Dir Dois Ltda", "SEDE", "ADM", "ADM", 5.0)])      # espaco duplo no nome do Sienge
    m = DD.marcar_outros_dir(df, ch)
    assert list(m["credor_exib"]) == ["Outros credores/Dir", "Outros credores/Dir", "FORN A", "Outros credores/Dir"]
    assert m.groupby("credor_exib")["valor"].sum()["Outros credores/Dir"] == 155.0
    assert list(DD.marcar_outros_dir(df, [])["credor_exib"]) == list(df["credor"])
    assert len(DD.marcar_outros_dir(DD.para_df([]), ch)) == 0


def test_pessoas_por_obra_na_mesma_linguagem_da_aba_obras():
    nomes = {"103": "ANASTÁCIO - LOTE 11"}
    df = DD.para_df([_l("2026-09", "2.01.02.03", "Horas Extras | Obra", "COLAB X", "EE - ANASTACIO - LOTE 11", "103", "OBRA", 400.0),
                     _l("2026-09", "2.01.02.03", "Horas Extras | Obra", "COLAB Y", "CON - ANASTACIO - LOTE 11", "103", "OBRA", 600.0),
                     _l("2026-09", "2.01.02.03", "Horas Extras | ADM", "COLAB Z", "SEDE", "ADM", "ADM", 50.0),
                     _l("2026-09", "2.01.02.03", "Horas Extras | Obra", "COLAB W", "CC SOLTO", "", "", 30.0),
                     _l("2026-09", "2.01.02.03", "Horas Extras | Obra", "COLAB V", "CC OUTRAS", "DEM", "OBRA", 20.0)])
    ob = DD.agrupar(DD.rotular_obras(df, nomes), "obra_rot", "2026-09")
    assert ob["linhas"][0] == {"chave": "103 · ANASTÁCIO - LOTE 11", "acumulado": 1000.0, "mes": 1000.0}      # dois centros de custo, uma obra
    assert {x["chave"] for x in ob["linhas"]} == {"103 · ANASTÁCIO - LOTE 11", "Administração", "Sem obra (CC SOLTO)", "Demais obras"}
    assert DD.rotular_obras(df, {}).iloc[0]["obra_rot"] == "103"                                              # sem nome no de-para: so' o codigo


def test_tabela_pessoas_conta_so_os_meses_do_periodo_escolhido():
    pes = DD.pessoas_df(DD.para_df(BASE))
    ano = DD.tabela_pessoas(pes, "2026-09", 10, 40)
    per = DD.tabela_pessoas(pes, "2026-09", 10, 40, meses=["2026-09"])                    # periodo de um mes so': nada "antes"
    assert next(x for x in ano if x["conta"] == "Horas Extras")["acum_antes"] == 400.0
    assert next(x for x in per if x["conta"] == "Horas Extras")["acum_antes"] == 0.0


def test_he_x_receita_variacao_sobre_o_mes_anterior_e_periodo_x_periodo():
    he = [{"mes": "2026-06", "he_pct": 0.04, "he": 100.0}, {"mes": "2026-07", "he_pct": 0.05, "he": 150.0}, {"mes": "2026-08", "he_pct": 0.05, "he": 150.0},
          {"mes": "2026-09", "he_pct": 0.06, "he": 300.0}]
    rec = [{"mes": m, "receita": r} for m, r in (("2026-06", 1000.0), ("2026-07", 1000.0), ("2026-08", 1200.0), ("2026-09", 1500.0))]
    ev = DD.evolucao_he_receita(he, rec, ["2026-06", "2026-07", "2026-08", "2026-09"])
    assert ev[0]["var_he"] is None and ev[1]["var_he"] == 0.5 and ev[1]["var_receita"] == 0.0
    assert ev[3]["var_he"] == 1.0 and ev[3]["var_receita"] == 0.25 and ev[3]["he_pct"] == 0.06
    cp = DD.comparar_periodos(he, rec, "2026-08", "2026-09")                              # ago-set x jun-jul
    assert cp["he_atual"] == 450.0 and cp["he_anterior"] == 250.0 and cp["var_he"] == 0.8
    assert cp["receita_atual"] == 2700.0 and cp["receita_anterior"] == 2000.0 and cp["var_receita"] == 0.35
    sem = DD.comparar_periodos(he, rec, "2026-09", "2026-10")                             # outubro sem dado: nao compara periodo incompleto
    assert sem["var_he"] is None and sem["var_receita"] is None
