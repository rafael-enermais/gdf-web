# -*- coding: utf-8 -*-
"""Integracao do db.py contra Postgres descartavel (aplica o schema.sql real)."""
import pytest

import db
import importador_csv as I
import motor
from dados_sinteticos import csv_texto, gerar_meses

pytestmark = pytest.mark.pg
CNPJ = "00.000.000/0001-91"
MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)])


def _arq(mes: int, ini=None, fim=None, ajuste=0.0):
    chave = f"2026-{mes:02d}"
    ult = {1: "31", 2: "28", 3: "31"}[mes]
    raw = csv_texto(MESES[chave], ini=ini or f"01/{mes:02d}/2026", fim=fim or f"{ult}/{mes:02d}/2026")
    return I.ler_bytes(raw, f"{chave}.csv")


@pytest.fixture()
def emp(conn):
    emp_id = db.garantir_empresa(conn, "TESTE", "Empresa Sintetica Ltda", CNPJ)
    db.garantir_mapa(conn, emp_id, "teste@x")
    return emp_id


def test_empresa_e_mapa_idempotentes(conn, emp):
    assert db.garantir_empresa(conn, "TESTE", "Empresa Sintetica Ltda", CNPJ) == emp
    assert db.garantir_mapa(conn, emp) is False
    mapa = db.mapa_vigente(conn, emp)
    assert len(mapa) == len(motor.MAPA_PADRAO) and mapa[0][0] == motor.MAPA_PADRAO[0][0]
    assert db.empresa_por_cnpj(conn, CNPJ)["id"] == emp and db.empresa_por_cnpj(conn, "x") is None


def test_importar_e_recarregar_calcula_igual(conn, emp):
    for mes in (1, 2, 3):
        cab, contas = _arq(mes)
        conf = motor.conferencias_arquivo(contas, db.mapa_vigente(conn, emp), cab["periodo"])
        db.inserir_importacao(conn, emp, cab, contas, "teste@x", conf)
    assert db.listar_meses_ativos(conn, emp) == ["2026-01", "2026-02", "2026-03"]
    b_db = motor.Balancetes(db.periodos_mensais_ativos(conn, emp), db.mapa_vigente(conn, emp))
    b_mem = motor.Balancetes(MESES)
    assert motor.dre(b_db, "2026-03") == motor.dre(b_mem, "2026-03")
    assert motor.balanco(b_db, "2026-03") == motor.balanco(b_mem, "2026-03")
    assert not [c for c in motor.conferencias(b_db) if not c["ok"]]
    imps = db.listar_importacoes(conn, emp)
    assert len(imps) == 3 and all(i["ativo"] and i["falhas"] == 0 and i["n_contas"] == 41 for i in imps)


def test_mesmo_arquivo_nao_entra_duas_vezes(conn, emp):
    cab, contas = _arq(1)
    imp = db.inserir_importacao(conn, emp, cab, contas, "u")
    with pytest.raises(db.ImportacaoDuplicada) as e:
        db.inserir_importacao(conn, emp, cab, contas, "u")
    assert e.value.importacao_id == imp and e.value.ativo


def test_mesmo_periodo_pede_substituicao_e_guarda_a_anterior(conn, emp):
    cab, contas = _arq(1)
    primeira = db.inserir_importacao(conn, emp, cab, contas, "u")
    contas2 = [dict(c) for c in contas]
    contas2[0]["nome"] = "Banco Alfa C/C (revisado)"
    cab2 = dict(cab, sha256="f" * 64, arquivo="2026-01-revisado.csv")
    with pytest.raises(db.PeriodoJaImportado):
        db.inserir_importacao(conn, emp, cab2, contas2, "u")
    segunda = db.inserir_importacao(conn, emp, cab2, contas2, "u", substituir=True)
    imps = {i["id"]: i for i in db.listar_importacoes(conn, emp)}
    assert not imps[primeira]["ativo"] and imps[segunda]["ativo"]
    assert len(db.carregar_contas(conn, primeira)) == 41                 # a anterior continua guardada
    assert list(db.periodos_mensais_ativos(conn, emp)) == ["2026-01"]


def test_desfazer_e_reativar(conn, emp):
    cab, contas = _arq(1)
    a = db.inserir_importacao(conn, emp, cab, contas, "u")
    db.definir_ativo(conn, a, False, "u")
    assert db.listar_meses_ativos(conn, emp) == []
    cab2 = dict(cab, sha256="e" * 64, arquivo="outro.csv")
    b = db.inserir_importacao(conn, emp, cab2, contas, "u")           # periodo livre de novo
    with pytest.raises(db.PeriodoJaImportado):
        db.definir_ativo(conn, a, True, "u")                          # b esta' ativa
    db.definir_ativo(conn, b, False, "u")
    db.definir_ativo(conn, a, True, "u")
    assert db.listar_meses_ativos(conn, emp) == ["2026-01"]
    db.definir_status(conn, a, "REVISADA", "u")
    assert [i for i in db.listar_importacoes(conn, emp) if i["id"] == a][0]["status"] == "REVISADA"


def test_transacao_atomica_nada_fica_pela_metade(conn, emp):
    cab, contas = _arq(1)
    ruim = [dict(c) for c in contas]
    ruim[3]["sal"] = None                                             # viola NOT NULL no meio do lote
    with pytest.raises(Exception):
        db.inserir_importacao(conn, emp, cab, ruim, "u")
    assert db.listar_importacoes(conn, emp) == []
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM balancete_linha")
        assert cur.fetchone()[0] == 0
    assert conn.autocommit is True                                    # estado da conexao restaurado


def test_acumulado_separado_dos_mensais(conn, emp):
    cab, contas = _arq(2, ini="01/01/2026", fim="28/02/2026")
    assert cab["tipo"] == "ACUMULADO"
    db.inserir_importacao(conn, emp, cab, contas, "u")
    assert db.listar_meses_ativos(conn, emp) == [] and list(db.acumulados_ativos(conn, emp)) == ["2026-02"]


def test_eventos_registram_importacoes(conn, emp):
    cab, contas = _arq(1)
    conf = [{"grupo": "Teste", "descricao": "falha proposital", "ok": False, "detalhe": "x"}]
    imp = db.inserir_importacao(conn, emp, cab, contas, "ana@x", conf)
    ev = db.listar_eventos(conn, emp)
    assert ev and ev[0]["nivel"] == "aviso" and "1 conferência" in ev[0]["mensagem"] and ev[0]["usuario"] == "ana@x"
    assert db.conferencias_da_importacao(conn, imp)[0]["ok"] is False
    db.registrar_evento(conn, "teste", "info", "ok", empresa_id=emp)
    db.registrar_evento(conn, "teste", "nivel-invalido", "nao levanta excecao", empresa_id=emp)   # melhor esforco


def test_role_do_app_nao_apaga(conn, emp, pg_dsn):
    """gdf_app (a role de producao) so' tem SELECT/INSERT/UPDATE: DELETE precisa falhar."""
    import psycopg2
    cab, contas = _arq(1)
    db.inserir_importacao(conn, emp, cab, contas, "u")
    c = psycopg2.connect(pg_dsn)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SET ROLE gdf_app")
        cur.execute("SELECT count(*) FROM gdf.importacao")
        assert cur.fetchone()[0] == 1
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM gdf.importacao")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM gdf.balancete_linha")
        cur.execute("UPDATE gdf.importacao SET ativo = false")        # desfazer continua permitido
    c.close()


def test_schema_e_idempotente(pg_dsn):
    import psycopg2
    from conftest import SCHEMA_SQL
    c = psycopg2.connect(pg_dsn)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf'")
        assert cur.fetchone()[0] == 8
    c.close()


def test_preparar_conexao_fixa_schema_e_exige_role_do_app(pg_dsn):
    """Pooler do Supabase nao repassa o search_path da role: o app fixa na sessao. E recusa usuario que nao seja gdf_app."""
    import psycopg2
    import conexao
    c = psycopg2.connect(pg_dsn)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SET ROLE gdf_app")
        cur.execute("RESET search_path")                                  # simula o pooler: sessao sem o schema gdf
        with pytest.raises(psycopg2.errors.UndefinedTable):
            cur.execute("SELECT id FROM empresa")
    c.rollback()
    with c.cursor() as cur:
        cur.execute("SET ROLE gdf_app")
        cur.execute("RESET search_path")
    assert conexao.preparar_conexao(c) == "gdf_app"
    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM empresa")                       # agora resolve para gdf.empresa
        assert cur.fetchone()[0] >= 0
    c.close()
    c2 = psycopg2.connect(pg_dsn)                                         # superuser de teste: nao e' gdf_app
    with pytest.raises(conexao.ConexaoInvalida):
        conexao.preparar_conexao(c2)
    c2.close()


# ---------------------------------------------------------------- apelidos, mapa e relatorio (v1.9)
def test_apelidos_salvar_trocar_e_limpar(conn, emp):
    assert db.salvar_apelidos(conn, emp, {"Itaú s/a - Cdb": "Itaú Unibanco — CDB"}, "u") == 1
    assert db.listar_apelidos(conn, emp) == {"itaú s/a - cdb": "Itaú Unibanco — CDB"}
    assert db.salvar_apelidos(conn, emp, {"Itaú s/a - Cdb": "Itaú Unibanco — CDB"}, "u") == 0          # sem mudanca
    assert db.salvar_apelidos(conn, emp, {"Itaú s/a - Cdb": "Itaú CDB"}, "u") == 1
    assert db.listar_apelidos(conn, emp)["itaú s/a - cdb"] == "Itaú CDB"
    assert db.salvar_apelidos(conn, emp, {"Itaú s/a - Cdb": ""}, "u") == 1                            # vazio = volta ao original
    assert db.listar_apelidos(conn, emp) == {}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE ativo) FROM apelido WHERE empresa_id=%s", (emp,))
        assert cur.fetchone() == (2, 0)                                                              # nada apagado


def test_apelido_apagado_na_tabela_vem_como_nan_e_nao_quebra(conn, emp):
    """Bug achado ao vivo: apagar a celula no data_editor devolve NaN (float) -> AttributeError. Deve voltar ao nome original."""
    nan = float("nan")
    assert db.txt(None) == "" and db.txt(nan) == "" and db.txt("  a   b ") == "a b"
    assert db.salvar_apelidos(conn, emp, {"Gsm Ambiental Ltda": "GSM"}, "u") == 1
    assert db.salvar_apelidos(conn, emp, {"Gsm Ambiental Ltda": nan}, "u") == 1
    assert db.listar_apelidos(conn, emp) == {}
    assert db.salvar_apelidos(conn, emp, {"Gsm Ambiental Ltda": None, "Outro": nan}, "u") == 0


def test_mapa_edicao_cria_nova_linha_e_guarda_a_anterior(conn, emp):
    antes = {m[0]: m for m in db.mapa_vigente(conn, emp)}["juros"]
    db.salvar_mapa_linha(conn, emp, "juros", "(−) Juros e encargos", ["5.7.11.001.005", "5.7.11.001.006"], "D", "u", "nova conta de encargos")
    depois = {m[0]: m for m in db.mapa_vigente(conn, emp)}["juros"]
    assert depois[1] == "(−) Juros e encargos" and depois[3] == ["5.7.11.001.005", "5.7.11.001.006"] and depois[3] != antes[3]
    hist = [h for h in db.historico_mapa(conn, emp) if h["chave"] == "juros"]
    assert [h["ativo"] for h in hist] == [True, False] and hist[0]["motivo"] == "nova conta de encargos"
    for ruim, msg in [(dict(motivo=""), "motivo"), (dict(prefixos=[]), "prefixo"), (dict(prefixos=["5.x"]), "inválido"), (dict(rotulo=" "), "vazio"), (dict(natureza=None), "natureza")]:
        args = dict(rotulo="X", prefixos=["5.7.11"], natureza="D", motivo="m"); args.update(ruim)
        with pytest.raises(db.MapaInvalido, match=msg):
            db.salvar_mapa_linha(conn, emp, "juros", args["rotulo"], args["prefixos"], args["natureza"], "u", args["motivo"])
    with pytest.raises(db.MapaInvalido, match="Nada mudou"):
        db.salvar_mapa_linha(conn, emp, "juros", "(−) Juros e encargos", ["5.7.11.001.005", "5.7.11.001.006"], "D", "u", "repetido")
    with pytest.raises(db.MapaInvalido, match="não existe"):
        db.salvar_mapa_linha(conn, emp, "chave_inexistente", "X", ["1"], None, "u", "m")


def test_relatorio_versoes_status_e_config(conn, emp):
    from datetime import date
    per = date(2026, 3, 1)
    assert db.config_empresa(conn, emp) == {}
    db.salvar_config_empresa(conn, emp, {"assinantes": [{"nome": "A", "cargo": "Adm"}]}, "u")
    assert db.config_empresa(conn, emp)["assinantes"][0]["nome"] == "A"
    r1, v1 = db.registrar_relatorio(conn, emp, per, "a" * 64, {"dest_1": "x"}, [{"nome": "A", "cargo": "Adm"}], "u", {"k": 1})
    r2, v2 = db.registrar_relatorio(conn, emp, per, "b" * 64, {}, [], "u")
    assert (v1, v2) == (1, 2)
    lista = db.listar_relatorios(conn, emp, per)
    assert [r["versao"] for r in lista] == [2, 1] and lista[0]["status"] == "RASCUNHO"
    db.definir_status_relatorio(conn, r1, "REVISADO", "u")
    assert [r["status"] for r in db.listar_relatorios(conn, emp, per)] == ["RASCUNHO", "REVISADO"]
    with conn.cursor() as cur:
        cur.execute("UPDATE relatorio SET status='ASSINADO' WHERE id=%s", (r1,))
    with pytest.raises(ValueError, match="assinado"):
        db.definir_status_relatorio(conn, r1, "RASCUNHO", "u")
    with pytest.raises(ValueError):
        db.definir_status_relatorio(conn, r2, "ASSINADO", "u")
