# -*- coding: utf-8 -*-
"""GDF - Dexie: ANOTACOES ("o que ela aprendeu"), tabela gdf.dexie_aprendizado (SQL-33).

Como a Dexie "aprende com o uso" sem se perder nem ser enganada:
  * ela so' SUGERE (ferramenta propor_aprendizado -> cartao na tela); a anotacao so' passa a valer depois do clique de um editor;
  * o que vale e' TEXTO de regra, definicao ou conhecimento (ex.: "juros 2.03.02 ficam em Financiamentos"), nunca numero de periodo, dado pessoal, senha ou link;
  * o texto volta ao modelo como DADO (envelope <dados_do_banco>), nunca como instrucao; nao autoriza acao nem muda regra de seguranca;
  * nada se apaga: editar cria versao nova e a anterior fica 'desativado'; qualquer editor pode desativar uma anotacao errada na tela.
Se o SQL-33 ainda nao foi rodado, tudo aqui vira no-op (a tela avisa) e a Dexie segue normal. Nunca derruba a tela."""
from __future__ import annotations

import re
import unicodedata

TIPOS = ("regra", "definicao", "conhecimento")
MAX_TITULO, MAX_TEXTO, MAX_FONTE = 100, 1000, 160
MAX_ATIVAS_NO_PROMPT = 30            # titulos que seguem no prompt (o texto completo so' sai pela ferramenta `aprendizados`)

_RE_OCULTO = re.compile("[​-‏‪-‮⁠-⁤﻿︀-️\U000E0000-\U000E007F-\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RE_LINK = re.compile(r"(https?://|www\.|javascript:|data:)\S*|!\[[^\]]*\]\([^)]*\)", re.I)
_PROIBIDO = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "CPF"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "CNPJ"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "e-mail"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|postgres(ql)?://\S+|eyJ[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{10,})", re.I), "chave/senha/endereco de banco"),
    (re.compile(r"\b(senha|password|token|api[_ -]?key)\b\s*[:=]", re.I), "senha/chave"),
    (re.compile(r"\bR\$\s*\d"), "valor em reais (anotacao e' regra, nao numero de periodo)"),
]


class ErroAnotacao(ValueError):
    """Anotacao recusada (a mensagem explica o motivo e volta para a pessoa/modelo)."""


def _limpa(s, maximo: int) -> str:
    t = unicodedata.normalize("NFC", str(s or ""))
    t = _RE_OCULTO.sub("", t)
    t = _RE_LINK.sub("[link removido]", t)
    t = re.sub(r"<[^>]{0,200}>", "", t)                       # nada de tag/html (inclui a tag de fechamento do envelope de dados)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()[:maximo]


def validar(tipo, titulo, texto, fonte=None) -> dict:
    """Limpa e confere a anotacao. Levanta ErroAnotacao se estiver fora das regras."""
    tipo = str(tipo or "").strip().lower()
    if tipo not in TIPOS:
        raise ErroAnotacao(f"tipo deve ser um destes: {', '.join(TIPOS)}.")
    t, x, f = _limpa(titulo, MAX_TITULO), _limpa(texto, MAX_TEXTO), _limpa(fonte, MAX_FONTE)
    if len(t) < 4 or len(x) < 15:
        raise ErroAnotacao("Titulo (min. 4 letras) e texto (min. 15 letras) sao obrigatorios.")
    for padrao, rotulo in _PROIBIDO:
        if padrao.search(t) or padrao.search(x) or padrao.search(f):
            raise ErroAnotacao(f"Nao guardo {rotulo} em anotacao; escreva so' a regra ou definicao, sem dados.")
    return {"tipo": tipo, "titulo": t, "texto": x, "fonte": f or None}


def _desfaz(conn):
    try:
        conn.rollback()
    except Exception:                                       # noqa: BLE001
        pass


def instalado(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('gdf.dexie_aprendizado') IS NOT NULL")
            return bool(cur.fetchone()[0])
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return False


_COLS = "id, tipo, titulo, texto, fonte, status, origem, criado_por, to_char(criado_em AT TIME ZONE 'America/Sao_Paulo','DD/MM/YYYY'), revisado_por, motivo, substitui_id"
_CHAVES = ("id", "tipo", "titulo", "texto", "fonte", "status", "origem", "criado_por", "criado_em", "revisado_por", "motivo", "substitui_id")


def listar(conn, status: str | None = "ativo", limite: int = 200) -> list:
    """Anotacoes (mais recentes primeiro). status None = todas. Lista vazia se o SQL-33 nao existe."""
    if not instalado(conn):
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM dexie_aprendizado WHERE (%s::text IS NULL OR status = %s) ORDER BY id DESC LIMIT %s", (status, status, int(limite)))
            return [dict(zip(_CHAVES, r)) for r in cur.fetchall()]
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return []


def guardar(conn, usuario: str, tipo, titulo, texto, fonte=None, origem: str = "pessoa", substitui_id: int | None = None) -> dict:
    """Guarda a anotacao como ATIVA (quem chama e' um editor que acabou de confirmar). Devolve a linha. Levanta ErroAnotacao se invalida ou sem o SQL-33."""
    a = validar(tipo, titulo, texto, fonte)
    if origem not in ("dexie", "pessoa"):
        raise ErroAnotacao("origem invalida.")
    if not usuario or not instalado(conn):
        raise ErroAnotacao("O banco ainda nao tem a tabela de anotacoes (SQL-33) ou nao sei quem esta guardando.")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM dexie_aprendizado WHERE status='ativo' AND lower(titulo)=lower(%s)", (a["titulo"],))
            if cur.fetchone()[0] and not substitui_id:
                raise ErroAnotacao("Ja existe uma anotacao ativa com este titulo; edite a existente ou use outro titulo.")
            cur.execute(f"""INSERT INTO dexie_aprendizado (tipo, titulo, texto, fonte, origem, criado_por, substitui_id) VALUES (%s,%s,%s,%s,%s,%s,%s)
                            RETURNING {_COLS}""", (a["tipo"], a["titulo"], a["texto"], a["fonte"], origem, usuario.strip().lower(), substitui_id))
            return dict(zip(_CHAVES, cur.fetchone()))
    except ErroAnotacao:
        raise
    except Exception as exc:                                # noqa: BLE001
        _desfaz(conn)
        raise ErroAnotacao("Nao consegui guardar agora; tente de novo ou avise o responsavel pelo app.") from exc


def desativar(conn, usuario: str, anotacao_id: int, motivo: str = "") -> bool:
    """Marca como desativada (some do uso; fica guardada). True se mudou algo."""
    if not usuario or not instalado(conn):
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE dexie_aprendizado SET status='desativado', revisado_por=%s, revisado_em=now(), motivo=%s WHERE id=%s AND status='ativo'",
                        (usuario.strip().lower(), _limpa(motivo, 200) or None, int(anotacao_id)))
            return cur.rowcount > 0
    except Exception:                                       # noqa: BLE001
        _desfaz(conn)
        return False


def editar(conn, usuario: str, anotacao_id: int, tipo, titulo, texto, fonte=None) -> dict:
    """Versao nova ATIVA no lugar da anterior (que fica 'desativado', com o motivo 'substituida')."""
    a = validar(tipo, titulo, texto, fonte)
    if not usuario or not instalado(conn):
        raise ErroAnotacao("O banco ainda nao tem a tabela de anotacoes (SQL-33).")
    if not desativar(conn, usuario, anotacao_id, f"substituida por nova versao ({a['titulo'][:40]})"):
        raise ErroAnotacao("Essa anotacao nao esta mais ativa.")
    return guardar(conn, usuario, a["tipo"], a["titulo"], a["texto"], a["fonte"], origem="pessoa", substitui_id=int(anotacao_id))


def reativar(conn, usuario: str, anotacao_id: int) -> dict:
    """Volta uma anotacao DESATIVADA a valer (nada e' apagado). Recusa se ja existe ativa com o mesmo titulo ou se uma versao mais nova a substituiu."""
    if not usuario or not instalado(conn):
        raise ErroAnotacao("O banco ainda nao tem a tabela de anotacoes (SQL-33) ou nao sei quem esta reativando.")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT titulo FROM dexie_aprendizado WHERE id=%s AND status='desativado'", (int(anotacao_id),))
            linha = cur.fetchone()
            if not linha:
                raise ErroAnotacao("Essa anotacao nao esta desativada.")
            cur.execute("SELECT count(*) FROM dexie_aprendizado WHERE status='ativo' AND lower(titulo)=lower(%s)", (linha[0],))
            if cur.fetchone()[0]:
                raise ErroAnotacao("Ja existe uma anotacao ativa com este titulo; edite a ativa em vez de reativar esta.")
            cur.execute("SELECT count(*) FROM dexie_aprendizado WHERE status='ativo' AND substitui_id=%s", (int(anotacao_id),))
            if cur.fetchone()[0]:
                raise ErroAnotacao("Esta versao foi substituida por uma mais nova que esta ativa; edite a nova.")
            cur.execute(f"UPDATE dexie_aprendizado SET status='ativo', revisado_por=%s, revisado_em=now(), motivo='reativada na tela' WHERE id=%s RETURNING {_COLS}",
                        (usuario.strip().lower(), int(anotacao_id)))
            return dict(zip(_CHAVES, cur.fetchone()))
    except ErroAnotacao:
        raise
    except Exception as exc:                                # noqa: BLE001
        _desfaz(conn)
        raise ErroAnotacao("Nao consegui reativar agora; tente de novo ou avise o responsavel pelo app.") from exc


def titulos_para_o_prompt(conn) -> list:
    """Ate MAX_ATIVAS_NO_PROMPT titulos ativos [{'titulo','tipo'}] (so' o titulo vai ao prompt; o texto vem pela ferramenta)."""
    return [{"titulo": a["titulo"], "tipo": a["tipo"]} for a in listar(conn, "ativo", MAX_ATIVAS_NO_PROMPT)]
