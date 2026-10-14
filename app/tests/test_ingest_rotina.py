# -*- coding: utf-8 -*-
"""Rotina diaria (scripts/ingest_sienge_gdf.py): meses, configuracao, execucao com dados sinteticos e falha parcial."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

import painel_db as P_
import sienge_api as S
from dados_sienge import income, outcome

RAIZ = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("ingest_sienge_gdf", RAIZ / "scripts" / "ingest_sienge_gdf.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def test_meses_padrao_sao_os_ultimos_365_dias():
    m = R.meses_padrao(dt.date(2026, 10, 13))
    assert m[0] == "2025-10" and m[-1] == "2026-10" and len(m) == 13
    m = R.meses_padrao(dt.date(2027, 1, 1))
    assert m[0] == "2026-01" and m[-1] == "2027-01" and "2026-12" in m
    assert R.meses_padrao(dt.date(2026, 3, 31))[0] == "2025-03"


def test_ler_meses():
    assert R.ler_meses({"GDF_MESES": " 2026-08 , 2026-09 "}) == ["2026-08", "2026-09"]
    assert len(R.ler_meses({})) == 13 and len(R.ler_meses({"GDF_MESES": ""})) == 13
    for ruim in ("2026-13", "26-09", "2026/09", "abc"):
        with pytest.raises(ValueError):
            R.ler_meses({"GDF_MESES": ruim})


def test_main_sem_configuracao_nao_vaza_nada(capsys):
    assert R.main({}) == 1
    assert "SIENGE_USER" in capsys.readouterr().out
    env = {"SIENGE_USER": "enermais-teste", "SIENGE_PASSWORD": "segredo-super-secreto"}
    assert R.main(env) == 1
    saida = capsys.readouterr().out
    assert "DATABASE_URL" in saida and "segredo-super-secreto" not in saida
    assert R.main({**env, "DATABASE_URL": "postgresql://u:senha-do-banco@host.invalido:1/db"}) == 1
    saida = capsys.readouterr().out
    assert "senha-do-banco" not in saida and "host.invalido" not in saida


@pytest.mark.pg
def test_executar_grava_e_falha_parcial_da_exit_1(conn):
    chamadas = []

    def buscar(cli, lado, mes, tipo, mes_fim=None):
        chamadas.append((lado, mes, tipo, mes_fim))
        if lado == "R":
            raise S.ErroSienge("Sienge respondeu HTTP 403 (sem permissão)")
        return outcome() if lado == "P" else income()

    linhas = []
    cod = R.executar(conn, None, ["2026-09", "2026-10"], buscar=buscar, atualizar_cadastros=False, log=linhas.append)
    assert cod == 1 and len(chamadas) == 4                       # uma janela: 2 lados x 2 tipos de data
    assert all(c[1] == "2026-09" and c[3] == "2026-10" for c in chamadas)
    assert sum(1 for l in linhas if l.startswith("ERRO")) == 2 and any("403" in l for l in linhas)
    with conn.cursor() as cur:
        cur.execute("SELECT usuario, status, count(*) FROM pnl_sync GROUP BY 1,2 ORDER BY 2")
        assert cur.fetchall() == [("rotina-diaria", "ERRO", 2), ("rotina-diaria", "OK", 2)]
    # repetir no dia seguinte nao duplica os titulos
    R.executar(conn, None, ["2026-09"], buscar=buscar, atualizar_cadastros=False, log=lambda *_: None)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pnl_titulo")
        assert cur.fetchone()[0] == 4                 # so os 4 titulos a pagar (o receber falhou)


@pytest.mark.pg
def test_executar_inclui_movimento_bancario(conn):
    from dados_sienge import movimentos_banco
    linhas = []
    cod = R.executar(conn, None, ["2026-09"], buscar=lambda c, l, m, t, mes_fim=None: outcome() if l == "P" else income(),
                     buscar_banco=lambda c, m, mes_fim=None: movimentos_banco(), atualizar_cadastros=False, log=linhas.append)
    assert cod == 0 and any("movimento bancário" in x and "2 lançamentos" in x for x in linhas)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pnl_titulo WHERE bill_id < 0")
        assert cur.fetchone()[0] == 2


def test_executar_sem_falhas_da_exit_0(conn):
    cod = R.executar(conn, None, ["2026-09"], buscar=lambda c, l, m, t, mes_fim=None: outcome() if l == "P" else income(),
                     atualizar_cadastros=False, log=lambda *_: None)
    assert cod == 0
    import painel_db as P
    fim = [l for l in P.ultimos_logs(conn) if l["acao"] == "ROTINA_FIM"]
    assert len(fim) == 1 and fim[0]["usuario"] == "rotina-diaria" and fim[0]["nivel"] == "INFO" and fim[0]["detalhe"]["falhas"] == 0


@pytest.mark.pg
def test_executar_para_quando_o_limite_429_persiste(conn):
    chamadas = []

    def buscar(cli, lado, mes, tipo, mes_fim=None):
        chamadas.append((lado, mes, tipo))
        raise S.ErroSienge("Sienge respondeu HTTP 429 (limite) em /x; esgotei as novas tentativas.")

    linhas = []
    cod = R.executar(conn, None, ["2026-08", "2026-09", "2026-10"], buscar=buscar, atualizar_cadastros=False, log=linhas.append)
    assert cod == 1 and len(chamadas) == 1                 # nao insiste nos outros lados/tipos
    assert any("parei aqui" in l for l in linhas)


@pytest.mark.pg
def test_meses_com_dados_pela_data_do_pagamento(conn):
    R.executar(conn, None, ["2026-08", "2026-09"], buscar=lambda c, l, m, t, mes_fim=None: outcome() if l == "P" else income(),
               atualizar_cadastros=False, log=lambda *_: None)
    assert "2026-09" in P_.meses_com_dados(conn) or "2026-08" in P_.meses_com_dados(conn)
    assert P_.meses_com_dados(conn) == sorted(P_.meses_com_dados(conn))


@pytest.mark.pg
def test_executar_baixa_repetida_nao_da_erro_e_avisa(conn):
    regs = outcome()
    regs[0]["payments"] = regs[0]["payments"] + [dict(regs[0]["payments"][0])]      # copia identica da primeira baixa
    linhas = []
    cod = R.executar(conn, None, ["2026-09"], buscar=lambda c, l, m, t, mes_fim=None: regs if l == "P" else income(),
                     atualizar_cadastros=False, log=linhas.append)
    assert cod == 0 and any("baixas_copia_ignorada" in l for l in linhas)


# ---------------------------------------------------------------- diagnostico
_spec2 = importlib.util.spec_from_file_location("diagnostico_sienge_gdf", RAIZ / "scripts" / "diagnostico_sienge_gdf.py")
D = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(D)


def test_meses_entre():
    assert D.meses_entre("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert D.meses_entre("2026-10", "2026-10") == ["2026-10"]


def test_analisar_acha_chaves_repetidas_sem_vazar_valores():
    regs = outcome()
    regs.append(dict(regs[0]))                                   # titulo 1 repetido, identico
    outro = dict(regs[1]); outro["payments"] = [{"sequencialNumber": 9, "netAmount": 1.0}]
    regs.append(outro)                                            # titulo 2 repetido, baixas diferentes
    regs[2] = dict(regs[2]); regs[2]["payments"] = regs[2]["payments"] + [dict(regs[2]["payments"][0])]  # baixa com seq repetida
    r = D.analisar(regs, "P")
    assert r["registros"] == 6 and r["chaves_unicas"] == 4 and r["chaves_repetidas"] == 2
    assert r["repetidas_identicas"] == 1 and r["repetidas_com_mesmas_baixas"] == 1
    assert r["baixas_chave_repetida_no_mesmo_registro"] == 1 and r["baixas_chave_repetida_total"] == 2
    assert r["colisoes_identicas"] == 1 and r["colisoes_diferentes"] == 0
    assert "FORNECEDOR" not in str(r)


def test_diagnostico_sem_configuracao(capsys):
    assert D.main({}, log=print) == 1
    assert "SIENGE_USER" in capsys.readouterr().out


# ---- diagnostico do movimento bancario (so contagens, nunca valores)
_spec3 = importlib.util.spec_from_file_location("diagnostico_banco_sienge_gdf", RAIZ / "scripts" / "diagnostico_banco_sienge_gdf.py")
B = importlib.util.module_from_spec(_spec3)
_spec3.loader.exec_module(B)


def test_resumo_do_movimento_bancario_so_tem_contagens():
    regs = [
        {"bankMovementId": 1, "billId": 10, "bankMovementOriginId": "CP", "bankMovementOperationType": "D", "bankMovementOperationId": 1, "bankMovementOperationName": "Pagamento",
         "financialCategories": [{"financialCategoryId": "2010104", "financialCategoryRate": 100, "financialCategoryAmount": 999.99}]},
        {"bankMovementId": 2, "billId": None, "bankMovementOriginId": "BC", "bankMovementOperationType": "D", "bankMovementOperationId": 7, "bankMovementOperationName": "Tarifa",
         "bankMovementHistoricId": 33, "financialCategories": [{"financialCategoryId": "2030102", "financialCategoryRate": 100}]},
        {"bankMovementId": 3, "billId": None, "bankMovementOriginId": "BC", "bankMovementOperationType": "D", "bankMovementOperationId": 7, "bankMovementOperationName": "Tarifa",
         "bankMovementHistoricId": 33, "financialCategories": []},
    ]
    r = B.resumir(regs)
    assert r["registros"] == 3 and r["sem_titulo"] == 2 and r["com_plano"] == 2 and r["sem_titulo_com_plano"] == 1
    assert r["sem_titulo_por_origem"] == {"BC": 2} and r["sem_titulo_contas_alvo"]["2.03.01.02"] == 1
    assert "financialCategoryId" in r["campos_plano"]
    assert "999.99" not in str(r)                                      # nenhum valor em R$ vai para o log publico
    assert B.resumir([])["registros"] == 0
