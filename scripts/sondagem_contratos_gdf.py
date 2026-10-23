# -*- coding: utf-8 -*-
"""
GDF - SONDAGEM de CONTRATOS no Sienge (somente leitura; NAO grava nada no banco).
Tenta alguns caminhos de contratos (suprimentos/obra e vendas) e imprime, para cada um, SO': codigo HTTP, quantidade de itens e os NOMES dos campos
do primeiro registro. O log do Actions e' PUBLICO: este script nunca imprime valores, nomes de pessoas/empresas nem numeros de contrato.
Variaveis: SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL (opcional).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import sienge_api as S  # noqa: E402

# (caminho, parametros). Os caminhos sao palpites baseados na documentacao publica do Sienge; 404 = nao existe, 403 = chave sem permissao.
CANDIDATOS = [
    ("v1/supply-contracts/all", {"limit": 5, "offset": 0}),
    ("v1/supply-contracts/all", {"startDate": "2026-01-01", "endDate": "2026-12-31", "limit": 5, "offset": 0}),
    ("v1/supply-contracts", {"limit": 5, "offset": 0}),
    ("v1/supply-contracts/measurements/all", {"limit": 5, "offset": 0}),
    ("v1/supply-contracts/items", {"limit": 5, "offset": 0}),
    ("v1/sales-contracts", {"limit": 5, "offset": 0}),
    ("v1/contracts", {"limit": 5, "offset": 0}),
    ("bulk-data/v1/supply-contracts", {"limit": 5}),
    ("bulk-data/v1/sales-contracts", {"limit": 5}),
]


def nomes_de_campos(reg, nivel: int = 0) -> list:
    """So' os nomes dos campos (e dos campos de sub-objetos, ate' 1 nivel). Nunca valores."""
    if not isinstance(reg, dict):
        return []
    out = []
    for k, v in reg.items():
        out.append(k)
        if nivel == 0 and isinstance(v, dict):
            out += [f"{k}.{x}" for x in nomes_de_campos(v, 1)]
        elif nivel == 0 and isinstance(v, list) and v and isinstance(v[0], dict):
            out += [f"{k}[].{x}" for x in nomes_de_campos(v[0], 1)]
    return out


def main() -> int:
    user, pwd, base = S.credenciais()
    cli = S.Cliente(user, pwd, base, timeout=90, pausa=1.0, esperas_429=(20, 60))
    for caminho, params in CANDIDATOS:
        t0 = time.monotonic()
        rot = f"{caminho} {sorted(params)}"
        try:
            resp = cli.get(caminho, params)
        except S.ErroSienge as e:
            cod = str(e).split("HTTP ")[1][:3] if "HTTP " in str(e) else "rede"
            print(f"{rot}: HTTP {cod} ({time.monotonic() - t0:.1f}s)")
            continue
        itens = S.lista(resp)
        extra = ""
        if isinstance(resp, dict):
            extra = " | chaves da resposta: " + ", ".join(sorted(resp.keys())[:10])
            meta = resp.get("resultSetMetadata")
            if isinstance(meta, dict):
                extra += f" | total declarado: {meta.get('count')}"
        print(f"{rot}: HTTP 200, {len(itens)} itens na pagina ({time.monotonic() - t0:.1f}s){extra}")
        if itens:
            print("   campos: " + ", ".join(nomes_de_campos(itens[0])[:80]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
