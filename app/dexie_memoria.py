# -*- coding: utf-8 -*-
"""GDF - Dexie: MEMORIA enxuta da conversa (SQL-31, tabela gdf.dexie_mensagem).
Guarda so' o texto das mensagens (pergunta/resposta) por usuario; ao abrir a pagina a Dexie le a janela das ultimas JANELA mensagens nao arquivadas.
"Nova conversa" arquiva (nunca apaga). Se o SQL-31 ainda nao foi rodado, tudo aqui vira no-op e a conversa fica so' na sessao (a tela avisa). Nunca derruba a tela."""
from __future__ import annotations

JANELA = 24                 # mensagens relidas (mesma janela do Erik.AI)
MAX_CONTEUDO = 6000         # caracteres guardados por mensagem


def instalado(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('gdf.dexie_mensagem') IS NOT NULL")
            return bool(cur.fetchone()[0])
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return False


def _desfaz(conn):
    try:
        conn.rollback()
    except Exception:                                       # noqa: BLE001
        pass


def carregar(conn, usuario: str, limite: int = JANELA) -> list:
    """[{'role','content'}] em ordem cronologica (so' as nao arquivadas do usuario). Lista vazia se nao ha memoria ou se o SQL-31 nao existe."""
    if not usuario or not instalado(conn):
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT papel, conteudo FROM (SELECT id, papel, conteudo FROM dexie_mensagem WHERE usuario=%s AND NOT arquivado ORDER BY id DESC LIMIT %s) x ORDER BY id",
                        (usuario.strip().lower(), int(limite)))
            return [{"role": p, "content": c} for p, c in cur.fetchall()]
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return []


def gravar(conn, usuario: str, papel: str, conteudo: str) -> bool:
    if not usuario or papel not in ("user", "assistant") or not (conteudo or "").strip() or not instalado(conn):
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO dexie_mensagem (usuario, papel, conteudo) VALUES (%s,%s,%s)", (usuario.strip().lower(), papel, conteudo[:MAX_CONTEUDO]))
        return True
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return False


def arquivar(conn, usuario: str) -> int:
    """Encerra a conversa atual do usuario (marca arquivado; nada e' apagado). Devolve quantas mensagens foram arquivadas."""
    if not usuario or not instalado(conn):
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE dexie_mensagem SET arquivado=true WHERE usuario=%s AND NOT arquivado", (usuario.strip().lower(),))
            return cur.rowcount
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return 0
