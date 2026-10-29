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


def _tela_upload(conn_, nomes_e_bytes):
    """Roda so' o envio de arquivos da Folha PJ com um st.file_uploader de mentira (AppTest nao envia arquivo)."""
    import streamlit as st
    import folha_pj_ui as UI

    class _Arq:
        def __init__(self, nome, b):
            self.name, self._b = nome, b

        def getvalue(self):
            return self._b
    original = st.file_uploader
    st.file_uploader = lambda *a, **k: [_Arq(n, b) for n, b in nomes_e_bytes]
    try:
        UI._arquivos_do_mes(conn_, True, "segredo-de-teste", "teste@x")
    finally:
        st.file_uploader = original                                                 # o AppTest roda no mesmo processo: devolve o original para os outros testes


def test_envio_do_flash_nao_escolhe_mes_sozinho_e_pede_confirmacao_para_substituir(conn):
    """Salvaguarda: o Flash nao traz o mes, entao nao ha' mes pre-escolhido; mes que ja' tem Flash exige confirmar a substituicao."""
    from test_folha_pj_pg import SEGREDO, _flash_xlsx, _mapa_xlsx, _meses_alvo, _meses_alvo_outro
    IP.gravar_colaboradores(conn, IP.ler_mapa_colaboradores(_mapa_xlsx(), SEGREDO)["linhas"], MES, "teste@x")
    alvo = _meses_alvo()
    IP.gravar_flash(conn, alvo, "ENERMAIS ENERGIA LTDA", [{"credor_id": 501, "premiacao": 10.0, "alimentacao": 20.0}], "teste@x")
    arq = [("FLASH ENERGIA.xlsx", _flash_xlsx([["Joao Teste", "529.982.247-25", 3000, 650, 0]]))]
    at = AppTest.from_function(_tela_upload, args=(conn, arq))
    at.run()
    assert not at.exception, at.exception
    sel = at.selectbox(key="fpj_mes_0")
    assert sel.value is None                                                        # nao abre no mes mais recente
    assert any("Escolha o mês dos arquivos" in w.value for w in at.warning)
    botao = at.button(key="fpj_confirma_0")
    assert botao.disabled
    sel.select(alvo).run()                                                          # mes que ja' tem Flash
    assert not at.exception, at.exception
    assert any("Já existe Flash" in w.value for w in at.warning)
    assert at.button(key="fpj_confirma_0").disabled                                 # falta a confirmacao
    at.checkbox(key="fpj_subst_0").check().run()
    assert not at.button(key="fpj_confirma_0").disabled
    outro = _meses_alvo_outro(alvo)                                                 # mes sem Flash: nada a substituir
    at.checkbox(key="fpj_subst_0").uncheck()
    at.selectbox(key="fpj_mes_0").select(outro).run()
    assert not any("Já existe Flash" in w.value for w in at.warning) and not at.button(key="fpj_confirma_0").disabled
