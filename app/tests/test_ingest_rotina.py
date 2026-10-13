# -*- coding: utf-8 -*-
"""Rotina diaria (scripts/ingest_sienge_gdf.py): meses, configuracao, execucao com dados sinteticos e falha parcial."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

import sienge_api as S
from dados_sienge import income, outcome

RAIZ = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("ingest_sienge_gdf", RAIZ / "scripts" / "ingest_sienge_gdf.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def test_meses_padrao():
    assert R.meses_padrao(dt.date(2026, 10, 13)) == ["2026-09", "2026-10"]
    assert R.meses_padrao(dt.date(2027, 1, 1)) == ["2026-12", "2027-01"]
    assert R.meses_padrao(dt.date(2026, 3, 31)) == ["2026-02", "2026-03"]


def test_ler_meses():
    assert R.ler_meses({"GDF_MESES": " 2026-08 , 2026-09 "}) == ["2026-08", "2026-09"]
    assert len(R.ler_meses({})) == 2 and len(R.ler_meses({"GDF_MESES": ""})) == 2
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

    def buscar(cli, lado, mes, tipo):
        chamadas.append((lado, mes, tipo))
        if lado == "R" and mes == "2026-10":
            raise S.ErroSienge("Sienge respondeu HTTP 403 (sem permissão)")
        return outcome() if lado == "P" else income()

    linhas = []
    cod = R.executar(conn, None, ["2026-09", "2026-10"], buscar=buscar, atualizar_cadastros=False, log=linhas.append)
    assert cod == 1 and len(chamadas) == 8
    assert sum(1 for l in linhas if l.startswith("ERRO")) == 2 and any("403" in l for l in linhas)
    with conn.cursor() as cur:
        cur.execute("SELECT usuario, status, count(*) FROM pnl_sync GROUP BY 1,2 ORDER BY 2")
        assert cur.fetchall() == [("rotina-diaria", "ERRO", 2), ("rotina-diaria", "OK", 6)]
    # repetir no dia seguinte nao duplica os titulos
    R.executar(conn, None, ["2026-09"], buscar=buscar, atualizar_cadastros=False, log=lambda *_: None)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pnl_titulo")
        assert cur.fetchone()[0] == 5


@pytest.mark.pg
def test_executar_sem_falhas_da_exit_0(conn):
    cod = R.executar(conn, None, ["2026-09"], buscar=lambda c, l, m, t: outcome() if l == "P" else income(),
                     atualizar_cadastros=False, log=lambda *_: None)
    assert cod == 0


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
    assert "FORNECEDOR" not in str(r)


def test_diagnostico_sem_configuracao(capsys):
    assert D.main({}, log=print) == 1
    assert "SIENGE_USER" in capsys.readouterr().out
