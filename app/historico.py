# -*- coding: utf-8 -*-
"""GDF V2 - Historico do ano vindo do painel da contabilidade (HTML ou JSON): le o arquivo, confere as contas e guarda no banco (pnl_historico_painel, SQL-21).
Serve para o que ainda nao existe no Sienge/app (jan a ago): acumulado do ano, desvio mensal realizado x previsto, recomposicao out-dez, horas extras mes a mes
e custos com pessoas. Fica so' no banco; o repositorio publico nunca recebe esses numeros. Nomes de pessoas e credores do arquivo sao descartados na leitura."""
from __future__ import annotations

import hashlib
import json

import db

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
# so' o que o app usa (sem pdet/admdet/hcob, que trazem nomes de colaboradores e credores)
CHAVES_USADAS = ("res", "dev", "recomp", "adm_m", "he", "hc", "pess", "obras")


class ErroHistorico(Exception):
    pass


def _extrair_d_do_html(txt: str) -> dict:
    """Acha `const D={...}` no HTML do painel e le o objeto (JSON) casando as chaves, respeitando textos entre aspas."""
    i = txt.find("const D=")
    if i < 0:
        i = txt.find("const D =")
    if i < 0:
        raise ErroHistorico("Não encontrei os dados do painel (const D) neste HTML. Envie o HTML do painel da contabilidade ou o JSON do histórico.")
    i = txt.index("{", i)
    depth, instr, esc = 0, None, False
    for j in range(i, len(txt)):
        ch = txt[j]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == instr:
                instr = None
        elif ch in "\"'":
            instr = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(txt[i:j + 1])
                except ValueError as exc:
                    raise ErroHistorico(f"Os dados do painel não estão em formato legível ({exc}).")
    raise ErroHistorico("Os dados do painel estão incompletos neste HTML.")


def ler_historico(conteudo: bytes, nome: str = "") -> dict:
    """-> {'dados': {...so as chaves usadas...}, 'meses': [...], 'avisos': [...], 'sha256': ...}. Levanta ErroHistorico se o arquivo nao e' o painel."""
    try:
        txt = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ErroHistorico("Não consegui ler o arquivo como texto (UTF-8).")
    if txt.lstrip().startswith("{"):
        try:
            obj = json.loads(txt)
        except ValueError as exc:
            raise ErroHistorico(f"JSON inválido: {exc}")
        d = obj.get("D", obj) if isinstance(obj, dict) else None
    else:
        d = _extrair_d_do_html(txt)
    if not isinstance(d, dict):
        raise ErroHistorico("O arquivo não tem os dados do painel (res, dev, recomp...).")
    faltam = [k for k in ("res", "dev", "recomp", "he") if k not in d]
    if faltam:
        raise ErroHistorico("Faltam partes do painel no arquivo: " + ", ".join(faltam) + ".")
    avisos = []
    res = d["res"]
    try:
        for rot, blk in (("mês", res["set"]), ("acumulado", res["acc"])):
            rec = blk["rec"][1] if isinstance(blk["rec"], list) else blk["rec"]
            cus = blk["cus"][1] if isinstance(blk["cus"], list) else blk["cus"]
            bdi = blk["bdi"][1] if isinstance(blk["bdi"], list) else blk["bdi"]
            adm = blk["adm"][1] if isinstance(blk["adm"], list) else blk["adm"]
            rs = blk["res"][1] if isinstance(blk["res"], list) else blk["res"]
            if abs((rec - cus) - bdi) > 1.0:
                avisos.append(f"{rot}: receita − custo não fecha com o BDI (diferença de R$ {abs((rec - cus) - bdi):,.2f}).")
            if abs((bdi - adm) - rs) > 1.0:
                avisos.append(f"{rot}: BDI − administração não fecha com o resultado (diferença de R$ {abs((bdi - adm) - rs):,.2f}).")
    except (KeyError, IndexError, TypeError):
        raise ErroHistorico("O bloco de resultado (res) do painel não tem o formato esperado.")
    meses = list(d["dev"].get("meses", []))
    dados = {k: d[k] for k in CHAVES_USADAS if k in d}
    return {"dados": dados, "meses": meses, "avisos": avisos, "arquivo": nome, "sha256": hashlib.sha256(conteudo).hexdigest()}


def instalado(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_historico_painel'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def gravar(conn, lido: dict, mes: str, arquivo: str, usuario: str | None) -> dict:
    """Grava o historico como importacao ativa do mes de referencia ('AAAA-MM'); a anterior do mesmo mes fica ativo=false. Mesmo arquivo: nao grava de novo."""
    mes_dt = f"{mes}-01"
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, mes FROM pnl_importacao WHERE tipo='HISTORICO' AND arquivo_sha256=%s", (lido["sha256"],))
            ja = cur.fetchone()
            if ja:
                return {"repetido": True, "id": ja[0], "ativo": ja[1], "mes": ja[2].strftime("%Y-%m")}
            cur.execute("UPDATE pnl_importacao SET ativo=false WHERE tipo='HISTORICO' AND mes=%s AND escopo='' AND ativo", (mes_dt,))
            cur.execute("""INSERT INTO pnl_importacao (tipo, mes, escopo, arquivo_nome, arquivo_sha256, importado_por, n_linhas, detalhe)
                           VALUES ('HISTORICO', %s, '', %s, %s, %s, %s, %s) RETURNING id""",
                        (mes_dt, arquivo, lido["sha256"], usuario, len(lido["meses"]),
                         json.dumps({"meses": lido["meses"], "avisos": lido["avisos"]}, ensure_ascii=False)))
            iid = cur.fetchone()[0]
            cur.execute("INSERT INTO pnl_historico_painel (importacao_id, dados) VALUES (%s, %s)", (iid, json.dumps(lido["dados"], ensure_ascii=False)))
    return {"repetido": False, "id": iid, "mes": mes}


def ativo(conn) -> dict | None:
    """Historico em uso (o do mes mais recente): {'mes': 'AAAA-MM', 'id', 'arquivo', 'dados': {...}} ou None (sem tabela / sem importacao)."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT i.id, to_char(i.mes,'YYYY-MM'), i.arquivo_nome, h.dados FROM pnl_importacao i JOIN pnl_historico_painel h ON h.importacao_id = i.id
                           WHERE i.tipo='HISTORICO' AND i.ativo ORDER BY i.mes DESC, i.id DESC LIMIT 1""")
            r = cur.fetchone()
    except Exception:
        return None
    if not r:
        return None
    dados = r[3] if isinstance(r[3], dict) else json.loads(r[3])
    return {"id": r[0], "mes": r[1], "arquivo": r[2], "dados": dados}


def _par(v):
    """Os blocos do painel vem como [previsto, realizado] ou so' o numero."""
    return v[1] if isinstance(v, list) else v


def resumo(h: dict) -> dict:
    """Numeros prontos para as telas/PDF: acumulado do ano, desvio mensal, recomposicao, HE mes a mes, custos com pessoas (so' valores, sem nomes)."""
    d = h["dados"]
    acc = {k: _par(v) for k, v in d["res"]["acc"].items()}
    mes_ref = {k: _par(v) for k, v in d["res"]["set"].items()}
    ate = h["mes"]
    ano = int(ate[:4])
    n = int(ate[5:])
    dev = d["dev"]
    ROT = {"Base-line (Receita)": "rec", "Custos": "cus", "BDI - Resultado": "bdi", "Despesas ADM": "adm", "Lucro do Período": "res"}
    accdev = d["res"].get("accdev", {})
    rotulos = [m for m in dev.get("meses", []) if m in MESES]
    # Janeiro nao vem no painel: = desvio acumulado menos a soma de fev a set (conta explicada pela contabilidade)
    linhas, tem_jan = {}, bool(accdev) and rotulos[:1] == ["Fev"]
    # o banco (jsonb) reordena as chaves do objeto; a ordem do painel (Receita, Custos, BDI, ADM, Lucro) e' refeita pela tabela ROT
    ordem = list(ROT)
    itens = sorted(dev.get("rows", {}).items(), key=lambda kv: (ordem.index(kv[0]) if kv[0] in ordem else len(ordem), kv[0]))
    for nome, vals in itens:
        vals = [float(x) for x in vals]
        k = ROT.get(nome)
        jan = (float(_par(accdev[k])) - sum(vals)) if (tem_jan and k in accdev) else None
        linhas[nome] = ([jan] if tem_jan else []) + vals
    meses_dev = [{"mes": f"{ano}-{MESES.index(m) + 1:02d}", "rotulo": m} for m in (["Jan"] if tem_jan else []) + rotulos]
    he = d.get("he", {})
    serie_he = []
    for i, (a, b) in enumerate(zip(he.get("he", []), he.get("sal", []))):
        if b:
            serie_he.append({"mes": f"{ano}-{i + 1:02d}", "he": float(a), "base": float(b), "pct": round(float(a) / float(b), 4)})
    pess = [{"nome": r[0], "mes": float(r[1]), "acumulado": float(r[2])} for r in d.get("pess", []) if len(r) >= 3]
    recomp = [{"rotulo": r[0], "projecao": float(r[1]), "para_cobrir": float(r[2])} for r in d.get("recomp", []) if len(r) >= 3]
    return {"ate": ate, "acumulado": acc, "mes_ref": mes_ref, "desvio_meses": meses_dev, "desvio_linhas": linhas, "desvio_acumulado": {k: float(_par(v)) for k, v in accdev.items()}, "serie_he": serie_he,
            "pessoas": pess, "recomposicao": recomp, "headcount": d.get("hc", {}).get("hist", [])}


def serie_he_combinada(res_hist: dict | None, serie_app: list) -> list:
    """HE + DSR / remuneracao mes a mes: meses do historico do painel da contabilidade + meses com folha no app (o app vale onde existe).
    -> [{'mes': 'AAAA-MM', 'he_pct': 0.49, 'origem': 'historico'|'app'}] em ordem de mes. A base do historico (proventos - HE) e' a mesma definicao confirmada."""
    por_mes = {}
    for x in (res_hist or {}).get("serie_he", []):
        por_mes[x["mes"]] = {"mes": x["mes"], "he_pct": x["pct"], "origem": "historico"}
    for x in serie_app or []:
        if x.get("he_pct") is not None:
            por_mes[x["mes"]] = {"mes": x["mes"], "he_pct": x["he_pct"], "origem": "app"}
    return [por_mes[m] for m in sorted(por_mes)]
