# -*- coding: utf-8 -*-
"""Rotina diaria do registro de metricas (scripts/registrar_metricas_gdf.py): meses a registrar, execucao contra Postgres descartavel e saida sem dados."""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

import metricas_registro as M
from test_metricas_registro import dados  # noqa: F401  (fixture com titulos sinteticos)

RAIZ = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("registrar_metricas_gdf", RAIZ / "scripts" / "registrar_metricas_gdf.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def test_meses_a_registrar_atual_e_anterior_nos_primeiros_dias():
    assert R.meses_a_registrar(dt.date(2026, 10, 22)) == ["2026-10"]
    assert R.meses_a_registrar(dt.date(2026, 10, 5)) == ["2026-09", "2026-10"]
    assert R.meses_a_registrar(dt.date(2026, 10, 6)) == ["2026-10"]
    assert R.meses_a_registrar(dt.date(2027, 1, 3)) == ["2026-12", "2027-01"]                 # virada do ano
    assert R.meses_a_registrar(dt.date(2026, 10, 22), "2026-09, 2026-08,2026-09") == ["2026-08", "2026-09"]
    for ruim in ("2026-13", "26-10", "abc", "2026/10"):
        with pytest.raises(ValueError):
            R.meses_a_registrar(dt.date(2026, 10, 22), ruim)


def test_rotina_grava_o_mes_atual_e_regravar_nao_muda_nada(conn, dados):          # noqa: F811
    saida = []
    hoje = dt.date(2026, 10, 20)
    assert R.main(env={}, conn=conn, hoje=hoje, log=saida.append) == 0
    assert any("2026-10: 3 nova(s)" in l for l in saida) and not any("ERRO" in l for l in saida)
    assert {l["item_id"] for l in M.ler_registro(conn, "2026-10")} == {"I03", "I22", "I27"}
    assert all(l["atualizado_por"] == "rotina-metricas" for l in M.ler_registro(conn, "2026-10"))
    saida.clear()
    assert R.main(env={}, conn=conn, hoje=hoje, log=saida.append) == 0
    assert any("0 nova(s), 0 atualizada(s), 3 sem mudança" in l for l in saida)
    assert M.ler_historico(conn, "2026-10") == []


def test_rotina_nos_primeiros_dias_fecha_tambem_o_mes_anterior(conn, dados):         # noqa: F811
    saida = []
    assert R.main(env={}, conn=conn, hoje=dt.date(2026, 10, 3), log=saida.append) == 0
    assert any(l.startswith("2026-09:") for l in saida) and any(l.startswith("2026-10:") for l in saida)
    assert M.json.loads(M.ler_registro(conn, "2026-09")[1]["detalhe"])["posicao"] == "fim do mês"


def test_indicador_com_falha_da_codigo_1_mas_grava_os_outros(conn, dados, monkeypatch):    # noqa: F811
    def quebra(c, mes, hoje=None):
        raise RuntimeError("falha de teste\ncom segunda linha")
    monkeypatch.setitem(M.CALCULADORES, "I22", quebra)
    saida = []
    assert R.main(env={}, conn=conn, hoje=dt.date(2026, 10, 20), log=saida.append) == 1
    assert any("ERRO 2026-10 I22" in l and "segunda linha" not in l for l in saida)
    assert {l["item_id"] for l in M.ler_registro(conn, "2026-10")} == {"I03", "I27"}


def test_sem_database_url_e_sem_tabelas_avisa_sem_quebrar(conn, monkeypatch):
    saida = []
    assert R.main(env={}, hoje=dt.date(2026, 10, 20), log=saida.append) == 1 and "DATABASE_URL" in saida[0]
    monkeypatch.setattr(M, "instalado", lambda c: False)
    saida.clear()
    assert R.main(env={}, conn=conn, hoje=dt.date(2026, 10, 20), log=saida.append) == 1 and "SQL-34" in saida[0]


def test_i03_sem_dados_no_banco_nao_quebra(conn):
    assert M._termos_mes(conn, "2026-10") is None
    assert M.calcular_I03(conn, "2026-10")[0]["status"] == "Sem lançamento"
