# -*- coding: utf-8 -*-
"""GDF - conexao com o Supabase (schema `gdf`) e utilitarios comuns das telas."""
from __future__ import annotations

import threading

import psycopg2
import psycopg2.extensions
import streamlit as st

APP_VERSION = "0.4.4"        # 0.MAJOR.MINOR ate' o lancamento oficial (mesma regra do EGC)
NOME_APP = "GDF — Gestão de Demonstrativo Financeiro"
CONTATO = "rafael.nakahara@enermais.com.br"       # mesmo contato do rodape do EGC/RADAR

EMPRESA_INICIAL = ("ANASTACIO", "Anastácio Transmissora de Energia S.A.", "54.800.488/0001-60")


class _CursorComTrava(psycopg2.extensions.cursor):
    """Cursor que so' executa com a trava da conexao. O Streamlit atende varias pessoas ao mesmo tempo (uma thread por sessao) usando
    a MESMA conexao; sem a trava, o comando de outra pessoa podia cair no meio da transacao de uma importacao."""

    def execute(self, query, vars=None):
        with self.connection.trava:
            return super().execute(query, vars)

    def executemany(self, query, vars_list):
        with self.connection.trava:
            return super().executemany(query, vars_list)


class ConexaoGDF(psycopg2.extensions.connection):
    """Conexao psycopg2 com uma trava reentrante (`trava`). `db.transacao` segura a trava do BEGIN ate' o COMMIT/ROLLBACK."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trava = threading.RLock()
        self.cursor_factory = _CursorComTrava


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


def conexao_viva(conn) -> bool:
    """True se a conexao ainda responde (o pooler do Supabase derruba conexoes ociosas; a conexao fica guardada entre as telas)."""
    if conn is None or getattr(conn, "closed", 1):
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _abrir_conn():
    """Abre a conexao (cacheada pelo processo Streamlit). Precisa de st.secrets['DATABASE_URL'] (Supabase, role gdf_app —
    nunca postgres/service_role). Se faltar, mostra aviso simples e para a tela (nunca traceback bruto)."""
    try:
        database_url = st.secrets["DATABASE_URL"]
    except Exception:
        st.error("Secret `DATABASE_URL` não configurado ainda. Configure em `.streamlit/secrets.toml` (local) ou em "
                 "Settings → Secrets (Streamlit Cloud) com a connection string do Supabase, role `gdf_app`.")
        st.stop()
        return None
    try:
        conn = psycopg2.connect(database_url, connection_factory=ConexaoGDF)
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


def get_conn():
    """Conexao do app. Se a guardada caiu (ociosidade, reinicio do banco), descarta e abre outra sozinha — o usuario nao precisa 'rebootar' o app."""
    conn = _abrir_conn()
    if not conexao_viva(conn):
        _abrir_conn.clear()
        conn = _abrir_conn()
    return conn


def flash(nivel: str, texto: str) -> None:
    """Mensagem que sobrevive ao st.rerun(). nivel: ok | warn | erro | info."""
    st.session_state.setdefault("_flash_msgs", []).append((nivel, texto))


def mostrar_flash() -> None:
    for nivel, texto in st.session_state.pop("_flash_msgs", []):
        {"ok": st.success, "warn": st.warning, "erro": st.error}.get(nivel, st.info)(texto)


def sidebar_rodape() -> None:
    """Rodape fixo no fundo da coluna cinza (sidebar): nome do app + versao + contato. Mesmo padrao do EGC: a sidebar tem uma cadeia de
    containers que precisam virar flex column para o 'margin-top: auto' empurrar o ultimo elemento (este) para baixo; 'sticky' segura o
    rodape no fundo quando o menu e' mais alto que a tela. Esta funcao tem que ser a ULTIMA coisa desenhada na sidebar de cada pagina."""
    import html
    linha_contato = f"<br>{html.escape(CONTATO)}"
    st.sidebar.markdown(
        f"""
        <style>
        [data-testid="stSidebarContent"] {{ display: flex; flex-direction: column; }}
        [data-testid="stSidebarUserContent"] {{ display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }}
        [data-testid="stSidebarUserContent"] > div {{ display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }}
        [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{ flex: 1 1 auto; min-height: 0; }}
        [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:last-child {{
            margin-top: auto; position: sticky; bottom: 0; background: rgb(38, 39, 48); z-index: 999; padding-bottom: 0.8rem;
        }}
        </style>
        <div style="margin-top:2rem;padding-top:0.6rem;border-top:1px solid rgba(245,246,250,0.15);
                    font-size:0.7rem;color:rgba(245,246,250,0.5);line-height:1.4;">
            {NOME_APP} · v{APP_VERSION}{linha_contato}
        </div>
        """,
        unsafe_allow_html=True,
    )


def empresa_atual(conn):
    """Garante a empresa inicial (Anastacio) e o mapa padrao; devolve a lista de empresas ativas."""
    import db
    emp_id = db.garantir_empresa(conn, *EMPRESA_INICIAL)
    db.garantir_mapa(conn, emp_id)
    return db.listar_empresas(conn)
