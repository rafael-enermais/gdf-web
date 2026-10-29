# -*- coding: utf-8 -*-
"""GDF V2 - dados do painel "Folha PJ" (Painel da Diretoria, ao lado de Pessoas). So' leitura; o calculo e' feito em funcoes puras (sem banco, sem streamlit).

Como funciona, em linguagem simples:
- A fonte e' o Sienge que ja' esta no banco: baixas (pago no mes) e titulos em aberto (a pagar, vencimento ate o fim do mes) das contas PJ
  (Salarios PJ, Premiacoes e Multas Contratuais, de obra e ADM). Nao precisa subir CSV.
- Titulos substitutos nao contam: a "Substituicao" some; o "Abatimento de adiantamento" some, salvo se houver adiantamento/proforma do mesmo credor e do mesmo valor
  no mes (ai o adiantamento some e a nota fica, com a data de pagamento do adiantamento).
- Um colaborador PJ = um credor do Sienge pago por uma empresa (credor + empresa pagadora). O centro de custo vem da apropriacao do Sienge: se o credor tem
  mais de um centro no mes vai para "EMPRESA - OBRAS" da empresa que pagou (excecao: se todos os centros sao sede/administracao, fica o de maior valor).
- A diretoria (credores cadastrados por codigo) aparece em UMA linha e o valor dela soma na empresa que pagou.
- O Flash (premiacao no cartao = ajuda de custo; refeicao/alimentacao = vale alimentacao) entra por upload de planilha e e' cruzado por CPF (so' o hash fica no banco) ou nome.
- Custo total = honorarios + premiacoes + multa + ajuda de custo + vale alimentacao - descontos. Pago e a pagar sao liquidos de desconto.
Nada daqui vai para o repositorio: nomes, CPF e valores ficam so' no banco; os testes usam dados ficticios."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import unicodedata
from collections import defaultdict

CONTAS = {"2.01.02.01": "honorarios", "2.02.01.01": "honorarios",          # Salarios PJ (obra / ADM)
          "2.01.02.11": "premiacao", "2.02.01.06": "premiacao",            # Premiacoes PJ (obra / ADM)
          "2.02.01.19": "multa"}                                           # Multas Contratuais PJ (ADM)
ROT_CATEGORIA = {"honorarios": "Honorários", "premiacao": "Premiações", "multa": "Multa contratual"}
TIPOS_BAIXA = (1, 8, 10)                                                   # 1 Pagamento, 8 Abatimento de adiantamento, 10 Adiantamento (5 Substituicao e 3 Cancelamento nao contam)
TOL = 0.005
SEDE, VARIOS, DIRETORIA = "SEDE / ADM CENTRAL", "OBRAS COM VÁRIOS CENTROS DE CUSTO", "DIRETORIA"
ROT_DIRETORIA = "Demais credores - diretoria"
EMPRESAS = {1: "ENERMAIS ENERGIA LTDA", 2: "SMG SOLUÇÕES LTDA", 3: "ENERMAIS ENGENHARIA LTDA", 4: "ENERMAIS RENOVAVEIS LTDA", 5: "ENERMAIS CONSTRUTORA LTDA", 6: "ENERMAIS SOLUCOES LTDA"}
SITUACOES = ("Pago", "Parcial", "A pagar", "Só Flash")
_PREPOSICOES = {"de", "da", "do", "das", "dos", "e", "di", "du"}


# ------------------------------------------------------------------ texto
def sem_acento(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def chave_nome(s) -> str:
    """Nome em minusculas, sem acento, sem pontuacao e com espacos simples (cruzamento com o Flash quando falta CPF)."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", sem_acento(s)).split())


def nome_exibicao(s) -> str:
    """'LUCAS MACHADO XAVIER' -> 'Lucas Machado Xavier' (so' a 1a letra de cada palavra maiuscula; de/da/do/dos/das/e em minuscula). Tira o numero de CNPJ que o Sienge poe antes do nome."""
    t = re.sub(r"^[\d\.\-/\s]+", "", str(s or "")).strip()
    palavras = t.lower().split()
    return " ".join(p if (i and p in _PREPOSICOES) else p[:1].upper() + p[1:] for i, p in enumerate(palavras))


def nome_empresa_curto(emp: str) -> str:
    """'ENERMAIS ENERGIA LTDA' -> 'ENERMAIS ENERGIA' (rotulo do centro 'ENERMAIS ENERGIA - OBRAS')."""
    return re.sub(r"\s+", " ", re.sub(r"\bLTDA\.?\b", "", str(emp or ""), flags=re.I)).strip()


def hash_cpf(cpf, segredo: str) -> str | None:
    """HMAC-SHA256 do CPF (so' digitos). O CPF nunca e' gravado. Sem 11 digitos -> None."""
    d = re.sub(r"\D", "", str(cpf or ""))
    if len(d) != 11 or not segredo:
        return None
    return hmac.new(str(segredo).encode(), d.encode(), hashlib.sha256).hexdigest()


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(x: float) -> float:
    return round(x + 0.0, 2)


def _mes_fim(mes: str) -> dt.date:
    a, m = int(mes[:4]), int(mes[5:7])
    return (dt.date(a + (m == 12), m % 12 + 1, 1)) - dt.timedelta(days=1)


# ------------------------------------------------------------------ banco (so' leitura)
_COLS_LINHA = ("bill", "inst", "seq", "tipo", "data", "bruto", "desc", "emp_id", "emp", "cred_id", "cred_nome", "doc_id", "num_doc", "venc",
               "plano", "plano_nome", "centro_id", "centro_nome", "pct")

_SQL_PAGAS = """SELECT b.bill_id, b.installment_id, b.seq, b.tipo_oper_id, b.data_pagamento, COALESCE(b.bruto,0), COALESCE(b.desconto,0),
                       t.empresa_id, t.empresa_nome, t.contraparte_id, t.contraparte_nome, t.doc_id, t.numero_doc, t.data_vencimento,
                       r.plano_cod, r.plano_nome, r.centro_custo_id, r.centro_custo_nome, r.percentual
                FROM pnl_v_baixa b
                JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
                JOIN pnl_v_rateio r ON r.lado=b.lado AND r.bill_id=b.bill_id AND r.installment_id=b.installment_id
                WHERE b.lado='P' AND b.data_pagamento >= %s::date AND b.data_pagamento < (%s::date + interval '1 month')
                  AND b.tipo_oper_id = ANY(%s) AND r.plano_cod = ANY(%s)
                ORDER BY b.bill_id, b.installment_id, b.seq, r.linha"""

_SQL_ABERTAS = """SELECT t.bill_id, t.installment_id, 0, 0, t.data_vencimento, COALESCE(t.valor_original,0) - COALESCE(bx.pago,0), {desc},
                         t.empresa_id, t.empresa_nome, t.contraparte_id, t.contraparte_nome, t.doc_id, t.numero_doc, t.data_vencimento,
                         r.plano_cod, r.plano_nome, r.centro_custo_id, r.centro_custo_nome, r.percentual
                  FROM pnl_titulo t
                  LEFT JOIN (SELECT bill_id, installment_id, sum(COALESCE(bruto,0)) pago FROM pnl_v_baixa
                             WHERE lado='P' AND data_pagamento < (%s::date + interval '1 month') GROUP BY 1, 2) bx
                         ON bx.bill_id=t.bill_id AND bx.installment_id=t.installment_id
                  JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
                  WHERE t.lado='P' AND t.data_vencimento >= %s::date AND t.data_vencimento < (%s::date + interval '1 month')
                    AND COALESCE(upper(t.previsao),'') <> 'S'
                    AND COALESCE(t.valor_original,0) - COALESCE(bx.pago,0) > 0.005 AND r.plano_cod = ANY(%s)
                  ORDER BY t.bill_id, t.installment_id, r.linha"""


# Base REFERENCIA (competencia): o titulo conta no mes da EMISSAO, pelo valor do documento. A parte ja' paga (baixas de dinheiro real) vira linha "Pago"
# e o resto "A pagar" (mesma tabela e mesmos cards da base Caixa; so' muda quando o titulo entra).
_SQL_EMITIDOS = """SELECT t.bill_id, t.installment_id, 0, 1, t.data_emissao, {bruto}, {desc},
                          t.empresa_id, t.empresa_nome, t.contraparte_id, t.contraparte_nome, t.doc_id, t.numero_doc, t.data_vencimento,
                          r.plano_cod, r.plano_nome, r.centro_custo_id, r.centro_custo_nome, r.percentual
                   FROM pnl_titulo t
                   {join} (SELECT bill_id, installment_id, sum(COALESCE(bruto,0)) pago, sum(COALESCE(desconto,0)) dsc FROM pnl_v_baixa
                           WHERE lado='P' AND tipo_oper_id = ANY(%s) GROUP BY 1, 2) bx
                          ON bx.bill_id=t.bill_id AND bx.installment_id=t.installment_id
                   JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
                   WHERE t.lado='P' AND t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month')
                     AND COALESCE(upper(t.previsao),'') <> 'S' AND r.plano_cod = ANY(%s) {filtro}
                   ORDER BY t.bill_id, t.installment_id, r.linha"""


def _para_dict(rows) -> list:
    out = []
    for r in rows:
        d = dict(zip(_COLS_LINHA, r))
        for k in ("bruto", "desc", "pct"):
            d[k] = _f(d[k])
        d["emp_id"] = int(d["emp_id"]) if d["emp_id"] is not None else None
        out.append(d)
    return out


def _consulta(conn, sql, par) -> list:
    with conn.cursor() as cur:
        cur.execute(sql, par)
        return _para_dict(cur.fetchall())


def _buscar_linhas_ref(conn, mes: str) -> dict:
    """Base REFERENCIA: titulos EMITIDOS no mes (sem previsao e sem titulo desfeito). Pago = baixas de dinheiro real ate' hoje; a pagar = o que falta do valor do documento."""
    import painel_db as _P                                                       # noqa: PLC0415  (so' para o filtro de titulos desfeitos; evita importar o painel na carga)
    import base_data as _BD                                                      # noqa: PLC0415
    ini, planos, tipos = f"{mes}-01", list(CONTAS), list(_BD.TIPOS_CAIXA["P"])
    filtro = _P._filtro_desfeitos(True)
    pagas = _consulta(conn, _SQL_EMITIDOS.format(bruto="LEAST(COALESCE(t.valor_original,0), bx.pago)", desc="bx.dsc", join="JOIN", filtro=filtro + " AND bx.pago > 0.005"),
                      (tipos, ini, ini, planos))
    def _abertas(desc):
        return _consulta(conn, _SQL_EMITIDOS.format(bruto="COALESCE(t.valor_original,0) - LEAST(COALESCE(t.valor_original,0), COALESCE(bx.pago,0))", desc=desc, join="LEFT JOIN",
                                                    filtro=filtro + " AND COALESCE(t.valor_original,0) - COALESCE(bx.pago,0) > 0.005"), (tipos, ini, ini, planos))
    try:
        abertas = _abertas("COALESCE(t.desconto_titulo,0)")
    except Exception:                                                        # noqa: BLE001  (SQL-40 ainda nao rodou)
        try:
            conn.rollback()
        except Exception:                                                    # noqa: BLE001
            pass
        abertas = _abertas("0")
    return {"baixas": pagas, "abertas": abertas}


def buscar_linhas(conn, mes: str, base: str = "CAIXA") -> dict:
    """Linhas (uma por baixa/titulo x linha de apropriacao) das contas PJ no mes 'AAAA-MM': {'baixas': [...], 'abertas': [...]}.
    Abertas = titulos com vencimento no mes, sem previsao, ainda nao pagos no fim do mes (saldo = valor - baixas ate o fim do mes).
    Base 'REF': titulos emitidos no mes (ver `_buscar_linhas_ref`)."""
    if base == "REF":
        return _buscar_linhas_ref(conn, mes)
    ini = f"{mes}-01"
    planos = list(CONTAS)
    baixas = _consulta(conn, _SQL_PAGAS, (ini, ini, list(TIPOS_BAIXA), planos))
    try:
        abertas = _consulta(conn, _SQL_ABERTAS.format(desc="COALESCE(t.desconto_titulo,0)"), (ini, ini, ini, planos))
    except Exception:                                                        # noqa: BLE001  (SQL-40 ainda nao rodou: sem desconto do titulo)
        try:
            conn.rollback()
        except Exception:                                                    # noqa: BLE001
            pass
        abertas = _consulta(conn, _SQL_ABERTAS.format(desc="0"), (ini, ini, ini, planos))
    return {"baixas": baixas, "abertas": abertas}


def instalado(conn) -> bool:
    """True se o SQL-40 (sql/v2_folha_pj.sql) ja' foi executado."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_name IN ('pj_colaborador','pj_flash','pj_diretoria_credor')")
            return int(cur.fetchone()[0]) == 3
    except Exception:                                                        # noqa: BLE001
        try:
            conn.rollback()
        except Exception:                                                    # noqa: BLE001
            pass
        return False


def carregar_apoio(conn, mes: str, credores: set) -> dict:
    """Cadastros que o painel cruza com o Sienge: nome fantasia dos credores, mapa de colaboradores, diretoria, Flash do mes e centros de custo. Tudo opcional (vazio se faltar)."""
    apoio = {"fantasia": {}, "colab": {}, "diretoria": set(), "flash": [], "centros": {}}
    def _tenta(sql, par=None):
        try:
            with conn.cursor() as cur:
                cur.execute(sql, par)
                return cur.fetchall()
        except Exception:                                                    # noqa: BLE001
            try:
                conn.rollback()
            except Exception:                                                # noqa: BLE001
                pass
            return []
    ids = sorted(credores)
    if ids:
        apoio["fantasia"] = {int(i): (fa or "").strip() for i, fa in _tenta("SELECT id, nome_fantasia FROM pnl_credor_sienge WHERE id = ANY(%s)", (ids,))}
    apoio["colab"] = {int(i): {"nome": n, "funcao": fu, "centro": ce, "empresa": em, "cpf_hash": ch, "novo_desde": nd, "chave": nc}
                      for i, n, fu, ce, em, ch, nd, nc in _tenta("SELECT credor_id, nome_exibicao, funcao, centro_origem, empresa_origem, cpf_hash, novo_desde, nome_chave FROM pj_colaborador WHERE ativo")}
    apoio["diretoria"] = {int(r[0]) for r in _tenta("SELECT credor_id FROM pj_diretoria_credor WHERE ativo")}
    apoio["flash"] = [{"credor_id": int(c), "empresa": e, "premiacao": _f(p), "alimentacao": _f(a)}
                      for c, e, p, a in _tenta("SELECT credor_id, empresa, premiacao, alimentacao FROM pj_flash WHERE ativo AND mes = %s::date", (f"{mes}-01",))]
    apoio["centros"] = {int(i): {"nome": n, "grupo": g, "obra": ob, "cod_obra": co}
                        for i, n, g, ob, co in _tenta("SELECT centro_custo_id, centro_nome, grupo, obra_nome, codigo_obra FROM pnl_centro_grupo")}
    return apoio


# ------------------------------------------------------------------ regras
def agrupar_baixas(linhas: list) -> list:
    """Linhas (baixa x apropriacao) -> uma baixa por (lancamento, parcela, seq) com suas apropriacoes."""
    por = {}
    for l in linhas:
        k = (l["bill"], l["inst"], l["seq"])
        b = por.get(k)
        if b is None:
            b = {k2: l[k2] for k2 in ("bill", "inst", "seq", "tipo", "data", "bruto", "desc", "emp_id", "emp", "cred_id", "cred_nome", "doc_id", "num_doc", "venc")}
            b["linhas"] = []
            por[k] = b
        b["linhas"].append({k2: l[k2] for k2 in ("plano", "plano_nome", "centro_id", "centro_nome", "pct")})
    return list(por.values())


def aplicar_substituicoes(baixas: list) -> tuple:
    """Tira os titulos substitutos. Devolve (validas, fora) onde fora = [{'baixa':..., 'motivo':...}].
    - tipo 8 (abatimento de adiantamento) e tipo 1 (nota) com um adiantamento/proforma (tipo 10) do mesmo credor e do mesmo valor no mes: o adiantamento sai e a nota
      fica com a data de pagamento do adiantamento; abatimento sem adiantamento do mesmo valor no mes sai (o adiantamento foi pago em outro mes)."""
    validas, fora = [], []
    por_cred = defaultdict(list)
    for b in baixas:
        por_cred[b["cred_id"]].append(b)
    for _, lst in por_cred.items():
        adiant = sorted((b for b in lst if b["tipo"] == 10), key=lambda x: (x["data"] or dt.date.min, x["bill"]))
        usados = set()
        notas = sorted((b for b in lst if b["tipo"] in (1, 8)), key=lambda x: (x["tipo"] != 8, x["data"] or dt.date.min, x["bill"]))
        for n in notas:
            par = next((a for a in adiant if id(a) not in usados and abs(a["bruto"] - n["bruto"]) <= TOL), None)
            if par is not None:
                usados.add(id(par))
                validas.append({**n, "data": par["data"], "data_original": n["data"], "substitui": f"{par['doc_id']} {par['num_doc']}".strip()})
                fora.append({"baixa": par, "motivo": "adiantamento/proforma substituído por nota do mesmo valor"})
            elif n["tipo"] == 8:
                fora.append({"baixa": n, "motivo": "abatimento de adiantamento (sem adiantamento do mesmo valor no mês)"})
            else:
                validas.append(n)
        for a in adiant:
            if id(a) not in usados:
                validas.append(a)
    return validas, fora


def agrupar_abertas(linhas: list) -> list:
    por = {}
    for l in linhas:
        k = (l["bill"], l["inst"])
        b = por.get(k)
        if b is None:
            b = {k2: l[k2] for k2 in ("bill", "inst", "seq", "tipo", "data", "bruto", "desc", "emp_id", "emp", "cred_id", "cred_nome", "doc_id", "num_doc", "venc")}
            b["linhas"] = []
            por[k] = b
        b["linhas"].append({k2: l[k2] for k2 in ("plano", "plano_nome", "centro_id", "centro_nome", "pct")})
    return list(por.values())


def _rotulo_centro(cid, nome) -> str:
    return f"{cid} - {nome}" if cid is not None else str(nome or "(sem centro de custo)")


def eh_adm(cid, centros: dict) -> bool:
    """Centro de sede/administracao: grupo ADM do de-para ou codigo 999xx (despesas e investimentos)."""
    return cid is not None and ((centros.get(int(cid), {}).get("grupo") == "ADM") or int(cid) >= 99000)


def decidir_centro(pesos: dict, emp: str, centros: dict, nomes: dict) -> str:
    """Centro de custo do colaborador (credor + empresa) no mes. pesos = {centro_id: valor}; nomes = {centro_id: rotulo}."""
    ids = [c for c, v in pesos.items() if abs(v) > TOL] or list(pesos)
    if not ids:
        return "(sem centro de custo)"
    if len(ids) == 1:
        return nomes[ids[0]]
    if all(eh_adm(c, centros) for c in ids):
        return nomes[max(ids, key=lambda c: pesos[c])]
    return f"{nome_empresa_curto(emp)} - OBRAS"


def obra_do_centro(rotulo: str, centros: dict) -> str:
    """Nivel 1 (obra) do centro de custo ja decidido: DIRETORIA, SEDE / ADM CENTRAL, OBRAS COM VARIOS CENTROS DE CUSTO ou o nome da obra do de-para."""
    r = str(rotulo or "")
    if r == DIRETORIA:
        return DIRETORIA
    if r.upper().endswith(" - OBRAS"):
        return VARIOS
    m = re.match(r"^(\d+)\s*-\s*", r)
    cid = int(m.group(1)) if m else None
    if cid is not None:
        if eh_adm(cid, centros):
            return SEDE
        info = centros.get(cid)
        if info and info.get("obra"):
            return info["obra"]
    if "SEDE / ADM" in r.upper():
        return SEDE
    return re.sub(r"^\d+\s*-\s*", "", r) or "(sem obra)"


def _situacao(pago: float, a_pagar: float, flash: float) -> str:
    if pago > TOL and a_pagar > TOL:
        return "Parcial"
    if pago > TOL:
        return "Pago"
    if a_pagar > TOL:
        return "A pagar"
    return "Só Flash" if flash > TOL else "Pago"


def _linhas_documento(b: dict, pago: bool) -> list:
    """Uma linha de documento por (baixa/titulo, conta): valor bruto da conta = bruto x soma dos % das apropriacoes daquela conta; desconto proporcional."""
    por_conta = defaultdict(list)
    for l in b["linhas"]:
        por_conta[l["plano"]].append(l)
    out = []
    for plano, ls in por_conta.items():
        p = sum(x["pct"] for x in ls) / 100.0
        out.append({"situacao": "Pago" if pago else "A pagar", "lancamento": f"{b['bill']}/{b['inst']}", "documento": f"{b['doc_id'] or ''} {b['num_doc'] or ''}".strip(),
                    "data": b["data"], "emp_id": b["emp_id"], "empresa": EMPRESAS.get(b["emp_id"], b["emp"]), "cred_id": b["cred_id"], "cred_nome": b["cred_nome"],
                    "plano": plano, "plano_nome": ls[0]["plano_nome"], "categoria": CONTAS[plano], "bruto": _r2(b["bruto"] * p), "desconto": _r2(b["desc"] * p),
                    "substitui": b.get("substitui"),
                    "apropriacao": [{"centro": _rotulo_centro(x["centro_id"], x["centro_nome"]), "centro_id": x["centro_id"], "pct": round(x["pct"], 2)} for x in ls]})
    return out


def consolidar(linhas: dict, apoio: dict, mes: str) -> dict:
    """Junta tudo: documentos, colaboradores (credor + empresa), resumo por obra/centro, cards por empresa e conferencias.
    linhas = buscar_linhas(); apoio = carregar_apoio(). Funcao pura."""
    centros = apoio.get("centros") or {}
    fantasia, colab, diretoria = apoio.get("fantasia") or {}, apoio.get("colab") or {}, set(apoio.get("diretoria") or ())
    baixas = agrupar_baixas(linhas.get("baixas") or [])
    validas, fora = aplicar_substituicoes(baixas)
    abertas = agrupar_abertas(linhas.get("abertas") or [])
    docs = []
    for b in validas:
        docs += _linhas_documento(b, True)
    for b in abertas:
        docs += _linhas_documento(b, False)
    nomes_centro = {}
    for b in validas + abertas:
        for l in b["linhas"]:
            if l["centro_id"] is not None:
                nomes_centro[int(l["centro_id"])] = _rotulo_centro(l["centro_id"], l["centro_nome"])
    # ---- colaboradores: credor + empresa que pagou
    grupos = {}
    pesos = defaultdict(lambda: defaultdict(float))
    for d in docs:
        k = (d["cred_id"], d["emp_id"])
        g = grupos.setdefault(k, {"cred_id": d["cred_id"], "emp_id": d["emp_id"], "empresa": d["empresa"], "cred_nome": d["cred_nome"], "honorarios": 0.0, "premiacao": 0.0, "multa": 0.0,
                                  "desconto": 0.0, "pago": 0.0, "a_pagar": 0.0, "n_docs": 0, "ajuda_custo": 0.0, "alimentacao": 0.0})
        g[d["categoria"]] += d["bruto"]
        g["desconto"] -= d["desconto"]
        g["pago" if d["situacao"] == "Pago" else "a_pagar"] += d["bruto"] - d["desconto"]
        g["n_docs"] += 1
        for a in d["apropriacao"]:
            if a["centro_id"] is not None:
                pesos[k][int(a["centro_id"])] += d["bruto"] * a["pct"] / 100.0
    for k, g in grupos.items():
        g["centro"] = DIRETORIA if g["cred_id"] in diretoria else decidir_centro(pesos[k], g["empresa"], centros, nomes_centro)
    # ---- Flash: casa por (credor, empresa); sem linha de nota naquela empresa vira "So' Flash"
    por_emp_nome = {sem_acento(v): k for k, v in EMPRESAS.items()}
    for f in apoio.get("flash") or []:
        emp_id = por_emp_nome.get(sem_acento(f["empresa"]))
        k = (f["credor_id"], emp_id)
        g = grupos.get(k)
        if g is None:
            info = colab.get(f["credor_id"], {})
            g = grupos[k] = {"cred_id": f["credor_id"], "emp_id": emp_id, "empresa": EMPRESAS.get(emp_id, f["empresa"]), "cred_nome": info.get("nome") or "", "honorarios": 0.0, "premiacao": 0.0,
                             "multa": 0.0, "desconto": 0.0, "pago": 0.0, "a_pagar": 0.0, "n_docs": 0, "ajuda_custo": 0.0, "alimentacao": 0.0,
                             "centro": DIRETORIA if f["credor_id"] in diretoria else (info.get("centro") or "(sem centro de custo)")}
        g["ajuda_custo"] += f["premiacao"]
        g["alimentacao"] += f["alimentacao"]
    mes_ini = dt.date.fromisoformat(f"{mes}-01")
    pessoas = []
    for g in grupos.values():
        info = colab.get(g["cred_id"], {})
        fa = fantasia.get(g["cred_id"]) or info.get("nome") or g["cred_nome"]
        flash = g["ajuda_custo"] + g["alimentacao"]
        g["nome"] = nome_exibicao(fa) or f"Credor {g['cred_id']}"
        g["funcao"] = info.get("funcao") or ""
        g["novo"] = bool(info.get("novo_desde") and info["novo_desde"] == mes_ini)
        g["diretoria"] = g["cred_id"] in diretoria
        g["obra"] = obra_do_centro(g["centro"], centros)
        g["custo_total"] = _r2(g["honorarios"] + g["premiacao"] + g["multa"] + flash + g["desconto"])
        g["situacao"] = _situacao(g["pago"], g["a_pagar"], flash)
        for c in ("honorarios", "premiacao", "multa", "desconto", "pago", "a_pagar", "ajuda_custo", "alimentacao"):
            g[c] = _r2(g[c])
        pessoas.append(g)
    pessoas.sort(key=lambda p: (p["diretoria"], sem_acento(p["nome"]), p["empresa"] or ""))
    # ---- documentos (diretoria mantem o nome do credor; o painel agrupa na tela)
    por_chave = {(g["cred_id"], g["emp_id"]): g for g in pessoas}
    for d in docs:
        g = por_chave[(d["cred_id"], d["emp_id"])]
        d["nome"], d["diretoria"] = g["nome"], g["diretoria"]
        d["valor_liquido"] = _r2(d["bruto"] - d["desconto"])
    docs.sort(key=lambda d: (d["situacao"] != "Pago", d["data"] or dt.date.max, d["lancamento"], d["plano"]))
    return {"mes": mes, "pessoas": pessoas, "documentos": docs, "fora": [{"lancamento": f"{x['baixa']['bill']}/{x['baixa']['inst']}", "documento": f"{x['baixa']['doc_id'] or ''} {x['baixa']['num_doc'] or ''}".strip(),
                                                                       "tipo": x["baixa"]["tipo"], "valor": _r2(x["baixa"]["bruto"]), "motivo": x["motivo"]} for x in fora],
            "totais": somar(pessoas), "cards": cards_empresas(pessoas), "obras": resumo_obras(pessoas), "top_obras": top_obras(pessoas)}


# ------------------------------------------------------------------ resumos (funcoes puras sobre a lista de colaboradores)
_CAMPOS = ("honorarios", "premiacao", "multa", "ajuda_custo", "alimentacao", "desconto", "custo_total", "pago", "a_pagar")


def somar(pessoas: list) -> dict:
    t = {c: _r2(sum(p[c] for p in pessoas)) for c in _CAMPOS}
    t["n"] = len(pessoas)
    t["n_docs"] = sum(p["n_docs"] for p in pessoas)
    t["flash"] = _r2(t["ajuda_custo"] + t["alimentacao"])
    return t


def cards_empresas(pessoas: list) -> list:
    """Um card por empresa (quem pagou); o valor da diretoria soma na empresa e aparece em destaque (diretoria = linha 'dir')."""
    por = {}
    for p in pessoas:
        e = por.setdefault(p["emp_id"], {"emp_id": p["emp_id"], "empresa": p["empresa"], "pessoas": [], "dir": []})
        e["dir" if p["diretoria"] else "pessoas"].append(p)
    out = []
    for e in por.values():
        tot = somar(e["pessoas"] + e["dir"])
        d = somar(e["dir"])
        out.append({"emp_id": e["emp_id"], "empresa": e["empresa"], "n": len(e["pessoas"]), "total": tot, "diretoria": d, "sem_diretoria": somar(e["pessoas"])})
    out.sort(key=lambda x: -x["total"]["custo_total"])
    return out


def resumo_obras(pessoas: list) -> list:
    """Resumo em 2 niveis: obra (nivel 1) -> centro de custo (nivel 2). Ordem: obras por custo; 'SEDE / ADM CENTRAL', 'OBRAS COM VARIOS...' e DIRETORIA por ultimo."""
    niv1 = {}
    for p in pessoas:
        o = niv1.setdefault(p["obra"], {"obra": p["obra"], "centros": {}})
        o["centros"].setdefault(p["centro"], []).append(p)
    fim = {SEDE: 1, VARIOS: 2, DIRETORIA: 3}
    out = []
    for o in niv1.values():
        todos = [x for lst in o["centros"].values() for x in lst]
        filhos = [{"centro": c, "n": len(l), **{k: v for k, v in somar(l).items() if k != "n"}} for c, l in o["centros"].items()]
        filhos.sort(key=lambda x: -x["custo_total"])
        out.append({"obra": o["obra"], "n": len(todos), **{k: v for k, v in somar(todos).items() if k != "n"}, "centros": filhos})
    out.sort(key=lambda x: (fim.get(x["obra"], 0), -x["custo_total"]))
    return out


def top_obras(pessoas: list, n: int = 3) -> list:
    """As n obras (nivel 1) com maior custo PJ, sem a diretoria e sem os grupos que nao sao obra (sede/adm e 'varios centros')."""
    sem_dir = [p for p in pessoas if not p["diretoria"] and p["obra"] not in (SEDE, VARIOS, DIRETORIA)]
    return [o for o in resumo_obras(sem_dir)][:n]


def agrupar_diretoria(pessoas: list) -> list:
    """Lista de colaboradores com a diretoria numa linha so' ('Demais credores - diretoria'), sempre a ultima."""
    comuns = [p for p in pessoas if not p["diretoria"]]
    dire = [p for p in pessoas if p["diretoria"]]
    if not dire:
        return comuns
    t = somar(dire)
    linha = {**{c: t[c] for c in _CAMPOS}, "nome": ROT_DIRETORIA, "empresa": "", "emp_id": None, "centro": DIRETORIA, "obra": DIRETORIA, "funcao": "Diretoria", "novo": False, "diretoria": True,
             "n_docs": t["n_docs"], "situacao": _situacao(t["pago"], t["a_pagar"], t["flash"]), "cred_id": None, "agrupado": len(dire)}
    return comuns + [linha]


def filtrar(pessoas: list, obras=None, centros=None, empresas=None, situacoes=None, busca: str = "") -> list:
    """Filtros em cascata do painel: obra (nivel 1), centro (nivel 2), empresa, situacao e busca por nome/funcao."""
    obras, centros, empresas, situacoes, t = set(obras or ()), set(centros or ()), set(empresas or ()), set(situacoes or ()), sem_acento(busca)
    out = []
    for p in pessoas:
        if obras and p["obra"] not in obras:
            continue
        if centros and p["centro"] not in centros:
            continue
        if empresas and p["empresa"] not in empresas:
            continue
        if situacoes and p["situacao"] not in situacoes:
            continue
        if t and t not in sem_acento(p["nome"]) and t not in sem_acento(p.get("funcao")):
            continue
        out.append(p)
    return out


def filtrar_documentos(docs: list, pessoas_sel: list | None = None, situacoes=None, busca: str = "") -> list:
    """Documentos dos colaboradores marcados (credor + empresa); diretoria marcada em linha unica traz os documentos de todos os credores da diretoria."""
    chaves = set()
    dir_todos = False
    for p in pessoas_sel or ():
        if p.get("agrupado"):
            dir_todos = True
        else:
            chaves.add((p["cred_id"], p["emp_id"]))
    sit, t = set(situacoes or ()), sem_acento(busca)
    out = []
    for d in docs:
        if pessoas_sel and not ((d["cred_id"], d["emp_id"]) in chaves or (dir_todos and d["diretoria"])):
            continue
        if sit and d["situacao"] not in sit:
            continue
        if t and t not in sem_acento(d["nome"]) and t not in sem_acento(d["documento"]):
            continue
        out.append(d)
    return out


def dados_do_mes(conn, mes: str, base: str = "CAIXA") -> dict:
    """Ponto de entrada da tela: le o banco e consolida o mes. base 'CAIXA' (padrao da aba: pago no mes + a pagar com vencimento no mes) ou 'REF' (emitidos no mes)."""
    linhas = buscar_linhas(conn, mes, base)
    creds = {l["cred_id"] for lst in linhas.values() for l in lst if l["cred_id"] is not None}
    apoio = carregar_apoio(conn, mes, creds)
    r = consolidar(linhas, apoio, mes)
    r["instalado"] = instalado(conn)
    r["sem_flash"] = not apoio["flash"]
    r["sem_diretoria"] = not apoio["diretoria"]
    r["sem_mapa"] = not apoio["colab"]
    r["base"] = base
    return r
