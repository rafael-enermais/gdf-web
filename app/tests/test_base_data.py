# -*- coding: utf-8 -*-
"""Base de data das abas da Diretoria: REFERENCIA (emissao) x CAIXA (pagamento). Dados 100% sinteticos."""
import pytest

import acesso
import base_data as BD
import diretoria_dados as DD
import painel_db as P
import sienge_api as S
from dados_sienge import _c, _pg


# ------------------------------------------------------------------ sem banco
def test_valida_e_padroes_de_cada_aba():
    assert BD.valida("ref") == BD.REF and BD.valida("Caixa") == BD.CAIXA and BD.valida("competência") == BD.REF
    assert BD.valida("") is None and BD.valida(None) is None and BD.valida("x") is None
    # o padrao e' o que cada aba ja usava antes do seletor
    assert [BD.padrao(a) for a in ("Resultado", "Obras", "Administração", "Despesas", "Pessoas", "Folha PJ", "Folha CLT")] == \
           [BD.REF, BD.REF, BD.CAIXA, BD.CAIXA, BD.CAIXA, BD.CAIXA, BD.REF]


def test_resolver_editor_escolhe_e_visualizador_so_ve_o_fixado():
    assert BD.resolver("Despesas", BD.REF, None, True) == BD.REF                    # editor: a escolha do seletor
    assert BD.resolver("Despesas", None, BD.REF, True) == BD.REF                    # editor sem escolha: abre na base fixada para a Diretoria
    assert BD.resolver("Despesas", None, None, True) == BD.CAIXA                    # ...ou no padrao da aba
    assert BD.resolver("Despesas", BD.REF, BD.CAIXA, False) == BD.CAIXA             # visualizador ignora qualquer escolha: so' a fixada
    assert BD.resolver("Resultado", BD.CAIXA, None, False) == BD.REF                # sem fixada: padrao da aba


def test_chave_de_config_sem_acento_nem_espaco():
    assert BD.chave_config("Administração") == "base_aba_administracao" and BD.chave_config("Folha PJ") == "base_aba_folha_pj"
    assert len({BD.chave_config(a) for a in BD.ABAS}) == len(BD.ABAS)


def test_legenda_diz_a_base_em_uso():
    assert "Referência" in BD.legenda(BD.REF) and "emitido" in BD.legenda(BD.REF)
    assert "Caixa" in BD.legenda(BD.CAIXA) and "realmente saiu" in BD.legenda(BD.CAIXA)
    assert "definida pela contabilidade" in BD.legenda(BD.CAIXA, fixada=True)


# ------------------------------------------------------------------ banco
def _t(bill, credor, valor, emissao, pago, data_pag, plano, cc, previsao="N"):
    """Titulo com emissao e (opcional) pagamento em datas diferentes: `pago` = valor realmente baixado (None = em aberto)."""
    reg = {"billId": bill, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "NFS ",
           "forecastDocument": previsao, "creditorId": bill, "creditorName": credor, "issueDate": emissao, "dueDate": emissao, "originalAmount": valor,
           "payments": [_pg(1, data_pag, pago)] if pago else [], "paymentsCategories": [_c(plano, "Conta " + plano, 100, cc, f"CC {cc}")]}
    return reg


def _monta(conn):
    regs = [
        _t(21, "FORN EMITIDO AGO PAGO SET", 1000.0, "2026-08-20", 1000.0, "2026-09-10", "2030102", 1),        # competencia ago, caixa set
        _t(22, "FORN EMITIDO SET ABERTO", 400.0, "2026-09-05", None, None, "2030102", 1),                      # competencia set, ainda nao pago
        _t(23, "FORN EMITIDO SET PAGO SET", 200.0, "2026-09-06", 200.0, "2026-09-25", "2030104", 2),           # competencia e caixa em set
        _t(24, "FORN PREVISAO", 150.0, "2026-09-20", None, None, "2030102", 1, previsao="S"),
    ]
    sid = P.criar_sync(conn, "2026-08", "P", "P", "teste@x")
    cont = P.gravar_normalizado(conn, sid, S.normalizar_titulos("P", regs))
    P.finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, empresa_nome, grupo, codigo_obra) VALUES "
                    "(1,'SEDE A','EMPRESA A','ADM','ADM'),(2,'SEDE B','EMPRESA B','ADM','ADM') ON CONFLICT DO NOTHING")


def _por(linhas, mes):
    return round(sum(l["valor"] for l in linhas if l["mes"] == mes), 2)


@pytest.mark.pg
def test_despesas_nas_duas_bases(conn):
    _monta(conn)
    caixa = DD.pagos_detalhe(conn, "2026-08", "2026-09", sem_previsao=True, base=BD.CAIXA)
    ref = DD.pagos_detalhe(conn, "2026-08", "2026-09", sem_previsao=True, base=BD.REF)
    assert (_por(caixa, "2026-08"), _por(caixa, "2026-09")) == (0.0, 1200.0)         # caixa: so' o que foi pago (1000 em set + 200 em set)
    assert (_por(ref, "2026-08"), _por(ref, "2026-09")) == (1000.0, 600.0)           # referencia: emitido (1000 em ago; 400 aberto + 200 em set)
    assert DD.pagos_detalhe(conn, "2026-08", "2026-09", sem_previsao=True) == caixa  # sem `base`: continua CAIXA (nada muda para quem nao escolhe)
    sem_filtro = DD.pagos_detalhe(conn, "2026-09", "2026-09", sem_previsao=False, base=BD.REF)
    assert _por(sem_filtro, "2026-09") == 750.0                                      # sem a regra de previsao entra o documento de previsao (150)
    assert all(l["credor"] and l["plano_cod"] for l in ref)


@pytest.mark.pg
def test_administracao_nas_duas_bases(conn):
    _monta(conn)
    ev_c = {x["mes"]: x["valor"] for x in P.adm_evolucao(conn, "2026-08", "2026-09", [], sem_previsao=True)}
    ev_r = {x["mes"]: x["valor"] for x in P.adm_evolucao(conn, "2026-08", "2026-09", [], sem_previsao=True, base=BD.REF)}
    assert ev_c == {"2026-09": 1200.0}
    assert ev_r == {"2026-08": 1000.0, "2026-09": 600.0}
    lin_r = P.adm_linhas(conn, "2026-09", "2026-09", [], sem_previsao=True, base=BD.REF)
    assert round(sum(l["valor"] for l in lin_r), 2) == 600.0 and {l["credor"] for l in lin_r} == {"FORN EMITIDO SET ABERTO", "FORN EMITIDO SET PAGO SET"}
    lin_c = P.adm_linhas(conn, "2026-09", "2026-09", [], sem_previsao=True)
    assert {l["credor"] for l in lin_c} == {"FORN EMITIDO AGO PAGO SET", "FORN EMITIDO SET PAGO SET"}
    assert P.adm_linhas(conn, "2026-09", "2026-09", ["2.03"], sem_previsao=True, base=BD.REF) == [] and \
           round(sum(l["valor"] for l in P.adm_linhas(conn, "2026-09", "2026-09", ["2.03.01.04"], sem_previsao=True, base=BD.REF)), 2) == 400.0   # contas excluidas valem nas 2 bases


@pytest.mark.pg
def test_base_fixada_para_a_diretoria_vai_e_volta(conn):
    assert acesso.bases_fixadas(conn) == {}
    assert acesso.definir_base_fixada(conn, "Despesas", "ref", "ed@x") == BD.REF
    assert acesso.definir_base_fixada(conn, "Resultado", BD.CAIXA, "ed@x") == BD.CAIXA
    assert acesso.bases_fixadas(conn) == {"Despesas": BD.REF, "Resultado": BD.CAIXA}
    assert acesso.definir_base_fixada(conn, "Despesas", None, "ed@x") is None            # soltar: grava vazio, volta ao padrao da aba
    assert acesso.bases_fixadas(conn) == {"Resultado": BD.CAIXA}
    with pytest.raises(ValueError):
        acesso.definir_base_fixada(conn, "Aba inexistente", BD.REF, "ed@x")
    with pytest.raises(ValueError):
        acesso.definir_base_fixada(conn, "Despesas", "talvez", "ed@x")


# ------------------------------------------------------------------ tela (Painel da Diretoria)
APP = __import__("pathlib").Path(__file__).resolve().parent.parent


def _tela(conn, email, todas=True):
    import streamlit as st
    from types import SimpleNamespace
    from streamlit.testing.v1 import AppTest
    st.cache_data.clear()
    at = AppTest.from_file(str(APP / "telas" / "9_Painel_Diretoria.py"), default_timeout=90)
    at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email=email))
    if todas:
        at.session_state["dir_todas_abas"] = True
    return at


def _legendas(at):
    return [c.value for c in at.caption if c.value.startswith("Base:")]


@pytest.mark.pg
def test_editor_escolhe_a_base_por_aba_e_visualizador_so_ve_a_fixada(conn):
    from unittest.mock import patch
    from test_administracao import _montar
    _montar(conn)
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        ed = _tela(conn, "contabilidade@empresa.com")
        ed.run()
        assert not ed.exception, ed.exception
        chaves = {r.key for r in ed.radio}
        assert {"dir_base_despesas", "dir_base_administracao", "dir_base_pessoas"} <= chaves          # as 3 abas desta fase tem seletor
        assert ed.radio(key="dir_base_despesas").value == BD.CAIXA and ed.radio(key="dir_base_administracao").value == BD.CAIXA     # padroes de hoje
        ed.radio(key="dir_base_despesas").set_value(BD.REF).run()                                   # editor troca so' a aba Despesas
        assert not ed.exception, ed.exception
        assert ed.radio(key="dir_base_despesas").value == BD.REF and ed.radio(key="dir_base_administracao").value == BD.CAIXA
        assert any("Referência" in x and "emitido" in x for x in _legendas(ed))
        # visualizador: nenhum seletor, base = padrao da aba (nada fixado ainda)
        vi = _tela(conn, "diretor@empresa.com")
        vi.run()
        assert not vi.exception, vi.exception
        assert not [r for r in vi.radio if r.key.startswith("dir_base_")]
        assert not [b for b in vi.button if (b.key or "").startswith("dir_base_")]
        assert all("definida pela contabilidade" not in x for x in _legendas(vi)) and _legendas(vi)
        # editor fixa a base da aba Despesas para a Diretoria pelo botao
        ed.button(key="dir_base_despesas_fixa").click().run()
        assert not ed.exception, ed.exception
        assert acesso.bases_fixadas(conn) == {"Despesas": BD.REF}
        vi2 = _tela(conn, "diretor@empresa.com")
        vi2.run()
        assert not vi2.exception, vi2.exception
        assert any("Referência" in x and "definida pela contabilidade" in x for x in _legendas(vi2))
        assert any("Caixa" in x for x in _legendas(vi2))                                           # as outras abas seguem no padrao (Caixa)
