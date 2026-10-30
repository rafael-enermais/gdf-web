# -*- coding: utf-8 -*-
"""GDF V2 - "visao do painel" para o RELATORIO PDF (v0.62.0). Guarda, na sessao de quem edita, o que esta marcado em cada aba do Painel da Diretoria
(obras, categorias, contas, credores, empresa, situacao, buscas...) e a base de data (Referencia x Caixa) escolhida em cada aba, para o gerador de PDF
sair IGUAL ao painel.

Como funciona (linguagem simples): cada aba, ao ser desenhada, chama `publicar("ob", obras=[...], cats=[...])`; a aba que nao esta aberta mantem o que ficou
da ultima vez que foi aberta. O gerador le tudo com `ler()` e mostra um resumo; `limpar()` esquece tudo. Nada vai ao banco: fica so' na sessao."""
from __future__ import annotations

import streamlit as st

_V = "_rel_visao"          # {aba: {filtro: valor}}  (aba = chave do catalogo do relatorio: res, ob, adm, desp, pes, pj, clt)
_B = "_rel_bases"          # {nome da aba do painel: 'REF'|'CAIXA'}


def _vazio(v) -> bool:
    return v is None or v == "" or (isinstance(v, (list, tuple, set, dict)) and not len(v))


def publicar(aba: str, **filtros) -> None:
    """Guarda os filtros desta aba (so' os preenchidos). Sem argumentos = aba sem filtro nenhum."""
    S = st.session_state
    vis = dict(S.get(_V) or {})
    vis[aba] = {k: (list(v) if isinstance(v, (list, tuple, set)) else v) for k, v in filtros.items() if not _vazio(v)}
    S[_V] = vis


def publicar_base(aba: str, base: str) -> None:
    S = st.session_state
    bs = dict(S.get(_B) or {})
    bs[aba] = base
    S[_B] = bs


def ler() -> tuple[dict, dict]:
    """(visao por aba, bases por aba) como estao agora."""
    S = st.session_state
    vis = {a: dict(f) for a, f in (S.get(_V) or {}).items() if f}
    return vis, dict(S.get(_B) or {})


def limpar() -> None:
    S = st.session_state
    S[_V] = {}
    S[_B] = {}
