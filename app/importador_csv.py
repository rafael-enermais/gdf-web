# -*- coding: utf-8 -*-
"""
GDF - Importador do balancete exportado em CSV do sistema contabil
("Relatorios_Contabeis_Balancete_(Texto)_Balancete_-_Debito_Credito.csv").

Formato (confirmado no arquivo 01/01 a 31/08/2026 enviado pela contadora em 08/10/2026):
  - codificacao cp1252, separador ';', numeros '1.234,56', negativo '(1.234,56)' ou '-1.234,56'
  - cabecalho: empresa, CNPJ e "Periodo: dd/mm/aaaa a dd/mm/aaaa"
  - linha de conta: Conta;S;"Classificacao  Nome";Saldo Ant.;(vazio);Debito;Credito;Saldo;
Sem banco, sem rede. Devolve o mesmo formato de contas do motor: [{id, sint, cl, nome, ant, deb, cred, sal}].
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import re
from datetime import date

_NUM = re.compile(r"^\(?-?[\d\.]*\d,\d{2}\)?$")


class ErroImportacao(Exception):
    """Arquivo fora do formato esperado (mensagem em linguagem simples, mostrada para a usuaria)."""


def _n(s):
    s = (s or "").strip()
    if not s:
        return 0.0
    if not _NUM.match(s):
        raise ErroImportacao(f"Número em formato inesperado: {s!r}")
    neg = s.startswith("(") or s.startswith("-")
    v = float(s.strip("()").replace("-", "").replace(".", "").replace(",", "."))
    return round(-v if neg else v, 2)


def _data(txt):
    d, m, a = (int(x) for x in txt.split("/"))
    return date(a, m, d)


def classificar_periodo(ini: date, fim: date):
    """('MENSAL', 'AAAA-MM') | ('ACUMULADO', 'AAAA-MM' do ultimo mes). Outros periodos nao sao aceitos."""
    ult = calendar.monthrange(fim.year, fim.month)[1]
    if fim.day != ult:
        raise ErroImportacao(f"O período termina em {fim:%d/%m/%Y}, que não é o último dia do mês.")
    if ini.year == fim.year and ini.month == fim.month and ini.day == 1:
        return "MENSAL", f"{fim.year}-{fim.month:02d}"
    if ini.year == fim.year and ini.month == 1 and ini.day == 1:
        return "ACUMULADO", f"{fim.year}-{fim.month:02d}"
    raise ErroImportacao(f"Período {ini:%d/%m/%Y} a {fim:%d/%m/%Y} não aceito: use um mês isolado ou janeiro até o mês.")


def ler_bytes(raw: bytes, nome_arquivo: str = "balancete.csv"):
    """Le o CSV (bytes). Retorna (cabecalho, contas). Levanta ErroImportacao se o arquivo nao for o esperado."""
    sha = hashlib.sha256(raw).hexdigest()
    try:
        txt = raw.decode("cp1252")
    except UnicodeDecodeError:
        raise ErroImportacao("Não consegui ler o arquivo (codificação). Exporte de novo o relatório em CSV (Texto).")
    cab = {"arquivo": nome_arquivo, "sha256": sha}
    m = re.search(r"CNPJ:\s*([\d\./-]+)", txt)
    cab["cnpj"] = m.group(1) if m else None
    m = re.search(r"Per\S*odo:\s*(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})", txt)
    if not m:
        raise ErroImportacao("Não achei a linha 'Período: dd/mm/aaaa a dd/mm/aaaa' no arquivo. Este é o CSV de balancete do sistema contábil?")
    cab["ini"], cab["fim"] = _data(m.group(1)), _data(m.group(2))
    cab["tipo"], cab["periodo"] = classificar_periodo(cab["ini"], cab["fim"])
    m = re.search(r'"?(\d+)\s+([^\r\n]+?)\r?\n', txt)
    cab["empresa"] = m.group(2).strip() if m else None
    if not cab["cnpj"]:
        raise ErroImportacao("Não achei o CNPJ da empresa no cabeçalho do arquivo.")
    contas, vistos, ignoradas = [], set(), []
    for lin in csv.reader(io.StringIO(txt), delimiter=";", quotechar='"'):
        if len(lin) < 8 or not lin[0].strip().isdigit():
            continue
        cid, s, cls = lin[0].strip(), lin[1].strip(), lin[2]
        mm = re.match(r"^\s*(\d(?:\.\d+)*)\s+(.*?)\s*$", cls)
        if not mm:
            ignoradas.append(cls)
            continue
        cl, nome = mm.group(1), mm.group(2)
        chave = (cid, cl)
        if chave in vistos:                      # linha repetida (quebra de pagina)
            continue
        vistos.add(chave)
        # colunas: Conta;S;Classificacao;Saldo Ant.;(vazio);Debito;Credito;Saldo
        contas.append({"id": cid, "sint": s == "S", "cl": cl, "nome": nome,
                       "ant": _n(lin[3]), "deb": _n(lin[5]), "cred": _n(lin[6]), "sal": _n(lin[7])})
    if not contas:
        raise ErroImportacao("Não encontrei nenhuma conta no arquivo. Confira se é o relatório 'Balancete – Débito/Crédito' em CSV (Texto).")
    cab["n_contas"] = len(contas)
    cab["ignoradas"] = ignoradas
    return cab, contas


def ler_csv(caminho: str):
    """Mesma coisa de ler_bytes, a partir de um caminho."""
    with open(caminho, "rb") as f:
        raw = f.read()
    return ler_bytes(raw, caminho.replace("\\", "/").split("/")[-1])
