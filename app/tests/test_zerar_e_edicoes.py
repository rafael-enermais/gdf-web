# -*- coding: utf-8 -*-
"""v0.4.5: SQL de zerar dados + 'nada se perde' em todas as edicoes (Postgres descartavel)."""
import json
from pathlib import Path

import psycopg2
import pytest

import db
import importador_csv as I
import motor
from dados_sinteticos import csv_texto, gerar_meses

pytestmark = pytest.mark.pg
CNPJ = "54.800.488/0001-60"
MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)])
ZERAR = Path(__file__).resolve().parent.parent.parent / "sql" / "zerar_dados.sql"
TABELAS = ["empresa", "importacao", "balancete_linha", "conferencia", "mapa_conta", "apelido", "relatorio", "evento"]


def _arq(m, nome=None):
    ult = {1: "31", 2: "28", 3: "31"}[m]
    return I.ler_bytes(csv_texto(MESES[f"2026-{m:02d}"], cnpj=CNPJ, ini=f"01/{m:02d}/2026", fim=f"{ult}/{m:02d}/2026"), nome or f"{m}.csv")


def _semear_tudo(conn):
    """Usa TODAS as edicoes do app uma vez: importar, substituir, desfazer, status, mapa, apelido, config, relatorio, assinatura."""
    emp = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    db.garantir_mapa(conn, emp)
    ids = []
    for m in (1, 2, 3):
        cab, contas = _arq(m)
        ids.append(db.inserir_importacao(conn, emp, cab, contas, "t", motor.conferencias_arquivo(contas, db.mapa_vigente(conn, emp), cab["periodo"])))
    db.definir_status(conn, ids[0], "REVISADA", "t")
    db.definir_ativo(conn, ids[2], False, "t")
    db.definir_ativo(conn, ids[2], True, "t")
    db.salvar_mapa_linha(conn, emp, "dep_vista", "Depósitos bancários à vista", ["1.1.01.002"], None, "t", "teste")
    db.salvar_apelidos(conn, emp, {"Banco Alfa C/C": "Alfa"}, "t")
    db.salvar_config_empresa(conn, emp, {"assinantes": [{"nome": "Fulano", "cargo": "Contador"}]}, "t")
    rid, _ = db.registrar_relatorio(conn, emp, __import__("datetime").date(2026, 3, 1), "a" * 64, {"dest_1": "x"}, [], "t", {"importacoes": ids}, status="REVISADO")
    db.registrar_assinatura(conn, rid, "assinado.pdf", "b" * 64, "t")
    return emp


def _contagens(conn):
    with conn.cursor() as cur:
        out = {}
        for t in TABELAS:
            cur.execute(f"SELECT count(*) FROM gdf.{t}")
            out[t] = cur.fetchone()[0]
    return out


def test_zerar_para_com_relatorio_assinado_e_nao_apaga_nada(conn):
    _semear_tudo(conn)
    antes = _contagens(conn)
    assert antes["relatorio"] == 1 and antes["importacao"] == 3
    with pytest.raises(psycopg2.Error) as exc:
        conn.cursor().execute(ZERAR.read_text(encoding="utf-8"))
    assert "ASSINADO" in str(exc.value)
    conn.rollback() if not conn.autocommit else None
    with conn.cursor() as cur:
        cur.execute("ROLLBACK")
    assert _contagens(conn) == antes                                 # nada foi apagado


def test_zerar_com_liberacao_zera_tudo_recomeca_numeracao_e_o_app_recria(conn):
    _semear_tudo(conn)
    sql = ZERAR.read_text(encoding="utf-8").replace("-- SET LOCAL gdf.permitir_zerar_assinados", "SET LOCAL gdf.permitir_zerar_assinados")
    with conn.cursor() as cur:
        cur.execute(sql)
    assert _contagens(conn) == {t: 0 for t in TABELAS}
    # o schema, a role e a RLS continuam; o app recria empresa e mapa padrao no proximo acesso
    emp = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    assert emp == 1                                                  # RESTART IDENTITY
    assert db.garantir_mapa(conn, emp) is True and len(db.mapa_vigente(conn, emp)) == len(motor.MAPA_PADRAO)
    assert db.config_empresa(conn, emp) == {} and db.listar_apelidos(conn, emp) == {}
    cab, contas = _arq(1)
    assert db.inserir_importacao(conn, emp, cab, contas, "t") == 1   # a MESMA planilha entra de novo (hash liberado)
    with conn.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'gdf.importacao'::regclass")
        assert cur.fetchone()[0] is True
        cur.execute("SELECT has_table_privilege('gdf_app','gdf.importacao','INSERT'), has_table_privilege('gdf_app','gdf.importacao','DELETE')")
        assert cur.fetchone() == (True, False)


def test_zerar_sem_assinados_roda_direto(conn):
    emp = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    db.garantir_mapa(conn, emp)
    cab, contas = _arq(2)
    db.inserir_importacao(conn, emp, cab, contas, "t")
    with conn.cursor() as cur:
        cur.execute(ZERAR.read_text(encoding="utf-8"))
    assert _contagens(conn) == {t: 0 for t in TABELAS}


def test_nada_se_perde_em_nenhuma_edicao(conn):
    """Toda edicao so' acrescenta ou inativa: contagens por tabela nunca diminuem e as linhas antigas continuam legiveis."""
    emp = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    db.garantir_mapa(conn, emp)
    cab, contas = _arq(1)
    a = db.inserir_importacao(conn, emp, cab, contas, "t")
    ant = _contagens(conn)
    cab2 = dict(cab, sha256="c" * 64, arquivo="retificado.csv")
    b = db.inserir_importacao(conn, emp, cab2, contas, "t", substituir=True)
    db.definir_ativo(conn, b, False, "t")
    db.definir_ativo(conn, a, True, "t")
    db.definir_status(conn, a, "REVISADA", "t")
    db.salvar_mapa_linha(conn, emp, "juros", "Juros pagos ou incorridos", ["3.1.02.001", "3.1.02.002"], "D", "t", "teste de edicao")
    db.salvar_apelidos(conn, emp, {"Fornecedor X Ltda": "X"}, "t")
    db.salvar_apelidos(conn, emp, {"Fornecedor X Ltda": ""}, "t")                       # limpar apelido = inativar
    db.salvar_config_empresa(conn, emp, {"assinantes": [{"nome": "A", "cargo": "B"}]}, "t")
    dep = _contagens(conn)
    assert all(dep[t] >= ant[t] for t in TABELAS), (ant, dep)
    assert len(db.carregar_contas(conn, a)) == len(db.carregar_contas(conn, b)) == 41      # as duas importacoes seguem completas
    hist = db.historico_mapa(conn, emp)
    assert [h["ativo"] for h in hist if h["chave"] == "juros"] == [True, False]            # a versao anterior do mapa continua la
    with conn.cursor() as cur:
        cur.execute("SELECT apelido, ativo FROM apelido WHERE empresa_id=%s", (emp,))
        assert cur.fetchall() == [("X", False)]
    assert db.listar_apelidos(conn, emp) == {}
    assert db.config_empresa(conn, emp)["assinantes"][0]["nome"] == "A"


def test_regras_ativas_mudam_quando_mapa_ou_apelido_mudam(conn):
    emp = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    db.garantir_mapa(conn, emp)
    r0 = db.ids_regras_ativas(conn, emp)
    assert len(r0["mapa"]) == len(motor.MAPA_PADRAO) and r0["apelidos"] == []
    db.salvar_apelidos(conn, emp, {"Beta Ltda": "Beta"}, "t")
    r1 = db.ids_regras_ativas(conn, emp)
    assert r1["mapa"] == r0["mapa"] and len(r1["apelidos"]) == 1
    db.salvar_mapa_linha(conn, emp, "dep_vista", "Depósitos à vista", ["1.1.01.002"], None, "t", "ajuste")
    assert db.ids_regras_ativas(conn, emp)["mapa"] != r0["mapa"]


# ---------------------------------------------------------------- v0.4.7: SQL que limpa so' os residuos do teste ao vivo
LIMPAR = Path(__file__).resolve().parent.parent.parent / "sql" / "limpar_residuos_teste.sql"


def _semear_residuos(conn):
    """Reproduz o estado de producao: #1 acumulado original, #2..#9 mensais, #10/#11 acumulados de teste, relatorios v1..v4 de 08/2026."""
    import datetime
    emp = db.garantir_empresa(conn, "ANASTACIO", "Anastácio Transmissora de Energia S.A.", CNPJ)
    db.garantir_mapa(conn, emp)

    def acum(nome, h):
        cab, contas = _arq(3, nome)
        cab = {**cab, "tipo": "ACUMULADO", "ini": datetime.date(2026, 1, 1), "fim": datetime.date(2026, 8, 31), "sha256": h * 64, "periodo": "2026-08"}
        return db.inserir_importacao(conn, emp, cab, contas, "t", None, status="REVISADA", substituir=True)
    assert acum("Relatorios_Contabeis_Balancete.csv", "1") == 1
    with conn.cursor() as cur:                                    # #2..#9 mensais ficam como estao; aqui basta avancar a sequencia
        cur.execute("SELECT setval(pg_get_serial_sequence('gdf.importacao','id'), 9)")
    assert acum("balancete_08_2026_TESTE.csv", "2") == 10          # substitui a #1
    assert acum("01 a 08.2026 - Balancete - sem assinatura.pdf", "3") == 11
    d = datetime.date(2026, 8, 1)
    for v, st in ((1, "REVISADO"), (2, "REVISADO"), (3, "RASCUNHO"), (4, "RASCUNHO")):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO relatorio (empresa_id, periodo, versao, status, pdf_sha256) VALUES (%s,%s,%s,%s,%s)", (emp, d, v, st, str(v) * 64))
    return emp


def test_limpar_residuos_apaga_so_o_combinado_e_devolve_a_importacao_1(conn):
    _semear_residuos(conn)
    antes = _contagens(conn)
    conn.cursor().execute(LIMPAR.read_text(encoding="utf-8"))
    depois = _contagens(conn)
    assert depois["importacao"] == antes["importacao"] - 2 and depois["relatorio"] == 2
    assert depois["evento"] == antes["evento"] + 1
    with conn.cursor() as cur:
        cur.execute("SELECT id, ativo, status FROM importacao")
        assert cur.fetchall() == [(1, True, "REVISADA")]
        cur.execute("SELECT count(*) FROM balancete_linha WHERE importacao_id IN (10,11)")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT versao FROM relatorio ORDER BY versao")
        assert [r[0] for r in cur.fetchall()] == [1, 2]
    assert db.registrar_relatorio  # o app continua gerando a proxima versao sem conflito
    emp = db.empresa_por_cnpj(conn, CNPJ)["id"]
    import datetime
    assert db.proxima_versao_relatorio(conn, emp, datetime.date(2026, 8, 1)) == 3


def test_limpar_residuos_recusa_se_o_estado_for_outro(conn):
    _semear_tudo(conn)                                              # estado diferente do esperado (sem #10/#11)
    antes = _contagens(conn)
    with pytest.raises(psycopg2.Error) as exc:
        conn.cursor().execute(LIMPAR.read_text(encoding="utf-8"))
    assert "Nada foi apagado" in str(exc.value)
    conn.cursor().execute("ROLLBACK")
    assert _contagens(conn) == antes
