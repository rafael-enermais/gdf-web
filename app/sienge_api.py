# -*- coding: utf-8 -*-
"""
GDF V2 - cliente SOMENTE-LEITURA da API do Sienge + normalizacao dos dados para as tabelas pnl_*.
Sem streamlit e sem banco: so' HTTP (urllib, biblioteca padrao) e funcoes puras (testaveis).

Seguranca: usuario e chave vem de st.secrets / variaveis de ambiente (SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL opcional);
nunca ficam no repositorio. Este modulo so' faz GET; nao existe nenhuma chamada de escrita no Sienge.
"""
from __future__ import annotations

import base64
import calendar
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# Tipos de data aceitos pela API (descobertos na sondagem de 13/10/2026):
#   contas pagas   (bulk-data/v1/outcome): I emissao, D vencimento, P pagamento
#   contas a receber (bulk-data/v1/income): I emissao, D vencimento, P recebimento, B data do titulo, C credito
ENDPOINT = {"P": "bulk-data/v1/outcome", "R": "bulk-data/v1/income"}


class ErroSienge(Exception):
    """Falha ao falar com o Sienge (mensagem em linguagem simples; nunca contem a chave)."""


def credenciais(secrets=None, ambiente=None) -> tuple:
    """(usuario, senha, base_url). `secrets` = st.secrets (ou dict). Levanta ErroSienge se faltar."""
    ambiente = os.environ if ambiente is None else ambiente

    def pegar(nome):
        try:
            if secrets is not None and nome in secrets:
                return str(secrets[nome]).strip()
        except Exception:
            pass
        return str(ambiente.get(nome, "")).strip()

    user, pwd, base = pegar("SIENGE_USER"), pegar("SIENGE_PASSWORD"), pegar("SIENGE_BASE_URL")
    if not user or not pwd:
        raise ErroSienge("Faltam os secrets SIENGE_USER e SIENGE_PASSWORD (Streamlit Cloud → Settings → Secrets). "
                         "A chave NUNCA vai para o repositório.")
    if not base:
        sub = user.split("-")[0] if "-" in user else ""
        if not sub:
            raise ErroSienge("Não consegui montar a URL do Sienge a partir do usuário; cadastre também SIENGE_BASE_URL.")
        base = f"https://api.sienge.com.br/{sub}/public/api"
    return user, pwd, base.rstrip("/")


class _Limite(Exception):
    """Interno: o Sienge pediu para esperar (HTTP 429)."""

    def __init__(self, espera: float = 0.0):
        super().__init__("429")
        self.espera = espera


class Cliente:
    def __init__(self, user: str, pwd: str, base: str, timeout: int = 240, pausa: float = 0, esperas_429: tuple = (), dormir=time.sleep):
        """pausa = segundos minimos entre duas chamadas; esperas_429 = segundos de espera a cada nova tentativa quando o Sienge
        responde HTTP 429 (limite de requisicoes). O padrao (sem pausa, sem nova tentativa) serve para o botao do app;
        a rotina diaria usa pausa e esperas (ver scripts/ingest_sienge_gdf.py)."""
        self.base, self.timeout = base.rstrip("/"), timeout
        self.pausa, self.esperas_429, self._dormir, self._ultima = pausa, tuple(esperas_429), dormir, 0.0
        self._segredos = [user, pwd]
        tok = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
        self._cab = {"Authorization": "Basic " + tok, "Accept": "application/json"}

    def _limpar(self, txt) -> str:
        txt = str(txt)
        for s in self._segredos:
            if s and len(s) >= 4:
                txt = txt.replace(s, "***")
        return txt

    def get(self, caminho: str, params: dict | None = None):
        """GET -> JSON. Erros viram ErroSienge com mensagem simples (401/403/422/429/rede). Com `esperas_429`, o 429 e' tentado de novo."""
        tentativa = 0
        while True:
            try:
                return self._get_uma_vez(caminho, params)
            except _Limite as lim:
                if tentativa >= len(self.esperas_429):
                    raise ErroSienge(f"Sienge respondeu HTTP 429 (limite de requisições por minuto) em {caminho}; esgotei as novas tentativas.") from None
                self._dormir(max(self.esperas_429[tentativa], lim.espera))
                tentativa += 1

    def _get_uma_vez(self, caminho: str, params: dict | None = None):
        if self.pausa:
            falta = self.pausa - (time.monotonic() - self._ultima)
            if falta > 0 and self._ultima:
                self._dormir(falta)
        self._ultima = time.monotonic()
        url = self.base + "/" + caminho.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._cab, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and self.esperas_429:
                try:
                    espera = float(e.headers.get("Retry-After") or 0)
                except Exception:
                    espera = 0.0
                raise _Limite(espera) from None
            corpo = e.read().decode("utf-8", errors="replace")
            msg = ""
            try:
                j = json.loads(corpo)
                msg = j.get("clientMessage") or j.get("developerMessage") or j.get("message") or ""
            except Exception:
                pass
            dica = {401: "usuário/chave recusados", 403: "a chave não tem permissão para este recurso", 429: "limite de requisições por minuto",
                    404: "caminho não existe", 422: "parâmetro inválido"}.get(e.code, "erro do Sienge")
            raise ErroSienge(f"Sienge respondeu HTTP {e.code} ({dica}) em {caminho}. {self._limpar(msg)[:200]}") from None
        except Exception as e:
            raise ErroSienge(f"Não consegui falar com o Sienge ({self._limpar(e)[:150]}).") from None


def lista(resposta) -> list:
    if isinstance(resposta, list):
        return resposta
    if isinstance(resposta, dict):
        for k in ("results", "data", "items", "content"):
            if isinstance(resposta.get(k), list):
                return resposta[k]
    return []


def limites_do_mes(mes: str) -> tuple:
    """'2026-09' -> (date(2026,9,1), date(2026,9,30))."""
    ano, m = int(mes[:4]), int(mes[5:7])
    return dt.date(ano, m, 1), dt.date(ano, m, calendar.monthrange(ano, m)[1])


def buscar_bulk(cli: Cliente, lado: str, mes: str, tipo_data: str, mes_fim: str | None = None) -> list:
    """Titulos do mes (lado 'P' = a pagar, 'R' = a receber) pelo tipo de data escolhido, com baixas e rateios.
    Com `mes_fim`, busca a janela inteira de `mes` ate `mes_fim` numa chamada so (medido: 3 meses = 5,3 mil titulos, 15 MB, 7 s)."""
    ini, _ = limites_do_mes(mes)
    _, fim = limites_do_mes(mes_fim or mes)
    params = {"startDate": ini.isoformat(), "endDate": fim.isoformat(), "selectionType": tipo_data,
              "correctionIndexerId": "0", "correctionDate": fim.isoformat(), "withBankMovements": "true"}
    return lista(cli.get(ENDPOINT[lado], params))


# ---- titulos EM ABERTO por data de vencimento (alem da janela de 365 dias da rotina diaria) --------------------------------------------------
# A rotina diaria busca por pagamento (P) e por emissao (I). Isso nao traz (a) titulos emitidos antes da janela e ainda nao pagos (inadimplencia antiga) nem
# (b) parcelas futuras de contratos antigos (financiamentos). Esta busca por VENCIMENTO (D), so' dos titulos ainda em aberto, completa o quadro.
def janelas_abertos(ini: str, fim: str) -> list:
    """Divide 'AAAA-MM'..'AAAA-MM' em janelas de 3 meses (ate dez/2026, onde ha muito titulo) e de 12 meses depois (poucos titulos). [(mes_ini, mes_fim)]."""
    a, b = (int(ini[:4]), int(ini[5:7])), (int(fim[:4]), int(fim[5:7]))
    out = []
    while a <= b:
        passo = 3 if a < (2027, 1) else 12
        z = a[0] * 12 + (a[1] - 1) + passo - 1
        fim_j = (z // 12, z % 12 + 1)
        if fim_j > b:
            fim_j = b
        out.append((f"{a[0]:04d}-{a[1]:02d}", f"{fim_j[0]:04d}-{fim_j[1]:02d}"))
        z2 = fim_j[0] * 12 + fim_j[1]
        a = (z2 // 12, z2 % 12 + 1)
    return out


def somente_abertos(regs: list, lado: str) -> list:
    """Fica so' o titulo cujo valor ainda nao foi todo baixado (soma das baixas < valor original). Funcao pura."""
    campo = "payments" if lado == "P" else "receipts"
    out = []
    for r in regs:
        if not isinstance(r, dict) or r.get("billId") is None:
            continue
        pago = sum(_num(x.get("grossAmount")) or 0.0 for x in (r.get(campo) or []))
        if (_num(r.get("originalAmount")) or 0.0) - pago > 0.01:
            out.append(r)
    return out


ENDPOINT_BANCO = "bulk-data/v1/bank-movement"
DOC_AVISO = ("AV", "AVISO DE LANÇAMENTO")


def buscar_movimento_banco(cli: Cliente, mes: str, mes_fim: str | None = None) -> list:
    """Movimentos bancarios (por data do movimento) do mes, ou da janela de `mes` ate `mes_fim` numa chamada so.
    Traz tambem os 'avisos de lancamento' (juros, tarifas, transferencias) que a busca de contas pagas nao devolve."""
    ini, _ = limites_do_mes(mes)
    _, fim = limites_do_mes(mes_fim or mes)
    return lista(cli.get(ENDPOINT_BANCO, {"startDate": ini.isoformat(), "endDate": fim.isoformat(), "selectionType": "M"}))


def buscar_cadastros(cli: Cliente) -> dict:
    """Cadastros que o painel usa. Centros de custo vem em paginas de 200; plano e tipos de negocio vem inteiros."""
    out = {"empresas": lista(cli.get("v1/companies", {"limit": 200})),
           "plano": lista(cli.get("v1/payment-categories", {"limit": 200})),
           "tipos_negocio": lista(cli.get("v1/business-types", {"limit": 200}))}
    ccs, off = [], 0
    while off < 5000:
        pag = lista(cli.get("v1/cost-centers", {"limit": 200, "offset": off}))
        ccs += pag
        if len(pag) < 200:
            break
        off += 200
        time.sleep(0.3)
    out["centros_custo"] = ccs
    return out


ENDPOINT_OBRAS = "v1/enterprises"


def buscar_obras(cli: Cliente) -> list:
    """Obras (empreendimentos) do cadastro do Sienge, em paginas de 200. Se a chave nao tiver permissao neste recurso, o Cliente levanta ErroSienge
    (quem chama mostra o aviso e segue: o resto dos cadastros nao depende disso)."""
    obras, off = [], 0
    while off < 5000:
        pag = lista(cli.get(ENDPOINT_OBRAS, {"limit": 200, "offset": off}))
        obras += pag
        if len(pag) < 200:
            break
        off += 200
        time.sleep(0.3)
    return obras


ENDPOINT_CREDORES = "v1/creditors"


def buscar_credores(cli: Cliente) -> list:
    """Credores do cadastro do Sienge, em paginas de 200 (so' para pegar o nome fantasia). Se a chave nao tiver permissao neste recurso, o Cliente levanta ErroSienge."""
    regs, off = [], 0
    while off < 100000:
        pag = lista(cli.get(ENDPOINT_CREDORES, {"limit": 200, "offset": off}))
        regs += pag
        if len(pag) < 200:
            break
        off += 200
        time.sleep(0.2)
    return regs


# ---------------------------------------------------------------- normalizacao (funcoes puras)
def cod_plano(i) -> str:
    """O Sienge devolve o plano financeiro as vezes sem pontos (2020212) e os relatorios com pontos (2.02.02.12)."""
    i = str(i or "").strip()
    if not i or "." in i:
        return i
    return i[0] + "." + ".".join(i[k:k + 2] for k in range(1, len(i), 2))


def _num(v):
    try:
        return round(float(v), 2)
    except Exception:
        return None


def _data(v):
    s = str(v or "")[:10]
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        return None


def _sn(v):
    """'S'/'N' (ou true/false) do Sienge -> bool; vazio -> None."""
    if v in (None, ""):
        return None
    return str(v).strip().upper() in ("S", "Y", "TRUE", "1")


def _int(v):
    try:
        return int(v)
    except Exception:
        return None


def normalizar_titulos(lado: str, regs: list) -> dict:
    """regs = lista devolvida por buscar_bulk. Devolve {'titulos': [...], 'baixas': [...], 'rateios': [...]} (dicts simples)."""
    contra_id, contra_nome = ("creditorId", "creditorName") if lado == "P" else ("clientId", "clientName")
    baixa_lista, rateio_lista = ("payments", "paymentsCategories") if lado == "P" else ("receipts", "receiptsCategories")
    tit, bx, rt = [], [], []
    avisos = {"baixas_copia_ignorada": 0, "baixas_renumeradas": 0, "titulos_repetidos_ignorados": 0}
    titulos_vistos = set()
    for b in regs:
        if not isinstance(b, dict) or b.get("billId") is None:
            continue
        chave = {"lado": lado, "bill_id": int(b["billId"]), "installment_id": int(b.get("installmentId") or 0)}
        k = (chave["bill_id"], chave["installment_id"])
        if k in titulos_vistos:                             # o Sienge nao deveria repetir o titulo; se repetir, evita o erro de chave dupla
            avisos["titulos_repetidos_ignorados"] += 1
            continue
        titulos_vistos.add(k)
        tit.append({**chave,
                    "empresa_id": _int(b.get("companyId")), "empresa_nome": b.get("companyName"),
                    "origem": (b.get("originId") or "").strip() or None,
                    "doc_id": (b.get("documentIdentificationId") or "").strip() or None,
                    "doc_nome": (b.get("documentIdentificationName") or "").strip() or None,
                    "previsao": str((b.get("forecastDocument") if lado == "P" else b.get("documentForecast")) or "") or None,
                    "numero_doc": str(b.get("documentNumber") or "").strip() or None,
                    "contraparte_id": _int(b.get(contra_id)), "contraparte_nome": b.get(contra_nome),
                    "data_emissao": _data(b.get("issueDate")), "data_vencimento": _data(b.get("dueDate")),
                    "valor_original": _num(b.get("originalAmount")),
                    "imposto_titulo": _num(b.get("taxAmount")) if lado == "R" else None,       # impostos da NF (ISS/PIS/COFINS): base do DRE 02.02
                    "tipo_negocio_id": _int(b.get("businessTypeId")), "tipo_negocio_nome": b.get("businessTypeName"),
                    "area_id": _int(b.get("businessAreaId")), "area_nome": b.get("businessAreaName"),
                    "projeto_id": _int(b.get("projectId")), "projeto_nome": b.get("projectName")})
        vistas = {}                                        # seq -> conteudos ja vistos neste titulo
        for i, p in enumerate(b.get(baixa_lista) or []):
            seq = _int(p.get("sequencialNumber"))
            seq = seq if seq is not None else 1000 + i
            conteudo = json.dumps(p, sort_keys=True, default=str)
            ja = vistas.setdefault(seq, [])
            if conteudo in ja:                              # copia identica (mesma baixa repetida pelo Sienge): ignora
                avisos["baixas_copia_ignorada"] += 1
                continue
            if ja:                                          # mesmo numero, conteudo diferente: sao baixas distintas -> numero novo e fixo
                avisos["baixas_renumeradas"] += 1
                seq_gravado = seq + 100000 * len(ja)
            else:
                seq_gravado = seq
            ja.append(conteudo)
            bx.append({**chave, "seq": seq_gravado,
                       "data_pagamento": _data(p.get("paymentDate") or p.get("creditDate")),
                       "tipo_oper_id": _int(p.get("operationTypeId")), "tipo_oper_nome": p.get("operationTypeName"),
                       "bruto": _num(p.get("grossAmount")), "liquido": _num(p.get("netAmount")),
                       "juros": _num(p.get("interestAmount")), "multa": _num(p.get("fineAmount")),
                       "desconto": _num(p.get("discountAmount")), "imposto": _num(p.get("taxAmount")),
                       "correcao": _num(p.get("monetaryCorrectionAmount"))})
        for i, c in enumerate(b.get(rateio_lista) or []):
            rt.append({**chave, "linha": i, "plano_cod": cod_plano(c.get("financialCategoryId")),
                       "plano_nome": c.get("financialCategoryName"),
                       "centro_custo_id": _int(c.get("costCenterId")), "centro_custo_nome": c.get("costCenterName"),
                       "percentual": float(c.get("financialCategoryRate") or 0)})
    return {"titulos": tit, "baixas": bx, "rateios": rt, "avisos": avisos}


def normalizar_movimentos(regs: list) -> dict:
    """Movimentos bancarios -> o mesmo formato de normalizar_titulos('P', ...), para entrar nas mesmas tabelas e telas.
    Fica SO o que a busca de contas pagas nao traz: saida (tipo 'S'), SEM titulo (billId vazio) e COM plano financeiro
    (juros, tarifas, transferencias entre empresas...). Cada movimento vira um 'titulo' de numero negativo (-id do movimento: nunca
    colide com um titulo real) com uma baixa e os rateios dele. Documento AV = aviso de lancamento, previsao N."""
    tit, bx, rt, vistos = [], [], [], set()
    for m in regs:
        if not isinstance(m, dict) or m.get("bankMovementId") in (None, ""):
            continue
        if m.get("billId") not in (None, 0, "") or str(m.get("bankMovementOperationType") or "").upper() != "S":
            continue
        cats = [c for c in (m.get("financialCategories") or []) if isinstance(c, dict)]
        if not cats:
            continue
        mid = int(m["bankMovementId"])
        if mid in vistos:
            continue
        vistos.add(mid)
        chave = {"lado": "P", "bill_id": -mid, "installment_id": 1}
        valor = _num(m.get("bankMovementAmount"))
        data = _data(m.get("bankMovementDate"))
        tit.append({**chave, "empresa_id": _int(m.get("companyId")), "empresa_nome": m.get("companyName"),
                    "origem": (str(m.get("bankMovementOriginId") or "").strip() or "BC"),
                    "doc_id": (str(m.get("documentIdentificationId") or "").strip() or DOC_AVISO[0]),
                    "doc_nome": (str(m.get("documentIdentificationName") or "").strip() or DOC_AVISO[1]),
                    "previsao": "N", "numero_doc": str(m.get("documentIdentificationNumber") or "").strip() or None,
                    "contraparte_id": None, "contraparte_nome": None, "data_emissao": data, "data_vencimento": data, "valor_original": valor,
                    "tipo_negocio_id": None, "tipo_negocio_nome": None, "area_id": None, "area_nome": None,
                    "projeto_id": _int(m.get("companyId")), "projeto_nome": m.get("companyName")})
        bx.append({**chave, "seq": 1, "data_pagamento": data, "tipo_oper_id": 1000 + (_int(m.get("bankMovementOperationId")) or 0),
                   "tipo_oper_nome": "Mov. bancário: " + str(m.get("bankMovementOperationName") or ""),
                   "bruto": valor, "liquido": valor, "juros": None, "multa": None, "desconto": None, "imposto": None, "correcao": None})
        for i, c in enumerate(cats):
            rt.append({**chave, "linha": i, "plano_cod": cod_plano(c.get("financialCategoryId")), "plano_nome": c.get("financialCategoryName"),
                       "centro_custo_id": _int(c.get("costCenterId")), "centro_custo_nome": c.get("costCenterName"),
                       "percentual": float(c.get("financialCategoryRate") or 0)})
    return {"titulos": tit, "baixas": bx, "rateios": rt, "avisos": {}}


def normalizar_cadastros(c: dict) -> dict:
    return {
        "empresas": [{"id": int(x["id"]), "nome": x.get("name") or x.get("tradeName") or "", "cnpj": x.get("cnpj")}
                     for x in c.get("empresas", []) if isinstance(x, dict) and x.get("id") is not None],
        "centros_custo": [{"id": int(x["id"]), "nome": x.get("name") or "", "empresa_id": _int(x.get("idCompany"))}
                          for x in c.get("centros_custo", []) if isinstance(x, dict) and x.get("id") is not None],
        "plano": [{"codigo": cod_plano(x["id"]), "codigo_sienge": str(x["id"]), "nome": x.get("name") or "",
                   "tipo": x.get("tpConta"), "redutora": _sn(x.get("flRedutora")),
                   "ativa": _sn(x.get("flAtiva"))}
                  for x in c.get("plano", []) if isinstance(x, dict) and x.get("id") is not None],
        "tipos_negocio": [{"id": int(x["businessTypeId"]), "nome": x.get("description") or ""}
                          for x in c.get("tipos_negocio", []) if isinstance(x, dict) and x.get("businessTypeId") is not None],
    }


def normalizar_obras(regs: list) -> list:
    """Obras do Sienge -> [{'id','nome','nome_comercial','empresa_id','codigo','bruto'}]. Tolerante: aceita nomes de campo em ingles do Sienge
    (name/commercialName/companyId...) e ignora registro sem id. 'bruto' guarda o registro original para conferir o de-para depois."""
    out = []
    for x in regs or []:
        if not isinstance(x, dict):
            continue
        oid = _int(x.get("id") if x.get("id") is not None else x.get("enterpriseId"))
        if oid is None:
            continue
        nome = (x.get("name") or x.get("description") or x.get("enterpriseName") or "").strip()
        comercial = (x.get("commercialName") or x.get("tradeName") or "").strip()
        codigo = x.get("code") if x.get("code") is not None else x.get("enterpriseCode")
        out.append({"id": oid, "nome": nome or None, "nome_comercial": comercial or None,
                    "empresa_id": _int(x.get("companyId") if x.get("companyId") is not None else x.get("idCompany")),
                    "codigo": str(codigo).strip() if codigo not in (None, "") else None, "bruto": x})
    return out


def normalizar_credores(regs: list) -> list:
    """Credores do Sienge -> [{'id','nome','nome_fantasia'}]. Tolerante a nomes de campo (name/tradeName/fantasyName...). So' guarda o necessario: sem CPF/CNPJ.
    Fantasia igual a razao social (ou vazia) vira None."""
    out = []
    for x in regs or []:
        if not isinstance(x, dict):
            continue
        cid = _int(x.get("id") if x.get("id") is not None else x.get("creditorId"))
        nome = (x.get("name") or x.get("creditorName") or x.get("companyName") or "").strip()
        if cid is None or not nome:
            continue
        fant = (x.get("tradeName") or x.get("fantasyName") or x.get("nomeFantasia") or x.get("alias") or "").strip()
        out.append({"id": cid, "nome": nome, "nome_fantasia": None if not fant or fant.upper() == nome.upper() else fant})
    return out
