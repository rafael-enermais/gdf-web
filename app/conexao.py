# -*- coding: utf-8 -*-
"""GDF - conexao com o Supabase (schema `gdf`) e utilitarios comuns das telas."""
from __future__ import annotations

import psycopg2
import streamlit as st

APP_VERSION = "0.1.0"        # 0.MAJOR.MINOR ate' o lancamento oficial (mesma regra do EGC)
NOME_APP = "GDF — Gestão de Demonstrativo Financeiro"

EMPRESA_INICIAL = ("ANASTACIO", "Anastácio Transmissora de Energia S.A.", "54.800.488/0001-60")


class ConexaoInvalida(Exception):
    """A DATABASE_URL conecta com o usuario errado (mensagem em linguagem simples)."""


def preparar_conexao(conn) -> str:
    """Fixa o schema `gdf` na SESSAO (o pooler do Supabase nao repassa o `ALTER ROLE ... SET search_path`) e confere
    que o usuario conectado e' a role do app (gdf_app) - nunca postgres/service_role. Devolve o usuario."""
    with conn.cursor() as cur:
        cur.execute("SET search_path TO gdf")
        cur.execute("SELECT current_user")
        usuario = cur.fetchone()[0]
    if usuario != "gdf_app":
        raise ConexaoInvalida(
            f"A DATABASE_URL está conectando como `{usuario}`, mas o app só pode usar a role `gdf_app`. "
            "Ajuste o secret `DATABASE_URL` (usuário `gdf_app.<ref-do-projeto>` no pooler).")
    return usuario


@st.cache_resource(show_spinner=False)
def get_conn():
    """Conexao cacheada pelo processo Streamlit. Precisa de st.secrets['DATABASE_URL'] (Supabase, role gdf_app —
    nunca postgres/service_role). Se faltar, mostra aviso simples e para a tela (nunca traceback bruto)."""
    try:
        database_url = st.secrets["DATABASE_URL"]
    except Exception:
        st.error("Secret `DATABASE_URL` não configurado ainda. Configure em `.streamlit/secrets.toml` (local) ou em "
                 "Settings → Secrets (Streamlit Cloud) com a connection string do Supabase, role `gdf_app`.")
        st.stop()
        return None
    try:
        conn = psycopg2.connect(database_url)
    except Exception as exc:
        st.error(f"Não consegui conectar ao banco: {exc}")
        st.stop()
        return None
    conn.autocommit = True
    try:
        preparar_conexao(conn)
    except ConexaoInvalida as exc:
        conn.close()
        st.error(str(exc))
        st.stop()
        return None
    return conn


def flash(nivel: str, texto: str) -> None:
    """Mensagem que sobrevive ao st.rerun(). nivel: ok | warn | erro | info."""
    st.session_state.setdefault("_flash_msgs", []).append((nivel, texto))


def mostrar_flash() -> None:
    for nivel, texto in st.session_state.pop("_flash_msgs", []):
        {"ok": st.success, "warn": st.warning, "erro": st.error}.get(nivel, st.info)(texto)


def sidebar_rodape() -> None:
    st.sidebar.markdown(
        f'<div style="margin-top:2rem;padding-top:0.6rem;border-top:1px solid rgba(245,246,250,0.15);'
        f'font-size:0.7rem;color:rgba(245,246,250,0.5);line-height:1.4;">{NOME_APP} · v{APP_VERSION}</div>', unsafe_allow_html=True)


def empresa_atual(conn):
    """Garante a empresa inicial (Anastacio) e o mapa padrao; devolve a lista de empresas ativas."""
    import db
    emp_id = db.garantir_empresa(conn, *EMPRESA_INICIAL)
    db.garantir_mapa(conn, emp_id)
    return db.listar_empresas(conn)
