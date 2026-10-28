# -*- coding: utf-8 -*-
"""Aba Administracao (despesas das unidades ADM, credores, de-para 'Outros credores/Dir') e serie de receita da aba Pessoas.
Dados 100% sinteticos (nomes inventados). Os testes sem banco rodam sempre; os com banco usam o Postgres descartavel."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import json
import pytest
from streamlit.testing.v1 import AppTest

import painel_db as P
import sienge_api as S
from dados_sienge import _c, _pg, income

APP = Path(__file__).resolve().parent.parent
PREF = ["2.01.02", "2.02.01", "2.04.02", "1.03.02.02"]
SESSAO = SimpleNamespace(user=SimpleNamespace(email="usuaria@teste"))


@pytest.fixture(autouse=True)
def _restaura_regras(request):
    """A tela cria a regra de previsao (proposta) se faltar; outros testes esperam o banco sem ela. Apaga so' o que ESTE teste criou em pnl_regra."""
    if "conn" not in request.fixturenames:
        yield
        return
    conn = request.getfixturevalue("conn")
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(max(id),0) FROM pnl_regra")
        antes = cur.fetchone()[0]
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pnl_regra WHERE id > %s", (antes,))


def _t(bill, credor, valor, data_pag, plano, cc, previsao="N", doc="NFS "):
    return {"billId": bill, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": doc,
            "forecastDocument": previsao, "creditorId": bill, "creditorName": credor, "issueDate": data_pag, "dueDate": data_pag, "originalAmount": valor,
            "payments": [_pg(1, data_pag, valor)], "paymentsCategories": [_c(plano, "Conta " + plano, 100, cc, f"CC {cc}")]}


def _regs():
    return [
        _t(11, "FORNECEDOR ALFA LTDA", 1000.0, "2026-09-10", "2030102", 1),
        _t(12, "Credor  Exemplo Gama Ltda", 400.0, "2026-09-12", "2030104", 1),
        _t(13, "PESSOA TESTE", 300.0, "2026-09-12", "2010201", 1),            # conta de pessoal de obra: sai pela regra
        _t(14, "FORNECEDOR DE OBRA", 900.0, "2026-09-14", "2010104", 1049),    # centro de OBRA: nao e' ADM
        _t(15, "FORNECEDOR BETA", 200.0, "2026-08-10", "2030102", 2),
        _t(16, "FORNECEDOR PREVISAO", 150.0, "2026-09-20", "2030102", 1, previsao="S", doc="PRV "),
    ]


def _montar(conn):
    sid = P.criar_sync(conn, "2026-08", "P", "P", "teste@x")
    cont = P.gravar_normalizado(conn, sid, S.normalizar_titulos("P", _regs()))
    P.finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, empresa_nome, grupo, codigo_obra) VALUES "
                    "(1,'SEDE A','EMPRESA A','ADM','ADM'),(2,'SEDE B','EMPRESA B','ADM','ADM'),(1049,'OBRA 1','EMPRESA A','OBRA','103')")


# ------------------------------------------------------------------ sem banco
def test_norm_credor_tira_acento_caixa_e_espacos():
    assert P.norm_credor("  Credor   Exemplo Gama  Ltda ") == "CREDOR EXEMPLO GAMA LTDA"
    assert P.norm_credor(None) == ""


def test_adm_resumo_agrupa_e_separa_outros_credores():
    linhas = [
        {"plano_cod": "2.03.01.02", "plano_nome": "Tarifas", "credor": "ALFA", "unidade": "U1", "valor": 600.0},
        {"plano_cod": "2.03.01.02", "plano_nome": "Tarifas", "credor": "BETA", "unidade": "U2", "valor": 300.0},
        {"plano_cod": "2.05.01.01", "plano_nome": "Aluguel", "credor": "Credor Exemplo Gama Ltda", "unidade": "U1", "valor": 100.0},
    ]
    r = P.adm_resumo(linhas, ["credor exemplo gama", "NINGUEM AQUI"], {"2.03": "Despesas financeiras"})
    assert r["total"] == 1000.0 and r["n_credores"] == 3
    assert [(g["nome"], g["valor"]) for g in r["por_grupo"]] == [("Despesas financeiras", 900.0), ("2.05", 100.0)]
    assert [(u["chave"], u["valor"], u["pct"]) for u in r["por_unidade"]] == [("U1", 700.0, 0.7), ("U2", 300.0, 0.3)]
    assert [c["credor"] for c in r["ranking"]] == ["ALFA", "BETA"]                          # o grupo sai do ranking...
    assert r["outros"]["valor"] == 100.0 and r["outros"]["pct"] == 0.1 and r["outros"]["credores"][0]["credor"].startswith("Credor")   # ...e soma a parte
    assert r["chaves_sem_credor"] == ["NINGUEM AQUI"]                                       # chave que nao casou ninguem fica sinalizada


def test_adm_resumo_top_contas_agrupa_o_resto_e_total_zero_nao_quebra():
    linhas = [{"plano_cod": f"2.03.01.{i:02d}", "plano_nome": f"C{i}", "credor": "X", "unidade": "U", "valor": float(20 - i)} for i in range(15)]
    r = P.adm_resumo(linhas, top_contas=12)
    assert len(r["top_contas"]) == 13 and r["top_contas"][-1]["nome"] == "Demais contas (3)" and r["top_contas"][-1]["valor"] == 21.0
    assert round(sum(a["valor"] for a in r["top_contas"]), 2) == r["total"]
    vazio = P.adm_resumo([])
    assert vazio["total"] == 0.0 and vazio["ranking"] == [] and vazio["outros"]["valor"] == 0.0


# ------------------------------------------------------------------ com banco
@pytest.mark.pg
def test_adm_linhas_so_centros_adm_com_regras_e_periodo(conn):
    _montar(conn)
    set_ = P.adm_linhas(conn, "2026-09", "2026-09", PREF, sem_previsao=True)
    assert round(sum(l["valor"] for l in set_), 2) == 1400.0                         # 1000 + 400; pessoal (regra), obra (nao ADM) e previsao (regra) ficam fora
    assert {l["unidade"] for l in set_} == {"EMPRESA A"} and {l["plano_cod"] for l in set_} == {"2.03.01.02", "2.03.01.04"}
    assert round(sum(l["valor"] for l in P.adm_linhas(conn, "2026-09", "2026-09", PREF, sem_previsao=False)), 2) == 1550.0
    ac = P.adm_linhas(conn, "2026-08", "2026-09", PREF, sem_previsao=True)
    assert round(sum(l["valor"] for l in ac), 2) == 1600.0 and {l["unidade"] for l in ac} == {"EMPRESA A", "EMPRESA B"}
    assert P.adm_evolucao(conn, "2026-08", "2026-09", PREF, True) == [{"mes": "2026-08", "valor": 200.0}, {"mes": "2026-09", "valor": 1400.0}]


@pytest.mark.pg
def test_detalhe_da_administracao_inclui_pessoal_adm_mas_nao_transferencias(conn):
    """Bug 20/10: o detalhe 'Quem recebeu' do grupo 2.02.01 (mao de obra propria) aparecia vazio porque aplicava a regra das Despesas (pessoal fora).
    Agora o detalhe mantem o pessoal ADM (2.02.01, que o Orcamento ADM inclui) e continua sem transferencias (1.03.02.02) e emprestimos (2.04.02);
    o resumo da aba Despesas segue com todas as regras."""
    import relatorio_painel_pdf as RPP
    sid = P.criar_sync(conn, "2026-08", "P", "P", "teste@x")
    extra = [_t(17, "PESSOAL ADM", 800.0, "2026-09-11", "2020101", 1), _t(18, "TRANSF EMPRESAS", 5000.0, "2026-09-11", "1030202", 1), _t(19, "EMPRESTIMO", 700.0, "2026-09-11", "2040201", 1)]
    cont = P.gravar_normalizado(conn, sid, S.normalizar_titulos("P", _regs() + extra))
    P.finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, empresa_nome, grupo, codigo_obra) VALUES "
                    "(1,'SEDE A','EMPRESA A','ADM','ADM'),(2,'SEDE B','EMPRESA B','ADM','ADM'),(1049,'OBRA 1','EMPRESA A','OBRA','103')")
    adm = RPP.montar_ctx(conn, "2026-09")["adm"]
    cods = {l["plano_cod"] for l in adm["linhas"]}
    assert "2.02.01.01" in cods and "1.03.02.02" not in cods and "2.04.02.01" not in cods and "2.01.02.01" not in cods
    assert round(sum(l["valor"] for l in adm["linhas_ano"]), 2) >= round(sum(l["valor"] for l in adm["linhas"]), 2)
    assert round(adm["resumo"]["total"], 2) == 1550.0                          # resumo da aba Despesas: sem pessoal, transferencias e emprestimos (1000 + 400 + 150 de previsao, sem a regra de previsao no teste)


@pytest.mark.pg
def test_adm_sem_de_para_devolve_vazio(conn):
    sid = P.criar_sync(conn, "2026-09", "P", "P", "teste@x")
    P.gravar_normalizado(conn, sid, S.normalizar_titulos("P", _regs()))
    assert P.adm_linhas(conn, "2026-09", "2026-09", PREF) == [] and P.adm_evolucao(conn, "2026-09", "2026-09", PREF) == []


@pytest.mark.pg
def test_credor_grupo_adiciona_duplicado_remove_e_log_sem_nome(conn):
    assert P.credor_grupo_instalado(conn) and P.credor_grupo_ativos(conn) == []
    r = P.credor_grupo_adicionar(conn, "Credor Exemplo Gama", "teste@x")
    assert r["ok"] and [c["chave"] for c in P.credor_grupo_ativos(conn)] == ["CREDOR EXEMPLO GAMA"]
    assert not P.credor_grupo_adicionar(conn, "CREDOR   EXEMPLO   GAMA", "teste@x")["ok"]       # mesmo credor, escrito diferente
    assert not P.credor_grupo_adicionar(conn, " ab ", "teste@x")["ok"]                          # curto demais
    logs = P.ultimos_logs(conn, acao="CREDOR_GRUPO_ADICIONADO")
    assert len(logs) == 1 and "CREDOR EXEMPLO" not in str(logs[0]["detalhe"]).upper()                # log nao guarda nome
    assert P.credor_grupo_remover(conn, r["id"], "teste@x") and P.credor_grupo_ativos(conn) == []
    assert not P.credor_grupo_remover(conn, r["id"], "teste@x")
    assert P.credor_grupo_adicionar(conn, "Credor Exemplo Gama", "teste@x")["ok"]              # depois de removido pode voltar
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE ativo) FROM pnl_credor_grupo")
        assert cur.fetchone() == (2, 1)                                                          # a linha antiga ficou no historico


@pytest.mark.pg
def test_receita_mensal_fontes_e_variacao(conn):
    reg_ago = dict(income()[0], billId=51, issueDate="2026-08-10", originalAmount=1000.0)
    for regs in (income(), [reg_ago]):
        sid = P.criar_sync(conn, "2026-08", "R", "I", "teste@x")
        P.gravar_normalizado(conn, sid, S.normalizar_titulos("R", regs))
    s = {x["mes"]: x for x in P.receita_mensal(conn)}
    assert (s["2026-08"]["receita"], s["2026-09"]["receita"], s["2026-09"]["var"]) == (1000.0, 2000.0, 1.0) and s["2026-09"]["fonte"].startswith("API")
    assert [x["mes"] for x in P.receita_mensal(conn, mes_atual="2026-09")] == ["2026-08"]       # mes em andamento fica de fora
    P.gravar_confirmacao(conn, "2026-09", {"01.01": "PDF"}, {"01.01": 2500.0}, "teste@x")
    s = {x["mes"]: x for x in P.receita_mensal(conn)}
    assert (s["2026-09"]["receita"], s["2026-09"]["fonte"], s["2026-09"]["var"]) == (2500.0, "DRE confirmado", 1.5)


@pytest.mark.pg
def test_receita_mensal_pula_variacao_quando_falta_mes(conn):
    for iss, bid in (("2026-06-10", 60), ("2026-09-10", 61)):
        sid = P.criar_sync(conn, iss[:7], "R", "I", "teste@x")
        P.gravar_normalizado(conn, sid, S.normalizar_titulos("R", [dict(income()[0], billId=bid, issueDate=iss, originalAmount=1000.0)]))
    assert [x["var"] for x in P.receita_mensal(conn)] == [None, None]                           # jun -> set nao e' "mes anterior"


@pytest.mark.pg
def test_receita_mensal_ignora_meses_de_api_antes_da_primeira_sincronizacao(conn):
    """Mes antigo so' com residuo da API (ex.: titulo emitido em 2025-05 e sincronizado depois) nao entra; com DRE confirmado entra."""
    sid = P.criar_sync(conn, "2026-08", "R", "I", "teste@x")
    P.gravar_normalizado(conn, sid, S.normalizar_titulos("R", [
        dict(income()[0], billId=70, issueDate="2026-05-10", originalAmount=300.0),
        dict(income()[0], billId=71, issueDate="2026-08-10", originalAmount=1000.0)]))
    assert [x["mes"] for x in P.receita_mensal(conn)] == ["2026-08"]
    P.gravar_confirmacao(conn, "2026-05", {"01.01": "PDF"}, {"01.01": 900.0}, "teste@x")
    assert [x["mes"] for x in P.receita_mensal(conn)] == ["2026-05", "2026-08"]


@pytest.mark.pg
def test_graficos_da_aba_pessoas_em_ordem_cronologica(conn):
    """A ordem do eixo X e' a da lista (cronologica), nao a alfabetica de 'MM/AAAA' (que poria 01/2026 antes de 12/2025)."""
    for iss, bid in (("2025-12-10", 80), ("2026-01-10", 81)):
        sid = P.criar_sync(conn, iss[:7], "R", "I", "teste@x")
        P.gravar_normalizado(conn, sid, S.normalizar_titulos("R", [dict(income()[0], billId=bid, issueDate=iss, originalAmount=1000.0)]))
    with patch("conexao.get_conn", return_value=conn):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    graficos = [json.loads(c.proto.spec) for c in at.get("vega_lite_chart")]
    assert graficos
    ordens = [g["encoding"]["x"]["sort"] for g in graficos]
    assert ["12/2025", "01/2026"] in ordens


def _tela(conn):
    at = AppTest.from_file(str(APP / "telas" / "8_Painel_EnerMais.py"), default_timeout=30)
    at.session_state["auth_session"] = SESSAO
    at.session_state["pn2_todas_abas"] = True
    return at


@pytest.mark.pg
def test_tela_administracao_mostra_ranking_e_outros_credores(conn):
    _montar(conn)
    P.credor_grupo_adicionar(conn, "Credor Exemplo Gama", "teste@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    assert at.tabs[5].label == "Administração (prévia)" and at.tabs[6].label == "Pessoas (prévia)"
    assert any("1.400,00" in m.value for m in at.tabs[5].metric)
    cred = [df.value for df in at.tabs[5].dataframe if "Credor" in df.value.columns and "% do total" in df.value.columns]
    assert cred and "Outros credores/Dir (fora do ranking)" in set(cred[0]["Credor"]) and "FORNECEDOR ALFA LTDA" in set(cred[0]["Credor"])
    assert not any("CREDOR EXEMPLO" in str(x).upper() for x in cred[0]["Credor"])                      # saiu do ranking


@pytest.mark.pg
def test_tela_administracao_sem_sql_11_avisa_e_nao_quebra(conn):
    _montar(conn)
    with patch("conexao.get_conn", return_value=conn), patch("painel_db.credor_grupo_instalado", return_value=False):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    assert any("SQL-11" in w.value for w in at.tabs[1].warning)   # o cadastro de credores mudou para a aba Importações (V2)


@pytest.mark.pg
def test_tela_pessoas_mostra_serie_de_receita(conn):
    sid = P.criar_sync(conn, "2026-09", "R", "I", "teste@x")
    P.gravar_normalizado(conn, sid, S.normalizar_titulos("R", income()))
    with patch("conexao.get_conn", return_value=conn):
        at = _tela(conn).run()
    assert not at.exception, at.exception
    tab = at.tabs[6].dataframe[0].value
    assert list(tab.columns) == ["Mês", "Receita bruta", "Var. % s/ mês anterior", "Fonte"] and "09/2026" in set(tab["Mês"])


@pytest.mark.pg
def test_credor_grupo_demais_pj_e_independente_do_outros_dir(conn):
    assert P.credor_grupo_aceita(conn, "DEMAIS_PJ") and P.credor_grupo_aceita(conn, "OUTROS_DIR")
    r = P.credor_grupo_adicionar(conn, "Colaborador Pj Exemplo Ltda", "teste@x", "DEMAIS_PJ")
    assert r["ok"] and [c["chave"] for c in P.credor_grupo_ativos(conn, "DEMAIS_PJ")] == ["COLABORADOR PJ EXEMPLO LTDA"]
    assert P.credor_grupo_ativos(conn) == []                                                  # nao vaza para 'Outros credores/Dir'
    assert not P.credor_grupo_adicionar(conn, "COLABORADOR  PJ EXEMPLO LTDA", "teste@x", "DEMAIS_PJ")["ok"]
    assert P.credor_grupo_adicionar(conn, "Colaborador Pj Exemplo Ltda", "teste@x")["ok"]       # o mesmo nome pode estar nos dois grupos
    assert not P.credor_grupo_adicionar(conn, "Qualquer Um", "teste@x", "GRUPO_INEXISTENTE")["ok"]
    logs = P.ultimos_logs(conn, acao="CREDOR_GRUPO_ADICIONADO")
    assert logs and "EXEMPLO" not in str(logs[0]["detalhe"]).upper() and "DEMAIS_PJ" in str(logs[-1]["detalhe"] if len(logs) == 1 else [l["detalhe"] for l in logs])
    assert P.credor_grupo_remover(conn, r["id"], "teste@x") and P.credor_grupo_ativos(conn, "DEMAIS_PJ") == []
    assert len(P.credor_grupo_ativos(conn)) == 1                                              # remover num grupo nao mexe no outro


def test_unidade_mega_aragoiania_fica_fora_do_cenario_adm_sem_acento_nem_caixa():
    assert P.unidade_fora_adm("MEGA ARAGOIÂNIA") and P.unidade_fora_adm("Mega Aragoiania Energia SPE Ltda") and P.unidade_fora_adm("mega  aragoiânia")
    assert not P.unidade_fora_adm("EMPRESA A") and not P.unidade_fora_adm("MEGA SOLAR") and not P.unidade_fora_adm(None)


@pytest.mark.pg
def test_adm_linhas_e_evolucao_tiram_a_unidade_mega_aragoiania(conn):
    _montar(conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_centro_grupo SET empresa_nome='MEGA ARAGOIÂNIA ENERGIA' WHERE centro_custo_id=2")           # o centro 2 (ago/26, R$ 200) vira a unidade que sai
    ac = P.adm_linhas(conn, "2026-08", "2026-09", PREF, sem_previsao=True)
    assert round(sum(l["valor"] for l in ac), 2) == 1400.0 and {l["unidade"] for l in ac} == {"EMPRESA A"}
    assert P.adm_evolucao(conn, "2026-08", "2026-09", PREF, True) == [{"mes": "2026-09", "valor": 1400.0}]
