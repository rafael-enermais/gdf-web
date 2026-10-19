# -*- coding: utf-8 -*-
"""
GDF V2 - DIAGNOSTICO dos IMPOSTOS SOBRE O FATURAMENTO (DRE 02.02) na API de contas a receber (bulk-data/v1/income). SOMENTE LEITURA; NAO grava nada.
Objetivo: achar em que campo da API esta o valor de "Impostos sobre o Faturamento" que o DRE oficial do Sienge mostra (PIS/COFINS/ISS... por NF) e que a API
ainda nao traz (nem nas categorias do rateio, nem na soma de taxAmount das baixas).
O log do Actions e' PUBLICO: este script imprime SO nomes de campos, contagens, codigos do plano e PROPORCOES (soma do campo / soma do valor original, em %);
nunca valores em R$, nomes de clientes ou de empresas. Variaveis: SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL. Opcional GDF_IMPOSTOS_MES="2026-09".
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import sienge_api as S  # noqa: E402


def _num(v):
    try:
        return float(v) if v not in (None, "") and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _soma_campos(lista: list) -> dict:
    """{campo numerico: (soma, quantos nao-zero)} dos dicts da lista."""
    out: dict = {}
    for d in lista:
        for k, v in d.items():
            n = _num(v)
            if n is None:
                continue
            s, q = out.get(k, (0.0, 0))
            out[k] = (s + n, q + (1 if abs(n) > 0.004 else 0))
    return out


def resumir(regs: list) -> dict:
    """So nomes, contagens e proporcoes em % da soma do valor original. Funcao pura (testavel)."""
    regs = [r for r in regs if isinstance(r, dict)]
    base = sum(_num(r.get("originalAmount")) or 0.0 for r in regs)
    pct = lambda x: round(100.0 * x / base, 4) if base else None  # noqa: E731
    listas = sorted({k for r in regs for k, v in r.items() if isinstance(v, list)})
    nested: dict = {}
    for lk in listas:
        itens = [i for r in regs for i in (r.get(lk) or []) if isinstance(i, dict)]
        nested[lk] = {"itens": len(itens), "campos": sorted({k for i in itens for k in i.keys()}),
                      "numericos_pct_do_original": {k: (pct(s), q) for k, (s, q) in sorted(_soma_campos(itens).items()) if not k.lower().endswith("id") and "sequen" not in k.lower()}}
    topo = _soma_campos(regs)
    cats = Counter()
    for r in regs:
        for lk in ("receiptsCategories", "incomeCategories", "financialCategories"):
            for c in (r.get(lk) or []):
                if isinstance(c, dict):
                    for k, v in c.items():
                        if "categoryid" in k.lower().replace("_", "") and v not in (None, ""):
                            cats[S.cod_plano(v)] += 1
    # taxa de imposto do titulo (taxAmount / originalAmount, em %, 2 casas): so' contagem por taxa; e por tipo de documento (codigos genericos: NFS, FAT...)
    taxas = Counter()
    por_doc: dict = {}
    for r in regs:
        orig, tx = _num(r.get("originalAmount")) or 0.0, _num(r.get("taxAmount")) or 0.0
        if orig > 0 and tx > 0.004:
            taxas[round(100.0 * tx / orig, 2)] += 1
        d = por_doc.setdefault(str(r.get("documentIdentificationId") or "").strip() or "?", {"titulos": 0, "orig": 0.0, "tax": 0.0, "previsao_S": 0})
        d["titulos"] += 1
        d["orig"] += orig
        d["tax"] += tx
        d["previsao_S"] += 1 if str(r.get("documentForecast") or "").upper() == "S" else 0
    sem_prev = [r for r in regs if str(r.get("documentForecast") or "").upper() != "S"]
    base_sp = sum(_num(r.get("originalAmount")) or 0.0 for r in sem_prev)
    tax_sp = sum(_num(r.get("taxAmount")) or 0.0 for r in sem_prev)
    return {
        "titulos": len(regs),
        "titulos_sem_previsao": len(sem_prev),
        "taxAmount_do_titulo_pct_do_original_sem_previsao": round(100.0 * tax_sp / base_sp, 4) if base_sp else None,
        "taxas_do_titulo_contagem": dict(sorted(taxas.items(), key=lambda kv: -kv[1])[:20]),
        "por_documento": {k: {"titulos": v["titulos"], "previsao_S": v["previsao_S"], "pct_do_original": round(100.0 * v["orig"] / base, 2) if base else None,
                              "taxAmount_pct_do_original_do_documento": round(100.0 * v["tax"] / v["orig"], 4) if v["orig"] else None} for k, v in sorted(por_doc.items())},
        "campos_do_titulo": sorted({k for r in regs for k in r.keys()}),
        "campos_do_titulo_preenchidos": {k: sum(1 for r in regs if r.get(k) not in (None, "", [], {})) for k in sorted({k for r in regs for k in r.keys()})},
        "numericos_do_titulo_pct_do_original": {k: (pct(s), q) for k, (s, q) in sorted(topo.items()) if not k.lower().endswith("id")},
        "listas": nested,
        "contas_do_plano_nas_categorias": dict(sorted(cats.items())),
        "contas_1_01_02_ou_deducoes": {c: n for c, n in sorted(cats.items()) if c.startswith("1.01.02") or c.startswith("1.01.03")},
    }


def main() -> int:
    mes = (os.environ.get("GDF_IMPOSTOS_MES") or "2026-09").strip()[:7]
    user, pwd, base = S.credenciais(None, os.environ)
    cli = S.Cliente(user, pwd, base, pausa=6, esperas_429=(30, 60, 120, 240))
    t0 = time.monotonic()
    try:
        regs = S.buscar_bulk(cli, "R", mes, "I")
    except S.ErroSienge as e:
        print(f"ERRO {e}")
        return 1
    print(f"== contas a receber, emissao em {mes}: {time.monotonic() - t0:.1f}s")
    for k, v in resumir(regs).items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
