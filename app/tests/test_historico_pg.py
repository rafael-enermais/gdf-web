# -*- coding: utf-8 -*-
"""Historico do painel da contabilidade (HTML/JSON): leitura e conferencia, gravacao como importacao ativa, e uso na tela da Diretoria e no PDF. Dados sinteticos."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import acesso
import historico as H
import painel_db as P
import relatorio_painel_pdf as RPP

APP = Path(__file__).resolve().parent.parent


def _d():
    return {
        "res": {"set": {"rec": [100.0, 90.0], "cus": [60.0, 80.0], "bdi": [40.0, 10.0], "adm": [20.0, 25.0], "res": [20.0, -15.0]},
                "acc": {"rec": 900.0, "cus": 700.0, "bdi": 200.0, "adm": 150.0, "res": 50.0},
                "accdev": {"rec": -100.0, "cus": -20.0, "bdi": -80.0, "adm": 10.0, "res": -90.0}},
        "dev": {"meses": ["Fev", "Mar", "Abr"], "rows": {"Base-line (Receita)": [-10.0, 5.0, -20.0], "Custos": [-1.0, 2.0, 3.0], "BDI - Resultado": [-9.0, 3.0, -23.0],
                                                           "Despesas ADM": [1.0, 1.0, 1.0], "Lucro do Período": [-10.0, 2.0, -24.0]}},
        "recomp": [["Out", 1000.0, 1300.0], ["Nov", 900.0, 1170.0]],
        "he": {"he": [10.0, 20.0, 30.0], "sal": [100.0, 100.0, 100.0]},
        "hc": {"hist": [10, 11, 12]},
        "pess": [["Horas Extras", 30.0, 60.0], ["Hospedagem", 20.0, 40.0]],
        "obras": [], "pdet": {"X": {"cred": {"rows": [["FULANO DE TAL", 1, 2]]}}}, "admdet": {}, "hcob": {},
    }


def _html():
    return ("<html><script>const D=" + json.dumps(_d(), ensure_ascii=False) + ";\nconst M9=['Jan'];</script></html>").encode("utf-8")


def test_ler_html_e_json_confere_e_descarta_nomes():
    for conteudo in (_html(), json.dumps({"_origem": "x", "D": _d()}).encode(), json.dumps(_d()).encode()):
        lido = H.ler_historico(conteudo, "painel.html")
        assert lido["meses"] == ["Fev", "Mar", "Abr"] and lido["avisos"] == []
        assert "pdet" not in lido["dados"] and "FULANO" not in json.dumps(lido["dados"])        # nomes de pessoas ficam de fora
    r = H.resumo({"mes": "2026-04", "dados": H.ler_historico(_html())["dados"]})
    assert r["acumulado"]["res"] == 50.0 and r["mes_ref"]["rec"] == 90.0
    assert [m["rotulo"] for m in r["desvio_meses"]] == ["Jan", "Fev", "Mar", "Abr"]
    assert r["desvio_linhas"]["Base-line (Receita)"][0] == pytest.approx(-100.0 - (-10.0 + 5.0 - 20.0))      # janeiro = acumulado - soma de fev em diante
    assert r["serie_he"][-1] == {"mes": "2026-03", "he": 30.0, "base": 100.0, "pct": 0.3}
    assert r["recomposicao"][0] == {"rotulo": "Out", "projecao": 1000.0, "para_cobrir": 1300.0}


def test_ler_avisa_conta_que_nao_fecha_e_recusa_arquivo_errado():
    d = _d()
    d["res"]["acc"]["bdi"] = 999.0
    assert any("não fecha" in a for a in H.ler_historico(json.dumps(d).encode())["avisos"])
    with pytest.raises(H.ErroHistorico):
        H.ler_historico(b"<html>nada aqui</html>")
    with pytest.raises(H.ErroHistorico):
        H.ler_historico(b'{"res": {}}')


def test_gravar_ativo_e_substituicao_no_mesmo_mes(conn):
    assert H.ativo(conn) is None
    l1 = H.ler_historico(_html(), "a.html")
    r1 = H.gravar(conn, l1, "2026-09", "a.html", "rafael@x")
    assert not r1["repetido"]
    assert H.gravar(conn, l1, "2026-09", "a.html", "rafael@x")["repetido"]                 # mesmo arquivo: nao grava de novo
    d2 = _d()
    d2["res"]["acc"]["rec"] = 901.0
    r2 = H.gravar(conn, H.ler_historico(json.dumps(d2).encode(), "b.json"), "2026-09", "b.json", "rafael@x")
    h = H.ativo(conn)
    assert h["id"] == r2["id"] and h["mes"] == "2026-09" and h["dados"]["res"]["acc"]["rec"] == 901.0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pnl_importacao WHERE tipo='HISTORICO' AND ativo")
        assert cur.fetchone()[0] == 1                                                       # a anterior ficou fora de uso, nada apagado
    assert any(i["tipo"] == "HISTORICO" for i in P.importacoes_lista(conn))


def test_serie_he_combinada_app_vale_onde_existe():
    res = {"serie_he": [{"mes": "2026-01", "pct": 0.1}, {"mes": "2026-02", "pct": 0.2}]}
    out = H.serie_he_combinada(res, [{"mes": "2026-02", "he_pct": 0.25}, {"mes": "2026-03", "he_pct": 0.3}])
    assert [(x["mes"], x["he_pct"], x["origem"]) for x in out] == [("2026-01", 0.1, "historico"), ("2026-02", 0.25, "app"), ("2026-03", 0.3, "app")]


def test_pdf_e_diretoria_usam_o_historico(conn):
    import hashlib
    import streamlit as st
    from dados_sienge import income
    from test_painel_db_pg import _ingerir, _pdf_lido
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    H.gravar(conn, H.ler_historico(_html(), "a.html"), "2026-09", "a.html", "rafael@x")
    ctx = RPP.montar_ctx(conn, "2026-09", "agora")
    assert ctx["hist"]["acumulado"]["rec"] == 900.0
    pdf = RPP.gerar_pdf_painel(ctx, gerado_em="agora")
    assert pdf[:4] == b"%PDF"
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    st.cache_data.clear()
    with patch("conexao.get_conn", return_value=conn):
        at = AppTest.from_file(str(APP / "app.py"), default_timeout=60)
        at.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="diretor@empresa.com"))
        at.run()
        assert not at.exception, at.exception
        assert not any("O acumulado do ano aparece quando" in i.value for i in at.info)
        assert not any("O acumulado do ano aparece quando" in i.value for i in at.info)
        rec_acc = next(m for m in at.metric if m.label == "Receita (base-line)")
        assert rec_acc.value == "R$ 2 mil"                                                     # realizado do ano = soma jan-set pela API (so' set/26 tem dado no teste), nao o historico (R$ 900)
        assert any("Conferência: histórico" in e.label for e in at.expander)               # tabela app x historico da contabilidade
        at.selectbox(key="dir_ano_linha").select("Custos").run()                            # escolher outra linha do desvio nao quebra
        assert not at.exception, at.exception
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pnl_regra WHERE tipo='EXCLUI_PREVISAO'")


def test_resumo_mantem_a_ordem_das_linhas_do_painel_apos_gravar_no_banco(conn):
    """O jsonb do banco reordena as chaves (por tamanho); o resumo precisa devolver Receita, Custos, BDI, ADM, Lucro."""
    d = _d()
    d["dev"]["rows"] = {"Base-line (Receita)": [1.0], "Custos": [2.0], "BDI - Resultado": [3.0], "Despesas ADM": [4.0], "Lucro do Período": [5.0]}
    d["dev"]["meses"] = ["Fev"]
    H.gravar(conn, H.ler_historico(json.dumps(d).encode(), "o.json"), "2026-09", "o.json", "rafael@x")
    r = H.resumo(H.ativo(conn))
    assert list(r["desvio_linhas"]) == ["Base-line (Receita)", "Custos", "BDI - Resultado", "Despesas ADM", "Lucro do Período"]
