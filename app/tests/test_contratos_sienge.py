# -*- coding: utf-8 -*-
"""Contratos de suprimentos do Sienge (somente leitura): normalizacao, filtros, tabelas, pagina 'Obras e contratos' e ferramenta da Dexie. Sem rede: a API e' simulada."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import acesso
import contratos_sienge as CS
import dexie_ferramentas as FERR
import selecao as SEL

APP = Path(__file__).resolve().parent.parent


def _bruto_c(doc, num, forn, fid, obras, mo, ma, st="Aprovado", obj="Obra civil"):
    return {"documentId": doc, "contractNumber": num, "supplierId": fid, "supplierName": forn, "companyName": "Empresa X", "status": st, "statusApproval": "A", "isAuthorized": True,
            "contractDate": "2026-01-10T00:00:00", "startDate": "2026-02-01", "endDate": "2026-12-31", "object": obj, "contractType": "Empreitada",
            "totalLaborValue": mo, "totalMaterialValue": ma, "buildings": [{"buildingId": i, "name": n} for i, n in obras]}


def _bruto_m(doc, num, obra, n, mo, ma, liq, lib):
    return {"documentId": doc, "contractNumber": num, "buildingId": obra, "measurementNumber": n, "measurementDate": "2026-03-31", "dueDate": "2026-04-10",
            "totalLaborValue": mo, "totalMaterialValue": ma, "netValue": liq, "valueToRelease": lib, "authorized": True, "finalized": True, "released": False}


@pytest.fixture()
def dados():
    c = [_bruto_c("CT", "1", "Alfa Ltda", 10, [(104, "Lote 03")], 600, 400),
         _bruto_c("CT", "2", "Beta SA", 20, [(104, "Lote 03"), (109, "Angra")], 3000, 1000, st="Em andamento", obj="Terraplenagem"),
         _bruto_c("CT", "3", "Alfa Ltda", 10, [(109, "Angra")], 200, 0)]
    m = [_bruto_m("CT", "1", 104, 1, 300, 200, 480, 480), _bruto_m("CT", "2", 104, 1, 500, 100, 590, 0), _bruto_m("CT", "2", 109, 1, 400, 0, 390, 390)]
    return CS.normalizar(c, m)


def test_normalizar_campos_e_totais(dados):
    k = {c["chave"]: c for c in dados["contratos"]}
    assert set(k) == {"CT-1", "CT-2", "CT-3"} and k["CT-1"]["total"] == 1000 and k["CT-2"]["credor"] == "Beta SA"
    assert [o["id"] for o in k["CT-2"]["obras"]] == ["104", "109"] and k["CT-1"]["inicio"] == "2026-02-01" and k["CT-1"]["data"] == "2026-01-10"
    assert len(dados["medicoes"]) == 3 and dados["medicoes"][0]["bruto"] == 500


def test_normalizar_tolera_lixo():
    d = CS.normalizar([None, {"documentId": "CT"}, "x"], [None, {"contractNumber": 5}])
    assert d["contratos"][0]["credor"] == "(sem credor)" and d["contratos"][0]["total"] == 0 and len(d["contratos"]) == 1 and len(d["medicoes"]) == 1


def test_filtros_em_cascata(dados):
    assert {c["chave"] for c in CS.filtrar(dados, obras=["109"])} == {"CT-2", "CT-3"}
    assert {c["chave"] for c in CS.filtrar(dados, obras=["109"], credores=["10"])} == {"CT-3"}
    assert {c["chave"] for c in CS.filtrar(dados, situacoes=["Em andamento"])} == {"CT-2"}
    assert {c["chave"] for c in CS.filtrar(dados, busca="terraplen")} == {"CT-2"} and {c["chave"] for c in CS.filtrar(dados, busca="angra")} == {"CT-2", "CT-3"}


def test_tabelas_obras_credores_contratos(dados):
    o = CS.df_obras(dados).set_index("Obra")
    assert o.loc["Lote 03", "Contratos"] == 2 and o.loc["Lote 03", "Contratado"] == 5000 and o.loc["Lote 03", "Medido"] == 1100          # CT-1 (1000) + CT-2 (4000); medicoes da obra 104
    assert o.loc["Angra", "Compartilhados"] == 1 and o.loc["Angra", "Medido"] == 400 and abs(o.loc["Lote 03", "% medido"] - 0.22) < 1e-9
    c = CS.df_credores(dados).set_index("Credor")
    assert c.loc["Alfa Ltda", "Contratos"] == 2 and c.loc["Alfa Ltda", "Contratado"] == 1200 and c.loc["Beta SA", "Medido"] == 1000
    c109 = CS.df_credores(dados, ["109"]).set_index("Credor")                    # so' contratos da obra 109 e medicao dela
    assert c109.loc["Beta SA", "Medido"] == 400 and c109.loc["Beta SA", "Contratado"] == 4000 and "Alfa Ltda" in c109.index
    k = CS.df_contratos(dados["contratos"], dados["medicoes"]).set_index("Contrato")
    assert k.loc["CT-2", "Medido"] == 1000 and k.loc["CT-2", "Saldo"] == 3000 and k.loc["CT-1", "A liberar"] == 480
    k109 = CS.df_contratos(dados["contratos"], dados["medicoes"], ["109"]).set_index("Contrato")
    assert k109.loc["CT-2", "Medido"] == 400 and k109["Saldo"].isna().all()
    m = CS.df_medicoes(dados["medicoes"], ["CT-2"], ["109"], {"109": "Angra"})
    assert len(m) == 1 and m.iloc[0]["Obra"] == "Angra" and m.iloc[0]["Valor líquido"] == 390


def test_paginar_junta_todas_as_paginas():
    class Cli:
        def __init__(self): self.pedidos = []
        def get(self, caminho, params):
            self.pedidos.append(params["offset"])
            tot = 5
            return {"resultSetMetadata": {"count": tot}, "results": list(range(params["offset"], min(params["offset"] + params["limit"], tot)))}
    cli = Cli()
    assert CS._paginar(cli, "x", limite=2) == [0, 1, 2, 3, 4] and cli.pedidos == [0, 2, 4]


def test_anexos_so_lista_e_guarda(monkeypatch):
    CS.limpar()
    chamadas = []

    class Cli:
        def get(self, caminho, params):
            chamadas.append((caminho, params))
            return {"results": [{"contractAttachmentNumber": 1, "name": "contrato.pdf", "description": "assinado"}]}
    a = CS.anexos("CT", "7", Cli())
    assert a == [{"n": "1", "nome": "contrato.pdf", "descricao": "assinado"}] and chamadas[0][0] == "v1/supply-contracts/attachments/all"
    assert chamadas[0][1] == {"documentId": "CT", "contractNumber": "7", "limit": 200, "offset": 0}
    CS.anexos("CT", "7", Cli())
    assert len(chamadas) == 1                                                     # segunda vez vem da memoria


def test_carregar_guarda_por_uma_hora(monkeypatch, dados):
    CS.limpar()
    n = []
    monkeypatch.setattr(CS, "baixar", lambda cli=None: (n.append(1), dados)[1])
    assert CS.carregar() is dados and CS.carregar() is dados and len(n) == 1
    CS.carregar(forcar=True)
    assert len(n) == 2


def test_dexie_ferramenta_contratos(monkeypatch, dados):
    monkeypatch.setattr(CS, "carregar", lambda forcar=False: dados)
    r, tab = FERR.executar(None, "contratos", {})
    assert "erro" not in r and r["contratos_no_recorte"] == 3 and r["contratado"] == 5200 and tab
    r2, _ = FERR.executar(None, "contratos", {"obra_contem": "angra", "credor_contem": "beta"})
    assert r2["contratos_no_recorte"] == 1 and r2["contratos"][0]["contrato"] == "CT-2" and r2["medido"] == 400
    r3, _ = FERR.executar(None, "contratos", {"agrupar_por": "credor"})
    assert {x["credor"] for x in r3["grupos"]} == {"Alfa Ltda", "Beta SA"}
    r4, _ = FERR.executar(None, "contratos", {"credor_contem": "nao existe"})
    assert r4["contratos_no_recorte"] == 0 and "aviso" in r4


@pytest.mark.pg
def test_pagina_obras_e_contratos_so_editor_e_caixinhas(conn, dados):
    CS.limpar()
    acesso.definir(conn, "diretor@empresa.com", acesso.VISUALIZADOR, True, "rafael@x")
    with patch("conexao.get_conn", return_value=conn), patch.object(CS, "carregar", lambda forcar=False: dados):
        v = AppTest.from_file(str(APP / "telas" / "12_Obras_Contratos.py"), default_timeout=60)
        v.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="diretor@empresa.com"))
        v.run()
        assert not v.exception and any("só para quem edita" in e.value for e in v.error) and not v.dataframe
        e = AppTest.from_file(str(APP / "telas" / "12_Obras_Contratos.py"), default_timeout=60)
        e.session_state["auth_session"] = SimpleNamespace(user=SimpleNamespace(email="contabilidade@empresa.com"))
        e.run()
        assert not e.exception, e.exception
        assert len(e.tabs) == 0 and len(e.dataframe) >= 3                      # sem abas: tudo na mesma tela, de cima para baixo
        assert [m.value for m in e.markdown if m.value.startswith("### ")][:3] == ["### 1 · Obras", "### 2 · Credores · todas as obras", "### 3 · Contratos · todas as obras · todos os credores"]
        obras = e.dataframe[0].value
        assert set(obras["Obra"]) == {"Lote 03", "Angra"}
        # marca a obra "Angra" -> credores e contratos acompanham
        pos = list(obras["Obra"]).index("Angra")
        chave_o = SEL.chave("oc_obras", "", (), False)
        e.session_state[chave_o] = {"selection": {"rows": [pos], "columns": []}}
        e.run()
        assert not e.exception, e.exception
        creds = [d.value for d in e.dataframe if "Credor" in d.value.columns and "Obras" in d.value.columns and "Contratos" in d.value.columns][0]
        assert set(creds["Credor"]) == {"Alfa Ltda", "Beta SA"}
        contratos = [d.value for d in e.dataframe if "Contrato" in d.value.columns and "Situação" in d.value.columns][0]
        assert "Saldo" not in contratos.columns                                  # com obra marcada o saldo não existe (nada de "None" na tela)
        assert set(contratos["Contrato"]) == {"CT-2", "CT-3"}
        # marca o contrato CT-2 -> aparecem as medicoes
        chave_k = SEL.chave("oc_contr", "", (), False, ("109",), ())
        e.session_state[chave_o] = {"selection": {"rows": [pos], "columns": []}}                # o AppTest nao guarda a marcacao entre execucoes: repete
        e.session_state[chave_k] = {"selection": {"rows": [list(contratos["Contrato"]).index("CT-2")], "columns": []}}
        e.run()
        assert not e.exception, e.exception
        assert any("Medições dos contratos marcados" in m.value for m in e.markdown)
        med = [d.value for d in e.dataframe if "Medição" in d.value.columns][0]
        assert len(med) == 1 and med.iloc[0]["Obra"] == "Angra"


def test_situacoes_da_api_em_portugues():
    assert CS._pt("PARTIALLY_MEASURED") == "Parcialmente medido" and CS._pt("COMPLETED") == "Concluído" and CS._pt("APPROVED") == "Aprovada"
    assert CS._pt("SOMETHING_NEW") == "Something new" and CS._pt("Em andamento") == "Em andamento" and CS._pt(None) == ""


def test_pendentes_e_cancelados_ficam_fora_dos_totais_por_padrao(monkeypatch):
    c = [_bruto_c("CT", "1", "Alfa Ltda", 10, [(104, "Lote 03")], 600, 400),
         _bruto_c("CT", "9", None, None, [(104, "Lote 03")], 40000, 0, st="PENDING", obj="Contrato modelo"),
         _bruto_c("CT", "8", "Gama", 30, [(104, "Lote 03")], 100, 0, st="CANCELED")]
    d = CS.normalizar(c, [])
    assert [x["chave"] for x in CS.filtrar(d, incluir_inativos=False)] == ["CT-1"]
    assert len(CS.filtrar(d)) == 3 and len(CS.filtrar(d, incluir_inativos=False, situacoes=["Pendente"])) == 1      # situacao escolhida a dedo sempre vale
    assert CS.fora_do_calculo(d) == {"contratos": 2, "total": 40100.0, "sem_credor": 1}
    monkeypatch.setattr(CS, "carregar", lambda forcar=False: d)
    r, _ = FERR.executar(None, "contratos", {})
    assert r["contratado"] == 1000 and r["pendentes_e_cancelados"]["fora_dos_totais"]["contratos"] == 2
    r2, _ = FERR.executar(None, "contratos", {"incluir_pendentes": True})
    assert r2["contratado"] == 41100 and r2["pendentes_e_cancelados"] == "incluidos"
    r3, _ = FERR.executar(None, "contratos", {"situacao_contem": "pendente"})
    assert r3["contratos_no_recorte"] == 1 and r3["contratado"] == 40000
