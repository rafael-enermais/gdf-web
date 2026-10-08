# -*- coding: utf-8 -*-
"""
GDF - controle de acesso via Supabase Auth (e-mail/senha), mesmo mecanismo do EGC/RADAR.

O app so' valida a credencial; leitura/gravacao de dados continua via DATABASE_URL (role gdf_app).
Secrets necessarios (.streamlit/secrets.toml local ou Settings -> Secrets no Streamlit Cloud):
SUPABASE_URL e SUPABASE_ANON_KEY (chave "anon"/"public", NUNCA a "service_role") e DATABASE_URL.

Atencao: o pool de usuarios do Supabase e' do PROJETO (RADAR, EGC e GDF compartilham). Quem tiver usuario la'
tambem consegue logar aqui. Para tirar o acesso da contadora: excluir/bloquear o usuario dela em
Authentication > Users (nunca os dos outros apps). Restricao por lista fica para depois (decisao do responsavel, 07/10/2026).
"""
from __future__ import annotations

import streamlit as st
from supabase import create_client

TITULO = "GDF — Gestão de Demonstrativo Financeiro"


def _config(chave: str) -> str:
    try:
        if chave in st.secrets:
            return st.secrets[chave]
    except Exception:
        pass
    raise KeyError(chave)


@st.cache_resource(show_spinner=False)
def _auth_client():
    try:
        url = _config("SUPABASE_URL")
        anon_key = _config("SUPABASE_ANON_KEY")
    except KeyError as exc:
        st.error(f"Secret `{exc.args[0]}` não configurado ainda. Configure em `.streamlit/secrets.toml` (local) ou em "
                 "Settings → Secrets (Streamlit Cloud) — use a chave `anon`/`public`, NUNCA a `service_role`.")
        st.stop()
        return None
    return create_client(url, anon_key)


def require_login() -> str:
    """Bloqueia a tela ate haver login valido (st.stop() se nao autenticado). Retorna o e-mail do usuario."""
    if "auth_session" not in st.session_state:
        st.session_state["auth_session"] = None
    if st.session_state["auth_session"] is None:
        client = _auth_client()
        st.title(TITULO)
        st.subheader("Login")
        with st.form("login_gdf", clear_on_submit=False):      # ENTER envia o login
            email = st.text_input("E-mail")
            senha = st.text_input("Senha", type="password")
            enviou = st.form_submit_button("Entrar", type="primary")
        if enviou:
            if not email.strip() or not senha:
                st.error("Informe o e-mail e a senha.")
            else:
                try:
                    resp = client.auth.sign_in_with_password({"email": email.strip(), "password": senha})
                    st.session_state["auth_session"] = resp.session
                    st.rerun()
                except Exception as exc:
                    st.error(f"Login inválido: {exc}")
        st.stop()
        return ""
    sessao = st.session_state["auth_session"]
    st.sidebar.caption(f"Logado como **{sessao.user.email}**")
    if st.sidebar.button("Sair"):
        st.session_state["auth_session"] = None
        st.rerun()
    return sessao.user.email


def usuario_atual() -> str:
    """E-mail do usuario ja autenticado, sem desenhar nada na sidebar (usar nas telas, depois do require_login do app.py)."""
    sessao = st.session_state.get("auth_session")
    if sessao is None:
        return require_login()
    return sessao.user.email
