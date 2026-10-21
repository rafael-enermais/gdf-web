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
        assert [t.label for t in at.tabs] == ["Resultado", "Obras", "Administração", "Despesas", "Pessoas", "Indicadores financeiros", "Financiamentos"]        # Investimentos: so' o editor (ou se liberado)
        assert any("Receita (base-line)" == m.label for m in at.metric)
        at.session_state["dir_todas_abas"] = True                                       # renderiza todas as abas (so' a aberta roda por padrao)
        at.run()
        assert not at.exception, at.exception
        rotulos = {m.label for m in at.metric}
        assert {"PMR simples", "PMP ponderado", "Vencido a receber", "Vencido a pagar"} <= rotulos      # aba Indicadores financeiros
        assert "Saldo devedor" in rotulos or any("financiamento" in (i.value or "").lower() for i in at.info)   # aba Financiamentos (com ou sem contratos)
        at.text_input(key="dir_ob_busca").input("zzz-inexistente").run()                 # busca sem resultado nao quebra
        assert not at.exception, at.exception


def test_cadastro_de_visualizador_na_aba_regras(conn):
    _ingerir(conn)
    with patch("conexao.get_conn", return_value=conn):
        at = AppTest.from_file(str(APP / "telas" / "8_Painel_EnerMais.py"), default_timeout=30)
        at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="rafael@x"))
        at.session_state["pn2_abas"] = "Regras"                       # as abas rodam so' quando abertas
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


def test_painel_da_diretoria_cinco_abas_com_tudo(conn):
    """Cenario completo (v0.23): DRE por obra, folha, orcamento ADM, historico, contas pagas com PJ -> as 5 abas renderizam e mostram o que a contabilidade espera."""
    import io
    import openpyxl
    import historico as H
    import importador_folha as IF
    import importador_orcamento as IO
    import importador_projecao as IP
    from folha_sintetica import pdf_folha_sintetico
    from orcamento_sintetico import pdf_orcamento_sintetico
    from test_historico_pg import _html
    from test_painel_db_pg import _depara_folha
    _ingerir(conn, lado="P", tipo="P")                       # contas pagas de ago/set (inclui "Salarios PJ")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    _depara_folha(conn)
    P.gravar_folha(conn, IF.ler_recibos_pdf(pdf_folha_sintetico()), "r.pdf", "d" * 64, "teste@x")
    ro = P.gravar_orcamento(conn, IO.ler_orcamento_adm_pdf(pdf_orcamento_sintetico()), "o.pdf", "1" * 64, "teste@x")
    with conn.cursor() as cur:                               # o orcamento sintetico vai de jan a jun: desloca 3 meses para cobrir setembro
        cur.execute("UPDATE pnl_orcamento_linha SET mes = mes + interval '3 months' WHERE importacao_id=%s", (ro["id"],))
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CONTRATO", "CLIENTE", "OBRA", "CATEGORIA", "NATUREZA", "EMPRESA / FORNECEDOR", "set/26", "CUSTOS", "BDI"])
    ws.append(["C1", "CLI A", "OBRA UM", "INDIRETO", None, "CONSTRUTORA", 1000.0, 700.0, 300.0])
    buf = io.BytesIO(); wb.save(buf)
    P.gravar_projecao(conn, IP.ler_projecao_xlsx(buf.getvalue()), "p.xlsx", "e" * 64, "teste@x")
    H.gravar(conn, H.ler_historico(_html(), "a.html"), "2026-09", "a.html", "rafael@x")
    assert P.credor_grupo_adicionar(conn, "FORNECEDOR TESTE", "rafael@x")["ok"]            # "Outros credores/Dir": entra numa linha so' na Administracao
    P.gravar_credores_sienge(conn, [{"id": 78, "nome": "COLABORADOR TESTE", "nome_fantasia": "Colab Fantasia"}])        # contabilidade 21/10: PJ pelo nome fantasia do cadastro
    with conn.cursor() as cur:                                                                                         # o centro do PJ vira a obra 103 (para ele aparecer na lista da aba Obras)
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, empresa_nome, grupo, codigo_obra) VALUES (1,'CC TESTE','EMPRESA','OBRA','103')")
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _app_como(conn, "diretor@empresa.com")
        at.session_state["dir_todas_abas"] = True
        at.run()
        assert not at.exception, at.exception
        nomes_pj = [list(d.value["Nome"]) for d in at.dataframe if "Nome" in d.value.columns and "Função" in d.value.columns]          # lista de colaboradores da aba Obras
        assert nomes_pj and any("Colab Fantasia" in n for n in nomes_pj[0]) and not any(n == "COLABORADOR TESTE" for n in nomes_pj[0]), nomes_pj
        pj_exp = [d.value for d in at.dataframe if "Colaborador PJ" in d.value.columns]                                                 # expander "PJ do mes" da aba Pessoas
        assert pj_exp and "Colab Fantasia" in set(pj_exp[0]["Colaborador PJ"]) and "COLABORADOR TESTE" in set(pj_exp[0]["Razão social"])
        rotulos = [m.label for m in at.metric]
        for esperado in ("Receita (base-line)", "Custos diretos", "BDI", "Administração", "Resultado",        # Resultado
                         "Receita realizada", "Obras com prejuízo",                                           # Obras
                         "Orçado 09/2026", "Meses acima do orçado",                                           # Administracao
                         "Pago em 09/2026", "Top 12 Jan–Set/26",                                                  # Despesas
                         "Colaboradores 09/2026", "Receita por colaborador"):                                 # Pessoas
            assert esperado in rotulos, (esperado, rotulos)
        colab = next(m for m in at.metric if m.label == "Colaboradores 09/2026")
        assert colab.value == "4" and "3 CLT + 1 PJ" in colab.delta                                            # 3 CLT (folha) + 1 PJ (contas pagas)
        assert any("PJ do mês" in e.label for e in at.expander)
        for modo in ("Mês", "Últimos 3 meses", "Últimos 6 meses", "Últimos 12 meses", "Personalizado", "Ano até o mês"):      # filtro de periodo flexivel: nenhuma aba quebra
            at.selectbox(key="dir_per_modo").select(modo).run()
            assert not at.exception, (modo, at.exception)
        assert any("Período:" in c.value or "período:" in c.value for c in at.caption)
        at.radio(key="dir_pes_linhas").set_value("Todas").run()
        assert not at.exception, at.exception
        # cascata da aba Obras: lista de colaboradores por obra (CLT da folha + PJ das contas pagas), com busca
        sb = at.selectbox(key="dir_col_obra")
        assert sb.options[0] == "Todas as obras" and len(sb.options) >= 2, sb.options
        todos = [c.value for c in at.caption if "colaboradores (" in c.value]
        assert todos and "CLT" in todos[0] and "PJ" in todos[0], todos
        sb.set_value("DEM").run()
        assert not at.exception, at.exception
        at.text_input(key="dir_col_busca").set_value("zzzz-nao-existe").run()
        assert not at.exception, at.exception
        assert any("Sem colaboradores para esta seleção" in c.value for c in at.caption)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pnl_regra WHERE tipo='EXCLUI_PREVISAO'")


def test_aba_investimentos_so_para_editor_ou_se_liberada(conn):
    """Checkbox do editor (SQL-29): padrao = visualizador NAO ve Investimentos; editor sempre ve; liberar/esconder vale na proxima abertura."""
    _ingerir(conn)
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    assert acesso.config_instalada(conn) and acesso.investimentos_para_visualizador(conn) is False
    with patch("conexao.get_conn", return_value=conn):
        v = _app_como(conn, "diretor@empresa.com").run()
        assert not v.exception, v.exception
        assert "Investimentos" not in [t.label for t in v.tabs]
        e = AppTest.from_file(str(APP / "telas" / "9_Painel_Diretoria.py"), default_timeout=60)          # o editor abre a pagina da Diretoria direto
        e.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="contabilidade@empresa.com"))
        e.session_state["dir_todas_abas"] = True
        e.run()
        assert not e.exception, e.exception
        assert [t.label for t in e.tabs][-2:] == ["Financiamentos", "Investimentos"]
        cb = e.checkbox(key="dir_inv_visu")
        assert cb.value is False
        cb.check().run()                                                                  # editor libera
        assert not e.exception, e.exception
        assert acesso.investimentos_para_visualizador(conn) is True
        v2 = _app_como(conn, "diretor@empresa.com").run()
        assert "Investimentos" in [t.label for t in v2.tabs]
        e.checkbox(key="dir_inv_visu").uncheck().run()                                    # e esconde de novo
        assert acesso.investimentos_para_visualizador(conn) is False
        v3 = _app_como(conn, "diretor@empresa.com").run()
        assert "Investimentos" not in [t.label for t in v3.tabs]


def test_administracao_do_painel_junta_outros_credores_dir_e_respeita_o_periodo(conn):
    """21/10/2026: no detalhe da Administracao, os credores do grupo 'Outros credores/Dir' viram UMA linha; o periodo escolhido muda o acumulado."""
    from test_administracao import _montar
    _montar(conn)                                                        # 1000 (ALFA) + 400 em set; 200 (BETA) em ago, centros ADM
    assert P.credor_grupo_adicionar(conn, "FORNECEDOR BETA", "rafael@x")["ok"]
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _app_como(conn, "diretor@empresa.com")
        at.session_state["dir_todas_abas"] = True
        at.run()
        assert not at.exception, at.exception
        if "2026-09" in at.selectbox(key="dir_mes").options:
            at.selectbox(key="dir_mes").select("2026-09").run()
        assert not at.exception, at.exception
        com_outros = [list(d.value["Credor"]) for d in at.dataframe if "Credor" in d.value.columns and "Outros credores/Dir" in set(d.value["Credor"])]
        assert com_outros, [m.value[:50] for m in at.markdown if "Quem recebeu" in m.value]            # a tabela de credores da Administracao
        nomes = com_outros[0]
        assert not any("BETA" in n for n in nomes) and any("ALFA" in n for n in nomes)
        assert any("Outros credores/Dir" in c.value for c in at.caption)
        at.selectbox(key="dir_per_modo").select("Mês").run()                # periodo de um mes so': a mesma tela segue sem erro
        assert not at.exception, at.exception


def test_periodo_personalizado_pede_primeiro_o_inicio_depois_o_fim(conn):
    """21/10/2026: na ordem da tela vem "De" e depois "Até"; o "Até" so' oferece meses a partir do "De" (nunca fim antes do inicio)."""
    from test_administracao import _montar
    _montar(conn)
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _app_como(conn, "diretor@empresa.com")
        at.run()
        at.selectbox(key="dir_per_modo").select("Personalizado").run()
        assert not at.exception, at.exception
        ordem = [s.key for s in at.selectbox if s.key in ("dir_mes_de", "dir_mes_ate")]
        assert ordem == ["dir_mes_de", "dir_mes_ate"], ordem
        de = at.selectbox(key="dir_mes_de")
        assert at.selectbox(key="dir_mes_ate").options[-1] == de.options[-1]
        ultimo = de.options[-1]                                                    # rotulos "MM/AAAA"
        de.set_value(f"{ultimo[3:]}-{ultimo[:2]}").run()                           # inicio = ultimo mes -> o fim so' pode ser esse mes
        assert not at.exception, at.exception
        assert at.selectbox(key="dir_mes_ate").options == [ultimo]
        assert at.selectbox(key="dir_mes_ate").value == f"{ultimo[3:]}-{ultimo[:2]}"
