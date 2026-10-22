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


# ---- protecoes contra Sienge lento (cargas #7/#8 de 21/10/2026) -------------------------------------------------------------------------------
def test_meses_da_janela():
    assert A._meses_da_janela("2026-11", "2027-02") == [("2026-11", "2026-11"), ("2026-12", "2026-12"), ("2027-01", "2027-01"), ("2027-02", "2027-02")]
    assert A._meses_da_janela("2027-01", "2027-01") == [("2027-01", "2027-01")]


def test_janela_que_estoura_e_quebrada_em_meses_e_so_o_mes_ruim_se_perde():
    """Janela de 3 meses estoura -> refaz mes a mes (com respiro); so' o mes que continua sem resposta fica de fora."""
    import time as _t
    chamadas, linhas, pausas = [], [], []

    def buscar(cli, lado, a, tipo, mes_fim=None):
        chamadas.append((lado, a, mes_fim))
        if a != mes_fim:                       # janela grande: Sienge nao responde
            _t.sleep(5)
        elif a == "2026-02":                   # um mes continua ruim
            _t.sleep(5)
        return [{"billId": 1, "originalAmount": 10.0, "payments": []}]

    rc = A.executar(None, None, "2026-01", "2026-03", False, buscar=buscar, log=linhas.append, limite_s=1, lados=("P",),
                    pausa_apos_estouro_s=7, dormir=pausas.append)
    assert rc == 1                                           # o mes ruim conta como falha
    assert ("P", "2026-01", "2026-01") in chamadas and ("P", "2026-03", "2026-03") in chamadas      # os outros meses foram buscados
    assert not any(c[0] == "R" for c in chamadas)            # so' o lado pedido
    texto = "\n".join(linhas)
    assert "refazer mês a mês" in texto and "desisti deste mês" in texto
    assert pausas and set(pausas) == {7}                     # deu respiro ao Sienge


def test_sienge_fora_do_ar_encerra_o_lado_apos_meses_seguidos_sem_resposta():
    import time as _t
    chamadas, linhas = [], []

    def buscar(cli, lado, a, tipo, mes_fim=None):
        chamadas.append((lado, a, mes_fim))
        _t.sleep(5)
        return []

    rc = A.executar(None, None, "2024-01", "2024-12", False, buscar=buscar, log=linhas.append, limite_s=1, lados=("R",), seguidas_max=3)
    assert rc == 1
    mensais = [c for c in chamadas if c[1] == c[2]]
    assert len(mensais) == 3                                 # parou apos 3 meses seguidos, nao tentou os 12
    assert "Sienge parece fora do ar" in "\n".join(linhas)


def test_prazo_global_encerra_limpo_e_fecha_o_lado_com_erro():
    """Com prazo global estourado: nao busca mais nada, fecha o lado com ERRO (gravacao parcial fica) e devolve 1."""
    relogio_falso = iter([0, 0, 0, 0, 0, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100])
    chamadas, linhas = [], []

    def buscar(cli, lado, a, tipo, mes_fim=None):
        chamadas.append((lado, a))
        return []

    rc = A.executar(None, None, "2026-01", "2026-12", False, buscar=buscar, log=linhas.append, lados=("P", "R"), prazo_global_s=60,
                    relogio=lambda: next(relogio_falso))
    assert rc == 1
    assert len(chamadas) == 1                                # so' a primeira janela coube no prazo
    assert not any(c[0] == "R" for c in chamadas)            # o outro lado nem comecou
    texto = "\n".join(linhas)
    assert "prazo global" in texto and "PARADO PELO PRAZO GLOBAL" in texto


def test_main_le_lado_e_prazo_do_ambiente(monkeypatch):
    recebido = {}

    def falso(conn, cli, ini, fim, gravar, **kw):
        recebido.update(kw, gravar=gravar)
        return 0

    class Cli:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(A, "executar", falso)
    monkeypatch.setattr(A.S, "credenciais", lambda *a, **k: ("u", "p", "b"))
    monkeypatch.setattr(A.S, "Cliente", Cli)
    assert A.main({"GDF_ABERTOS_GRAVAR": "nao", "GDF_ABERTOS_LADO": "r", "GDF_ABERTOS_PRAZO_MIN": "25"}) == 0
    assert recebido["lados"] == ("R",) and recebido["prazo_global_s"] == 25 * 60 and recebido["gravar"] is False
    assert A.main({"GDF_ABERTOS_GRAVAR": "nao"}) == 0
    assert recebido["lados"] == ("P", "R") and recebido["prazo_global_s"] == 40 * 60
    assert A.main({"GDF_ABERTOS_GRAVAR": "nao", "GDF_ABERTOS_PRAZO_MIN": "abc"}) == 0
    assert recebido["prazo_global_s"] == A.PRAZO_GLOBAL_S
