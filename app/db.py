# -*- coding: utf-8 -*-
"""
GDF - acesso ao banco (schema `gdf`, role gdf_app). Funcoes puras sobre uma conexao psycopg2.
Regras: nada e' apagado (ativo=false; "Desfazer" reativa); a role do app nao tem DELETE.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager, nullcontext

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
    # Se a conexao tem trava (ConexaoGDF), segura-a durante TODA a transacao: outras sessoes esperam, em vez de se misturarem nela.
    trava = getattr(conn, "trava", None) or nullcontext()
    with trava:
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
    """Uma unica consulta (antes eram 1 + N, uma por mes): {'AAAA-MM': contas} das importacoes ativas do tipo."""
    with conn.cursor() as cur:
        cur.execute("SELECT i.id, i.periodo_fim, l.conta_id, l.sintetica, l.classificacao, l.nome, l.saldo_anterior, l.debito, l.credito, l.saldo_final "
                    "FROM importacao i JOIN balancete_linha l ON l.importacao_id = i.id "
                    "WHERE i.empresa_id=%s AND i.tipo=%s AND i.ativo ORDER BY i.periodo_fim, i.id, l.id", (empresa_id, tipo))
        linhas = cur.fetchall()
    out: dict = {}
    for _iid, fim, a, b, c, d, e, f, g, h in linhas:
        out.setdefault(f"{fim.year}-{fim.month:02d}", []).append(
            {"id": a, "sint": b, "cl": c, "nome": d, "ant": float(e), "deb": float(f), "cred": float(g), "sal": float(h)})
    return out


def periodos_mensais_ativos(conn, empresa_id: int) -> dict:
    """{'AAAA-MM': contas} das importacoes MENSAL ativas."""
    return _periodos(conn, empresa_id, "MENSAL")


def acumulados_ativos(conn, empresa_id: int) -> dict:
    """{'AAAA-MM' (ultimo mes): contas} das importacoes ACUMULADO ativas."""
    return _periodos(conn, empresa_id, "ACUMULADO")


def ids_importacoes_mensais(conn, empresa_id: int, ate: str) -> list:
    """Ids (ordenados) das importacoes MENSAL ativas de janeiro ate' o mes `ate` ('AAAA-MM') do mesmo ano.
    Serve para o relatorio saber quais dados usou e avisar quando eles mudarem depois."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM importacao WHERE empresa_id=%s AND tipo='MENSAL' AND ativo AND periodo_fim >= %s AND periodo_fim <= "
                    "(date_trunc('month', %s::date) + interval '1 month - 1 day')::date ORDER BY id",
                    (empresa_id, f"{ate[:4]}-01-01", f"{ate}-01"))
        return [r[0] for r in cur.fetchall()]


def listar_meses_ativos(conn, empresa_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT periodo_fim FROM importacao WHERE empresa_id=%s AND tipo='MENSAL' AND ativo ORDER BY periodo_fim", (empresa_id,))
        return [f"{r[0].year}-{r[0].month:02d}" for r in cur.fetchall()]


def conferencias_da_importacao(conn, importacao_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT grupo, descricao, ok, detalhe FROM conferencia WHERE importacao_id = %s ORDER BY id", (importacao_id,))
        return [{"grupo": g, "periodo": "", "descricao": d, "ok": o, "detalhe": t or ""} for g, d, o, t in cur.fetchall()]


# ---------------------------------------------------------------- mapa de contas (edicao = nova linha; a anterior fica inativa)
class MapaInvalido(Exception):
    """Alteracao de mapa recusada (mensagem em linguagem simples)."""


_PREFIXO = re.compile(r"^\d(\.\d+)*$")


def salvar_mapa_linha(conn, empresa_id: int, chave: str, rotulo: str, prefixos: list, natureza, usuario: str, motivo: str) -> None:
    """Troca a linha ATIVA da chave por uma nova (a antiga fica inativa, com historico). Exige motivo."""
    rotulo = (rotulo or "").strip()
    prefixos = [p.strip() for p in (prefixos or []) if p and p.strip()]
    motivo = (motivo or "").strip()
    if not motivo:
        raise MapaInvalido("Informe o motivo da alteração (fica registrado no histórico).")
    if not rotulo:
        raise MapaInvalido("O nome da linha do demonstrativo não pode ficar vazio.")
    if not prefixos:
        raise MapaInvalido("Informe ao menos um prefixo de conta (ex.: 1.1.01.002).")
    ruins = [p for p in prefixos if not _PREFIXO.match(p)]
    if ruins:
        raise MapaInvalido("Prefixo inválido: " + ", ".join(ruins) + ". Use só números separados por ponto (ex.: 2.4.01.001).")
    with conn.cursor() as cur:
        cur.execute("SELECT id, secao, rotulo, prefixos, natureza FROM mapa_conta WHERE empresa_id=%s AND chave=%s AND ativo", (empresa_id, chave))
        atual = cur.fetchone()
    if not atual:
        raise MapaInvalido("Essa chave não existe no mapa da empresa.")
    _, secao, rot0, pref0, nat0 = atual
    if secao == "DRE" and natureza not in ("D", "C"):
        raise MapaInvalido("Para linhas da DRE informe a natureza: despesa/custo ou receita.")
    nat = natureza if secao == "DRE" else None
    if rotulo == rot0 and list(pref0) == prefixos and nat == nat0:
        raise MapaInvalido("Nada mudou em relação ao mapa atual.")
    with transacao(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE mapa_conta SET ativo=false WHERE id=%s", (atual[0],))
            cur.execute("INSERT INTO mapa_conta (empresa_id, chave, rotulo, secao, prefixos, natureza, alterado_por, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (empresa_id, chave, rotulo, secao, prefixos, nat, usuario, motivo))
            _evento(cur, empresa_id, "mapa", "info", f"Mapa de contas: linha '{chave}' alterada — {motivo}", usuario,
                    {"chave": chave, "antes": {"rotulo": rot0, "prefixos": list(pref0), "natureza": nat0}, "depois": {"rotulo": rotulo, "prefixos": prefixos, "natureza": nat}})


def historico_mapa(conn, empresa_id: int, limite: int = 200) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT chave, rotulo, secao, prefixos, natureza, ativo, alterado_por, alterado_em, motivo FROM mapa_conta "
                    "WHERE empresa_id=%s ORDER BY id DESC LIMIT %s", (empresa_id, limite))
        cols = ("chave", "rotulo", "secao", "prefixos", "natureza", "ativo", "alterado_por", "alterado_em", "motivo")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------- apelidos (Composicao de Saldos)
def listar_apelidos(conn, empresa_id: int) -> dict:
    """{nome_original em minusculas: apelido} dos apelidos ativos."""
    with conn.cursor() as cur:
        cur.execute("SELECT nome_original, apelido FROM apelido WHERE empresa_id=%s AND ativo", (empresa_id,))
        return {n.lower(): a for n, a in cur.fetchall()}


def salvar_apelidos(conn, empresa_id: int, mudancas: dict, usuario: str) -> int:
    """mudancas: {nome_original: apelido}. Apelido vazio (ou igual ao nome) desativa o apelido. O antigo fica inativo. Retorna quantos mudaram."""
    n = 0
    with transacao(conn):
        with conn.cursor() as cur:
            for nome, ap in mudancas.items():
                nome, ap = " ".join((nome or "").split()), " ".join((ap or "").split())
                if not nome:
                    continue
                cur.execute("SELECT id, apelido FROM apelido WHERE empresa_id=%s AND lower(nome_original)=lower(%s) AND ativo", (empresa_id, nome))
                ant = cur.fetchone()
                novo = ap if ap and ap != nome else ""
                if (ant[1] if ant else "") == novo:
                    continue
                if ant:
                    cur.execute("UPDATE apelido SET ativo=false WHERE id=%s", (ant[0],))
                if novo:
                    cur.execute("INSERT INTO apelido (empresa_id, nome_original, apelido, alterado_por) VALUES (%s,%s,%s,%s)", (empresa_id, nome, novo, usuario))
                n += 1
            if n:
                _evento(cur, empresa_id, "composicao", "info", f"{n} apelido(s) da Composição de Saldos atualizado(s)", usuario)
    return n


# ---------------------------------------------------------------- relatorio PDF
def config_empresa(conn, empresa_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT config FROM empresa WHERE id=%s", (empresa_id,))
        r = cur.fetchone()
    return dict(r[0]) if r and r[0] else {}


def salvar_config_empresa(conn, empresa_id: int, novos: dict, usuario: str) -> None:
    """Mescla chaves em empresa.config (ex.: assinantes)."""
    cfg = config_empresa(conn, empresa_id)
    cfg.update(novos)
    with conn.cursor() as cur:
        cur.execute("UPDATE empresa SET config=%s::jsonb WHERE id=%s", (json.dumps(cfg), empresa_id))
        _evento(cur, empresa_id, "relatorio", "info", "Configuração do relatório da empresa atualizada (" + ", ".join(novos) + ")", usuario)


def proxima_versao_relatorio(conn, empresa_id: int, periodo) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(versao),0)+1 FROM relatorio WHERE empresa_id=%s AND periodo=%s", (empresa_id, periodo))
        return cur.fetchone()[0]


def registrar_relatorio(conn, empresa_id: int, periodo, pdf_sha256: str, textos: dict, assinantes: list, usuario: str, meta: dict | None = None,
                        status: str = "RASCUNHO", versao: int | None = None) -> tuple:
    """Grava um relatorio gerado (nova versao do periodo; nunca regrava uma linha existente). status: RASCUNHO ou REVISADO (versao final,
    sem a marca de rascunho). `versao`: a mesma usada na legenda do PDF (a restricao UNIQUE barra duas pessoas gerando juntas). Retorna (id, versao)."""
    if status not in ("RASCUNHO", "REVISADO"):
        raise ValueError("Status inválido para um relatório recém-gerado.")
    with transacao(conn):
        with conn.cursor() as cur:
            v = versao or proxima_versao_relatorio(conn, empresa_id, periodo)
            corpo = dict(textos)
            if meta:
                corpo["_meta"] = meta
            cur.execute("INSERT INTO relatorio (empresa_id, periodo, versao, status, pdf_sha256, textos, assinantes, gerado_por) "
                        "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) RETURNING id",
                        (empresa_id, periodo, v, status, pdf_sha256, json.dumps(corpo), json.dumps(assinantes), usuario))
            rid = cur.fetchone()[0]
            _evento(cur, empresa_id, "relatorio", "info", f"Relatório {periodo:%m/%Y} v{v} gerado ({status})", usuario, {"relatorio_id": rid, "sha256": pdf_sha256})
    return rid, v


def listar_relatorios(conn, empresa_id: int, periodo=None) -> list:
    sql = "SELECT id, periodo, versao, status, pdf_sha256, gerado_por, gerado_em, COALESCE(textos->'_meta','{}'::jsonb) FROM relatorio WHERE empresa_id=%s"
    par = [empresa_id]
    if periodo:
        sql += " AND periodo=%s"; par.append(periodo)
    with conn.cursor() as cur:
        cur.execute(sql + " ORDER BY periodo DESC, versao DESC", par)
        cols = ("id", "periodo", "versao", "status", "pdf_sha256", "gerado_por", "gerado_em", "meta")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def definir_status_relatorio(conn, relatorio_id: int, status: str, usuario: str) -> None:
    """RASCUNHO <-> REVISADO. Relatorio ASSINADO nunca e' alterado (gerar nova versao)."""
    if status not in ("RASCUNHO", "REVISADO"):
        raise ValueError("Status inválido (a assinatura é feita fora do GDF nesta versão).")
    with conn.cursor() as cur:
        cur.execute("SELECT empresa_id, status, periodo, versao FROM relatorio WHERE id=%s", (relatorio_id,))
        r = cur.fetchone()
        if not r:
            raise ValueError("Relatório não encontrado.")
        if r[1] == "ASSINADO":
            raise ValueError("Relatório assinado não pode ser alterado; gere uma nova versão.")
        cur.execute("UPDATE relatorio SET status=%s WHERE id=%s", (status, relatorio_id))
        _evento(cur, r[0], "relatorio", "info", f"Relatório {r[2]:%m/%Y} v{r[3]} marcado como {status}", usuario, {"relatorio_id": relatorio_id})


class AssinaturaInvalida(Exception):
    """O arquivo enviado nao serve como registro de assinatura (mensagem em linguagem simples)."""


def registrar_assinatura(conn, relatorio_id: int, nome_arquivo: str, sha256_assinado: str, usuario: str) -> None:
    """Fecha o ciclo: o relatorio REVISADO foi assinado fora do GDF (Autentique). Guarda so' o nome e o hash do PDF assinado (o arquivo nao e' guardado
    nem alterado) e muda o status para ASSINADO. Dali em diante a linha nao muda mais; correcao = nova versao."""
    with transacao(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT empresa_id, status, periodo, versao, pdf_sha256 FROM relatorio WHERE id=%s FOR UPDATE", (relatorio_id,))
            r = cur.fetchone()
            if not r:
                raise AssinaturaInvalida("Relatório não encontrado.")
            if r[1] == "ASSINADO":
                raise AssinaturaInvalida("Este relatório já está registrado como assinado.")
            if r[1] != "REVISADO":
                raise AssinaturaInvalida("Só uma versão final (REVISADO) pode ser registrada como assinada. Gere a versão final primeiro.")
            if sha256_assinado == r[4]:
                raise AssinaturaInvalida("Este arquivo é idêntico ao PDF gerado pelo GDF, ou seja, ainda não tem assinatura. Envie o PDF que voltou do Autentique.")
            info = {"arquivo": nome_arquivo, "sha256": sha256_assinado, "por": usuario}
            cur.execute("UPDATE relatorio SET status='ASSINADO', textos = jsonb_set(textos, '{_assinatura}', %s::jsonb, true) WHERE id=%s", (json.dumps(info), relatorio_id))
            _evento(cur, r[0], "relatorio", "info", f"Relatório {r[2]:%m/%Y} v{r[3]} registrado como ASSINADO ({nome_arquivo})", usuario,
                    {"relatorio_id": relatorio_id, "sha256_assinado": sha256_assinado})


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
