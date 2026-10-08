# -*- coding: utf-8 -*-
"""Ponto de entrada: sem login nao aparece menu nem dados; com login abre o Inicio. (sem banco)"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"


def test_sem_secrets_mostra_aviso_e_nao_abre_nada():
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert any("SUPABASE_URL" in e.value for e in at.error)
    assert not at.sidebar.button


def test_login_form_e_credencial_invalida():
    cliente = MagicMock()
    cliente.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials")
    with patch("auth._auth_client", return_value=cliente):
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        assert not at.exception
        assert at.title[0].value.startswith("GDF") and len(at.text_input) == 2
        at.text_input[0].set_value("a@b.com")
        at.text_input[1].set_value("errada")
        at.button[0].click().run()
        assert any("Login inválido" in e.value for e in at.error)
        cliente.auth.sign_in_with_password.assert_called_once()
        at.text_input[0].set_value("")
        at.text_input[1].set_value("")
        at.button[0].click().run()
        assert any("Informe o e-mail" in e.value for e in at.error)


def test_login_ok_abre_inicio():
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="usuaria@teste"))
    at.run()
    assert not at.exception, at.exception
    assert any("Gestão de Demonstrativo Financeiro" in t.value for t in at.title)
    assert any("Logado como" in c.value and "usuaria@teste" in c.value for c in at.sidebar.caption)
