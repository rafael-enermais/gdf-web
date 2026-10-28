# -*- coding: utf-8 -*-
"""Relatorio PDF do Painel da Diretoria (v0.54.0): dados + PDF, contra Postgres descartavel. Dados 100% ficticios."""
import hashlib
import io
import shutil
import subprocess

import pytest

import acesso
import painel_db as P
import periodo as PER
import relatorio_diretoria as RD
import relatorio_diretoria_dados as RDD
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from dados_sienge import income
from test_painel_db_pg import _ingerir, _pdf_lido

pytestmark = pytest.mark.pg
APP = Path(__file__).resolve().parent.parent


def _cenario_rico(conn):
    """Mesmo cenario do teste das cinco abas: DRE por obra, folha CLT, orcamento ADM, projecao, historico, contas pagas com PJ."""
    import openpyxl
    import historico as H
    import importador_folha as IF
    import importador_orcamento as IO
    import importador_projecao as IP
    from folha_sintetica import pdf_folha_sintetico
    from orcamento_sintetico import pdf_orcamento_sintetico
    from test_historico_pg import _html
    from test_painel_db_pg import _depara_folha
    _ingerir(conn, lado="P", tipo="P")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    _depara_folha(conn)
    P.gravar_folha(conn, IF.ler_recibos_pdf(pdf_folha_sintetico()), "r.pdf", "d" * 64, "teste@x")
    ro = P.gravar_orcamento(conn, IO.ler_orcamento_adm_pdf(pdf_orcamento_sintetico()), "o.pdf", "1" * 64, "teste@x")
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_orcamento_linha SET mes = mes + interval '3 months' WHERE importacao_id=%s", (ro["id"],))
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CONTRATO", "CLIENTE", "OBRA", "CATEGORIA", "NATUREZA", "EMPRESA / FORNECEDOR", "set/26", "CUSTOS", "BDI"])
    ws.append(["C1", "CLI A", "OBRA UM", "INDIRETO", None, "CONSTRUTORA", 1000.0, 700.0, 300.0])
    buf = io.BytesIO(); wb.save(buf)
    P.gravar_projecao(conn, IP.ler_projecao_xlsx(buf.getvalue()), "p.xlsx", "e" * 64, "teste@x")
    H.gravar(conn, H.ler_historico(_html(), "a.html"), "2026-09", "a.html", "rafael@x")
    assert P.credor_grupo_adicionar(conn, "FORNECEDOR TESTE", "rafael@x")["ok"]
    P.gravar_credores_sienge(conn, [{"id": 78, "nome": "COLABORADOR TESTE", "nome_fantasia": "Colab Fantasia"}])
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_centro_grupo (centro_custo_id, centro_nome, empresa_nome, grupo, codigo_obra) VALUES (1,'CC TESTE','EMPRESA','OBRA','103')")


def _texto(pdf: bytes) -> str:
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        nome = f.name
    try:
        return subprocess.run(["pdftotext", "-layout", nome, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(nome)


def _rotulos(d):
    return [(a["aba"], [b["key"] for b in a["blocos"]]) for a in d["abas"]]


def _notas(d):
    return [e["texto"] for a in d["abas"] for b in a["blocos"] for e in b["els"] if e.get("t") == "nota"]


def _bloco(d, chave):
    return next(b for a in d["abas"] for b in a["blocos"] if b["key"] == chave)


def _tabelas(b):
    return [e for e in b["els"] if e.get("t") == "tab"]


def test_catalogo_e_modelos_coerentes():
    assert set(RDD.FUNCOES) == set(RDD.TODAS_CHAVES) and len(RDD.TODAS_CHAVES) == len(set(RDD.TODAS_CHAVES))
    for nome, chaves in RDD.MODELOS.items():
        assert chaves and set(chaves) <= set(RDD.TODAS_CHAVES), nome
    assert all(k.startswith("pj_") for k in RDD.MODELOS["Só PJ"]) and all(k.startswith("clt_") for k in RDD.MODELOS["Só CLT"])
    longas = {"ob_colab", "pj_docs", "clt_lista", "ind_receitas"}
    assert not (longas & set(RDD.PADRAO)) and set(RDD.PADRAO) == set(RDD.TODAS_CHAVES) - longas        # listas longas e nominais ficam desmarcadas por padrao


def test_montar_todas_as_informacoes_nenhuma_quebra_e_ordem_do_painel(conn):
    _cenario_rico(conn)
    d = RDD.montar(conn, "2026-01", "2026-09", RDD.TODAS_CHAVES, PER.ANO, None, None, "teste@x")
    assert [a["aba"] for a in d["abas"]] == ["res", "ob", "adm", "desp", "pes", "pj", "clt", "ind", "fin", "inv"]
    assert not any("não pôde ser montada" in t for t in _notas(d)), [t for t in _notas(d) if "não pôde" in t]
    assert d["meta"]["n_blocos"] == len(RDD.TODAS_CHAVES) - 2 and d["meta"]["per_rot"] == PER.rotulo("2026-01", "2026-09")
    assert any("todas (geral)" in f for f in d["meta"]["filtros"])
    tab_obras = _tabelas(_bloco(d, "ob_tabela"))[0]
    assert [r[1][0] for r in tab_obras["rows"]][:2] == ["103", "DEM"] and tab_obras["rows"][-1][0] == "tot"        # obra 103 + demais obras + total
    f = _bloco(d, "res_formula")["els"]
    assert [e["t"] for e in f][:3] == ["sec", "kpis", "kpis"] and f[1]["itens"][0]["rot"] == "Receita (base-line)"
    sem_inv = RDD.montar(conn, "2026-01", "2026-09", RDD.TODAS_CHAVES, PER.ANO, None, None, "teste@x", mostra_inv=False)
    assert "inv" not in [a["aba"] for a in sem_inv["abas"]]                                                        # quem nao ve Investimentos nao leva no PDF


def test_so_o_marcado_e_calculado(conn):
    _cenario_rico(conn)
    d = RDD.montar(conn, "2026-01", "2026-09", ["ob_kpis", "res_dre"], PER.ANO, None, None, "")
    assert _rotulos(d) == [("res", ["res_dre"]), ("ob", ["ob_kpis"])]
    assert RDD.montar(conn, "2026-01", "2026-09", [], PER.ANO, None, None, "")["abas"] == []


def test_filtro_de_obra_restringe_as_informacoes_com_filtro_e_avisa_nas_do_grupo(conn):
    _cenario_rico(conn)
    todas = ["ob_tabela", "ob_detalhe", "ob_colab", "pes_kpis", "res_receita"]
    d = RDD.montar(conn, "2026-01", "2026-09", todas, PER.ANO, {"obras": ["103"]}, None, "")
    linhas = [r for r in _tabelas(_bloco(d, "ob_tabela"))[0]["rows"] if r[0] == "norm"]
    assert [r[1][0] for r in linhas] == ["103"]                                                                    # so' a obra escolhida
    assert any(e["t"] == "kpis" for e in _bloco(d, "ob_detalhe")["els"])                                           # detalhe da selecao so' existe com obra escolhida
    assert all(r[1][3].startswith("103") for r in _tabelas(_bloco(d, "ob_colab"))[0]["rows"])                       # colaboradores so' da obra escolhida
    assert any("do grupo todo" in e.get("texto", "") for e in _bloco(d, "res_receita")["els"])                      # nao segue o filtro: avisa
    assert not any("do grupo todo" in e.get("texto", "") for e in _bloco(d, "ob_tabela")["els"])
    assert any("103" in f for f in d["meta"]["filtros"])
    geral = RDD.montar(conn, "2026-01", "2026-09", ["ob_detalhe"], PER.ANO, None, None, "")
    assert geral["abas"] == [] and geral["meta"]["n_blocos"] == 0                                                   # sem obra escolhida o detalhe some (nao imprime aviso)
    nenhuma = RDD.montar(conn, "2026-01", "2026-09", ["ob_tabela", "ob_prejuizo"], PER.ANO, {"obras": ["999"]}, None, "")
    assert any("Nenhuma das obras escolhidas" in t for t in _notas(nenhuma))


def test_opcoes_de_obras_trazem_as_obras_do_periodo_e_a_administracao_central(conn):
    _cenario_rico(conn)
    cods = [c for c, _ in RDD.opcoes_obras(conn, "2026-01", "2026-09")]
    assert "103" in cods and "99" in cods and "DEM" not in cods


def test_so_pj_com_filtros_de_empresa_e_situacao(conn):
    import folha_pj_dados as FP
    from test_folha_pj_pg import MES, _regs
    _ingerir(conn, regs=_regs(), lado="P", tipo="I", mes=MES)
    d = RDD.montar(conn, MES, MES, RDD.MODELOS["Só PJ"] + ["pj_docs"], PER.MES, {"obras": [], "empresas": [], "situacoes": []}, None, "")
    assert [a["aba"] for a in d["abas"]] == ["pj"] and not any("não pôde" in t for t in _notas(d))
    txt = str(_bloco(d, "pj_colab")["els"])
    assert "Joao Teste" in txt and "Maria Teste" in txt
    parcial = RDD.montar(conn, MES, MES, ["pj_colab", "pj_cards"], PER.MES, {"situacoes": ["Parcial"]}, None, "")
    txt = str(_bloco(parcial, "pj_colab")["els"])
    assert "Joao Teste" in txt and "Maria Teste" not in txt and any("Situação (PJ): Parcial" in f for f in parcial["meta"]["filtros"])
    outra = RDD.montar(conn, MES, MES, ["pj_colab", "pj_kpis", "pj_obras"], PER.MES, {"empresas": [FP.EMPRESAS[2]]}, None, "")             # empresa sem nenhum pagamento: nao quebra
    assert not any("não pôde" in t for t in _notas(outra)) and "Joao Teste" not in str(_bloco(outra, "pj_colab")["els"])


def test_pdf_do_relatorio_tem_capa_sumario_paginas_e_conteudo(conn):
    _cenario_rico(conn)
    d = RDD.montar(conn, "2026-01", "2026-09", RDD.TODAS_CHAVES, PER.ANO, {"obras": ["103"]}, None, "teste@x", True)
    pdf = RD.gerar_pdf(d)
    assert pdf[:5] == b"%PDF-"
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext indisponivel")
    t = _texto(pdf)
    paginas = t.count("\f")
    assert paginas >= 8
    assert "Relatório do" in t and "Painel da Diretoria" in t and "Filtros deste relatório" in t and "Obras: 103" in t
    assert f"Página 2 de {paginas}" in t and f"Página {paginas} de {paginas}" in t                                  # 'Pagina n de N' certo nas duas passadas
    for titulo in ("Resultado por obra", "Despesas: visão geral", "Composição do custo PJ", "Folha CLT consolidada"):
        assert titulo in t, titulo
    assert "Colab Fantasia" in t and "COLABORADOR TESTE" not in t                                                      # nome fantasia, como no painel


def test_pdf_sem_nenhuma_informacao_nao_quebra(conn):
    _cenario_rico(conn)
    pdf = RD.gerar_pdf(RDD.montar(conn, "2026-01", "2026-09", [], PER.ANO, None, None, ""))
    assert pdf[:5] == b"%PDF-"
    if shutil.which("pdftotext"):
        assert "Nenhuma informação foi marcada" in _texto(pdf)


def _painel(conn, email="contabilidade@empresa.com"):
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_file(str(APP / "telas" / "9_Painel_Diretoria.py"), default_timeout=90)
    at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email=email))
    return at


def test_botao_do_relatorio_no_painel_modelos_filtros_e_download(conn):
    _cenario_rico(conn)
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn):
        at = _painel(conn).run()
        assert not at.exception, at.exception
        assert any(e.label.startswith("Gerar relatório em PDF") for e in at.expander)
        assert at.radio(key="rel_modelo").value == "Completo" and at.checkbox(key="rel_k_res_formula").value and not at.checkbox(key="rel_k_pj_docs").value      # padrao: completo, sem as listas longas
        at.radio(key="rel_modelo").set_value("Só PJ").run()                                                                                       # modelo marca as caixinhas dele
        assert not at.exception, at.exception
        assert at.checkbox(key="rel_k_pj_cards").value and not at.checkbox(key="rel_k_res_formula").value and not at.checkbox(key="rel_k_pj_docs").value and not at.checkbox(key="rel_a_res").value
        at.checkbox(key="rel_k_res_formula").check().run()                                                                                        # marcar a mao vira Personalizado
        assert at.radio(key="rel_modelo").value == "Personalizado"
        at.checkbox(key="rel_a_clt").check().run()                                                                                                # "aba toda" liga todas as informacoes dela
        assert at.checkbox(key="rel_k_clt_cards").value and at.checkbox(key="rel_k_clt_lista").value
        at.multiselect(key="rel_obras").set_value(["103"]).run()
        at.button(key="rel_gerar").click().run()
        assert not at.exception, at.exception
        pdf = at.session_state["rel_pdf"]
        assert pdf["bytes"][:5] == b"%PDF-" and pdf["nome"] == "relatorio_painel_diretoria_2026-09_obras-103.pdf" and pdf["n"] > 5
        assert any("Relatório pronto" in s.value for s in at.success)
        at.multiselect(key="rel_obras").set_value([]).run()                                                                                       # mudou o filtro: pede para gerar de novo
        assert not any("Relatório pronto" in s.value for s in at.success) and any("mudou desde o último relatório" in i.value for i in at.info)
        for k in [k for k in RDD.TODAS_CHAVES if at.checkbox(key="rel_k_" + k).value]:                                                              # nada marcado: botao desligado
            at.checkbox(key="rel_k_" + k).uncheck()
        at.run()
        assert at.button(key="rel_gerar").disabled
        v = _painel(conn, "diretor@empresa.com").run()                                                                                           # visualizador: o gerador NAO existe (so' o painel)
        assert not v.exception, v.exception
        assert not any(e.label.startswith("Gerar relatório em PDF") for e in v.expander)
        assert not [c for c in v.checkbox if c.key and c.key.startswith(("rel_k_", "rel_a_"))] and not [t for t in v.text_area if t.key and t.key.startswith("rel_o_")]
        assert "rel_gerar" not in [b.key for b in v.button]
        assert [t.label for t in v.tabs][:2] == ["Resultado", "Obras"]                                                                         # as abas do painel continuam normais


def test_observacao_por_aba_so_entra_no_pdf_se_escrita_e_com_aba_marcada(conn):
    _cenario_rico(conn)
    txt = "Rodapé do CLT: valores sujeitos a conferência.\nSegunda linha da observação."
    d = RDD.montar(conn, "2026-01", "2026-09", ["clt_cards", "res_dre"], PER.ANO, None, None, "", observacoes={"clt": txt, "pj": "não deve entrar (aba sem informação)", "res": "   "})
    assert {a["aba"]: a.get("obs") for a in d["abas"]} == {"res": None, "clt": txt}                                       # vazio ou aba nao marcada: nada
    sem = RDD.montar(conn, "2026-01", "2026-09", ["clt_cards"], PER.ANO, None, None, "")
    assert "obs" not in sem["abas"][0]
    longa = RDD.montar(conn, "2026-01", "2026-09", ["clt_cards"], PER.ANO, None, None, "", observacoes={"clt": "x" * 5000})["abas"][0]["obs"]
    assert len(longa) == RDD.OBS_MAX
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext indisponivel")
    t_com, t_sem = _texto(RD.gerar_pdf(d)), _texto(RD.gerar_pdf(sem))
    assert "OBSERVAÇÃO" in t_com and "Rodapé do CLT: valores sujeitos a conferência." in t_com and "Segunda linha da observação." in t_com
    assert "não deve entrar" not in t_com and "OBSERVAÇÃO" not in t_sem                                               # sem texto, o relatorio continua igual


def test_observacao_muito_longa_quebra_de_pagina_sem_perder_texto(conn):
    _cenario_rico(conn)
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext indisponivel")
    linhas = "\n".join(f"Linha {i:03d} da observação longa." for i in range(1, 56))
    t = _texto(RD.gerar_pdf(RDD.montar(conn, "2026-01", "2026-09", ["res_dre"], PER.ANO, None, None, "", observacoes={"res": linhas})))
    assert "Linha 001 da observação longa." in t and "Linha 055 da observação longa." in t


def test_observacao_na_tela_muda_a_assinatura_e_vai_para_o_pdf(conn):
    _cenario_rico(conn)
    with patch("conexao.get_conn", return_value=conn):
        at = _painel(conn).run()
        at.radio(key="rel_modelo").set_value("Só CLT").run()
        at.button(key="rel_gerar").click().run()
        assert any("Relatório pronto" in s.value for s in at.success)
        at.text_area(key="rel_o_clt").set_value("Observação da Suellen para o CLT").run()
        assert not any("Relatório pronto" in s.value for s in at.success) and any("mudou desde o último relatório" in i.value for i in at.info)
        at.text_area(key="rel_o_pj").set_value("aba PJ sem informação marcada").run()                                 # aba sem nada marcado: nao conta
        at.button(key="rel_gerar").click().run()
        assert not at.exception, at.exception
        assert any("Relatório pronto" in s.value for s in at.success)
        if shutil.which("pdftotext"):
            t = _texto(at.session_state["rel_pdf"]["bytes"])
            assert "Observação da Suellen para o CLT" in t and "aba PJ sem informação marcada" not in t


def test_relatorio_sem_nan_sem_hifen_de_sinal_e_previsto_so_quando_cobre_o_periodo(conn):
    _cenario_rico(conn)
    d = RDD.montar(conn, "2026-01", "2026-09", RDD.TODAS_CHAVES, PER.ANO, None, None, "")
    cru = str([(b["key"], b["els"]) for a in d["abas"] for b in a["blocos"]])
    import re
    assert not re.search(r"\bnan%?\b", cru, flags=re.I), "nan no relatorio"
    assert "'-R$" not in cru and "'+-" not in cru                                                                       # sinal sempre "−" (nunca hifen ASCII)
    R = RDD._regs_obras(RDD.Base(conn, "2026-01", "2026-09", PER.ANO, None, None))
    if R["proj"] and R["n_proj"] < R["n_ob"]:                                                                         # projecao so' em parte dos meses: sem previsto/desvio enganosos
        assert not R["prev_ok"] and all(r["BDI previsto"] is None for r in R["regs"])
        assert any("Previsto e desvio de BDI não aparecem" in t for t in _notas(d))
    assert _notas(d).count([t for t in _notas(d) if t.startswith("Soma de ")][0]) == 1                                  # a nota do periodo de Obras aparece uma vez so'


def test_colunas_numericas_nunca_sao_cortadas_e_titulo_nao_fica_solto():
    from reportlab.pdfbase import pdfmetrics
    R_ = RD._Doc
    head = ["Nome", "Valor", "Total"]
    rows = [("norm", ["Fulano de Tal", "2.370.612", "9.999.999"]), ("tot", ["Total · 3 linhas", "12.345.678", "−9.412.001"])]
    larg, fs = R_._larguras(head, rows, [6, 0.5, 0.5], ["l", "r", "r"], 6.9)
    assert abs(sum(larg) - RD.CW) < 0.5
    for j in (1, 2):
        for tipo, cel in rows:
            assert pdfmetrics.stringWidth(cel[j], "PB" if tipo == "tot" else "P", fs + (0.2 if tipo == "tot" else 0)) + 10 <= larg[j] + 0.01, (j, cel[j])
    assert R_._h_min({"t": "barras", "h": 100}) >= 146 and R_._h_min({"t": "kpis", "itens": []}) >= 66


def test_texto_longo_quebra_em_linhas_sem_cortar_e_pagina_pode_quebrar_por_informacao(conn):
    import re
    _cenario_rico(conn)
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext indisponivel")
    d = RDD.montar(conn, "2026-01", "2026-09", ["ob_tabela"], PER.ANO, None, None, "")
    nome = "PARQUE SOLAR ALFA COM NOME BEM LONGO DE TESTE DA TABELA"
    tb = _tabelas(_bloco(d, "ob_tabela"))[0]
    tb["rows"][0][1][1] = nome.strip()
    t = _texto(RD.gerar_pdf(d))
    assert all(p in t for p in ("PARQUE", "ALFA", "LONGO", "TESTE", "TABELA")) and "TABELA…" not in t                    # o texto foi para a linha de baixo, inteiro (nada de reticencias)
    d1 = RDD.montar(conn, "2026-01", "2026-09", ["res_formula", "res_receita", "res_dre", "adm_kpis"], PER.ANO, None, None, "")
    d2 = RDD.montar(conn, "2026-01", "2026-09", ["res_formula", "res_receita", "res_dre", "adm_kpis"], PER.ANO, None, None, "", quebra_pagina=True)
    assert d1["meta"]["quebra_pagina"] is False and d2["meta"]["quebra_pagina"] is True
    assert _texto(RD.gerar_pdf(d2)).count("\f") > _texto(RD.gerar_pdf(d1)).count("\f")                              # com quebra, cada informacao abre pagina nova


def test_adm_grupos_com_totalizadoras_em_destaque_e_desvio_em_mil(conn):
    _cenario_rico(conn)
    d = RDD.montar(conn, "2026-01", "2026-09", ["adm_grupos", "adm_serie", "adm_unidades"], PER.ANO, None, None, "")
    tb = _tabelas(_bloco(d, "adm_grupos"))[0]
    tipos = [r[0] for r in tb["rows"]]
    assert tipos[-1] == "tot" and tb["rows"][-1][1][1] == "Total das despesas ADM"
    for tipo, cel in tb["rows"][:-1]:
        assert tipo == ("sub" if cel[0].count(".") <= 1 else "norm"), cel[0]                                          # grupo de 1o nivel em destaque, como na DRE
    ch = [e for e in _bloco(d, "adm_serie")["els"] if e.get("t") == "barras"]
    assert ch and ch[0]["fmt"] == "mil" and ch[0]["unidade"] == "R$ mil" and "R$ mil" in ch[0]["titulo"]
