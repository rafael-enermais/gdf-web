# -*- coding: utf-8 -*-
"""
GDF - acesso ao banco (schema `gdf`, role gdf_app). Funcoes puras sobre uma conexao psycopg2.
Regras: nada e' apagado (ativo=false; "Desfazer" reativa); a role do app nao tem DELETE.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

from psycopg2.extras import execute_values

import motor


class ImportacaoDuplicada(Exception):
    """O mesmo arquivo (mesmo hash) ja foi importado para esta empresa."""

    def __init__(self, importacao_id: int, ativo: bool):
        super().__init__(f"Arquivo já importado (importação #{importacao_id}{'' if ativo else ', hoje inativa'}).")
        self.importacao_id, self.ativo = importacao_id, ativo


class PeriodoJaImportado(Exception):
    """Ja existe importacao ATIVA para o mesmo periodo (e o arquivo e' outro): precisa confirmar a substituicao."""

    def __init__(self, importacao_id: int):
        super().__init__(f"Já existe a importação #{importacao_id} ativa para este período.")
        self.importacao_id = importacao_id


@contextmanager
def transacao(conn):
    """Transacao atomica (a conexao do app e' autocommit; aqui liga a transacao e devolve o estado)."""
    antes = conn.autocommit
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = antes


# ---------------------------------------------------------------- empresas e mapa
def garantir_empresa(conn, codigo: str, razao_social: str, cnpj: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM empresa WHERE cnpj = %s", (cnpj,))
        r = cur.fetchone()
        if r:
            return r[0]
        cur.execute("INSERT INTO empresa (codigo, razao_social, cnpj) VALUES (%s,%s,%s) RETURNING id", (codigo, razao_social, cnpj))
        return cur.fetchone()[0]


def empresa_por_cnpj(conn, cnpj: str):
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo, razao_social, cnpj FROM empresa WHERE cnpj = %s AND ativo", (cnpj,))
        r = cur.fetchone()
    return dict(zip(("id", "codigo", "razao_social", "cnpj"), r)) if r else None


def listar_empresas(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo, razao_social, cnpj FROM empresa WHERE ativo ORDER BY codigo")
        return [dict(zip(("id", "codigo", "razao_social", "cnpj"), r)) for r in cur.fetchall()]


def garantir_mapa(conn, empresa_id: int, usuario: str | None = None) -> bool:
    """Se a empresa nao tem mapa ativo, grava o mapa padrao (v1.0 da Anastacio). Retorna True se gravou."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM mapa_conta WHERE empresa_id = %s AND ativo LIMIT 1", (empresa_id,))
        if cur.fetchone():
            return False
        execute_values(cur, "INSERT INTO mapa_conta (empresa_id, chave, rotulo, secao, prefixos, natureza, alterado_por, motivo) VALUES %s",
                       [(empresa_id, k, rot, sec, pref, nat, usuario, "mapa padrão v1.0") for k, rot, sec, pref, nat in motor.MAPA_PADRAO])
    return True


def mapa_vigente(conn, empresa_id: int):
    """Mapa ativo da empresa como lista de tuplas do motor; sem mapa gravado -> mapa padrao."""
    with conn.cursor() as cur:
        cur.execute("SELECT chave, rotulo, secao, prefixos, natureza FROM mapa_conta WHERE empresa_id = %s AND ativo ORDER BY id", (empresa_id,))
        rows = cur.fetchall()
    return [(k, r, s, list(p), n) for k, r, s, p, n in rows] if rows else list(motor.MAPA_PADRAO)


# ---------------------------------------------------------------- importacoes
def inserir_importacao(conn, empresa_id: int, cab: dict, contas: list, usuario: str, conferencias: list | None = None,
                       status: str = "RASCUNHO", substituir: bool = False) -> int:
    """Grava a importacao + linhas + conferencias numa transacao. `cab` vem de importador_csv.ler_bytes.
    - mesmo hash ja existente -> ImportacaoDuplicada
    - mesmo periodo ja ativo (outro arquivo) -> PeriodoJaImportado, a menos que substituir=True (a anterior fica inativa)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, ativo FROM importacao WHERE empresa_id = %s AND arquivo_sha256 = %s", (empresa_id, cab["sha256"]))
        r = cur.fetchone()
        if r:
            raise ImportacaoDuplicada(r[0], r[1])
        cur.execute("SELECT id FROM importacao WHERE empresa_id=%s AND tipo=%s AND periodo_ini=%s AND periodo_fim=%s AND ativo",
                    (empresa_id, cab["tipo"], cab["ini"], cab["fim"]))
        ativa = cur.fetchone()
    if ativa and not substituir:
        raise PeriodoJaImportado(ativa[0])
    with transacao(conn):
        with conn.cursor() as cur:
            if ativa:
                cur.execute("UPDATE importacao SET ativo = false WHERE id = %s", (ativa[0],))
                _evento(cur, empresa_id, "importar", "info", f"Importação #{ativa[0]} substituída por um novo arquivo do mesmo período", usuario, {"substituida": ativa[0]})
            cur.execute(
                "INSERT INTO importacao (empresa_id, tipo, periodo_ini, periodo_fim, arquivo_nome, arquivo_sha256, status, importado_por, n_contas) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (empresa_id, cab["tipo"], cab["ini"], cab["fim"], cab["arquivo"], cab["sha256"], status, usuario, len(contas)))
            imp_id = cur.fetchone()[0]
            execute_values(cur, "INSERT INTO balancete_linha (importacao_id, conta_id, classificacao, nome, sintetica, saldo_anterior, debito, credito, saldo_final) VALUES %s",
                           [(imp_id, c["id"], c["cl"], c["nome"], c["sint"], c["ant"], c["deb"], c["cred"], c["sal"]) for c in contas], page_size=500)
            if conferencias:
                execute_values(cur, "INSERT INTO conferencia (importacao_id, grupo, descricao, ok, detalhe) VALUES %s",
                               [(imp_id, c["grupo"], c["descricao"], c["ok"], c.get("detalhe") or "") for c in conferencias])
            nfalhas = sum(1 for c in (conferencias or []) if not c["ok"])
            _evento(cur, empresa_id, "importar", "aviso" if nfalhas else "info",
                    f"Importado {cab['arquivo']} ({cab['tipo']} {cab['periodo']}, {len(contas)} contas, {nfalhas} conferência(s) com falha)",
                    usuario, {"importacao_id": imp_id, "sha256": cab["sha256"]})
    return imp_id


def listar_importacoes(conn, empresa_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT i.id, i.tipo, i.periodo_ini, i.periodo_fim, i.arquivo_nome, i.status, i.ativo, i.importado_por, i.importado_em, i.n_contas, "
            "COALESCE(SUM((NOT c.ok)::int),0) AS falhas "
            "FROM importacao i LEFT JOIN conferencia c ON c.importacao_id = i.id "
            "WHERE i.empresa_id = %s GROUP BY i.id ORDER BY i.periodo_fim DESC, i.id DESC", (empresa_id,))
        cols = ("id", "tipo", "periodo_ini", "periodo_fim", "arquivo_nome", "status", "ativo", "importado_por", "importado_em", "n_contas", "falhas")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def definir_ativo(conn, importacao_id: int, ativo: bool, usuario: str) -> None:
    """Desfazer (ativo=False) ou reativar. Reativar falha se ja houver outra ativa no mesmo periodo."""
    with conn.cursor() as cur:
        cur.execute("SELECT empresa_id, tipo, periodo_ini, periodo_fim, ativo FROM importacao WHERE id = %s", (importacao_id,))
        r = cur.fetchone()
        if not r:
            raise ValueError("Importação não encontrada.")
        emp, tipo, ini, fim, atual = r
        if ativo and not atual:
            cur.execute("SELECT id FROM importacao WHERE empresa_id=%s AND tipo=%s AND periodo_ini=%s AND periodo_fim=%s AND ativo AND id<>%s",
                        (emp, tipo, ini, fim, importacao_id))
            outra = cur.fetchone()
            if outra:
                raise PeriodoJaImportado(outra[0])
        cur.execute("UPDATE importacao SET ativo = %s WHERE id = %s", (ativo, importacao_id))
        _evento(cur, emp, "historico", "info", f"Importação #{importacao_id} {'reativada' if ativo else 'desfeita (inativa)'}", usuario, {"importacao_id": importacao_id})


def definir_status(conn, importacao_id: int, status: str, usuario: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE importacao SET status = %s WHERE id = %s RETURNING empresa_id", (status, importacao_id))
        r = cur.fetchone()
        if r:
            _evento(cur, r[0], "historico", "info", f"Importação #{importacao_id} marcada como {status}", usuario, {"importacao_id": importacao_id})


def carregar_contas(conn, importacao_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT conta_id, sintetica, classificacao, nome, saldo_anterior, debito, credito, saldo_final FROM balancete_linha WHERE importacao_id = %s ORDER BY id", (importacao_id,))
        return [{"id": a, "sint": b, "cl": c, "nome": d, "ant": float(e), "deb": float(f), "cred": float(g), "sal": float(h)} for a, b, c, d, e, f, g, h in cur.fetchall()]


def _periodos(conn, empresa_id: int, tipo: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT id, periodo_fim FROM importacao WHERE empresa_id=%s AND tipo=%s AND ativo ORDER BY periodo_fim", (empresa_id, tipo))
        ims = cur.fetchall()
    return {f"{fim.year}-{fim.month:02d}": carregar_contas(conn, i) for i, fim in ims}


def periodos_mensais_ativos(conn, empresa_id: int) -> dict:
    """{'AAAA-MM': contas} das importacoes MENSAL ativas."""
    return _periodos(conn, empresa_id, "MENSAL")


def acumulados_ativos(conn, empresa_id: int) -> dict:
    """{'AAAA-MM' (ultimo mes): contas} das importacoes ACUMULADO ativas."""
    return _periodos(conn, empresa_id, "ACUMULADO")


def listar_meses_ativos(conn, empresa_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT periodo_fim FROM importacao WHERE empresa_id=%s AND tipo='MENSAL' AND ativo ORDER BY periodo_fim", (empresa_id,))
        return [f"{r[0].year}-{r[0].month:02d}" for r in cur.fetchall()]


def conferencias_da_importacao(conn, importacao_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT grupo, descricao, ok, detalhe FROM conferencia WHERE importacao_id = %s ORDER BY id", (importacao_id,))
        return [{"grupo": g, "periodo": "", "descricao": d, "ok": o, "detalhe": t or ""} for g, d, o, t in cur.fetchall()]


# ---------------------------------------------------------------- log
def _evento(cur, empresa_id, origem, nivel, mensagem, usuario, detalhe=None):
    cur.execute("INSERT INTO evento (empresa_id, origem, nivel, mensagem, detalhe, usuario) VALUES (%s,%s,%s,%s,%s,%s)",
                (empresa_id, origem, nivel, mensagem, json.dumps(detalhe or {}), usuario))


def registrar_evento(conn, origem: str, nivel: str, mensagem: str, empresa_id=None, usuario=None, detalhe=None) -> None:
    """Log de melhor esforco: nunca levanta excecao."""
    try:
        with conn.cursor() as cur:
            _evento(cur, empresa_id, origem, nivel, mensagem, usuario, detalhe)
    except Exception:
        pass


def listar_eventos(conn, empresa_id: int | None = None, limite: int = 200) -> list:
    with conn.cursor() as cur:
        if empresa_id is None:
            cur.execute("SELECT criado_em, nivel, origem, mensagem, usuario FROM evento ORDER BY id DESC LIMIT %s", (limite,))
        else:
            cur.execute("SELECT criado_em, nivel, origem, mensagem, usuario FROM evento WHERE empresa_id = %s OR empresa_id IS NULL ORDER BY id DESC LIMIT %s", (empresa_id, limite))
        return [dict(zip(("criado_em", "nivel", "origem", "mensagem", "usuario"), r)) for r in cur.fetchall()]
