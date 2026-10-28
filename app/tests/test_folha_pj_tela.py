# -*- coding: utf-8 -*-
"""Aba "Folha PJ" do Painel da Diretoria: abre sem erro, mostra os cards e reage a busca e 'Limpar filtros'. Dados sinteticos."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import acesso
import importador_folha_pj as IP
from test_acesso_diretoria_pg import APP, _app_como
from test_folha_pj_pg import MES, _regs
from test_painel_db_pg import _ingerir

pytestmark = pytest.mark.pg


def _rodar(conn, email="diretor@empresa.com"):
    acesso.definir(conn, email, acesso.VISUALIZADOR, True, "rafael@x")
    at = _app_como(conn, email)
    at.session_state["dir_todas_abas"] = True
    return at


def test_aba_folha_pj_abre_com_cards_e_tabelas(conn):
    _ingerir(conn, regs=_regs(), lado="P", tipo="P", mes=MES)
    IP.diretoria_adicionar(conn, 503, "Diretor Um", "teste@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _rodar(conn).run()
        assert not at.exception, at.exception
        assert "Folha PJ" in [t.label for t in at.tabs]
        rotulos = {m.label for m in at.metric}
        assert {"Total PJ", "Honorários", "Premiações", "Multa contratual", "Descontos"} <= rotulos
        assert any(m.label == "Total PJ" and m.value.startswith("R$") for m in at.metric)
        assert len(at.dataframe) >= 3                                               # resumo por obra, colaboradores e documentos
        at.text_input(key="fpj_busca_0").input("zzz-inexistente").run()
        assert not at.exception, at.exception
        assert any("Nenhum colaborador" in i.value for i in at.info)
        at.button(key="fpj_limpar_0").click().run()
        assert not at.exception and at.session_state["fpj_rst"] == 1
        at.text_input(key="fpj_busca_1").input("joao").run()
        assert not at.exception, at.exception


def test_aba_folha_pj_sem_flash_nem_mapa_mostra_so_o_sienge(conn):
    _ingerir(conn, lado="P", tipo="P")                                               # set/26: um unico salario PJ pago (500), sem Flash, mapa nem diretoria
    with patch("conexao.get_conn", return_value=conn):
        at = _rodar(conn).run()
        assert not at.exception, at.exception
        assert any(m.label == "Total PJ" for m in at.metric)
        assert any("Ainda não carregado" in c.value for c in at.caption)
