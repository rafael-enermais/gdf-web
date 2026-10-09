# -*- coding: utf-8 -*-
"""
GDF - Composicao de Saldos (caixa, divida, adiantamentos, fornecedores, capital por acionista) a partir das contas do
balancete do mes de referencia. Modulo puro (sem banco/streamlit). Mostra so' saldo diferente de zero; nomes passam pelos
APELIDOS que a contadora cadastra (o sistema reaproveita todo mes).
"""
from __future__ import annotations

import re

TOL = 0.005

# modo: 'conta' (cada conta analitica), 'prefixo' (soma por prefixo, com rotulo fixo), 'acionista' (capital + "Afac - ..." pelo nome)
GRUPOS_PADRAO = [
    {"chave": "caixa", "titulo": "Caixa e equivalentes de caixa", "prefixos": ["1.1.01.002", "1.1.01.003"], "modo": "conta", "max": 8, "demais": "Demais contas",
     "sufixos": {"1.1.01.003": " (aplicação)"}},
    {"chave": "divida", "titulo": "Empréstimos e financiamentos (BNDES)", "prefixos": ["2.1.01.001", "2.2.01.001"], "modo": "prefixo",
     "rotulos": {"2.1.01.001": "Curto prazo", "2.2.01.001": "Longo prazo"}},
    {"chave": "adiant", "titulo": "Adiantamentos a fornecedores", "prefixos": ["1.1.04.013"], "modo": "conta", "max": 8, "demais": "Demais fornecedores"},
    {"chave": "fornec", "titulo": "Fornecedores — 10 maiores saldos", "prefixos": ["2.1.03.001"], "modo": "conta", "max": 11, "demais": "Demais fornecedores"},
    {"chave": "capital", "titulo": "Capital aportado por acionista (capital social + AFAC)", "prefixos": ["2.4.01.001"], "modo": "acionista", "max": 8, "demais": "Demais acionistas"},
]
_AFAC = re.compile(r"^\s*afac\s*[-–—:]\s*", re.I)


def limpar_nome(nome: str) -> str:
    return " ".join((nome or "").split())


def _casa(cl, prefixos):
    return next((p for p in prefixos if cl == p or cl.startswith(p + ".")), None)


def chave_apelido(nome: str) -> str:
    return limpar_nome(nome).lower()


def _nome_exibido(nome, apelidos):
    n = limpar_nome(nome)
    return (apelidos or {}).get(chave_apelido(n), n)


def nomes_do_grupo(contas, grupo):
    """[(nome_original_limpo, saldo)] das contas analiticas do grupo com saldo != 0 (para o cadastro de apelidos)."""
    out = {}
    for c in contas:
        if c["sint"] or abs(c["sal"]) < TOL or not _casa(c["cl"], grupo["prefixos"]):
            continue
        n = limpar_nome(c["nome"]) + grupo.get("sufixos", {}).get(_casa(c["cl"], grupo["prefixos"]), "")
        if grupo["modo"] == "acionista":
            n = _AFAC.sub("", n)
        if grupo["modo"] == "prefixo":
            continue
        out[n] = round(out.get(n, 0.0) + c["sal"], 2)
    return sorted(out.items(), key=lambda kv: -abs(kv[1]))


def calcular(contas, grupos=None, apelidos=None):
    """Lista de grupos: {chave, titulo, itens:[(nome, valor)], total, n_itens, demais}. total = soma de TODOS os saldos != 0."""
    res = []
    for g in grupos or GRUPOS_PADRAO:
        if g["modo"] == "prefixo":
            soma = {}
            for c in contas:
                if c["sint"]:
                    continue
                p = _casa(c["cl"], g["prefixos"])
                if p:
                    soma[p] = round(soma.get(p, 0.0) + c["sal"], 2)
            itens = [(g.get("rotulos", {}).get(p, p), v) for p, v in soma.items() if abs(v) >= TOL]
        else:
            itens = [(_nome_exibido(n, apelidos), v) for n, v in nomes_do_grupo(contas, g)]
            agreg = {}
            for n, v in itens:                         # apelidos iguais somam (ex.: duas contas do mesmo fornecedor)
                agreg[n] = round(agreg.get(n, 0.0) + v, 2)
            itens = sorted(agreg.items(), key=lambda kv: -abs(kv[1]))
        total = round(sum(v for _, v in itens), 2)
        n_itens = len(itens)
        demais = False
        mx = g.get("max")
        if mx and n_itens > mx:
            resto = itens[mx - 1:]
            itens = itens[:mx - 1] + [(f"{g.get('demais', 'Demais')} ({len(resto)})", round(sum(v for _, v in resto), 2))]
            demais = True
        res.append({"chave": g["chave"], "titulo": g["titulo"], "itens": itens, "total": total, "n_itens": n_itens, "demais": demais})
    return res
