# -*- coding: utf-8 -*-
"""GDF - ajudantes das tabelas com CAIXINHA e varias linhas (st.dataframe com selecao multipla), para as paginas novas.
(O Painel da Diretoria tem copias identicas desses tres ajudantes; sao pequenos e ficam la para nao mexer numa tela estavel.)"""
from __future__ import annotations

import zlib


def chave(base: str, *dep) -> str:
    """Chave de um st.dataframe com selecao que muda quando muda o que o alimenta (a selecao por posicao nao fica 'grudada' em outra linha)."""
    return f"{base}_{zlib.crc32(repr(dep).encode()) % 100000}"


def selecionadas(ev, df):
    """TODAS as linhas marcadas (caixinhas) de um st.dataframe com selecao multipla -> DataFrame (vazio se nenhuma)."""
    try:
        rows = [r for r in ev.selection.rows if r < len(df)]
    except Exception:                                   # noqa: BLE001
        rows = []
    return df.iloc[rows] if rows else df.iloc[0:0]


def rotulo(itens, vazio: str, ate: int = 2) -> str:
    """Rotulo curto do que esta marcado: 'A, B' ate' `ate` itens; acima disso 'N selecionados'; sem marcacao -> `vazio`."""
    itens = [str(i) for i in itens]
    if not itens:
        return vazio
    return ", ".join(itens) if len(itens) <= ate else f"{len(itens)} selecionados"
