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


def test_resultado_e_obras_sao_sempre_referencia_para_a_diretoria():
    """Contabilidade (29/10/2026): Resultado e Obras para a Diretoria = Referencia, mesmo que alguem tenha fixado Caixa; o editor ainda pode explorar o Caixa."""
    for aba in ("Resultado", "Obras"):
        assert BD.resolver(aba, None, BD.CAIXA, False) == BD.REF
        assert BD.resolver(aba, BD.CAIXA, BD.CAIXA, True) == BD.CAIXA               # editor escolhendo Caixa para analisar
        assert BD.resolver(aba, None, BD.CAIXA, True) == BD.REF                     # editor sem escolha abre em Referencia (a fixacao e' ignorada)
    assert BD.resolver("Despesas", None, BD.REF, False) == BD.REF                   # as outras abas seguem a base fixada


def test_chave_de_config_sem_acento_nem_espaco():
    assert BD.chave_config("Administração") == "base_aba_administracao" and BD.chave_config("Folha PJ") == "base_aba_folha_pj"
    assert len({BD.chave_config(a) for a in BD.ABAS}) == len(BD.ABAS)


def test_legenda_diz_a_base_em_uso():
    assert "Referência" in BD.legenda(BD.REF) and "emitido" in BD.legenda(BD.REF)
    assert "Caixa" in BD.legenda(BD.CAIXA) and "realmente saiu" in BD.legenda(BD.CAIXA)
    assert "definida pela contabilidade" in BD.legenda(BD.CAIXA, fixada=True)


# ------------------------------------------------------------------ banco
def _t(bill, credor, valor, emissao, pago, data_pag, plano, cc, previsao="N", extras=()):
    """Titulo com emissao e (opcional) pagamento em datas diferentes: `pago` = valor realmente baixado (None = em aberto). `extras` = baixas adicionais (ex.: substituicao)."""
    reg = {"billId": bill, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "NFS ",
           "forecastDocument": previsao, "creditorId": bill, "creditorName": credor, "issueDate": emissao, "dueDate": emissao, "originalAmount": valor,
           "payments": ([_pg(1, data_pag, pago)] if pago else []) + list(extras), "paymentsCategories": [_c(plano, "Conta " + plano, 100, cc, f"CC {cc}")]}
    return reg


def _monta(conn):
    regs = [
        _t(21, "FORN EMITIDO AGO PAGO SET", 1000.0, "2026-08-20", 1000.0, "2026-09-10", "2030102", 1),        # competencia ago, caixa set
        _t(22, "FORN EMITIDO SET ABERTO", 400.0, "2026-09-05", None, None, "2030102", 1),                      # competencia set, ainda nao pago
        _t(23, "FORN EMITIDO SET PAGO SET", 200.0, "2026-09-06", 200.0, "2026-09-25", "2030104", 2),           # competencia e caixa em set
        _t(24, "FORN PREVISAO", 150.0, "2026-09-20", None, None, "2030102", 1, previsao="S"),
        # 400 emitido em set; pago 100 em dinheiro + 300 de SUBSTITUICAO (troca de documento: nao e' caixa)
        _t(25, "FORN MISTO", 400.0, "2026-09-02", 100.0, "2026-09-15", "2030102", 1, extras=[_pg(2, "2026-09-16", 300.0, 5, "Substituição")]),
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
    assert (_por(caixa, "2026-08"), _por(caixa, "2026-09")) == (0.0, 1300.0)         # caixa: so' dinheiro real (1000 + 200 + 100; os 300 de substituicao ficam fora)
    assert (_por(ref, "2026-08"), _por(ref, "2026-09")) == (1000.0, 1000.0)          # referencia: emitido (1000 em ago; em set 400 aberto + 200 + 400 do titulo misto)
    assert DD.pagos_detalhe(conn, "2026-08", "2026-09", sem_previsao=True) == caixa  # sem `base`: continua CAIXA (nada muda para quem nao escolhe)
    sem_filtro = DD.pagos_detalhe(conn, "2026-09", "2026-09", sem_previsao=False, base=BD.REF)
    assert _por(sem_filtro, "2026-09") == 1150.0                                     # sem a regra de previsao entra o documento de previsao (150)
    assert all(l["credor"] and l["plano_cod"] for l in ref)


@pytest.mark.pg
def test_administracao_nas_duas_bases(conn):
    _monta(conn)
    ev_c = {x["mes"]: x["valor"] for x in P.adm_evolucao(conn, "2026-08", "2026-09", [], sem_previsao=True)}
    ev_r = {x["mes"]: x["valor"] for x in P.adm_evolucao(conn, "2026-08", "2026-09", [], sem_previsao=True, base=BD.REF)}
    assert ev_c == {"2026-09": 1300.0}
    assert ev_r == {"2026-08": 1000.0, "2026-09": 1000.0}
    lin_r = P.adm_linhas(conn, "2026-09", "2026-09", [], sem_previsao=True, base=BD.REF)
    assert round(sum(l["valor"] for l in lin_r), 2) == 1000.0 and {l["credor"] for l in lin_r} == {"FORN EMITIDO SET ABERTO", "FORN EMITIDO SET PAGO SET", "FORN MISTO"}
    lin_c = P.adm_linhas(conn, "2026-09", "2026-09", [], sem_previsao=True)
    assert {l["credor"] for l in lin_c} == {"FORN EMITIDO AGO PAGO SET", "FORN EMITIDO SET PAGO SET", "FORN MISTO"}
    assert round(sum(l["valor"] for l in lin_c if l["credor"] == "FORN MISTO"), 2) == 100.0          # so' os 100 em dinheiro, nao os 300 da substituicao
    assert P.adm_linhas(conn, "2026-09", "2026-09", ["2.03"], sem_previsao=True, base=BD.REF) == [] and \
           round(sum(l["valor"] for l in P.adm_linhas(conn, "2026-09", "2026-09", ["2.03.01.04"], sem_previsao=True, base=BD.REF)), 2) == 800.0   # contas excluidas valem nas 2 bases


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



def _rec(bill, valor, emissao, recebido, data_rec, cc=1049, oper=2):
    """Titulo a RECEBER (receita 1.01.01.01) com emissao e recebimento em datas diferentes (tipo 2 = Recebimento; 7 = Distrato nao e' caixa)."""
    return {"billId": bill, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "NS", "documentIdentificationId": "NFS ", "clientId": 900,
            "clientName": "CLIENTE TESTE", "issueDate": emissao, "dueDate": emissao, "originalAmount": valor,
            "receipts": ([{"sequencialNumber": 1, "paymentDate": data_rec, "netAmount": recebido, "grossAmount": recebido, "taxAmount": 0.0, "operationTypeId": oper,
                           "operationTypeName": "Recebimento"}] if recebido else []),
            "receiptsCategories": [{"financialCategoryId": "1010101", "financialCategoryName": "Receitas de Serviços", "financialCategoryRate": 100,
                                    "costCenterId": cc, "costCenterName": "CON - OBRA 103", "projectId": 5, "projectName": "CONSTRUTORA"}]}


def _monta_resultado(conn):
    P.limpar_memo()
    sp = P.criar_sync(conn, "2026-08", "P", "P", "teste@x")
    regs_p = [_t(31, "FORN MATERIAL", 1000.0, "2026-08-20", 1000.0, "2026-09-10", "2010104", 1049,
                 extras=[_pg(2, "2026-09-11", 400.0, 5, "Substituição")]),                                    # custo de obra 103: emitido em ago, pago em set (+ substituicao fora)
              _t(32, "FORN MATERIAL 2", 300.0, "2026-09-03", None, None, "2010104", 1049)]                    # emitido em set, ainda nao pago
    cont = P.gravar_normalizado(conn, sp, S.normalizar_titulos("P", regs_p))
    P.finalizar_sync(conn, sp, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    sr = P.criar_sync(conn, "2026-08", "R", "P", "teste@x")
    regs_r = [_rec(61, 2000.0, "2026-08-15", 1800.0, "2026-09-30"),                                           # emitido em ago, recebido em set
              _rec(62, 500.0, "2026-09-05", None, None),                                                       # emitido em set, nao recebido
              _rec(63, 700.0, "2026-09-06", 700.0, "2026-09-20", oper=7)]                                      # distrato: nao e' dinheiro
    cont = P.gravar_normalizado(conn, sr, S.normalizar_titulos("R", regs_r))
    P.finalizar_sync(conn, sr, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, empresa_nome, grupo, codigo_obra, obra_nome) VALUES "
                    "(1049,'OBRA 103','EMPRESA A','OBRA','103','OBRA CENTO E TRES') ON CONFLICT DO NOTHING")


@pytest.mark.pg
def test_resultado_e_obras_em_caixa_so_contam_dinheiro_real(conn):
    _monta_resultado(conn)
    c = {x["plano_cod"]: x["valor"] for x in P.resultado_por_conta_caixa(conn, "2026-09", sem_previsao=True)}
    assert c["1.01.01.01"] == 1800.0 and c["2.01.01.04"] == -1000.0                  # recebido 1800 (distrato fora); pago 1000 (substituicao de 400 fora)
    assert {x["plano_cod"]: x["valor"] for x in P.resultado_por_conta_caixa(conn, "2026-08", sem_previsao=True)} == {}      # nada foi pago/recebido em agosto
    ob = P.obras_do_mes(conn, "2026-09", "CAIXA")
    assert ob and ob["fonte"] == "API" and "baixas" in ob["arquivo"]
    assert (ob["total"]["receita"], ob["total"]["custo"], ob["total"]["bdi"]) == (1800.0, -1000.0, 800.0)
    assert [l["obra"] for l in ob["linhas"]] == ["103"] and ob["linhas"][0]["nome"] == "OBRA CENTO E TRES"
    em_ref = P.obras_do_mes(conn, "2026-09", "REF")                                   # referencia: emitido em set = receita 500 e custo 300 (o de ago nao entra)
    assert (em_ref["total"]["receita"], em_ref["total"]["custo"]) == (500.0, -300.0)
    lote = P.obras_dos_meses(conn, ["2026-08", "2026-09"], "CAIXA")
    assert lote["2026-08"] is None and lote["2026-09"]["total"] == ob["total"]       # em lote = mes a mes
    t = P.termos_do_mes(conn, "2026-09", "CAIXA")
    assert (t["rec"], t["cus"], t["bdi"], t["fonte"]) == (1800.0, 1000.0, 800.0, "caixa") and t["rec_p"] is None and t["adm_orc"] is None
    assert P.termos_do_mes(conn, "2026-08", "CAIXA") is None
    assert [(x["mes"], x["receita"]) for x in P.receita_mensal(conn, base="CAIXA")] == [("2026-09", 1800.0)]
    ln = P.custos_obra_linhas_caixa(conn, "2026-08", "2026-09")
    assert [(o, m, pl, v) for o, m, pl, v in ln] == [("103", "2026-09", "2.01.01.04", -1000.0)]

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


@pytest.mark.pg
def test_resultado_e_obras_tem_seletor_e_abrem_em_caixa_sem_erro(conn):
    from unittest.mock import patch
    from test_administracao import _montar
    _montar(conn)
    _monta_resultado(conn)
    with patch("conexao.get_conn", return_value=conn):
        ed = _tela(conn, "contabilidade@empresa.com")
        ed.run()
        assert not ed.exception, ed.exception
        chaves = {r.key for r in ed.radio}
        assert {"dir_base_resultado", "dir_base_obras"} <= chaves
        assert ed.radio(key="dir_base_resultado").value == BD.REF and ed.radio(key="dir_base_obras").value == BD.REF        # padroes de hoje
        ed.radio(key="dir_base_resultado").set_value(BD.CAIXA).run()
        assert not ed.exception, ed.exception
        ed.radio(key="dir_base_obras").set_value(BD.CAIXA).run()
        assert not ed.exception, ed.exception
        assert sum("Caixa" in x for x in _legendas(ed)) >= 2
        ed.radio(key="dir_base_resultado").set_value(BD.REF).run()                                    # e volta sem quebrar
        assert not ed.exception, ed.exception


@pytest.mark.pg
def test_folha_pj_e_folha_clt_tem_seletor_e_trocam_de_base_sem_erro(conn):
    from unittest.mock import patch
    from test_administracao import _montar
    _montar(conn)
    with patch("conexao.get_conn", return_value=conn):
        ed = _tela(conn, "contabilidade@empresa.com")
        ed.run()
        assert not ed.exception, ed.exception
        assert {"dir_base_folha_pj", "dir_base_folha_clt"} <= {r.key for r in ed.radio}
        assert ed.radio(key="dir_base_folha_pj").value == BD.CAIXA and ed.radio(key="dir_base_folha_clt").value == BD.REF        # padroes de hoje
        for chave, nova in (("dir_base_folha_pj", BD.REF), ("dir_base_folha_clt", BD.CAIXA)):
            ed.radio(key=chave).set_value(nova).run()
            assert not ed.exception, ed.exception
        vi_leg = [c.value for c in ed.caption if c.value.startswith("Base:")]
        assert sum("Caixa" in x for x in vi_leg) >= 1 and sum("Referência" in x for x in vi_leg) >= 1


@pytest.mark.pg
def test_pdf_segue_a_base_fixada_e_a_folha_clt_em_caixa_e_a_do_mes_anterior(conn):
    """O PDF usa a base que a Diretoria ve (nao a do seletor); Folha CLT em Caixa = folha de competencia do mes anterior (paga neste mes)."""
    import relatorio_diretoria_dados as RDD
    B = RDD.Base(conn, "2026-09", "2026-09")
    assert B.bases == {a: BD.padrao(a) for a in BD.ABAS} and B.comp_clt() == ("2026-09", BD.REF)       # padrao da Folha CLT: Referencia
    acesso.definir_base_fixada(conn, "Folha CLT", BD.CAIXA, "ed@x")
    acesso.definir_base_fixada(conn, "Resultado", BD.CAIXA, "ed@x")                                   # ignorado: Resultado e' sempre Referencia
    B2 = RDD.Base(conn, "2026-09", "2026-09")
    assert B2.bases["Folha CLT"] == BD.CAIXA and B2.bases["Resultado"] == BD.REF
    assert B2.comp_clt() == ("2026-08", BD.REF)                                                       # setembro em Caixa = folha de agosto
    assert any("Folha CLT Caixa" in f for f in RDD.texto_filtros("Mês", "2026-09", "2026-09", None, None, B2.bases))
