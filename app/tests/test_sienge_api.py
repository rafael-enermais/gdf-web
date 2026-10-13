# -*- coding: utf-8 -*-
"""Cliente e normalizacao da API do Sienge (sem banco). O cliente e' testado contra um servidor HTTP local de mentira."""
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import sienge_api as S
from dados_sienge import income, outcome


def test_cod_plano_com_e_sem_pontos():
    assert S.cod_plano("2020212") == "2.02.02.12"
    assert S.cod_plano("205010159") == "2.05.01.01.59"
    assert S.cod_plano("1.03.02.02") == "1.03.02.02"
    assert S.cod_plano("101") == "1.01"
    assert S.cod_plano(None) == ""


def test_normalizar_pagar():
    n = S.normalizar_titulos("P", outcome())
    assert len(n["titulos"]) == 4 and len(n["baixas"]) == 5 and len(n["rateios"]) == 5
    t1 = n["titulos"][0]
    assert (t1["lado"], t1["bill_id"], t1["installment_id"], t1["doc_id"], t1["data_emissao"]) == ("P", 1, 1, "NFS", dt.date(2026, 8, 20))
    assert t1["contraparte_nome"] == "FORNECEDOR TESTE" and t1["valor_original"] == 1000.0
    r = [x for x in n["rateios"] if x["bill_id"] == 1]
    assert [x["plano_cod"] for x in r] == ["2.01.01.04", "2.01.04.04"] and sum(x["percentual"] for x in r) == 100
    assert {x["tipo_oper_id"] for x in n["baixas"]} == {1, 3}


def test_normalizar_receber():
    n = S.normalizar_titulos("R", income())
    assert n["titulos"][0]["contraparte_nome"] == "CLIENTE TESTE" and n["baixas"][0]["liquido"] == 1800.0 and n["rateios"][0]["plano_cod"] == "1.01.01.01"


def test_normalizar_ignora_registro_sem_numero_e_baixa_sem_sequencial():
    regs = [{"foo": 1}, {"billId": 9, "installmentId": 1, "payments": [{"paymentDate": "2026-09-01", "netAmount": 1}, {"paymentDate": "2026-09-02", "netAmount": 2}]}]
    n = S.normalizar_titulos("P", regs)
    assert len(n["titulos"]) == 1 and len({b["seq"] for b in n["baixas"]}) == 2


def test_normalizar_baixa_repetida_no_mesmo_titulo():
    """Mesmo sequencialNumber no mesmo titulo: copia identica e' ignorada; conteudo diferente vira baixa nova com numero fixo."""
    ig = {"sequencialNumber": 1, "paymentDate": "2026-09-01", "netAmount": 10}
    regs = [{"billId": 9, "installmentId": 1, "payments": [ig, dict(ig), {"sequencialNumber": 1, "paymentDate": "2026-09-05", "netAmount": 7},
                                                         {"sequencialNumber": 2, "paymentDate": "2026-09-06", "netAmount": 3}]}]
    n = S.normalizar_titulos("P", regs)
    seqs = sorted(b["seq"] for b in n["baixas"])
    assert len(seqs) == 3 and len(set(seqs)) == 3 and seqs[:2] == [1, 2]
    assert n["avisos"]["baixas_copia_ignorada"] == 1 and n["avisos"]["baixas_renumeradas"] == 1
    assert sorted(S.normalizar_titulos("P", regs)["baixas"], key=lambda b: b["seq"]) == sorted(n["baixas"], key=lambda b: b["seq"])  # repetivel


def test_normalizar_titulo_repetido_e_ignorado():
    regs = [{"billId": 5, "installmentId": 1}, {"billId": 5, "installmentId": 1}, {"billId": 5, "installmentId": 2}]
    n = S.normalizar_titulos("P", regs)
    assert len(n["titulos"]) == 2 and n["avisos"]["titulos_repetidos_ignorados"] == 1


def test_normalizar_cadastros():
    c = S.normalizar_cadastros({"empresas": [{"id": 5, "name": "CONSTRUTORA", "cnpj": "x"}], "centros_custo": [{"id": 1049, "name": "CC", "idCompany": 5}],
                                "plano": [{"id": "2010104", "name": "Material", "tpConta": "R", "flRedutora": "N", "flAtiva": "S"}],
                                "tipos_negocio": [{"businessTypeId": 10, "description": "CONSTRUTORA - OBRAS"}]})
    assert c["plano"][0]["codigo"] == "2.01.01.04" and c["plano"][0]["ativa"] is True and c["plano"][0]["redutora"] is False
    assert c["centros_custo"][0]["empresa_id"] == 5 and c["tipos_negocio"][0]["id"] == 10


def test_credenciais_faltando_e_montagem_da_url():
    with pytest.raises(S.ErroSienge, match="SIENGE_USER"):
        S.credenciais({}, {})
    u, p, base = S.credenciais({"SIENGE_USER": "empresa-api", "SIENGE_PASSWORD": "segredo123"}, {})
    assert base == "https://api.sienge.com.br/empresa/public/api" and (u, p) == ("empresa-api", "segredo123")
    assert S.credenciais({"SIENGE_USER": "a-b", "SIENGE_PASSWORD": "segredo123", "SIENGE_BASE_URL": "http://x/y/"}, {})[2] == "http://x/y"


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if "/ok" in self.path:
            corpo, cod = json.dumps({"results": [{"id": 1}]}), 200
        else:
            corpo, cod = json.dumps({"clientMessage": "Permission denied para segredo123"}), 403
        self.send_response(cod)
        self.end_headers()
        self.wfile.write(corpo.encode())


@pytest.fixture()
def servidor():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_cliente_ok_e_erro_sem_vazar_a_chave(servidor):
    cli = S.Cliente("usuario-api", "segredo123", servidor)
    assert S.lista(cli.get("/ok")) == [{"id": 1}]
    with pytest.raises(S.ErroSienge) as e:
        cli.get("/negado")
    msg = str(e.value)
    assert "403" in msg and "permissão" in msg and "segredo123" not in msg


def test_cliente_rede_fora_do_ar():
    cli = S.Cliente("usuario-api", "segredo123", "http://127.0.0.1:9")
    with pytest.raises(S.ErroSienge, match="Não consegui falar"):
        cli.get("/x")


class _H429(BaseHTTPRequestHandler):
    vezes = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        _H429.vezes += 1
        if _H429.vezes <= 2:
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message":"API rate limit exceeded"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'[{"id": 7}]')


def _servidor_429():
    _H429.vezes = 0
    srv = HTTPServer(("127.0.0.1", 0), _H429)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_cliente_429_tenta_de_novo_com_espera():
    srv = _servidor_429()
    try:
        dormiu = []
        cli = S.Cliente("usuario-api", "segredo123", f"http://127.0.0.1:{srv.server_port}", esperas_429=(5, 10, 20), dormir=dormiu.append)
        assert S.lista(cli.get("/x")) == [{"id": 7}]
        assert dormiu == [5, 10] and _H429.vezes == 3
    finally:
        srv.shutdown()


def test_cliente_429_sem_esperas_falha_com_mensagem_simples_e_esgotando_tentativas():
    srv = _servidor_429()
    try:
        with pytest.raises(S.ErroSienge, match="429"):
            S.Cliente("u-api", "segredo123", f"http://127.0.0.1:{srv.server_port}").get("/x")
        _H429.vezes = -100                                           # sempre 429
        with pytest.raises(S.ErroSienge, match="esgotei"):
            S.Cliente("u-api", "segredo123", f"http://127.0.0.1:{srv.server_port}", esperas_429=(1, 1), dormir=lambda s: None).get("/x")
    finally:
        srv.shutdown()


def test_cliente_pausa_entre_chamadas():
    srv = _servidor_429()
    try:
        _H429.vezes = 10                                             # so 200
        dormiu = []
        cli = S.Cliente("u-api", "segredo123", f"http://127.0.0.1:{srv.server_port}", pausa=5, dormir=dormiu.append)
        cli.get("/a"); cli.get("/b")
        assert len(dormiu) == 1 and 0 < dormiu[0] <= 5
    finally:
        srv.shutdown()
