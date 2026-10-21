# -*- coding: utf-8 -*-
"""GDF - Dexie (assistente): ACOES com confirmacao.

O modelo so' PROPOE uma acao (ferramenta `propor_acao`); quem executa e' o botao "Confirmar e executar" da tela, clicado por uma pessoa.
Por isso: (1) so' existem 2 tipos de acao, ambas as mesmas que ja existem na aba "Sincronizar com o Sienge" do Painel EnerMais;
(2) os parametros sao REVALIDADOS aqui (nao se confia no que o modelo mandou, nem no que ficou guardado na tela);
(3) cada execucao grava uma linha no historico (pnl_log, acao DEXIE_ACAO) com quem pediu e o resultado;
(4) o Sienge e' so' CONSULTADO (leitura); as escritas vao apenas ao schema gdf.
Nada aqui apaga dados. Texto vindo do banco nunca entra em parametro de acao: so' meses AAAA-MM e tipos fixos.
"""
from __future__ import annotations

import re

import painel_db as P
import periodo as PER
import sienge_api as S
from fuso import agora_br

TIPOS = ("sincronizar_sienge", "atualizar_cadastros")
MAX_MESES_SYNC = 24
_RE_MES = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")
TIPOS_DATA = ("P", "I", "D")


class ErroAcao(ValueError):
    """Pedido de acao invalido (a mensagem volta para o modelo ou aparece na tela)."""


def _mes(v, nome) -> str:
    s = str(v or "").strip()
    if not _RE_MES.match(s):
        raise ErroAcao(f"'{nome}' deve ser AAAA-MM (ex.: 2026-09).")
    return s


def validar(tipo, params) -> dict:
    """Valida e NORMALIZA o pedido. Devolve {'tipo', ...parametros limpos}; levanta ErroAcao se algo nao estiver nas regras."""
    if tipo not in TIPOS:
        raise ErroAcao(f"Tipo de acao nao permitido. Use um destes: {', '.join(TIPOS)}.")
    params = params if isinstance(params, dict) else {}
    if tipo == "atualizar_cadastros":
        return {"tipo": tipo}
    hoje = agora_br().date()
    atual = f"{hoje.year}-{hoje.month:02d}"
    ini, fim = _mes(params.get("mes_ini"), "mes_ini"), _mes(params.get("mes_fim") or params.get("mes_ini"), "mes_fim")
    if ini > fim:
        raise ErroAcao("mes_ini nao pode ser depois de mes_fim.")
    if fim > atual:
        raise ErroAcao("Nao da para buscar meses futuros: mes_fim deve ser no maximo o mes atual.")
    if len(PER.meses_entre(ini, fim)) > MAX_MESES_SYNC:
        raise ErroAcao(f"Janela grande demais (maximo {MAX_MESES_SYNC} meses por busca).")
    tipos = params.get("tipos")
    tipos = ["P", "I"] if tipos is None else tipos
    if not isinstance(tipos, (list, tuple)) or not tipos or any(t not in TIPOS_DATA for t in tipos):
        raise ErroAcao("tipos deve usar so' P (pagamento), I (emissao) e/ou D (vencimento).")
    tipos = [t for t in TIPOS_DATA if t in tipos]
    banco = params.get("incluir_movimento_bancario")
    banco = True if banco is None else (str(banco).lower() in ("true", "1", "sim"))
    return {"tipo": tipo, "mes_ini": ini, "mes_fim": fim, "tipos": tipos, "incluir_movimento_bancario": banco}


def descrever(acao: dict) -> str:
    """Texto em linguagem simples para o cartao de aprovacao."""
    if acao["tipo"] == "atualizar_cadastros":
        return ("Atualizar os cadastros a partir do Sienge: empresas, centros de custo, plano de contas, nomes das obras e nomes fantasia dos credores. "
                "Só consulta o Sienge e grava no banco do GDF; não apaga nada.")
    nomes = {"P": "pagamento/recebimento", "I": "emissão", "D": "vencimento"}
    extra = " e o movimento bancário (juros, tarifas)" if acao["incluir_movimento_bancario"] else ""
    return (f"Buscar no Sienge as contas a pagar e a receber de {PER.rot(acao['mes_ini'])} a {PER.rot(acao['mes_fim'])} "
            f"(datas de {', '.join(nomes[t] for t in acao['tipos'])}){extra}. Pode levar de 1 a 3 minutos. Só consulta o Sienge e grava no banco do GDF; não apaga nada.")


def executar(conn, acao: dict, usuario: str | None, secrets=None, cliente=None) -> dict:
    """Executa a acao JA validada (revalida mesmo assim). Devolve {'ok': bool, 'mensagens': [(nivel, texto)]}; nunca levanta para a tela.
    `cliente` existe para os testes injetarem um Sienge falso; em producao nasce das credenciais (secrets)."""
    try:
        acao = validar(acao.get("tipo"), acao)
    except ErroAcao as exc:
        return {"ok": False, "mensagens": [("erro", str(exc))]}
    msgs: list = []
    P.registrar_log(conn, "DEXIE_ACAO", "INFO", usuario, acao.get("mes_ini"), {"etapa": "iniciada", **{k: v for k, v in acao.items() if k != "tipo"}, "acao": acao["tipo"]})
    try:
        cli = cliente or S.Cliente(*S.credenciais(secrets))
        if acao["tipo"] == "atualizar_cadastros":
            ok = _cadastros(conn, cli, msgs)
        else:
            ok = _sincronizar(conn, cli, acao, usuario, msgs)
    except S.ErroSienge as exc:
        msgs.append(("erro", str(exc)))
        ok = False
    except Exception as exc:                                    # noqa: BLE001  (o texto tecnico nao vai para a tela)
        msgs.append(("erro", f"A ação parou por um erro inesperado ({type(exc).__name__}). Nada foi apagado; confira o Histórico e logs."))
        ok = False
    P.registrar_log(conn, "DEXIE_ACAO", "INFO" if ok else "ERRO", usuario, acao.get("mes_ini"),
                    {"etapa": "concluida" if ok else "com_erro", "acao": acao["tipo"], "resumo": [t for _, t in msgs][:6]})
    return {"ok": ok, "mensagens": msgs}


def _sincronizar(conn, cli, acao, usuario, msgs) -> bool:
    ini, fim = acao["mes_ini"], acao["mes_fim"]
    res = P.sincronizar_mes(conn, cli, ini, usuario, tipos=tuple(acao["tipos"]), mes_fim=fim)
    ok = bool(res)
    for r in res:
        lado = "a pagar" if r["lado"] == "P" else "a receber"
        if r["ok"]:
            msgs.append(("ok", f"{lado} · data {r['tipo']}: {r['titulos']} títulos, {r['baixas']} baixas, {r['rateios']} rateios."))
        else:
            ok = False
            msgs.append(("erro", f"{lado} · data {r['tipo']}: {r['erro']}"))
    if acao["incluir_movimento_bancario"]:
        rb = P.sincronizar_banco(conn, cli, ini, usuario, mes_fim=fim)
        if rb["ok"]:
            msgs.append(("ok", f"movimento bancário: {rb['titulos']} lançamentos sem título, {rb['rateios']} rateios."))
        else:
            ok = False
            msgs.append(("erro", f"movimento bancário: {rb['erro']}"))
    return ok


def _cadastros(conn, cli, msgs) -> bool:
    cont = P.gravar_cadastros(conn, S.normalizar_cadastros(S.buscar_cadastros(cli)))
    msgs.append(("ok", "Cadastros atualizados: " + ", ".join(f"{k} {v}" for k, v in cont.items()) + "."))
    # obras e credores: falha aqui nao desfaz o que ja foi atualizado (mesmo comportamento da aba Sincronizar)
    for rotulo, buscar, normalizar, gravar, chave in (("obras", S.buscar_obras, S.normalizar_obras, P.gravar_obras_sienge, "obras"),
                                                      ("credores (nome fantasia)", S.buscar_credores, S.normalizar_credores, P.gravar_credores_sienge, "credores")):
        try:
            r = gravar(conn, normalizar(buscar(cli)))
            if "erro" in r:
                msgs.append(("aviso", str(r["erro"])))
            else:
                msgs.append(("ok", f"{rotulo.capitalize()} do Sienge atualizados: {r[chave]}."))
        except S.ErroSienge as exc:
            msgs.append(("aviso", f"Não consegui ler {rotulo} do Sienge (o restante foi atualizado): {exc}"))
    return True
