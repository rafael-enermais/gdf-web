# -*- coding: utf-8 -*-
"""
Configuracao compartilhada dos testes do GDF.

Testes de INTEGRACAO (marker `pg`) rodam contra um Postgres DESCARTAVEL (nunca o Supabase de producao):
  1. env GDF_TEST_DATABASE_URL (DSN de um Postgres vazio/descartavel -- cria/derruba o proprio schema `gdf`), ou
  2. autostart de um cluster temporario com initdb/pg_ctl achados no PATH ou em /usr/lib/postgresql/*/bin
     (como root, roda como o usuario `postgres`);
  3. senao, os testes `pg` dao SKIP.
Testes que usam dados reais so' rodam com GDF_DADOS_REAIS=<pasta> (os dados reais NAO ficam no repositorio).
"""
from __future__ import annotations

import atexit
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_SQL = Path(__file__).resolve().parent.parent.parent / "schema.sql"
_estado = {"dsn": None, "tentou": False}


def pytest_configure(config):
    config.addinivalue_line("markers", "pg: integracao contra Postgres real descartavel (skip se indisponivel)")
    config.addinivalue_line("markers", "dados_reais: usa arquivos reais fora do repositorio (GDF_DADOS_REAIS)")


def _bin(nome):
    achado = shutil.which(nome)
    if achado:
        return achado
    for d in sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        cand = os.path.join(d, nome)
        if os.path.exists(cand):
            return cand
    return None


def _autostart():
    initdb, pg_ctl = _bin("initdb"), _bin("pg_ctl")
    if not initdb or not pg_ctl:
        return None
    raiz = tempfile.mkdtemp(prefix="gdf_pg_")
    data, porta = os.path.join(raiz, "data"), "54398"
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    pre = []
    if root:
        os.chmod(raiz, 0o777)
        pre = ["su", "postgres", "-c"]

    def rodar(cmd):
        if root:
            return subprocess.run(pre + [" ".join(f"'{c}'" for c in cmd)], capture_output=True, text=True)
        return subprocess.run(cmd, capture_output=True, text=True)

    if rodar([initdb, "-D", data, "-A", "trust", "-U", "postgres"]).returncode != 0:
        return None
    r = rodar([pg_ctl, "-D", data, "-o", f"-p {porta} -k {raiz} -c listen_addresses=''", "-w", "-l", os.path.join(raiz, "log"), "start"])
    if r.returncode != 0:
        return None
    atexit.register(lambda: rodar([pg_ctl, "-D", data, "-m", "immediate", "stop"]))
    atexit.register(lambda: shutil.rmtree(raiz, ignore_errors=True))
    return f"host={raiz} port={porta} dbname=postgres user=postgres"


def dsn_teste():
    if not _estado["tentou"]:
        _estado["tentou"] = True
        _estado["dsn"] = os.environ.get("GDF_TEST_DATABASE_URL") or _autostart()
    return _estado["dsn"]


@pytest.fixture(scope="session")
def pg_dsn():
    dsn = dsn_teste()
    if not dsn:
        pytest.skip("sem Postgres de teste disponivel")
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS gdf CASCADE")
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.close()
    return dsn


@pytest.fixture()
def conn(pg_dsn):
    """Conexao (como superuser de teste, igual ao app: autocommit) com o schema `gdf` LIMPO a cada teste."""
    import psycopg2
    c = psycopg2.connect(pg_dsn)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("TRUNCATE gdf.evento, gdf.conferencia, gdf.balancete_linha, gdf.importacao, gdf.mapa_conta, gdf.apelido, gdf.relatorio, gdf.empresa RESTART IDENTITY CASCADE")
        cur.execute("SET search_path = gdf, public")
    yield c
    c.close()


@pytest.fixture()
def dados_reais():
    pasta = os.environ.get("GDF_DADOS_REAIS")
    if not pasta or not Path(pasta).exists():
        pytest.skip("defina GDF_DADOS_REAIS=<pasta com os dados reais> para rodar este teste")
    return Path(pasta)
