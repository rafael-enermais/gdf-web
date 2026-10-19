# -*- coding: utf-8 -*-
"""Acesso por papel (EDITOR / VISUALIZADOR) e Painel da Diretoria (so' leitura), contra Postgres descartavel."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import acesso
import painel_db as P
from dados_sienge import income
from test_painel_db_pg import _ingerir, _pdf_lido

pytestmark = pytest.mark.pg
APP = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _limpa_regra_criada_pela_tela(conn):
    """As telas criam a regra EXCLUI_PREVISAO sozinhas (proposta); a tabela de regras nao e' zerada entre testes, entao tira-se aqui para nao afetar os outros arquivos."""
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pnl_regra WHERE tipo='EXCLUI_PREVISAO'")


def test_papel_padrao_e_editor_e_visualizador_so_quando_ativo(conn):
    assert acesso.instalado(conn)
    assert acesso.papel(conn, "qualquer@x.com") == acesso.EDITOR                       # fora da lista: tudo, como hoje
    r = acesso.definir(conn, "  Diretor@Empresa.com ", acesso.VISUALIZADOR, True, "rafael@x")
    assert r == {"email": "diretor@empresa.com", "papel": "VISUALIZADOR", "ativo": True, "novo": True}
    assert acesso.papel(conn, "DIRETOR@empresa.com") == acesso.VISUALIZADOR            # sem diferenca de maiuscula
    assert acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, False, "rafael@x")["novo"] is False
    assert acesso.papel(conn, "diretor@empresa.com") == acesso.EDITOR                  # inativo volta ao padrao (acesso so' sai excluindo o usuario no Authentication)
    assert [a["email"] for a in acesso.listar(conn)] == ["diretor@empresa.com"]
    with pytest.raises(ValueError):
        acesso.definir(conn, "sem-arroba", acesso.VISUALIZADOR, True, None)
    with pytest.raises(ValueError):
        acesso.definir(conn, "a@b.com", "ADMIN", True, None)


def _app_como(conn, email):
    import streamlit as st
    st.cache_data.clear()                                   # o painel guarda os dados por 2 minutos; cada teste parte do zero
    at = AppTest.from_file(str(APP / "app.py"), default_timeout=60)
    at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email=email))
    return at


def test_visualizador_so_ve_o_painel_da_diretoria(conn):
    _ingerir(conn)
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _app_como(conn, "diretor@empresa.com").run()
        assert not at.exception, at.exception
        assert any("Painel da Diretoria" in t.value for t in at.title)
        corpo = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.sidebar.caption)
        assert "Importar balancete" not in corpo and "Situação do ano" not in " ".join(s.value for s in at.subheader)
        # o editor continua com o app completo
        at2 = _app_como(conn, "contabilidade@empresa.com").run()
        assert not at2.exception, at2.exception
        assert any("Situação do ano" in s.value for s in at2.subheader)


def test_painel_da_diretoria_com_dados_e_abas(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _app_como(conn, "diretor@empresa.com").run()
        assert not at.exception, at.exception
        assert [t.label for t in at.tabs] == ["Obras", "Administração", "Despesas", "Pessoas", "Resultado (DRE)"]
        assert any("Receita" == m.label for m in at.metric)
        at.text_input(key="dir_ob_busca").input("zzz-inexistente").run()                 # busca sem resultado nao quebra
        assert not at.exception, at.exception


def test_cadastro_de_visualizador_na_aba_regras(conn):
    _ingerir(conn)
    with patch("conexao.get_conn", return_value=conn):
        at = AppTest.from_file(str(APP / "telas" / "8_Painel_EnerMais.py"), default_timeout=30)
        at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="rafael@x"))
        at.run()
        assert not at.exception, at.exception
        at.text_input(key="pn2_ac_email").input("novo.diretor@empresa.com").run()
        at.button(key="pn2_ac_btn").click().run()
        assert not at.exception, at.exception
    assert acesso.papel(conn, "novo.diretor@empresa.com") == acesso.VISUALIZADOR


def test_banco_fora_do_ar_nao_libera_o_menu():
    at = _app_como(None, "diretor@empresa.com")
    with patch("acesso.papel", side_effect=RuntimeError("banco fora")), patch("conexao.get_conn", return_value=None):
        at.run()
    assert not at.exception, at.exception
    assert any("verificar o seu acesso" in e.value for e in at.error)
    assert not any("Situação do ano" in s.value for s in at.subheader)
