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
V2_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_painel_schema.sql"
LOG_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_log.sql"
GRUPO_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_centro_grupo.sql"
DRE_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_dre_pdf.sql"
CONF_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_dre_confirmacao.sql"
CREDOR_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_credor_grupo.sql"
IMPOSTO_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_titulo_imposto.sql"
FOLHA_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_folha.sql"
ORC_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_orcamento_adm.sql"
EDICAO_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_edicao.sql"
HISTORICO_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_historico.sql"
ACESSO_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_acesso.sql"
OBRA_SQL = Path(__file__).resolve().parent.parent.parent / "sql" / "v2_obra_sienge.sql"
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
        cur.execute(V2_SQL.read_text(encoding="utf-8"))        # V2 (Painel EnerMais): tabelas pnl_*
        cur.execute(LOG_SQL.read_text(encoding="utf-8"))       # historico e logs (pnl_log)
        cur.execute(GRUPO_SQL.read_text(encoding="utf-8"))     # de-para centro de custo -> grupo
        cur.execute(DRE_SQL.read_text(encoding="utf-8"))       # DRE oficial lido do PDF (pnl_dre_valor)
        cur.execute(CONF_SQL.read_text(encoding="utf-8"))      # confirmacao do DRE do mes (fonte por linha)
        cur.execute(CREDOR_SQL.read_text(encoding="utf-8"))    # de-para credor -> "Outros credores/Dir" (aba Administracao)
        cur.execute(IMPOSTO_SQL.read_text(encoding="utf-8"))   # SQL-13: imposto do titulo de receita (DRE 02.02)
        cur.execute(FOLHA_SQL.read_text(encoding="utf-8"))     # SQL-16: recibos da folha e de-para departamento -> obra
        cur.execute(ORC_SQL.read_text(encoding="utf-8"))       # SQL-18: orcamento ADM (orcado x realizado)
        cur.execute(EDICAO_SQL.read_text(encoding="utf-8"))    # SQL-19: edicao dos dados importados
        cur.execute(HISTORICO_SQL.read_text(encoding="utf-8"))   # SQL-21: historico do painel da contabilidade
        cur.execute(ACESSO_SQL.read_text(encoding="utf-8"))    # SQL-20: papel de acesso (editor / visualizador)
        cur.execute(OBRA_SQL.read_text(encoding="utf-8"))      # SQL-24: obras do Sienge (nomes)
    conn.close()
    return dsn


@pytest.fixture()
def conn(pg_dsn):
    """Conexao (como superuser de teste, igual ao app: autocommit) com o schema `gdf` LIMPO a cada teste."""
    import psycopg2
    c = psycopg2.connect(pg_dsn)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("TRUNCATE gdf.pnl_historico_painel, gdf.pnl_acesso, gdf.pnl_edicao, gdf.pnl_credor_grupo, gdf.pnl_orcamento_linha, gdf.pnl_folha_recibo, gdf.pnl_folha_depto_obra, gdf.pnl_dre_confirmacao, gdf.pnl_dre_valor, gdf.pnl_centro_grupo, gdf.pnl_log, gdf.pnl_folha_evento, gdf.pnl_projecao_linha, gdf.pnl_historico_bloco, gdf.pnl_importacao, gdf.pnl_rateio, gdf.pnl_baixa, gdf.pnl_titulo, gdf.pnl_sync, gdf.pnl_centro_custo, gdf.pnl_obra, gdf.pnl_obra_sienge, gdf.pnl_plano_conta, gdf.pnl_tipo_negocio, gdf.pnl_empresa_sienge, gdf.evento, gdf.conferencia, gdf.balancete_linha, gdf.importacao, gdf.mapa_conta, gdf.apelido, gdf.relatorio, gdf.empresa RESTART IDENTITY CASCADE")
        cur.execute("SET search_path = gdf, public")
    yield c
    c.close()


@pytest.fixture()
def dados_reais():
    pasta = os.environ.get("GDF_DADOS_REAIS")
    if not pasta or not Path(pasta).exists():
        pytest.skip("defina GDF_DADOS_REAIS=<pasta com os dados reais> para rodar este teste")
    return Path(pasta)
