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

from psycopg2.extras import Json, execute_values

import time

import db

# Base da HE (contabilidade 20/10/2026): "pode descontar tudo, considere somente os salarios liquidos" -> todos os descontos do recibo saem da base

TABELAS_V2 = ("pnl_sync", "pnl_titulo", "pnl_baixa", "pnl_rateio", "pnl_regra", "pnl_obra", "pnl_centro_custo")



# ---------------------------------------------------------------- memoria curta (a abertura do Painel da Diretoria repetia as mesmas consultas pequenas, uma por mes)
_MEMO: dict = {}


def _memo(chave, ttl: float, fn):
    """Guarda por `ttl` segundos o resultado de `fn()` (chave inclui a conexao). Quem GRAVA dados que essas consultas leem chama `limpar_memo()`."""
    agora = time.monotonic()
    h = _MEMO.get(chave)
    if h is not None and agora - h[0] < ttl:
        return h[1]
    v = fn()
    _MEMO[chave] = (agora, v)
    return v


def limpar_memo() -> None:
    _MEMO.clear()


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
    limpar_memo()


def _tem_coluna(cur, tabela: str, coluna: str) -> bool:
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s", (tabela, coluna))
    return cur.fetchone() is not None


def gravar_normalizado(conn, sync_id: int, norm: dict) -> dict:
    """Grava titulos, baixas e rateios (upsert) numa unica transacao. Devolve contagens e o liquido total das baixas."""
    tit, bx, rt = norm["titulos"], norm["baixas"], norm["rateios"]
    limpar_memo()
    with db.transacao(conn):
        with conn.cursor() as cur:
            if tit:
                com_imposto = _tem_coluna(cur, "pnl_titulo", "imposto_titulo")          # SQL-13; sem ela grava como antes (nada quebra)
                col_extra, upd_extra = (",imposto_titulo", ", imposto_titulo=EXCLUDED.imposto_titulo") if com_imposto else ("", "")
                # SQL-27: "vencimento original" = o PRIMEIRO vencimento que o app viu para o titulo (o Sienge nao expõe o original por API);
                # na primeira gravacao copia o vencimento; nas seguintes NAO sobrescreve (prorrogacao nao esconde a divida).
                com_base = _tem_coluna(cur, "pnl_titulo", "data_vencimento_original")
                if com_base:
                    col_extra = col_extra + ",data_vencimento_original"
                    upd_extra = upd_extra + ", data_vencimento_original=COALESCE(pnl_titulo.data_vencimento_original, EXCLUDED.data_vencimento_original)"
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
                                 t["area_nome"], t["projeto_id"], t["projeto_nome"]) + ((t.get("imposto_titulo"),) if com_imposto else ())
                                + ((t["data_vencimento"],) if com_base else ()) for t in tit],
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
    limpar_memo()
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


def obras_sienge_instalado(conn) -> bool:
    """True se a tabela das obras do Sienge (sql/v2_obra_sienge.sql, SQL-24) existe."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_obra_sienge'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def gravar_obras_sienge(conn, obras: list) -> dict:
    """Upsert das obras do Sienge (ja normalizadas por sienge_api.normalizar_obras). Nao mexe em nenhum outro cadastro. Sem a tabela devolve {'erro': ...}."""
    if not obras_sienge_instalado(conn):
        return {"erro": "A tabela das obras do Sienge ainda não existe no banco (falta executar o SQL-24, arquivo sql/v2_obra_sienge.sql)."}
    if not obras:
        return {"obras": 0}
    with db.transacao(conn):
        with conn.cursor() as cur:
            execute_values(cur, """INSERT INTO pnl_obra_sienge (id, nome, nome_comercial, empresa_id, codigo, bruto) VALUES %s
                                   ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, nome_comercial=EXCLUDED.nome_comercial, empresa_id=EXCLUDED.empresa_id,
                                   codigo=EXCLUDED.codigo, bruto=EXCLUDED.bruto, atualizado_em=now()""",
                           [(o["id"], o["nome"], o["nome_comercial"], o["empresa_id"], o["codigo"], Json(o["bruto"])) for o in obras])
    return {"obras": len(obras)}


def credores_sienge_instalado(conn) -> bool:
    """True se a tabela dos credores do Sienge (sql/v2_credor_sienge.sql, SQL-30) existe."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_credor_sienge'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def gravar_credores_sienge(conn, credores: list) -> dict:
    """Upsert dos credores do Sienge (ja normalizados por sienge_api.normalizar_credores). Sem a tabela devolve {'erro': ...}."""
    if not credores_sienge_instalado(conn):
        return {"erro": "A tabela dos credores do Sienge ainda não existe no banco (falta executar o SQL-30, arquivo sql/v2_credor_sienge.sql)."}
    if not credores:
        return {"credores": 0, "com_fantasia": 0}
    with db.transacao(conn):
        with conn.cursor() as cur:
            execute_values(cur, """INSERT INTO pnl_credor_sienge (id, nome, nome_fantasia) VALUES %s
                                   ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, nome_fantasia=EXCLUDED.nome_fantasia, atualizado_em=now()""",
                           [(c["id"], c["nome"], c["nome_fantasia"]) for c in credores])
    return {"credores": len(credores), "com_fantasia": sum(1 for c in credores if c["nome_fantasia"])}


def fantasia_por_credor(conn) -> dict:
    """{nome do credor normalizado (norm_credor): nome fantasia} so' dos credores que TEM fantasia no cadastro. Sem a tabela (ou sem dados) devolve {}."""
    if not credores_sienge_instalado(conn):
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, nome_fantasia FROM pnl_credor_sienge WHERE nome_fantasia IS NOT NULL AND btrim(nome_fantasia) <> ''")
            return {norm_credor(n): f.strip() for n, f in cur.fetchall()}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return {}


def _carimbo_credores(conn) -> str:
    """Parte do carimbo do painel: muda quando o cadastro de credores e' atualizado (sem a tabela = vazio)."""
    if not credores_sienge_instalado(conn):
        return ""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*)||'/'||coalesce(max(atualizado_em)::text,'') FROM pnl_credor_sienge")
            return cur.fetchone()[0]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return ""


def obras_sienge_conferencia(conn) -> list:
    """Para cada codigo de obra do painel (de-para de centros de custo), o nome que o Sienge tem para o mesmo numero (id ou codigo da obra) ao lado do nome ja usado.
    Serve para a contabilidade/Rafael validarem se o numero do painel e' o mesmo do Sienge ANTES de confiar nos nomes. [{'codigo','nome_sienge','nome_comercial','nome_atual'}]."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT g.codigo_obra, o.nome, o.nome_comercial,
                                  (SELECT max(g2.obra_nome) FROM pnl_centro_grupo g2 WHERE g2.codigo_obra = g.codigo_obra AND g2.obra_nome IS NOT NULL)
                           FROM (SELECT DISTINCT codigo_obra FROM pnl_centro_grupo WHERE COALESCE(codigo_obra,'') NOT IN ('', 'DEM', 'ADM')) g
                           LEFT JOIN pnl_obra_sienge o ON o.id::text = g.codigo_obra OR o.codigo = g.codigo_obra
                           ORDER BY g.codigo_obra""")
            return [{"codigo": c, "nome_sienge": n, "nome_comercial": nc, "nome_atual": a} for c, n, nc, a in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:                                       # noqa: BLE001
            pass
        return []


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
        # So' meses a partir da janela da rotina diaria (data de emissao): a rotina semanal de titulos em aberto traz titulos mais antigos
        # (inadimplencia / financiamentos) que NAO formam um mes completo de emissao.
        cur.execute("""SELECT DISTINCT to_char(data_emissao,'YYYY-MM') FROM pnl_titulo
                       WHERE data_emissao IS NOT NULL
                         AND data_emissao >= COALESCE((SELECT min(mes) FROM pnl_sync WHERE status='OK' AND tipo_data='I'), DATE '0001-01-01')
                       ORDER BY 1""")
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


def _filtro_desfeitos(sem_desfeitos: bool) -> str:
    """REGRA CONFIRMADA pela contabilidade em 19/10/2026 (ligada por padrao): o DRE gerencial do Sienge NAO conta (a) titulos a PAGAR cujas baixas dos tipos Cancelamento (3),
    Substituicao (5) ou Abatimento de adiantamento (8) somam o valor todo, nem (b) documentos do tipo AEJ (multas). Aplicar isso reduz a diferenca de
    custo API x PDF em ~R$ 200 mil (de R$ 272 mil para R$ 69 mil, fora INSS/FGTS em guia, que a contabilidade disse que entra depois do PDF)."""
    if not sem_desfeitos:
        return ""
    return """AND NOT (t.lado='P' AND (upper(trim(COALESCE(t.doc_id,''))) = 'AEJ'
                   OR (SELECT COALESCE(sum(dx.bruto),0) FROM pnl_baixa dx WHERE dx.lado=t.lado AND dx.bill_id=t.bill_id AND dx.installment_id=t.installment_id
                       AND dx.tipo_oper_id IN (3,5,8)) >= GREATEST(COALESCE(t.valor_original,0) - 0.01, 0.01)))"""


def centro_grupo_instalado(conn) -> bool:
    """True se a tabela do de-para (sql/v2_centro_grupo.sql) existe E ja tem linhas (os dados vem do vault). So' o 'sim' fica guardado (5 min)."""
    h = _MEMO.get(("cg_inst", id(conn)))
    if h is not None and time.monotonic() - h[0] < 300:
        return True
    ok = _centro_grupo_instalado_sql(conn)
    if ok:
        _MEMO[("cg_inst", id(conn))] = (time.monotonic(), True)
    return ok


def _centro_grupo_instalado_sql(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pnl_centro_grupo")
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def resultado_por_conta(conn, mes: str, sem_previsao: bool = False, so_obras: bool = False, sem_distrato: bool = True, sem_desfeitos: bool = True) -> list:
    """Valor COMPROMETIDO do mes por conta do plano: soma(valor do titulo x % do rateio) dos titulos EMITIDOS no mes, com sinal de DRE
    (receita +, custo -). `so_obras` tira os centros de custo do grupo ADM (de-para pnl_centro_grupo); centro sem de-para fica dentro.
    Devolve [{'plano_cod','plano_nome','valor'}]. Mesmo criterio do DRE gerencial 'Comprometido, selecao por data de emissao'."""
    ini = f"{mes}-01"
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro_prev = filtro                                    # descontos das baixas: so previsao (nao distrato; conferido sem esse filtro)
    filtro += " " + _filtro_distrato(sem_distrato) + " " + _filtro_desfeitos(sem_desfeitos)
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


def resultado_por_centro(conn, mes: str, sem_previsao: bool = False, sem_distrato: bool = True, sem_desfeitos: bool = True) -> list:
    """Diagnostico: receita e custo (so contas do DRE de obras: 1.01.01 e 2.01.*) por centro de custo, com o grupo do de-para (ou 'sem de-para')."""
    ini = f"{mes}-01"
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro += " " + _filtro_distrato(sem_distrato) + " " + _filtro_desfeitos(sem_desfeitos)
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
    limpar_memo()
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


def _dre_importacoes_ativas(conn) -> dict:
    """{'AAAA-MM': importacao ativa do DRE} de todos os meses numa consulta so' (tabela pequena); guardado 15 s."""
    def ler():
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT to_char(mes,'YYYY-MM'), id, arquivo_nome, importado_por, importado_em, n_linhas, status FROM pnl_importacao
                               WHERE tipo='DRE' AND escopo='' AND ativo ORDER BY id""")
                return {m: {"id": i, "arquivo": a, "quem": q, "quando": w, "linhas": n, "status": st} for m, i, a, q, w, n, st in cur.fetchall()}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {}
    return _memo(("dre_imp", id(conn)), 15, ler)


def dre_importacao_ativa(conn, mes: str) -> dict | None:
    """Importacao ativa do DRE em PDF para o mes ('AAAA-MM'), ou None (tambem None se o SQL ainda nao foi rodado)."""
    return _dre_importacoes_ativas(conn).get(mes)


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


def _codigos_obra_proprios(conn):
    """Codigos de obra do de-para de centros de custo (sem DEM/ADM) ou None se nao ha de-para no banco."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT codigo_obra FROM pnl_centro_grupo WHERE COALESCE(codigo_obra,'') NOT IN ('', 'DEM', 'ADM')")
            achados = {r[0] for r in cur.fetchall()}
        return achados or None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


CUSTO_PADRAO_LINHAS = ("04", "06", "08", "09", "10", "12")        # padrao da contabilidade (22/10/2026): Custos = DRE 04+06+08+09+10+12 = "Custo Total" do relatorio Custos por obra


def custo_padrao_obra(linhas: dict) -> float:
    """Custo da obra no padrao da contabilidade (negativo, como no DRE). Pela API vem pronto em 'CP' (soma das contas do relatorio de custos por obra);
    pelo PDF do DRE soma as linhas 04+06+08+09+10+12 que existirem."""
    if "CP" in linhas:
        return round(float(linhas["CP"] or 0.0), 2)
    return round(sum(float(linhas.get(k, 0.0) or 0.0) for k in CUSTO_PADRAO_LINHAS), 2)


def _montar_obras(por_obra: dict, proprios, importacao_id, arquivo: str, fonte: str) -> dict:
    """Monta a tabela da aba Obras: por obra, receita bruta (linha 01), CUSTOS no padrao da contabilidade (DRE 04+06+08+09+10+12; `custo_04` guarda so' a linha 04),
    BDI real = receita + custos (custos ja vem negativo) e margem = BDI / receita. `por_obra` = {cod: {'nome': ..., 'linhas': {linha_dre: valor}}}.
    Obra sem codigo proprio no de-para vira a linha 'DEM'."""
    linhas, dem = [], {"receita": 0.0, "custo": 0.0, "custo_04": 0.0, "n": 0}
    for cod, o in por_obra.items():
        rec, cus, c04 = o["linhas"].get("01", 0.0), custo_padrao_obra(o["linhas"]), o["linhas"].get("04", 0.0)
        if abs(rec) < 0.005 and abs(cus) < 0.005:
            continue
        if proprios is not None and cod not in proprios:
            dem["receita"] += rec; dem["custo"] += cus; dem["custo_04"] += c04; dem["n"] += 1
            continue
        linhas.append({"obra": cod, "nome": o["nome"] or "", "receita": rec, "custo": cus, "custo_04": c04})
    if dem["n"]:
        linhas.append({"obra": "DEM", "nome": f"Demais obras ({dem['n']})", "receita": round(dem["receita"], 2), "custo": round(dem["custo"], 2),
                       "custo_04": round(dem["custo_04"], 2), "n": dem["n"]})
    for l in linhas:
        l["bdi"] = round(l["receita"] + l["custo"], 2)
        l["margem"] = round(l["bdi"] / l["receita"], 4) if abs(l["receita"]) > 0.005 else None
    linhas.sort(key=lambda l: (l["obra"] == "DEM", -l["receita"]))
    rt, ct = round(sum(l["receita"] for l in linhas), 2), round(sum(l["custo"] for l in linhas), 2)
    total = {"receita": rt, "custo": ct, "custo_04": round(sum(l.get("custo_04", 0.0) for l in linhas), 2), "bdi": round(rt + ct, 2),
             "margem": round((rt + ct) / rt, 4) if abs(rt) > 0.005 else None}
    proprias = [l for l in linhas if l["obra"] != "DEM"]
    return {"importacao_id": importacao_id, "arquivo": arquivo, "fonte": fonte, "linhas": linhas, "total": total,
            "top_lucro": sorted(proprias, key=lambda l: -l["bdi"])[:5], "top_prejuizo": sorted((l for l in proprias if l["bdi"] < 0), key=lambda l: l["bdi"])[:5]}


def obras_do_dre(conn, mes: str) -> dict | None:
    """Tabela da aba Obras a partir do DRE oficial (PDF) do mes. Devolve None se o mes nao tem DRE importado.
    Sem de-para no banco, todas as obras do PDF aparecem separadas."""
    imp = dre_importacao_ativa(conn, mes)
    if not imp:
        return None
    return _montar_obras(dre_por_obra_importado(conn, imp["id"]), _codigos_obra_proprios(conn), imp["id"], imp["arquivo"], "PDF")


def nomes_obras_depara(conn) -> dict:
    """{codigo_obra: nome} do de-para de centros de custo (o nome mais frequente por codigo). Sem a tabela devolve {}."""
    out: dict = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT codigo_obra, obra_nome FROM pnl_centro_grupo WHERE codigo_obra IS NOT NULL AND obra_nome IS NOT NULL GROUP BY 1, 2 ORDER BY count(*) DESC, 2")
            for cod, nome in cur.fetchall():
                out.setdefault(cod, str(nome).strip())
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    return out


def obras_da_api(conn, mes: str) -> dict | None:
    """Mesma tabela da aba Obras, mas calculada pela API do Sienge (titulos emitidos no mes, regras padrao: sem previsao, sem NF desfeita, sem titulo
    desfeito, sem centros ADM). Obras sem codigo proprio no de-para ('sem de-para' inclusive) entram em 'Demais obras'. None se nao ha dado no mes."""
    api = resultado_por_obra_api(conn, mes, sem_previsao=True, sem_distrato=True, sem_desfeitos=True)
    if not api:
        return None
    nomes = nomes_obras_depara(conn)
    por_obra = {cod: {"nome": nomes.get(cod, ""), "linhas": {"01": v.get("01", 0.0), "04": v.get("04", 0.0), "CP": v.get("CP", v.get("04", 0.0))}} for cod, v in api.items()}
    ob = _montar_obras(por_obra, _codigos_obra_proprios(conn), None, "API do Sienge (titulos emitidos no mes)", "API")
    return ob if ob["linhas"] else None


def fonte_obras(conn, mes: str) -> str | None:
    """De onde vem a tabela de Obras do mes: 'PDF' ou 'API'. Regra (a mesma do `dre_resolvido`): API e' o padrao; o PDF so' vale se a contabilidade confirmou os CUSTOS
    DIRETOS 04.* todos em PDF (e o PDF existe) ou se o mes e' anterior a rotina de emissao da API e ha PDF. PDF importado sem confirmacao NAO entra: fica para conferencia."""
    imp = dre_importacao_ativa(conn, mes)
    conf = confirmacao_ativa(conn, mes) if confirmacao_instalada(conn) else None
    if conf:
        fontes = conf["fontes"] or {}
        custos = [f for k, f in fontes.items() if k.startswith("04.")]
        return "PDF" if imp and custos and all(f == "PDF" for f in custos) else "API"
    ini = cobertura_emissao_ini(conn)
    return "PDF" if imp and ini and mes < ini else "API"


def obras_do_mes(conn, mes: str) -> dict | None:
    """Tabela de Obras do mes pela fonte de `fonte_obras` (PDF oficial ou API do Sienge). None se nao ha dado."""
    return obras_do_dre(conn, mes) if fonte_obras(conn, mes) == "PDF" else obras_da_api(conn, mes)


def meses_com_obras(conn) -> list:
    """Meses ('AAAA-MM') que podem ter tabela de Obras: com PDF importado ou com titulos emitidos (API)."""
    return sorted(set(meses_com_dre(conn)) | set(meses_com_emissao(conn)))


SEMPRE_EM_DEMAIS = ("1026", "1050", "2014", "3009", "5013", "6003")       # contabilidade 13/10: sempre em "Demais obras"


def agrupar_demais_obras(ob: dict, com_projecao, n: int = 5) -> dict:
    """Regra do painel da contabilidade para a tabela de Obras: ficam em linha propria as 5 maiores em BDI positivo, as 5 maiores em BDI negativo e as obras com
    projecao de receita no mes; todas as outras (e as da lista SEMPRE_EM_DEMAIS) viram a linha 'Demais obras' (DEM). Os totais nao mudam.
    Recebe o resultado de `obras_do_dre` e devolve uma COPIA com 'linhas' reagrupadas (e 'n' na linha DEM)."""
    proprias = [l for l in ob["linhas"] if l["obra"] != "DEM"]
    dem0 = next((l for l in ob["linhas"] if l["obra"] == "DEM"), None)
    lucro = sorted((l for l in proprias if l["bdi"] > 0.005), key=lambda l: -l["bdi"])[:n]
    perda = sorted((l for l in proprias if l["bdi"] < -0.005), key=lambda l: l["bdi"])[:n]
    manter = ({l["obra"] for l in lucro + perda} | {str(c) for c in (com_projecao or [])}) - set(SEMPRE_EM_DEMAIS)
    ficam = [dict(l) for l in proprias if l["obra"] in manter]
    resto = [l for l in proprias if l["obra"] not in manter]
    if resto or dem0:
        rec = round(sum(l["receita"] for l in resto) + (dem0["receita"] if dem0 else 0.0), 2)
        cus = round(sum(l["custo"] for l in resto) + (dem0["custo"] if dem0 else 0.0), 2)
        qtd = len(resto) + (dem0.get("n", 0) if dem0 else 0)
        bdi = round(rec + cus, 2)
        ficam.append({"obra": "DEM", "nome": f"Demais obras ({qtd})", "receita": rec, "custo": cus, "n": qtd, "bdi": bdi,
                      "margem": round(bdi / rec, 4) if abs(rec) > 0.005 else None})
    ficam.sort(key=lambda l: (l["obra"] == "DEM", -l["receita"]))
    return {**ob, "linhas": ficam}


def somar_obras(obs: list) -> dict | None:
    """Soma a tabela de Obras de varios meses (cada item = resultado de `obras_do_dre`, SEM reagrupar): receita e custo por obra; as obras que ja vinham em 'DEM'
    (sem codigo proprio no de-para) seguem somadas em 'DEM'. BDI e margem refeitos sobre as somas. A regra das 5 maiores etc. (`agrupar_demais_obras`) vale depois, sobre o periodo.
    None se a lista e' vazia. Devolve o mesmo formato de `obras_do_dre` (+ 'meses' = quantos meses entraram)."""
    obs = [o for o in (obs or []) if o]
    if not obs:
        return None
    por, dem = {}, {"receita": 0.0, "custo": 0.0, "n": 0}
    for ob in obs:
        for l in ob["linhas"]:
            if l["obra"] == "DEM":
                dem["receita"] += l["receita"]
                dem["custo"] += l["custo"]
                dem["custo_04"] = dem.get("custo_04", 0.0) + l.get("custo_04", l["custo"])
                dem["n"] = max(dem["n"], l.get("n", 0))
                continue
            a = por.setdefault(l["obra"], {"obra": l["obra"], "nome": "", "receita": 0.0, "custo": 0.0, "custo_04": 0.0})
            a["receita"] += l["receita"]
            a["custo"] += l["custo"]
            a["custo_04"] += l.get("custo_04", l["custo"])
            a["nome"] = l.get("nome") or a["nome"]
    linhas = [{**a, "receita": round(a["receita"], 2), "custo": round(a["custo"], 2), "custo_04": round(a["custo_04"], 2)} for a in por.values()]
    if dem["n"] or abs(dem["receita"]) > 0.005 or abs(dem["custo"]) > 0.005:
        linhas.append({"obra": "DEM", "nome": f"Demais obras ({dem['n']})", "receita": round(dem["receita"], 2), "custo": round(dem["custo"], 2),
                       "custo_04": round(dem.get("custo_04", 0.0), 2), "n": dem["n"]})
    for l in linhas:
        l["bdi"] = round(l["receita"] + l["custo"], 2)
        l["margem"] = round(l["bdi"] / l["receita"], 4) if abs(l["receita"]) > 0.005 else None
    linhas.sort(key=lambda l: (l["obra"] == "DEM", -l["receita"]))
    rt, ct = round(sum(l["receita"] for l in linhas), 2), round(sum(l["custo"] for l in linhas), 2)
    proprias = [l for l in linhas if l["obra"] != "DEM"]
    return {"linhas": linhas, "total": {"receita": rt, "custo": ct, "custo_04": round(sum(l.get("custo_04", 0.0) for l in linhas), 2), "bdi": round(rt + ct, 2), "margem": round((rt + ct) / rt, 4) if abs(rt) > 0.005 else None},
            "top_lucro": sorted(proprias, key=lambda l: -l["bdi"])[:5], "top_prejuizo": sorted((l for l in proprias if l["bdi"] < 0), key=lambda l: l["bdi"])[:5],
            "meses": len(obs), "importacao_id": None, "arquivo": f"{len(obs)} meses somados"}


def somar_projecoes(projs: list) -> dict | None:
    """Soma a projecao x realizado (`projecao_x_realizado`) de varios meses, por obra. None se nenhum mes tem projecao. 'meses' = quantos meses entraram."""
    projs = [p for p in (projs or []) if p]
    if not projs:
        return None
    por = {}
    for p in projs:
        for x in p["linhas"]:
            a = por.setdefault(x["codigo"], {"codigo": x["codigo"], "nome": x.get("nome") or "", "receita_proj": 0.0, "receita_real": 0.0, "bdi_proj": 0.0, "bdi_real": 0.0})
            for k in ("receita_proj", "receita_real", "bdi_proj", "bdi_real"):
                a[k] += x[k]
    linhas = []
    for a in por.values():
        a = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in a.items()}
        a["desvio"] = round(a["receita_real"] - a["receita_proj"], 2)
        a["desvio_pct"] = round(a["desvio"] / a["receita_proj"], 4) if abs(a["receita_proj"]) > 0.005 else None
        a["desvio_bdi"] = round(a["bdi_real"] - a["bdi_proj"], 2)
        linhas.append(a)
    soma = lambda f: round(sum(f(p) for p in projs), 2)          # noqa: E731
    return {"linhas": linhas, "total": {"receita_proj": soma(lambda p: p["total"]["receita_proj"]), "receita_real": soma(lambda p: p["total"]["receita_real"]),
                                        "bdi_proj": soma(lambda p: p["total"]["bdi_proj"])},
            "receita_proj_total": soma(lambda p: p["receita_proj_total"]), "receita_real_total": soma(lambda p: p["receita_real_total"]), "meses": len(projs)}


def cobertura_emissao_ini(conn) -> str | None:
    """Primeiro mes ('AAAA-MM') com a rotina diaria de emissao funcionando (antes disso a base so' tem residuos de titulos antigos). Guardado 2 min."""
    return _memo(("cob_emi", id(conn)), 120, lambda: _cobertura_emissao_ini_sql(conn))


def _cobertura_emissao_ini_sql(conn) -> str | None:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(min(mes), 'YYYY-MM') FROM pnl_sync WHERE lado='R' AND tipo_data='I' AND status <> 'ERRO'")
            return cur.fetchone()[0]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def contas_api_padrao(conn, mes: str) -> list:
    """Contas do mes reconstruidas pela API com as regras padrao (as mesmas da tela Resultado): sem previsao, sem NF desfeita, sem titulo desfeito
    e so' centros de obra (sem ADM) quando o de-para existe."""
    # guardado 60 s: a abertura do Painel da Diretoria pede o mesmo mes varias vezes (DRE, termos, obras); sync/importacao/confirmacao limpam
    return _memo(("contas_api", id(conn), mes), 60,
                 lambda: resultado_por_conta(conn, mes, sem_previsao=True, so_obras=centro_grupo_instalado(conn), sem_distrato=True, sem_desfeitos=True))


def dre_resolvido(conn, mes: str) -> dict | None:
    """DRE do mes pela prioridade unica do app: 1) CONFIRMADO (a fonte que a contabilidade escolheu por linha); 2) API do Sienge com as regras padrao (FLUXO PADRAO:
    ninguem precisa gerar PDF). O DRE oficial (PDF) e' OPCIONAL: serve para conferir contra a API e so' entra no fluxo (a) se a contabilidade o escolher numa linha da
    confirmacao ou (b) em meses ANTERIORES a rotina de emissao da API (la a base so' tem residuos). Devolve {'dre', 'fonte', 'origem', 'conf', 'imp'}
    com fonte em 'confirmado' | 'api' | 'pdf' (so' no caso b), ou None se o mes nao tem dado."""
    conf = confirmacao_ativa(conn, mes) if confirmacao_instalada(conn) else None
    if conf:
        return {"dre": dre_de_folhas(conf["valores"] or {}), "fonte": "confirmado", "origem": "DRE confirmado pela contabilidade", "conf": conf, "imp": None}
    ini = cobertura_emissao_ini(conn)
    if ini and mes < ini:
        imp = dre_importacao_ativa(conn, mes)
        if imp:
            contas = [{"plano_cod": c, "plano_nome": "", "valor": v} for c, v in dre_contas_importadas(conn, imp["id"]).items()]
            return {"dre": dre_do_mes(contas), "fonte": "pdf", "origem": "DRE oficial (PDF): mes anterior a API", "conf": None, "imp": imp}
        return None
    dre = dre_do_mes(contas_api_padrao(conn, mes) or [])
    if abs(dre["valores"]["01"]) < 0.005 and abs(dre["valores"]["04"]) < 0.005:
        return None
    return {"dre": dre, "fonte": "api", "origem": "API do Sienge (padrao, a conferir)", "conf": None, "imp": None}


def termos_do_mes(conn, mes: str) -> dict | None:
    """Os cinco termos do Resultado de UM mes: receita, custos diretos e BDI (= receita - custos) do DRE do mes (`dre_resolvido`: confirmado > API; PDF so' antes da API),
    administracao (orcamento ADM: realizado e orcado) e a projecao (receita e BDI previstos). A tabela de obras (projecao x realizado) vem da mesma fonte
    (`obras_do_mes`). None se o mes nao tem dado. Valores None quando falta a fonte (sem orcamento, sem projecao). 'fonte' diz de onde vieram os numeros."""
    r = dre_resolvido(conn, mes)
    if not r:
        return None
    v = r["dre"]["valores"]
    rec, cus = round(v["01"], 2), round(abs(v["04"]), 2)
    ob0 = obras_do_mes(conn, mes)
    if ob0:                                                  # custo no padrao da contabilidade: linha 04 do DRE (com as confirmacoes) + o que o padrao 04+06+08+09+10+12 soma alem da 04
        extra = ob0["total"]["custo"] - ob0["total"].get("custo_04", ob0["total"]["custo"])
        cus = round(abs(v["04"]) + abs(extra), 2) if extra <= 0 else round(max(abs(v["04"]) - extra, 0.0), 2)
    out = {"mes": mes, "rec": rec, "cus": cus, "bdi": round(rec - cus, 2), "fonte": r["fonte"],
           "adm_real": None, "adm_orc": None, "rec_p": None, "bdi_p": None}
    orc = orcamento_ativo(conn) if orcamento_instalado(conn) else None
    if orc and mes in orc["meses"]:
        t = orcamento_resumo(conn, orc["id"], mes)["total"]
        out["adm_real"], out["adm_orc"] = t["realizado"], t["orcado"]
    proj = projecao_do_mes(conn, mes)
    if proj:
        ob = ob0
        if ob:
            px = projecao_x_realizado(proj, ob, nomes_obras_extra(conn))
            if abs(px["receita_proj_total"]) > 0.005:
                out["rec_p"], out["bdi_p"] = px["receita_proj_total"], px["total"]["bdi_proj"]
    return out


def somar_termos(lista: list) -> dict | None:
    """Soma os termos de varios meses (`termos_do_mes`) no formato do painel: {chave: (realizado, previsto)} para rec, cus, bdi, adm, res. Administracao e resultado
    so' existem se TODOS os meses tem orcamento ADM; previsto so' se TODOS os meses tem projecao (senao None: n/d)."""
    lista = [t for t in (lista or []) if t]
    if not lista:
        return None
    tem = lambda k: all(t[k] is not None for t in lista)          # noqa: E731
    soma = lambda k: round(sum(t[k] for t in lista), 2)           # noqa: E731
    rec, cus, bdi = soma("rec"), soma("cus"), soma("bdi")
    adm_real = soma("adm_real") if tem("adm_real") else None
    adm_orc = soma("adm_orc") if tem("adm_orc") else None
    rec_p = soma("rec_p") if tem("rec_p") else None
    bdi_p = soma("bdi_p") if tem("bdi_p") else None
    cus_p = round(rec_p - bdi_p, 2) if rec_p is not None and bdi_p is not None else None
    return {"rec": (rec, rec_p), "cus": (cus, cus_p), "bdi": (bdi, bdi_p), "adm": (adm_real, adm_orc),
            "res": (round(bdi - adm_real, 2) if adm_real is not None else None, round(bdi_p - adm_orc, 2) if bdi_p is not None and adm_orc is not None else None),
            "meses": [t["mes"] for t in lista]}


def resultado_por_obra_api(conn, mes: str, sem_previsao: bool = False, sem_distrato: bool = True, sem_desfeitos: bool = True) -> dict:
    """Mesmo calculo do resultado_por_conta, agrupado pelo codigo da obra do de-para: {codigo_obra: {linha_dre: valor}} (+ 'sem de-para')."""
    ini = f"{mes}-01"
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro += " " + _filtro_distrato(sem_distrato) + " " + _filtro_desfeitos(sem_desfeitos)
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
    import custos_obra_nivel as CON
    for cod_obra, contas in por_obra.items():
        dre = dre_do_mes([{"plano_cod": k, "plano_nome": "", "valor": x} for k, x in contas.items()])
        saida[cod_obra] = {**dre["valores"], "CP": round(sum(x for k, x in contas.items() if k in CON.MAPA), 2)}      # CP = custo padrao (contas do relatorio de custos por obra)
    return saida


def custos_obra_linhas(conn, mes_ini: str, mes_fim: str, sem_previsao: bool = True, sem_desfeitos: bool = True) -> list:
    """Base da tabela "Custos por categoria" da aba Obras: [(codigo_obra, 'AAAA-MM', plano_cod, resultado)] dos titulos EMITIDOS de mes_ini ate mes_fim (analise
    'comprometido', como no relatorio da contabilidade), so' as contas que entram nas 7 categorias (custos_obra_nivel), sem centros ADM e com as mesmas regras padrao
    da tabela de Obras (sem previsao, sem titulos desfeitos). Resultado = com sinal do DRE (custo negativo). Sem a tabela de de-para: []."""
    import custos_obra_nivel as CON
    filtro = "AND COALESCE(upper(t.previsao),'') <> 'S'" if sem_previsao else ""
    filtro += " " + _filtro_distrato(True) + " " + _filtro_desfeitos(sem_desfeitos)
    with conn.cursor() as cur:
        try:
            cur.execute(f"""SELECT COALESCE(g.codigo_obra,'sem de-para'), to_char(t.data_emissao,'YYYY-MM'), t.lado, r.plano_cod, sum(t.valor_original * r.percentual / 100.0)
                            FROM pnl_titulo t JOIN pnl_v_rateio r ON r.lado=t.lado AND r.bill_id=t.bill_id AND r.installment_id=t.installment_id
                            LEFT JOIN pnl_centro_grupo g ON g.centro_custo_id = r.centro_custo_id
                            WHERE t.data_emissao >= %s::date AND t.data_emissao < (%s::date + interval '1 month') {filtro}
                              AND COALESCE(g.grupo,'') <> 'ADM' AND r.plano_cod = ANY(%s)
                            GROUP BY 1, 2, t.lado, r.plano_cod""", (f"{mes_ini}-01", f"{mes_fim}-01", list(CON.CONTAS)))
            return [(o, m, plano, round(_sinal_resultado(lado, plano) * float(v or 0), 2)) for o, m, lado, plano, v in cur.fetchall()]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return []


# ---------------------------------------------------------------- Confirmacao do DRE do mes (fonte escolhida por linha)
def confirmacao_instalada(conn) -> bool:
    """True se o SQL da confirmacao do DRE (sql/v2_dre_confirmacao.sql) ja foi executado. So' o 'sim' fica guardado (5 min)."""
    h = _MEMO.get(("conf_inst", id(conn)))
    if h is not None and time.monotonic() - h[0] < 300:
        return True
    ok = _confirmacao_instalada_sql(conn)
    if ok:
        _MEMO[("conf_inst", id(conn))] = (time.monotonic(), True)
    return ok


def _confirmacao_instalada_sql(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_dre_confirmacao'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def _confirmacoes_ativas(conn) -> dict:
    """{'AAAA-MM': confirmacao ativa} de todos os meses numa consulta so' (poucas linhas); guardado 15 s."""
    def ler():
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT to_char(mes,'YYYY-MM'), id, fontes, valores, confirmado_por, confirmado_em, observacao, resumo FROM pnl_dre_confirmacao
                               WHERE ativo ORDER BY id""")
                return {m: {"id": i, "fontes": f, "valores": v, "quem": q, "quando": w, "observacao": o, "resumo": r} for m, i, f, v, q, w, o, r in cur.fetchall()}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {}
    return _memo(("dre_conf", id(conn)), 15, ler)


def confirmacao_ativa(conn, mes: str) -> dict | None:
    """Confirmacao ativa do DRE do mes ('AAAA-MM'): {'id','fontes','valores','quem','quando','observacao','resumo'} ou None."""
    return _confirmacoes_ativas(conn).get(mes)


def carimbo_dados(conn) -> str:
    """'Carimbo' barato do estado dos dados (1 consulta so'): muda quando entra carga do Sienge, upload, confirmacao do DRE, regra ou de-para editado.
    O painel usa o carimbo como parte da chave do cache: enquanto nao muda, serve o resultado guardado; mudou, recalcula sozinho.
    Devolve '' se algo falhar (o cache cai no prazo de seguranca e o botao Atualizar continua valendo)."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT concat_ws('|',
                (SELECT coalesce(max(id),0) FROM pnl_sync),
                (SELECT count(*)||'/'||coalesce(max(importado_em)::text,'')||'/'||count(*) FILTER (WHERE ativo) FROM pnl_importacao),
                (SELECT count(*)||'/'||coalesce(max(alterado_em)::text,'')||'/'||count(*) FILTER (WHERE ativo) FROM pnl_regra),
                (SELECT coalesce(max(id),0) FROM pnl_edicao),
                (SELECT count(*) FROM pnl_centro_grupo),
                (SELECT count(*) FROM pnl_credor_grupo),
                (SELECT count(*) FROM pnl_folha_depto_obra),
                (SELECT coalesce(max(id),0) FROM pnl_dre_confirmacao),
                (SELECT count(*) FROM pnl_dre_valor),
                (SELECT coalesce(max(atualizado_em)::text,'') FROM pnl_obra_sienge),
                (SELECT coalesce(max(id),0) FROM pnl_log))""")
            base = cur.fetchone()[0] or ""
        return base + "|" + _carimbo_financiamento(conn) + "|" + _carimbo_credores(conn)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return ""


def _carimbo_financiamento(conn) -> str:
    """Parte do carimbo do cadastro de financiamentos (SQL-26): vazio se a tabela ainda nao existe (nao derruba o carimbo inteiro)."""
    if not fin_bem_instalado(conn):
        return ""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*)||'/'||coalesce(max(alterado_em)::text,'') FROM pnl_financiamento_bem")
        return cur.fetchone()[0] or ""


def fin_bem_instalado(conn) -> bool:
    """True se o SQL-26 (sql/v2_financiamento_bem.sql) ja foi executado."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_financiamento_bem'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def fin_bem_listar(conn) -> dict:
    """{chave_do_contrato: {'categoria','objeto','observacao','taxa_mensal'(% a.m. ou None)}} so' dos ativos."""
    if not fin_bem_instalado(conn):
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT chave, categoria, objeto, observacao, taxa_mensal FROM pnl_financiamento_bem WHERE ativo")
        return {c: {"categoria": cat, "objeto": obj, "observacao": obs, "taxa_mensal": float(tx) if tx is not None else None}
                for c, cat, obj, obs, tx in cur.fetchall()}


def fin_bem_salvar(conn, linhas: list, usuario: str | None) -> dict:
    """Grava/atualiza o cadastro de contratos. linhas = [{'chave','categoria','objeto','observacao','taxa_mensal'(% ao mes)}].
    Sem categoria E sem taxa = tira a definicao manual (ativo=false; volta a sugestao automatica). O log guarda so' contagens.
    Devolve {'novos','alterados','limpos'}."""
    novos = alterados = limpos = 0
    atuais = fin_bem_listar(conn)
    with db.transacao(conn):
        with conn.cursor() as cur:
            for l in linhas:
                chave = str(l.get("chave") or "").strip()
                if not chave:
                    continue
                cat = (l.get("categoria") or "").strip() or None
                obj = (l.get("objeto") or "").strip() or None
                obs = (l.get("observacao") or "").strip() or None
                tx = l.get("taxa_mensal")
                tx = round(float(tx), 4) if tx not in (None, "") and tx == tx else None
                if tx is not None and not (0 <= tx <= 100):
                    raise ValueError("A taxa mensal deve estar entre 0 e 100 (% ao mês).")
                antes = atuais.get(chave)
                if not cat and tx is None and not obj and not obs:
                    if antes:
                        cur.execute("UPDATE pnl_financiamento_bem SET ativo=false, alterado_por=%s, alterado_em=now() WHERE chave=%s", (usuario, chave))
                        limpos += 1
                    continue
                if antes and (antes["categoria"], antes["objeto"], antes["observacao"], antes["taxa_mensal"]) == (cat, obj, obs, tx):
                    continue
                cur.execute("""INSERT INTO pnl_financiamento_bem (chave, categoria, objeto, observacao, taxa_mensal, ativo, alterado_por)
                               VALUES (%s,%s,%s,%s,%s,true,%s)
                               ON CONFLICT (chave) DO UPDATE SET categoria=EXCLUDED.categoria, objeto=EXCLUDED.objeto, observacao=EXCLUDED.observacao,
                                   taxa_mensal=EXCLUDED.taxa_mensal, ativo=true, alterado_por=EXCLUDED.alterado_por, alterado_em=now()""",
                            (chave, cat, obj, obs, tx, usuario))
                novos, alterados = (novos + 1, alterados) if not antes else (novos, alterados + 1)
    registrar_log(conn, "FINANCIAMENTO_BEM_SALVO", "INFO", usuario, None, {"novos": novos, "alterados": alterados, "limpos": limpos})
    return {"novos": novos, "alterados": alterados, "limpos": limpos}


def meses_confirmados(conn) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(mes,'YYYY-MM') FROM pnl_dre_confirmacao WHERE ativo ORDER BY 1")
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def valores_adotados(fontes_disp: dict, escolha: dict, manuais: dict | None = None) -> dict:
    """Valor adotado por linha: da fonte escolhida (API/PDF) ou, se a escolha for 'MANUAL', o numero digitado na tela."""
    manuais = manuais or {}
    saida = {}
    for k, f in escolha.items():
        if f == "MANUAL":
            saida[k] = round(float(manuais.get(k, 0.0)), 2)
        else:
            saida[k] = float(fontes_disp[f].get(k, 0.0))
    return saida


def resumo_manuais(escolha: dict, adotado: dict, fontes_disp: dict) -> dict:
    """Para cada linha ajustada a mao: o valor digitado e o que a API e o PDF diziam (auditoria do ajuste)."""
    return {k: {"manual": round(float(adotado[k]), 2), **{f: fontes_disp[f].get(k) for f in fontes_disp}} for k, f in escolha.items() if f == "MANUAL"}


def gravar_confirmacao(conn, mes: str, fontes: dict, valores: dict, usuario: str | None, observacao: str | None = None,
                       resumo: dict | None = None, dre_importacao_id: int | None = None) -> dict:
    """Grava o DRE confirmado do mes: para cada linha 'folha' guarda a FONTE escolhida (API/PDF) e o valor adotado. A confirmacao anterior do mes
    fica ativo=false (historico). Devolve {'id', 'mes', 'substituiu': id_anterior|None}."""
    if set(fontes) != set(valores):
        raise ValueError("Fontes e valores precisam cobrir as mesmas linhas.")
    if any(f == "MANUAL" for f in fontes.values()) and not (observacao or "").strip():
        raise ValueError("Ajuste manual exige uma observação explicando o motivo.")
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE pnl_dre_confirmacao SET ativo=false WHERE mes=%s::date AND ativo RETURNING id", (f"{mes}-01",))
            ant = cur.fetchone()
            cur.execute("""INSERT INTO pnl_dre_confirmacao (mes, confirmado_por, observacao, fontes, valores, resumo, dre_importacao_id)
                           VALUES (%s::date, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        (f"{mes}-01", usuario, (observacao or None), json.dumps(fontes), json.dumps({k: round(float(v), 2) for k, v in valores.items()}),
                         json.dumps(resumo or {}), dre_importacao_id))
            novo = cur.fetchone()[0]
    limpar_memo()
    registrar_log(conn, "DRE_CONFIRMADO", "INFO", usuario, mes, {"confirmacao_id": novo, "substituiu": ant[0] if ant else None, "fontes": fontes,
                                                                  "resumo": resumo or {}, "observacao": (observacao or "")[:200]})
    return {"id": novo, "mes": mes, "substituiu": ant[0] if ant else None}


# ---------------------------------------------------------------- Administracao (aba do painel): despesas das unidades ADM, credores e de-para "Outros credores/Dir"
def norm_credor(s) -> str:
    """Nome do credor para comparar: MAIUSCULAS, sem acento e com espacos simples ('Credor  Beta Ltda' == 'CREDOR BETA LTDA')."""
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


GRUPOS_CREDOR = {"OUTROS_DIR": "Outros credores/Dir", "DEMAIS_PJ": "Demais colaboradores-PJ"}      # grupo -> rotulo mostrado


def credor_grupo_aceita(conn, grupo: str) -> bool:
    """True se o banco ja aceita esse grupo (o SQL-37 amplia o CHECK para 'DEMAIS_PJ'; 'OUTROS_DIR' vale desde o SQL-11)."""
    if grupo == "OUTROS_DIR":
        return credor_grupo_instalado(conn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname='gdf' AND t.relname='pnl_credor_grupo' AND c.contype='c' AND pg_get_constraintdef(c.oid) LIKE %s", (f"%{grupo}%",))
            return cur.fetchone()[0] >= 1
    except Exception:
        return False


def credor_grupo_ativos(conn, grupo: str = "OUTROS_DIR") -> list:
    """Credores ativos de um grupo ('OUTROS_DIR' = 'Outros credores/Dir'; 'DEMAIS_PJ' = 'Demais colaboradores-PJ'): [{'id','chave','nome','quem','quando'}]."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, chave, COALESCE(nome_exibicao, chave), alterado_por, alterado_em FROM pnl_credor_grupo WHERE ativo AND grupo=%s ORDER BY chave", (grupo,))
            return [{"id": i, "chave": c, "nome": n, "quem": q, "quando": e} for i, c, n, q, e in cur.fetchall()]
    except Exception:
        return []


def credor_grupo_adicionar(conn, nome: str, usuario: str | None, grupo: str = "OUTROS_DIR") -> dict:
    """Poe um credor num grupo. O credor casa se o nome dele COMECA com o texto informado (sem acento, sem diferenca de maiuscula).
    Devolve {'ok': True, 'id'} ou {'ok': False, 'erro'}. O log guarda so' o id (nada de nome de pessoa)."""
    if grupo not in GRUPOS_CREDOR:
        return {"ok": False, "erro": "Grupo desconhecido."}
    chave = norm_credor(nome)
    if len(chave) < 3:
        return {"ok": False, "erro": "Escreva pelo menos 3 letras do nome do credor."}
    if not credor_grupo_aceita(conn, grupo):
        return {"ok": False, "erro": "Falta executar o SQL-37 (sql/v2_demais_pj.sql) no Supabase para usar este grupo."}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM pnl_credor_grupo WHERE ativo AND grupo=%s AND chave=%s", (grupo, chave))
            if cur.fetchone():
                return {"ok": False, "erro": "Esse credor já está no grupo."}
            cur.execute("INSERT INTO pnl_credor_grupo (chave, nome_exibicao, grupo, alterado_por) VALUES (%s,%s,%s,%s) RETURNING id", (chave, str(nome).strip(), grupo, usuario))
            novo = cur.fetchone()[0]
    except Exception as exc:
        return {"ok": False, "erro": f"Não consegui gravar: {exc}"}
    registrar_log(conn, "CREDOR_GRUPO_ADICIONADO", "INFO", usuario, None, {"id": novo, "grupo": grupo, "tamanho_do_nome": len(chave)})
    return {"ok": True, "id": novo}


def credor_grupo_remover(conn, id_: int, usuario: str | None) -> bool:
    """Tira o credor do grupo (ativo = false; a linha fica no historico). Devolve True se mudou algo."""
    with conn.cursor() as cur:
        cur.execute("UPDATE pnl_credor_grupo SET ativo=false, alterado_por=%s, alterado_em=now() WHERE id=%s AND ativo RETURNING grupo", (usuario, int(id_)))
        r = cur.fetchone()
    if r:
        registrar_log(conn, "CREDOR_GRUPO_REMOVIDO", "INFO", usuario, None, {"id": int(id_), "grupo": r[0]})
    return bool(r)


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
    """Receita bruta por mes: 1) DRE CONFIRMADO do mes (linha 01.01); 2) API (titulos emitidos no mes, sem previsao e sem NF desfeita), o padrao; o DRE oficial
    importado (PDF) so' vale em meses anteriores a rotina de emissao da API. O mes em andamento ('mes_atual') fica de fora (incompleto).
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
        if rec is None and cobertura_ini and m < cobertura_ini:            # antes da rotina de emissao da API: so' o PDF (se houver) serve
            imp = dre_importacao_ativa(conn, m)
            if not imp:
                continue
            rec = round(sum(o["linhas"].get("01", 0.0) for o in dre_por_obra_importado(conn, imp["id"]).values()), 2)
            fonte = "DRE oficial (PDF)"
        if rec is None:
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
            # TODOS os descontos do recibo por departamento (contabilidade 20/10: base da HE = remuneracao liquida)
            cur.execute("""SELECT e.empresa, e.departamento, COALESCE(sum(e.desconto),0)
                           FROM pnl_folha_evento e JOIN pnl_importacao i ON i.id = e.importacao_id
                           WHERE i.tipo='FOLHA' AND i.mes=%s::date AND i.ativo
                           GROUP BY e.empresa, e.departamento""", (f"{mes}-01",))
            descontos = {(a, b): float(v) for a, b, v in cur.fetchall()}
    except Exception:
        return None
    tot = {"colab": 0, "salarios": 0.0, "hora_extra": 0.0, "dsr_he": 0.0, "proventos": 0.0, "fgts": 0.0, "descontos": 0.0}
    por_emp, por_obra, sem = {}, {}, []
    for emp, dep, sub, cod, onome, n, sal, he, dsr, prov, fgts in linhas:
        vals = {"colab": int(n), "salarios": float(sal), "hora_extra": float(he), "dsr_he": float(dsr), "proventos": float(prov), "fgts": float(fgts),
                "descontos": descontos.get((emp, dep), 0.0)}
        for k, v in vals.items():
            tot[k] += v
        e = por_emp.setdefault(emp, {"empresa": EMPRESAS_FOLHA.get(emp, emp), "colab": 0, "salarios": 0.0, "hora_extra": 0.0, "dsr_he": 0.0, "proventos": 0.0, "fgts": 0.0, "descontos": 0.0})
        for k, v in vals.items():
            e[k] += v
        if cod is None:
            sem.append({"empresa": EMPRESAS_FOLHA.get(emp, emp), "departamento": dep, "subnivel": sub, "colab": int(n)})
            cod = "sem de-para"
        o = por_obra.setdefault(cod, {"codigo": cod, "nome": onome or (sub if cod == "sem de-para" else ""), "colab": 0, "salarios": 0.0, "hora_extra": 0.0, "dsr_he": 0.0, "proventos": 0.0, "fgts": 0.0, "descontos": 0.0})
        for k, v in vals.items():
            o[k] += v
    # Base da HE (contabilidade, 20/10/2026): remuneracao liquida = proventos que nao sao HE nem DSR s/ HE, menos todos os descontos do recibo
    for d in [tot, *por_emp.values(), *por_obra.values()]:
        d["base_he"] = d["proventos"] - d["hora_extra"] - d["dsr_he"] - d["descontos"]
    pct = lambda d: round((d["hora_extra"] + d["dsr_he"]) / d["base_he"], 4) if d["base_he"] > 0.005 else None
    for d in [tot, *por_emp.values(), *por_obra.values()]:
        d["custo"] = round(d["proventos"] + d["fgts"], 2)
        d["he_pct"] = pct(d)
        for k in ("salarios", "hora_extra", "dsr_he", "proventos", "fgts", "descontos", "base_he"):
            d[k] = round(d[k], 2)
    return {"mes": mes, "importacoes": [{"id": i[0], "escopo": i[1], "arquivo": i[2], "quem": i[3], "quando": i[4]} for i in imps], "total": tot,
            "por_empresa": sorted(por_emp.values(), key=lambda d: d["empresa"]), "por_obra": por_obra, "sem_depara": sem}


def folha_colaboradores(conn, mes: str) -> list:
    """Colaboradores CLT do mes (recibos da folha das importacoes ativas): [{'nome','cargo','empresa','obra'}], 'obra' = codigo do de-para departamento -> obra
    ('sem de-para' quando nao ha; '99' = administracao central). So' leitura; lista vazia se o mes nao tem folha."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT r.nome, r.cargo, r.empresa, COALESCE(d.codigo_obra,'sem de-para')
                           FROM pnl_folha_recibo r JOIN pnl_importacao i ON i.id = r.importacao_id
                           LEFT JOIN pnl_folha_depto_obra d ON d.empresa = r.empresa AND d.departamento = r.departamento
                           WHERE i.tipo='FOLHA' AND i.mes=%s::date AND i.ativo
                           ORDER BY r.nome""", (f"{mes}-01",))
            return [{"nome": n or "", "cargo": c or "", "empresa": EMPRESAS_FOLHA.get(e, e), "obra": o} for n, c, e, o in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def folha_serie(conn) -> list:
    """[{'mes','colab','salarios','he_pct','he_valor' (HE + DSR s/ HE em R$)}] dos meses com folha importada (para o grafico HE / salarios)."""
    out = []
    for m in folha_meses(conn):
        f = folha_do_mes(conn, m)
        if f:
            out.append({"mes": m, "colab": f["total"]["colab"], "salarios": f["total"]["salarios"], "he_pct": f["total"]["he_pct"],
                        "he_valor": round(f["total"]["hora_extra"] + f["total"]["dsr_he"], 2)})
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


# ---------------------------------------------------------------- Projecao de receitas das obras (planilha xlsx; tabela pnl_projecao_linha do SQL v2)
def gravar_projecao(conn, proj: dict, arquivo: str, sha256: str, usuario: str | None) -> dict:
    """Grava a projecao lida do xlsx como importacao ativa do mes (a anterior do mesmo mes fica ativo=false). Mesmo arquivo: nao grava de novo."""
    mes = proj["mes"] + "-01"
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, mes FROM pnl_importacao WHERE tipo='PROJECAO' AND arquivo_sha256=%s", (sha256,))
            ja = cur.fetchone()
            if ja:
                return {"repetido": True, "id": ja[0], "ativo": ja[1], "mes": ja[2].strftime("%Y-%m")}
            cur.execute("UPDATE pnl_importacao SET ativo=false WHERE tipo='PROJECAO' AND mes=%s AND escopo='' AND ativo", (mes,))
            cur.execute("""INSERT INTO pnl_importacao (tipo, mes, escopo, arquivo_nome, arquivo_sha256, importado_por, n_linhas, detalhe)
                           VALUES ('PROJECAO', %s, '', %s, %s, %s, %s, %s) RETURNING id""",
                        (mes, arquivo, sha256, usuario, len(proj["linhas"]), json.dumps({"linhas": len(proj["linhas"]), "avisos": proj["avisos"]}, ensure_ascii=False)))
            iid = cur.fetchone()[0]
            execute_values(cur, """INSERT INTO pnl_projecao_linha (importacao_id, linha, contrato, cliente, obra, categoria, natureza, empresa, valor_mes, custos, bdi) VALUES %s""",
                           [(iid, l["linha"], l["contrato"], l["cliente"], l["obra"], l["categoria"], l["natureza"], l["empresa"], l["valor_mes"], l["custos"], l["bdi"]) for l in proj["linhas"]])
    registrar_log(conn, "PROJECAO_XLSX_IMPORTADA", "AVISO" if proj["avisos"] else "INFO", usuario, mes[:7],
                  {"arquivo": arquivo, "sha256": sha256[:16], "importacao_id": iid, "linhas": len(proj["linhas"]), "avisos": len(proj["avisos"])})
    return {"repetido": False, "id": iid, "mes": mes[:7], "linhas": len(proj["linhas"])}


def projecao_meses(conn) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(mes,'YYYY-MM') FROM pnl_importacao WHERE tipo='PROJECAO' AND ativo ORDER BY 1")
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def projecao_do_mes(conn, mes: str) -> dict | None:
    """Projecao ativa do mes: {'id','arquivo','quem','quando','linhas':[{obra, cliente, empresa, valor_mes, custos, bdi}]} ou None."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, arquivo_nome, importado_por, importado_em FROM pnl_importacao
                           WHERE tipo='PROJECAO' AND mes=%s::date AND escopo='' AND ativo ORDER BY id DESC LIMIT 1""", (f"{mes}-01",))
            imp = cur.fetchone()
            if not imp:
                return None
            cur.execute("""SELECT obra, cliente, empresa, valor_mes, custos, bdi FROM pnl_projecao_linha WHERE importacao_id=%s ORDER BY linha""", (imp[0],))
            linhas = [{"obra": o or "", "cliente": c or "", "empresa": e or "", "valor_mes": float(v or 0), "custos": float(cu or 0), "bdi": float(b or 0)} for o, c, e, v, cu, b in cur.fetchall()]
    except Exception:
        return None
    return {"id": imp[0], "arquivo": imp[1], "quem": imp[2], "quando": imp[3], "linhas": linhas}


def projecao_x_realizado(proj: dict, ob: dict, nomes_extra: dict | None = None) -> dict:
    """Compara a projecao do mes com o DRE oficial por obra. `ob` e' o resultado de obras_do_dre (linhas com obra/nome/receita/custo/bdi).
    Devolve {'linhas': [{obra_proj, codigo, nome, receita_proj, receita_real, desvio, desvio_pct, bdi_proj, bdi_real, desvio_bdi}], 'sem_correspondencia': [...],
    'total': {...}}. Obras do DRE sem projecao nao entram na tabela, mas a receita delas aparece em 'receita_sem_projecao'."""
    from importador_projecao import casar_obra_dre, projecao_por_obra
    # O nome da obra no PDF do DRE e' so' o cliente ('ELETROBRAS'); a projecao usa 'LOTE 03', 'OPGW II'... Por isso o casamento tambem olha os nomes
    # completos cadastrados para o codigo (de-para de centros de custo e de departamentos da folha), passados em nomes_extra {codigo: "nome1 nome2"}.
    nomes = {l["obra"]: f'{l["nome"]} {(nomes_extra or {}).get(l["obra"], "")}'.strip() for l in ob["linhas"] if l["obra"] != "DEM"}
    por_cod = {l["obra"]: l for l in ob["linhas"]}
    linhas, sem, usados = [], [], set()
    for o in projecao_por_obra([{"obra": l["obra"], "cliente": l["cliente"], "valor_mes": l["valor_mes"], "custos": l["custos"], "bdi": l["bdi"]} for l in proj["linhas"]]):
        cod = casar_obra_dre(o["chave"], nomes)
        if cod is None:
            sem.append(o)
            continue
        usados.add(cod)
        r = por_cod[cod]
        linhas.append({"obra_proj": o["obra"], "codigo": cod, "nome": r["nome"], "receita_proj": o["receita"], "receita_real": r["receita"],
                       "desvio": round(r["receita"] - o["receita"], 2), "desvio_pct": round((r["receita"] - o["receita"]) / o["receita"], 4) if abs(o["receita"]) > 0.005 else None,
                       "bdi_proj": o["bdi"], "bdi_real": r["bdi"], "desvio_bdi": round(r["bdi"] - o["bdi"], 2)})
    soma = lambda k, L: round(sum(x[k] for x in L), 2)
    total = {"receita_proj": soma("receita_proj", linhas) + soma("receita", sem), "receita_real": soma("receita_real", linhas), "bdi_proj": soma("bdi_proj", linhas) + soma("bdi", sem)}
    return {"linhas": linhas, "sem_correspondencia": sem, "total": total,
            "receita_sem_projecao": round(sum(l["receita"] for l in ob["linhas"] if l["obra"] not in usados), 2),
            "receita_proj_total": round(sum(o["valor_mes"] for o in proj["linhas"]), 2), "receita_real_total": ob["total"]["receita"]}


# ---------------------------------------------------------------- Orcamento ADM (PDF "Comparativo Orcado X Realizado"; SQL-18)
def orcamento_instalado(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_orcamento_linha'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def gravar_orcamento(conn, orc: dict, arquivo: str, sha256: str, usuario: str | None) -> dict:
    """Grava o orcamento lido do PDF como importacao ativa (a anterior com o mesmo mes inicial fica ativo=false). Mesmo arquivo: nao grava de novo."""
    ini = (orc["cabecalho"].get("inicio") or "")[:7]
    if not ini:
        raise ValueError("O PDF não informa o período; não sei a que mês o orçamento começa.")
    mes = ini + "-01"
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, mes FROM pnl_importacao WHERE tipo='ORCAMENTO' AND arquivo_sha256=%s", (sha256,))
            ja = cur.fetchone()
            if ja:
                return {"repetido": True, "id": ja[0], "ativo": ja[1], "mes": ja[2].strftime("%Y-%m")}
            cur.execute("UPDATE pnl_importacao SET ativo=false WHERE tipo='ORCAMENTO' AND mes=%s AND escopo='' AND ativo", (mes,))
            cur.execute("""INSERT INTO pnl_importacao (tipo, mes, escopo, arquivo_nome, arquivo_sha256, importado_por, n_linhas, detalhe)
                           VALUES ('ORCAMENTO', %s, '', %s, %s, %s, %s, %s) RETURNING id""",
                        (mes, arquivo, sha256, usuario, len(orc["linhas"]),
                         json.dumps({"cabecalho": orc["cabecalho"], "meses": orc["meses"], "avisos": orc["avisos"]}, ensure_ascii=False)))
            iid = cur.fetchone()[0]
            execute_values(cur, "INSERT INTO pnl_orcamento_linha (importacao_id, codigo, conta, tipo, mes, orcado, realizado, saldo) VALUES %s",
                           [(iid, l["codigo"], l["conta"], l["tipo"], l["mes"] + "-01", l["orcado"], l["realizado"], l["saldo"]) for l in orc["linhas"]])
    registrar_log(conn, "ORCAMENTO_ADM_IMPORTADO", "AVISO" if orc["avisos"] else "INFO", usuario, ini,
                  {"arquivo": arquivo, "sha256": sha256[:16], "importacao_id": iid, "linhas": len(orc["linhas"]), "meses": len(orc["meses"]), "avisos": len(orc["avisos"])})
    return {"repetido": False, "id": iid, "mes": ini, "linhas": len(orc["linhas"])}


def orcamento_ativo(conn) -> dict | None:
    """Orcamento ADM mais recente e ativo: {'id','arquivo','quem','quando','inicio','meses':['AAAA-MM'...]} ou None."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, arquivo_nome, importado_por, importado_em, to_char(mes,'YYYY-MM') FROM pnl_importacao
                           WHERE tipo='ORCAMENTO' AND ativo ORDER BY mes DESC, id DESC LIMIT 1""")
            r = cur.fetchone()
            if not r:
                return None
            cur.execute("SELECT DISTINCT to_char(mes,'YYYY-MM') FROM pnl_orcamento_linha WHERE importacao_id=%s ORDER BY 1", (r[0],))
            meses = [x[0] for x in cur.fetchall()]
    except Exception:
        return None
    return {"id": r[0], "arquivo": r[1], "quem": r[2], "quando": r[3], "inicio": r[4], "meses": meses}


def orcamento_resumo(conn, importacao_id: int, mes: str, acumulado: bool = False, top: int = 8, mes_ini: str | None = None) -> dict:
    """Orcado x realizado das DESPESAS (codigo 2.*) no mes ou acumulado do inicio do periodo ate o mes. Desvio = realizado - orcado (positivo = gastou mais
    que o orcado). `mes_ini` (so' com acumulado) limita o inicio do periodo: de `mes_ini` a `mes`; sem ele, do primeiro mes do orcamento.
    Devolve {'total': {...}, 'grupos': [linhas T de 2 e 3 niveis], 'acima': [contas que mais passaram], 'abaixo': [contas que mais sobraram], 'contas': [todas as contas]}."""
    with conn.cursor() as cur:
        if acumulado:
            cur.execute("""SELECT codigo, max(conta), tipo, sum(orcado), sum(realizado) FROM pnl_orcamento_linha
                           WHERE importacao_id=%s AND mes <= %s::date AND mes >= %s::date AND (codigo = '2' OR codigo LIKE '2.%%') GROUP BY codigo, tipo""",
                        (importacao_id, f"{mes}-01", f"{mes_ini or '0001-01'}-01" if mes_ini else "0001-01-01"))
        else:
            cur.execute("""SELECT codigo, max(conta), tipo, sum(orcado), sum(realizado) FROM pnl_orcamento_linha
                           WHERE importacao_id=%s AND mes = %s::date AND (codigo = '2' OR codigo LIKE '2.%%') GROUP BY codigo, tipo""", (importacao_id, f"{mes}-01"))
        linhas = cur.fetchall()
    def reg(cod, nome, tipo, orc, real):
        orc, real = round(float(orc or 0), 2), round(float(real or 0), 2)
        return {"codigo": cod, "conta": nome, "tipo": tipo, "orcado": orc, "realizado": real, "desvio": round(real - orc, 2),
                "desvio_pct": round((real - orc) / orc, 4) if abs(orc) > 0.005 else None}
    regs = [reg(*l) for l in linhas]
    total = next((r for r in regs if r["codigo"] == "2"), None) or {"codigo": "2", "conta": "SAÍDAS/CUSTOS/DESPESAS", "tipo": "T", "orcado": 0.0, "realizado": 0.0, "desvio": 0.0, "desvio_pct": None}
    grupos = sorted((r for r in regs if r["tipo"] == "T" and r["codigo"].count(".") in (1, 2)), key=lambda r: r["codigo"])
    contas = [r for r in regs if r["tipo"] in ("R", "M") and (abs(r["orcado"]) > 0.005 or abs(r["realizado"]) > 0.005)]
    return {"total": total, "grupos": grupos, "acima": sorted((r for r in contas if r["desvio"] > 0.005), key=lambda r: -r["desvio"])[:top],
            "abaixo": sorted((r for r in contas if r["desvio"] < -0.005), key=lambda r: r["desvio"])[:top],
            "contas": sorted(contas, key=lambda r: (-r["desvio"], r["codigo"]))}


def orcamento_serie_mensal(conn, importacao_id: int) -> list:
    """Serie mes a mes do total de despesas (codigo 2): orcado, realizado, desvio (realizado - orcado), desvio % e desvio acumulado no periodo.
    Devolve [{'mes':'AAAA-MM','orcado','realizado','desvio','desvio_pct','desvio_acum'}] em ordem de mes."""
    with conn.cursor() as cur:
        cur.execute("""SELECT to_char(mes,'YYYY-MM'), sum(orcado), sum(realizado) FROM pnl_orcamento_linha
                       WHERE importacao_id=%s AND codigo='2' GROUP BY mes ORDER BY mes""", (importacao_id,))
        linhas = cur.fetchall()
    saida, acum = [], 0.0
    for mes, orc, real in linhas:
        orc, real = round(float(orc or 0), 2), round(float(real or 0), 2)
        desvio = round(real - orc, 2)
        acum = round(acum + desvio, 2)
        saida.append({"mes": mes, "orcado": orc, "realizado": real, "desvio": desvio,
                      "desvio_pct": round(desvio / orc, 4) if abs(orc) > 0.005 else None, "desvio_acum": acum})
    return saida


def importacao_por_sha(conn, tipo: str, sha256: str) -> dict | None:
    """Esse arquivo (pelo SHA-256 completo) ja foi salvo? Devolve {id, ativo, mes, quando, quem, linhas} ou None. So leitura; nunca levanta erro."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, mes, importado_em, importado_por, n_linhas FROM pnl_importacao WHERE tipo=%s AND arquivo_sha256=%s", (tipo, sha256))
            r = cur.fetchone()
    except Exception:
        return None
    if not r:
        return None
    return {"id": r[0], "ativo": r[1], "mes": r[2].strftime("%Y-%m"), "quando": r[3], "quem": r[4], "linhas": r[5]}


# Nome da obra vindo do cadastro do Sienge (SQL-24): so' onde o numero do painel e' o mesmo id/codigo da obra no Sienge; entra por ultimo (os nomes
# do de-para e da folha, validados pela contabilidade, tem prioridade)
NOMES_OBRA_SIENGE_SQL = """SELECT g.codigo_obra, COALESCE(NULLIF(o.nome,''), o.nome_comercial)
                           FROM (SELECT DISTINCT codigo_obra FROM pnl_centro_grupo WHERE COALESCE(codigo_obra,'') NOT IN ('', 'DEM', 'ADM')) g
                           JOIN pnl_obra_sienge o ON o.id::text = g.codigo_obra OR o.codigo = g.codigo_obra
                           WHERE COALESCE(NULLIF(o.nome,''), o.nome_comercial) IS NOT NULL"""


def nomes_obras_extra(conn) -> dict:
    """{codigo_obra: 'nome completo 1 nome completo 2 ...'} juntando os nomes do de-para de centros de custo e do de-para de departamentos da folha.
    Serve para casar o nome curto da projecao ('LOTE 03') com a obra do DRE. So leitura; sem as tabelas devolve {}."""
    out: dict = {}
    for sql in ("SELECT codigo_obra, obra_nome FROM pnl_centro_grupo WHERE codigo_obra IS NOT NULL AND obra_nome IS NOT NULL",
                "SELECT codigo_obra, obra_nome FROM pnl_folha_depto_obra WHERE obra_nome IS NOT NULL",
                NOMES_OBRA_SIENGE_SQL):
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                for cod, nome in cur.fetchall():
                    if nome and nome not in out.get(cod, ""):
                        out[cod] = f"{out.get(cod, '')} {nome}".strip()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    return out


# ---------------------------------------------------------------- Importacoes (V2): historico, reverter sem apagar, editar valores (SQL-19)
# Cada tipo de importacao grava numa tabela; os campos abaixo sao os que a tela deixa editar (tipo: text, num, int, date). NOT NULL = obrigatorios.
EDIT_CFG = {
    "FOLHA": {"tabela": "pnl_folha_recibo", "ordem": "empresa, nome, id", "nome": "Recibos da folha",
              "campos": [("empresa", "text"), ("cadastro", "text"), ("nome", "text"), ("cargo", "text"), ("local_obra", "text"), ("departamento", "text"),
                         ("subnivel_texto", "text"), ("admissao", "date"), ("salario", "num"), ("hora_extra", "num"), ("dsr_he", "num"),
                         ("total_proventos", "num"), ("total_descontos", "num"), ("liquido", "num"), ("fgts_mes", "num")],
              "obrigatorios": {"empresa", "cadastro"}},
    "PROJECAO": {"tabela": "pnl_projecao_linha", "ordem": "linha, id", "nome": "Linhas da projeção de receitas",
                 "campos": [("linha", "int"), ("contrato", "text"), ("cliente", "text"), ("obra", "text"), ("categoria", "text"), ("natureza", "text"),
                            ("empresa", "text"), ("valor_mes", "num"), ("custos", "num"), ("bdi", "num")],
                 "obrigatorios": {"linha"}},
    "ORCAMENTO": {"tabela": "pnl_orcamento_linha", "ordem": "codigo, mes, id", "nome": "Linhas do orçamento ADM",
                  "campos": [("codigo", "text"), ("conta", "text"), ("tipo", "text"), ("mes", "date"), ("orcado", "num"), ("realizado", "num"), ("saldo", "num")],
                  "obrigatorios": {"codigo", "mes"}},
    "DRE": {"tabela": "pnl_dre_valor", "ordem": "obra_cod, linha, conta NULLS FIRST, id", "nome": "Valores do DRE oficial (por obra, linha e conta)",
            "campos": [("obra_cod", "text"), ("obra_nome", "text"), ("linha", "text"), ("conta", "text"), ("conta_nome", "text"), ("valor", "num")],
            "obrigatorios": {"obra_cod", "linha", "valor"}},
}


def edicao_instalada(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='gdf' AND table_name='pnl_edicao'")
            return cur.fetchone()[0] == 1
    except Exception:
        return False


def _vazio(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    try:
        return v != v          # NaN
    except Exception:
        return False


def converter_valor_edicao(tipo: str, v):
    """Converte o que veio da tela para o tipo do campo (None se vazio). Erro de valor levanta ValueError com mensagem em portugues."""
    import datetime as _dt
    from decimal import Decimal, InvalidOperation
    if _vazio(v):
        return None
    try:
        if tipo == "text":
            return str(v).strip()
        if tipo == "int":
            return int(round(float(v)))
        if tipo == "num":
            if isinstance(v, str):
                t = v.strip().replace("R$", "").replace(" ", "")
                if "," in t:
                    t = t.replace(".", "").replace(",", ".")
                v = t
            return Decimal(str(round(float(v), 2))).quantize(Decimal("0.01"))
        if tipo == "date":
            if hasattr(v, "date") and not isinstance(v, _dt.date):
                return v.date()
            if isinstance(v, _dt.datetime):
                return v.date()
            if isinstance(v, _dt.date):
                return v
            return _dt.date.fromisoformat(str(v)[:10])
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError(f"Valor inválido “{v}” (esperado: {'texto' if tipo == 'text' else 'número' if tipo in ('num', 'int') else 'data AAAA-MM-DD'}).")
    raise ValueError(f"Tipo de campo desconhecido: {tipo}")


def importacoes_lista(conn, tipo: str | None = None) -> list[dict]:
    """Todas as importacoes da V2 (DRE, folha, projecao, orcamento), da mais nova para a mais antiga, com o numero de edicoes de cada uma."""
    with conn.cursor() as cur:
        cur.execute("""SELECT id, tipo, mes, escopo, arquivo_nome, ativo, importado_por, importado_em, n_linhas
                       FROM pnl_importacao WHERE tipo IN ('DRE','FOLHA','PROJECAO','ORCAMENTO','HISTORICO') AND (%s IS NULL OR tipo=%s) ORDER BY id DESC""", (tipo, tipo))
        rows = cur.fetchall()
    n_ed: dict = {}
    if edicao_instalada(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT importacao_id, count(*) FROM pnl_edicao WHERE importacao_id IS NOT NULL AND acao IN ('EDITOU','ADICIONOU') GROUP BY importacao_id")
            n_ed = {i: n for i, n in cur.fetchall()}
    return [{"id": r[0], "tipo": r[1], "mes": r[2].strftime("%Y-%m"), "escopo": r[3], "arquivo": r[4], "ativo": r[5], "quem": r[6], "quando": r[7],
             "linhas": r[8], "edicoes": n_ed.get(r[0], 0)} for r in rows]


def importacao_definir_ativo(conn, imp_id: int, ativo: bool, usuario: str | None, motivo: str | None = None) -> dict:
    """Reverter sem apagar: ativo=False tira a importacao de uso; ativo=True poe esta em uso e tira de uso a que estava ativa no mesmo tipo+mes+escopo.
    Nada e' apagado; fica registrado em pnl_edicao (DESATIVOU/REATIVOU) e no historico do painel."""
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT tipo, mes, escopo, ativo FROM pnl_importacao WHERE id=%s FOR UPDATE", (imp_id,))
            r = cur.fetchone()
            if not r:
                raise ValueError("Importação não encontrada.")
            tipo, mes, escopo, ja = r
            if ja == ativo:
                return {"mudou": False, "tipo": tipo, "mes": mes.strftime("%Y-%m"), "substituiu": None}
            subst = None
            if ativo:
                cur.execute("SELECT id FROM pnl_importacao WHERE tipo=%s AND mes=%s AND escopo=%s AND ativo AND id<>%s", (tipo, mes, escopo, imp_id))
                x = cur.fetchone()
                if x:
                    subst = x[0]
                    cur.execute("UPDATE pnl_importacao SET ativo=false WHERE id=%s", (subst,))
                    cur.execute("INSERT INTO pnl_edicao (importacao_id, tabela, campo, acao, motivo, quem) VALUES (%s,'pnl_importacao','ativo','DESATIVOU',%s,%s)",
                                (subst, f"substituída pela #{imp_id}" + (f" — {motivo}" if motivo else ""), usuario))
            cur.execute("UPDATE pnl_importacao SET ativo=%s WHERE id=%s", (ativo, imp_id))
            cur.execute("INSERT INTO pnl_edicao (importacao_id, tabela, campo, valor_antes, valor_depois, acao, motivo, quem) VALUES (%s,'pnl_importacao','ativo',%s,%s,%s,%s,%s)",
                        (imp_id, str(ja).lower(), str(ativo).lower(), "REATIVOU" if ativo else "DESATIVOU", motivo, usuario))
    limpar_memo()
    registrar_log(conn, "IMPORTACAO_REATIVADA" if ativo else "IMPORTACAO_FORA_DE_USO", "AVISO", usuario, mes.strftime("%Y-%m"),
                  {"importacao_id": imp_id, "tipo": tipo, "escopo": escopo, "substituiu": subst})
    return {"mudou": True, "tipo": tipo, "mes": mes.strftime("%Y-%m"), "substituiu": subst}


def edicao_carregar(conn, tipo: str, imp_id: int) -> list[dict]:
    """Linhas de uma importacao para a tela editar: [{'id': ..., campo: valor, ...}] (numeros como float, datas como date)."""
    cfg = EDIT_CFG[tipo]
    cols = ", ".join(c for c, _ in cfg["campos"])
    with conn.cursor() as cur:
        cur.execute(f"SELECT id, {cols} FROM {cfg['tabela']} WHERE importacao_id=%s ORDER BY {cfg['ordem']}", (imp_id,))
        dados = cur.fetchall()
    nomes = ["id"] + [c for c, _ in cfg["campos"]]
    out = []
    for r in dados:
        d = dict(zip(nomes, r))
        for c, t in cfg["campos"]:
            if t == "num" and d[c] is not None:
                d[c] = float(d[c])
        out.append(d)
    return out


def _orcamento_recalcular(cur, imp_id: int, tocadas: dict, deltas: dict, usuario: str | None, motivo: str | None) -> int:
    """Orcamento ADM: depois de editar orcado/realizado, o app acerta sozinho (1) o SALDO (= realizado - orcado) das linhas mexidas e (2) os TOTAIS dos grupos acima
    (linha T do mesmo mes: soma a diferenca do que mudou). tocadas = {id_da_linha}; deltas = {(codigo, mes, campo): variacao}. Cada acerto automatico tambem vai para pnl_edicao
    (motivo 'automatico'), entao nada muda sem registro. Devolve quantas celulas automaticas foram acertadas."""
    auto = 0
    mot_auto = "automático (soma do grupo)" + (f": {motivo}" if motivo else "")
    mot_saldo = "automático (saldo = realizado − orçado)" + (f": {motivo}" if motivo else "")
    for (cod, mes, campo), delta in sorted(deltas.items()):
        if abs(delta) < 0.005:
            continue
        partes = cod.split(".")
        for n in range(len(partes) - 1, 0, -1):               # 2.01.01 -> 2.01 -> 2
            pai = ".".join(partes[:n])
            cur.execute(f"SELECT id, {campo} FROM pnl_orcamento_linha WHERE importacao_id=%s AND codigo=%s AND mes=%s AND tipo='T' ORDER BY id LIMIT 1 FOR UPDATE", (imp_id, pai, mes))
            r = cur.fetchone()
            if not r:                                         # o grupo estava todo zerado nesse mes (o PDF nao traz linha zerada): cria a linha do total
                cur.execute("SELECT conta FROM pnl_orcamento_linha WHERE importacao_id=%s AND codigo=%s AND tipo='T' ORDER BY id LIMIT 1", (imp_id, pai))
                nome = cur.fetchone()
                if not nome:                                  # grupo que nem existe no arquivo: nao inventa
                    continue
                cur.execute(f"INSERT INTO pnl_orcamento_linha (importacao_id, codigo, conta, tipo, mes, orcado, realizado, saldo) VALUES (%s,%s,%s,'T',%s,0,0,0) RETURNING id", (imp_id, pai, nome[0], mes))
                r = (cur.fetchone()[0], 0)
                cur.execute("UPDATE pnl_importacao SET n_linhas = n_linhas + 1 WHERE id=%s", (imp_id,))
                cur.execute("""INSERT INTO pnl_edicao (importacao_id, tabela, linha_id, campo, valor_depois, acao, motivo, quem)
                               VALUES (%s,'pnl_orcamento_linha',%s,'*',%s,'ADICIONOU',%s,%s)""",
                            (imp_id, r[0], f"total do grupo {pai} criado (estava zerado neste mês)", mot_auto, usuario))
                auto += 1
            novo = round(float(r[1] or 0) + delta, 2)
            cur.execute(f"UPDATE pnl_orcamento_linha SET {campo}=%s WHERE id=%s", (novo, r[0]))
            cur.execute("""INSERT INTO pnl_edicao (importacao_id, tabela, linha_id, campo, valor_antes, valor_depois, acao, motivo, quem)
                           VALUES (%s,'pnl_orcamento_linha',%s,%s,%s,%s,'EDITOU',%s,%s)""",
                        (imp_id, r[0], campo, None if r[1] is None else str(r[1]), str(novo), mot_auto, usuario))
            tocadas.setdefault(r[0], None)
            auto += 1
    for lid in list(tocadas):
        cur.execute("SELECT orcado, realizado, saldo FROM pnl_orcamento_linha WHERE id=%s AND importacao_id=%s", (lid, imp_id))
        r = cur.fetchone()
        if not r:
            continue
        saldo = round(float(r[1] or 0) - float(r[0] or 0), 2)
        if r[2] is None or abs(float(r[2]) - saldo) >= 0.005:
            cur.execute("UPDATE pnl_orcamento_linha SET saldo=%s WHERE id=%s", (saldo, lid))
            cur.execute("""INSERT INTO pnl_edicao (importacao_id, tabela, linha_id, campo, valor_antes, valor_depois, acao, motivo, quem)
                           VALUES (%s,'pnl_orcamento_linha',%s,'saldo',%s,%s,'EDITOU',%s,%s)""",
                        (imp_id, lid, None if r[2] is None else str(r[2]), str(saldo), mot_saldo, usuario))
            auto += 1
    return auto


def edicao_aplicar(conn, tipo: str, imp_id: int, alteracoes: list, novos: list, usuario: str | None, motivo: str | None = None) -> dict:
    """Grava as edicoes de uma importacao. alteracoes = [(id_da_linha, campo, valor_novo)]; novos = [{campo: valor}] (linhas novas). Valida campo e tipo,
    nao deixa campo obrigatorio vazio, guarda ANTES e DEPOIS de cada celula em pnl_edicao e so' troca o que de fato mudou. Tudo numa transacao."""
    import json as _json
    cfg = EDIT_CFG[tipo]
    tipos = dict(cfg["campos"])
    obrig = cfg["obrigatorios"]
    tabela = cfg["tabela"]
    ed = nv = auto = 0
    orc_deltas: dict = {}
    orc_tocadas: dict = {}
    with db.transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pnl_importacao WHERE id=%s AND tipo=%s", (imp_id, tipo))
            if not cur.fetchone():
                raise ValueError("Importação não encontrada para esse tipo.")
            for linha_id, campo, valor in alteracoes:
                if campo not in tipos:
                    raise ValueError(f"Campo não editável: {campo}")
                novo = converter_valor_edicao(tipos[campo], valor)
                if novo is None and campo in obrig:
                    raise ValueError(f"O campo “{campo}” não pode ficar vazio (linha {linha_id}).")
                if tipo == "ORCAMENTO" and campo == "saldo":
                    raise ValueError("O saldo é calculado sozinho (realizado − orçado): edite o orçado ou o realizado.")
                cur.execute(f"SELECT {campo} FROM {tabela} WHERE id=%s AND importacao_id=%s FOR UPDATE", (linha_id, imp_id))
                r = cur.fetchone()
                if not r:
                    raise ValueError(f"Linha {linha_id} não pertence a esta importação.")
                if r[0] == novo:
                    continue
                if tipo == "ORCAMENTO" and campo in ("orcado", "realizado"):
                    cur.execute("SELECT codigo, mes FROM pnl_orcamento_linha WHERE id=%s", (linha_id,))
                    _cod, _mes = cur.fetchone()
                    chave = (_cod, _mes, campo)
                    orc_deltas[chave] = orc_deltas.get(chave, 0.0) + float(novo or 0) - float(r[0] or 0)
                    orc_tocadas[linha_id] = None
                cur.execute(f"UPDATE {tabela} SET {campo}=%s WHERE id=%s", (novo, linha_id))
                cur.execute("""INSERT INTO pnl_edicao (importacao_id, tabela, linha_id, campo, valor_antes, valor_depois, acao, motivo, quem)
                               VALUES (%s,%s,%s,%s,%s,%s,'EDITOU',%s,%s)""",
                            (imp_id, tabela, linha_id, campo, None if r[0] is None else str(r[0]), None if novo is None else str(novo), motivo, usuario))
                ed += 1
            for nova in novos:
                vals = {c: converter_valor_edicao(t, nova.get(c)) for c, t in cfg["campos"]}
                if all(v is None for v in vals.values()):
                    continue
                faltam = [c for c in obrig if vals[c] is None]
                if faltam:
                    raise ValueError("Linha nova incompleta: preencha " + ", ".join(sorted(faltam)) + ".")
                cs = list(vals)
                cur.execute(f"INSERT INTO {tabela} (importacao_id, {', '.join(cs)}) VALUES (%s, {', '.join(['%s'] * len(cs))}) RETURNING id", (imp_id, *[vals[c] for c in cs]))
                nid = cur.fetchone()[0]
                cur.execute("""INSERT INTO pnl_edicao (importacao_id, tabela, linha_id, campo, valor_depois, acao, motivo, quem) VALUES (%s,%s,%s,'*',%s,'ADICIONOU',%s,%s)""",
                            (imp_id, tabela, nid, _json.dumps({c: (None if v is None else str(v)) for c, v in vals.items()}, ensure_ascii=False), motivo, usuario))
                nv += 1
                if tipo == "ORCAMENTO":
                    orc_tocadas[nid] = None
                    for campo_n in ("orcado", "realizado"):
                        if vals.get(campo_n):
                            chave = (vals["codigo"], vals["mes"], campo_n)
                            orc_deltas[chave] = orc_deltas.get(chave, 0.0) + float(vals[campo_n])
            if nv:
                cur.execute("UPDATE pnl_importacao SET n_linhas = n_linhas + %s WHERE id=%s", (nv, imp_id))
            if tipo == "ORCAMENTO" and (orc_deltas or orc_tocadas):
                auto = _orcamento_recalcular(cur, imp_id, orc_tocadas, orc_deltas, usuario, motivo)
    if ed or nv:
        registrar_log(conn, "IMPORTACAO_EDITADA", "AVISO", usuario, None, {"importacao_id": imp_id, "tipo": tipo, "celulas_editadas": ed, "linhas_novas": nv, "acertos_automaticos": auto})
    return {"editados": ed, "linhas_novas": nv, "automaticos": auto}


def edicoes_lista(conn, imp_id: int | None = None, limite: int = 500) -> list[dict]:
    """Historico de edicoes (mais novas primeiro), de uma importacao ou de todas."""
    if not edicao_instalada(conn):
        return []
    with conn.cursor() as cur:
        cur.execute("""SELECT e.quando, e.quem, e.importacao_id, i.tipo, e.tabela, e.linha_id, e.campo, e.valor_antes, e.valor_depois, e.acao, e.motivo
                       FROM pnl_edicao e LEFT JOIN pnl_importacao i ON i.id=e.importacao_id
                       WHERE (%s IS NULL OR e.importacao_id=%s) ORDER BY e.id DESC LIMIT %s""", (imp_id, imp_id, limite))
        return [dict(zip(["quando", "quem", "importacao_id", "tipo", "tabela", "linha_id", "campo", "antes", "depois", "acao", "motivo"], r)) for r in cur.fetchall()]


def depto_obra_listar(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT empresa, departamento, subnivel_texto, codigo_obra, obra_nome FROM pnl_folha_depto_obra ORDER BY empresa, departamento")
        return [dict(zip(["empresa", "departamento", "subnivel_texto", "codigo_obra", "obra_nome"], r)) for r in cur.fetchall()]


def depto_obra_salvar(conn, linhas: list[dict], usuario: str | None, motivo: str | None = None) -> dict:
    """Cria ou altera o de-para departamento (da folha) -> obra. Nao apaga; cada mudanca fica em pnl_edicao (acao CADASTRO)."""
    novos = alt = 0
    with db.transacao(conn):
        with conn.cursor() as cur:
            for l in linhas:
                emp, dep = (l.get("empresa") or "").strip(), (l.get("departamento") or "").strip()
                cod = (l.get("codigo_obra") or "").strip()
                if not emp and not dep and not cod:
                    continue
                if not (emp and dep and cod):
                    raise ValueError("De-para incompleto: preencha empresa, departamento e código da obra.")
                sub, nome = (l.get("subnivel_texto") or None), (l.get("obra_nome") or None)
                cur.execute("SELECT subnivel_texto, codigo_obra, obra_nome FROM pnl_folha_depto_obra WHERE empresa=%s AND departamento=%s FOR UPDATE", (emp, dep))
                ant = cur.fetchone()
                if ant == (sub, cod, nome):
                    continue
                cur.execute("""INSERT INTO pnl_folha_depto_obra (empresa, departamento, subnivel_texto, codigo_obra, obra_nome) VALUES (%s,%s,%s,%s,%s)
                               ON CONFLICT (empresa, departamento) DO UPDATE SET subnivel_texto=EXCLUDED.subnivel_texto, codigo_obra=EXCLUDED.codigo_obra, obra_nome=EXCLUDED.obra_nome""",
                            (emp, dep, sub, cod, nome))
                cur.execute("""INSERT INTO pnl_edicao (importacao_id, tabela, campo, valor_antes, valor_depois, acao, motivo, quem) VALUES (NULL,'pnl_folha_depto_obra',%s,%s,%s,'CADASTRO',%s,%s)""",
                            (f"{emp}|{dep}", None if ant is None else " | ".join(str(x) for x in ant), " | ".join(str(x) for x in (sub, cod, nome)), motivo, usuario))
                if ant is None:
                    novos += 1
                else:
                    alt += 1
    if novos or alt:
        registrar_log(conn, "DEPARA_DEPTO_OBRA_EDITADO", "AVISO", usuario, None, {"novos": novos, "alterados": alt})
    return {"novos": novos, "alterados": alt}
# v0.16.1: recarga do modulo (serie mensal do orcamento)
