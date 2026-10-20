# -*- coding: utf-8 -*-
"""Indicadores financeiros e financiamentos (indicadores_dados.py) contra Postgres descartavel, com dados SINTETICOS."""
import datetime as dt

import pytest

import indicadores_dados as I
import painel_db as P
import sienge_api as S
from dados_sienge import _c, _pg

pytestmark = pytest.mark.pg
HOJE = dt.date(2026, 10, 20)


def _tit(bill, inst, lado, contra, emissao, venc, valor, planos, baixas=(), previsao="N", numero="1"):
    base = {"billId": bill, "installmentId": inst, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "NF",
            "documentNumber": numero, "issueDate": emissao, "dueDate": venc, "originalAmount": valor}
    if lado == "P":
        base.update({"forecastDocument": previsao, "creditorId": hash(contra) % 1000, "creditorName": contra, "payments": list(baixas), "paymentsCategories": planos})
    else:
        base.update({"documentForecast": previsao, "clientId": hash(contra) % 1000, "clientName": contra, "receipts": list(baixas), "receiptsCategories": planos})
    return base


def _gravar(conn, lado, regs, mes="2026-01"):
    sid = P.criar_sync(conn, mes, lado, "P", "teste@x")
    cont = P.gravar_normalizado(conn, sid, S.normalizar_titulos(lado, regs))
    P.finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])


def _rec(plano, nome):
    return [_c(plano, nome, 100)]


@pytest.fixture()
def dados(conn):
    rec = lambda cod, nome: [{"financialCategoryId": cod, "financialCategoryName": nome, "financialCategoryRate": 100, "costCenterId": 1, "costCenterName": "CC"}]  # noqa: E731
    receber = [
        _tit(1, 1, "R", "CLIENTE A", "2026-09-01", "2026-09-30", 1000.0, rec("1010101", "Receita"), numero="NF-A"),                       # vencida, em aberto
        _tit(2, 1, "R", "CLIENTE B", "2026-09-10", "2026-10-30", 500.0, rec("1010101", "Receita"),
             baixas=[{"sequencialNumber": 1, "paymentDate": "2026-10-05", "netAmount": 500.0, "grossAmount": 500.0, "operationTypeId": 2}]),  # recebida
        _tit(3, 1, "R", "CLIENTE C", "2026-08-01", "2026-09-01", 900.0, rec("1010101", "Receita"), previsao="S"),                        # previsao: fora
        _tit(4, 1, "R", "CLIENTE D", "2026-09-05", "2026-12-15", 200.0, rec("1010101", "Receita")),                                      # a vencer
    ]
    pagar = [
        _tit(10, 1, "P", "FORN 1", "2026-09-01", "2026-09-11", 100.0, rec("2010104", "Material"),
             baixas=[_pg(1, "2026-09-11", 100.0)]),                                                                                       # prazo 10 dias, pago em setembro
        _tit(11, 1, "P", "FORN 2", "2026-09-01", "2026-09-21", 300.0, rec("2010104", "Material"), baixas=[_pg(1, "2026-09-21", 300.0)]),  # prazo 20 dias
        _tit(12, 1, "P", "FORN 3", "2026-08-01", "2026-09-15", 700.0, rec("2010104", "Material")),                                       # vencido e nao pago
    ]
    nome_p, nome_j = "Caminhão ABC1D23 - Fin. Traton Ct 38172", "Juros s/ Fin. Caminhão ABC1D23 - Ct 38172"
    for i, (venc, pago) in enumerate((("2026-10-01", True), ("2026-11-01", False), ("2026-12-01", False)), start=1):
        pagar.append(_tit(100, i, "P", "TRATON", "2026-01-10", venc, 1000.0, rec("2050101", nome_p), baixas=[_pg(1, venc, 1000.0)] if pago else [], numero="CT1"))
    for i, venc in enumerate(("2026-11-01", "2026-12-01"), start=1):
        pagar.append(_tit(101, i, "P", "TRATON", "2026-01-10", venc, 100.0, rec("2030201", nome_j), numero="CT1J"))
    pagar.append(_tit(102, 1, "P", "BANCO SANTANDER", "2026-03-10", "2027-03-10", 5000.0, rec("2030405", "Banco Santander S/A | Capital de Giro | Ct. 4455667")))
    pagar.append(_tit(103, 1, "P", "BANCO X", "2026-03-10", "2027-03-10", 777.0, rec("2030405", "Banco X | Capital de Giro | Ct. 9999"), previsao="S"))
    _gravar(conn, "R", receber)
    _gravar(conn, "P", pagar)


def test_prazo_medio_simples_e_ponderado(conn, dados):
    r = I.prazo_medio(conn, "P", "2026-09")
    assert r["n"] == 2 and r["simples"] == 15.0 and r["ponderado"] == 17.5      # (10+20)/2 ; (10*100+20*300)/400
    assert I.prazo_medio(conn, "R", "2026-09")["n"] == 3                         # A, B e D (a previsao C fica de fora)
    assert I.prazo_medio(conn, "R", "2026-01")["simples"] is None


def test_gasto_e_ciclo_financeiro(conn, dados):
    g = I.gasto_pago(conn, "2026-09", hoje=HOJE)
    assert g["mensal"] == 400.0 and g["dias"] == 30 and round(g["diario"], 2) == 13.33
    c = I.ciclo_e_capital(conn, "2026-09", hoje=HOJE)
    assert c["pmp"]["simples"] == 15.0 and c["pmr"]["simples"] is not None
    assert c["ciclo_simples"] == round(c["pmr"]["simples"] - 15.0, 1)
    assert c["ncg_simples"] == round(g["diario"] * max(c["ciclo_simples"], 0), 2)


def test_inadimplencia_ate_hoje_e_ate_fim_do_mes(conn, dados):
    v, p = I.data_posicao("2026-10", HOJE)
    assert (v, p) == (dt.date(2026, 10, 19), HOJE)
    ina = I.inadimplencia(conn, v, p)
    assert ina["receber"]["total"] == 1000.0 and ina["receber"]["n"] == 1             # so' CLIENTE A (B recebida, C previsao, D a vencer)
    assert ina["receber"]["top"][0]["nome"] == "CLIENTE A"
    assert ina["pagar"]["total"] == 700.0 and ina["pagar"]["n"] == 1                   # so' FORN 3 (as parcelas dos financiamentos ainda nao venceram)
    f = {x["faixa"]: x["valor"] for x in ina["receber"]["faixas"]}
    assert f["1 a 30 dias"] == 1000.0                                                 # venceu 30/09, hoje 20/10 -> 20 dias
    fim_set = I.inadimplencia(conn, *I.data_posicao("2026-09", HOJE, ate_hoje=False))
    assert fim_set["receber"]["total"] == 1000.0
    antes = I.inadimplencia(conn, dt.date(2026, 9, 29), dt.date(2026, 9, 29))
    assert antes["receber"]["total"] == 0.0                                          # ainda nao tinha vencido


def test_data_base_da_parcela_so_vale_depois_de_validada(conn, dados, monkeypatch):
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_titulo SET data_base_parcela = DATE '2026-08-01' WHERE lado='R' AND bill_id=4")   # prorrogado: o original ja venceu
    ina = I.inadimplencia(conn, dt.date(2026, 10, 19), HOJE)
    assert not ina["usa_vencimento_original"] and ina["receber"]["total"] == 1000.0       # padrao: ainda usa o vencimento atual
    monkeypatch.setattr(I, "USAR_DATA_BASE_COMO_ORIGINAL", True)
    ina = I.inadimplencia(conn, dt.date(2026, 10, 19), HOJE)
    assert ina["usa_vencimento_original"] and ina["receber"]["total"] == 1200.0


def test_rotina_guarda_a_data_base_da_parcela(conn):
    reg = _tit(7, 1, "R", "CLIENTE Z", "2026-09-01", "2026-10-30", 100.0, [_c("1010101", "Receita", 100)])
    reg["installmentBaseDate"] = "2026-09-30"
    _gravar(conn, "R", [reg])
    with conn.cursor() as cur:
        cur.execute("SELECT data_base_parcela FROM pnl_titulo WHERE bill_id=7")
        assert cur.fetchone()[0] == dt.date(2026, 9, 30)


def test_cadastro_de_financiamento_vale_mais_que_a_sugestao_e_renova_o_cache(conn, dados):
    antes = P.carimbo_dados(conn)
    r = P.fin_bem_salvar(conn, [{"chave": "38172", "categoria": "Máquinas e equipamentos", "objeto": "Retroescavadeira", "observacao": "teste"}], "teste@x")
    assert r == {"novos": 1, "alterados": 0, "limpos": 0}
    assert P.carimbo_dados(conn) != antes                                              # o painel recalcula sozinho
    cam = next(c for c in I.financiamentos(conn, HOJE)["por_contrato"] if c["chave"] == "38172")
    assert (cam["categoria"], cam["objeto"], cam["origem"], cam["sugestao"]) == ("Máquinas e equipamentos", "Retroescavadeira", "Cadastro", "Veículo")
    assert P.fin_bem_salvar(conn, [{"chave": "38172", "categoria": "Máquinas e equipamentos", "objeto": "Retroescavadeira", "observacao": "teste"}], "teste@x") == {"novos": 0, "alterados": 0, "limpos": 0}
    assert P.fin_bem_salvar(conn, [{"chave": "38172", "categoria": "", "objeto": "", "observacao": ""}], "teste@x")["limpos"] == 1
    cam = next(c for c in I.financiamentos(conn, HOJE)["por_contrato"] if c["chave"] == "38172")
    assert cam["categoria"] == "Veículo" and cam["origem"] == "Sugestão"                # voltou para a sugestao; a linha fica no historico
    with conn.cursor() as cur:
        cur.execute("SELECT ativo FROM pnl_financiamento_bem WHERE chave='38172'")
        assert cur.fetchone()[0] is False


def test_receitas_em_aberto_lista_cliente_nota_vencimento(conn, dados):
    r = I.receitas_em_aberto(conn, HOJE)
    assert [x["cliente"] for x in r] == ["CLIENTE A", "CLIENTE D"]
    assert r[0]["nota"] == "NF-A" and r[0]["valor"] == 1000.0 and r[0]["atraso"] == 20 and r[1]["atraso"] == 0


def test_financiamentos_saldo_juros_contratos_e_curva(conn, dados):
    f = I.financiamentos(conn, HOJE)
    assert f["saldo_devedor"] == 2000.0 + 5000.0                                      # caminhao (2 parcelas) + capital de giro; previsao fora
    assert f["juros_totais"] == 200.0 and f["desembolso_total"] == 7200.0
    assert f["contratos"] == 2 and f["encerramento_mais_longo"] == dt.date(2027, 3, 10)
    cam = next(c for c in f["por_contrato"] if c["chave"] == "38172")
    assert cam["categoria"] == "Veículo" and cam["credor"] == "TRATON" and cam["principal"] == 2000.0 and cam["juros"] == 200.0 and cam["parcelas"] == 4
    assert cam["taxa_mensal"] == round(200.0 / (1000 * 1 + 1000 * 2), 4)
    cg = next(c for c in f["por_contrato"] if c["chave"] == "4455667")
    assert cg["categoria"] == "Capital de giro" and cg["credor"] == "BANCO SANTANDER"
    assert [c["credor"] for c in f["por_credor"]] == ["BANCO SANTANDER", "TRATON"]
    assert round(sum(c["pct_carteira"] for c in f["por_credor"]), 4) == 1.0
    assert [(c["mes"], c["principal"], c["juros"]) for c in f["curva"]] == [("2026-11", 1000.0, 100.0), ("2026-12", 1000.0, 100.0), ("2027-03", 5000.0, 0.0)]
    com_prev = I.financiamentos(conn, HOJE, incluir_previsao=True)
    assert com_prev["saldo_devedor"] == 7777.0


def test_classificar_e_chave_de_contrato():
    assert I.chave_contrato("Caminhão SEB6A60 - Fin. Traton Ct 38172") == "38172"
    assert I.chave_contrato("Juros s/ Fin. Nivus PLACA - Contrato 300200") == "300200"
    assert I.chave_contrato("Banco Safra S/A | Capital de Giro | CT. 84857") == "84857"
    assert I.chave_contrato("Aquisição Sala Aruna", "2.05.01.02").startswith("2.05.01.02")
    assert I.classificar("2.03.04.05", "Banco Santander S/A | Capital de Giro | Ct. 4455667")[0] == "Capital de giro"
    assert I.classificar("2.05.01.01", "Caminhão SEB6A60 - Fin. Traton Ct 38172") == ("Veículo", "Caminhão SEB6A60 - Fin. Traton")
    assert I.classificar("2.05.01.03", "Imobilizado - Maquinário")[0] == "Máquinas e equipamentos"
    assert I.classificar("2.05.01.02", "Aquisição Sala Aruna")[0] == "Imóveis e obras"
    assert I.classificar("2.05.03.01", "Aporte de Capital - Anastacio")[0] == "Aporte de capital"


def test_custo_medio_usa_a_taxa_do_contrato_quando_cadastrada(conn, dados):
    f0 = I.financiamentos(conn, HOJE)
    assert f0["custo_medio"] == round(200.0 / 7000.0, 4) and "sem taxa" in f0["custo_medio_origem"]       # padrao: juros / saldo
    P.fin_bem_salvar(conn, [{"chave": "38172", "categoria": "", "objeto": "", "observacao": "", "taxa_mensal": 2.0},
                            {"chave": "4455667", "taxa_mensal": 1.0}], "teste@x")
    f = I.financiamentos(conn, HOJE)
    assert f["custo_medio"] == round((0.02 * 2000 + 0.01 * 5000) / 7000, 4) and "2 de 2" in f["custo_medio_origem"]
    cam = next(c for c in f["por_contrato"] if c["chave"] == "38172")
    assert cam["taxa_mensal"] == 0.02 and cam["taxa_origem"] == "Contrato" and cam["origem"] == "Sugestão" and cam["categoria"] == "Veículo"   # so' taxa: categoria segue a sugestao
    assert next(c for c in f["por_credor"] if c["credor"] == "TRATON")["taxa_mensal"] == 0.02
    with pytest.raises(ValueError):
        P.fin_bem_salvar(conn, [{"chave": "38172", "taxa_mensal": 150}], "teste@x")
