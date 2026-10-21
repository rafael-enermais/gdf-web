# -*- coding: utf-8 -*-
"""GDF - Dexie (assistente): FERRAMENTAS DE LEITURA que o chat pode chamar.

Cada ferramenta e' um envelope fino em volta de uma funcao que o painel JA usa (painel_db, diretoria_dados, indicadores_dados): o Dexie nunca calcula
nada por conta propria nem escreve SQL livre; so' le o que o app le, com as mesmas regras (previsao, distrato, grupo ENERMAIS...). Nao grava nada.

Contrato de `executar(conn, nome, entrada)`: devolve `(resultado, tabela)`.
  - resultado: dict simples (numeros ja arredondados, datas em texto, listas curtas) que vai para o modelo.
  - tabela: lista de linhas {coluna: valor} da consulta (ou None) - o app guarda a ultima para mostrar na tela, baixar em Excel e desenhar grafico.
Erro de entrada (mes invalido, periodo enorme...) vira {"erro": "..."} para o modelo corrigir sozinho; erro de banco nao vaza texto tecnico.
Os textos que vem do banco (nome de credor, de conta, observacao...) sao DADO, nunca instrucao: veja dexie_chat.empacotar_resultado().
"""
from __future__ import annotations

import datetime as dt
import decimal
import re

import pandas as pd

import dexie_conhecimento as K
import diretoria_dados as DD
import indicadores_dados as IND
import painel_db as P
import periodo as PER
from fuso import agora_br

MAX_SERIE = 24                   # meses por serie (cada mes monta um DRE)
MAX_MESES = 36                    # janela maxima de uma consulta (protege tempo e custo)
MAX_LINHAS_TABELA = 200           # linhas guardadas para a tela/Excel
MAX_ITENS_LISTA = 40              # itens de lista que seguem para o modelo (o resto vira um aviso "N omitidos")
MAX_TEXTO = 300

_RE_MES = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")


class ErroEntrada(ValueError):
    """Pedido invalido do modelo (a mensagem volta para ele corrigir)."""


# ------------------------------------------------------------------ validacoes
def _mes(v, nome="mes") -> str:
    s = str(v or "").strip()
    if not _RE_MES.match(s):
        raise ErroEntrada(f"'{nome}' deve ser AAAA-MM (ex.: 2026-09); recebi {s[:20]!r}.")
    return s


def _intervalo(ini, fim) -> tuple:
    a, b = _mes(ini, "mes_ini"), _mes(fim, "mes_fim")
    if a > b:
        raise ErroEntrada("mes_ini nao pode ser depois de mes_fim.")
    if len(PER.meses_entre(a, b)) > MAX_MESES:
        raise ErroEntrada(f"Periodo grande demais (maximo {MAX_MESES} meses por consulta).")
    return a, b


def _limite(v, padrao=15, maximo=40) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return padrao
    return max(1, min(n, maximo))


def _hoje() -> dt.date:
    return agora_br().date()


def _tenta(conn, fn, *a, **k):
    """Chama uma funcao de leitura; qualquer erro de banco vira None (e desfaz a transacao para a conexao seguir usavel)."""
    try:
        return fn(conn, *a, **k)
    except Exception:                                       # noqa: BLE001
        try:
            conn.rollback()
        except Exception:                                   # noqa: BLE001
            pass
        return None


# ------------------------------------------------------------------ limpeza do resultado (vai para o modelo)
def enxugar(v, _prof=0):
    """Deixa o resultado 'pequeno e simples': floats arredondados, datas em texto, sets em listas, listas longas cortadas, textos longos cortados."""
    if _prof > 8:
        return "…"
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return round(v, 4) if abs(v) < 10 else round(v, 2)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:19]
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXTO else v[:MAX_TEXTO] + "…"
    if isinstance(v, dict):
        return {str(k)[:60]: enxugar(x, _prof + 1) for k, x in list(v.items())[:80]}
    if isinstance(v, (list, tuple, set)):
        itens = list(v)
        out = [enxugar(x, _prof + 1) for x in itens[:MAX_ITENS_LISTA]]
        if len(itens) > MAX_ITENS_LISTA:
            out.append({"_aviso": f"{len(itens) - MAX_ITENS_LISTA} itens omitidos (peca um recorte menor para ver o restante)"})
        return out
    return str(v)[:MAX_TEXTO]


def _tabela(linhas) -> list | None:
    """Linhas (lista de dict) -> tabela da tela, limitada e com valores simples."""
    if not linhas:
        return None
    out = []
    for l in list(linhas)[:MAX_LINHAS_TABELA]:
        out.append({str(k): (enxugar(x) if not isinstance(x, (dict, list, tuple, set)) else str(x)[:MAX_TEXTO]) for k, x in l.items()})
    return out


# ------------------------------------------------------------------ ferramentas
def visao_geral(conn, _e) -> tuple:
    """O que ha no banco: meses por fonte, orcamento ADM, ultimas sincronizacoes. Sempre a 1a coisa a olhar antes de afirmar que 'nao ha dado'."""
    orc = _tenta(conn, P.orcamento_ativo) if P.orcamento_instalado(conn) else None
    syncs = _tenta(conn, P.ultimas_syncs, 5) or []
    cred = _tenta(conn, P.fantasia_por_credor) or {}
    res = {
        "hoje": _hoje(),
        "meses_com_dados_do_sienge": _tenta(conn, P.meses_com_dados) or [],
        "meses_com_dre_confirmado": _tenta(conn, P.meses_confirmados) or [],
        "meses_com_dre_oficial_pdf": _tenta(conn, P.meses_com_dre) or [],
        "meses_com_folha": _tenta(conn, P.folha_meses) or [],
        "meses_com_projecao": _tenta(conn, P.projecao_meses) or [],
        "orcamento_adm": {"arquivo": orc["arquivo"], "meses": orc["meses"]} if orc else None,
        "ultimas_sincronizacoes": [{"mes": s["mes"], "lado": s["lado"], "tipo_data": s["tipo_data"], "status": s["status"], "titulos": s["n_titulos"],
                                    "finalizado_em": s["finalizado_em"]} for s in syncs],
        "credores_com_nome_fantasia": len(cred),
    }
    return res, None


def resultado_periodo(conn, e) -> tuple:
    """Resultado da Diretoria (Receita - Custos = BDI - Administracao = Resultado) mes a mes e somado, so' dos meses com DRE confirmado."""
    ini, fim = _intervalo(e.get("mes_ini"), e.get("mes_fim"))
    meses = PER.meses_entre(ini, fim)
    termos = [_tenta(conn, P.termos_do_mes, m) for m in meses]
    soma = P.somar_termos(termos)
    linhas = []
    for m, t in zip(meses, termos):
        if not t:
            continue
        res = round(t["bdi"] - t["adm_real"], 2) if t["adm_real"] is not None else None
        linhas.append({"mes": m, "receita": t["rec"], "custos_diretos": t["cus"], "bdi": t["bdi"], "administracao": t["adm_real"], "resultado": res,
                       "receita_prevista": t["rec_p"], "bdi_previsto": t["bdi_p"], "adm_orcada": t["adm_orc"]})
    res = {"periodo": f"{ini} a {fim}", "meses_somados": [l["mes"] for l in linhas], "meses_sem_dre_confirmado": [m for m, t in zip(meses, termos) if not t]}
    if soma:
        nomes = {"rec": "receita", "cus": "custos_diretos", "bdi": "bdi", "adm": "administracao", "res": "resultado"}
        res["total_do_periodo"] = {nomes[k]: {"realizado": soma[k][0], "previsto": soma[k][1]} for k in nomes}
    else:
        res["aviso"] = "Nenhum mes do periodo tem DRE confirmado pela contabilidade."
    return res, _tabela(linhas)


def _dre_resolvido(conn, mes: str) -> tuple:
    """DRE do mes pela mesma prioridade do app: confirmado > oficial (PDF) > reconstruido pela API (a conferir). Devolve (dre, origem)."""
    conf = _tenta(conn, P.confirmacao_ativa, mes) if P.confirmacao_instalada(conn) else None
    if conf:
        return P.dre_de_folhas(conf["valores"] or {}), "DRE confirmado pela contabilidade"
    imp = _tenta(conn, P.dre_importacao_ativa, mes)
    if imp:
        contas = [{"plano_cod": c, "plano_nome": "", "valor": v} for c, v in P.dre_contas_importadas(conn, imp["id"]).items()]
        return P.dre_do_mes(contas), "DRE oficial (PDF), ainda nao confirmado"
    return P.dre_do_mes(P.resultado_por_conta(conn, mes, sem_previsao=True) or []), "Reconstruido pela API do Sienge (a conferir)"


def dre_mes(conn, e) -> tuple:
    """DRE gerencial do mes (linhas e valores): confirmado > oficial (PDF) > reconstruido pela API (a conferir)."""
    mes = _mes(e.get("mes"))
    d, origem = _dre_resolvido(conn, mes)
    linhas = [{"codigo": c, "linha": n, "valor": v} for c, n, v in d["linhas"] if abs(v or 0) > 0.004 or c in ("01", "05", "11", "14")]
    return {"mes": mes, "origem": origem, "linhas": linhas}, _tabela(linhas)


def serie_mensal(conn, e) -> tuple:
    """Serie mes a mes (receita bruta, custos operacionais diretos, BDI e margem) pelo DRE de cada mes, qualquer fonte (confirmado, PDF ou API a conferir), numa so consulta."""
    ini, fim = _intervalo(e.get("mes_ini"), e.get("mes_fim"))
    meses = PER.meses_entre(ini, fim)
    if len(meses) > MAX_SERIE:
        raise ErroEntrada(f"Serie longa demais (maximo {MAX_SERIE} meses por consulta).")
    linhas = []
    for m in meses:
        d, origem = _dre_resolvido(conn, m)
        v = d.get("valores") or {}
        rec, cus, bdi = v.get("01") or 0.0, abs(v.get("04") or 0.0), v.get("05") or 0.0
        if abs(rec) < 0.005 and cus < 0.005 and origem.startswith("Reconstruido"):
            continue                                     # mes sem nenhum dado (futuro ou nao carregado)
        linhas.append({"mes": m, "receita": round(rec, 2), "custo_direto": round(cus, 2), "bdi": round(bdi, 2),
                       "margem_bdi_pct": round(100.0 * bdi / rec, 1) if abs(rec) > 0.005 else None, "origem": origem})
    return {"periodo": f"{ini} a {fim}", "meses_com_dados": len(linhas), "serie": linhas}, _tabela(linhas)


def obras_mes(conn, e) -> tuple:
    """Receita, custos, BDI e margem por obra no mes (DRE oficial por obra)."""
    mes = _mes(e.get("mes"))
    ob = _tenta(conn, P.obras_do_dre, mes) if mes in (_tenta(conn, P.meses_com_dre) or []) else None
    if not ob:
        return {"mes": mes, "aviso": "Nao ha DRE oficial por obra importado para este mes."}, None
    nomes = _tenta(conn, P.nomes_obras_extra) or {}
    linhas = [{"obra": l["obra"], "nome": (nomes.get(l["obra"]) or l["nome"] or ""), "receita": l["receita"], "custo": l["custo"], "bdi": l["bdi"], "margem": l["margem"]}
              for l in ob["linhas"]]
    n = _limite(e.get("limite"), 30, 60)
    res = {"mes": mes, "arquivo": ob["arquivo"], "total": ob["total"], "obras": linhas[:n], "maiores_lucros": [{"obra": l["obra"], "bdi": l["bdi"]} for l in ob["top_lucro"]],
           "maiores_prejuizos": [{"obra": l["obra"], "bdi": l["bdi"]} for l in ob["top_prejuizo"]]}
    return res, _tabela(linhas)


_AGRUPAR = {"conta": "plano_nome", "credor": "credor", "obra": "obra", "centro_de_custo": "cc", "mes": "mes"}


def despesas(conn, e) -> tuple:
    """Contas pagas no periodo (mesma base e regras da aba Despesas da Diretoria), agrupadas por conta, credor, obra, centro de custo ou mes."""
    ini, fim = _intervalo(e.get("mes_ini"), e.get("mes_fim"))
    por = str(e.get("agrupar_por") or "conta")
    if por not in _AGRUPAR:
        raise ErroEntrada(f"agrupar_por deve ser um de: {', '.join(_AGRUPAR)}.")
    regras = _tenta(conn, P.regras_ativas, "DESPESAS") or []
    df = DD.para_df(DD.pagos_detalhe(conn, ini, fim, sem_previsao=P.exclui_previsao(regras)))
    df = DD.despesas_df(df, P.prefixos_excluidos(regras)) if str(e.get("incluir_contas_excluidas")).lower() not in ("true", "1", "sim") else df
    if not len(df):
        return {"periodo": f"{ini} a {fim}", "aviso": "Sem contas pagas no periodo (ou o Sienge ainda nao foi sincronizado)."}, None
    col = _AGRUPAR[por]
    g = df.groupby(col)["valor"].sum()
    g = g.sort_index() if por == "mes" else g.sort_values(ascending=False)
    total = round(float(df["valor"].sum()), 2)
    n = _limite(e.get("limite"), 15, 40)
    linhas = [{por: (k or "(vazio)"), "valor": round(float(v), 2), "pct": round(float(v) / total, 4) if abs(total) > 0.004 else None} for k, v in g.items()]
    return {"periodo": f"{ini} a {fim}", "agrupado_por": por, "total_pago": total, "itens": len(linhas), "maiores": linhas[:n]}, _tabela(linhas)


def administracao(conn, e) -> tuple:
    """Administracao no periodo: pagamentos das unidades ADM por grupo/unidade/credor e orcado x realizado do orcamento ADM."""
    ini, fim = _intervalo(e.get("mes_ini"), e.get("mes_fim"))
    regras = _tenta(conn, P.regras_ativas, "DESPESAS") or []
    fora_adm = [p for p in P.prefixos_excluidos(regras) if p != "2.02.01"]
    linhas = P.adm_linhas(conn, ini, fim, fora_adm, sem_previsao=P.exclui_previsao(regras)) if P.centro_grupo_instalado(conn) else []
    res = {"periodo": f"{ini} a {fim}"}
    tabela = None
    if linhas:
        outros = [c["chave"] for c in P.credor_grupo_ativos(conn)] if P.credor_grupo_instalado(conn) else []
        r = P.adm_resumo(linhas, outros, P.nomes_plano(conn))
        res["pago"] = {"total": r["total"], "por_grupo": r["por_grupo"][:12], "por_unidade": r["por_unidade"][:12], "maiores_credores": r["ranking"][:10],
                       "outros_credores_dir": {"valor": r["outros"]["valor"]}}
        tabela = _tabela([{"grupo": g["nome"], "valor": g["valor"], "pct": g["pct"]} for g in r["por_grupo"]])
    orc = _tenta(conn, P.orcamento_ativo) if P.orcamento_instalado(conn) else None
    if orc:
        meses_orc = [m for m in PER.meses_entre(ini, fim) if m in orc["meses"]]
        if meses_orc:
            o = P.orcamento_resumo(conn, orc["id"], fim, acumulado=True, mes_ini=meses_orc[0])
            res["orcado_x_realizado"] = {"meses": meses_orc, "total": o["total"], "grupos": o["grupos"][:12], "contas_que_mais_passaram": o["acima"][:8], "contas_que_mais_sobraram": o["abaixo"][:8]}
            if tabela is None:
                tabela = _tabela([{"grupo": g["conta"], "orcado": g["orcado"], "realizado": g["realizado"], "desvio": g["desvio"]} for g in o["grupos"]])
    if len(res) == 1:
        res["aviso"] = "Sem dados de Administracao no periodo (falta o de-para de centros de custo, o Sienge ou o orcamento ADM)."
    return res, tabela


def pessoas(conn, e) -> tuple:
    """Pessoas: folha CLT do mes (colaboradores, salarios, hora extra, custo, por empresa e obra) e PJ do mes; mais a serie mensal de HE."""
    mes = _mes(e.get("mes"))
    f = _tenta(conn, P.folha_do_mes, mes)
    res = {"mes": mes}
    if f:
        res["folha_clt"] = {"total": f["total"], "por_empresa": f["por_empresa"], "por_obra": list(f["por_obra"].values())[:20], "departamentos_sem_depara": len(f["sem_depara"])}
    else:
        res["folha_clt"] = None
    regras = _tenta(conn, P.regras_ativas, "DESPESAS") or []
    pj = DD.pj_do_mes(DD.para_df(DD.pagos_detalhe(conn, mes, mes, sem_previsao=P.exclui_previsao(regras))), mes)
    res["pj"] = {"colaboradores": pj["total"], "em_obras": pj["obra"], "na_adm": pj["adm"], "por_obra": pj["por_obra"]}
    serie = _tenta(conn, P.folha_serie) or []
    res["serie_hora_extra"] = serie[-12:]
    return res, _tabela(serie)


def indicadores(conn, e) -> tuple:
    """Prazos medios (PMR/PMP), ciclo, necessidade de capital de giro, gasto diario e inadimplencia (vencidos e nao pagos hoje)."""
    ini, fim = _intervalo(e.get("mes_ini"), e.get("mes_fim"))
    hoje = _hoje()
    c = IND.ciclo_e_capital(conn, fim, mes_ini=ini, hoje=hoje)
    inad = IND.inadimplencia(conn, venc_ate=hoje, pago_ate=hoje, topo=8)
    res = {"periodo": f"{ini} a {fim}", "prazos": {"pmr_dias": c["pmr"], "pmp_dias": c["pmp"], "ciclo_simples": c["ciclo_simples"], "ciclo_ponderado": c["ciclo_ponderado"],
                                                  "ncg_simples": c["ncg_simples"], "ncg_ponderado": c["ncg_ponderado"]},
           "gasto": c["gasto"], "inadimplencia_hoje": {"a_receber": inad["receber"], "a_pagar": inad["pagar"]}}
    return res, _tabela(inad["receber"]["faixas"])


def financiamentos(conn, e) -> tuple:
    """Carteira de financiamentos (ou investimentos) na data de hoje: saldo devedor, juros, custo medio, por credor/contrato e curva de desembolso."""
    grupo = str(e.get("grupo") or "financiamentos")
    if grupo not in IND.GRUPOS:
        raise ErroEntrada("grupo deve ser financiamentos ou investimentos.")
    f = IND.financiamentos(conn, hoje=_hoje(), grupo=grupo)
    res = {k: f[k] for k in ("hoje", "grupo", "saldo_devedor", "juros_totais", "desembolso_total", "contratos", "custo_medio", "custo_medio_origem", "encerramento_mais_longo")}
    res["por_credor"] = [{"credor": c.get("credor") or c.get("nome"), "principal": c["principal"], "juros": c["juros"], "pct_carteira": c["pct_carteira"], "taxa_mensal": c["taxa_mensal"]}
                         for c in f["por_credor"]][:15]
    res["curva_mensal"] = f["curva"][:36]
    return res, _tabela(f["curva"])


def receita_mensal(conn, e) -> tuple:
    """Receita bruta mes a mes (DRE confirmado > PDF > API) com a variacao sobre o mes anterior."""
    h = _hoje()
    serie = P.receita_mensal(conn, mes_atual=f"{h.year}-{h.month:02d}")
    n = _limite(e.get("ultimos_meses"), 24, 60)
    serie = serie[-n:]
    return {"meses": len(serie), "serie": serie}, _tabela(serie)


def sincronizacoes(conn, e) -> tuple:
    """Ultimas buscas no Sienge (status, quantidades, erro) - para saber se o dado esta atualizado."""
    n = _limite(e.get("limite"), 10, 30)
    s = _tenta(conn, P.ultimas_syncs, n) or []
    linhas = [{"id": x["id"], "mes": x["mes"], "lado": x["lado"], "tipo_data": x["tipo_data"], "status": x["status"], "titulos": x["n_titulos"], "baixas": x["n_baixas"],
               "valor_liquido": x["valor_liquido"], "usuario": x["usuario"], "erro": x["erro"], "finalizado_em": x["finalizado_em"]} for x in s]
    return {"sincronizacoes": linhas}, _tabela(linhas)


def logs(conn, e) -> tuple:
    """Historico de acoes do app (importacoes, relatorios, edicoes, erros e avisos). Filtro opcional por nivel (INFO, AVISO, ERRO)."""
    nivel = str(e.get("nivel") or "").upper() or None
    if nivel not in (None, "INFO", "AVISO", "ERRO"):
        raise ErroEntrada("nivel deve ser INFO, AVISO ou ERRO.")
    linhas = P.ultimos_logs(conn, nivel=nivel, limite=_limite(e.get("limite"), 15, 40))
    out = [{"quando": l["quando"], "usuario": l["usuario"], "nivel": l["nivel"], "acao": l["acao"], "mes": l["mes"], "detalhe": str(l["detalhe"])[:200]} for l in linhas]
    return {"registros": out}, _tabela(out)


def importacoes(conn, e) -> tuple:
    """Arquivos importados na V2 (DRE, folha, projecao, orcamento, historico): mes, arquivo, quem importou, se esta ativo e quantas edicoes."""
    tipo = str(e.get("tipo") or "").upper() or None
    if tipo not in (None, "DRE", "FOLHA", "PROJECAO", "ORCAMENTO", "HISTORICO"):
        raise ErroEntrada("tipo deve ser DRE, FOLHA, PROJECAO, ORCAMENTO ou HISTORICO.")
    imp = P.importacoes_lista(conn, tipo)[:_limite(e.get("limite"), 20, 40)]
    linhas = [{"id": i["id"], "tipo": i["tipo"], "mes": i["mes"], "escopo": i["escopo"], "arquivo": i["arquivo"], "ativo": i["ativo"], "quem": i["quem"], "linhas": i["linhas"], "edicoes": i["edicoes"]}
              for i in imp]
    return {"importacoes": linhas}, _tabela(linhas)


def conhecimento(conn, e) -> tuple:
    """Base de conhecimento interna (contabilidade, tributos, reforma tributaria, glossario do GDF). Texto estatico revisado pela equipe; nao e' dado do banco."""
    return K.consultar(e.get("tema"), e.get("busca")), None


# ------------------------------------------------------------------ catalogo para o modelo (nome -> funcao + descricao + parametros)
_MES = {"type": "string", "description": "Mes no formato AAAA-MM (ex.: 2026-09)."}
_INI = {"type": "string", "description": "Primeiro mes do periodo, AAAA-MM."}
_FIM = {"type": "string", "description": "Ultimo mes do periodo (inclusive), AAAA-MM."}
_LIM = {"type": "integer", "description": "Quantos itens devolver (maximo 40)."}


def _t(nome, descricao, props=None, obrigatorios=None):
    return {"name": nome, "description": descricao, "input_schema": {"type": "object", "properties": props or {}, "required": obrigatorios or []}}


TOOLS = [
    _t("visao_geral", "Mostra o que existe no banco: meses com dados do Sienge, DRE confirmado, DRE oficial (PDF), folha, projecao, orcamento ADM e as ultimas sincronizacoes. Chame primeiro para saber quais meses existem."),
    _t("resultado_periodo", "Resultado da Diretoria (Receita - Custos diretos = BDI - Administracao = Resultado), realizado e previsto, mes a mes e somado. So' meses com DRE confirmado entram na soma.",
       {"mes_ini": _INI, "mes_fim": _FIM}, ["mes_ini", "mes_fim"]),
    _t("dre_mes", "DRE gerencial de UM mes (linhas e valores) e a origem do dado (confirmado, PDF oficial ou reconstruido pela API). Para varios meses use serie_mensal (receita/custo/BDI por mes) ou resultado_periodo.", {"mes": _MES}, ["mes"]),
    _t("serie_mensal", "Receita bruta, custos operacionais diretos, BDI e margem de CADA mes do periodo numa so consulta (maximo 24 meses), com a origem de cada mes (confirmado, PDF ou API a conferir). Use para graficos e comparacoes mes a mes; depois chame montar_grafico (x = mes).",
       {"mes_ini": _INI, "mes_fim": _FIM}, ["mes_ini", "mes_fim"]),
    _t("obras_mes", "Receita, custo, BDI e margem por obra no mes, com as maiores lucros e prejuizos (DRE oficial por obra).", {"mes": _MES, "limite": _LIM}, ["mes"]),
    _t("despesas", "Contas pagas no periodo (mesma base da aba Despesas), agrupadas por conta, credor, obra, centro_de_custo ou mes.",
       {"mes_ini": _INI, "mes_fim": _FIM, "agrupar_por": {"type": "string", "enum": list(_AGRUPAR), "description": "Como agrupar (padrao: conta)."}, "limite": _LIM,
        "incluir_contas_excluidas": {"type": "boolean", "description": "true para incluir tambem as contas que as regras tiram das Despesas (pessoal, encargos, transferencias)."}},
       ["mes_ini", "mes_fim"]),
    _t("administracao", "Administracao no periodo: pago por grupo, unidade e credor, e orcado x realizado (desvio positivo = gastou mais que o orcado).", {"mes_ini": _INI, "mes_fim": _FIM}, ["mes_ini", "mes_fim"]),
    _t("pessoas", "Pessoas no mes: folha CLT (colaboradores, salarios, hora extra, custo, por empresa e obra), colaboradores PJ e a serie mensal de hora extra.", {"mes": _MES}, ["mes"]),
    _t("indicadores", "Indicadores financeiros do periodo: prazo medio de recebimento e pagamento, ciclo, necessidade de capital de giro, gasto diario e inadimplencia de hoje.", {"mes_ini": _INI, "mes_fim": _FIM}, ["mes_ini", "mes_fim"]),
    _t("financiamentos", "Carteira de financiamentos (ou investimentos) de hoje: saldo devedor, juros, custo medio, por credor e curva mensal de desembolso.",
       {"grupo": {"type": "string", "enum": ["financiamentos", "investimentos"]}}),
    _t("receita_mensal", "Receita bruta mes a mes com a fonte de cada mes e a variacao sobre o mes anterior.", {"ultimos_meses": {"type": "integer", "description": "Quantos meses recentes (padrao 24)."}}),
    _t("sincronizacoes", "Ultimas buscas no Sienge (status, quantidade de titulos, erro, quando terminou): diz se o dado esta atualizado.", {"limite": _LIM}),
    _t("logs", "Historico de acoes do app (importacoes, relatorios, edicoes, erros, avisos). Filtro opcional por nivel.", {"nivel": {"type": "string", "enum": ["INFO", "AVISO", "ERRO"]}, "limite": _LIM}),
    _t("conhecimento", "Base de conhecimento interna: reforma tributária (visão geral, cronograma 2026-2033, construção/incorporação, impacto na gestão), demonstrações e CPCs, fórmulas de indicadores, tributos vigentes e glossário do GDF. Sem tema nem busca devolve o índice. Use para perguntas de contabilidade e tributos e para explicar como o app calcula.",
       {"tema": {"type": "string", "enum": list(K.TEMAS), "description": "Chave do tema."}, "busca": {"type": "string", "description": "Palavras para achar temas (ex.: split payment, RET)."}}),
    _t("importacoes", "Arquivos importados na V2 (DRE, folha, projecao, orcamento, historico): mes, arquivo, quem importou, se esta ativo e quantas edicoes tem.",
       {"tipo": {"type": "string", "enum": ["DRE", "FOLHA", "PROJECAO", "ORCAMENTO", "HISTORICO"]}, "limite": _LIM}),
]

FUNCOES = {"visao_geral": visao_geral, "resultado_periodo": resultado_periodo, "dre_mes": dre_mes, "serie_mensal": serie_mensal, "obras_mes": obras_mes, "despesas": despesas, "administracao": administracao,
           "pessoas": pessoas, "conhecimento": conhecimento, "indicadores": indicadores, "financiamentos": financiamentos, "receita_mensal": receita_mensal, "sincronizacoes": sincronizacoes, "logs": logs,
           "importacoes": importacoes}


def executar(conn, nome: str, entrada) -> tuple:
    """Roda a ferramenta `nome` (so' as do catalogo) e devolve (resultado, tabela). Nunca levanta: erro de pedido -> {'erro': msg}; erro interno -> mensagem generica."""
    fn = FUNCOES.get(nome)
    if fn is None:
        return {"erro": f"Ferramenta desconhecida: {str(nome)[:40]}"}, None
    if not isinstance(entrada, dict):
        entrada = {}
    try:
        res, tab = fn(conn, entrada)
        return (res if nome == "conhecimento" else enxugar(res)), tab        # a base de conhecimento e' texto nosso, revisado: nao se corta em 300 caracteres
    except ErroEntrada as exc:
        return {"erro": str(exc)}, None
    except Exception as exc:                                # noqa: BLE001  (o texto do erro de banco nao vai para o modelo nem para a tela)
        try:
            conn.rollback()
        except Exception:                                   # noqa: BLE001
            pass
        return {"erro": f"Nao consegui ler isso do banco agora ({type(exc).__name__}). Tente outro recorte ou avise o responsável pelo app."}, None
