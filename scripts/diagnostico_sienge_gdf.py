# -*- coding: utf-8 -*-
"""
GDF V2 - DIAGNOSTICO (somente leitura no Sienge; NAO grava nada no banco): mede volume/tempo por mes e procura chaves repetidas
nas respostas (causa do erro "ON CONFLICT DO UPDATE command cannot affect row a second time"). Testa tambem uma janela larga (ano todo).
O log do Actions e' PUBLICO: este script imprime SO contagens, tamanhos, tempos e codigos de origem (CP/ME/...); nunca valores nem nomes.
Variaveis: SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL (opcional). Opcional GDF_DIAG_INICIO="2026-01" e GDF_DIAG_FIM="2026-10".
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import sienge_api as S  # noqa: E402

CAMPOS = {"P": ("payments", "paymentsCategories"), "R": ("receipts", "receiptsCategories")}


def meses_entre(ini: str, fim: str) -> list:
    a, b = (int(ini[:4]), int(ini[5:7])), (int(fim[:4]), int(fim[5:7]))
    out = []
    while a <= b:
        out.append(f"{a[0]:04d}-{a[1]:02d}")
        a = (a[0] + (a[1] == 12), 1 if a[1] == 12 else a[1] + 1)
    return out


def analisar(regs: list, lado: str) -> dict:
    """Contagens de chaves repetidas (titulo, baixa) numa resposta. Funcao pura (testavel)."""
    pl, rl = CAMPOS[lado]
    regs = [r for r in regs if isinstance(r, dict) and r.get("billId") is not None]
    chave = lambda r: (r.get("billId"), r.get("installmentId") or 0)           # noqa: E731
    por = {}
    for r in regs:
        por.setdefault(chave(r), []).append(r)
    dup = {k: v for k, v in por.items() if len(v) > 1}
    ident = sum(1 for v in dup.values() if len({json.dumps(x, sort_keys=True, default=str) for x in v}) == 1)
    mesmas_baixas = sum(1 for v in dup.values() if len({json.dumps(x.get(pl) or [], sort_keys=True, default=str) for x in v}) == 1)
    baixas_total = sum(len(r.get(pl) or []) for r in regs)
    seqs, colisao_mesmo_registro = Counter(), 0
    for r in regs:
        vistos = Counter()
        for p in r.get(pl) or []:
            s = p.get("sequencialNumber")
            vistos[s] += 1
            seqs[(chave(r), s)] += 1
        colisao_mesmo_registro += sum(c - 1 for c in vistos.values() if c > 1)
    colisao_total = sum(c - 1 for c in seqs.values() if c > 1)
    return {"registros": len(regs), "chaves_unicas": len(por), "chaves_repetidas": len(dup),
            "repetidas_identicas": ident, "repetidas_com_mesmas_baixas": mesmas_baixas,
            "origem_das_repetidas": dict(Counter((v[0].get("originId") or "?").strip() for v in dup.values()).most_common(8)),
            "baixas": baixas_total, "baixas_chave_repetida_no_mesmo_registro": colisao_mesmo_registro,
            "baixas_chave_repetida_total": colisao_total, "rateios": sum(len(r.get(rl) or []) for r in regs)}


def chamar(cli, lado, ini: dt.date, fim: dt.date, tipo: str):
    params = {"startDate": ini.isoformat(), "endDate": fim.isoformat(), "selectionType": tipo, "correctionIndexerId": "0",
              "correctionDate": fim.isoformat(), "withBankMovements": "true"}
    t = time.time()
    regs = S.lista(cli.get(S.ENDPOINT[lado], params))
    return regs, round(time.time() - t, 1), round(len(json.dumps(regs, default=str)) / 1024)


def main(env=None, log=print) -> int:
    env = os.environ if env is None else env
    try:
        user, pwd, base = S.credenciais(None, env)
    except S.ErroSienge as exc:
        log(f"ERRO de configuração: {exc}")
        return 1
    cli = S.Cliente(user, pwd, base)
    hoje = dt.date.today()
    ini = (env.get("GDF_DIAG_INICIO") or f"{hoje.year}-01").strip()
    fim = (env.get("GDF_DIAG_FIM") or f"{hoje.year}-{hoje.month:02d}").strip()
    falhas = 0
    log("== por mês (lado, tipo de data): registros | chaves únicas | repetidas (idênticas / mesmas baixas) | baixas (chave repetida) | rateios | KB | s ==")
    tot = Counter()
    for mes in meses_entre(ini, fim):
        a, b = S.limites_do_mes(mes)
        for lado in ("P", "R"):
            for tipo in ("P", "I"):
                try:
                    regs, seg, kb = chamar(cli, lado, a, b, tipo)
                except S.ErroSienge as exc:
                    falhas += 1
                    log(f"{mes} {lado} {tipo}: ERRO {exc}")
                    continue
                r = analisar(regs, lado)
                tot[(lado, tipo, "reg")] += r["registros"]
                tot[(lado, tipo, "kb")] += kb
                log(f"{mes} {lado} {tipo}: {r['registros']} | {r['chaves_unicas']} | {r['chaves_repetidas']} ({r['repetidas_identicas']}/{r['repetidas_com_mesmas_baixas']}) "
                    f"| {r['baixas']} ({r['baixas_chave_repetida_no_mesmo_registro']}/{r['baixas_chave_repetida_total']}) | {r['rateios']} | {kb} | {seg}"
                    + (f" | origem das repetidas {r['origem_das_repetidas']}" if r["chaves_repetidas"] else ""))
    log("== soma dos meses ==")
    for (lado, tipo, k), v in sorted(tot.items()):
        log(f"{lado} {tipo} {k}: {v}")
    log(f"== janela larga {ini}..{fim} numa chamada só ==")
    a, _ = S.limites_do_mes(ini)
    _, b = S.limites_do_mes(fim)
    for lado in ("P", "R"):
        for tipo in ("P", "I"):
            try:
                regs, seg, kb = chamar(cli, lado, a, b, tipo)
                log(f"{lado} {tipo}: {len(regs)} registros | {kb} KB | {seg} s")
            except S.ErroSienge as exc:
                falhas += 1
                log(f"{lado} {tipo}: ERRO {exc}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
