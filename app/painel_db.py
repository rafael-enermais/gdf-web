# -*- coding: utf-8 -*-
"""
GDF V2 - Painel EnerMais: gravacao do que vem do Sienge nas tabelas pnl_* e calculos que dependem das REGRAS (pnl_regra).
Sem streamlit. Mesma disciplina do db.py: nada e' apagado (a role nao tem DELETE); cada sincronizacao fica registrada em pnl_sync;
a leitura so' enxerga baixas/rateios da ULTIMA sincronizacao de cada titulo (views pnl_v_baixa / pnl_v_rateio).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json

from psycopg2.extras import execute_values

import db

TABELAS_V2 = ("pnl_sync", "pnl_titulo", "pnl_baixa", "pnl_rateio", "pnl_regra", "pnl_obra", "pnl_centro_custo")


def v2_instalado(conn) -> bool:
    """True se o SQL da V2 (sql/v2_painel_schema.sql) ja foi executado no Supabase."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name = ANY(%s)", (list(TABELAS_V2),))
        return cur.fetchone()[0] == len(TABELAS_V2)


# ---------------------------------------------------------------- sincronizacao
def criar_sync(conn, mes: str, lado: str, tipo_data: str, usuario: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO pnl_sync (mes, lado, tipo_data, usuario) VALUES (%s,%s,%s,%s) RETURNING id",
                    (f"{mes}-01", lado, tipo_data, usuario))
        return cur.fetchone()[0]


def finalizar_sync(conn, sync_id: int, status: str, n_tit=0, n_bx=0, n_rt=0, valor=None, erro: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_sync SET status=%s, n_titulos=%s, n_baixas=%s, n_rateios=%s, valor_liquido=%s, erro=%s, finalizado_em=now() WHERE id=%s",
                    (status, n_tit, n_bx, n_rt, valor, (erro or None) and erro[:500], sync_id))


def _tem_coluna(cur, tabela: str, coluna: str) -> bool:
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s", (tabela, coluna))
    return cur.fetchone() is not None


def gravar_normalizado(conn, sync_id: int, norm: dict) -> dict:
    """Grava titulos, baixas e rateios (upsert) numa unica transacao. Devolve contagens e o liquido total das baixas."""
    tit, bx, rt = norm["titulos"], norm["baixas"], norm["rateios"]
    with db.transacao(conn):
        with conn.cursor() as cur:
            if tit:
                com_imposto = _tem_coluna(cur, "pnl_titulo", "imposto_titulo")          # SQL-13; sem ela grava como antes (nada quebra)
                col_extra, upd_extra = (",imposto_titulo", ", imposto_titulo=EXCLUDED.imposto_titulo") if com_imposto else ("", "")
                execute_values(cur, f"""
                    INSERT INTO pnl_titulo (lado,bill_id,installment_id,sync_id,empresa_id,empresa_nome,origem,doc_id,doc_nome,previsao,numero_doc,
                        contraparte_id,contraparte_nome,data_emissao,data_vencimento,valor_original,tipo_negocio_id,tipo_negocio_nome,
                        area_id,area_nome,projeto_id,projeto_nome{col_extra})
                    VALUES %s
                    ON CONFLICT (lado,bill_id,installment_id) DO UPDATE SET
                        sync_id=EXCLUDED.sync_id, empresa_id=EXCLUDED.empresa_id, empresa_nome=EXCLUDED.empresa_nome, origem=EXCLUDED.origem,
                        doc_id=EXCLUDED.doc_id, doc_nome=EXCLUDED.doc_nome, previsao=EXCLUDED.previsao, numero_doc=EXCLUDED.numero_doc,
                        contraparte_id=EXCLUDED.contraparte_id, contraparte_nome=EXCLUDED.contraparte_nome, data_emissao=EXCLUDED.data_emissao,
                        data_vencimento=EXCLUDED.data_vencimento, valor_original=EXCLUDED.valor_original, tipo_negocio_id=EXCLUDED.tipo_negocio_id,
                        tipo_negocio_nome=EXCLUDED.tipo_negocio_nome, area_id=EXCLUDED.area_id, area_nome=EXCLUDED.area_nome,
                        projeto_id=EXCLUDED.projeto_id, projeto_nome=EXCLUDED.projeto_nome{upd_extra}, atualizado_em=now()""",
                               [(t["lado"], t["bill_id"], t["installment_id"], sync_id, t["empresa_id"], t["empresa_nome"], t["origem"], t["doc_id"],
                                 t["doc_nome"], t["previsao"], t["numero_doc"], t["contraparte_id"], t["contraparte_nome"], t["data_emissao"],
                                 t["data_vencimento"], t["valor_original"], t["tipo_negocio_id"], t["tipo_negocio_nome"], t["area_id"],
                                 t["area_nome"], t["projeto_id"], t["projeto_nome"]) + ((t.get("imposto_titulo"),) if com_imposto else ()) for t in tit],
                               page_size=500)
            if bx:
                execute_values(cur, """
                    INSERT INTO pnl_baixa (lado,bill_id,installment_id,seq,sync_id,data_pagamento,tipo_oper_id,tipo_oper_nome,bruto,liquido,juros,multa,desconto,imposto,correcao)
                    VALUES %s
                    ON CONFLICT (lado,bill_id,installment_id,seq) DO UPDATE SET
                        sync_id=EXCLUDED.sync_id, data_pagamento=EXCLUDED.data_pagamento, tipo_oper_id=EXCLUDED.tipo_oper_id,
                        tipo_oper_nome=EXCLUDED.tipo_oper_nome, bruto=EXCLUDED.bruto, liquido=EXCLUDED.liquido, juros=EXCLUDED.juros,
                        multa=EXCLUDED.multa, desconto=EXCLUDED.desconto, imposto=EXCLUDED.imposto, correcao=EXCLUDED.correcao""",
                               [(b["lado"], b["bill_id"], b["installment_id"], b["seq"], sync_id, b["data_pagamento"], b["tipo_oper_id"],
                                 b["tipo_oper_nome"], b["bruto"], b["liquido"], b["juros"], b["multa"], b["desconto"], b["imposto"], b["correcao"])
                                for b in bx], page_size=500)
            if rt:
                execute_values(cur, """
                    INSERT INTO pnl_rateio (lado,bill_id,installment_id,linha,sync_id,plano_cod,plano_nome,centro_custo_id,centro_custo_nome,percentual)
                    VALUES %s
                    ON CONFLICT (lado,bill_id,installment_id,linha) DO UPDATE SET
                        sync_id=EXCLUDED.sync_id, plano_cod=EXCLUDED.plano_cod, plano_nome=EXCLUDED.plano_nome,
                        centro_custo_id=EXCLUDED.centro_custo_id, centro_custo_nome=EXCLUDED.centro_custo_nome, percentual=EXCLUDED.percentual""",
                               [(r["lado"], r["bill_id"], r["installment_id"], r["linha"], sync_id, r["plano_cod"], r["plano_nome"],
                                 r["centro_custo_id"], r["centro_custo_nome"], r["percentual"]) for r in rt], page_size=500)
    return {"titulos": len(tit), "baixas": len(bx), "rateios": len(rt), "liquido": round(sum((b["liquido"] or 0) for b in bx), 2)}


def gravar_cadastros(conn, cad: dict) -> dict:
    """Upsert dos cadastros (empresas, centros de custo, plano, tipos de negocio). Nao mexe no de-para centro de custo -> obra."""
    with db.transacao(conn):
        with conn.cursor() as cur:
            if cad["empresas"]:
                execute_values(cur, "INSERT INTO pnl_empresa_sienge (id,nome,cnpj) VALUES %s ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, cnpj=EXCLUDED.cnpj, atualizado_em=now()",
                               [(x["id"], x["nome"], x["cnpj"]) for x in cad["empresas"]])
            if cad["centros_custo"]:
                execute_values(cur, "INSERT INTO pnl_centro_custo (id,nome,empresa_id) VALUES %s ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, empresa_id=EXCLUDED.empresa_id, atualizado_em=now()",
                               [(x["id"], x["nome"], x["empresa_id"]) for x in cad["centros_custo"]])
            if cad["plano"]:
                execute_values(cur, "INSERT INTO pnl_plano_conta (codigo,codigo_sienge,nome,tipo,redutora,ativa) VALUES %s ON CONFLICT (codigo) DO UPDATE SET codigo_sienge=EXCLUDED.codigo_sienge, nome=EXCLUDED.nome, tipo=EXCLUDED.tipo, redutora=EXCLUDED.redutora, ativa=EXCLUDED.ativa, atualizado_em=now()",
                               [(x["codigo"], x["codigo_sienge"], x["nome"], x["tipo"], x["redutora"], x["ativa"]) for x in cad["plano"]])
            if cad["tipos_negocio"]:
                execute_values(cur, "INSERT INTO pnl_tipo_negocio (id,nome) VALUES %s ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, atualizado_em=now()",
                               [(x["id"], x["nome"]) for x in cad["tipos_negocio"]])
    return {k: len(v) for k, v in cad.items()}


def sincronizar_mes(conn, cli, mes: str, usuario: str | None, lados=("P", "R"), tipos=("P", "I"), buscar=None, normalizar=None,
                    mes_fim: str | None = None) -> list:
    """Busca no Sienge e grava o mes ('AAAA-MM'), ou a janela de `mes` ate `mes_fim` numa chamada so por (lado, tipo de data).
    Cada (lado, tipo de data) vira uma linha em pnl_sync (OK ou ERRO com a mensagem; em janela, o `mes` do log e' o primeiro).
    `buscar`/`normalizar` existem para os testes injetarem dados sem rede."""
    import sienge_api as S
    buscar = buscar or S.buscar_bulk
    normalizar = normalizar or S.normalizar_titulos
    resultado = []
    for lado in lados:
        for tipo in tipos:
            sid = criar_sync(conn, mes, lado, tipo, usuario)
            try:
                regs = buscar(cli, lado, mes, tipo) if not mes_fim or mes_fim == mes else buscar(cli, lado, mes, tipo, mes_fim=mes_fim)
                norm = normalizar(lado, regs)
                cont = gravar_normalizado(conn, sid, norm)
                finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
                resultado.append({"lado": lado, "tipo": tipo, "ok": True, **cont, "avisos": norm.get("avisos") or {}})
                registrar_log(conn, "SYNC_OK", usuario=usuario, mes=mes, detalhe={"lado": lado, "tipo": tipo, "titulos": cont["titulos"], "baixas": cont["baixas"], "rateios": cont["rateios"], "sync_id": sid})
            except Exception as exc:                      # registra e segue para o proximo; nunca derruba a tela
                finalizar_sync(conn, sid, "ERRO", erro=str(exc))
                resultado.append({"lado": lado, "tipo": tipo, "ok": False, "erro": str(exc)})
                registrar_log(conn, "SYNC_ERRO", "ERRO", usuario, mes, {"lado": lado, "tipo": tipo, "erro": str(exc)[:300], "sync_id": sid})
                if "HTTP 429" in str(exc):                # limite do Sienge persistiu: insistir so piora; para e deixa para a proxima execucao
                    return resultado
    return resultado


def sincronizar_banco(conn, cli, mes: str, usuario: str | None, mes_fim: str | None = None, buscar=None, normalizar=None) -> dict:
    """Busca o movimento bancario do Sienge (juros, tarifas e outros avisos de lancamento sem titulo) e grava junto com os titulos a pagar
    (lado P, data 'M' no log). Devolve {'ok','titulos','baixas','rateios','liquido'} ou {'ok': False,'erro'}."""
    import sienge_api as S
    buscar = buscar or S.buscar_movimento_banco
    normalizar = normalizar or S.normalizar_movimentos
    sid = criar_sync(conn, mes, "P", "M", usuario)
    try:
        regs = buscar(cli, mes) if not mes_fim or mes_fim == mes else buscar(cli, mes, mes_fim=mes_fim)
        cont = gravar_normalizado(conn, sid, normalizar(regs))
        finalizar_sync(conn, sid, "OK", cont["titulos"], cont["baixas"], cont["rateios"], cont["liquido"])
        registrar_log(conn, "SYNC_BANCO_OK", usuario=usuario, mes=mes, detalhe={"lancamentos": cont["titulos"], "rateios": cont["rateios"], "sync_id": sid})
        return {"ok": True, **cont}
    except Exception as exc:
        finalizar_sync(conn, sid, "ERRO", erro=str(exc))
        registrar_log(conn, "SYNC_BANCO_ERRO", "ERRO", usuario, mes, {"erro": str(exc)[:300], "sync_id": sid})
        return {"ok": False, "erro": str(exc)}


def meses_com_dados(conn) -> list:
    """Meses ('AAAA-MM') com pagamentos a pagar gravados, pela data do pagamento. So' meses COMPLETOS: do mes inicial da primeira carga OK
    ate o mes atual (uma carga por janela traz tambem pagamentos antigos/futuros dos titulos da janela, que nao formam um mes inteiro)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT to_char(b.data_pagamento, 'YYYY-MM') FROM pnl_v_baixa b
                       WHERE b.lado='P' AND b.data_pagamento IS NOT NULL
                         AND b.data_pagamento >= (SELECT min(mes) FROM pnl_sync WHERE status='OK' AND lado='P' AND tipo_data='P')
                         AND b.data_pagamento < (date_trunc('month', CURRENT_DATE) + interval '1 month')
                       ORDER BY 1""")
        return [r[0] for r in cur.fetchall()]


def documentos_do_mes(conn, mes: str) -> list:
    """Conferencia do mes: pagamentos a pagar agrupados por tipo de documento, origem do titulo, previsao e tipo de operacao da baixa.
    Serve para achar o que marca 'previsao', 'folha de pagamento' e 'reapropriacao'. Nao mostra nomes de credores."""
    ini = f"{mes}-01"
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(t.doc_id,'') AS doc_id, max(COALESCE(t.doc_nome,'')) AS doc_nome, COALESCE(t.origem,'') AS origem,
                   COALESCE(t.previsao,'') AS previsao, b.tipo_oper_id, count(DISTINCT (t.bill_id, t.installment_id)) AS titulos,
                   count(*) AS baixas, sum(b.liquido) AS liquido
            FROM pnl_v_baixa b
            JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
            WHERE b.lado='P' AND b.data_pagamento >= %s::date AND b.data_pagamento < (%s::date + interval '1 month')
            GROUP BY 1,3,4,5 ORDER BY sum(b.liquido) DESC NULLS LAST""", (ini, ini))
        return [{"doc_id": d, "doc_nome": n, "origem": o, "previsao": p, "tipo_oper": t, "titulos": ti, "baixas": ba, "liquido": round(float(l or 0), 2)}
                for d, n, o, p, t, ti, ba, l in cur.fetchall()]


def ultimas_syncs(conn, limite: int = 12) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT id, mes, lado, tipo_data, status, n_titulos, n_baixas, n_rateios, valor_liquido, usuario, erro, iniciado_em, finalizado_em "
                    "FROM pnl_sync ORDER BY id DESC LIMIT %s", (limite,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------- regras
def regras_ativas(conn, area: str) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT tipo, valor, descricao, status, id FROM pnl_regra WHERE area=%s AND ativo ORDER BY id", (area,))
        return [{"tipo": t, "valor": v, "descricao": d, "status": s, "id": i} for t, v, d, s, i in cur.fetchall()]


def prefixos_excluidos(regras: list) -> list:
    return [r["valor"] for r in regras if r["tipo"] == "EXCLUI_PLANO_PREFIXO"]


def exclui_previsao(regras: list) -> bool:
    """True se existe a regra ativa EXCLUI_PREVISAO (tirar baixas de documentos com previsao = 'S': PRV, PCT, PPC, FOPA...)."""
    return any(r["tipo"] == "EXCLUI_PREVISAO" and str(r["valor"]).upper() == "S" for r in regras)


# Regras que o app garante que existam (nasce como PROPOSTA; a contabilidade/Rafael confirma na aba Regras)
REGRAS_PADRAO = [
    ("DESPESAS", "EXCLUI_PREVISAO", "S", "Baixas de documentos de previsao (previsao = S: PRV, PCT, PPC, FOPA): sao a troca do papel de previsao pelo documento real, nao dinheiro saindo (reapropriacao)",
     "setembro/2026: o CSV de contas pagas nao tem nenhum documento de previsao"),
]


def garantir_regras_padrao(conn, usuario: str = "sistema") -> int:
    """Cria as regras de REGRAS_PADRAO que ainda nao existem (nunca mexe nas que ja existem). Devolve quantas criou."""
    criadas = 0
    with conn.cursor() as cur:
        for area, tipo, valor, desc, motivo in REGRAS_PADRAO:
            cur.execute("""INSERT INTO pnl_regra (area, tipo, valor, descricao, status, alterado_por, motivo)
                           SELECT %s,%s,%s,%s,'PROPOSTA',%s,%s
                           WHERE NOT EXISTS (SELECT 1 FROM pnl_regra WHERE area=%s AND tipo=%s AND valor=%s AND ativo)""",
                        (area, tipo, valor, desc, usuario, motivo, area, tipo, valor))
            criadas += cur.rowcount
    conn.commit()
    return criadas


def confirmar_regras(conn, ids: list, usuario: str, motivo: str = "confirmada na tela") -> int:
    """Marca regras como CONFIRMADA (guarda quem e quando). Devolve quantas mudaram."""
    if not ids:
        return 0
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_regra SET status='CONFIRMADA', alterado_por=%s, alterado_em=now(), motivo=%s WHERE id = ANY(%s) AND ativo AND status<>'CONFIRMADA'",
                    (usuario, motivo, list(ids)))
        n = cur.rowcount
    conn.commit()
    registrar_log(conn, "REGRA_CONFIRMADA", usuario=usuario, detalhe={"ids": [int(i) for i in ids], "mudaram": n, "motivo": motivo})
    return n


def _excluido(cod: str, prefixos: list) -> bool:
    return any(cod == p or cod.startswith(p + ".") for p in prefixos)


# ---------------------------------------------------------------- Despesas (aba do painel)
def despesas_do_mes(conn, mes: str, prefixos: list, tipo_oper_fora: list | None = None, doc_fora: list | None = None,
                    sem_previsao: bool = False) -> list:
    """Despesas pagas no mes ('AAAA-MM') por conta do plano: soma(liquido da baixa x % do rateio), SEM as contas excluidas pelas regras (e, se sem_previsao, sem baixas de documentos de previsao).
    Devolve [{'plano_cod','plano_nome','valor'}] ordenado do maior para o menor. Datas por pagamento (tipo P)."""
    ini = f"{mes}-01"
    filtros, par = [], [ini, ini]
    if tipo_oper_fora:
        filtros.append("AND NOT (b.tipo_oper_id = ANY(%s))")
        par.append(list(tipo_oper_fora))
    if doc_fora:
        filtros.append("AND NOT (COALESCE(t.doc_id,'') = ANY(%s))")
        par.append(list(doc_fora))
    if sem_previsao:                                   # regra EXCLUI_PREVISAO: tira documentos com previsao = 'S'
        filtros.append("AND COALESCE(upper(t.previsao),'') <> 'S'")
    sql = f"""
        SELECT r.plano_cod, max(r.plano_nome) AS plano_nome, sum(b.liquido * r.percentual / 100.0) AS valor
        FROM pnl_v_baixa b
        JOIN pnl_v_rateio r ON r.lado=b.lado AND r.bill_id=b.bill_id AND r.installment_id=b.installment_id
        JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
        WHERE b.lado='P' AND b.data_pagamento >= %s::date AND b.data_pagamento < (%s::date + interval '1 month')
        {' '.join(filtros)}
        GROUP BY r.plano_cod"""
    with conn.cursor() as cur:
        cur.execute(sql, par)
        linhas = [{"plano_cod": c, "plano_nome": n, "valor": round(float(v or 0), 2)} for c, n, v in cur.fetchall()]
    linhas = [l for l in linhas if not _excluido(l["plano_cod"], prefixos)]
    return sorted(linhas, key=lambda l: -l["valor"])


# ---------------------------------------------------------------- conferencia com o CSV de contas pagas do Sienge
def _num_br(s) -> float:
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def despesas_do_csv(conteudo: bytes, prefixos: list) -> dict:
    """Le o ExportacaoContasPagas.csv (as mesmas colunas da exportacao do Sienge) e soma 'Valor aprop fin' por conta, aplicando as mesmas regras.
    Devolve {'por_conta': {cod: (nome, valor)}, 'total_bruto', 'total_despesas', 'linhas'}."""
    txt = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            txt = conteudo.decode(enc)
            break
        except Exception:
            continue
    if txt is None:
        raise ValueError("Não consegui ler o arquivo (codificação).")
    rd = csv.reader(io.StringIO(txt), delimiter=";")
    cab = [c.strip() for c in next(rd, [])]
    obrig = ("Código plano fin", "Desc plano fin", "Valor aprop fin")
    if any(c not in cab for c in obrig):
        raise ValueError("Este não parece o CSV de contas pagas do Sienge (faltam as colunas do plano financeiro e do valor apropriado).")
    ix = {c: i for i, c in enumerate(cab)}
    meses = {}                                           # mes (AAAA-MM) da "Data pagamento" de cada linha: serve para avisar se o CSV e' de outro mes
    por, bruto, n = {}, 0.0, 0
    for r in rd:
        if len(r) < len(cab) - 3:
            continue
        cod, nome, v = r[ix["Código plano fin"]].strip(), r[ix["Desc plano fin"]].strip(), _num_br(r[ix["Valor aprop fin"]])
        n += 1
        bruto += v
        if "Data pagamento" in ix:
            m = r[ix["Data pagamento"]].strip()[:7]
            if len(m) == 7 and m[4] == "-":
                meses[m] = meses.get(m, 0) + 1
        if not _excluido(cod, prefixos):
            antigo = por.get(cod, (nome, 0.0))
            por[cod] = (nome, round(antigo[1] + v, 2))
    return {"por_conta": por, "total_bruto": round(bruto, 2), "total_despesas": round(sum(v for _, v in por.values()), 2), "linhas": n,
            "meses": meses, "mes_dominante": max(meses, key=meses.get) if meses else None}


def comparar_despesas(db_linhas: list, csv_res: dict, tolerancia: float = 0.5) -> dict:
    """Compara Despesas do banco (API) com as do CSV por conta. Devolve totais e as contas com diferenca > tolerancia."""
    api = {l["plano_cod"]: (l["plano_nome"], l["valor"]) for l in db_linhas}
    csvp = csv_res["por_conta"]
    dif = []
    for cod in sorted(set(api) | set(csvp)):
        a, c = api.get(cod, ("", 0.0))[1], csvp.get(cod, ("", 0.0))[1]
        if abs(a - c) > tolerancia:
            dif.append({"plano_cod": cod, "plano_nome": (api.get(cod) or csvp.get(cod))[0], "api": a, "csv": c, "dif": round(a - c, 2)})
    dif.sort(key=lambda d: -abs(d["dif"]))
    todas = [{"plano_cod": cod, "plano_nome": (api.get(cod) or csvp.get(cod))[0], "api": api.get(cod, ("", 0.0))[1], "csv": csvp.get(cod, ("", 0.0))[1],
              "dif": round(api.get(cod, ("", 0.0))[1] - csvp.get(cod, ("", 0.0))[1], 2)} for cod in sorted(set(api) | set(csvp))
             if cod or abs(api.get(cod, ("", 0.0))[1]) > 0.005 or abs(csvp.get(cod, ("", 0.0))[1]) > 0.005]       # some a linha sem conta e sem valor
    return {"total_api": round(sum(v for _, v in api.values()), 2), "total_csv": csv_res["total_despesas"], "contas_com_diferenca": dif, "contas": todas}


def _br(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def csv_conferencia(cmp: dict, mes: str) -> bytes:
    """CSV da conferencia (todas as contas: API, CSV, diferenca; linha de total no fim; 'confere' = sim/nao). Separador ';', decimal ',', abre no Excel."""
    linhas = ["mes;conta;nome;valor_api;valor_csv;diferenca;confere"]
    for c in cmp["contas"]:
        nome = str(c["plano_nome"] or "").replace(";", ",").replace("\n", " ")
        linhas.append(f"{mes};{c['plano_cod']};{nome};{_br(c['api'])};{_br(c['csv'])};{_br(c['dif'])};{'sim' if abs(c['dif']) <= 0.5 else 'nao'}")
    dif = round(cmp["total_api"] - cmp["total_csv"], 2)
    linhas.append(f"{mes};TOTAL;;{_br(cmp['total_api'])};{_br(cmp['total_csv'])};{_br(dif)};{'sim' if not cmp['contas_com_diferenca'] else 'nao'}")
    return ("\n".join(linhas) + "\n").encode("utf-8-sig")


# ---------------------------------------------------------------- logs (historico de conferencias, erros, acoes)
def log_instalado(conn) -> bool:
    """True se a tabela de logs (sql/v2_log.sql) ja foi criada. O app funciona sem ela (so nao registra)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_log'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def registrar_log(conn, acao: str, nivel: str = "INFO", usuario: str | None = None, mes: str | None = None, detalhe: dict | None = None) -> bool:
    """Grava uma linha no historico. NUNCA derruba a tela: se a tabela nao existe ou der erro, devolve False e segue.
    `detalhe` guarda so contagens, totais, nomes de arquivo e hashes (o repositorio e' publico: nada de linha de dado de pessoa)."""
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO pnl_log (usuario, nivel, acao, mes, detalhe) VALUES (%s,%s,%s,%s,%s)",
                        (usuario, nivel if nivel in ("INFO", "ERRO", "AVISO") else "INFO", acao[:80],
                         f"{mes}-01" if mes and len(mes) == 7 else None, json.dumps(detalhe or {}, ensure_ascii=False, default=str)))
        return True
    except Exception:
        return False


def ultimos_logs(conn, nivel: str | None = None, acao: str | None = None, limite: int = 300) -> list:
    """Linhas mais recentes do historico (filtro opcional por nivel e por acao). Lista vazia se a tabela ainda nao existe."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, quando, usuario, nivel, acao, mes, detalhe FROM pnl_log
                           WHERE (%s::text IS NULL OR nivel=%s) AND (%s::text IS NULL OR acao=%s) ORDER BY id DESC LIMIT %s""",
                        (nivel, nivel, acao, acao, limite))
            return [{"id": i, "quando": q, "usuario": u, "nivel": n, "acao": a, "mes": m, "detalhe": d if isinstance(d, dict) else json.loads(d or "{}")}
                    for i, q, u, n, a, m, d in cur.fetchall()]
    except Exception:
        return []


def csv_logs(linhas: list) -> bytes:
    """Historico em CSV (';', abre no Excel): quando;usuario;nivel;acao;mes;detalhe."""
    out = ["quando;usuario;nivel;acao;mes;detalhe"]
    for l in linhas:
        det = json.dumps(l["detalhe"], ensure_ascii=False).replace(";", ",").replace("\n", " ")
        out.append(f"{l['quando']:%Y-%m-%d %H:%M:%S};{l['usuario'] or ''};{l['nivel']};{l['acao']};{l['mes'].strftime('%Y-%m') if l['mes'] else ''};{det}")
    return ("\n".join(out) + "\n").encode("utf-8-sig")


def sha256_curto(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()[:16]


# ---------------------------------------------------------------- Resultado (DRE gerencial, comprometido por data de emissao)
def meses_com_emissao(conn) -> list:
    """Meses ('AAAA-MM') que tem titulos emitidos no banco (base da aba Resultado)."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT to_char(data_emissao,'YYYY-MM') FROM pnl_titulo WHERE data_emissao IS NOT NULL ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def _sinal_resultado(lado: str, plano_cod: str) -> int:
    """Receitas (a receber) contam +; custos/despesas (a pagar) contam -; as contas de deducao da receita (1.01.02 e 1.01.03) sempre -."""
    if plano_cod.startswith(("1.01.02", "1.01.03")):
        return -1
    return 1 if lado == "R" else -1


def _filtro_distrato(sem_distrato: bool) -> str:
    """Tira da RECEITA os titulos desfeitos por distrato: titulo a receber (lado R) cujas baixas do tipo 7 (Distrato) somam o valor todo.
    O Sienge continua listando a NF na API, mas o DRE gerencial dele nao a conta (conferido em set/2026: obras 109, 111, 118, 121 e demais = 100% das diferencas de receita)."""
    if not sem_distrato:
        return ""
    return """AND NOT (t.lado='R' AND EXISTS (SELECT 1 FROM pnl_baixa dx WHERE dx.lado=t.lado AND dx.bill_id=t.bill_id AND dx.installment_id=t.installment_id
                                            AND dx.tipo_oper_id=7 HAVING COALESCE(sum(dx.bruto),0) >= COALESCE(t.valor_original,0) - 0.01))"""


def centro_grupo_instalado(conn) -> bool:
    """True se a tabela do de-para (sql/v2_centro_grupo.sql) existe E ja tem linhas (os dados vem do vault)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pnl_centro_grupo")
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def resultado_por_conta(conn, mes: str, sem_previsao: bool = False, so_obras: bool = False, sem_distrato: bool = True) -> list:
    """Valor COMPROMETIDO do mes por conta do plano: soma(valor do titulo x % do rateio) dos titulos EMITIDOS no mes, com sinal de DRE
    (receita +, custo -). `so_obras` tira os centros de custo do grupo ADM (de-para pnl_centro_grupo); centro sem de-para fica dentro.
    Devolve [{'plano_cod','plano_nome','valor'}]. Mesmo criterio do DRE gerencial 'Comprometido, selecao por data de emissao'."""
    ini = f"{mes}-01"
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro_prev = filtro                                    # descontos das baixas: so previsao (nao distrato; conferido sem esse filtro)
    filtro += " " + _filtro_distrato(sem_distrato)
    juncao = "LEFT JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id" if so_obras else ""
    filtro_cc = "AND COALESCE(g.grupo,'') <> 'ADM'" if so_obras else ""
    with conn.cursor() as cur:
        cur.execute(f"""SELECT t.lado, r.plano_cod, max(r.plano_nome), sum(t.valor_original * r.percentual / 100.0)
                        FROM pnl_titulo t JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
                        {juncao}
                        WHERE t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month') {filtro} {filtro_cc}
                        GROUP BY t.lado, r.plano_cod""", (ini, ini))
        linhas = cur.fetchall()
    por = {}
    for lado, cod, nome, v in linhas:
        a = por.setdefault(cod, {"plano_cod": cod, "plano_nome": nome, "valor": 0.0})
        a["valor"] = round(a["valor"] + _sinal_resultado(lado, cod) * float(v or 0), 2)
    # Descontos concedidos (1.01.03.01): a API nao traz essa conta no rateio; vem dos descontos das baixas dos titulos de receita emitidos no mes
    # (conferido ao centavo com o DRE do Sienge de set/2026: 11.594,08).
    with conn.cursor() as cur:
        cur.execute(f"""SELECT COALESCE(sum(b.desconto),0) FROM pnl_baixa b JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
                        WHERE t.lado='R' AND t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month') {filtro_prev}""", (ini, ini))
        desc = float(cur.fetchone()[0] or 0)
    if abs(desc) > 0.004 and "1.01.03.01" not in por:
        por["1.01.03.01"] = {"plano_cod": "1.01.03.01", "plano_nome": "Descontos concedidos (descontos das baixas)", "valor": round(-desc, 2)}
    # Impostos sobre o faturamento (02.02): a API traz no proprio titulo de receita (taxAmount = ISS/PIS/COFINS da NF; SQL-13), nao no rateio nem nas baixas.
    # Mesmos filtros da receita (previsao e distrato). Sem a coluna ou sem valores, a linha fica de fora (como antes).
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT COALESCE(sum(t.imposto_titulo),0) FROM pnl_titulo t
                            WHERE t.lado='R' AND t.imposto_titulo IS NOT NULL AND t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month') {filtro}""",
                        (ini, ini))
            imp = float(cur.fetchone()[0] or 0)
    except Exception:
        conn.rollback()
        imp = 0.0
    if abs(imp) > 0.004 and "1.01.02.01" not in por:
        por["1.01.02.01"] = {"plano_cod": "1.01.02.01", "plano_nome": "Impostos sobre o faturamento (imposto do titulo da NF)", "valor": round(-imp, 2)}
    return sorted(por.values(), key=lambda d: d["plano_cod"])


def resultado_por_centro(conn, mes: str, sem_previsao: bool = False, sem_distrato: bool = True) -> list:
    """Diagnostico: receita e custo (so contas do DRE de obras: 1.01.01 e 2.01.*) por centro de custo, com o grupo do de-para (ou 'sem de-para')."""
    ini = f"{mes}-01"
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro += " " + _filtro_distrato(sem_distrato)
    with conn.cursor() as cur:
        try:
            cur.execute(f"""SELECT r.centro_custo_id, max(r.centro_custo_nome), max(g.grupo), max(g.codigo_obra), t.lado, sum(t.valor_original * r.percentual / 100.0)
                            FROM pnl_titulo t JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
                            LEFT JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id
                            WHERE t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month') {filtro}
                              AND (r.plano_cod LIKE '1.01.01%%' OR r.plano_cod LIKE '2.01.%%')
                            GROUP BY r.centro_custo_id, t.lado""", (ini, ini))
        except Exception:
            return []
        linhas = cur.fetchall()
    por = {}
    for cid, nome, grupo, cod, lado, v in linhas:
        a = por.setdefault(cid, {"centro_id": cid, "centro": nome, "grupo": grupo or "sem de-para", "codigo": cod or "", "receita": 0.0, "custo": 0.0})
        a["receita" if lado == "R" else "custo"] += float(v or 0) * (1 if lado == "R" else -1)       # custo com sinal negativo, como no DRE
    return sorted(({**a, "receita": round(a["receita"], 2), "custo": round(a["custo"], 2)} for a in por.values()), key=lambda a: -(abs(a["receita"]) + abs(a["custo"])))


def dre_de_folhas(folha: dict) -> dict:
    """Monta o DRE (linhas de total) a partir do valor de cada linha 'folha' ({'01.01': 1000.0, '04.01': -300.0, ...}). Linha ausente conta 0."""
    from dre_mapa import LINHAS
    g = lambda k: float(folha.get(k, 0.0) or 0.0)
    v = {k: round(g(k), 2) for k, _, t in LINHAS if t == "folha"}
    v["01"] = v["01.01"]
    v["02"] = round(v["02.01"] + v["02.02"], 2)
    v["03"] = round(v["01"] + v["02"], 2)
    v["04"] = round(sum(v[k] for k in ("04.01", "04.02", "04.03", "04.04")), 2)
    v["05"] = round(v["03"] + v["04"], 2)
    v["06"] = v["06.04"]
    v["07"] = round(v["05"] + v["06"], 2)
    v["08"] = v["08.02"]
    v["10"] = v["10.01"]
    v["11"] = round(v["07"] + v["08"] + v["10"], 2)
    v["12"] = v["12.01"]
    v["14"] = round(v["11"] + v["12"], 2)
    return {"linhas": [(k, n, v[k]) for k, n, _ in LINHAS], "valores": v}


def dre_do_mes(contas: list) -> dict:
    """Monta o DRE gerencial a partir das contas: devolve {'linhas': [(cod, nome, valor)], 'valores': {...}, 'folha': {...}, 'fora_do_mapa': [contas sem linha no DRE]}."""
    from dre_mapa import MAPA
    folha = {}
    fora = []
    for c in contas:
        lin = MAPA.get(c["plano_cod"])
        if lin is None:
            if abs(c["valor"]) > 0.005:
                fora.append(c)
            continue
        folha[lin] = round(folha.get(lin, 0.0) + c["valor"], 2)
    d = dre_de_folhas(folha)
    return {**d, "folha": folha, "fora_do_mapa": sorted(fora, key=lambda c: -abs(c["valor"]))}


def ler_referencia_dre(conteudo: bytes) -> dict:
    """Le o CSV de referencia (colunas 'conta' e uma coluna que comeca com 'total' ou 'valor'; separador ';' e decimal ',') -> {conta: valor}."""
    txt = conteudo.decode("utf-8-sig", errors="replace")
    rd = csv.reader(io.StringIO(txt), delimiter=";")
    cab = [c.strip().lower() for c in next(rd, [])]
    if "conta" not in cab:
        raise ValueError("CSV de referência sem a coluna 'conta'.")
    ic = cab.index("conta")
    iv = next((i for i, c in enumerate(cab) if c.startswith(("total", "valor"))), None)
    if iv is None:
        raise ValueError("CSV de referência sem coluna 'total' ou 'valor'.")
    out = {}
    for r in rd:
        if len(r) > max(ic, iv) and r[ic].strip():
            out[r[ic].strip()] = _num_br(r[iv])
    return out


def comparar_resultado(contas: list, ref: dict, tolerancia: float = 0.5) -> dict:
    """Compara por conta o comprometido da API com a referencia. Devolve linhas por conta e totais."""
    api = {c["plano_cod"]: (c["plano_nome"], c["valor"]) for c in contas}
    todas = [{"plano_cod": k, "plano_nome": (api.get(k) or ("", 0))[0], "api": api.get(k, ("", 0.0))[1], "ref": ref.get(k, 0.0),
              "dif": round(api.get(k, ("", 0.0))[1] - ref.get(k, 0.0), 2)} for k in sorted(set(api) | set(ref))]
    todas = [t for t in todas if abs(t["api"]) > 0.005 or abs(t["ref"]) > 0.005]
    dif = [t for t in todas if abs(t["dif"]) > tolerancia]
    return {"contas": todas, "contas_com_diferenca": sorted(dif, key=lambda d: -abs(d["dif"]))}


# ---------------------------------------------------------------- DRE oficial do Sienge (PDF importado)
def dre_instalado(conn) -> bool:
    """True se o SQL do DRE em PDF (sql/v2_dre_pdf.sql) ja foi executado."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_dre_valor'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def gravar_dre(conn, dre: dict, arquivo: str, sha256: str, usuario: str | None) -> dict:
    """Grava o DRE lido do PDF como importacao ativa do mes (a anterior do mesmo mes fica ativo=false). Se o mesmo arquivo (sha256) ja foi
    importado, nao grava de novo e devolve {'repetido': True, ...}. Tudo numa transacao so."""
    periodo = dre.get("periodo") or {}
    if not periodo.get("inicio"):
        raise ValueError("O PDF não informa o período; não sei a que mês pertence.")
    mes = periodo["inicio"][:7] + "-01"
    nomes = {o["cod"]: o["nome"] for o in dre["obras"]}
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, mes FROM pnl_importacao WHERE tipo='DRE' AND arquivo_sha256=%s", (sha256,))
            ja = cur.fetchone()
            if ja:
                return {"repetido": True, "id": ja[0], "ativo": ja[1], "mes": ja[2].strftime("%Y-%m")}
            cur.execute("UPDATE pnl_importacao SET ativo=false WHERE tipo='DRE' AND mes=%s AND escopo='' AND ativo", (mes,))
            cur.execute("""INSERT INTO pnl_importacao (tipo, mes, escopo, arquivo_nome, arquivo_sha256, importado_por, n_linhas, detalhe)
                           VALUES ('DRE', %s, '', %s, %s, %s, %s, %s) RETURNING id""",
                        (mes, arquivo, sha256, usuario, len(dre["valores"]),
                         json.dumps({"periodo": periodo, "obras": len(dre["obras"]), "avisos": dre["avisos"]}, ensure_ascii=False)))
            iid = cur.fetchone()[0]
            execute_values(cur, "INSERT INTO pnl_dre_valor (importacao_id, obra_cod, obra_nome, linha, conta, conta_nome, valor) VALUES %s",
                           [(iid, v["obra"], nomes.get(v["obra"]), v["linha"] or "", v["conta"], v["nome"] if v["conta"] else None, v["valor"]) for v in dre["valores"]])
    registrar_log(conn, "DRE_PDF_IMPORTADO", "AVISO" if dre["avisos"] else "INFO", usuario, mes[:7],
                  {"arquivo": arquivo, "sha256": sha256[:16], "importacao_id": iid, "linhas": len(dre["valores"]), "obras": len(dre["obras"]), "avisos": dre["avisos"]})
    return {"repetido": False, "id": iid, "mes": mes[:7]}


def meses_com_dre(conn) -> list:
    """Meses ('AAAA-MM') que ja tem um DRE oficial (PDF) importado e ativo."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(mes,'YYYY-MM') FROM pnl_importacao WHERE tipo='DRE' AND ativo ORDER BY 1")
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def dre_importacao_ativa(conn, mes: str) -> dict | None:
    """Importacao ativa do DRE em PDF para o mes ('AAAA-MM'), ou None (tambem None se o SQL ainda nao foi rodado)."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, arquivo_nome, importado_por, importado_em, n_linhas, status FROM pnl_importacao
                           WHERE tipo='DRE' AND mes=%s::date AND escopo='' AND ativo ORDER BY id DESC LIMIT 1""", (f"{mes}-01",))
            r = cur.fetchone()
    except Exception:
        return None
    return {"id": r[0], "arquivo": r[1], "quem": r[2], "quando": r[3], "linhas": r[4], "status": r[5]} if r else None


def dre_contas_importadas(conn, importacao_id: int) -> dict:
    """Soma das obras por conta do plano no DRE importado: {conta: valor}."""
    with conn.cursor() as cur:
        cur.execute("SELECT conta, sum(valor) FROM pnl_dre_valor WHERE importacao_id=%s AND conta IS NOT NULL GROUP BY conta", (importacao_id,))
        return {c: round(float(v), 2) for c, v in cur.fetchall()}


def dre_por_obra_importado(conn, importacao_id: int) -> dict:
    """{obra_cod: {'nome': ..., 'linhas': {linha_dre: valor}}} das linhas de total do DRE (01, 03, 04, 05, 14...) do PDF."""
    with conn.cursor() as cur:
        cur.execute("SELECT obra_cod, max(obra_nome), linha, sum(valor) FROM pnl_dre_valor WHERE importacao_id=%s AND conta IS NULL GROUP BY obra_cod, linha", (importacao_id,))
        out = {}
        for cod, nome, linha, v in cur.fetchall():
            o = out.setdefault(cod, {"nome": nome, "linhas": {}})
            o["linhas"][linha] = round(float(v), 2)
    return out


def obras_do_dre(conn, mes: str) -> dict | None:
    """Tabela da aba Obras a partir do DRE oficial (PDF) do mes: por obra, receita bruta (linha 01), custos diretos (linha 04), BDI real = receita + custos
    (custos ja vem negativo) e margem = BDI / receita. Obras que nao tem codigo proprio no de-para viram uma linha 'DEM' (demais obras).
    Devolve None se o mes nao tem DRE importado. Sem de-para no banco, todas as obras do PDF aparecem separadas."""
    imp = dre_importacao_ativa(conn, mes)
    if not imp:
        return None
    pdf = dre_por_obra_importado(conn, imp["id"])
    proprios = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT codigo_obra FROM pnl_centro_grupo WHERE COALESCE(codigo_obra,'') NOT IN ('', 'DEM', 'ADM')")
            achados = {r[0] for r in cur.fetchall()}
        proprios = achados or None
    except Exception:
        proprios = None
    linhas, dem = [], {"receita": 0.0, "custo": 0.0, "n": 0}
    for cod, o in pdf.items():
        rec, cus = o["linhas"].get("01", 0.0), o["linhas"].get("04", 0.0)
        if abs(rec) < 0.005 and abs(cus) < 0.005:
            continue
        if proprios is not None and cod not in proprios:
            dem["receita"] += rec; dem["custo"] += cus; dem["n"] += 1
            continue
        linhas.append({"obra": cod, "nome": o["nome"] or "", "receita": rec, "custo": cus})
    if dem["n"]:
        linhas.append({"obra": "DEM", "nome": f"Demais obras ({dem['n']})", "receita": round(dem["receita"], 2), "custo": round(dem["custo"], 2)})
    for l in linhas:
        l["bdi"] = round(l["receita"] + l["custo"], 2)
        l["margem"] = round(l["bdi"] / l["receita"], 4) if abs(l["receita"]) > 0.005 else None
    linhas.sort(key=lambda l: (l["obra"] == "DEM", -l["receita"]))
    rt, ct = round(sum(l["receita"] for l in linhas), 2), round(sum(l["custo"] for l in linhas), 2)
    total = {"receita": rt, "custo": ct, "bdi": round(rt + ct, 2), "margem": round((rt + ct) / rt, 4) if abs(rt) > 0.005 else None}
    proprias = [l for l in linhas if l["obra"] != "DEM"]
    return {"importacao_id": imp["id"], "arquivo": imp["arquivo"], "linhas": linhas, "total": total,
            "top_lucro": sorted(proprias, key=lambda l: -l["bdi"])[:5], "top_prejuizo": sorted((l for l in proprias if l["bdi"] < 0), key=lambda l: l["bdi"])[:5]}


def resultado_por_obra_api(conn, mes: str, sem_previsao: bool = False, sem_distrato: bool = True) -> dict:
    """Mesmo calculo do resultado_por_conta, agrupado pelo codigo da obra do de-para: {codigo_obra: {linha_dre: valor}} (+ 'sem de-para')."""
    ini = f"{mes}-01"
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro += " " + _filtro_distrato(sem_distrato)
    with conn.cursor() as cur:
        try:
            cur.execute(f"""SELECT COALESCE(g.codigo_obra,'sem de-para'), t.lado, r.plano_cod, sum(t.valor_original * r.percentual / 100.0)
                            FROM pnl_titulo t JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
                            LEFT JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id
                            WHERE t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month') {filtro}
                              AND COALESCE(g.grupo,'') <> 'ADM'
                            GROUP BY 1, t.lado, r.plano_cod""", (ini, ini))
        except Exception:
            return {}
        linhas = cur.fetchall()
    por_obra = {}
    for cod_obra, lado, plano, v in linhas:
        c = por_obra.setdefault(cod_obra, {})
        c[plano] = round(c.get(plano, 0.0) + _sinal_resultado(lado, plano) * float(v or 0), 2)
    saida = {}
    for cod_obra, contas in por_obra.items():
        dre = dre_do_mes([{"plano_cod": k, "plano_nome": "", "valor": x} for k, x in contas.items()])
        saida[cod_obra] = dre["valores"]
    return saida


# ---------------------------------------------------------------- Confirmacao do DRE do mes (fonte escolhida por linha)
def confirmacao_instalada(conn) -> bool:
    """True se o SQL da confirmacao do DRE (sql/v2_dre_confirmacao.sql) ja foi executado."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_dre_confirmacao'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def confirmacao_ativa(conn, mes: str) -> dict | None:
    """Confirmacao ativa do DRE do mes ('AAAA-MM'): {'id','fontes','valores','quem','quando','observacao','resumo'} ou None."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, fontes, valores, confirmado_por, confirmado_em, observacao, resumo FROM pnl_dre_confirmacao
                           WHERE mes=%s::date AND ativo ORDER BY id DESC LIMIT 1""", (f"{mes}-01",))
            r = cur.fetchone()
    except Exception:
        return None
    return {"id": r[0], "fontes": r[1], "valores": r[2], "quem": r[3], "quando": r[4], "observacao": r[5], "resumo": r[6]} if r else None


def meses_confirmados(conn) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(mes,'YYYY-MM') FROM pnl_dre_confirmacao WHERE ativo ORDER BY 1")
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def gravar_confirmacao(conn, mes: str, fontes: dict, valores: dict, usuario: str | None, observacao: str | None = None,
                       resumo: dict | None = None, dre_importacao_id: int | None = None) -> dict:
    """Grava o DRE confirmado do mes: para cada linha 'folha' guarda a FONTE escolhida (API/PDF) e o valor adotado. A confirmacao anterior do mes
    fica ativo=false (historico). Devolve {'id', 'mes', 'substituiu': id_anterior|None}."""
    if set(fontes) != set(valores):
        raise ValueError("Fontes e valores precisam cobrir as mesmas linhas.")
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE pnl_dre_confirmacao SET ativo=false WHERE mes=%s::date AND ativo RETURNING id", (f"{mes}-01",))
            ant = cur.fetchone()
            cur.execute("""INSERT INTO pnl_dre_confirmacao (mes, confirmado_por, observacao, fontes, valores, resumo, dre_importacao_id)
                           VALUES (%s::date, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        (f"{mes}-01", usuario, (observacao or None), json.dumps(fontes), json.dumps({k: round(float(v), 2) for k, v in valores.items()}),
                         json.dumps(resumo or {}), dre_importacao_id))
            novo = cur.fetchone()[0]
    registrar_log(conn, "DRE_CONFIRMADO", "INFO", usuario, mes, {"confirmacao_id": novo, "substituiu": ant[0] if ant else None, "fontes": fontes,
                                                                  "resumo": resumo or {}, "observacao": (observacao or "")[:200]})
    return {"id": novo, "mes": mes, "substituiu": ant[0] if ant else None}


# ---------------------------------------------------------------- Administracao (aba do painel): despesas das unidades ADM, credores e de-para "Outros credores/Dir"
def norm_credor(s) -> str:
    """Nome do credor para comparar: MAIUSCULAS, sem acento e com espacos simples ('Credor  Exemplo Gama' == 'CREDOR EXEMPLO GAMA')."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


def credor_grupo_instalado(conn) -> bool:
    """True se o SQL-11 (sql/v2_credor_grupo.sql) ja foi executado."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_credor_grupo'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def credor_grupo_ativos(conn) -> list:
    """Credores que estao no grupo 'Outros credores/Dir' (ativos): [{'id','chave','nome','quem','quando'}]."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, chave, COALESCE(nome_exibicao, chave), alterado_por, alterado_em FROM pnl_credor_grupo WHERE ativo AND grupo='OUTROS_DIR' ORDER BY chave")
            return [{"id": i, "chave": c, "nome": n, "quem": q, "quando": e} for i, c, n, q, e in cur.fetchall()]
    except Exception:
        return []


def credor_grupo_adicionar(conn, nome: str, usuario: str | None) -> dict:
    """Poe um credor em 'Outros credores/Dir'. O credor casa se o nome dele COMECA com o texto informado (sem acento, sem diferenca de maiuscula).
    Devolve {'ok': True, 'id'} ou {'ok': False, 'erro'}. O log guarda so' o id (nada de nome de pessoa)."""
    chave = norm_credor(nome)
    if len(chave) < 3:
        return {"ok": False, "erro": "Escreva pelo menos 3 letras do nome do credor."}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM pnl_credor_grupo WHERE ativo AND grupo='OUTROS_DIR' AND chave=%s", (chave,))
            if cur.fetchone():
                return {"ok": False, "erro": "Esse credor já está no grupo."}
            cur.execute("INSERT INTO pnl_credor_grupo (chave, nome_exibicao, grupo, alterado_por) VALUES (%s,%s,'OUTROS_DIR',%s) RETURNING id", (chave, str(nome).strip(), usuario))
            novo = cur.fetchone()[0]
    except Exception as exc:
        return {"ok": False, "erro": f"Não consegui gravar: {exc}"}
    registrar_log(conn, "CREDOR_GRUPO_ADICIONADO", "INFO", usuario, None, {"id": novo, "grupo": "OUTROS_DIR", "tamanho_do_nome": len(chave)})
    return {"ok": True, "id": novo}


def credor_grupo_remover(conn, id_: int, usuario: str | None) -> bool:
    """Tira o credor do grupo (ativo = false; a linha fica no historico). Devolve True se mudou algo."""
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_credor_grupo SET ativo=false, alterado_por=%s, alterado_em=now() WHERE id=%s AND ativo", (usuario, int(id_)))
        n = cur.rowcount
    if n:
        registrar_log(conn, "CREDOR_GRUPO_REMOVIDO", "INFO", usuario, None, {"id": int(id_), "grupo": "OUTROS_DIR"})
    return bool(n)


def _periodo(mes_ini: str, mes_fim: str) -> tuple:
    return f"{mes_ini}-01", f"{mes_fim}-01"


def adm_linhas(conn, mes_ini: str, mes_fim: str, prefixos: list, sem_previsao: bool = False) -> list:
    """Despesas PAGAS das unidades ADM (centros de custo com grupo 'ADM' no de-para) entre os meses 'AAAA-MM' (inclusive), por conta, credor e unidade:
    soma(liquido da baixa x % do rateio). Mesmas regras da aba Despesas (contas excluidas, previsao). Sem de-para no banco devolve [].
    Devolve [{'plano_cod','plano_nome','credor','unidade','valor'}]."""
    ini, fim = _periodo(mes_ini, mes_fim)
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT r.plano_cod, max(r.plano_nome), COALESCE(NULLIF(trim(t.contraparte_nome),''),'(sem credor)'),
                                   COALESCE(NULLIF(trim(g.empresa_nome),''),'(sem unidade)'), sum(b.liquido * r.percentual / 100.0)
                            FROM pnl_v_baixa b
                            JOIN pnl_v_rateio r ON r.lado=b.lado AND r.bill_id=b.bill_id AND r.installment_id=b.installment_id
                            JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
                            JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id AND g.grupo = 'ADM'
                            WHERE b.lado='P' AND b.data_pagamento >= %s::date AND b.data_pagamento < (%s::date + interval '1 month') {filtro}
                            GROUP BY r.plano_cod, 3, 4""", (ini, fim))
            linhas = cur.fetchall()
    except Exception:
        return []
    return [{"plano_cod": c, "plano_nome": n, "credor": cr, "unidade": u, "valor": round(float(v or 0), 2)}
            for c, n, cr, u, v in linhas if not _excluido(c, prefixos)]


def adm_evolucao(conn, mes_ini: str, mes_fim: str, prefixos: list, sem_previsao: bool = False) -> list:
    """Total pago nas unidades ADM mes a mes (mesmas regras de adm_linhas): [{'mes','valor'}], so' meses com movimento."""
    ini, fim = _periodo(mes_ini, mes_fim)
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT to_char(b.data_pagamento,'YYYY-MM'), r.plano_cod, sum(b.liquido * r.percentual / 100.0)
                            FROM pnl_v_baixa b
                            JOIN pnl_v_rateio r ON r.lado=b.lado AND r.bill_id=b.bill_id AND r.installment_id=b.installment_id
                            JOIN pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id
                            JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id AND g.grupo = 'ADM'
                            WHERE b.lado='P' AND b.data_pagamento >= %s::date AND b.data_pagamento < (%s::date + interval '1 month') {filtro}
                            GROUP BY 1, 2""", (ini, fim))
            linhas = cur.fetchall()
    except Exception:
        return []
    por = {}
    for m, c, v in linhas:
        if not _excluido(c, prefixos):
            por[m] = round(por.get(m, 0.0) + float(v or 0), 2)
    return [{"mes": m, "valor": por[m]} for m in sorted(por)]


def nomes_plano(conn) -> dict:
    """{codigo: nome} do plano financeiro cadastrado (para nomear os grupos de despesa); {} se nao houver."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT codigo, nome FROM pnl_plano_conta")
            return {c: n for c, n in cur.fetchall()}
    except Exception:
        return {}


def adm_resumo(linhas: list, chaves_outros: list | None = None, nomes: dict | None = None, top_contas: int = 12) -> dict:
    """Resume as linhas de adm_linhas (sem banco): total; por grupo de despesa (2 primeiros niveis do plano, ex. '2.03'); por unidade; top contas
    (as demais somadas numa linha); ranking de credores SEM os do grupo 'Outros credores/Dir' (que somam a parte, com a lista de quem sao)."""
    chaves = [norm_credor(c) for c in (chaves_outros or []) if norm_credor(c)]
    nomes = nomes or {}
    total = round(sum(l["valor"] for l in linhas), 2)
    pct = lambda v: round(v / total, 4) if abs(total) > 0.004 else None

    def agrupar(chave_fn, nome_fn=None):
        por = {}
        for l in linhas:
            k = chave_fn(l)
            a = por.setdefault(k, {"chave": k, "nome": nome_fn(l) if nome_fn else k, "valor": 0.0})
            a["valor"] = round(a["valor"] + l["valor"], 2)
        out = sorted(por.values(), key=lambda a: -a["valor"])
        for a in out:
            a["pct"] = pct(a["valor"])
        return out

    grupo_cod = lambda l: ".".join(l["plano_cod"].split(".")[:2])
    por_grupo = agrupar(grupo_cod, lambda l: nomes.get(grupo_cod(l)) or grupo_cod(l))
    por_unidade = agrupar(lambda l: l["unidade"])
    contas = agrupar(lambda l: l["plano_cod"], lambda l: l["plano_nome"] or l["plano_cod"])
    top, resto = contas[:top_contas], contas[top_contas:]
    if resto:
        v = round(sum(a["valor"] for a in resto), 2)
        top.append({"chave": "", "nome": f"Demais contas ({len(resto)})", "valor": v, "pct": pct(v)})
    cred = {}
    for l in linhas:
        k = l["credor"].strip()
        cred[k] = round(cred.get(k, 0.0) + l["valor"], 2)
    ranking, outros = [], []
    for nome, v in cred.items():
        (outros if any(norm_credor(nome).startswith(c) for c in chaves) else ranking).append({"credor": nome, "valor": v})
    ranking.sort(key=lambda a: -a["valor"])
    outros.sort(key=lambda a: -a["valor"])
    for a in ranking + outros:
        a["pct"] = pct(a["valor"])
    v_outros = round(sum(a["valor"] for a in outros), 2)
    casadas = {c for c in chaves if any(norm_credor(n["credor"]).startswith(c) for n in outros)}
    return {"total": total, "por_grupo": por_grupo, "por_unidade": por_unidade, "top_contas": top, "ranking": ranking,
            "outros": {"valor": v_outros, "pct": pct(v_outros), "credores": outros}, "n_credores": len(ranking) + len(outros),
            "chaves_sem_credor": sorted(set(chaves) - casadas)}


# ---------------------------------------------------------------- Receita mes a mes (aba Pessoas: linha "Receita: var. % s/ mes anterior")
def receita_mensal(conn, mes_atual: str | None = None, sem_distrato: bool = True) -> list:
    """Receita bruta por mes, da fonte mais confiavel que existir: 1) DRE CONFIRMADO do mes (linha 01.01); 2) DRE oficial importado (PDF, linha 01);
    3) reconstrucao pela API (titulos emitidos no mes, sem previsao e sem NF desfeita). O mes em andamento ('mes_atual') fica de fora (incompleto).
    Meses so' com API (sem DRE importado/confirmado) ANTES da primeira sincronizacao de emissao ficam de fora: la a base tem so' residuos de titulos
    antigos (receita parcial, variacao % absurda). Devolve [{'mes','receita','fonte','var'}] em ordem; 'var' = variacao sobre o mes anterior (fracao)
    so' quando os dois meses vieram da lista e o anterior e' > 0."""
    meses = set(meses_com_emissao(conn)) | set(meses_com_dre(conn)) | set(meses_confirmados(conn))
    if mes_atual:
        meses.discard(mes_atual)
    with conn.cursor() as cur:
        cur.execute("SELECT to_char(min(mes), 'YYYY-MM') FROM pnl_sync WHERE lado='R' AND tipo_data='I' AND status <> 'ERRO'")
        cobertura_ini = cur.fetchone()[0]
    out = []
    for m in sorted(meses):
        rec, fonte = None, None
        conf = confirmacao_ativa(conn, m)
        if conf and "01.01" in (conf["valores"] or {}):
            rec, fonte = float(conf["valores"]["01.01"]), "DRE confirmado"
        if rec is None:
            imp = dre_importacao_ativa(conn, m)
            if imp:
                rec = round(sum(o["linhas"].get("01", 0.0) for o in dre_por_obra_importado(conn, imp["id"]).values()), 2)
                fonte = "DRE oficial (PDF)"
        if rec is None:
            if cobertura_ini and m < cobertura_ini:
                continue
            rec = float(dre_do_mes(resultado_por_conta(conn, m, sem_previsao=True, sem_distrato=sem_distrato))["valores"]["01"])
            fonte = "API (a conferir)"
        if abs(rec) > 0.004:
            out.append({"mes": m, "receita": round(rec, 2), "fonte": fonte, "var": None})
    for ant, atu in zip(out, out[1:]):
        ya, ma = (int(x) for x in ant["mes"].split("-"))
        yb, mb = (int(x) for x in atu["mes"].split("-"))
        if (yb * 12 + mb) - (ya * 12 + ma) == 1 and ant["receita"] > 0:
            atu["var"] = round(atu["receita"] / ant["receita"] - 1, 4)
    return out


# ---------------------------------------------------------------- Folha de pagamento (recibos em PDF; SQL-16)
EMPRESAS_FOLHA = {"468": "CONSTRUTORA", "469": "ENERGIA"}          # codigo da empresa no recibo -> escopo da importacao


def folha_instalada(conn) -> bool:
    """True se o SQL da folha (sql/v2_folha.sql) ja foi executado."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name IN ('pnl_folha_recibo','pnl_folha_depto_obra')")
            return cur.fetchone()[0] == 2
    except Exception:
        return False


def gravar_folha(conn, folha: dict, arquivo: str, sha256: str, usuario: str | None) -> dict:
    """Grava os recibos lidos do PDF como importacao ativa do mes+empresa (a anterior do mesmo mes/escopo fica ativo=false). Mesmo arquivo (sha256)
    ja importado: nao grava de novo ({'repetido': True}). Tudo numa transacao so. O log guarda so' contagens (nada de nome nem salario)."""
    from importador_folha import resumo_por_recibo
    if not folha.get("competencia"):
        raise ValueError("O PDF não informa a competência (mês/ano); não sei a que mês pertence.")
    mes = folha["competencia"] + "-01"
    escopo = "+".join(EMPRESAS_FOLHA.get(e, f"EMP{e}") for e in folha["empresas"])
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, mes FROM pnl_importacao WHERE tipo='FOLHA' AND arquivo_sha256=%s", (sha256,))
            ja = cur.fetchone()
            if ja:
                return {"repetido": True, "id": ja[0], "ativo": ja[1], "mes": ja[2].strftime("%Y-%m"), "escopo": escopo}
            cur.execute("UPDATE pnl_importacao SET ativo=false WHERE tipo='FOLHA' AND mes=%s AND escopo=%s AND ativo", (mes, escopo))
            cur.execute("""INSERT INTO pnl_importacao (tipo, mes, escopo, arquivo_nome, arquivo_sha256, importado_por, n_linhas, detalhe)
                           VALUES ('FOLHA', %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        (mes, escopo, arquivo, sha256, usuario, len(folha["recibos"]),
                         json.dumps({"recibos": len(folha["recibos"]), "paginas": folha["paginas"], "avisos": folha["avisos"]}, ensure_ascii=False)))
            iid = cur.fetchone()[0]
            linhas_r, linhas_e = [], []
            for r in folha["recibos"]:
                s = resumo_por_recibo(r)
                linhas_r.append((iid, r["empresa"], r["cadastro"], r["nome"], r["cargo"], r["local"], r["departamento"], r["subnivel_texto"], r["admissao"],
                                 s["salario"], s["hora_extra"], s["dsr_he"], r["total_proventos"], r["total_descontos"], r["liquido"], r["fgts_mes"]))
                for e in r["eventos"]:
                    linhas_e.append((iid, r["empresa"], r["cadastro"], r["nome"], r["cbo"], r["cargo"], r["local"], r["departamento"], r["admissao"],
                                     e["ev"], e["descricao"], e["referencia"], e["provento"], e["desconto"], e["informativo"]))
            execute_values(cur, """INSERT INTO pnl_folha_recibo (importacao_id, empresa, cadastro, nome, cargo, local_obra, departamento, subnivel_texto, admissao,
                                   salario, hora_extra, dsr_he, total_proventos, total_descontos, liquido, fgts_mes) VALUES %s""", linhas_r)
            execute_values(cur, """INSERT INTO pnl_folha_evento (importacao_id, empresa, cadastro, nome, cbo, cargo, local_obra, departamento, admissao,
                                   ev, descricao, referencia, provento, desconto, informativo) VALUES %s""", linhas_e)
    registrar_log(conn, "FOLHA_PDF_IMPORTADA", "AVISO" if folha["avisos"] else "INFO", usuario, mes[:7],
                  {"arquivo": arquivo, "sha256": sha256[:16], "importacao_id": iid, "escopo": escopo, "recibos": len(folha["recibos"]),
                   "eventos": len(linhas_e), "avisos": len(folha["avisos"])})
    return {"repetido": False, "id": iid, "mes": mes[:7], "escopo": escopo, "recibos": len(folha["recibos"])}


def folha_meses(conn) -> list:
    """Meses ('AAAA-MM') com folha importada e ativa."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT to_char(mes,'YYYY-MM') FROM pnl_importacao WHERE tipo='FOLHA' AND ativo ORDER BY 1")
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def folha_do_mes(conn, mes: str) -> dict | None:
    """Folha CLT do mes (todas as empresas importadas): total de colaboradores, salarios (evento 1), HE + DSR s/HE, % HE/salarios, custo (proventos + FGTS),
    por empresa, por obra (de-para departamento -> obra) e os departamentos sem de-para. None se o mes nao tem folha."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, escopo, arquivo_nome, importado_por, importado_em FROM pnl_importacao
                           WHERE tipo='FOLHA' AND mes=%s::date AND ativo ORDER BY escopo""", (f"{mes}-01",))
            imps = cur.fetchall()
            if not imps:
                return None
            cur.execute("""SELECT r.empresa, r.departamento, max(r.subnivel_texto), d.codigo_obra, max(d.obra_nome), count(*),
                                  sum(COALESCE(r.salario,0)), sum(COALESCE(r.hora_extra,0)), sum(COALESCE(r.dsr_he,0)),
                                  sum(COALESCE(r.total_proventos,0)), sum(COALESCE(r.fgts_mes,0))
                           FROM pnl_folha_recibo r JOIN pnl_importacao i ON i.id = r.importacao_id
                           LEFT JOIN pnl_folha_depto_obra d ON d.empresa = r.empresa AND d.departamento = r.departamento
                           WHERE i.tipo='FOLHA' AND i.mes=%s::date AND i.ativo
                           GROUP BY r.empresa, r.departamento, d.codigo_obra""", (f"{mes}-01",))
            linhas = cur.fetchall()
    except Exception:
        return None
    tot = {"colab": 0, "salarios": 0.0, "hora_extra": 0.0, "dsr_he": 0.0, "proventos": 0.0, "fgts": 0.0}
    por_emp, por_obra, sem = {}, {}, []
    for emp, dep, sub, cod, onome, n, sal, he, dsr, prov, fgts in linhas:
        vals = {"colab": int(n), "salarios": float(sal), "hora_extra": float(he), "dsr_he": float(dsr), "proventos": float(prov), "fgts": float(fgts)}
        for k, v in vals.items():
            tot[k] += v
        e = por_emp.setdefault(emp, {"empresa": EMPRESAS_FOLHA.get(emp, emp), "colab": 0, "salarios": 0.0, "hora_extra": 0.0, "dsr_he": 0.0, "proventos": 0.0, "fgts": 0.0})
        for k, v in vals.items():
            e[k] += v
        if cod is None:
            sem.append({"empresa": EMPRESAS_FOLHA.get(emp, emp), "departamento": dep, "subnivel": sub, "colab": int(n)})
            cod = "sem de-para"
        o = por_obra.setdefault(cod, {"codigo": cod, "nome": onome or (sub if cod == "sem de-para" else ""), "colab": 0, "salarios": 0.0, "hora_extra": 0.0, "dsr_he": 0.0, "proventos": 0.0, "fgts": 0.0})
        for k, v in vals.items():
            o[k] += v
    pct = lambda d: round((d["hora_extra"] + d["dsr_he"]) / d["salarios"], 4) if d["salarios"] > 0.005 else None
    for d in [tot, *por_emp.values(), *por_obra.values()]:
        d["custo"] = round(d["proventos"] + d["fgts"], 2)
        d["he_pct"] = pct(d)
        for k in ("salarios", "hora_extra", "dsr_he", "proventos", "fgts"):
            d[k] = round(d[k], 2)
    return {"mes": mes, "importacoes": [{"id": i[0], "escopo": i[1], "arquivo": i[2], "quem": i[3], "quando": i[4]} for i in imps], "total": tot,
            "por_empresa": sorted(por_emp.values(), key=lambda d: d["empresa"]), "por_obra": por_obra, "sem_depara": sem}


def folha_serie(conn) -> list:
    """[{'mes','colab','salarios','he_pct'}] dos meses com folha importada (para o grafico HE / salarios)."""
    out = []
    for m in folha_meses(conn):
        f = folha_do_mes(conn, m)
        if f:
            out.append({"mes": m, "colab": f["total"]["colab"], "salarios": f["total"]["salarios"], "he_pct": f["total"]["he_pct"]})
    return out


def colab_por_linha_obras(linhas: list, folha: dict | None) -> dict:
    """Para cada linha da tabela de Obras ({'obra': cod, ...}) devolve {cod: colaboradores CLT}. 'DEM' soma as obras da folha que nao aparecem em linha propria
    (e que nao sao a administracao central, codigo 99). Sem folha, {}."""
    if not folha:
        return {}
    proprias = {l["obra"] for l in linhas if l["obra"] != "DEM"}
    res = {}
    for l in linhas:
        if l["obra"] == "DEM":
            res["DEM"] = sum(o["colab"] for c, o in folha["por_obra"].items() if c not in proprias and c != "99")
        else:
            res[l["obra"]] = folha["por_obra"].get(l["obra"], {}).get("colab", 0)
    return res
