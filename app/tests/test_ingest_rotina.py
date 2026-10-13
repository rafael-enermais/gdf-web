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
