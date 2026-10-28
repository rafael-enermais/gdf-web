# -*- coding: utf-8 -*-
"""Regra unica de fonte do DRE (v0.37.0): confirmado > PDF importado (sem confirmacao) > API do Sienge (padrao). A tabela de obras segue a mesma fonte.
Caso real de out/2026: a contabilidade marcou tudo como API, mas o painel da Diretoria continuava lendo o PDF antigo."""
import hashlib

import pytest

import painel_db as P
from dados_sienge import income
from test_painel_db_pg import _ingerir, _pdf_lido

pytestmark = pytest.mark.pg
MES = "2026-09"


@pytest.fixture()
def base(conn):
    """Set/26 com a API carregada (pagar + receber) e um PDF de DRE importado (os dois caem em valores diferentes de custo)."""
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    b, dre = _pdf_lido()
    P.gravar_dre(conn, dre, "dre.pdf", hashlib.sha256(b).hexdigest(), "teste@x")
    return conn


def _confirmar(conn, fonte_por_linha: dict):
    """Grava uma confirmacao com a fonte indicada por linha (valores vindos da fonte), como a tela faz."""
    from dre_mapa import LINHAS
    api = P.dre_do_mes(P.contas_api_padrao(conn, MES))["valores"]
    imp = P.dre_importacao_ativa(conn, MES)
    pdf = P.dre_do_mes([{"plano_cod": c, "plano_nome": "", "valor": x} for c, x in P.dre_contas_importadas(conn, imp["id"]).items()])["valores"]
    folhas = [k for k, _, t in LINHAS if t == "folha"]
    fontes = {k: fonte_por_linha.get(k, fonte_por_linha.get("*", "API")) for k in folhas}
    valores = {k: (api if f == "API" else pdf)[k] for k, f in fontes.items()}
    P.gravar_confirmacao(conn, MES, fontes, valores, "teste@x", None, None, imp["id"])


def test_api_e_pdf_do_teste_realmente_diferem(base):
    api = P.dre_do_mes(P.contas_api_padrao(base, MES))["valores"]
    imp = P.dre_importacao_ativa(base, MES)
    pdf = P.dre_do_mes([{"plano_cod": c, "plano_nome": "", "valor": x} for c, x in P.dre_contas_importadas(base, imp["id"]).items()])["valores"]
    assert abs(api["04"] - pdf["04"]) > 0.01                       # sem isso os testes abaixo nao provariam nada


def test_pdf_sem_confirmacao_nao_entra_no_fluxo_so_a_api(base):
    """v0.39.0: o PDF virou opcional (conferencia). Importado e sem confirmacao, o mes segue pela API em tudo."""
    api = P.dre_do_mes(P.contas_api_padrao(base, MES))["valores"]
    r = P.dre_resolvido(base, MES)
    assert r["fonte"] == "api" and P.fonte_obras(base, MES) == "API"
    t = P.termos_do_mes(base, MES)
    assert t["fonte"] == "api" and t["cus"] == abs(api["04"]) and t["rec"] == api["01"]
    assert P.obras_do_mes(base, MES)["fonte"] == "API"


def test_pdf_so_vale_em_mes_anterior_a_api(base, monkeypatch):
    """Antes da rotina de emissao da API a base so' tem residuos: ali o PDF importado (se houver) e' a unica fonte."""
    monkeypatch.setattr(P, "cobertura_emissao_ini", lambda conn: "2026-10")
    r = P.dre_resolvido(base, MES)
    assert r["fonte"] == "pdf" and P.fonte_obras(base, MES) == "PDF" and P.obras_do_mes(base, MES)["fonte"] == "PDF"
    assert P.dre_resolvido(base, "2026-07") is None                   # sem PDF e sem API nesse mes: sem dado


def test_confirmacao_em_api_manda_no_custo_da_diretoria_apesar_do_pdf(base):
    _confirmar(base, {"*": "API"})
    api = P.dre_do_mes(P.contas_api_padrao(base, MES))["valores"]
    pdf_cus = abs(P.obras_do_dre(base, MES)["total"]["custo"])
    t = P.termos_do_mes(base, MES)
    assert t["fonte"] == "confirmado"
    assert t["cus"] == abs(api["04"]) and t["cus"] != pdf_cus       # o bug de out/2026: antes saia o custo do PDF
    assert t["rec"] == api["01"] and t["bdi"] == round(api["01"] - abs(api["04"]), 2)
    assert P.fonte_obras(base, MES) == "API"
    ob = P.obras_do_mes(base, MES)
    assert ob["fonte"] == "API" and ob["total"]["custo"] == pytest.approx(api["04"], abs=0.01)


def test_confirmacao_em_pdf_mantem_o_pdf(base):
    _confirmar(base, {"*": "PDF"})
    t = P.termos_do_mes(base, MES)
    assert t["fonte"] == "confirmado" and t["cus"] == abs(P.obras_do_dre(base, MES)["total"]["custo"])
    assert P.fonte_obras(base, MES) == "PDF" and P.obras_do_mes(base, MES)["fonte"] == "PDF"


def test_confirmacao_mista_com_custos_em_pdf_usa_obras_do_pdf(base):
    _confirmar(base, {"*": "API", "04.01": "PDF", "04.02": "PDF", "04.03": "PDF", "04.04": "PDF"})
    assert P.fonte_obras(base, MES) == "PDF"                       # so' custos 04.* em PDF decidem a tabela por obra
    _confirmar(base, {"*": "PDF", "04.01": "API"})
    assert P.fonte_obras(base, MES) == "API"                       # um custo em API ja basta para a tabela vir da API


def test_mes_novo_sem_pdf_nem_confirmacao_usa_a_api(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    r = P.dre_resolvido(conn, MES)
    assert r["fonte"] == "api" and "API" in r["origem"]
    t = P.termos_do_mes(conn, MES)
    assert t and t["fonte"] == "api" and t["cus"] > 0 and P.fonte_obras(conn, MES) == "API"
    assert MES in P.meses_com_obras(conn)


def test_mes_sem_dado_nenhum_devolve_none(conn):
    _ingerir(conn, lado="P", tipo="I")
    _ingerir(conn, regs=income(), lado="R", tipo="I")
    assert P.dre_resolvido(conn, "2027-03") is None and P.termos_do_mes(conn, "2027-03") is None


def test_confirmacao_em_api_acompanha_o_dado_atual_e_pdf_fica_congelado(base):
    """v0.50.0: a confirmacao guarda a FONTE por linha; linhas em API seguem o Sienge de hoje (senao o Resultado fica velho e difere da aba Obras); PDF fica como gravado."""
    from dados_sienge import _c, _pg, outcome
    from dre_mapa import MAPA
    lin = MAPA["2.01.01.04"]                                                      # linha do DRE onde o titulo novo cai
    _confirmar(base, {"*": "API"})
    antes = P.termos_do_mes(base, MES)
    gravado = P.confirmacao_ativa(base, MES, ao_vivo=False)["valores"]
    novo = {"billId": 90, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "NFS ", "forecastDocument": "N",
            "creditorId": 77, "creditorName": "FORNECEDOR TESTE", "issueDate": "2026-09-10", "dueDate": "2026-09-30", "originalAmount": 5000.0,
            "payments": [_pg(1, "2026-09-30", 5000.0)], "paymentsCategories": [_c("2010104", "Material de Consumo | Obra", 100, 1049)]}
    _ingerir(base, regs=outcome() + [novo], lado="P", tipo="I")                    # o Sienge mudou depois da confirmacao
    vivo = P.dre_do_mes(P.contas_api_padrao(base, MES))["valores"]
    assert vivo[lin] != gravado[lin]                                               # o dado atual mudou
    c = P.confirmacao_ativa(base, MES)
    assert c["valores"][lin] == vivo[lin] and c["valores_gravados"][lin] == gravado[lin] and lin in c["ao_vivo"]
    t = P.termos_do_mes(base, MES)
    assert t["fonte"] == "confirmado" and t["cus"] == abs(vivo["04"]) and t["cus"] > antes["cus"]
    assert t["cus"] == pytest.approx(abs(P.obras_do_mes(base, MES)["total"]["custo"]), abs=0.01)         # Resultado fecha com a aba Obras
    assert P.confirmacao_ativa(base, MES, ao_vivo=False)["valores"][lin] == gravado[lin]               # o que foi gravado nao muda
    _confirmar(base, {"*": "API", lin: "PDF"})                                                          # uma linha em PDF: continua congelada
    c2 = P.confirmacao_ativa(base, MES)
    assert lin not in c2["ao_vivo"] and c2["valores"][lin] == P.confirmacao_ativa(base, MES, ao_vivo=False)["valores"][lin]
