# -*- coding: utf-8 -*-
"""
GDF - SONDAGEM de CONTRATOS no Sienge (somente leitura; NAO grava nada no banco).
Tenta alguns caminhos de contratos (suprimentos/obra e vendas) e imprime, para cada um, SO': codigo HTTP, quantidade de itens e os NOMES dos campos
do primeiro registro. O log do Actions e' PUBLICO: este script nunca imprime valores, nomes de pessoas/empresas nem numeros de contrato.
Variaveis: SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL (opcional).
"""
from __future__ import annotations

import re
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
    anexos(cli)
    return 0


def anexos(cli) -> None:
    """Fase 2 (anexos): mostra o NOME dos links (rel) que a API devolve no contrato e na medicao e testa caminhos candidatos de anexos/itens
    com o primeiro contrato. Imprime so' codigos HTTP, nomes de links/campos e contagens (nunca ids, valores ou nomes)."""
    print("--- fase 2: anexos e itens ---")
    try:
        c = (S.lista(cli.get("v1/supply-contracts/all", {"limit": 1, "offset": 0})) or [None])[0]
        m = (S.lista(cli.get("v1/supply-contracts/measurements/all", {"limit": 1, "offset": 0})) or [None])[0]
    except S.ErroSienge as e:
        print(f"falha ao ler o primeiro contrato: {str(e)[:80]}")
        return
    for nome, reg in (("contrato", c), ("medicao", m)):
        if not isinstance(reg, dict):
            continue
        rels = [l.get("rel") for l in (reg.get("links") or []) if isinstance(l, dict)]
        print(f"{nome}: rels dos links = {rels}")
        suspeitos = [k for k in reg if any(t in k.lower() for t in ("attach", "anex", "file", "arquiv", "document", "url"))]
        print(f"{nome}: campos com cara de anexo/arquivo = {suspeitos}")
    if not isinstance(c, dict):
        return
    doc, num = c.get("documentId"), c.get("contractNumber")
    bld = ((c.get("buildings") or [{}])[0]).get("buildingId")
    cand = [
        ("v1/supply-contracts/attachments", {"documentId": doc, "contractNumber": num, "buildingId": bld}),
        ("v1/supply-contracts/attachments", {"documentId": doc, "contractNumber": num}),
        (f"v1/supply-contracts/{doc}/{num}/attachments", {}),
        (f"v1/supply-contracts/{doc}/{num}/{bld}/attachments", {}),
        (f"v1/supply-contracts/{doc}/{num}", {}),
        ("v1/supply-contracts/all/attachments", {"documentId": doc, "contractNumber": num}),
        ("v1/supply-contracts/items", {"documentId": doc, "contractNumber": num, "buildingId": bld}),
        ("v1/supply-contracts/items", {"documentId": doc, "contractNumber": num}),
        ("v1/supply-contracts/items/all", {"documentId": doc, "contractNumber": num}),
        ("v1/supply-contracts/measurements/attachments", {"documentId": doc, "contractNumber": num}),
        ("v1/supply-contracts/measurements/all", {"documentId": doc, "contractNumber": num, "limit": 5}),
        ("v1/attachments", {"documentId": doc, "contractNumber": num}),
        ("v1/supply-contracts/attachments", {}),
        ("v1/supply-contracts/attachments", {"documentId": doc, "contractNumber": num, "buildingId": bld, "limit": 5, "offset": 0}),
        ("v1/supply-contracts/attachments", {"documentId": doc, "contractNumber": num, "buildingId": bld, "measurementNumber": 1}),
        ("v1/supply-contracts/attachments", {"documentId": doc, "contractNumber": num, "buildingId": bld, "supplierId": c.get("supplierId")}),
        ("v1/supply-contracts/items", {}),
    ]
    for caminho, params in cand:
        rot = caminho.replace(str(doc), "{doc}").replace(str(num), "{num}").replace(str(bld), "{bld}")
        pars = sorted(k for k, v in params.items() if v is not None)
        try:
            resp = cli.get(caminho, {k: v for k, v in params.items() if v is not None})
        except S.ErroSienge as e:
            cod = str(e).split("HTTP ")[1][:3] if "HTTP " in str(e) else "rede"
            msg = str(e).split(caminho + ". ", 1)[1] if (caminho + ". ") in str(e) else ""
            msg = re.sub(r"[0-9]", "#", msg)[:160]                 # sem numeros: o log e' publico
            print(f"{rot} {pars}: HTTP {cod} {msg}")
            continue
        itens = S.lista(resp)
        campos = nomes_de_campos(itens[0])[:40] if itens else (sorted(resp.keys())[:15] if isinstance(resp, dict) else [])
        print(f"{rot} {pars}: HTTP 200, {len(itens)} itens | campos: {', '.join(campos)}")


if __name__ == "__main__":
    sys.exit(main())
