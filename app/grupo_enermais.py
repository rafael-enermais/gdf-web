# -*- coding: utf-8 -*-
"""GDF V2 - Grupo ENERMAIS: as 6 empresas do grupo (cadastro do Sienge, pnl_empresa_sienge ids 1 a 6) para tirar das listas de credores/clientes
as operacoes ENTRE empresas do grupo (nao sao fornecedor nem cliente de verdade). Sem streamlit: so' texto e SQL (testavel).

Como funciona, em linguagem simples:
- o nome da empresa e o nome do credor/cliente sao comparados pelo "nucleo": MAIUSCULAS, sem acento, sem 'LTDA/S.A.' e sem ' - CNPJ ...' no fim;
- a lista das 6 empresas vem do banco (cadastro do Sienge); se o cadastro estiver vazio, vale a lista padrao abaixo (combinada com o Rafael em 21/10/2026:
  Enermais Energia, Construtora, Solucoes, Renovaveis, Engenharia e SMG; as demais empresas do cadastro - Stellantis, Center etc. - NAO entram)."""
from __future__ import annotations

import re
import unicodedata

IDS_GRUPO = (1, 2, 3, 4, 5, 6)
NOMES_PADRAO = ("ENERMAIS ENERGIA LTDA", "ENERMAIS CONSTRUTORA LTDA", "ENERMAIS SOLUCOES LTDA", "ENERMAIS RENOVAVEIS LTDA", "ENERMAIS ENGENHARIA LTDA", "SMG SOLUCOES LTDA")

_ACENTOS = "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_SEM = "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN"
_RE_CNPJ = re.compile(r"\s*-\s*CNPJ.*$")
_RE_SUFIXO = re.compile(r"[\s,.]+(LTDA|S/A|SA|ME|EPP)[\s.]*$")


def nucleo(nome) -> str:
    """Nome para comparar: sem acento, MAIUSCULAS, espacos simples, sem ' - CNPJ ...' e sem LTDA/S.A. no fim. 'Enermais Energia Ltda - CNPJ 1' -> 'ENERMAIS ENERGIA'."""
    t = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"\s+", " ", t).strip()
    t = _RE_CNPJ.sub("", t)
    t = _RE_SUFIXO.sub("", t)
    return t.strip()


def sql_nucleo(coluna: str) -> str:
    """Mesma regra de `nucleo` em SQL (para filtrar direto no banco). Sem parametros (nao tem %)."""
    return (rf"btrim(regexp_replace(regexp_replace(upper(translate(COALESCE({coluna},''), '{_ACENTOS}', '{_SEM}')), "
            r"'\s*-\s*CNPJ.*$', ''), '[\s,.]+(LTDA|S/A|SA|ME|EPP)[\s.]*$', ''))")


def nucleos_do_grupo(conn=None) -> list:
    """Nucleos das empresas do grupo: do cadastro do Sienge (ids 1 a 6) quando existe; senao, a lista padrao."""
    nomes = []
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT nome FROM pnl_empresa_sienge WHERE id = ANY(%s)", (list(IDS_GRUPO),))
                nomes = [r[0] for r in cur.fetchall()]
        except Exception:                                           # noqa: BLE001
            try:
                conn.rollback()
            except Exception:                                       # noqa: BLE001
                pass
    return sorted({nucleo(n) for n in (nomes or NOMES_PADRAO) if nucleo(n)})


def eh_do_grupo(nome, nucleos) -> bool:
    n = nucleo(nome)
    return bool(n) and n in set(nucleos or [])
