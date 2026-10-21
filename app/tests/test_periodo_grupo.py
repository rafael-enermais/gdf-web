# -*- coding: utf-8 -*-
"""Periodos flexiveis do Painel da Diretoria (periodo.py) e Grupo ENERMAIS (grupo_enermais.py): funcoes puras + leitura no Postgres descartavel."""
import pytest

import grupo_enermais as GE
import periodo as PER


def test_resolver_modos_de_periodo():
    assert PER.resolver(PER.MES, "2026-10") == ("2026-10", "2026-10")
    assert PER.resolver(PER.TRI, "2026-10") == ("2026-08", "2026-10")
    assert PER.resolver(PER.SEM, "2026-03") == ("2025-10", "2026-03")                 # atravessa o ano
    assert PER.resolver(PER.ANO, "2026-10") == ("2026-01", "2026-10")                 # padrao: como o painel era
    assert PER.resolver(PER.DOZE, "2026-10") == ("2025-11", "2026-10")
    assert PER.resolver(PER.PERSONALIZADO, "2026-10", "2026-04") == ("2026-04", "2026-10")
    assert PER.resolver(PER.PERSONALIZADO, "2026-04", "2026-10") == ("2026-04", "2026-04")     # 'de' depois de 'ate': vale o 'ate'
    assert PER.PADRAO == PER.ANO and set(PER.MODOS) >= {PER.MES, PER.TRI, PER.ANO, PER.DOZE, PER.PERSONALIZADO}


def test_meses_entre_anterior_e_rotulos():
    assert PER.meses_entre("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert PER.meses_entre("2026-05", "2026-04") == []
    assert PER.anterior("2026-08", "2026-10") == ("2026-05", "2026-07")                # mesmo tamanho, logo antes
    assert PER.anterior("2026-01", "2026-01") == ("2025-12", "2025-12")
    assert PER.rotulo("2026-10", "2026-10") == "10/2026" and PER.rotulo("2026-01", "2026-10") == "01/2026 a 10/2026"
    assert PER.curto("2026-01", "2026-10") == "Jan–Out/26" and PER.curto("2026-10", "2026-10") == "Out/26" and PER.curto("2025-11", "2026-10") == "Nov/25–Out/26"


def test_nucleo_ignora_acento_ltda_e_cnpj():
    assert GE.nucleo("Enermais Soluções Ltda - CNPJ 12.345.678/0001-90") == "ENERMAIS SOLUCOES"
    assert GE.nucleo("SMG SOLUÇÕES LTDA") == GE.nucleo("smg solucoes ltda.") == "SMG SOLUCOES"
    assert GE.nucleo(None) == ""
    nuc = [GE.nucleo(n) for n in GE.NOMES_PADRAO]
    assert GE.eh_do_grupo("ENERMAIS ENERGIA LTDA", nuc) and GE.eh_do_grupo("Enermais Renováveis Ltda - CNPJ 1", nuc)
    assert not GE.eh_do_grupo("ENERMAIS ENERGIA SOLAR LTDA", nuc) and not GE.eh_do_grupo("", nuc) and not GE.eh_do_grupo("STELLANTIS LTDA", nuc)
    assert len(set(nuc)) == 6


@pytest.mark.pg
def test_grupo_vem_do_cadastro_do_sienge_ids_1_a_6(conn):
    assert GE.nucleos_do_grupo(conn) == sorted(GE.nucleo(n) for n in GE.NOMES_PADRAO)           # cadastro vazio -> lista padrao
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_empresa_sienge (id, nome) VALUES (1, 'ENERMAIS ENERGIA LTDA'), (2, 'SMG SOLUÇÕES LTDA'), (9, 'STELLANTIS LTDA')")
    assert GE.nucleos_do_grupo(conn) == ["ENERMAIS ENERGIA", "SMG SOLUCOES"]                    # so' os ids 1 a 6; Stellantis (id 9) nao entra
    with conn.cursor() as cur:
        cur.execute("SELECT t FROM (SELECT %s AS t) x WHERE " + GE.sql_nucleo("t") + " = 'ENERMAIS ENERGIA'", ("Enermais Energia Ltda - CNPJ 5",))
        assert cur.fetchone() is not None                                                      # mesma regra no SQL
        cur.execute("SELECT t FROM (SELECT %s AS t) x WHERE " + GE.sql_nucleo("t") + " = 'SMG SOLUCOES'", ("SMG Soluções S/A",))
        assert cur.fetchone() is not None
