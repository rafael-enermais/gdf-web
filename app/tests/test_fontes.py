# -*- coding: utf-8 -*-
"""Modo flexivel (v0.5.0): o relatorio sai com o que existir (mensais, acumulado, saldo anterior) e marca n/d so' no que nao da' para calcular.
Sempre a mesma regra: numero calculado por outro caminho tem de ser IGUAL ao do caminho completo; o que nao tem caminho vira None com explicacao."""
import io

import pytest

import fontes
import importador_csv as I
import motor
import painel as P
import relatorio_dados as RD
import relatorio_pdf as RP
from dados_sinteticos import csv_texto, gerar_meses

CNPJ = "54.800.488/0001-60"
MESES = gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100), (60_000, 3_000, 50), (70_000, 2_000, 80)])
ULT = {1: "31", 2: "28", 3: "31", 4: "30"}
EMP = {"id": 1, "codigo": "ANASTACIO", "razao_social": "Anastácio Transmissora de Energia S.A.", "cnpj": CNPJ}


def _mensais(n=4):
    per = {}
    for m in range(1, n + 1):
        _, contas = I.ler_bytes(csv_texto(MESES[f"2026-{m:02d}"], cnpj=CNPJ, ini=f"01/{m:02d}/2026", fim=f"{ULT[m]}/{m:02d}/2026"), "x.csv")
        per[f"2026-{m:02d}"] = contas
    return per


def _acum(per, ate):
    """Balancete acumulado de janeiro ate 'ate' montado a partir dos mensais, no formato do sistema: saldo anterior de janeiro, debitos/creditos somados,
    saldos de balanco do ultimo mes, saldos de resultado ACUMULADOS no ano; 2.4.13 fica no saldo de abertura e a linha 8 traz o resultado do ano."""
    meses = [m for m in sorted(per) if m <= ate]
    jan = {c["cl"]: c for c in per[meses[0]] if not c["sint"]}
    ana = []
    for c in per[ate]:
        if c["sint"]:
            continue
        deb = round(sum(x["deb"] for m in meses for x in per[m] if x["cl"] == c["cl"]), 2)
        cred = round(sum(x["cred"] for m in meses for x in per[m] if x["cl"] == c["cl"]), 2)
        ant = jan[c["cl"]]["ant"] if c["cl"] in jan else 0.0
        sal = c["sal"]
        if c["cl"][0] == "5":
            sal = round(deb - cred, 2)
        elif c["cl"][0] == "4":
            sal = round(cred - deb, 2)
        elif c["cl"].startswith("2.4.13"):                       # o resultado dos meses nao passa por 2.4.13 no acumulado: fica na linha 8
            sal, deb, cred = ant, 0.0, 0.0
        ana.append({**c, "ant": ant, "deb": deb, "cred": cred, "sal": sal})
    out = list(ana)
    for c in per[ate]:
        if not c["sint"]:
            continue
        filhas = [x for x in ana if x["cl"].startswith(c["cl"] + ".")]
        if c["cl"] == "8":
            s5 = sum(x["sal"] for x in ana if x["cl"][0] == "5")
            s4 = sum(x["sal"] for x in ana if x["cl"][0] == "4")
            out.append({**c, "sal": round(-(s5 - s4), 2)})
        elif filhas:
            out.append({**c, **{k: round(sum(x[k] for x in filhas), 2) for k in ("ant", "deb", "cred", "sal")}})
        else:
            out.append(dict(c))
    return out


PER = _mensais()
CHEIO = fontes.calcular(PER, {}, None, "2026-04")


def _igual(a, b, cols, tol=0.011):
    for col in cols:
        assert (a[col] is None) == (b[col] is None), col
        if a[col] is not None:
            assert all(abs(a[col][k] - b[col][k]) <= tol for k in b[col]), (col, {k: (a[col][k], b[col][k]) for k in b[col] if abs(a[col][k] - b[col][k]) > tol})


def test_completo_e_igual_ao_motor_de_sempre():
    b = motor.Balancetes(PER)
    assert CHEIO["fonte"] == "completo" and CHEIO["lacunas"] == [] and CHEIO["faltam_mensais"] == []
    bp, d = motor.balanco(b, "2026-04", "2026-03"), motor.dre(b, "2026-04")
    assert CHEIO["bp"] == bp and CHEIO["d"] == d and CHEIO["mes_ant"] == "2026-03"
    assert [c["ok"] for c in CHEIO["conf"]] == [c["ok"] for c in motor.conferencias(b)] and not CHEIO["falhas"]


def test_acumulado_ate_o_mes_anterior_mais_o_mes_da_o_mesmo_relatorio():
    """O caso da contadora: acumulado jan-mar + balancete mensal de abril (sem nenhum dos mensais jan-mar)."""
    r = fontes.calcular({"2026-04": PER["2026-04"]}, {"2026-03": _acum(PER, "2026-03")}, None, "2026-04")
    assert r["fonte"] == "alternativo" and r["lacunas"] == [] and r["usados_acum"] == ["2026-03"] and r["usados_mensais"] == ["2026-04"]
    _igual(r["bp"], CHEIO["bp"], ("abertura", "mes_ant", "mes_ref"))
    _igual(r["d"], CHEIO["d"], ("ate_mes_ant", "mes", "acumulado"))
    assert "acumulado" in r["fontes"]["dre_acum"] and "saldo anterior" in r["fontes"]["bp_ant"]
    assert any("acumulado" in n for n in r["notas"])


def test_so_acumulado_do_mes_calcula_posicao_e_acumulado_e_marca_nd_no_resto():
    r = fontes.calcular({}, {"2026-04": _acum(PER, "2026-04")}, None, "2026-04")
    assert r["fonte"] == "parcial" and len(r["lacunas"]) == 3
    _igual({**r["bp"], "mes_ant": None}, {**CHEIO["bp"], "mes_ant": None}, ("abertura", "mes_ref"))
    _igual({"acumulado": r["d"]["acumulado"]}, {"acumulado": CHEIO["d"]["acumulado"]}, ("acumulado",))
    assert r["bp"]["mes_ant"] is None and r["d"]["ate_mes_ant"] is None and r["d"]["mes"] is None
    onde = " | ".join(l["onde"] for l in r["lacunas"])
    assert "mês anterior" in onde and "Jan–Mar" in onde and "04/2026" in onde


def test_acumulado_e_mensal_do_mes_derivam_o_acumulado_ate_o_mes_anterior():
    r = fontes.calcular({"2026-04": PER["2026-04"]}, {"2026-04": _acum(PER, "2026-04")}, None, "2026-04")
    assert r["fonte"] == "alternativo" and "menos o mensal" in r["fontes"]["dre_ate_ant"]
    _igual(r["d"], CHEIO["d"], ("ate_mes_ant", "mes", "acumulado"))


def test_so_o_mensal_do_mes_usa_o_saldo_anterior_e_o_resto_vira_nd():
    r = fontes.calcular({"2026-04": PER["2026-04"]}, {}, None, "2026-04")
    _igual({"mes_ant": r["bp"]["mes_ant"], "mes_ref": r["bp"]["mes_ref"]}, {"mes_ant": CHEIO["bp"]["mes_ant"], "mes_ref": CHEIO["bp"]["mes_ref"]}, ("mes_ant", "mes_ref"))
    _igual({"mes": r["d"]["mes"]}, {"mes": CHEIO["d"]["mes"]}, ("mes",))
    assert r["bp"]["abertura"] is None and r["d"]["acumulado"] is None and r["d"]["ate_mes_ant"] is None and len(r["lacunas"]) == 3
    assert any("janeiro" in l["resolver"] for l in r["lacunas"])


def test_mensais_com_buraco_nunca_inventam_a_dre():
    r = fontes.calcular({k: PER[k] for k in ("2026-01", "2026-03", "2026-04")}, {}, None, "2026-04")        # falta fevereiro
    _igual({"abertura": r["bp"]["abertura"], "mes_ant": r["bp"]["mes_ant"], "mes_ref": r["bp"]["mes_ref"]}, CHEIO["bp"], ("abertura", "mes_ant", "mes_ref"))
    assert r["d"]["mes"] is not None and r["d"]["acumulado"] is None and r["d"]["ate_mes_ant"] is None
    assert r["faltam_mensais"] == ["2026-02"] and len(r["lacunas"]) == 2 and not r["falhas"]
    assert "02/2026" in r["lacunas"][0]["resolver"]


def test_acumulado_que_nao_bate_com_o_mensal_vizinho_e_deixado_de_lado():
    ac = [dict(c) for c in _acum(PER, "2026-03")]
    for c in ac:
        if c["cl"] == "1.1.01.002.001":
            c["sal"] += 100.0                                   # arquivo errado/adulterado: o saldo final nao bate com o saldo anterior de abril
    r = fontes.calcular({"2026-04": PER["2026-04"]}, {"2026-03": ac}, None, "2026-04")
    assert r["usados_acum"] == [] and r["d"]["acumulado"] is None
    assert any("não foi usado" in l["motivo"] for l in r["lacunas"])           # o motivo aparece, nada e' calculado com dado incoerente


def test_sem_nenhum_balancete_do_mes_e_o_unico_caso_que_bloqueia():
    with pytest.raises(motor.ErroDados, match="Não há balancete"):
        fontes.calcular({"2026-02": PER["2026-02"]}, {}, None, "2026-03")


def test_janeiro_sozinho_tem_mes_anterior_igual_a_abertura():
    r = fontes.calcular({"2026-01": PER["2026-01"]}, {}, None, "2026-01")
    assert r["fonte"] == "completo" and r["lacunas"] == [] and r["bp"]["mes_ant"] == r["bp"]["abertura"]


def test_conferencias_com_buraco_nao_geram_falso_alarme():
    b = motor.Balancetes({k: PER[k] for k in ("2026-01", "2026-03")})
    R = motor.conferencias(b)
    assert all(c["ok"] for c in R)
    assert not any(c["grupo"] == "Continuidade" for c in R)                    # marco nao tem o fevereiro para comparar
    assert [c["periodo"] for c in R if c["grupo"] == "Encerramento"] == ["2026-01"]       # so' janeiro tem a sequencia desde o inicio do ano
    with pytest.raises(motor.ErroDados):
        b.ajuste_mes("2026-03")                                                # resultado de marco sem o saldo de fevereiro: nao calcula


def test_cruzamento_mensal_x_acumulado_continua_valendo_quando_ha_todos_os_meses():
    r = fontes.calcular(PER, {"2026-03": _acum(PER, "2026-03")}, None, "2026-04")
    cruz = [c for c in r["conf"] if c["grupo"] == "Mensal x acumulado"]
    assert r["fonte"] == "completo" and len(cruz) == 2 and not r["falhas"]


def test_painel_com_lacunas_bate_com_o_painel_completo_e_deixa_none_onde_nao_calcula():
    cheio = P.serie_mensal(motor.Balancetes(PER))
    igual = P.serie_com_lacunas(PER, {}, None, "2026-04")
    for a, b_ in zip(igual, cheio):
        assert all(a[k] == b_[k] for k in b_), a["periodo"]
    burac = P.serie_com_lacunas({k: PER[k] for k in ("2026-01", "2026-03", "2026-04")}, {}, None, "2026-04")
    assert [l["periodo"] for l in burac] == ["2026-01", "2026-03", "2026-04"]
    mar = burac[1]
    assert mar["resultado_acum"] is None and mar["resultado_mes"] == cheio[2]["resultado_mes"]
    assert mar["variacao_caixa"] == cheio[2]["variacao_caixa"] and mar["caixa"] == cheio[2]["caixa"]       # variacao do caixa vem do saldo anterior de marco


def _pdf(r, ref="2026-04"):
    x = RD.montar(EMP, r["b"], ref, r["bp"], r["d"], r["contas_ref"], None, None, None, None, r)
    return x, RP.gerar_pdf(x, {}, "RASCUNHO", "09/10/2026 10:00")


def _texto_pdf(pdf):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        return len(p.pages), "\n".join(pg.extract_text() or "" for pg in p.pages)


def test_pdf_completo_continua_com_11_paginas_e_sem_aviso():
    x, pdf = _pdf(CHEIO)
    n, txt = _texto_pdf(pdf)
    assert n == 11 and "Dados incompletos" not in txt and "n/d" not in txt


def test_pdf_com_acumulado_tem_pagina_de_fontes_e_os_mesmos_numeros():
    r = fontes.calcular({"2026-04": PER["2026-04"]}, {"2026-03": _acum(PER, "2026-03")}, None, "2026-04")
    _, pdf = _pdf(r)
    n, txt = _texto_pdf(pdf)
    _, txt_cheio = _texto_pdf(_pdf(CHEIO)[1])
    assert n == 12 and "De onde vêm os números" in txt and "Dados incompletos" not in txt and "indisponível" not in txt
    res = RP.fnum(CHEIO["d"]["acumulado"]["res_liq"])
    assert res in txt and res in txt_cheio


def test_pdf_com_nd_explica_o_que_falta_e_a_pagina_impossivel_vira_aviso():
    r = fontes.calcular({"2026-04": PER["2026-04"]}, {}, None, "2026-04")
    x, pdf = _pdf(r)
    n, txt = _texto_pdf(pdf)
    assert n == 12 and "n/d" in txt and "Dados incompletos e fontes dos números" in txt
    assert "Formação do Resultado — indisponível neste relatório" in txt                    # precisa da DRE acumulada: nao inventa
    assert "importe o balancete mensal de 01/2026" in txt.replace("\n", " ")
    assert x["bp"]["capital"][0] == "n/d" and x["dre"]["res_liq"][2] == "n/d" and x["dre"]["res_liq"][1] != "n/d"
    assert RP.fnum(r["d"]["mes"]["res_liq"]) in txt                                          # o que existe (mes) segue correto


def test_pdf_so_com_acumulado_gera_e_textos_omitem_o_que_depende_de_nd():
    r = fontes.calcular({}, {"2026-04": _acum(PER, "2026-04")}, None, "2026-04")
    x, pdf = _pdf(r)
    n, txt = _texto_pdf(pdf)
    assert n == 12 and RP.fnum(r["d"]["acumulado"]["res_liq"]) in txt
    padrao = RD.textos_padrao(x)
    assert "dest_9" in padrao and "dados incompletos" in padrao["dest_9"]
    assert all(isinstance(v, str) for v in padrao.values())


def test_cobertura_diz_como_sai_o_relatorio_de_cada_mes():
    import lacunas
    linhas = lacunas.cobertura({k: PER[k] for k in ("2026-01", "2026-03", "2026-04")}, {"2026-04": _acum(PER, "2026-04")}, None)
    por_mes = {l["Mês"]: l for l in linhas}
    assert list(por_mes) == ["01/2026", "02/2026", "03/2026", "04/2026"]
    assert por_mes["01/2026"]["Relatório deste mês"] == "✅ completo"
    assert "sem balancete" in por_mes["02/2026"]["Relatório deste mês"]
    assert "n/d" in por_mes["03/2026"]["Relatório deste mês"]
    assert por_mes["04/2026"]["Relatório deste mês"].startswith("✅ completo")                # abril: acumulado + mensal cobrem tudo


# ---------- v0.5.2: periodo do relatorio (gerar ate' a lacuna / so' depois dela) ----------
SEM_FEV = {k: PER[k] for k in ("2026-01", "2026-03", "2026-04")}


def _soma_dre(ate_ini, ate_fim):
    tot = {}
    for m in range(ate_ini, ate_fim + 1):
        mes = fontes.calcular(PER, {}, None, f"2026-{m:02d}")["d"]["mes"]
        for k, v in mes.items():
            tot[k] = round(tot.get(k, 0) + v, 2)
    return tot


def test_opcoes_de_periodo_dizem_ate_onde_e_a_partir_de_onde_gerar():
    r = fontes.calcular(SEM_FEV, {}, None, "2026-04")
    assert fontes.opcoes_periodo(r, "2026-04") == {"faltam": ["2026-02"], "ate": "2026-01", "apos": "2026-03"}
    assert fontes.opcoes_periodo(CHEIO, "2026-04") is None                                   # completo: nada a oferecer
    r1 = fontes.calcular({k: PER[k] for k in ("2026-02", "2026-03", "2026-04")}, {}, None, "2026-04")      # falta janeiro: nao ha' "ate"
    o = fontes.opcoes_periodo(r1, "2026-04")
    assert o["ate"] is None and o["apos"] == "2026-02" and o["faltam"] == ["2026-01"]
    r4 = fontes.calcular({k: PER[k] for k in ("2026-01", "2026-02", "2026-03")}, {"2026-04": _acum(PER, "2026-04")}, None, "2026-04")
    o4 = fontes.opcoes_periodo(r4, "2026-04")
    assert o4 is None or o4["apos"] is None or o4["apos"] <= "2026-04"


def test_periodo_a_partir_de_marco_tem_abertura_em_28_02_e_dre_so_de_marco_e_abril():
    r = fontes.calcular(SEM_FEV, {}, None, "2026-04", 3)
    assert r["ini"] == 3 and not r["falhas"]
    fev = fontes.calcular(PER, {}, None, "2026-02")["bp"]["mes_ref"]
    _igual({"abertura": r["bp"]["abertura"], "mes_ref": r["bp"]["mes_ref"]}, {"abertura": fev, "mes_ref": CHEIO["bp"]["mes_ref"]}, ("abertura", "mes_ref"))
    _igual({"mes": r["d"]["mes"]}, {"mes": CHEIO["d"]["mes"]}, ("mes",))
    soma = _soma_dre(3, 4)
    assert r["d"]["acumulado"] is not None
    for k, v in soma.items():
        assert abs(r["d"]["acumulado"][k] - v) <= 0.011, k
    assert r["d"]["ate_mes_ant"] is not None and abs(r["d"]["ate_mes_ant"]["res_liq"] - _soma_dre(3, 3)["res_liq"]) <= 0.011


def test_periodo_a_partir_do_primeiro_mes_do_periodo_se_comporta_como_janeiro():
    r = fontes.calcular(SEM_FEV, {}, None, "2026-03", 3)
    fev = fontes.calcular(PER, {}, None, "2026-02")["bp"]["mes_ref"]
    _igual({"mes_ant": r["bp"]["mes_ant"], "abertura": r["bp"]["abertura"]}, {"mes_ant": fev, "abertura": fev}, ("mes_ant", "abertura"))
    assert all(abs(v) < 0.011 for v in r["d"]["ate_mes_ant"].values())
    _igual({"acumulado": r["d"]["acumulado"]}, {"acumulado": fontes.calcular(PER, {}, None, "2026-03")["d"]["mes"]}, ("acumulado",))


def test_periodo_ate_janeiro_nao_precisa_de_nada_que_falte():
    r = fontes.calcular(SEM_FEV, {}, None, "2026-01")
    _igual(r["bp"], fontes.calcular(PER, {}, None, "2026-01")["bp"], ("abertura", "mes_ant", "mes_ref"))
    assert not r["lacunas"] and r["fonte"] == "completo"


def test_periodo_sem_o_balancete_mensal_do_mes_inicial_bloqueia_e_diz_qual():
    with pytest.raises(fontes.ErroDados) as e:
        fontes.calcular(SEM_FEV, {}, None, "2026-04", 2)
    assert "02/2026" in str(e.value) and "mensal" in str(e.value)
    with pytest.raises(fontes.ErroDados):
        fontes.calcular(PER, {}, None, "2026-02", 3)                                         # inicio depois do mes do relatorio


def test_pdf_periodo_diz_o_que_e_e_nao_traz_n_d_do_que_foi_escolhido():
    r = fontes.calcular(SEM_FEV, {}, None, "2026-04", 3)
    x, pdf = _pdf(r)
    n, txt = _texto_pdf(pdf)
    t = txt.replace("\n", " ")
    assert "28/02/2026" in t and "cobre só o período de março a abril" in t
    assert RP.fnum(r["d"]["acumulado"]["res_liq"]) in txt
    assert "indisponível" not in txt
    assert all(isinstance(v, str) for v in RD.textos_padrao(x).values())


def test_pdf_ate_a_lacuna_e_um_relatorio_completo_de_janeiro():
    r = fontes.calcular(SEM_FEV, {}, None, "2026-01")
    x, pdf = _pdf(r, "2026-01")
    n, txt = _texto_pdf(pdf)
    assert n == 11 and "n/d" not in txt and "Dados incompletos" not in txt
