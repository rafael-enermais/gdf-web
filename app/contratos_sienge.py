# -*- coding: utf-8 -*-
"""GDF - Contratos de SUPRIMENTOS do Sienge (somente leitura): contratos, medicoes e anexos, para a pagina "Obras e contratos" e para a Dexie.

Os dados vem direto da API (v1/supply-contracts/all e v1/supply-contracts/measurements/all, 200 por pagina) e ficam guardados em memoria por 1 hora
(botao "Atualizar do Sienge" na pagina limpa na hora). Nada e' gravado no banco nem no Sienge. Os anexos so' sao LISTADOS (nome e descricao), um contrato por vez.
Contratos de VENDA ainda nao estao liberados para a chave da API (HTTP 403)."""
from __future__ import annotations

import threading
import time

import pandas as pd

import sienge_api as S

TTL = 3600.0                      # segundos que a carga completa fica guardada
_CAB = threading.Lock()
_GUARDA: dict = {}                # {"dados": (momento, dict)} e {("anexos", chave): (momento, lista)}


def _num(v) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


_SITUACAO = {"COMPLETED": "Concluído", "FULLY_MEASURED": "Totalmente medido", "PARTIALLY_MEASURED": "Parcialmente medido", "PENDING": "Pendente", "CANCELED": "Cancelado",
             "CANCELLED": "Cancelado", "APPROVED": "Aprovada", "DISAPPROVED": "Reprovada", "IN_PROGRESS": "Em andamento", "NOT_MEASURED": "Sem medição"}


def _pt(v) -> str:
    """Situacao da API (ex.: 'PARTIALLY_MEASURED') em portugues; o que nao conhecemos fica legivel ('Foo bar'); texto ja normal nao muda."""
    t = _txt(v)
    if t.upper() in _SITUACAO:
        return _SITUACAO[t.upper()]
    return t.replace("_", " ").capitalize() if (t.isupper() or "_" in t) else t


def _data(v) -> str:
    """'2026-03-15T00:00:00...' -> '2026-03-15' (texto ISO; vazio se nao houver)."""
    t = _txt(v)
    return t[:10] if len(t) >= 10 and t[4:5] == "-" else t


def _cliente():
    try:
        import streamlit as st
        sec = st.secrets
        sec.get("SIENGE_USER")                     # forca a leitura (sem arquivo de secrets o Streamlit levanta erro aqui)
    except Exception:                              # noqa: BLE001
        sec = None
    user, pwd, base = S.credenciais(sec)
    return S.Cliente(user, pwd, base, timeout=90, pausa=0.4, esperas_429=(20, 60))


def _paginar(cli, caminho: str, params: dict | None = None, limite: int = 200, maximo: int = 20000) -> list:
    """Todas as paginas de uma lista do Sienge (limit/offset)."""
    out, off = [], 0
    while True:
        resp = cli.get(caminho, {**(params or {}), "limit": limite, "offset": off})
        itens = S.lista(resp)
        out += itens
        meta = resp.get("resultSetMetadata") if isinstance(resp, dict) else None
        total = meta.get("count") if isinstance(meta, dict) else None
        off += limite
        if len(itens) < limite or (isinstance(total, int) and off >= total) or off >= maximo:
            return out


def baixar(cli=None) -> dict:
    """Busca tudo no Sienge e devolve {'contratos': [...], 'medicoes': [...], 'quando': 'AAAA-MM-DD HH:MM'} ja normalizado."""
    cli = cli or _cliente()
    brutos_c = _paginar(cli, "v1/supply-contracts/all")
    brutos_m = _paginar(cli, "v1/supply-contracts/measurements/all")
    return normalizar(brutos_c, brutos_m)


def chave(doc, num) -> str:
    return f"{_txt(doc)}-{_txt(num)}"


def normalizar(brutos_c: list, brutos_m: list) -> dict:
    contratos = []
    for c in brutos_c or []:
        if not isinstance(c, dict):
            continue
        obras = [{"id": _txt(b.get("buildingId")), "nome": _txt(b.get("name")) or _txt(b.get("buildingId"))}
                 for b in (c.get("buildings") or []) if isinstance(b, dict) and b.get("buildingId") is not None]
        mo, ma = _num(c.get("totalLaborValue")), _num(c.get("totalMaterialValue"))
        contratos.append({"chave": chave(c.get("documentId"), c.get("contractNumber")), "doc": _txt(c.get("documentId")), "num": _txt(c.get("contractNumber")),
                          "credor_id": _txt(c.get("supplierId")), "credor": _txt(c.get("supplierName")) or "(sem credor)", "empresa": _txt(c.get("companyName")),
                          "situacao": _pt(c.get("status")) or "(sem situação)", "aprovacao": _pt(c.get("statusApproval")), "autorizado": bool(c.get("isAuthorized")),
                          "data": _data(c.get("contractDate")), "inicio": _data(c.get("startDate")), "fim": _data(c.get("endDate")), "objeto": _txt(c.get("object")),
                          "tipo": _pt(c.get("contractType")), "obras": obras, "mao_obra": mo, "material": ma, "total": round(mo + ma, 2)})
    medicoes = []
    for m in brutos_m or []:
        if not isinstance(m, dict):
            continue
        mo, ma = _num(m.get("totalLaborValue")), _num(m.get("totalMaterialValue"))
        medicoes.append({"chave": chave(m.get("documentId"), m.get("contractNumber")), "obra_id": _txt(m.get("buildingId")), "n": _txt(m.get("measurementNumber")),
                         "data": _data(m.get("measurementDate")), "venc": _data(m.get("dueDate")), "mao_obra": mo, "material": ma, "bruto": round(mo + ma, 2),
                         "liquido": _num(m.get("netValue")), "a_liberar": _num(m.get("valueToRelease")), "autorizada": bool(m.get("authorized")),
                         "finalizada": bool(m.get("finalized")), "liberada": bool(m.get("released")), "situacao": _pt(m.get("statusApproval")), "obs": _txt(m.get("notes"))})
    return {"contratos": contratos, "medicoes": medicoes, "quando": time.strftime("%Y-%m-%d %H:%M")}


def carregar(forcar: bool = False) -> dict:
    """Carga completa, guardada por 1 hora (compartilhada entre quem usa o app). `forcar` busca de novo."""
    with _CAB:
        h = _GUARDA.get("dados")
        if h and not forcar and time.monotonic() - h[0] < TTL:
            return h[1]
    dados = baixar()                                  # fora do cadeado: a busca demora e nao deve travar os outros
    with _CAB:
        _GUARDA["dados"] = (time.monotonic(), dados)
    return dados


def limpar() -> None:
    with _CAB:
        _GUARDA.clear()


def anexos(doc: str, num: str, cli=None) -> list:
    """Anexos de UM contrato (so' a lista: numero, nome e descricao). Guardado 10 min por contrato."""
    k = ("anexos", chave(doc, num))
    with _CAB:
        h = _GUARDA.get(k)
        if h and time.monotonic() - h[0] < 600:
            return h[1]
    cli = cli or _cliente()
    brutos = _paginar(cli, "v1/supply-contracts/attachments/all", {"documentId": doc, "contractNumber": num})
    lista = [{"n": _txt(a.get("contractAttachmentNumber")), "nome": _txt(a.get("name")), "descricao": _txt(a.get("description"))} for a in brutos if isinstance(a, dict)]
    with _CAB:
        _GUARDA[k] = (time.monotonic(), lista)
    return lista


# ------------------------------------------------------------------ tabelas para a tela e para a Dexie
def _tem(contrato: dict, obras: set) -> bool:
    return bool(obras & {o["id"] for o in contrato["obras"]})


def medido_por_contrato(medicoes: list, obras: set | None = None) -> dict:
    """{chave do contrato: {'medido', 'liquido', 'a_liberar', 'n'}}; com `obras` (ids), so' as medicoes dessas obras."""
    out: dict = {}
    for m in medicoes:
        if obras and m["obra_id"] not in obras:
            continue
        r = out.setdefault(m["chave"], {"medido": 0.0, "liquido": 0.0, "a_liberar": 0.0, "n": 0})
        r["medido"] += m["bruto"]
        r["liquido"] += m["liquido"]
        r["a_liberar"] += m["a_liberar"]
        r["n"] += 1
    return out


SIT_FORA = ("Pendente", "Cancelado")        # ainda nao valem como contrato firmado: ficam fora dos totais, a menos que a pessoa peca


def fora_do_calculo(dados: dict) -> dict:
    """Quantos contratos e quanto (R$) ficam de fora quando pendentes/cancelados nao entram, e quantos deles nem tem credor."""
    fora = [c for c in dados["contratos"] if c["situacao"] in SIT_FORA]
    return {"contratos": len(fora), "total": round(sum(c["total"] for c in fora), 2), "sem_credor": sum(1 for c in fora if not c["credor_id"])}


def filtrar(dados: dict, obras=None, credores=None, situacoes=None, busca: str = "", incluir_inativos: bool = True) -> list:
    """Contratos que passam pelos filtros (ids de obra, ids de credor, situacoes, texto livre em credor/objeto/numero/obra).
    Com incluir_inativos=False e nenhuma situacao escolhida, contratos Pendentes e Cancelados ficam de fora (situacao escolhida a dedo sempre vale)."""
    obras, credores, situacoes = set(obras or []), set(credores or []), set(situacoes or [])
    t = _txt(busca).lower()
    out = []
    for c in dados["contratos"]:
        if not situacoes and not incluir_inativos and c["situacao"] in SIT_FORA:
            continue
        if obras and not _tem(c, obras):
            continue
        if credores and c["credor_id"] not in credores:
            continue
        if situacoes and c["situacao"] not in situacoes:
            continue
        if t and t not in " ".join([c["credor"], c["objeto"], c["chave"], c["empresa"]] + [o["nome"] for o in c["obras"]]).lower():
            continue
        out.append(c)
    return out


def df_contratos(contratos: list, medicoes: list, obras=None) -> pd.DataFrame:
    """Uma linha por contrato: dados + medido (nas obras marcadas, se houver) + saldo."""
    med = medido_por_contrato(medicoes, set(obras or []))
    linhas = []
    for c in contratos:
        m = med.get(c["chave"], {})
        medido = round(m.get("medido", 0.0), 2)
        linhas.append({"Contrato": c["chave"], "Credor": c["credor"], "Obras": ", ".join(o["nome"] for o in c["obras"]) or "—", "Situação": c["situacao"],
                       "Início": c["inicio"], "Fim": c["fim"], "Mão de obra": c["mao_obra"], "Material": c["material"], "Total": c["total"], "Medido": medido,
                       "A liberar": round(m.get("a_liberar", 0.0), 2), "Saldo": round(c["total"] - medido, 2) if not obras else float("nan"), "Medições": m.get("n", 0),
                       "_chave": c["chave"], "_doc": c["doc"], "_num": c["num"]})
    return pd.DataFrame(linhas, columns=["Contrato", "Credor", "Obras", "Situação", "Início", "Fim", "Mão de obra", "Material", "Total", "Medido", "A liberar", "Saldo", "Medições",
                                         "_chave", "_doc", "_num"])


def df_obras(dados: dict, credores=None) -> pd.DataFrame:
    """Uma linha por obra. Contratado = soma dos contratos que INCLUEM a obra (contrato de mais de uma obra conta inteiro em cada uma); Medido = medicoes da obra."""
    credores = set(credores or [])
    por: dict = {}
    for c in dados["contratos"]:
        if credores and c["credor_id"] not in credores:
            continue
        for o in c["obras"]:
            r = por.setdefault(o["id"], {"Obra": o["nome"], "_id": o["id"], "chaves": set(), "credores": set(), "Contratado": 0.0, "Medido": 0.0, "A liberar": 0.0, "comp": 0})
            r["chaves"].add(c["chave"])
            r["credores"].add(c["credor_id"])
            r["Contratado"] += c["total"]
            r["comp"] += 1 if len(c["obras"]) > 1 else 0
    chaves_ok = {c["chave"] for c in dados["contratos"] if not credores or c["credor_id"] in credores}
    for m in dados["medicoes"]:
        r = por.get(m["obra_id"])
        if r is not None and m["chave"] in chaves_ok and m["chave"] in r["chaves"]:
            r["Medido"] += m["bruto"]
            r["A liberar"] += m["a_liberar"]
    linhas = [{"Obra": r["Obra"], "Contratos": len(r["chaves"]), "Compartilhados": r["comp"], "Credores": len(r["credores"]), "Contratado": round(r["Contratado"], 2), "Medido": round(r["Medido"], 2),
               "% medido": (r["Medido"] / r["Contratado"]) if r["Contratado"] > 0.005 else None, "A liberar": round(r["A liberar"], 2), "_id": r["_id"]} for r in por.values()]
    df = pd.DataFrame(linhas, columns=["Obra", "Contratos", "Compartilhados", "Credores", "Contratado", "Medido", "% medido", "A liberar", "_id"])
    return df.sort_values("Contratado", ascending=False).reset_index(drop=True)


def df_credores(dados: dict, obras=None) -> pd.DataFrame:
    """Uma linha por credor (so' contratos das obras marcadas, se houver). Medido = medicoes dos contratos (nas obras marcadas, se houver)."""
    obras = set(obras or [])
    cs = [c for c in dados["contratos"] if not obras or _tem(c, obras)]
    med = medido_por_contrato(dados["medicoes"], obras)
    por: dict = {}
    for c in cs:
        r = por.setdefault(c["credor_id"], {"Credor": c["credor"], "_id": c["credor_id"], "n": 0, "obras": set(), "Contratado": 0.0, "Medido": 0.0, "A liberar": 0.0})
        r["n"] += 1
        r["obras"] |= {o["id"] for o in c["obras"]}
        r["Contratado"] += c["total"]
        m = med.get(c["chave"], {})
        r["Medido"] += m.get("medido", 0.0)
        r["A liberar"] += m.get("a_liberar", 0.0)
    linhas = [{"Credor": r["Credor"], "Contratos": r["n"], "Obras": len(r["obras"]), "Contratado": round(r["Contratado"], 2), "Medido": round(r["Medido"], 2),
               "% medido": (r["Medido"] / r["Contratado"]) if r["Contratado"] > 0.005 else None, "A liberar": round(r["A liberar"], 2), "_id": r["_id"]} for r in por.values()]
    df = pd.DataFrame(linhas, columns=["Credor", "Contratos", "Obras", "Contratado", "Medido", "% medido", "A liberar", "_id"])
    return df.sort_values("Contratado", ascending=False).reset_index(drop=True)


def df_medicoes(medicoes: list, chaves, obras=None, nomes: dict | None = None) -> pd.DataFrame:
    """Medicoes dos contratos marcados (ordem: contrato, numero). `nomes` = {id da obra: nome}."""
    chaves, obras, nomes = set(chaves), set(obras or []), nomes or {}
    linhas = [{"Contrato": m["chave"], "Medição": m["n"], "Data": m["data"], "Vencimento": m["venc"], "Mão de obra": m["mao_obra"], "Material": m["material"], "Valor líquido": m["liquido"],
               "A liberar": m["a_liberar"], "Situação": m["situacao"] or ("finalizada" if m["finalizada"] else "—"), "Autorizada": "sim" if m["autorizada"] else "não", "Obra": nomes.get(m["obra_id"], m["obra_id"])}
              for m in medicoes if m["chave"] in chaves and (not obras or m["obra_id"] in obras)]
    return pd.DataFrame(linhas, columns=["Contrato", "Medição", "Data", "Vencimento", "Mão de obra", "Material", "Valor líquido", "A liberar", "Situação", "Autorizada", "Obra"])
