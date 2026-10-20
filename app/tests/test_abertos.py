# -*- coding: utf-8 -*-
"""Rotina semanal de titulos em aberto (scripts/ingest_abertos_gdf.py): janelas, filtro de abertos, medicao sem gravar."""
import importlib.util
from pathlib import Path

import sienge_api as S

RAIZ = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("ingest_abertos_gdf", RAIZ / "scripts" / "ingest_abertos_gdf.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def test_janelas_cobrem_tudo_sem_buraco_nem_sobreposicao():
    j = S.janelas_abertos("2023-01", "2032-12")
    assert j[0] == ("2023-01", "2023-03") and j[-1] == ("2032-01", "2032-12")
    assert ("2026-10", "2026-12") in j and ("2027-01", "2027-12") in j
    for (a1, b1), (a2, b2) in zip(j, j[1:]):
        y, m = int(b1[:4]), int(b1[5:])
        assert (a2 == f"{y + 1}-01") if m == 12 else (a2 == f"{y}-{m + 1:02d}")
    assert S.janelas_abertos("2026-03", "2026-04") == [("2026-03", "2026-04")]


def test_somente_abertos_tira_o_que_foi_todo_baixado():
    regs = [{"billId": 1, "originalAmount": 100.0, "payments": [{"grossAmount": 100.0}]},
            {"billId": 2, "originalAmount": 100.0, "payments": [{"grossAmount": 40.0}]},
            {"billId": 3, "originalAmount": 100.0, "payments": []},
            {"billId": None, "originalAmount": 5.0}]
    assert [r["billId"] for r in S.somente_abertos(regs, "P")] == [2, 3]
    rec = [{"billId": 9, "originalAmount": 10.0, "receipts": [{"grossAmount": 10.0}]}, {"billId": 8, "originalAmount": 10.0}]
    assert [r["billId"] for r in S.somente_abertos(rec, "R")] == [8]


def test_medir_nao_grava_e_nao_imprime_valores(capsys):
    chamadas = []

    def buscar(cli, lado, mes, tipo, mes_fim=None):
        chamadas.append((lado, mes, tipo, mes_fim))
        return [{"billId": 1, "originalAmount": 123456.78, "creditorName": "SEGREDO LTDA", "payments": [], "dueDate": "2026-01-01"}]
    linhas = []
    assert A.executar(None, None, "2026-01", "2026-12", False, buscar=buscar, log=linhas.append) == 0
    assert {c[2] for c in chamadas} == {"D"} and {c[0] for c in chamadas} == {"P", "R"}
    texto = "\n".join(linhas)
    assert "SEGREDO" not in texto and "123456" not in texto
    assert "campos do título" in texto and "billId" in texto
    assert "gravar=False" in texto


def test_falha_de_uma_janela_devolve_1_e_segue():
    def buscar(cli, lado, mes, tipo, mes_fim=None):
        if mes == "2026-01":
            raise S.ErroSienge("boom")
        return []
    assert A.executar(None, None, "2026-01", "2026-12", False, buscar=buscar, log=lambda *_: None) == 1


def test_janela_que_nao_responde_e_pulada_e_a_rotina_segue():
    """Se uma janela passar do limite, registra ERRO e continua nas proximas (antes ficava parado ate o fim do job)."""
    import time as _t
    chamadas, linhas = [], []

    def buscar(cli, lado, a, tipo, mes_fim=None):
        chamadas.append((lado, a))
        if a == "2026-01":
            _t.sleep(5)            # simula o Sienge parado
        return []

    rc = A.executar(None, None, "2025-10", "2026-03", False, buscar=buscar, log=linhas.append, limite_s=1)
    assert rc == 1
    assert any("sem resposta" in l and "2026-01" in l for l in linhas)
    assert ("P", "2026-04") not in chamadas and ("R", "2025-10") in chamadas      # seguiu para a proxima janela e para o outro lado
