# -*- coding: utf-8 -*-
"""
GDF V2 - DIAGNOSTICO do MOVIMENTO BANCARIO do Sienge (bulk-data/v1/bank-movement). SOMENTE LEITURA; NAO grava nada no banco.
Objetivo: achar como aparecem os "avisos de lancamento" (juros e tarifas de banco, origem BC) que a busca de contas pagas nao traz.
O log do Actions e' PUBLICO: este script imprime SO contagens, nomes de campos e codigos (origem, operacao, historico, conta do plano); nunca valores em R$, nomes de pessoas/empresas.
Variaveis: SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL. Opcional GDF_BANCO_MES="2026-09".
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import sienge_api as S  # noqa: E402

ENDPOINT = "bulk-data/v1/bank-movement"
CONTAS_ALVO = ("2.03.04.09", "2.03.01.04", "2.03.01.02", "2.03.01.01", "2.03.01.07", "2.03.01.15", "1.03.04.02", "1.03.02.02")


def _cats(r: dict) -> list:
    v = r.get("financialCategories")
    if isinstance(v, dict):
        return [v]
    return [c for c in (v or []) if isinstance(c, dict)]


def _cod(c: dict) -> str:
    for k, v in c.items():
        if "ategoryid" in k.lower().replace("_", "") and v not in (None, ""):
            return S.cod_plano(v)
    return ""


def resumir(regs: list) -> dict:
    """So contagens e codigos. Funcao pura (testavel)."""
    regs = [r for r in regs if isinstance(r, dict)]
    sem_titulo = [r for r in regs if r.get("billId") in (None, 0, "")]
    contas = Counter()
    for r in regs:
        for c in _cats(r):
            contas[_cod(c)] += 1
    cats1 = next((c for r in regs for c in _cats(r)), {})
    return {
        "registros": len(regs),
        "sem_titulo": len(sem_titulo),
        "com_plano": sum(1 for r in regs if _cats(r)),
        "sem_titulo_com_plano": sum(1 for r in sem_titulo if _cats(r)),
        "por_origem": dict(Counter(str(r.get("bankMovementOriginId")) for r in regs)),
        "por_tipo_operacao": dict(Counter(str(r.get("bankMovementOperationType")) for r in regs)),
        "por_operacao": dict(Counter(f"{r.get('bankMovementOperationId')}={r.get('bankMovementOperationName')}" for r in regs)),
        "sem_titulo_por_origem": dict(Counter(str(r.get("bankMovementOriginId")) for r in sem_titulo)),
        "sem_titulo_por_historico": dict(Counter(str(r.get("bankMovementHistoricId")) for r in sem_titulo).most_common(25)),
        "campos_plano": sorted(cats1.keys()),
        "campos_centro": sorted((next((c for r in regs for c in (r.get("buldingCosts") or []) if isinstance(c, dict)), {})).keys()),
        "contas_alvo": {c: contas.get(c, 0) for c in CONTAS_ALVO},
        "sem_titulo_contas_alvo": {c: sum(1 for r in sem_titulo for k in _cats(r) if _cod(k) == c) for c in CONTAS_ALVO},
    }


def main() -> int:
    mes = (os.environ.get("GDF_BANCO_MES") or "2026-09").strip()[:7]
    user, pwd, base = S.credenciais(None, os.environ)
    cli = S.Cliente(user, pwd, base, pausa=6, esperas_429=(30, 60, 120, 240))
    ini, fim = S.limites_do_mes(mes)
    for sel in ("M", "B"):
        t0 = time.monotonic()
        try:
            regs = S.lista(cli.get(ENDPOINT, {"startDate": ini.isoformat(), "endDate": fim.isoformat(), "selectionType": sel}))
        except S.ErroSienge as e:
            print(f"selectionType={sel}: ERRO {e}")
            continue
        print(f"== selectionType={sel} mes={mes}: {time.monotonic() - t0:.1f}s")
        for k, v in resumir(regs).items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
