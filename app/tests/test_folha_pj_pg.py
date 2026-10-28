# -*- coding: utf-8 -*-
"""Painel Folha PJ contra Postgres descartavel: leitura do Sienge (pago / a pagar), cadastros (SQL-40) e cargas de planilha. Dados 100% SINTETICOS."""
import io

import openpyxl
import pytest

import folha_pj_dados as FP
import importador_folha_pj as IP
import painel_db as P
from dados_sienge import _c, _pg
from test_painel_db_pg import _ingerir

pytestmark = pytest.mark.pg
MES = "2026-10"
SEGREDO = "segredo-de-teste"


def _t(bill, cred, nome, venc, valor, pagos, cats, emp=1, prev="N", desconto=None, doc="NFS ", num=None):
    r = {"billId": bill, "installmentId": 1, "companyId": emp, "companyName": FP.EMPRESAS[emp], "originId": "CP", "documentIdentificationId": doc,
         "forecastDocument": prev, "documentNumber": num or str(bill), "creditorId": cred, "creditorName": nome, "issueDate": "2026-10-01", "dueDate": venc,
         "originalAmount": valor, "payments": pagos, "paymentsCategories": cats}
    if desconto is not None:
        r["discountAmount"] = desconto
    return r


def _regs():
    sal = lambda cc=1005, nome="EE - ANASTACIO", p=100: _c("2010201", "Salários PJ | Obra", p, cc, nome)           # noqa: E731
    pre = lambda cc=1005, nome="EE - ANASTACIO", p=100: _c("2010211", "Premiações | Obra", p, cc, nome)            # noqa: E731
    mul = _c("2020119", "Multas Contratuais PJ | ADM", 100, 1, "EE - SEDE / ADM CENTRAL")
    return [
        _t(1, 501, "11.111.111 JOAO TESTE", "2026-10-05", 10000.0, [_pg(1, "2026-10-07", 10000.0)], [sal()]),                          # pago integral
        _t(2, 501, "11.111.111 JOAO TESTE", "2026-10-30", 2000.0, [], [sal()], desconto=50.0),                                         # a pagar do mesmo credor -> Parcial
        _t(3, 502, "22.222.222 MARIA TESTE", "2026-10-08", 4000.0, [_pg(1, "2026-10-09", 4000.0)], [sal(1005, "EE - ANASTACIO", 50), sal(1006, "EE - NOVA ERA", 50)]),   # dois centros
        _t(4, 503, "33.333.333 DIRETOR UM", "2026-10-09", 30000.0, [_pg(1, "2026-10-10", 30000.0)], [pre()]),                        # diretoria
        _t(5, 504, "44.444.444 FORNECEDOR", "2026-10-20", 777.0, [_pg(1, "2026-10-21", 777.0, 8, "Abatimento de Adiantamento")], [sal()]),   # abatimento sem adiantamento: sai
        _t(6, 505, "55.555.555 SUBSTITUIDO", "2026-10-12", 999.0, [_pg(1, "2026-10-12", 999.0, 5, "Substituição")], [sal()]),         # substituicao nao conta
        _t(7, 506, "66.666.666 MULTADO", "2026-10-25", 16210.0, [], [mul]),                                                            # multa a pagar
        _t(8, 507, "77.777.777 PREVISTO", "2026-10-28", 1234.0, [], [sal()], prev="S"),                                                 # previsao: nao entra
        _t(9, 508, "88.888.888 FORA DO MES", "2026-11-05", 555.0, [], [sal()]),                                                         # vence em novembro: nao entra
        _t(10, 509, "99.999.999 OUTRA CONTA", "2026-10-06", 321.0, [_pg(1, "2026-10-06", 321.0)], [_c("2010104", "Material | Obra", 100)]),   # nao e' conta PJ
    ]


@pytest.fixture()
def base(conn):
    _ingerir(conn, regs=_regs(), lado="P", tipo="I", mes=MES)
    return conn


def _por_cred(r, cred):
    return next(p for p in r["pessoas"] if p["cred_id"] == cred)


def test_painel_le_o_sienge_do_banco(base):
    assert FP.instalado(base)
    r = FP.dados_do_mes(base, MES)
    assert {p["cred_id"] for p in r["pessoas"]} == {501, 502, 503, 506}                  # 504 (abatimento), 505 (substituicao), 507 (previsao), 508 (nov) e 509 (outra conta) fora
    j = _por_cred(r, 501)
    assert j["honorarios"] == 12000.0 and j["pago"] == 10000.0 and j["situacao"] == "Parcial"
    assert j["desconto"] == -50.0 and j["a_pagar"] == 1950.0 and j["custo_total"] == 11950.0       # desconto do titulo (SQL-40) em aberto, liquido no a pagar
    assert j["nome"] == "Joao Teste" and j["centro"].startswith("1005")
    m = _por_cred(r, 502)
    assert m["centro"] == "ENERMAIS ENERGIA - OBRAS" and m["obra"] == FP.VARIOS and m["honorarios"] == 4000.0
    assert _por_cred(r, 506)["multa"] == 16210.0 and _por_cred(r, 506)["situacao"] == "A pagar"
    assert [f["lancamento"] for f in r["fora"]] == ["5/1"]
    t = r["totais"]
    assert t["custo_total"] == pytest.approx(t["honorarios"] + t["premiacao"] + t["multa"] + t["desconto"], abs=0.01)
    assert t["pago"] + t["a_pagar"] == pytest.approx(t["custo_total"], abs=0.01)
    assert len(r["documentos"]) == 5 and r["sem_flash"] and r["sem_diretoria"] and r["sem_mapa"]


def test_sem_o_sql_40_o_painel_ainda_funciona(base):
    """Antes de rodar o SQL-40 (sem desconto_titulo) o painel abre com desconto zero em vez de quebrar."""
    with base.cursor() as cur:
        cur.execute("ALTER TABLE pnl_titulo DROP COLUMN desconto_titulo")
    try:
        r = FP.dados_do_mes(base, MES)
        assert _por_cred(r, 501)["desconto"] == 0.0 and _por_cred(r, 501)["a_pagar"] == 2000.0
    finally:
        with base.cursor() as cur:
            cur.execute("ALTER TABLE pnl_titulo ADD COLUMN desconto_titulo numeric(18,2)")


def test_diretoria_cadastrada_vai_para_uma_linha_e_soma_na_empresa(base):
    IP.diretoria_adicionar(base, 503, "Diretor Um", "teste@x")
    assert [d["credor_id"] for d in IP.diretoria_listar(base)] == [503]
    r = FP.dados_do_mes(base, MES)
    assert not r["sem_diretoria"] and _por_cred(r, 503)["centro"] == FP.DIRETORIA and _por_cred(r, 503)["diretoria"]
    card = next(c for c in r["cards"] if c["emp_id"] == 1)
    assert card["diretoria"]["premiacao"] == 30000.0 and card["total"]["custo_total"] == pytest.approx(r["totais"]["custo_total"])
    IP.diretoria_remover(base, 503, "teste@x")
    assert IP.diretoria_listar(base) == [] and not _por_cred(FP.dados_do_mes(base, MES), 503)["diretoria"]


# ------------------------------------------------------------------ planilhas sinteticas
def _xlsx(abas: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for l in linhas:
            ws.append(l)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


CAB_MAPA = ["Nome", "CPF", "Cód. credor Sienge", "Função", "Centro de custo", "Empresa", "Vínculo", "Admissão"]


def _mapa_xlsx():
    return _xlsx({"09-2026": [["titulo qualquer"], [], CAB_MAPA, ["Antiga Silva", "000.000.000-00", 999, "X", "1 - SEDE", "ENERMAIS ENERGIA LTDA", "PJ", None]],
                  "10-2026": [["Folha de outubro"], [], CAB_MAPA,
                              ["Joao Teste", "529.982.247-25", 501, "Engenheiro", "1005 - EE - ANASTACIO", "ENERMAIS ENERGIA LTDA", "PJ", None],
                              ["Maria Teste", "111.444.777-35", 502, "Técnica", "1005 - EE - ANASTACIO", "ENERMAIS ENERGIA LTDA", "PJ", None],
                              ["Clt Pessoa", "390.533.447-05", 700, "Analista", "1 - SEDE", "ENERMAIS ENERGIA LTDA", "CLT", None],
                              ["Sem Codigo", "276.241.660-32", None, "Analista", "1 - SEDE", "ENERMAIS ENERGIA LTDA", "PJ", None],
                              ["Joao Teste", "529.982.247-25", 501, None, "1006 - EE - NOVA ERA", "ENERMAIS ENERGIA LTDA", "PJ", None]]})      # mesmo credor em outra linha


def _flash_xlsx(linhas):
    return _xlsx({"Planilha1": [["relatorio"], ["Nome completo", "CPF", "Premiação no cartão", "Refeição", "Flexível"]] + linhas})


def test_mapa_le_aba_do_mes_e_nao_guarda_cpf(base):
    m = IP.ler_mapa_colaboradores(_mapa_xlsx(), SEGREDO)
    assert m["aba"] == "10-2026" and [l["credor_id"] for l in m["linhas"]] == [501, 502]
    assert all(l["cpf_hash"] and len(l["cpf_hash"]) == 64 and "52998224725" not in l["cpf_hash"] for l in m["linhas"])
    assert any("não são PJ" in a for a in m["avisos"]) and any("sem código" in a for a in m["avisos"]) and any("repetiam" in a for a in m["avisos"])
    cont = IP.gravar_colaboradores(base, m["linhas"], MES, "teste@x", novos=True)
    assert cont == {"novos": 2, "atualizados": 0}
    assert IP.gravar_colaboradores(base, m["linhas"], MES, "teste@x")["atualizados"] == 2
    with base.cursor() as cur:
        cur.execute("SELECT credor_id, funcao, centro_origem, novo_desde FROM pj_colaborador ORDER BY credor_id")
        assert [(r[0], r[1], r[2], str(r[3])) for r in cur.fetchall()] == [(501, "Engenheiro", "1005 - EE - ANASTACIO", "2026-10-01"), (502, "Técnica", "1005 - EE - ANASTACIO", "2026-10-01")]
        cur.execute("SELECT count(*) FROM pj_colaborador WHERE cpf_hash LIKE '%52998224725%'")
        assert cur.fetchone()[0] == 0
    r = FP.dados_do_mes(base, MES)
    assert not r["sem_mapa"] and _por_cred(r, 501)["funcao"] == "Engenheiro" and _por_cred(r, 501)["novo"] is True
    # outra aba escolhida
    assert [l["credor_id"] for l in IP.ler_mapa_colaboradores(_mapa_xlsx(), SEGREDO, aba="09-2026")["linhas"]] == [999]


def test_flash_cruza_por_cpf_e_por_nome_e_entra_no_painel(base):
    IP.gravar_colaboradores(base, IP.ler_mapa_colaboradores(_mapa_xlsx(), SEGREDO)["linhas"], MES, "teste@x")
    fl = IP.ler_flash(_flash_xlsx([["Joao Teste", "529.982.247-25", 3000, 650, 0],            # casa por CPF
                                   ["MARIA  TESTE", None, 0, 750, 0],                          # sem CPF: casa pelo nome
                                   ["Desconhecido Silva", "000.000.000-00", 100, 100, 0],      # nao e' PJ do mapa
                                   ["Joao Teste", "529.982.247-25", 100, 0, 0]]), SEGREDO)     # a mesma pessoa em 2 linhas soma
    assert fl["total_premiacao"] == 3000.0 + 100.0 + 100.0
    assert fl["total_alimentacao"] == 650.0 + 750.0 + 100.0
    cruz = IP.cruzar_flash(fl["linhas"], IP.colaboradores_cadastrados(base), IP.fantasias_dos(base, [501, 502]))
    assert cruz["sem_pj"] == 1 and cruz["ambiguas"] == 0 and {c["credor_id"]: c["via"] for c in cruz["casadas"]} == {501: "CPF", 502: "nome"}
    res = IP.gravar_flash(base, MES, "ENERMAIS ENERGIA LTDA", cruz["casadas"], "teste@x")
    assert res == {"pessoas": 2, "premiacao": 3100.0, "alimentacao": 1400.0}
    r = FP.dados_do_mes(base, MES)
    j = _por_cred(r, 501)
    assert j["ajuda_custo"] == 3100.0 and j["alimentacao"] == 650.0 and j["custo_total"] == pytest.approx(12000 - 50 + 3100 + 650)
    assert _por_cred(r, 502)["alimentacao"] == 750.0 and not r["sem_flash"]
    # reimportar troca (nao soma): o antigo fica inativo
    IP.gravar_flash(base, MES, "ENERMAIS ENERGIA LTDA", [{"credor_id": 501, "premiacao": 10.0, "alimentacao": 20.0}], "teste@x")
    r2 = FP.dados_do_mes(base, MES)
    assert _por_cred(r2, 501)["ajuda_custo"] == 10.0 and _por_cred(r2, 502)["alimentacao"] == 0.0
    with base.cursor() as cur:
        cur.execute("SELECT count(*) FROM pj_flash WHERE NOT ativo")
        assert cur.fetchone()[0] == 1


def test_nome_ambiguo_nao_casa_e_planilha_protegida_e_recusada():
    colab = {1: {"cpf_hash": None, "chave": "ana souza"}, 2: {"cpf_hash": None, "chave": "ana souza"}}
    flash = [{"nome": "Ana Souza", "nome_chave": "ana souza", "cpf_hash": None, "premiacao": 10.0, "alimentacao": 0.0}]
    c = IP.cruzar_flash(flash, colab)
    assert c["casadas"] == [] and c["ambiguas"] == 1
    with pytest.raises(IP.ErroFolhaPJ, match="senha"):
        IP.ler_flash(IP.ASSINATURA_OLE + b"0" * 100, SEGREDO)
    with pytest.raises(IP.ErroFolhaPJ):
        IP.ler_mapa_colaboradores(_xlsx({"A": [["x", "y"], [1, 2]]}), SEGREDO)
    with pytest.raises(IP.ErroFolhaPJ, match="NOME COMPLETO"):
        IP.ler_flash(_xlsx({"A": [["x", "y"], [1, 2]]}), SEGREDO)


def test_ingestao_grava_desconto_do_titulo(base):
    with base.cursor() as cur:
        cur.execute("SELECT desconto_titulo FROM pnl_titulo WHERE lado='P' AND bill_id=2")
        assert float(cur.fetchone()[0]) == 50.0
        cur.execute("SELECT desconto_titulo FROM pnl_titulo WHERE lado='P' AND bill_id=1")
        assert cur.fetchone()[0] in (None, 0)


def test_detecta_o_tipo_do_arquivo_e_a_empresa_pelo_nome(base):
    """Envio unico: o app descobre se e' Flash, mapa ou 'Novos colaboradores' e a empresa do Flash (dados ficticios)."""
    fl = IP.detectar(_flash_xlsx([["Joao Teste", "529.982.247-25", 100, 50, 0]]), "FLASH  RENOVAVEIS.xlsx")
    assert fl["tipo"] == "flash" and fl["empresa"] == "ENERMAIS RENOVAVEIS LTDA"
    assert IP.detectar(_flash_xlsx([]), "Flash Out - Energia.xlsx")["empresa"] == "ENERMAIS ENERGIA LTDA"
    assert IP.detectar(_flash_xlsx([]), "FLASH SMG SOLUCOES.xlsx")["empresa"] == "SMG SOLUÇÕES LTDA"
    assert IP.detectar(_flash_xlsx([]), "FLASH SOLUCOES.xlsx")["empresa"] == "ENERMAIS SOLUCOES LTDA"
    assert IP.detectar(_flash_xlsx([]), "arquivo qualquer.xlsx")["empresa"] is None            # nome nao diz a empresa: a tela pede para escolher
    mp = IP.detectar(_mapa_xlsx(), "Mapa PJ.xlsx")
    assert mp["tipo"] == "mapa" and mp["aba"] == "10-2026" and mp["abas"] == ["09-2026", "10-2026"]
    nv = IP.detectar(_mapa_xlsx(), "Novos colaboradores PJ - 102026.xlsx")
    assert nv["tipo"] == "novos"
    assert IP.detectar(_xlsx({"X": [["a", "b"], [1, 2]]}), "outra.xlsx")["tipo"] == "desconhecido"


def test_resumo_salvo_mostra_o_que_foi_gravado(base):
    assert IP.resumo_salvo(base) == {"colaboradores": 0, "quando": None, "flash": []}
    m = IP.ler_mapa_colaboradores(_mapa_xlsx(), SEGREDO)
    IP.gravar_colaboradores(base, m["linhas"], MES, "teste@x")
    IP.gravar_flash(base, MES, "ENERMAIS ENERGIA LTDA", [{"credor_id": 501, "premiacao": 100.0, "alimentacao": 50.0}], "teste@x")
    r = IP.resumo_salvo(base)
    assert r["colaboradores"] == 2 and r["quando"] is not None
    assert [(x["mes"], x["empresa"], x["pessoas"], x["premiacao"], x["alimentacao"]) for x in r["flash"]] == [(MES, "ENERMAIS ENERGIA LTDA", 1, 100.0, 50.0)]


def test_nome_escrito_diferente_casa_so_se_for_seguro():
    """Flash com nome abreviado/erro de digitacao casa com UM colaborador; sobrenome repetido nao junta pessoas diferentes (nomes ficticios)."""
    c = FP.chave_nome
    sim = [("Pedro Alvarenga", "PEDRO LUIZ ALVARENGA"), ("Ana Beatriz F. Souza", "ANA BEATRIZ FONSECA DA SOUZA"), ("MARCELO ALISON LIMA", "MARCELO ALISSON LIMA"),
           ("Joaquim Yuri Pinto", "JOAQUIM YURY PINTO"), ("Carla Midori Tanaka Kabawata", "Carla Midori Tanaka Kawabata"), ("Helena Prado", "HELENA PRADO DO NASCIMENTO")]
    nao = [("Jorge Joao da Silva", "Jorge Faria da Silva"), ("Edson Borges Rocha", "Edson Gregoris Rocha"), ("Mauro Martins dos Santos", "LUCAS MARTINS DOS SANTOS"), ("Joao", "Joao Silva")]
    assert all(IP.nome_aproximado(c(a), c(b)) for a, b in sim)
    assert not any(IP.nome_aproximado(c(a), c(b)) for a, b in nao)
    cad = {1: {"cpf_hash": None, "chave": c("PEDRO LUIZ ALVARENGA")}, 2: {"cpf_hash": None, "chave": c("Jorge Faria da Silva")}}
    flash = [{"nome": "Pedro Alvarenga", "nome_chave": c("Pedro Alvarenga"), "cpf_hash": None, "premiacao": 100.0, "alimentacao": 0.0},
             {"nome": "Jorge Joao da Silva", "nome_chave": c("Jorge Joao da Silva"), "cpf_hash": None, "premiacao": 0.0, "alimentacao": 650.0}]
    r = IP.cruzar_flash(flash, cad)
    assert [(x["credor_id"], x["via"]) for x in r["casadas"]] == [(1, "nome aproximado")] and r["sem_pj"] == 1
