# -*- coding: utf-8 -*-
"""GDF V2 - papel de cada usuario: EDITOR (tudo) ou VISUALIZADOR (so' o Painel da Diretoria). Modulo novo e independente de painel_db
(assim um deploy nunca deixa o controle de acesso dependente de um modulo antigo ainda em memoria).
Regra: quem nao esta na tabela gdf.pnl_acesso (SQL-20) continua EDITOR; so' vira visualizador quem estiver cadastrado como VISUALIZADOR e ativo."""
from __future__ import annotations

import db

EDITOR, VISUALIZADOR = "EDITOR", "VISUALIZADOR"


def _norm(email) -> str:
    return (email or "").strip().lower()


def instalado(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_acesso'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def papel(conn, email) -> str:
    """VISUALIZADOR se o e-mail estiver cadastrado como visualizador ativo; EDITOR para os demais (inclusive enquanto a tabela do SQL-20 nao existe).
    Erro de banco NAO e' engolido: quem chama (app.py) bloqueia o acesso em vez de liberar o menu completo por engano."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('gdf.pnl_acesso') IS NOT NULL")
            if not cur.fetchone()[0]:
                return EDITOR
            cur.execute("SELECT papel FROM pnl_acesso WHERE email=%s AND ativo", (_norm(email),))
            r = cur.fetchone()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return r[0] if r and r[0] in (EDITOR, VISUALIZADOR) else EDITOR


def listar(conn) -> list[dict]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT email, papel, ativo, criado_por, criado_em, alterado_por, alterado_em FROM pnl_acesso ORDER BY papel, email")
            return [{"email": a, "papel": b, "ativo": c, "criado_por": d, "criado_em": e, "alterado_por": f, "alterado_em": g} for a, b, c, d, e, f, g in cur.fetchall()]
    except Exception:
        return []


def definir(conn, email: str, papel_: str, ativo: bool, quem: str | None) -> dict:
    """Cadastra ou atualiza o papel de um e-mail (nunca apaga). Devolve {'email','papel','ativo','novo'}."""
    e = _norm(email)
    if "@" not in e or " " in e:
        raise ValueError("Informe um e-mail válido.")
    if papel_ not in (EDITOR, VISUALIZADOR):
        raise ValueError("Papel inválido.")
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pnl_acesso WHERE email=%s", (e,))
            existe = cur.fetchone() is not None
            if existe:
                cur.execute("UPDATE pnl_acesso SET papel=%s, ativo=%s, alterado_por=%s, alterado_em=now() WHERE email=%s", (papel_, bool(ativo), quem, e))
            else:
                cur.execute("INSERT INTO pnl_acesso (email, papel, ativo, criado_por, alterado_por) VALUES (%s,%s,%s,%s,%s)", (e, papel_, bool(ativo), quem, quem))
    return {"email": e, "papel": papel_, "ativo": bool(ativo), "novo": not existe}


# ---------------------------------------------------------------- configuracao: aba Investimentos para visualizadores (SQL-29)
CHAVE_INVEST = "investimentos_visualizador"


def config_instalada(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('gdf.pnl_config') IS NOT NULL")
            return bool(cur.fetchone()[0])
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def investimentos_para_visualizador(conn) -> bool:
    """True se o EDITOR liberou a aba Investimentos para o login de visualizacao. Padrao: False (tambem enquanto o SQL-29 nao existe)."""
    if not config_instalada(conn):
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT valor FROM pnl_config WHERE chave=%s", (CHAVE_INVEST,))
            r = cur.fetchone()
        return bool(r and (r[0] or "").strip().lower() == "sim")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def definir_investimentos_para_visualizador(conn, liberar: bool, quem: str | None) -> bool:
    """Grava a escolha do editor (nunca apaga: so' troca 'sim'/'nao'). Devolve o valor gravado."""
    if not config_instalada(conn):
        raise RuntimeError("Falta executar o SQL-29 (sql/v2_config.sql) no Supabase.")
    v = "sim" if liberar else "nao"
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO pnl_config (chave, valor, alterado_por) VALUES (%s,%s,%s) "
                        "ON CONFLICT (chave) DO UPDATE SET valor=EXCLUDED.valor, alterado_por=EXCLUDED.alterado_por, alterado_em=now()", (CHAVE_INVEST, v, quem))
    return bool(liberar)
