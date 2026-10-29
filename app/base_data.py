# -*- coding: utf-8 -*-
"""GDF V2 - Base de data das abas do Painel da Diretoria: REFERENCIA (competencia = data de emissao do titulo) ou CAIXA (data do pagamento/recebimento real).

Funcoes puras (sem banco). A escolha de cada aba vem de (1) o seletor do EDITOR, ou (2) para o login de visualizacao, a base FIXADA pelo editor
(guardada em pnl_config, sem SQL novo); sem nada fixado vale o padrao de cada aba (o que ela ja usava antes do seletor).
"""
from __future__ import annotations

REF, CAIXA = "REF", "CAIXA"
BASES = (REF, CAIXA)
ROTULO = {REF: "Referência (competência)", CAIXA: "Caixa (pagamento)"}
CURTO = {REF: "Referência", CAIXA: "Caixa"}
ABAS = ("Resultado", "Obras", "Administração", "Despesas", "Pessoas", "Folha PJ", "Folha CLT")
# o que cada aba ja usava ANTES do seletor (continua valendo para quem nao escolher nem tiver base fixada)
PADRAO = {"Resultado": REF, "Obras": REF, "Administração": CAIXA, "Despesas": CAIXA, "Pessoas": CAIXA, "Folha PJ": CAIXA, "Folha CLT": REF}
# Decisao da contabilidade (Suellen, 29/10/2026): Resultado e Obras para a Diretoria sao SEMPRE Referencia/competencia (o editor ainda pode olhar o Caixa para analise)
SO_REF = ("Resultado", "Obras")
PREFIXO_CHAVE = "base_aba_"


def valida(base) -> str | None:
    """'REF' / 'CAIXA' (aceita minusculas e os nomes por extenso); outra coisa -> None."""
    b = str(base or "").strip().upper()
    b = {"REFERENCIA": REF, "REFERÊNCIA": REF, "COMPETENCIA": REF, "COMPETÊNCIA": REF}.get(b, b)
    return b if b in BASES else None


def padrao(aba: str) -> str:
    return PADRAO.get(aba, REF)


def chave_config(aba: str) -> str:
    """Chave em pnl_config: 'base_aba_resultado', 'base_aba_folha_pj'..."""
    t = str(aba).lower()
    for a, b in (("ç", "c"), ("ã", "a"), ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ê", "e"), ("õ", "o"), (" ", "_")):
        t = t.replace(a, b)
    return PREFIXO_CHAVE + t


def resolver(aba: str, escolha, fixada, eh_editor: bool) -> str:
    """Base que a aba usa: o EDITOR usa a escolha do seletor (se ainda nao escolheu: a fixada para a Diretoria, senao o padrao da aba);
    o VISUALIZADOR nunca escolhe: usa a fixada (senao o padrao)."""
    fix = None if aba in SO_REF else valida(fixada)
    if aba in SO_REF and not eh_editor:
        return REF
    if eh_editor:
        return valida(escolha) or fix or padrao(aba)
    return fix or padrao(aba)


def rotulo_data(base: str) -> str:
    """Frase curta de qual data entra em cada base (para legendas)."""
    return "data de emissão do título" if base == REF else "data do pagamento (baixa no Sienge)"


def legenda(base: str, fixada: bool = False) -> str:
    """Texto de rodape da aba: diz a base em uso, para ninguem comparar numeros de bases diferentes sem saber."""
    if base == REF:
        t = "Base: **Referência (competência)** — conta o mês em que o título foi **emitido**, pelo valor do documento (pago ou não)."
    else:
        t = "Base: **Caixa** — conta o mês em que o pagamento **realmente saiu** (data da baixa no Sienge), pelo valor pago. Título ainda em aberto não entra."
    return t + (" Base definida pela contabilidade para este painel." if fixada else "")


# ---------------------------------------------------------------- o que conta como DINHEIRO REAL na base Caixa (decisao do Rafael, 29/10/2026)
# Pagar: 1 Pagamento, 10 Adiantamento, 1002 Movimento bancario (pagamento). Fora: 3 Cancelamento, 5 Substituicao, 8 Abatimento de adiantamento (troca de documento, nao e'
# dinheiro) e 1030 transferencia entre empresas. Receber: 2 Recebimento (fora: 3 Cancelamento, 4 Reparcelamento, 5 Substituicao, 7 Distrato). Mesma definicao dos Indicadores.
TIPOS_CAIXA = {"P": (1, 10, 1002), "R": (2,)}


def sql_caixa(alias: str = "b") -> str:
    """Trecho SQL (sem parametros; so' inteiros fixos) que deixa so' as baixas que sao dinheiro de verdade, para o alias da tabela de baixas."""
    p = ",".join(str(int(x)) for x in TIPOS_CAIXA["P"])
    r = ",".join(str(int(x)) for x in TIPOS_CAIXA["R"])
    return f"(({alias}.lado='P' AND {alias}.tipo_oper_id IN ({p})) OR ({alias}.lado='R' AND {alias}.tipo_oper_id IN ({r})))"
