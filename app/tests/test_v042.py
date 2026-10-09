# -*- coding: utf-8 -*-
"""v0.4.2: fuso de Brasilia, ajustes do PDF (logo da capa, unidades, 'x' na liquidez, dez/AA) e trava da conexao compartilhada."""
import io
import re
import threading
import time
from datetime import datetime, timezone

import pdfplumber
import pytest

import fuso
import motor
import relatorio_dados as RD
import relatorio_pdf as RP
from dados_sinteticos import gerar_meses

MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50)])
EMP = {"id": 1, "codigo": "TESTE", "razao_social": "Empresa Sintetica Ltda", "cnpj": "00.000.000/0001-91"}


def _pdf(**cfg):
    per = dict(MESES)
    b = motor.Balancetes(per)
    x = RD.montar(EMP, b, "2026-03", motor.balanco(b, "2026-03"), motor.dre(b, "2026-03"), per["2026-03"], config=cfg or None)
    pdf = RP.gerar_pdf(x, {}, "RASCUNHO", "09/10/2026 10:00")
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        return pdf, [pg.extract_text() or "" for pg in p.pages], x


def test_fuso_converte_utc_para_brasilia():
    assert fuso.fmt_br(datetime(2026, 10, 9, 13, 23, tzinfo=timezone.utc)) == "09/10/2026 10:23"
    assert fuso.fmt_br(datetime(2026, 10, 9, 1, 5)) == "08/10/2026 22:05"            # sem fuso = UTC; vira o dia anterior
    assert fuso.fmt_br(None) == "" and fuso.agora_br().utcoffset().total_seconds() == -3 * 3600


def test_capa_sem_logo_do_grupo_por_padrao_e_com_quando_ligado():
    assert RD.info_empresa(EMP, None)["logo_grupo_capa"] is False
    assert RD.info_empresa(EMP, {"logo_grupo_capa": True})["logo_grupo_capa"] is True
    sem, _, _ = _pdf()
    com, _, _ = _pdf(logo_grupo_capa=True)
    assert sem != com and len(com) > len(sem)                                      # a imagem do grupo so' entra quando ligada


def test_cabecalho_da_variacao_do_balanco_usa_dezembro_do_ano_anterior():
    _, paginas, _ = _pdf()
    bp = paginas[6]
    assert "dez/25" in bp and "dez/26" not in bp


def test_liquidez_corrente_sai_com_x_nas_paginas_de_indicadores():
    _, paginas, _ = _pdf()
    assert re.search(r"\d,\d\dx", paginas[5]) and re.search(r"\d,\d\dx", paginas[7])


# ------------------------------------------------------------------ trava da conexao (precisa do Postgres de teste)
@pytest.mark.pg
def test_transacao_segura_a_conexao_e_outra_thread_espera(pg_dsn):
    import psycopg2
    import db
    from conexao import ConexaoGDF
    c = psycopg2.connect(pg_dsn, connection_factory=ConexaoGDF)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SET search_path = gdf, public")
    ordem, dentro = [], threading.Event()

    def a():
        with db.transacao(c):
            dentro.set()
            time.sleep(0.6)
            with c.cursor() as cur:
                cur.execute("SELECT 1")
            ordem.append("a_commit")

    def b():
        dentro.wait()
        with c.cursor() as cur:
            cur.execute("SELECT 2")                                                 # tem que esperar a transacao da thread A acabar
        ordem.append("b_executou")

    ta, tb = threading.Thread(target=a), threading.Thread(target=b)
    ta.start(); tb.start(); ta.join(); tb.join()
    assert ordem == ["a_commit", "b_executou"] and c.autocommit is True
    c.close()
