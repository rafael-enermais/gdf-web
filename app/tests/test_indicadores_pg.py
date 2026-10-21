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


def _tit(bill, inst, lado, contra, emissao, venc, valor, planos, baixas=(), previsao="N", numero="1", origem="CP"):
    base = {"billId": bill, "installmentId": inst, "companyId": 5, "companyName": "CONSTRUTORA", "originId": origem, "documentIdentificationId": "NF",
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
    assert r["n"] == 2 and r["simples"] == 15 and r["ponderado"] == 18 and r["n_fora"] == 0     # (10+20)/2 ; (10*100+20*300)/400 = 17,5 -> 18 (dias inteiros)
    assert I.prazo_medio(conn, "R", "2026-09")["n"] == 3                         # A, B e D (a previsao C fica de fora)
    assert I.prazo_medio(conn, "R", "2026-01")["simples"] is None


def test_gasto_e_ciclo_financeiro(conn, dados):
    g = I.gasto_pago(conn, "2026-09", hoje=HOJE)
    assert g["mensal"] == 400.0 and g["dias"] == 30 and round(g["diario"], 2) == 13.33
    c = I.ciclo_e_capital(conn, "2026-09", hoje=HOJE)
    assert c["pmp"]["simples"] == 15 and c["pmr"]["simples"] is not None
    assert c["ciclo_simples"] == c["pmr"]["simples"] - 15 and isinstance(c["ciclo_simples"], int)
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


def test_vencimento_original_e_o_primeiro_visto_e_nunca_e_sobrescrito(conn, dados):
    # 1a carga (fixture): titulo R 4 vence 2026-12-15 -> original = 2026-12-15
    with conn.cursor() as cur:
        cur.execute("SELECT data_vencimento_original FROM pnl_titulo WHERE lado='R' AND bill_id=4")
        assert cur.fetchone()[0] == dt.date(2026, 12, 15)
    ina = I.inadimplencia(conn, dt.date(2026, 10, 19), HOJE)
    assert ina["usa_vencimento_original"] and ina["receber"]["total"] == 1000.0            # 4 ainda nao venceu
    # Sienge prorroga o titulo 3 (previsao) e o 1: o 1 vencia 2026-09-30, passa para 2027-01-31; a carga seguinte NAO muda o original
    reg = _tit(1, 1, "R", "CLIENTE A", "2026-09-01", "2027-01-31", 1000.0, [_c("1010101", "Receita", 100)], numero="NF-A")
    _gravar(conn, "R", [reg])
    with conn.cursor() as cur:
        cur.execute("SELECT data_vencimento, data_vencimento_original FROM pnl_titulo WHERE lado='R' AND bill_id=1")
        assert cur.fetchone() == (dt.date(2027, 1, 31), dt.date(2026, 9, 30))
    assert I.inadimplencia(conn, dt.date(2026, 10, 19), HOJE)["receber"]["total"] == 1000.0   # continua vencido pelo original (nao some da inadimplencia)


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


def test_grupo_do_plano_planos_da_contabilidade():
    for cod in ("2.05.01.01", "2.05.01.01.03", "2.05.01.03.02", "2.05.01.03.04", "2.05.01.03.06", "2.05.01.03.07", "2.03.04.05"):
        assert I.grupo_do_plano(cod) == "financiamentos", cod
    for cod in ("2.05.01.02", "2.05.01.03", "2.05.01.03.03", "2.05.01.03.05", "2.05.03.01", "2.05.02", "2.05.01.010"):
        assert I.grupo_do_plano(cod) == "investimentos", cod
    assert I.grupo_do_plano("2.03.02.01") is None                                     # juros seguem o contrato
    with pytest.raises(ValueError):
        I.financiamentos(None, HOJE, grupo="outro")


def test_investimentos_separados_dos_financiamentos(conn, dados):
    rec = lambda cod, nome: [{"financialCategoryId": cod, "financialCategoryName": nome, "financialCategoryRate": 100, "costCenterId": 1, "costCenterName": "CC"}]  # noqa: E731
    extra = []
    for i, venc in enumerate(("2026-11-10", "2026-12-10"), start=1):                  # sala (2.05.01.02): NAO esta na lista da contabilidade -> Investimentos
        extra.append(_tit(200, i, "P", "IMOBILIARIA", "2026-02-01", venc, 400.0, rec("2.05.01.02", "Aquisição Sala Aruna - Ct 777"), numero="CT7"))
    extra.append(_tit(201, 1, "P", "IMOBILIARIA", "2026-02-01", "2026-11-10", 50.0, rec("2.03.02.01", "Juros s/ Aquisição Sala Aruna - Ct 777"), numero="CT7J"))   # juros seguem o contrato
    extra.append(_tit(202, 1, "P", "MAQUINAS SA", "2026-02-01", "2026-12-20", 900.0, rec("2.05.01.03", "Imobilizado - Maquinário Ct 888"), numero="CT8"))          # 2.05.01.03 sem sufixo: Investimentos
    extra.append(_tit(203, 1, "P", "MAQUINAS SA", "2026-02-01", "2026-12-20", 600.0, rec("2.05.01.03.04", "Retroescavadeira Ct 889"), numero="CT9"))                 # 2.05.01.03.04: Financiamentos
    _gravar(conn, "P", extra)
    fin = I.financiamentos(conn, HOJE)
    inv = I.financiamentos(conn, HOJE, grupo="investimentos")
    assert inv["grupo"] == "investimentos" and fin["grupo"] == "financiamentos"
    assert {c["chave"] for c in inv["por_contrato"]} == {"777", "888"}
    assert inv["saldo_devedor"] == 800.0 + 900.0 and inv["juros_totais"] == 50.0
    assert [(c["mes"], c["principal"], c["juros"]) for c in inv["curva"]] == [("2026-11", 400.0, 50.0), ("2026-12", 1300.0, 0.0)]
    assert "777" not in {c["chave"] for c in fin["por_contrato"]} and "889" in {c["chave"] for c in fin["por_contrato"]}
    assert fin["saldo_devedor"] == 2000.0 + 5000.0 + 600.0 and fin["juros_totais"] == 200.0          # nada do investimento vazou para o financiamento
    assert all(c["grupo"] == "investimentos" for c in inv["por_contrato"])


def test_historico_de_alteracao_do_vencimento(conn, dados):
    """SQL-28: o trigger registra antes/depois quando a carga muda o vencimento; o vencimento ATUAL e' atualizado e o ORIGINAL fica intacto."""
    reg = _tit(1, 1, "R", "CLIENTE A", "2026-09-01", "2027-01-31", 1000.0, [_c("1010101", "Receita", 100)], numero="NF-A")      # era 2026-09-30
    _gravar(conn, "R", [reg])
    _gravar(conn, "R", [reg])                                                                                                    # mesma data de novo: nao duplica
    reg2 = _tit(1, 1, "R", "CLIENTE A", "2026-09-01", "2027-03-31", 1000.0, [_c("1010101", "Receita", 100)], numero="NF-A")
    _gravar(conn, "R", [reg2])
    with conn.cursor() as cur:
        cur.execute("SELECT vencimento_anterior, vencimento_novo FROM pnl_vencimento_alteracao WHERE lado='R' AND bill_id=1 AND installment_id=1 ORDER BY id")
        assert cur.fetchall() == [(dt.date(2026, 9, 30), dt.date(2027, 1, 31)), (dt.date(2027, 1, 31), dt.date(2027, 3, 31))]
        cur.execute("SELECT data_vencimento, data_vencimento_original FROM pnl_titulo WHERE lado='R' AND bill_id=1")
        assert cur.fetchone() == (dt.date(2027, 3, 31), dt.date(2026, 9, 30))
        cur.execute("SELECT count(*) FROM pnl_vencimento_alteracao WHERE bill_id=2")
        assert cur.fetchone()[0] == 0                                                                                            # titulos sem mudanca nao geram linha


# ---------------------------------------------------------------- 21/10/2026: so' fornecedores de verdade, grupo ENERMAIS, periodo livre
@pytest.fixture()
def nao_fornecedores(conn, dados):
    """Soma ao cenario base titulos de setembro que NAO sao fornecedor/cliente de verdade: sem credor (banco), financiamento e empresas do grupo."""
    rec = lambda cod, nome: [{"financialCategoryId": cod, "financialCategoryName": nome, "financialCategoryRate": 100, "costCenterId": 1, "costCenterName": "CC"}]  # noqa: E731
    pagar = [
        _tit(20, 1, "P", "", "2026-09-05", "2026-09-05", 5000.0, rec("2010104", "Material"), baixas=[_pg(1, "2026-09-05", 5000.0)], origem="BC"),          # banco, sem credor
        _tit(21, 1, "P", "BANCO Y", "2026-09-06", "2026-09-06", 4000.0, rec("2030405", "Banco Y | Capital de Giro | Ct. 1"), baixas=[_pg(1, "2026-09-06", 4000.0)]),   # financiamento
        _tit(22, 1, "P", "ENERMAIS ENERGIA LTDA", "2026-09-07", "2026-09-07", 3000.0, rec("2010104", "Material"), baixas=[_pg(1, "2026-09-07", 3000.0)]),         # grupo
    ]
    receber = [_tit(30, 1, "R", "ENERMAIS CONSTRUTORA LTDA - CNPJ 12.345.678/0001-90", "2026-09-02", "2026-09-02", 8000.0, rec("1010101", "Receita"), numero="NF-G")]
    _gravar(conn, "P", pagar)
    _gravar(conn, "R", receber)


def test_prazos_e_gasto_so_com_fornecedores_de_verdade(conn, nao_fornecedores):
    r = I.prazo_medio(conn, "P", "2026-09")
    assert r["n"] == 2 and r["n_fora"] == 3 and r["simples"] == 15 and r["ponderado"] == 18            # igual ao cenario base: o resto ficou de fora
    tudo = I.prazo_medio(conn, "P", "2026-09", completo=True)
    assert tudo["n"] == 5 and tudo["ponderado"] < 18 and tudo["simples"] < 15                           # prazo zero puxava a media para baixo
    assert I.prazo_medio(conn, "R", "2026-09")["n_fora"] == 1 and I.prazo_medio(conn, "R", "2026-09", completo=True)["n"] == 4
    assert I.gasto_pago(conn, "2026-09", HOJE)["total"] == 400.0                                         # so' FORN 1 e FORN 2
    assert I.gasto_pago(conn, "2026-09", HOJE, completo=True)["total"] == 400.0 + 5000 + 4000 + 3000
    c, c_tudo = I.ciclo_e_capital(conn, "2026-09", hoje=HOJE), I.ciclo_e_capital(conn, "2026-09", hoje=HOJE, completo=True)
    assert c["completo"] is False and c_tudo["completo"] is True and c["ciclo_ponderado"] != c_tudo["ciclo_ponderado"]


def test_periodo_livre_prazos_e_gasto(conn, dados):
    um = I.prazo_medio(conn, "P", "2026-09", mes_ini="2026-08")
    assert um["n"] == 3                                                                                   # agosto (FORN 3) + setembro (FORN 1 e 2)
    g = I.gasto_pago(conn, "2026-10", HOJE, mes_ini="2026-09")
    assert g["total"] == 400.0 and g["dias"] == (HOJE - dt.date(2026, 9, 1)).days + 1                    # a parcela do caminhao (financiamento, paga em 01/10) fica de fora...
    assert I.gasto_pago(conn, "2026-10", HOJE, mes_ini="2026-09", completo=True)["total"] == 400.0 + 1000.0   # ...e entra no "incluir tudo"
    assert I.ciclo_e_capital(conn, "2026-10", hoje=HOJE, mes_ini="2026-09")["mes_ini"] == "2026-09"


def test_a_receber_sem_clientes_do_grupo(conn, nao_fornecedores):
    r = I.receitas_em_aberto(conn, HOJE)
    assert [x["cliente"] for x in r] == ["CLIENTE A", "CLIENTE D"]                                      # grupo ENERMAIS fora (mesmo com ' - CNPJ ...' no nome)
    assert "ENERMAIS CONSTRUTORA LTDA - CNPJ 12.345.678/0001-90" in [x["cliente"] for x in I.receitas_em_aberto(conn, HOJE, completo=True)]
    v, p = I.data_posicao("2026-10", HOJE)
    assert I.inadimplencia(conn, v, p)["receber"]["total"] == 1000.0
    assert I.inadimplencia(conn, v, p, completo=True)["receber"]["total"] == 9000.0
