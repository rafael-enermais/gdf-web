# -*- coding: utf-8 -*-
"""Painel Folha PJ: regras de calculo (funcoes puras) com dados SINTETICOS. Nenhum nome, CPF ou valor real."""
import datetime as dt

import pytest

import folha_pj_dados as FP

D = dt.date


def L(bill, inst, seq, tipo, data, bruto, desc, emp_id, cred, doc, num, plano, centro, pct=100.0, venc=None, nome=None):
    """Uma linha (baixa/titulo x apropriacao), no formato de buscar_linhas."""
    return {"bill": bill, "inst": inst, "seq": seq, "tipo": tipo, "data": data, "bruto": bruto, "desc": desc, "emp_id": emp_id, "emp": FP.EMPRESAS[emp_id], "cred_id": cred,
            "cred_nome": nome or f"{cred}.000.000 CREDOR {cred}", "doc_id": doc, "num_doc": num, "venc": venc or data, "plano": plano, "plano_nome": "Conta " + plano,
            "centro_id": centro, "centro_nome": f"CENTRO {centro}", "pct": pct}


CENTROS = {1: {"nome": "EE - SEDE / ADM CENTRAL", "grupo": "ADM", "obra": "Sede / ADM central", "cod_obra": "ADM"},
           2: {"nome": "SMG - SEDE", "grupo": "ADM", "obra": "Sede / ADM central", "cod_obra": "ADM"},
           1005: {"nome": "EE - ANASTACIO", "grupo": "OBRA", "obra": "Anastácio — Lote 11", "cod_obra": "103"},
           1049: {"nome": "CON - ANASTACIO", "grupo": "OBRA", "obra": "Anastácio — Lote 11", "cod_obra": "103"},
           1006: {"nome": "EE - NOVA ERA", "grupo": "OBRA", "obra": "Nova Era", "cod_obra": "106"},
           99982: {"nome": "EE - INVESTIMENTO", "grupo": "DEMAIS_MES", "obra": "Investimento", "cod_obra": "999"}}


def _apoio(**kw):
    base = {"centros": CENTROS, "fantasia": {}, "colab": {}, "diretoria": set(), "flash": []}
    base.update(kw)
    return base


def _pessoa(r, cred, emp=1):
    return next(p for p in r["pessoas"] if p["cred_id"] == cred and p["emp_id"] == emp)


# ------------------------------------------------------------------ texto
def test_nome_exibicao_e_hash():
    assert FP.nome_exibicao("55.808.658 LUCAS DE SOUZA E SILVA") == "Lucas de Souza e Silva"
    assert FP.nome_exibicao("ANA MARIA DOS SANTOS") == "Ana Maria dos Santos"
    assert FP.nome_empresa_curto("ENERMAIS ENERGIA LTDA") == "ENERMAIS ENERGIA"
    assert FP.chave_nome("  José  da Silva-Júnior ") == "jose da silva junior"
    h = FP.hash_cpf("123.456.789-09", "segredo")
    assert h and len(h) == 64 and h == FP.hash_cpf("12345678909", "segredo") and h != FP.hash_cpf("12345678909", "outro")
    assert FP.hash_cpf("123", "segredo") is None and FP.hash_cpf("12345678909", "") is None
    assert "12345678909" not in h


# ------------------------------------------------------------------ substituicoes
def test_abatimento_sem_proforma_sai_e_com_proforma_a_nota_fica_com_a_data_do_adiantamento():
    linhas = [
        L(1, 1, 1, 1, D(2026, 10, 5), 1000.0, 0, 1, 10, "NFS", "1", "2.01.02.01", 1005),                 # pagamento normal
        L(2, 1, 1, 8, D(2026, 10, 21), 7884.87, 0, 1, 20, "NFS", "44", "2.01.02.01", 1005),              # abatimento sem adiantamento do mesmo valor: sai
        L(3, 1, 1, 10, D(2026, 10, 7), 7295.64, 0, 1, 30, "PRO", "006", "2.01.02.01", 1005),             # proforma...
        L(4, 1, 1, 8, D(2026, 10, 21), 7295.64, 0, 1, 30, "NFS", "45", "2.01.02.01", 1005),              # ...substituida pela nota (abatimento): proforma sai, nota fica em 07/10
        L(5, 1, 1, 10, D(2026, 10, 13), 122000.0, 0, 1, 40, "ADT", "1", "2.01.02.11", 1005),             # adiantamento...
        L(6, 1, 1, 1, D(2026, 10, 13), 122000.0, 0, 1, 40, "CT", "X", "2.01.02.11", 1005),               # ...e a nota do mesmo valor: o adiantamento sai
        L(7, 1, 1, 10, D(2026, 10, 9), 3000.0, 0, 1, 50, "ADT", "2", "2.01.02.11", 1005),                # adiantamento sem nota: fica
    ]
    validas, fora = FP.aplicar_substituicoes(FP.agrupar_baixas(linhas))
    ids = {b["bill"] for b in validas}
    assert ids == {1, 4, 6, 7}
    assert {f["baixa"]["bill"] for f in fora} == {2, 3, 5}
    nota45 = next(b for b in validas if b["bill"] == 4)
    assert nota45["data"] == D(2026, 10, 7) and nota45["data_original"] == D(2026, 10, 21) and nota45["substitui"] == "PRO 006"
    assert sum(b["bruto"] for b in validas) == pytest.approx(1000 + 7295.64 + 122000 + 3000)


def test_substituicao_e_cancelamento_nao_entram_na_consulta():
    assert 5 not in FP.TIPOS_BAIXA and 3 not in FP.TIPOS_BAIXA and set(FP.TIPOS_BAIXA) == {1, 8, 10}


# ------------------------------------------------------------------ consolidar
def _cenario():
    pago = [
        L(1, 1, 1, 1, D(2026, 10, 7), 10000.0, 100.0, 1, 10, "NFS", "1", "2.01.02.01", 1005),            # honorarios obra, 1 centro
        L(2, 1, 1, 1, D(2026, 10, 7), 10500.0, 0.0, 1, 11, "NFS", "2", "2.02.01.01", 1, pct=50.0),        # dividido entre ADM e Obra: 2 linhas de documento
        L(2, 1, 1, 1, D(2026, 10, 7), 10500.0, 0.0, 1, 11, "NFS", "2", "2.01.02.01", 1005, pct=50.0),
        L(3, 1, 1, 1, D(2026, 10, 7), 4000.0, 0.0, 1, 12, "NFS", "3", "2.02.01.01", 1, pct=60.0),         # tudo sede (2 centros ADM): fica o de maior valor
        L(3, 1, 1, 1, D(2026, 10, 7), 4000.0, 0.0, 1, 12, "NFS", "3", "2.02.01.01", 99982, pct=40.0),
        L(4, 1, 1, 1, D(2026, 10, 7), 5000.0, 0.0, 1, 13, "NFS", "4", "2.01.02.11", 1005, pct=50.0),      # premiacao em dois centros de obra: EMPRESA - OBRAS
        L(4, 1, 1, 1, D(2026, 10, 7), 5000.0, 0.0, 1, 13, "NFS", "4", "2.01.02.11", 1006, pct=50.0),
        L(5, 1, 1, 1, D(2026, 10, 8), 900.0, 0.0, 3, 14, "NFS", "5", "2.01.02.01", 1006),                  # outra empresa pagadora
        L(6, 1, 1, 1, D(2026, 10, 9), 30000.0, 0.0, 1, 90, "CT", "D", "2.01.02.11", 1005, pct=50.0),      # diretoria (credor 90)
        L(6, 1, 1, 1, D(2026, 10, 9), 30000.0, 0.0, 1, 90, "CT", "D", "2.01.02.11", 1006, pct=50.0),
        L(7, 1, 1, 8, D(2026, 10, 20), 777.0, 0.0, 1, 15, "NFS", "9", "2.01.02.01", 1005),                 # abatimento sem adiantamento: fora
    ]
    abertas = [
        L(20, 1, 0, 0, D(2026, 10, 30), 2000.0, 50.0, 1, 10, "NFS", "20", "2.01.02.01", 1005),            # a pagar do mesmo credor do pagamento 1 -> Parcial
        L(21, 1, 0, 0, D(2026, 10, 25), 16210.0, 0.0, 1, 16, "NFS", "21", "2.02.01.19", 1),                # multa a pagar
        L(22, 1, 0, 0, D(2026, 10, 30), 1000.0, 0.0, 3, 90, "CT", "D2", "2.01.02.11", 1005),               # diretoria paga pela empresa 3
    ]
    return {"baixas": pago, "abertas": abertas}


def test_consolidar_totais_documentos_e_regras():
    apoio = _apoio(diretoria={90}, fantasia={10: "JOAO DA SILVA", 11: "MARIA DOS ANJOS"},
                   colab={12: {"nome": "Pedro Sede", "funcao": "Analista", "centro": "1 - EE - SEDE", "novo_desde": D(2026, 10, 1)}},
                   flash=[{"credor_id": 10, "empresa": "ENERMAIS ENERGIA LTDA", "premiacao": 3000.0, "alimentacao": 650.0},
                          {"credor_id": 17, "empresa": "ENERMAIS ENERGIA LTDA", "premiacao": 0.0, "alimentacao": 750.0}])
    apoio["colab"][17] = {"nome": "so flash silva", "funcao": "Tecnico", "centro": "1006 - EE - NOVA ERA", "novo_desde": None}
    r = FP.consolidar(_cenario(), apoio, "2026-10")
    # documentos pagos: 1 por titulo+conta (os varios centros viram apropriacao): titulos 1,3,4,5,6 = 1 cada; titulo 2 divide ADM/Obra em 2 contas = 2
    pagos = [d for d in r["documentos"] if d["situacao"] == "Pago"]
    assert len(pagos) == 7
    assert not any(d["lancamento"] == "7/1" for d in r["documentos"])
    assert r["fora"] == [{"lancamento": "7/1", "documento": "NFS 9", "tipo": 8, "valor": 777.0, "motivo": "abatimento de adiantamento (sem adiantamento do mesmo valor no mês)"}]
    p10 = _pessoa(r, 10)
    assert p10["nome"] == "Joao da Silva" and p10["honorarios"] == 12000.0 and p10["desconto"] == -150.0
    assert p10["ajuda_custo"] == 3000.0 and p10["alimentacao"] == 650.0
    assert p10["custo_total"] == 12000.0 - 150.0 + 3650.0
    assert p10["pago"] == 9900.0 and p10["a_pagar"] == 1950.0 and p10["situacao"] == "Parcial"
    assert p10["centro"] == "1005 - CENTRO 1005" and p10["obra"] == "Anastácio — Lote 11"
    # dividido entre sede e obra: 2 centros, um de obra -> EMPRESA - OBRAS
    p11 = _pessoa(r, 11)
    assert p11["centro"] == "ENERMAIS ENERGIA - OBRAS" and p11["obra"] == FP.VARIOS and p11["honorarios"] == 10500.0
    assert len([d for d in r["documentos"] if d["cred_id"] == 11]) == 2
    # todos os centros sao sede/adm: fica o de maior valor
    p12 = _pessoa(r, 12)
    assert p12["centro"] == "1 - CENTRO 1" and p12["obra"] == FP.SEDE and p12["novo"] is True and p12["funcao"] == "Analista"
    # premiacao em dois centros de obra
    assert _pessoa(r, 13)["centro"] == "ENERMAIS ENERGIA - OBRAS" and _pessoa(r, 13)["premiacao"] == 5000.0
    # outra empresa pagadora -> outra linha do mesmo mundo
    assert _pessoa(r, 14, 3)["empresa"] == "ENERMAIS ENGENHARIA LTDA"
    # multa a pagar
    p16 = _pessoa(r, 16)
    assert p16["multa"] == 16210.0 and p16["situacao"] == "A pagar" and p16["a_pagar"] == 16210.0
    # so Flash
    p17 = _pessoa(r, 17)
    assert p17["situacao"] == "Só Flash" and p17["alimentacao"] == 750.0 and p17["centro"] == "1006 - EE - NOVA ERA" and p17["obra"] == "Nova Era" and p17["custo_total"] == 750.0
    # diretoria: centro DIRETORIA, uma linha so' no agrupamento
    assert _pessoa(r, 90)["centro"] == FP.DIRETORIA and _pessoa(r, 90)["diretoria"]
    ag = FP.agrupar_diretoria(r["pessoas"])
    assert ag[-1]["nome"] == FP.ROT_DIRETORIA and ag[-1]["agrupado"] == 2 and not any(p["diretoria"] for p in ag[:-1])
    assert ag[-1]["honorarios"] == 0.0 and ag[-1]["premiacao"] == 31000.0   # 30.000 pago pela empresa 1 + 1.000 a pagar pela empresa 3
    # totais fecham: custo total = honorarios + premiacoes + multa + flash - descontos
    t = r["totais"]
    assert t["custo_total"] == pytest.approx(t["honorarios"] + t["premiacao"] + t["multa"] + t["ajuda_custo"] + t["alimentacao"] + t["desconto"], abs=0.01)
    assert t["pago"] + t["a_pagar"] == pytest.approx(t["honorarios"] + t["premiacao"] + t["multa"] + t["desconto"], abs=0.01)


def test_cards_resumo_e_top_obras():
    apoio = _apoio(diretoria={90})
    r = FP.consolidar(_cenario(), apoio, "2026-10")
    cards = {c["emp_id"]: c for c in r["cards"]}
    assert cards[1]["diretoria"]["premiacao"] == 30000.0 and cards[3]["diretoria"]["premiacao"] == 1000.0       # diretoria soma na empresa que pagou
    assert cards[1]["total"]["custo_total"] == pytest.approx(cards[1]["sem_diretoria"]["custo_total"] + 30000.0)
    assert sum(c["total"]["custo_total"] for c in r["cards"]) == pytest.approx(r["totais"]["custo_total"])
    # resumo 2 niveis: pseudo-grupos por ultimo, diretoria por ultimo de todos
    nomes = [o["obra"] for o in r["obras"]]
    assert nomes[-1] == FP.DIRETORIA and nomes.index(FP.SEDE) > nomes.index("Anastácio — Lote 11")
    anast = next(o for o in r["obras"] if o["obra"] == "Anastácio — Lote 11")
    assert [c["centro"] for c in anast["centros"]] == ["1005 - CENTRO 1005"] or anast["centros"][0]["custo_total"] >= anast["centros"][-1]["custo_total"]
    assert sum(o["custo_total"] for o in r["obras"]) == pytest.approx(r["totais"]["custo_total"])
    # top 3: sem diretoria e sem sede / varios centros
    top = r["top_obras"]
    assert {o["obra"] for o in top} <= {"Anastácio — Lote 11", "Nova Era"} and FP.DIRETORIA not in {o["obra"] for o in top}
    assert top[0]["custo_total"] >= top[-1]["custo_total"]


def test_filtros_em_cascata():
    apoio = _apoio(diretoria={90}, fantasia={10: "JOAO DA SILVA"})
    r = FP.consolidar(_cenario(), apoio, "2026-10")
    pes = r["pessoas"]
    assert {p["cred_id"] for p in FP.filtrar(pes, obras=["Anastácio — Lote 11"])} == {10}
    assert {p["cred_id"] for p in FP.filtrar(pes, centros=["ENERMAIS ENERGIA - OBRAS"])} == {11, 13}
    assert {p["cred_id"] for p in FP.filtrar(pes, situacoes=["A pagar"])} == {16, 90} or {p["cred_id"] for p in FP.filtrar(pes, situacoes=["A pagar"])} == {16}
    assert {p["cred_id"] for p in FP.filtrar(pes, empresas=["ENERMAIS ENGENHARIA LTDA"])} == {14, 90}
    assert [p["cred_id"] for p in FP.filtrar(pes, busca="joao")] == [10]
    # documentos de quem esta marcado
    sel = [p for p in pes if p["cred_id"] == 10]
    docs = FP.filtrar_documentos(r["documentos"], sel)
    assert {d["cred_id"] for d in docs} == {10} and {d["situacao"] for d in docs} == {"Pago", "A pagar"}
    assert [d["situacao"] for d in FP.filtrar_documentos(r["documentos"], sel, situacoes=["A pagar"])] == ["A pagar"]
    # diretoria agrupada traz os documentos de todos os credores da diretoria
    dire = [p for p in FP.agrupar_diretoria(pes) if p.get("agrupado")]
    assert {d["cred_id"] for d in FP.filtrar_documentos(r["documentos"], dire)} == {90}
    assert len(FP.filtrar_documentos(r["documentos"], None)) == len(r["documentos"])


def test_flash_em_outra_empresa_vira_linha_so_flash_e_documento_tem_apropriacao():
    apoio = _apoio(colab={10: {"nome": "Joao", "funcao": None, "centro": "1005 - X", "novo_desde": None}},
                   flash=[{"credor_id": 10, "empresa": "ENERMAIS CONSTRUTORA LTDA", "premiacao": 100.0, "alimentacao": 200.0}])
    r = FP.consolidar(_cenario(), apoio, "2026-10")
    linhas10 = [p for p in r["pessoas"] if p["cred_id"] == 10]
    assert {p["empresa"] for p in linhas10} == {"ENERMAIS ENERGIA LTDA", "ENERMAIS CONSTRUTORA LTDA"}
    so = next(p for p in linhas10 if p["empresa"] == "ENERMAIS CONSTRUTORA LTDA")
    assert so["situacao"] == "Só Flash" and so["centro"] == "1005 - X" and so["custo_total"] == 300.0
    d = next(d for d in r["documentos"] if d["lancamento"] == "2/1" and d["plano"] == "2.02.01.01")
    assert d["bruto"] == 5250.0 and d["apropriacao"] == [{"centro": "1 - CENTRO 1", "centro_id": 1, "pct": 50.0}]


def test_obra_do_centro_e_decisao():
    assert FP.obra_do_centro("1005 - EE - ANASTACIO", CENTROS) == "Anastácio — Lote 11"
    assert FP.obra_do_centro("99982 - EE - INVESTIMENTO", CENTROS) == FP.SEDE          # 999xx e sedes ficam em SEDE / ADM CENTRAL
    assert FP.obra_do_centro("ENERMAIS ENERGIA - OBRAS", CENTROS) == FP.VARIOS
    assert FP.obra_do_centro("DIRETORIA", CENTROS) == FP.DIRETORIA
    assert FP.obra_do_centro("5 - CONST - SEDE / ADM CENTRAL", {}) == FP.SEDE
    nomes = {1: "1 - A", 1005: "1005 - B"}
    assert FP.decidir_centro({1: 10.0}, "ENERMAIS ENERGIA LTDA", CENTROS, nomes) == "1 - A"
    assert FP.decidir_centro({1: 10.0, 1005: 5.0}, "ENERMAIS ENERGIA LTDA", CENTROS, nomes) == "ENERMAIS ENERGIA - OBRAS"
    assert FP.decidir_centro({}, "X", CENTROS, nomes) == "(sem centro de custo)"
    assert FP.eh_adm(99983, {}) and FP.eh_adm(1, CENTROS) and not FP.eh_adm(1005, CENTROS)
