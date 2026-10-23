# -*- coding: utf-8 -*-
"""GDF - registro mensal das metricas do painel de metas (contrato do ENERDATA, metricas.md secao 4).

Em linguagem simples: todo mes o app CALCULA os indicadores que sao dele e GRAVA o resultado numa tabela so' para isso
(`gdf.metrica_registro`, SQL-34), uma linha por indicador e mes. O painel de metas (e, no futuro, o app que mostra o indicador) so' LE essa tabela,
sem refazer a conta. Assim o numero e' calculado uma unica vez e fica guardado mes a mes (o historico nao muda quando o Sienge muda).

Regras que valem aqui:
  * Status pelo % de atingimento: No alvo >= 100, Atencao de 50 a 99, Fora da meta < 50, Sem lancamento (sem valor).
  * Regra ZERO ("0 em atraso"): 100% se nao ha nada vencido; proporcional ao total (1 - vencido/total) quando ha; 0% se ha falha e nao ha total.
  * Linha com origem 'manual' (alguem corrigiu a mao) NUNCA e' sobrescrita por um novo calculo automatico.
  * Toda mudanca de um valor ja gravado deixa rastro em `metrica_registro_hist` (campo, valor anterior e novo, motivo, quem). So' cresce (sem DELETE).
  * Nada de nome de pessoa ou de credor no registro (o repositorio e' publico e o painel e' compartilhado): so' valores e contagens.

Cada indicador e' uma funcao `calcular_<ID>(conn, mes, hoje)` que devolve uma lista de linhas (dicts com os campos da tabela); para somar um novo
indicador basta escreve-la e inclui-la em `CALCULADORES`.
"""
from __future__ import annotations

import datetime as dt
import json

import indicadores_dados as ID
import painel_db as P
from fuso import agora_br

APP_ORIGEM = "GDF"
STATUS = ("No alvo", "Atenção", "Fora da meta", "Sem lançamento")
CAMPOS_VALOR = ("meta", "previsto", "realizado", "numerador", "denominador", "pct_atingimento", "status", "origem", "detalhe")
CAMPOS_NUM = ("previsto", "realizado", "numerador", "denominador", "pct_atingimento")
DIMENSOES = ("empresa", "obra", "un")
# Campo `pessoa` do registro: o repositorio e' publico, entao guarda a AREA do dono (nao o nome). O painel de metas resolve o nome pelo item (matriz do ENERDATA).
DONOS = {"I03": "Gerência (resultado)", "I22": "Financeiro (receber)", "I27": "Financeiro (pagar)"}


# ---------------------------------------------------------------- regras puras (sem banco)
def status_por_pct(pct: float | None) -> str:
    """Status do % de atingimento (regra validada pelo Rafael em 22/10/2026): >=100 No alvo; 50 a 99 Atencao; <50 Fora da meta; sem valor = Sem lancamento."""
    if pct is None:
        return "Sem lançamento"
    if pct >= 100:
        return "No alvo"
    if pct >= 50:
        return "Atenção"
    return "Fora da meta"


def pct_zero(falhas: float | None, total: float | None) -> float | None:
    """Regra ZERO: a meta e' 'zero falhas'. Sem falha = 100%. Com falha, % = 1 - falhas/total (nunca abaixo de 0). Com falha e sem total (ou total <= 0) = 0%.
    `falhas` None = ainda sem dado = None (sem lancamento)."""
    if falhas is None:
        return None
    if falhas <= 0:
        return 100.0
    if total is None or total <= 0:
        return 0.0
    return round(max(0.0, 100.0 * (1.0 - falhas / total)), 1)


def razao_pct(numerador: float | None, denominador: float | None) -> float | None:
    """numerador / denominador em %, 1 casa; None se nao da' para dividir (denominador vazio ou zero)."""
    if numerador is None or denominador is None or abs(denominador) < 0.005:
        return None
    return round(100.0 * numerador / denominador, 1)


def _r2(v) -> float | None:
    return None if v is None else round(float(v), 2)


def _linha(item_id: str, periodo: str, pessoa: str, **campos) -> dict:
    """Linha completa do registro, com os padroes da tabela (dimensoes vazias, origem 'medido', status pelo %)."""
    out = {"item_id": item_id, "periodo": periodo, "pessoa": pessoa, "empresa": "", "obra": "", "un": "", "app_origem": APP_ORIGEM,
           "meta": None, "previsto": None, "realizado": None, "numerador": None, "denominador": None, "pct_atingimento": None,
           "status": None, "origem": "medido", "detalhe": None}
    out.update(campos)
    if out["status"] is None:
        out["status"] = status_por_pct(out["pct_atingimento"])
    return out


def _json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=str)


# ---------------------------------------------------------------- posicao de cada mes
def posicao_do_mes(mes: str, hoje: dt.date | None = None) -> tuple:
    """(venc_ate, pago_ate, ao_vivo): mes ainda em andamento = 'ao vivo' (vence ate ontem, pago ate hoje); mes fechado = fim do mes. Mes futuro nao existe."""
    hoje = hoje or agora_br().date()
    atual = f"{hoje.year}-{hoje.month:02d}"
    if mes > atual:
        raise ValueError(f"O mês {mes} ainda não começou: não há o que registrar.")
    ao_vivo = mes == atual
    venc_ate, pago_ate = ID.data_posicao(mes, hoje, ate_hoje=ao_vivo)
    return venc_ate, pago_ate, ao_vivo


# ---------------------------------------------------------------- I03 margem de contribuicao
def _tenta(conn, fn, *a):
    """Chama uma leitura; qualquer erro de banco vira None (e desfaz a transacao para a conexao seguir usavel)."""
    try:
        return fn(conn, *a)
    except Exception:                                               # noqa: BLE001
        try:
            conn.rollback()
        except Exception:                                           # noqa: BLE001
            pass
        return None


def _termos_mes(conn, mes: str) -> dict | None:
    """Receita e BDI do mes (e os previstos, quando ha projecao) como o app calcula (painel_db.termos_do_mes): DRE confirmado > oficial (PDF) > API do
    Sienge (padrao). BDI = receita - custos diretos. None se o mes nao tem dado."""
    t = _tenta(conn, P.termos_do_mes, mes)
    if not t:
        return None
    nomes = {"confirmado": "DRE confirmado pela contabilidade", "pdf": "DRE oficial (PDF): mes anterior a API", "api": "API do Sienge (padrao, a conferir)"}
    return {"rec": t["rec"], "bdi": t["bdi"], "rec_p": t["rec_p"], "bdi_p": t["bdi_p"], "fonte": nomes.get(t["fonte"], t["fonte"])}


def calcular_I03(conn, mes: str, hoje: dt.date | None = None) -> list:
    """I03 Margem de contribuicao % = BDI / receita (confirmado em 22/10/2026). Realizado = %; previsto = % da projecao (quando existe);
    % de atingimento = realizado / previsto. Sem previsto o status fica 'Sem lancamento' (nao ha referencia numerica no app) e o valor aparece mesmo assim."""
    t = _termos_mes(conn, mes)
    if not t:
        return [_linha("I03", mes, DONOS["I03"], meta="Budget (sem referência numérica no app)", detalhe="Sem DRE para o mês: nada a calcular.")]
    real = razao_pct(t["bdi"], t["rec"])
    prev = razao_pct(t["bdi_p"], t["rec_p"])
    ating = razao_pct(real, prev) if real is not None and prev not in (None, 0) else None
    det = f"MC % = BDI ÷ receita. Fonte: {t['fonte']}. Tela: Painel da Diretoria > Resultado."
    return [_linha("I03", mes, DONOS["I03"], meta="Budget (previsto da projeção)" if prev is not None else "Budget (sem referência numérica no app)",
                   previsto=prev, realizado=real, numerador=_r2(t["bdi"]), denominador=_r2(t["rec"]), pct_atingimento=ating, detalhe=det)]


# ---------------------------------------------------------------- I22 contas a receber e I27 contas a pagar
def _faixas_json(lista: list) -> list:
    """Faixas de atraso do slide (1-30, 31-60, 61-90, mais de 90 dias), as mesmas FAIXAS da tela, so' com contagem e valor."""
    return [{"faixa": f["faixa"], "n": f["n"], "valor": f["valor"]} for f in lista]


def calcular_I22(conn, mes: str, hoje: dt.date | None = None) -> list:
    """I22 Contas a receber : carteira = vencido + a vencer; realizado = vencido; faixas de atraso e prazo medio no detalhe.
    Informativo (a referencia do slide e' 'Contas a receber', sem meta numerica): o status fica 'Sem lancamento' e o % de atingimento vazio."""
    venc_ate, pago_ate, ao_vivo = posicao_do_mes(mes, hoje)
    inad = ID.inadimplencia(conn, venc_ate, pago_ate)["receber"]
    fut = ID.a_vencer(conn, venc_ate, pago_ate, 30)["receber"]
    carteira = round(inad["total"] + fut["total"], 2)
    pm = ID.prazo_medio(conn, "R", mes)
    det = {"posicao": "ao vivo (até hoje)" if ao_vivo else "fim do mês", "venc_ate": venc_ate.isoformat(), "n_vencidos": inad["n"],
           "a_vencer_total": fut["total"], "a_vencer_30d": fut["proximos"], "faixas": _faixas_json(inad["faixas"]),
           "prazo_medio_dias": pm.get("ponderado"), "tela": "Indicadores financeiros > Inadimplência"}
    return [_linha("I22", mes, DONOS["I22"], meta="Informativo (sem meta numérica)", realizado=inad["total"], numerador=inad["total"],
                   denominador=carteira, detalhe=_json(det))]


def calcular_I27(conn, mes: str, hoje: dt.date | None = None) -> list:
    """I27 Contas a pagar : meta 'vencidos = 0' (regra ZERO sobre o valor: 100% sem vencido; senao 1 - vencido/total a pagar).
    Realizado = vencido (R$); denominador = total em aberto (vencido + a vencer); a vencer em 30 dias, contagens e faixas no detalhe."""
    venc_ate, pago_ate, ao_vivo = posicao_do_mes(mes, hoje)
    inad = ID.inadimplencia(conn, venc_ate, pago_ate)["pagar"]
    fut = ID.a_vencer(conn, venc_ate, pago_ate, 30)["pagar"]
    total = round(inad["total"] + fut["total"], 2)
    det = {"posicao": "ao vivo (até hoje)" if ao_vivo else "fim do mês", "venc_ate": venc_ate.isoformat(), "n_vencidos": inad["n"],
           "a_vencer_total": fut["total"], "a_vencer_30d": fut["proximos"], "n_a_vencer_30d": fut["n_proximos"],
           "faixas": _faixas_json(inad["faixas"]), "tela": "Indicadores financeiros > Inadimplência"}
    return [_linha("I27", mes, DONOS["I27"], meta="Vencidos = 0", previsto=0.0, realizado=inad["total"], numerador=inad["total"], denominador=total,
                   pct_atingimento=pct_zero(inad["total"], total), detalhe=_json(det))]


CALCULADORES = {"I03": calcular_I03, "I22": calcular_I22, "I27": calcular_I27}


def calcular_mes(conn, mes: str, hoje: dt.date | None = None, itens: list | None = None) -> tuple:
    """Calcula (sem gravar) os indicadores do mes. Devolve (linhas, erros): um indicador que falha nao derruba os outros (erro em texto simples)."""
    linhas, erros = [], {}
    for item in itens or list(CALCULADORES):
        try:
            linhas.extend(CALCULADORES[item](conn, mes, hoje))
        except Exception as exc:                                    # noqa: BLE001 - mostra o motivo e segue com os demais
            erros[item] = str(exc)
    return linhas, erros


# ---------------------------------------------------------------- gravacao (upsert com historico)
_CHAVE = ("item_id", "periodo", "empresa", "obra", "un", "app_origem")


def _igual(campo: str, a, b) -> bool:
    if campo in CAMPOS_NUM:
        if a is None or b is None:
            return a is None and b is None
        return abs(float(a) - float(b)) < 0.005
    return (a or None) == (b or None)


def _txt(v) -> str | None:
    return None if v is None else str(v)


def gravar_registro(conn, linhas: list, usuario: str, motivo: str = "Recálculo automático do mês") -> dict:
    """Grava as linhas no `metrica_registro`: nova = INSERT; existente com valor diferente = UPDATE + 1 linha de historico por campo que mudou;
    existente igual = nada; existente com origem 'manual' = preservada (o calculo automatico nao passa por cima). Devolve contagens e a lista do que mudou."""
    res = {"novas": 0, "atualizadas": 0, "iguais": 0, "preservadas_manual": 0, "mudancas": []}
    cols = ", ".join(CAMPOS_VALOR)
    with conn.cursor() as cur:
        for ln in linhas:
            cur.execute(f"SELECT id, {cols} FROM metrica_registro WHERE item_id=%s AND periodo=%s AND empresa=%s AND obra=%s AND un=%s AND app_origem=%s",
                        tuple(ln[c] for c in _CHAVE))
            ex = cur.fetchone()
            if ex is None:
                cur.execute(f"""INSERT INTO metrica_registro (item_id, periodo, pessoa, empresa, obra, un, app_origem, {cols}, atualizado_por)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,{', '.join(['%s'] * len(CAMPOS_VALOR))},%s)""",
                            (ln["item_id"], ln["periodo"], ln["pessoa"], ln["empresa"], ln["obra"], ln["un"], ln["app_origem"],
                             *[ln[c] for c in CAMPOS_VALOR], usuario))
                res["novas"] += 1
                continue
            reg_id, atual = ex[0], dict(zip(CAMPOS_VALOR, ex[1:]))
            if atual["origem"] == "manual" and ln["origem"] != "manual":
                res["preservadas_manual"] += 1
                continue
            mudou = [c for c in CAMPOS_VALOR if not _igual(c, atual[c], ln[c])]
            if not mudou:
                res["iguais"] += 1
                continue
            sets = ", ".join(f"{c}=%s" for c in mudou)
            cur.execute(f"UPDATE metrica_registro SET {sets}, atualizado_em=now(), atualizado_por=%s WHERE id=%s", (*[ln[c] for c in mudou], usuario, reg_id))
            for c in mudou:
                cur.execute("INSERT INTO metrica_registro_hist (registro_id, campo, valor_anterior, valor_novo, motivo, alterado_por) VALUES (%s,%s,%s,%s,%s,%s)",
                            (reg_id, c, _txt(atual[c]), _txt(ln[c]), motivo, usuario))
            res["atualizadas"] += 1
            res["mudancas"].append({"item_id": ln["item_id"], "periodo": ln["periodo"], "campos": mudou})
    return res


def registrar_mes(conn, mes: str, usuario: str, hoje: dt.date | None = None, itens: list | None = None) -> dict:
    """Calcula e grava o mes. Devolve {'linhas', 'erros', **contagens de gravar_registro}."""
    linhas, erros = calcular_mes(conn, mes, hoje, itens)
    res = gravar_registro(conn, linhas, usuario)
    res.update({"linhas": linhas, "erros": erros})
    return res


# ---------------------------------------------------------------- leitura (tela)
def ler_registro(conn, mes: str) -> list:
    """Linhas gravadas do mes (ordem por indicador)."""
    cols = ("item_id", "pessoa", "empresa", "obra", "un", "meta", "previsto", "realizado", "numerador", "denominador", "pct_atingimento", "status", "origem",
            "detalhe", "atualizado_em", "atualizado_por")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM metrica_registro WHERE periodo=%s AND app_origem=%s ORDER BY item_id, empresa, obra, un", (mes, APP_ORIGEM))
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def ler_historico(conn, mes: str, limite: int = 200) -> list:
    """Rastro de mudancas dos registros do mes (mais recentes primeiro)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT r.item_id, h.campo, h.valor_anterior, h.valor_novo, h.motivo, h.alterado_por, h.alterado_em
                       FROM metrica_registro_hist h JOIN metrica_registro r ON r.id = h.registro_id
                       WHERE r.periodo=%s AND r.app_origem=%s ORDER BY h.id DESC LIMIT %s""", (mes, APP_ORIGEM, limite))
        return [dict(zip(("item_id", "campo", "valor_anterior", "valor_novo", "motivo", "alterado_por", "alterado_em"), r)) for r in cur.fetchall()]


def instalado(conn) -> bool:
    """True se o SQL-34 (tabelas do registro) ja foi executado no banco."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() "
                        "AND table_name IN ('metrica_registro','metrica_registro_hist','metrica_ocorrencia')")
            return cur.fetchone()[0] == 3
    except Exception:
        return False
