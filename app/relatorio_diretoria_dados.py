# -*- coding: utf-8 -*-
"""GDF V2 - dados do RELATORIO PDF do Painel da Diretoria (v0.54.0). So' leitura; sem streamlit.

Como funciona, em linguagem simples:
- O painel tem varias abas e cada aba tem varias "informacoes" (cartoes, tabelas, graficos). Aqui cada informacao e' um BLOCO com uma chave (`res_formula`, `ob_tabela`,
  `pj_colab`...). A pessoa marca na tela quais blocos quer; `montar` calcula SO' os marcados, com as mesmas funcoes e regras das abas (painel_db, diretoria_dados,
  folha_pj_dados, indicadores_dados), e devolve cada bloco como uma lista de elementos neutros (cartoes, tabelas, barras, notas) que `relatorio_diretoria.py` desenha.
- Filtros do relatorio: periodo (o do topo do painel), obras especificas (ou geral), empresa que pagou e situacao (so' Folha PJ).
  Obras seguem o filtro nas abas Obras, Despesas, Pessoas, Folha PJ e Folha CLT; Resultado, Administracao, Indicadores e Financiamentos sao do grupo todo (a tela tambem nao os filtra por obra).
- Bloco sem dado nao derruba o relatorio: vira um aviso dizendo o que falta. Nomes e valores ficam so' no PDF gerado em memoria; nada e' gravado em disco nem no repositorio."""
from __future__ import annotations

import pandas as pd

import custos_obra_nivel as CON
import diretoria_dados as DD
import folha_pj_dados as FP
import grupo_enermais as GE
import historico as HIST
import indicadores_dados as I
import painel_db as P
import periodo as PER
from fuso import agora_br
from relatorio_fmt import fnum, mmn, neg, pct as _pct_fmt

# ------------------------------------------------------------------ catalogo: aba -> informacoes (chave, rotulo da caixinha, marcada por padrao, segue o filtro de obra, titulo no PDF)
CATALOGO = [
    ("res", "Resultado", [
        ("res_formula", "Receita − Custos = BDI − Administração = Resultado (realizado × previsto)", True, False, "Receita − Custos = BDI − Administração = Resultado"),
        ("res_desvio", "Desvio mensal (realizado − previsto), 12 meses", True, False, "Desvio mensal: realizado − previsto"),
        ("res_recomp", "Recomposição out–dez", True, False, "Recomposição out–dez"),
        ("res_receita", "Receita mês a mês (12 meses)", True, False, "Receita mês a mês"),
        ("res_dre", "DRE do mês de referência (linha a linha)", True, False, "DRE do mês de referência"),
    ]),
    ("ob", "Obras", [
        ("ob_kpis", "Cartões: receita, custos, BDI, obras com prejuízo, maior e menor BDI", True, True, "Obras: visão geral"),
        ("ob_tabela", "Tabela de obras (receita, custos, BDI previsto e real, margem, colaboradores)", True, True, "Resultado por obra"),
        ("ob_detalhe", "Detalhe da seleção de obras (só com obras específicas)", True, True, "Detalhe da seleção"),
        ("ob_categorias", "Custos por categoria", True, True, "Custos por categoria"),
        ("ob_credores", "Principais credores", True, True, "Principais credores"),
        ("ob_prejuizo", "Obras com maior prejuízo", True, True, "Obras com maior prejuízo"),
        ("ob_colab", "Colaboradores alocados nas obras (lista longa)", False, True, "Colaboradores alocados nas obras"),
    ]),
    ("adm", "Administração", [
        ("adm_kpis", "Cartões: orçado × realizado do mês e do período", True, False, "Administração: orçado × realizado"),
        ("adm_serie", "Orçado × realizado mês a mês (12 meses)", True, False, "Orçado × realizado por mês"),
        ("adm_grupos", "Por grupo de despesa", True, False, "Por grupo de despesa"),
        ("adm_contas", "Contas que mais passaram do orçado", True, False, "Contas que mais passaram do orçado"),
        ("adm_unidades", "Quem recebeu: por unidade", True, False, "Pago nas unidades da administração"),
        ("adm_credores", "Quem recebeu: por credor", True, False, "Pago por credor na administração"),
    ]),
    ("desp", "Despesas", [
        ("desp_kpis", "Cartões: pago no mês e no período, top 5 e top 12", True, True, "Despesas: visão geral"),
        ("desp_top12", "Top 12 contas do período", True, True, "Top 12 contas do período"),
        ("desp_top5", "Top 5 contas do mês", True, True, "Top 5 contas do mês"),
        ("desp_evolucao", "Evolução mensal (12 meses)", True, True, "Evolução mensal das despesas"),
        ("desp_credores", "Principais credores", True, True, "Principais credores das despesas"),
        ("desp_obras", "Por obra / centro de custo", True, True, "Despesas por obra / centro de custo"),
    ]),
    ("pes", "Pessoas", [
        ("pes_kpis", "Cartões: colaboradores, receita, custo e BDI por colaborador", True, False, "Pessoas: visão geral"),
        ("pes_headcount", "Colaboradores ativos (12 meses)", True, False, "Colaboradores ativos"),
        ("pes_custos", "Custos prioritários com pessoas", True, True, "Custos prioritários com pessoas"),
        ("pes_credores", "Principais credores de pessoas", True, True, "Principais credores de pessoas"),
        ("pes_obras", "Pessoas por obra", True, True, "Custos de pessoas por obra"),
    ]),
    ("pj", "Folha PJ", [
        ("pj_cards", "Custo PJ total e por empresa que pagou", True, True, "Custo PJ por empresa"),
        ("pj_kpis", "Cartões: honorários, premiações, ajuda de custo, vale alimentação, multa, descontos", True, True, "Composição do custo PJ"),
        ("pj_top_obras", "Obras com maior custo PJ", True, True, "Obras com maior custo PJ"),
        ("pj_obras", "Resumo por obra e centro de custo", True, True, "Folha PJ por obra e centro de custo"),
        ("pj_colab", "Colaboradores PJ (lista)", True, True, "Colaboradores PJ"),
        ("pj_docs", "Documentos lançados (lista longa)", False, True, "Documentos lançados"),
    ]),
    ("clt", "Folha CLT", [
        ("clt_cards", "Folha consolidada e por empresa", True, True, "Folha CLT consolidada"),
        ("clt_top_obras", "Obras com mais horas extras", True, True, "Obras com mais horas extras"),
        ("clt_selecao", "Cartões da seleção (obras filtradas)", True, True, "Folha CLT: seleção"),
        ("clt_he_receita", "Horas extras × receita (12 meses)", True, False, "Horas extras × receita"),
        ("clt_empresa_obra", "Folha CLT por empresa e por obra", True, True, "Folha CLT por empresa e por obra"),
        ("clt_lista", "Colaboradores CLT (lista nominal longa)", False, True, "Colaboradores CLT"),
    ]),
    ("ind", "Indicadores financeiros", [
        ("ind_prazos", "Prazo médio e ciclo financeiro", True, False, "Prazo médio e ciclo financeiro"),
        ("ind_giro", "Capital de giro", True, False, "Capital de giro"),
        ("ind_inad", "Inadimplência", True, False, "Inadimplência"),
        ("ind_receitas", "Receitas em aberto (lista longa)", False, False, "Receitas em aberto"),
    ]),
    ("fin", "Financiamentos", [
        ("fin_kpis", "Cartões: saldo devedor, juros, desembolso, contratos", True, False, "Financiamentos: visão geral"),
        ("fin_curva", "Curva de endividamento", True, False, "Curva de endividamento"),
        ("fin_categoria", "O que está financiado", True, False, "O que está financiado"),
        ("fin_credores", "Por credor (banco / financiadora)", True, False, "Financiamentos por credor"),
        ("fin_contratos", "Contratos", True, False, "Contratos de financiamento"),
    ]),
    ("inv", "Investimentos", [
        ("inv_kpis", "Cartões: saldo devedor, juros, desembolso, contratos", True, False, "Investimentos: visão geral"),
        ("inv_curva", "Curva de desembolso", True, False, "Curva de desembolso"),
        ("inv_categoria", "O que está investido", True, False, "O que está investido"),
        ("inv_credores", "Por credor", True, False, "Investimentos por credor"),
        ("inv_contratos", "Contratos", True, False, "Contratos de investimento"),
    ]),
]
ABAS = {a: (rot, itens) for a, rot, itens in CATALOGO}
BLOCOS_INFO = {k: {"aba": a, "rotulo": r, "padrao": p, "obra": o, "titulo": t} for a, _, itens in CATALOGO for k, r, p, o, t in itens}
TODAS_CHAVES = [k for _, _, itens in CATALOGO for k, *_ in itens]
PADRAO = [k for k in TODAS_CHAVES if BLOCOS_INFO[k]["padrao"]]
MODELOS = {
    "Completo": PADRAO,
    "Só PJ": [k for k in TODAS_CHAVES if k.startswith("pj_") and k != "pj_docs"],
    "Só CLT": [k for k in TODAS_CHAVES if k.startswith("clt_") and k != "clt_lista"],
    "Resultado e obras": ["res_formula", "res_receita", "ob_kpis", "ob_tabela", "ob_prejuizo", "adm_kpis"],
    "Pessoas (CLT e PJ)": [k for k in TODAS_CHAVES if k.split("_")[0] in ("pes", "pj", "clt") and k not in ("pj_docs", "clt_lista")],
}
PERSONALIZADO = "Personalizado"


# ------------------------------------------------------------------ formatos
def _mi(v, sinal: bool = False) -> str:
    """R$ em milhoes (ou mil), compacto, para os cartoes (igual ao painel)."""
    if v is None:
        return "–"
    a = abs(v)
    s = ("-" if v < 0 else ("+" if sinal and v > 0 else "")) if sinal else ("−" if v < 0 else "")
    f = lambda x, c: f"{x:,.{c}f}".replace(",", "X").replace(".", ",").replace("X", ".")          # noqa: E731
    if a >= 1e6:
        return s + "R$ " + f(a / 1e6, 2) + " mi"
    if a >= 1e3:
        return s + "R$ " + f(a / 1e3, 0) + " mil"
    return s + "R$ " + f(a, 0)


def _n0(v) -> str:
    return fnum(v, 0)


def _n2(v) -> str:
    return fnum(v, 2)


def _z0(v) -> str:
    """Numero sem centavos; zero ou vazio vira traco."""
    return "–" if v is None or abs(v) < 0.005 else fnum(v, 0)


def _pc(v, d: int = 1) -> str:
    return _pct_fmt(v, d) if v is not None else "–"


def _rot(m: str) -> str:
    return f"{m[5:]}/{m[:4]}"


def _rot_curto(m: str) -> str:
    return f"{m[5:]}/{m[2:4]}"


def _fk(v) -> str:
    return fnum(v / 1000.0, 0)


def _delta(real, prev):
    if real is None or prev is None:
        return None
    dv = real - prev
    p = f" · {_pct_fmt(dv / abs(prev), 1)}" if abs(prev) > 0.005 else ""
    return _mi(dv, True) + p


def _dias(v) -> str:
    return "–" if v is None else f"{round(v):,}".replace(",", ".") + (" dia" if round(v) in (1, -1) else " dias")


def _data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "–"


def _txt_sel(itens, vazio: str, ate: int = 2) -> str:
    itens = [str(i) for i in itens]
    if not itens:
        return vazio
    return ", ".join(itens) if len(itens) <= ate else f"{len(itens)} selecionados"


# ------------------------------------------------------------------ elementos neutros (o PDF os desenha)
def K(rot, val, sub="", dark=False) -> dict:
    return {"rot": rot, "val": val, "sub": sub or "", "dark": dark}


def kpis(itens: list, por_linha: int = 4) -> dict:
    return {"t": "kpis", "itens": itens, "n": por_linha}


def tab(head: list, rows: list, pesos: list, alin: list | None = None, titulo: str | None = None, fs: float = 6.9, rh: float = 12.6) -> dict:
    """rows: [(tipo, [celulas])] com tipo norm|sub|tot; pesos = largura relativa de cada coluna; alin = 'l'/'r' (padrao: 1a coluna esquerda, o resto direita)."""
    alin = alin or (["l"] + ["r"] * (len(head) - 1))
    return {"t": "tab", "head": head, "rows": rows, "pesos": pesos, "alin": alin, "titulo": titulo, "fs": fs, "rh": rh}


def barras(labels: list, vals: list, fmt: str = "mi", unidade: str = "R$ MM", titulo: str | None = None, h: float = 100) -> dict:
    return {"t": "barras", "labels": labels, "vals": vals, "fmt": fmt, "unidade": unidade, "titulo": titulo, "h": h}


def nota(txt: str) -> dict:
    return {"t": "nota", "texto": txt}


def sec(txt: str) -> dict:
    return {"t": "sec", "texto": txt}


# ------------------------------------------------------------------ base compartilhada (tudo calculado so' quando algum bloco pede)
class Base:
    def __init__(self, conn, mes_ini: str, mes: str, modo: str = PER.ANO, escopo: dict | None = None, ctx: dict | None = None, hoje=None):
        self.conn, self.mes_ini, self.mes, self.modo = conn, mes_ini, mes, modo
        esc = escopo or {}
        self.obras = [str(o) for o in (esc.get("obras") or [])]
        self.empresas = list(esc.get("empresas") or [])
        self.situacoes = list(esc.get("situacoes") or [])
        self._ctx = ctx
        self.hoje = hoje or agora_br().date()
        self.um_mes = mes_ini == mes
        self.per_rot = PER.rotulo(mes_ini, mes)
        self.acum = PER.curto(mes_ini, mes)
        self.mes_ini_g = PER.somar_meses(mes, -11)
        self.meses_g = PER.meses_entre(self.mes_ini_g, mes)
        self._m: dict = {}

    def memo(self, chave, fn):
        if chave not in self._m:
            self._m[chave] = fn()
        return self._m[chave]

    @property
    def filtra_obra(self) -> bool:
        return bool(self.obras)

    @property
    def ctx(self) -> dict:
        if self._ctx is None:
            import relatorio_painel_pdf as RPP
            self._ctx = RPP.montar_ctx(self.conn, self.mes, agora_br().strftime("%d/%m/%Y %H:%M"))
        return self._ctx

    @property
    def hist(self):
        return self.ctx.get("hist")

    def nomes_obras(self) -> dict:
        import relatorio_painel_pdf as RPP
        return self.memo("nomes_obras", lambda: RPP._nomes_obras(self.conn))

    def nomes_por_codigo(self) -> dict:
        """{codigo da obra: {nomes de obra usados na Folha PJ}} (so' para ligar o filtro de obras da tela ao nome de obra da Folha PJ)."""
        def f():
            out: dict = {}
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT codigo_obra, obra_nome FROM pnl_centro_grupo WHERE codigo_obra IS NOT NULL AND obra_nome IS NOT NULL")
                    for cod, nome in cur.fetchall():
                        out.setdefault(str(cod), set()).add(nome)
            except Exception:                                          # noqa: BLE001
                try:
                    self.conn.rollback()
                except Exception:                                      # noqa: BLE001
                    pass
            return out
        return self.memo("nomes_por_codigo", f)

    # ---- contas pagas (Despesas, Pessoas, PJ por obra)
    def _pagos(self, ini: str):
        def f():
            regras = P.regras_ativas(self.conn, "DESPESAS")
            linhas = DD.pagos_detalhe(self.conn, ini, self.mes, sem_previsao=P.exclui_previsao(regras))
            return DD.para_df(linhas), P.prefixos_excluidos(regras)
        return self.memo(("pagos", ini), f)

    def pagos(self):
        return self._pagos(self.mes_ini)

    def despesas(self) -> pd.DataFrame:
        return self.memo("despesas", lambda: DD.despesas_df(*self.pagos()))

    def despesas_12(self) -> pd.DataFrame:
        if self.mes_ini <= self.mes_ini_g:
            return self.despesas()
        return self.memo("despesas12", lambda: DD.despesas_df(*self._pagos(self.mes_ini_g)))

    def pj_nomes(self) -> set:
        return self.memo("pj_nomes", lambda: DD.credores_pj(self.pagos()[0]))

    def despesas_sem_pj(self) -> pd.DataFrame:
        return self.memo("desp_sem_pj", lambda: DD.sem_credores(self.despesas(), self.pj_nomes()))

    def pessoas_df(self) -> pd.DataFrame:
        return self.memo("pessoas_df", lambda: DD.pessoas_df(self.pagos()[0]))

    def pessoas_sem_grupo(self) -> pd.DataFrame:
        return self.memo("pessoas_sem_grupo", lambda: DD.sem_grupo_enermais(self.pessoas_df(), GE.nucleos_do_grupo(self.conn)))

    def esc(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica o filtro de obras a uma tabela que tem a coluna 'obra' (codigo do de-para)."""
        if not self.filtra_obra or not len(df) or "obra" not in df.columns:
            return df
        return df[df["obra"].isin(self.obras)]

    # ---- Obras do periodo (o mes de referencia ou a soma dos meses com dado)
    def _obras_mes(self, m: str):
        extra = self.memo("obras_extra", lambda: (P.nomes_obras_extra(self.conn), set(P.meses_com_obras(self.conn))))
        nomes_extra, com_obras = extra
        ob_m = P.obras_do_mes(self.conn, m) if m in com_obras else None
        px = None
        if ob_m:
            pj_ = P.projecao_do_mes(self.conn, m)
            px = P.projecao_x_realizado(pj_, ob_m, nomes_extra) if pj_ else None
        return ob_m, px

    def obras_periodo(self):
        """(ob, proj, meses somados, meses sem dado) -- mesma regra da aba Obras."""
        def f():
            ctx = self.ctx
            if self.um_mes:
                return ctx["obras"], ctx.get("proj"), 1, []
            ms = PER.meses_entre(self.mes_ini, self.mes)
            pares = [self._obras_mes(m) for m in ms]
            oks = [(o, px) for o, px in pares if o]
            falt = [m for m, (o, _) in zip(ms, pares) if not o]
            soma = P.somar_obras([o for o, _ in oks])
            if not soma:
                return None, None, 0, falt
            proj_s = P.somar_projecoes([px for _, px in oks])
            com_proj = {x["codigo"] for x in (proj_s or {}).get("linhas", []) if x.get("codigo") and x.get("receita_proj")}
            soma.update(P.agrupar_demais_obras(soma, com_proj))
            soma["nome_cheio"] = self.nomes_obras()
            folha_f = P.folha_do_mes(self.conn, self.mes)
            soma["colab"] = P.colab_por_linha_obras(soma["linhas"], folha_f) if folha_f else {}
            return soma, proj_s, len(oks), falt
        return self.memo("obras_periodo", f)

    def pj_obra(self) -> list:
        return self.memo("pj_obra", lambda: DD.pj_por_obra(self.pagos()[0], self.mes))

    def adm_periodo(self):
        def f():
            c, mes, mes_ini = self.conn, self.mes, self.mes_ini
            linhas_mes, linhas_per = [], []
            if P.meses_com_dados(c) and P.centro_grupo_instalado(c):
                regras = P.regras_ativas(c, "DESPESAS")
                fora_adm = [p for p in P.prefixos_excluidos(regras) if p != "2.02.01"]
                sem_prev = P.exclui_previsao(regras)
                linhas_mes = P.adm_linhas(c, mes, mes, fora_adm, sem_previsao=sem_prev)
                linhas_per = P.adm_linhas(c, mes_ini, mes, fora_adm, sem_previsao=sem_prev) if mes_ini != mes else linhas_mes
            orc = P.orcamento_ativo(c) if P.orcamento_instalado(c) else None
            orc_mes = orc_per = None
            serie, serie_g = [], []
            if orc:
                meses_orc = [m for m in PER.meses_entre(mes_ini, mes) if m in orc["meses"]]
                if mes in orc["meses"]:
                    orc_mes = P.orcamento_resumo(c, orc["id"], mes)
                if meses_orc:
                    orc_per = P.orcamento_resumo(c, orc["id"], mes, acumulado=True, mes_ini=meses_orc[0])
                todas = P.orcamento_serie_mensal(c, orc["id"])
                serie = [x for x in todas if mes_ini <= x["mes"] <= mes]
                serie_g = [x for x in todas if self.mes_ini_g <= x["mes"] <= mes]
            if not (linhas_per or orc_per or orc_mes):
                return None
            return {"linhas_mes": linhas_mes, "linhas_per": linhas_per, "orc_mes": orc_mes, "orc_per": orc_per, "serie_orc": serie, "serie_orc_g": serie_g}
        return self.memo("adm_periodo", f)

    def pj_dados(self) -> dict:
        return self.memo("pj_dados", lambda: FP.dados_do_mes(self.conn, self.mes))

    def clt_todos(self) -> list:
        return self.memo("clt_todos", lambda: P.folha_pessoas_mes(self.conn, self.mes))


# ------------------------------------------------------------------ RESULTADO
def _termos_mes(B: Base) -> dict:
    """Receita - Custo = BDI - Administracao = Resultado do mes de referencia: {chave: (realizado, previsto)}."""
    ctx = B.ctx
    ob, proj, v = ctx["obras"], ctx.get("proj"), ctx["dre"]["valores"]
    rec = ob["total"]["receita"] if ob else v["01"]
    cus = abs(ob["total"]["custo"]) if ob else abs(v["04"])
    bdi = ob["total"]["bdi"] if ob else v["05"]
    adm = ctx["adm"]
    orc = adm["orcamento"] if adm and adm.get("orcamento") else None
    adm_real = orc["total"]["realizado"] if orc else None
    adm_orc = orc["total"]["orcado"] if orc else None
    resultado = round(bdi - adm_real, 2) if adm_real is not None else None
    rec_p = bdi_p = cus_p = None
    if proj and abs(proj["receita_proj_total"]) > 0.005:
        rec_p = proj["receita_proj_total"]
        bdi_p = proj["total"]["bdi_proj"]
        cus_p = round(rec_p - bdi_p, 2)
    res_p = round(bdi_p - adm_orc, 2) if bdi_p is not None and adm_orc is not None else None
    return {"rec": (rec, rec_p), "cus": (cus, cus_p), "bdi": (bdi, bdi_p), "adm": (adm_real, adm_orc), "res": (resultado, res_p)}


def _termos_periodo(B: Base):
    ms = PER.meses_entre(B.mes_ini, B.mes)
    lst = [B.memo(("termo", m), lambda m=m: P.termos_do_mes(B.conn, m)) for m in ms]
    return P.somar_termos(lst), [m for m, t in zip(ms, lst) if not t]


def _historico_cobre(B: Base) -> bool:
    h = B.hist
    return bool(h and h.get("ate") in (B.mes, PER.somar_meses(B.mes, -1)))


def _ano_pela_api(B: Base):
    """Ano ate o mes: realizado = soma dos meses; previsto e administracao completados com o historico da contabilidade (mesma regra da aba Resultado)."""
    t, falt = _termos_periodo(B)
    if not t:
        return None, falt, False
    if not _historico_cobre(B):
        return t, falt, False
    hist = B.hist
    ate, ac, dev = hist["ate"], hist["acumulado"], hist.get("desvio_acumulado", {})
    atual, usou = _termos_mes(B), False
    out = dict(t)

    def do_hist(k):
        real_h = ac.get(k)
        prev_h = (real_h - dev[k]) if real_h is not None and k in dev else None
        if ate == B.mes:
            return real_h, prev_h
        r_m, p_m = atual[k]
        return (None if real_h is None or r_m is None else real_h + r_m, None if prev_h is None or p_m is None else prev_h + p_m)

    for k in ("rec", "cus", "bdi", "adm"):
        real, prev = out[k]
        h_real, h_prev = do_hist(k)
        if prev is None and h_prev is not None:
            prev, usou = h_prev, True
        if k == "adm" and real is None and h_real is not None:
            real, usou = h_real, True
        out[k] = (real, prev)
    bdi_real, bdi_prev = out["bdi"]
    adm_real_, adm_prev_ = out["adm"]
    res_real, res_prev = out["res"]
    if res_real is None and bdi_real is not None and adm_real_ is not None:
        res_real, usou = round(bdi_real - adm_real_, 2), True
    h_res_prev = do_hist("res")[1]
    if res_prev is None:
        res_prev = round(bdi_prev - adm_prev_, 2) if bdi_prev is not None and adm_prev_ is not None else h_res_prev
        usou = usou or res_prev is not None
    out["res"] = (res_real, res_prev)
    return out, falt, usou


def b_res_formula(B: Base) -> list:
    els: list = []
    termos, rotulo_per = None, ""
    if B.modo == PER.MES:
        termos, rotulo_per = _termos_mes(B), _rot(B.mes)
    else:
        if B.modo == PER.ANO:
            t_per, falt, usou_h = _ano_pela_api(B)
        else:
            (t_per, falt), usou_h = _termos_periodo(B), False
        if t_per:
            termos, rotulo_per = t_per, B.per_rot
            txt = (f"Soma de {len(t_per['meses'])} {'mês' if len(t_per['meses']) == 1 else 'meses'} com dados em {B.per_rot}: {', '.join(_rot(m) for m in t_per['meses'])}."
                   + (f" Fora da soma por falta de dados: {', '.join(_rot(m) for m in falt)}." if falt else "")
                   + (" Previsto e administração completados com o histórico do painel da contabilidade." if usou_h else
                      " Administração e Resultado só aparecem se todos os meses somados têm Orçamento ADM; o previsto só se todos têm projeção."))
            els_nota = nota(txt)
        else:
            termos, rotulo_per = _termos_mes(B), _rot(B.mes)
            els.append(nota(f"Nenhum mês de {B.per_rot} tem dados de DRE; abaixo, o resultado do mês de referência ({_rot(B.mes)})."))
            els_nota = None
    rot = [("rec", "Receita (base-line)", True), ("cus", "Custos", False), ("bdi", "BDI", True), ("adm", "Administração", False), ("res", "Resultado", True)]
    itens = []
    for k, nome, _ in rot:
        real, prev = termos[k]
        dl = _delta(real, prev)
        itens.append(K(nome, _mi(real), (f"previsto {_mi(prev)}" if prev is not None else "previsto n/d") + (f" · {dl}" if dl else ""), dark=(k == "res")))
    els.append(sec(f"Período: {rotulo_per}"))
    els.append(kpis(itens[:3], 3))
    els.append(kpis(itens[3:], 2))
    partes = []
    for k, nome, _ in rot:
        real, prev = termos[k]
        if real is None or prev is None or abs(real - prev) < 0.005:
            continue
        partes.append(f"{nome.split(' (')[0].lower()} {_mi(abs(real - prev)).replace('−', '')} {'acima' if real > prev else 'abaixo'} do previsto")
    if partes:
        els.append(nota("Em relação ao previsto: " + "; ".join(partes) + ". Para custos e administração, acima do previsto é estouro."))
    if B.modo != PER.MES and 'els_nota' in locals() and els_nota:
        els.append(els_nota)
    return els


def b_res_desvio(B: Base) -> list:
    h = B.hist
    if not h or not h.get("desvio_linhas"):
        return [nota("O desvio mensal aparece quando o histórico do painel da contabilidade é importado.")]
    idx = [i for i, m in enumerate(h["desvio_meses"]) if B.mes_ini_g <= m["mes"] <= B.mes]
    if not idx:
        return [nota(f"O histórico do painel da contabilidade (até {_rot(h['ate'])}) não tem desvio mensal nos 12 meses até {_rot(B.mes)}.")]
    ml = [h["desvio_meses"][i]["rotulo"] for i in idx]
    rows = [("sub" if nome.startswith("Lucro") else "norm", [nome] + [_fk(vals[i]) for i in idx]) for nome, vals in h["desvio_linhas"].items()]
    els = [tab(["Linha (R$ mil)"] + ml, rows, [2.2] + [1] * len(ml), fs=6.2, rh=13)]
    luc = h["desvio_linhas"].get("Lucro do Período")
    if luc:
        els.append(barras(ml, [luc[i] for i in idx], fmt="mi2", titulo="Desvio do lucro do período (R$ MM)", h=80))
    els.append(nota(f"Fixo nos últimos 12 meses ({PER.rotulo(B.mes_ini_g, B.mes)}; histórico do painel da contabilidade). Para Custos e Despesas ADM, valor positivo indica estouro."))
    return els


def b_res_recomp(B: Base) -> list:
    h = B.hist
    if not h or not h.get("recomposicao"):
        return [nota("A recomposição aparece quando o histórico do painel da contabilidade é importado.")]
    rc = h["recomposicao"]
    rows = [("norm", [r["rotulo"], _n0(r["projecao"]), _n0(r["para_cobrir"])]) for r in rc]
    rows.append(("sub", ["Out–Dez", _n0(sum(r["projecao"] for r in rc)), _n0(sum(r["para_cobrir"] for r in rc))]))
    return [tab(["Mês", "Projeção (R$)", "Para cobrir o déficit (R$)"], rows, [1, 1.4, 1.6]),
            nota("Faturamento necessário para cobrir o déficit acumulado de base-line, distribuído proporcionalmente à projeção. Visão de fim de ano: não muda com o período.")]


def b_res_receita(B: Base) -> list:
    serie = [x for x in B.ctx["serie"] if B.mes_ini_g <= x["mes"] <= B.mes]
    if len(serie) < 2:
        return [nota("Ainda não há meses suficientes para mostrar a evolução da receita.")]
    els = [barras([_rot_curto(x["mes"]) for x in serie], [x["receita"] for x in serie], fmt="mi")]
    if any(x["fonte"].startswith("API") for x in serie):
        els.append(nota("Meses com fonte “API (a conferir)” ainda não têm DRE oficial confirmado e podem mudar quando forem conferidos."))
    return els


def b_res_dre(B: Base) -> list:
    d = B.ctx["dre"]
    rb = d["valores"]["01"]
    rows = []
    for cod, nome, val in d["linhas"]:
        pai = "." not in cod
        tipo = "tot" if cod in ("11", "14") else ("sub" if pai else "norm")
        rows.append((tipo, [cod, nome, _n2(val), _pc(val / rb) if abs(rb) > 0.005 and pai else "", d["fontes"].get(cod, "") if not pai else ""]))
    els = [sec(f"{_rot(B.mes)} · {d['origem']}"),
           tab(["Linha", "Descrição", "Valor (R$)", "% rec. bruta", "Fonte"], rows, [0.7, 4.6, 2.0, 1.2, 1.0], ["l", "l", "r", "r", "l"], fs=7.0, rh=13.4)]
    if d.get("manuais"):
        els.append(nota("Linhas ajustadas à mão pela contabilidade (com observação registrada): " + ", ".join(d["manuais"]) + "."))
    return els


# ------------------------------------------------------------------ OBRAS
def _regs_obras(B: Base):
    """Linhas da tabela de Obras (mesma conta da aba) -> (registros, ob, proj, n_ob, falt) ou None."""
    def f():
        ob, proj, n_ob, falt = B.obras_periodo()
        if not ob:
            return None
        ctx = B.ctx
        pes = ctx["pessoas"]
        pj_obra: dict = {}
        for x in B.pj_obra():
            pj_obra.setdefault(x["obra"], set()).add(x["credor"])
        nome_cheio = ob.get("nome_cheio", {})
        proprias = {l["obra"] for l in ob["linhas"] if l["obra"] != "DEM"}
        prev_por_obra = {x["codigo"]: x for x in (proj["linhas"] if proj else [])}
        import relatorio_painel_pdf as RPP
        regs = []
        for l in ob["linhas"]:
            clt = ob["colab"].get(l["obra"], 0)
            pj_n = (len(set().union(*[cr for c, cr in pj_obra.items() if c not in proprias and c not in ("ADM", "99", "sem de-para")]))
                    if l["obra"] == "DEM" else len(pj_obra.get(l["obra"], ())))
            pr = prev_por_obra.get(l["obra"])
            hc = clt + pj_n
            regs.append({"Obra": l["obra"], "Nome": RPP._nome_obra(l, nome_cheio), "Receita": l["receita"], "Custos": abs(l["custo"]), "BDI previsto": pr["bdi_proj"] if pr else None,
                         "BDI real": l["bdi"], "Desvio BDI": (l["bdi"] - pr["bdi_proj"]) / abs(pr["bdi_proj"]) if pr and abs(pr["bdi_proj"]) > 0.005 else None,
                         "CLT": clt, "PJ": pj_n, "Colab.": hc, "Fat./colab.": (l["receita"] / n_ob / hc) if hc and l["obra"] != "DEM" else None,
                         "Custo/colab.": (abs(l["custo"]) / n_ob / hc) if hc and l["obra"] != "DEM" else None, "Margem": l["margem"],
                         "receita_proj": pr["receita_proj"] if pr else None})
        return {"regs": regs, "ob": ob, "proj": proj, "n_ob": n_ob, "falt": falt, "pes": pes, "pj_obra": pj_obra, "proprias": proprias, "nome_cheio": nome_cheio}
    return B.memo("regs_obras", f)


def _sem_obras(B: Base) -> list:
    return [nota("Sem dados por obra " + ("neste mês (nenhum título emitido carregado pela API e nenhum PDF importado)." if B.um_mes else "em nenhum mês deste período."))]


def _nota_periodo_obras(B: Base, R: dict) -> list:
    if B.um_mes:
        return []
    return [nota(f"Soma de {R['n_ob']} {'mês' if R['n_ob'] == 1 else 'meses'} com dados por obra em {B.per_rot}." + (f" Sem dados (fora da soma): {', '.join(_rot(m) for m in R['falt'])}." if R["falt"] else "")
                 + " Colaboradores = os do mês de referência; faturamento e custo por colaborador = média mensal do período.")]


def _selecao(B: Base, R: dict) -> pd.DataFrame:
    base = pd.DataFrame(R["regs"])
    if B.filtra_obra:
        return base[base["Obra"].isin(B.obras)]
    return base


def b_ob_kpis(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    base = pd.DataFrame(R["regs"])
    main = base[base["Obra"] != "DEM"]
    if B.filtra_obra:
        main = main[main["Obra"].isin(B.obras)]
        sel = base[base["Obra"].isin(B.obras)]
        tr, tc, tb = float(sel["Receita"].sum()), float(sel["Custos"].sum()), float(sel["BDI real"].sum())
        rp = sel["receita_proj"].dropna()
        bp = sel["BDI previsto"].dropna()
        rec_p = float(rp.sum()) if len(rp) else None
        bdi_p = float(bp.sum()) if len(bp) else None
    else:
        ob, proj = R["ob"], R["proj"]
        tr, tc, tb = ob["total"]["receita"], abs(ob["total"]["custo"]), ob["total"]["bdi"]
        rec_p = proj["receita_proj_total"] if proj else None
        bdi_p = proj["total"]["bdi_proj"] if proj else None
    cus_p = (rec_p - bdi_p) if rec_p is not None and bdi_p is not None else None
    n_neg = int((main["BDI real"] < 0).sum())
    itens = [K("Receita realizada", _mi(tr), _delta(tr, rec_p) or ""), K("Custos", _mi(tc), _delta(tc, cus_p) or ""), K("BDI", _mi(tb), _delta(tb, bdi_p) or ""),
             K("Obras com prejuízo", f"{n_neg} de {len(main)}", "BDI negativo no mês" if B.um_mes else "BDI negativo no período")]
    if len(main):
        mx, mn = main.loc[main["BDI real"].idxmax()], main.loc[main["BDI real"].idxmin()]
        itens += [K("Maior BDI", str(mx["Nome"] or mx["Obra"])[:26], _mi(mx["BDI real"], True)), K("Menor BDI", str(mn["Nome"] or mn["Obra"])[:26], _mi(mn["BDI real"], True))]
    els = _nota_periodo_obras(B, R)
    if B.filtra_obra:
        els.append(sec(f"Seleção: {len(B.obras)} obra(s) · {', '.join(B.obras[:6])}{'…' if len(B.obras) > 6 else ''}"))
    els.append(kpis(itens, 3))
    return els


def b_ob_tabela(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    sel = _selecao(B, R)
    if not len(sel):
        return [nota("Nenhuma das obras escolhidas tem movimento no período.")]
    rows = [("norm", [str(r["Obra"]), str(r["Nome"])[:34], _n0(r["Receita"]), _n0(r["Custos"]), _z0(r["BDI previsto"]) if r["BDI previsto"] is not None else "–", _n0(r["BDI real"]),
                      _pc(r["Desvio BDI"]), _pc(r["Margem"]), str(int(r["Colab."])), _z0(r["Fat./colab."]) if pd.notna(r["Fat./colab."]) else "–",
                      _z0(r["Custo/colab."]) if pd.notna(r["Custo/colab."]) else "–"]) for _, r in sel.iterrows()]
    tr, tc, tb = float(sel["Receita"].sum()), float(sel["Custos"].sum()), float(sel["BDI real"].sum())
    bp = sel["BDI previsto"].dropna()
    rows.append(("tot", ["", "Total" + (" da seleção" if B.filtra_obra else ""), _n0(tr), _n0(tc), _n0(float(bp.sum())) if len(bp) else "–", _n0(tb), "", _pc(tb / tr) if abs(tr) > 0.005 else "–",
                         str(int(sel["Colab."].sum())), "", ""]))
    return _nota_periodo_obras(B, R) + [tab(["Obra", "Nome", "Receita", "Custos", "BDI previsto", "BDI real", "Desvio BDI", "Margem", "Colab.", "Fat./colab.", "Custo/colab."],
                                            rows, [0.55, 2.3, 1.15, 1.15, 1.05, 1.1, 0.8, 0.8, 0.6, 1.0, 1.0], ["l", "l"] + ["r"] * 9, fs=6.2, rh=12.4),
                                        nota("Valores em R$ (sem centavos). Previsto = projeção de receitas do mês; obras sem projeção não têm BDI previsto. Colaboradores = CLT da folha do mês + PJ alocado na obra onde mais recebeu em “Salários PJ”.")]


def b_ob_detalhe(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    if not B.filtra_obra:
        return [nota("Este detalhe aparece quando há obras específicas nos filtros do relatório (como ao marcar linhas na tabela de obras).")]
    sel = _selecao(B, R)
    if not len(sel):
        return [nota("Nenhuma das obras escolhidas tem movimento no período.")]
    rp = sel["receita_proj"].dropna()
    rec, cus, bdi = float(sel["Receita"].sum()), float(sel["Custos"].sum()), float(sel["BDI real"].sum())
    hc = int(sel["Colab."].sum())
    n_ob = R["n_ob"]
    pes = R["pes"]
    pos = [pes["folha"]["por_obra"].get(c) for c in sel["Obra"]] if pes else []
    pos = [x for x in pos if x]
    po = {"custo": sum(x["custo"] for x in pos), "colab": sum(x["colab"] for x in pos)} if pos else None
    nome = str(sel.iloc[0]["Nome"]) if len(sel) == 1 else f"{len(sel)} obras selecionadas"
    return [sec(f"{', '.join(map(str, sel['Obra']))} · {nome}"),
            kpis([K("Receita realizada", _mi(rec)), K("Receita prevista", _mi(float(rp.sum())) if len(rp) else "sem projeção"), K("Custos", _mi(cus)),
                  K("BDI real", _mi(bdi), (_pc(bdi / rec) + " de margem") if abs(rec) > 0.005 else "")], 4),
            kpis([K("Colaboradores", str(hc), f"{int(sel['CLT'].sum())} CLT + {int(sel['PJ'].sum())} PJ"),
                  K("Faturamento por colaborador", _mi(rec / n_ob / hc) if hc and "DEM" not in set(sel["Obra"]) else "–"),
                  K("Custo por colaborador", _mi(cus / n_ob / hc) if hc else "–"),
                  K("Custo da folha CLT por colaborador", _n2(po["custo"] / po["colab"]) if po and po["colab"] else "–")], 4)]


def _destino_ob(cod: str, proprias: set):
    if cod in proprias:
        return cod
    return None if cod in ("ADM", "99", "") or cod == "sem de-para" else "DEM"


def b_ob_categorias(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    proprias = R["proprias"]
    lin = B.memo("custos_nivel", lambda: P.custos_obra_linhas(B.conn, B.mes_ini, B.mes))
    tab_n = CON.tabela(lin, B.obras, lambda o: o if o in proprias else "DEM", B.mes) if lin else []
    if not tab_n or abs(tab_n[0]["periodo"]) <= 0.005:
        return [nota("Sem custos por categoria para esta seleção (faltam títulos emitidos no período ou o de-para de centros de custo → obra).")]
    rows = [("sub" if "." not in x["codigo"] else "norm", [x["codigo"], x["categoria"], _n0(x["periodo"]), _pc(x["pct"]), _z0(x["mes"])]) for x in tab_n]
    return [tab(["Código", "Categoria", f"Acumulado {B.acum}", "% do total", _rot(B.mes)], rows, [0.7, 4.4, 1.8, 1.0, 1.5], ["l", "l", "r", "r", "r"], fs=6.9),
            nota(f"Custos dos títulos emitidos em {B.per_rot} (análise “comprometido”, como no relatório de custos por obra da contabilidade), sem previsões e títulos desfeitos e sem os centros da administração. "
                 "Valor negativo é crédito. O total acompanha a coluna “Custos” da tabela de obras.")]


def b_ob_credores(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    proprias = R["proprias"]
    dd_ob = B.despesas_sem_pj()
    nao_obra = ("ADM", "99", "")
    alvo = None
    if B.filtra_obra:
        alvo = [c for c in B.obras if c != "DEM"]
        if "DEM" in B.obras:
            alvo += [c for c in dd_ob["obra"].unique() if c not in proprias and c not in nao_obra] if len(dd_ob) else []
    cr = DD.credores_da_obra(dd_ob, alvo, B.mes)
    if not cr["linhas"]:
        return [nota("Sem contas pagas para esta seleção (ou falta o de-para de centros de custo → obra).")]
    rows = [("norm", [x["chave"][:60], _n0(x["acumulado"]), _pc(x["acumulado"] / cr["total"]) if cr["total"] else "–", _z0(x["mes"])]) for x in cr["linhas"]]
    return [tab(["Credor", f"Acumulado {B.acum}", "%", _rot(B.mes)], rows, [4.0, 1.7, 0.9, 1.5], ["l", "r", "r", "r"]),
            nota(("Todos os credores." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores.")
                 + f" Contas pagas em {B.per_rot}, sem pessoal e encargos e sem os credores que são colaboradores PJ. Obra pelo centro de custo do lançamento.")]


def b_ob_prejuizo(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    import relatorio_painel_pdf as RPP
    lista = [x for x in R["ob"]["top_prejuizo"] if not B.filtra_obra or x["obra"] in B.obras]
    if not lista:
        return [nota("Nenhuma obra com BDI negativo " + ("no mês." if B.um_mes else "no período.") if not B.filtra_obra else "Nenhuma das obras escolhidas está entre as de maior prejuízo.")]
    return [tab(["Obra", "Nome", "BDI", "Margem"], [("norm", [x["obra"], RPP._nome_obra(x, R["nome_cheio"])[:40], _n0(x["bdi"]), _pc(x["margem"])]) for x in lista],
                [0.7, 4.0, 1.5, 1.0], ["l", "l", "r", "r"])]


def b_ob_colab(B: Base) -> list:
    R = _regs_obras(B)
    if not R:
        return _sem_obras(B)
    proprias = R["proprias"]
    nomes_ob = {l["obra"]: (R["nome_cheio"].get(l["obra"]) or l.get("nome") or l["obra"]) for l in R["ob"]["linhas"]}
    fant = B.memo("fantasias", lambda: P.fantasia_por_credor(B.conn))
    regs = [{"Nome": c["nome"], "Função": c["cargo"], "Tipo": "CLT", "dest": _destino_ob(c["obra"], proprias)} for c in P.folha_colaboradores(B.conn, B.mes)]
    for x in B.pj_obra():
        nf = DD.nome_fantasia(x["credor"], fant)
        regs.append({"Nome": nf, "Função": f"Prestador de serviço (PJ) — {round(x['pct'] * 100)}% nesta obra", "Tipo": "PJ", "dest": _destino_ob(x["obra"], proprias)})
    lst = [r for r in regs if r["dest"] and (not B.filtra_obra or r["dest"] in B.obras)]
    if not lst:
        return [nota("Sem colaboradores para esta seleção (folha do mês ainda não importada ou obra sem pessoal).")]
    lst.sort(key=lambda r: (r["dest"] == "DEM", str(r["dest"]), r["Nome"]))
    rows = [("norm", [r["Nome"][:34], r["Função"][:52], r["Tipo"], ("Demais obras" if r["dest"] == "DEM" else f"{r['dest']} · {nomes_ob.get(r['dest'], r['dest'])}")[:36]]) for r in lst]
    n_clt = sum(1 for r in lst if r["Tipo"] == "CLT")
    n_pj = len({r["Nome"] for r in lst if r["Tipo"] == "PJ"})
    return [tab(["Nome", "Função", "Tipo", "Obra"], rows, [2.2, 2.9, 0.6, 2.5], ["l", "l", "l", "l"], fs=6.4, rh=11.6),
            nota(f"{n_clt + n_pj} colaboradores ({n_clt} CLT + {n_pj} PJ). CLT pelos recibos da folha do mês; PJ pelos credores de “Salários PJ” pagos no mês (quem atende mais de uma obra aparece em cada uma). Administração fora da lista.")]


# ------------------------------------------------------------------ ADMINISTRACAO
def _sem_adm() -> list:
    return [nota("Falta sincronizar as contas pagas do período e/ou importar o Orçamento ADM.")]


def b_adm_kpis(B: Base) -> list:
    ap = B.adm_periodo()
    if not ap:
        return _sem_adm()
    o, ac, so = ap["orc_mes"], ap["orc_per"], ap["serie_orc"]
    if not (o or ac):
        return [nota("Falta importar o Orçamento ADM (aba Importações V2): sem ele não há orçado × realizado.")]
    acima = sum(1 for x in so if x["realizado"] > x["orcado"])
    return [kpis([K(f"Orçado {_rot(B.mes)}", _mi(o["total"]["orcado"]) if o else "–"),
                  K(f"Realizado {_rot(B.mes)}", _mi(o["total"]["realizado"]) if o else "–", (_delta(o["total"]["realizado"], o["total"]["orcado"]) or "") if o else ""),
                  K("Orçado no período", _mi(ac["total"]["orcado"]) if ac else "–", B.per_rot),
                  K("Realizado no período", _mi(ac["total"]["realizado"]) if ac else "–", (_delta(ac["total"]["realizado"], ac["total"]["orcado"]) or "") if ac else ""),
                  K("Meses acima do orçado", f"{acima} de {len(so)}" if so else "–", "realizado > orçado")], 3),
            nota("Desvio = realizado − orçado: positivo é estouro. Orçamento ADM consolidado das unidades.")]


def b_adm_serie(B: Base) -> list:
    ap = B.adm_periodo()
    if not ap or len(ap.get("serie_orc_g") or []) < 2:
        return [nota("O orçado × realizado mês a mês aparece depois de importar o Orçamento ADM (2 meses ou mais).")]
    sg = ap["serie_orc_g"]
    rows = [("norm", [_rot(x["mes"]), _n0(x["orcado"]), _n0(x["realizado"]), _n0(x["realizado"] - x["orcado"])]) for x in sg]
    return [barras([_rot_curto(x["mes"]) for x in sg], [x["realizado"] - x["orcado"] for x in sg], fmt="mi2", titulo="Desvio mensal: realizado − orçado (R$ MM)", h=90),
            tab(["Mês", "Orçado (R$)", "Realizado (R$)", "Desvio (R$)"], rows, [1, 1.5, 1.5, 1.5])]


def b_adm_grupos(B: Base) -> list:
    ap = B.adm_periodo()
    if not ap or not (ap["orc_mes"] or ap["orc_per"]):
        return [nota("Falta importar o Orçamento ADM (aba Importações V2).")]
    o, ac = ap["orc_mes"], ap["orc_per"]
    gm = {g["codigo"]: g for g in (o["grupos"] if o else [])}
    ga = {g["codigo"]: g for g in (ac["grupos"] if ac else [])}
    rows = []
    for cod in sorted(set(gm) | set(ga)):
        g1, g2 = gm.get(cod), ga.get(cod)
        gu = g1 or (g2 if B.um_mes else None)
        cells = [cod, ("  " * cod.count(".")) + str((g1 or g2)["conta"] or cod)[:34]]
        cells += [_z0(gu["orcado"]) if gu else "–", _z0(gu["realizado"]) if gu else "–", _n0(gu["desvio"]) if gu else "–"]
        if not B.um_mes:
            cells += [_z0(g2["orcado"]) if g2 else "–", _z0(g2["realizado"]) if g2 else "–", _n0(g2["desvio"]) if g2 else "–"]
        rows.append(("norm", cells))
    if not rows:
        return [nota("Sem grupos de despesa com orçamento no período.")]
    head = ["Código", "Grupo", f"Orçado {_rot(B.mes)}", f"Realizado {_rot(B.mes)}", f"Desvio {_rot(B.mes)}"] + ([f"Orçado {B.acum}", f"Realizado {B.acum}", f"Desvio {B.acum}"] if not B.um_mes else [])
    pesos = [0.9, 2.6, 1.1, 1.1, 1.0] + ([1.2, 1.2, 1.1] if not B.um_mes else [])
    return [tab(head, rows, pesos, ["l", "l"] + ["r"] * (len(head) - 2), fs=6.2, rh=12.4),
            nota("Desvio = realizado − orçado: positivo é estouro. O orçamento está consolidado das unidades; valores em R$ (sem centavos).")]


def b_adm_contas(B: Base) -> list:
    ap = B.adm_periodo()
    base_c = (ap["orc_per"] or ap["orc_mes"]) if ap else None
    if not base_c:
        return [nota("Falta importar o Orçamento ADM (aba Importações V2).")]
    cs = base_c["acima"]
    if not cs:
        return [nota("Nenhuma conta passou do orçado no período.")]
    return [tab(["Conta", "Orçado", "Realizado", "Desvio"], [("norm", [f"{x['codigo']} · {x['conta']}"[:58], _n0(x["orcado"]), _n0(x["realizado"]), _n0(x["desvio"])]) for x in cs],
                [4.2, 1.4, 1.4, 1.4])]


def _adm_dfs(B: Base):
    ap = B.adm_periodo()
    if not ap or not (ap["linhas_per"] or ap["linhas_mes"]):
        return None, None
    chaves = B.memo("outros_dir", lambda: [c["chave"] for c in P.credor_grupo_ativos(B.conn)] if P.credor_grupo_instalado(B.conn) else [])
    cols = ["plano_cod", "plano_nome", "credor", "unidade", "valor"]
    df_l = DD.marcar_outros_dir(pd.DataFrame(ap["linhas_mes"], columns=cols), chaves)
    df_a = DD.marcar_outros_dir(pd.DataFrame(ap["linhas_per"] or ap["linhas_mes"], columns=cols), chaves)
    return df_l, df_a


def b_adm_unidades(B: Base) -> list:
    df_l, df_a = _adm_dfs(B)
    if df_a is None or (not len(df_l) and not len(df_a)):
        return [nota("Falta sincronizar as contas pagas do período (nenhum pagamento da administração).")]
    un_mes = df_l.groupby("unidade")["valor"].sum() if len(df_l) else pd.Series(dtype=float)
    un_ano = df_a.groupby("unidade")["valor"].sum() if len(df_a) else pd.Series(dtype=float)
    nomes = sorted(set(un_mes.index) | set(un_ano.index), key=lambda u: (-float(un_ano.get(u, 0.0)), -float(un_mes.get(u, 0.0))))
    tot = float(un_ano.sum())
    rows = [("norm", [u[:44], _z0(float(un_mes.get(u, 0.0))), _n0(float(un_ano.get(u, 0.0))), _pc(float(un_ano.get(u, 0.0)) / tot) if tot else "–"]) for u in nomes]
    rows.append(("tot", ["Total", _n0(float(un_mes.sum())), _n0(tot), "100,0%"]))
    return [tab(["Unidade", _rot(B.mes), B.acum, "% do período"], rows, [3.4, 1.4, 1.6, 1.1]),
            nota(f"Pago nas unidades da administração (contas pagas, inclui pessoal). Mês = {_rot(B.mes)}; período = {B.per_rot}.")]


def b_adm_credores(B: Base) -> list:
    df_l, df_a = _adm_dfs(B)
    if df_a is None or (not len(df_l) and not len(df_a)):
        return [nota("Falta sincronizar as contas pagas do período (nenhum pagamento da administração).")]
    c_mes = df_l.groupby("credor_exib")["valor"].sum() if len(df_l) else pd.Series(dtype=float)
    c_ano = df_a.groupby("credor_exib")["valor"].sum() if len(df_a) else pd.Series(dtype=float)
    nomes = sorted(set(c_mes.index) | set(c_ano.index), key=lambda c: (-float(c_ano.get(c, 0.0)), -float(c_mes.get(c, 0.0))))
    tot = float(df_a["valor"].sum())
    rows = [("norm", [c[:56], _z0(float(c_mes.get(c, 0.0))), _n0(float(c_ano.get(c, 0.0))), _pc(float(c_ano.get(c, 0.0)) / tot) if tot else "–"]) for c in nomes[:30]]
    return [tab(["Credor", _rot(B.mes), B.acum, "% do total"], rows, [3.6, 1.3, 1.6, 1.0]),
            nota(f"{min(30, len(nomes))} de {len(nomes)} credores. “Outros credores/Dir” junta numa linha os credores do grupo definido pela contabilidade.")]


# ------------------------------------------------------------------ DESPESAS
def _desp(B: Base):
    dd = B.esc(B.despesas())
    return dd


def b_desp_kpis(B: Base) -> list:
    dd = _desp(B)
    if not len(dd):
        return [nota("Falta sincronizar as contas pagas do período" + (" (ou nenhuma despesa nas obras escolhidas)." if B.filtra_obra else "."))]
    tot_ano = float(dd["valor"].sum())
    dm = dd[dd["mes"] == B.mes]
    tot_mes = float(dm["valor"].sum()) if len(dm) else 0.0
    ca, cm = DD.total_por(dd), DD.total_por(dm)
    top5, top12 = sum(x[1] for x in cm[:5]), sum(x[1] for x in ca[:12])
    return [kpis([K(f"Pago em {_rot(B.mes)}", _mi(tot_mes), "exceto contas de pessoas"), K(f"Top 5 de {_rot(B.mes)}", _pc(top5 / tot_mes) if tot_mes else "–", "do total do mês"),
                  K(f"Pago {B.acum}", _mi(tot_ano), "exceto contas de pessoas"), K(f"Top 12 {B.acum}", _pc(top12 / tot_ano) if tot_ano else "–", "do total do período")], 4)]


def b_desp_top12(B: Base) -> list:
    dd = _desp(B)
    if not len(dd):
        return [nota("Falta sincronizar as contas pagas do período.")]
    tot = float(dd["valor"].sum())
    ca = DD.total_por(dd)[:12]
    return [tab(["Conta", f"Acumulado {B.acum}", "% do período"], [("norm", [x[0][:60], _n0(x[1]), _pc(x[1] / tot) if tot else "–"]) for x in ca], [4.4, 1.7, 1.1]),
            nota("Contas pagas, exceto as contas de pessoas e encargos (aba Pessoas), conforme as regras do Painel EnerMais.")]


def b_desp_top5(B: Base) -> list:
    dd = _desp(B)
    dm = dd[dd["mes"] == B.mes] if len(dd) else dd
    if not len(dm):
        return [nota(f"Sem despesas pagas em {_rot(B.mes)}.")]
    tot = float(dm["valor"].sum())
    return [tab(["Conta", _rot(B.mes), "% do mês"], [("norm", [x[0][:60], _n0(x[1]), _pc(x[1] / tot) if tot else "–"]) for x in DD.total_por(dm)[:5]], [4.4, 1.7, 1.1])]


def b_desp_evolucao(B: Base) -> list:
    dd = B.esc(B.despesas_12())
    if not len(dd):
        return [nota("Falta sincronizar as contas pagas do período.")]
    vals = DD.serie_mensal(dd, B.meses_g, None)
    return [barras([_rot_curto(m) for m in B.meses_g], vals, fmt="mi")]


def b_desp_credores(B: Base) -> list:
    dd = _desp(B)
    cr = DD.agrupar(dd, "credor", B.mes) if len(dd) else {"linhas": [], "n": 0, "total": 0.0}
    if not cr["linhas"]:
        return [nota("Sem credores no período.")]
    return [tab(["Credor", B.acum, "% do filtro", _rot(B.mes)], [("norm", [x["chave"][:56], _n0(x["acumulado"]), _pc(x["acumulado"] / cr["total"]) if cr["total"] else "–", _z0(x["mes"])]) for x in cr["linhas"]],
                [3.8, 1.6, 1.0, 1.4]),
            nota(("Todos os credores." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores."))]


def b_desp_obras(B: Base) -> list:
    dd = _desp(B)
    ob = DD.agrupar(dd, "cc", B.mes) if len(dd) else {"linhas": [], "n": 0, "total": 0.0}
    if not ob["linhas"]:
        return [nota("Sem despesas por obra / centro de custo no período.")]
    return [tab(["Obra / centro de custo", B.acum, "%", _rot(B.mes)], [("norm", [x["chave"][:56], _n0(x["acumulado"]), _pc(x["acumulado"] / ob["total"]) if ob["total"] else "–", _z0(x["mes"])]) for x in ob["linhas"]],
                [3.8, 1.6, 0.9, 1.4]),
            nota("Obra pelo centro de custo do lançamento no pagamento." + ("" if ob["n"] <= len(ob["linhas"]) else f" Top {len(ob['linhas'])} de {ob['n']}."))]


# ------------------------------------------------------------------ PESSOAS
def _pessoas_base(B: Base):
    def f():
        ctx = B.ctx
        pes = ctx["pessoas"]
        dfp = B.pagos()[0]
        pj = DD.pj_do_mes(dfp, B.mes)
        clt = pes["folha"]["total"]["colab"] if pes else None
        ms = PER.meses_entre(B.mes_ini, B.mes)
        n_mes = (clt + pj["total"]) if clt is not None and (pj["total"] or len(dfp)) else None
        hist = B.hist
        hc_hist = list(hist["headcount"]) if hist and hist.get("headcount") else []
        hc_por_mes = {f"{hist['ate'][:4]}-{i + 1:02d}": v for i, v in enumerate(hc_hist)} if hist else {}
        if n_mes is None and B.mes in hc_por_mes:
            n_mes = hc_por_mes[B.mes]
        antes = [m for m in ms if m < B.mes]
        soma_antes = sum(hc_por_mes[m] for m in antes) if antes and all(m in hc_por_mes for m in antes) else None
        return {"pes": pes, "dfp": dfp, "pj": pj, "clt": clt, "ms": ms, "n_mes": n_mes, "hc_por_mes": hc_por_mes, "soma_antes": soma_antes}
    return B.memo("pessoas_base", f)


def _ob_base(B: Base):
    ob = B.ctx["obras"]
    v = B.ctx["dre"]["valores"]
    rec = ob["total"]["receita"] if ob else v["01"]
    cus = abs(ob["total"]["custo"]) if ob else abs(v["04"])
    bdi = ob["total"]["bdi"] if ob else v["05"]
    return rec, cus, bdi


def b_pes_kpis(B: Base) -> list:
    S = _pessoas_base(B)
    if not S["n_mes"]:
        return [nota("Faltam os recibos da folha e as contas pagas deste mês.")]
    rec, cus, bdi = _ob_base(B)
    n = S["n_mes"]
    return [kpis([K(f"Colaboradores {_rot(B.mes)}", f"{int(n):,}".replace(",", "."), (f"{S['clt']} CLT + {S['pj']['total']} PJ" if S["clt"] is not None else "")),
                  K("Receita por colaborador", _mi(rec / n)), K("Custo por colaborador", _mi(cus / n)), K("BDI por colaborador", _mi(bdi / n))], 4),
            nota("Colaboradores = CLT pelos recibos da folha + PJ pelos credores de “Salários PJ” pagos no mês. Receita, custo e BDI do mês de referência (tabela de obras).")]


def b_pes_headcount(B: Base) -> list:
    S = _pessoas_base(B)
    hc = [(m, S["hc_por_mes"].get(m, S["n_mes"] if m == B.mes else None)) for m in B.meses_g]
    hc = [(m, x) for m, x in hc if x is not None]
    if not hc:
        return [nota("O headcount mensal aparece quando há folha importada ou o histórico do painel da contabilidade.")]
    return [barras([_rot_curto(m) for m, _ in hc], [x for _, x in hc], fmt="int", unidade="colaboradores")]


def b_pes_custos(B: Base) -> list:
    S = _pessoas_base(B)
    pdf_ = B.esc(B.pessoas_df())
    if not len(pdf_):
        return [nota("Falta sincronizar as contas pagas do período" + (" (ou nenhuma conta de pessoas nas obras escolhidas)." if B.filtra_obra else "."))]
    tabp = DD.tabela_pessoas(pdf_, B.mes, S["n_mes"], S["soma_antes"], meses=S["ms"])
    lista = [x for x in tabp if x["mes"] or x["acum_antes"]]
    if not lista:
        return [nota("Sem custos prioritários com pessoas no período.")]
    um = B.um_mes
    head = ["Conta", _rot(B.mes), "% do mês", "R$/colab. mês", "Acum. até mês anterior", "R$/colab. acum."] + ([] if um else [f"Total {B.acum}", f"R$/colab. {B.acum}"]) + ["Variação"]
    rows = []
    for x in lista:
        cells = [x["conta"][:40], _n0(x["mes"]), _pc(x["pct_mes"], 2), _z0(x["por_colab_mes"]) if x["por_colab_mes"] is not None else "–", _z0(x["acum_antes"]),
                 _z0(x["por_colab_acum"]) if x["por_colab_acum"] is not None else "–"]
        if not um:
            cells += [_z0(x["periodo"]), _z0(x["por_colab_periodo"]) if x["por_colab_periodo"] is not None else "–"]
        cells.append(_pc(x["variacao"]) if x["variacao"] is not None else "N/A")
        rows.append(("norm", cells))
    pesos = [2.6, 1.0, 0.8, 1.0, 1.2, 1.0] + ([] if um else [1.1, 1.0]) + [0.8]
    return [tab(head, rows, pesos, fs=6.2, rh=12.4),
            nota(f"Contas de pessoal de obra (2.01.02) e ADM (2.02.01), sem salários CLT/PJ e premiações. Total do mês (todas as contas): {_n2(sum(x['mes'] for x in tabp))}. "
                 "R$/colab. acumulado = acumulado até o mês anterior ÷ soma do headcount mensal desses meses" + ("." if S["soma_antes"] else " (indisponível sem o headcount dos meses anteriores)."))]


def b_pes_credores(B: Base) -> list:
    pdf_cr = B.esc(B.pessoas_sem_grupo())
    cr = DD.agrupar(pdf_cr, "credor", B.mes) if len(pdf_cr) else {"linhas": [], "n": 0, "total": 0.0}
    if not cr["linhas"]:
        return [nota("Sem credores de pessoas no período.")]
    return [tab(["Credor", B.acum, "%", _rot(B.mes)], [("norm", [x["chave"][:56], _n0(x["acumulado"]), _pc(x["acumulado"] / cr["total"]) if cr["total"] else "–", _z0(x["mes"])]) for x in cr["linhas"]],
                [3.8, 1.6, 0.9, 1.4]),
            nota(("Todos os credores." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores.") + " Sem os credores do grupo ENERMAIS (as seis empresas).")]


def b_pes_obras(B: Base) -> list:
    pdf_cr = B.esc(B.pessoas_sem_grupo())
    ob = DD.agrupar(DD.rotular_obras(pdf_cr, B.nomes_obras()), "obra_rot", B.mes, top=25) if len(pdf_cr) else {"linhas": [], "n": 0, "total": 0.0}
    if not ob["linhas"]:
        return [nota("Sem custos de pessoas por obra no período.")]
    return [tab(["Obra", B.acum, "%", _rot(B.mes)], [("norm", [x["chave"][:56], _n0(x["acumulado"]), _pc(x["acumulado"] / ob["total"]) if ob["total"] else "–", _z0(x["mes"])]) for x in ob["linhas"]],
                [3.8, 1.6, 0.9, 1.4]),
            nota("Centros de custo ligados à obra pelo de-para, na mesma linguagem da aba Obras. Administração e centros sem de-para aparecem à parte.")]


# ------------------------------------------------------------------ FOLHA PJ
def _pj_filtrada(B: Base):
    """(dados do mes, colaboradores PJ filtrados) com os filtros do relatorio (obras, empresa que pagou, situacao)."""
    d = B.pj_dados()
    pessoas = d["pessoas"]
    obras_nomes = None
    if B.filtra_obra:
        mapa = B.nomes_por_codigo()
        obras_nomes = set()
        for c in B.obras:
            obras_nomes |= mapa.get(c, set())
            if c == "99":
                obras_nomes.add(FP.SEDE)
        if not obras_nomes:
            return d, []
    return d, FP.filtrar(pessoas, obras=obras_nomes, empresas=B.empresas, situacoes=B.situacoes)


def _pj_filtros_txt(B: Base) -> str:
    partes = []
    if B.filtra_obra:
        partes.append("obras " + ", ".join(B.obras))
    if B.empresas:
        partes.append("empresa(s) " + ", ".join(FP.nome_empresa_curto(e) for e in B.empresas))
    if B.situacoes:
        partes.append("situação " + ", ".join(B.situacoes))
    return ("Filtros: " + "; ".join(partes) + ".") if partes else ""


def _sem_pj(B: Base, d: dict, pes: list) -> list | None:
    if not d["pessoas"]:
        return [nota(f"Não há contas PJ (Salários PJ, Premiações ou Multas Contratuais) pagas ou a pagar em {_rot(B.mes)}.")]
    if not pes:
        return [nota("Nenhum colaborador PJ com esses filtros.")]
    return None


def _nota_mes_pj(B: Base) -> list:
    return [nota(f"A Folha PJ mostra sempre o mês de referência ({_rot(B.mes)}); não soma o período.")] if not B.um_mes else []


def b_pj_cards(B: Base) -> list:
    d, pes = _pj_filtrada(B)
    r = _sem_pj(B, d, pes)
    if r:
        return r
    tot = FP.somar(pes)
    cards = FP.cards_empresas(pes)
    itens = [K("Total PJ", _mi(tot["custo_total"]), f"{tot['n']} colaboradores · pago {_mi(tot['pago'])} · a pagar {_mi(tot['a_pagar'])}", dark=True)]
    for c in cards:
        itens.append(K(FP.nome_empresa_curto(c["empresa"]), _mi(c["total"]["custo_total"]),
                       f"{c['n']} colab. · diretoria {_mi(c['diretoria']['custo_total'])} · pago {_mi(c['total']['pago'])} · a pagar {_mi(c['total']['a_pagar'])}"))
    els = [sec(f"Custo PJ · {_rot(B.mes)} (honorários + premiações + multa + ajuda de custo + vale alimentação − descontos)")]
    if _pj_filtros_txt(B):
        els.append(nota(_pj_filtros_txt(B)))
    els.append(kpis(itens, 3))
    faltas = [txt for cond, txt in ((d["sem_flash"], "Flash do mês"), (d["sem_mapa"], "mapa de colaboradores"), (d["sem_diretoria"], "credores da diretoria")) if cond and d["instalado"]]
    if faltas:
        els.append(nota("Ainda não carregado: " + ", ".join(faltas) + ". Esses itens aparecem vazios (o custo vem só do Sienge)."))
    return els + _nota_mes_pj(B)


def b_pj_kpis(B: Base) -> list:
    d, pes = _pj_filtrada(B)
    r = _sem_pj(B, d, pes)
    if r:
        return r
    t = FP.somar(pes)
    return [kpis([K("Honorários", _mi(t["honorarios"])), K("Premiações", _mi(t["premiacao"])), K("Ajuda de custo (Flash)", _mi(t["ajuda_custo"])), K("Vale alimentação (Flash)", _mi(t["alimentacao"])),
                  K("Multa contratual", _mi(t["multa"])), K("Descontos", _mi(t["desconto"])), K("Documentos", f"{t['n_docs']:,}".replace(",", "."))], 4),
            nota("Descontos aparecem com sinal negativo porque reduzem o custo (o imposto retido não entra como desconto: fica no custo). Flash = premiação no cartão (ajuda de custo) e refeição/alimentação (vale alimentação).")]


def b_pj_top_obras(B: Base) -> list:
    d, pes = _pj_filtrada(B)
    r = _sem_pj(B, d, pes)
    if r:
        return r
    top = FP.top_obras(pes)
    if not top:
        return [nota("Sem obras para destacar (só sede, diretoria ou obras com vários centros).")]
    return [kpis([K(o["obra"][:42], _mi(o["custo_total"]), f"{o['n']} colaboradores") for o in top], 3), nota("Sem a diretoria e sem os grupos que não são obra (sede/administração e “vários centros”).")]


def b_pj_obras(B: Base) -> list:
    d, pes = _pj_filtrada(B)
    r = _sem_pj(B, d, pes)
    if r:
        return r
    obras = FP.resumo_obras(pes)
    rows = []

    def linha(nome, x, tipo):
        return (tipo, [nome[:46], str(x["n"]), _z0(x["honorarios"]), _z0(x["premiacao"]), _z0(x["ajuda_custo"] + x["alimentacao"]), _z0(x["multa"]), _z0(x["desconto"]), _n0(x["custo_total"]), _z0(x["pago"]), _z0(x["a_pagar"])])
    for o in obras:
        rows.append(linha(o["obra"], o, "sub"))
        for c in o["centros"]:
            rows.append(linha("   " + c["centro"], c, "norm"))
    t = FP.somar(pes)
    rows.append(linha("Total", {**t, "n": t["n"]}, "tot"))
    return [tab(["Obra / centro de custo", "Colab.", "Honorários", "Premiações", "Benef. Flash", "Multa", "Descontos", "Custo total", "Pago", "A pagar"], rows, [3.0, 0.6, 1.1, 1.0, 1.0, 0.8, 0.9, 1.2, 1.1, 1.0],
                fs=6.2, rh=12.2),
            nota("Valores em R$ (sem centavos). Benefícios Flash = ajuda de custo + vale alimentação. Pago e a pagar são líquidos de desconto.")] + ([nota(_pj_filtros_txt(B))] if _pj_filtros_txt(B) else [])


def b_pj_colab(B: Base) -> list:
    d, pes = _pj_filtrada(B)
    r = _sem_pj(B, d, pes)
    if r:
        return r
    lista = FP.agrupar_diretoria(pes)
    rows = [("norm", [(p["nome"] + (" · novo" if p["novo"] else ""))[:34], (p["funcao"] or "")[:26], (FP.nome_empresa_curto(p["empresa"]) if p["empresa"] else "–")[:14], (p["centro"] or "")[:30],
                      _z0(p["honorarios"]), _z0(p["premiacao"]), _z0(p["ajuda_custo"] + p["alimentacao"]), _z0(p["multa"]), _z0(p["desconto"]), _n0(p["custo_total"]), _z0(p["pago"]), _z0(p["a_pagar"])])
            for p in lista]
    t = FP.somar(pes)
    rows.append(("tot", [f"Total · {len(lista)} linhas", "", "", "", _n0(t["honorarios"]), _n0(t["premiacao"]), _n0(t["ajuda_custo"] + t["alimentacao"]), _n0(t["multa"]), _n0(t["desconto"]), _n0(t["custo_total"]),
                         _n0(t["pago"]), _n0(t["a_pagar"])]))
    return [tab(["Colaborador", "Função", "Empresa", "Centro de custo", "Honorários", "Prem.", "Flash", "Multa", "Desc.", "Custo total", "Pago", "A pagar"], rows,
                [2.1, 1.5, 0.9, 1.9, 1.0, 0.8, 0.8, 0.7, 0.7, 1.0, 0.9, 0.9], ["l", "l", "l", "l"] + ["r"] * 8, fs=5.6, rh=11.2),
            nota("Valores em R$ (sem centavos). “novo” = entrou na folha neste mês. A diretoria aparece numa linha só (“Demais credores - diretoria”), sempre por último. Flash = ajuda de custo + vale alimentação.")] \
        + ([nota(_pj_filtros_txt(B))] if _pj_filtros_txt(B) else [])


def b_pj_docs(B: Base) -> list:
    d, pes = _pj_filtrada(B)
    r = _sem_pj(B, d, pes)
    if r:
        return r
    docs = FP.filtrar_documentos(d["documentos"], pes) if (B.filtra_obra or B.empresas or B.situacoes) else d["documentos"]
    if not docs:
        return [nota("Nenhum documento para a seleção.")]
    rows = [("norm", [x["situacao"], _data(x["data"]), x["documento"][:18], x["nome"][:28], FP.nome_empresa_curto(x["empresa"])[:12], f"{x['plano']} {x['plano_nome']}"[:34], _n2(x["bruto"]), _z0(x["desconto"]),
                      _n2(x["valor_liquido"])]) for x in docs]
    return [tab(["Situação", "Data", "Documento", "Colaborador", "Empresa", "Conta", "Bruto", "Desc.", "Líquido"], rows, [0.8, 1.0, 1.2, 2.2, 1.0, 2.5, 1.2, 0.8, 1.2],
                ["l", "l", "l", "l", "l", "l", "r", "r", "r"], fs=5.8, rh=11.2),
            nota(f"{len(docs)} documentos · líquido {_n2(sum(x['valor_liquido'] for x in docs))}. Um documento por linha; se o documento tem mais de uma conta, cada conta é uma linha.")]


# ------------------------------------------------------------------ FOLHA CLT
def _clt_filtrada(B: Base) -> list:
    return DD.filtrar_clt(B.clt_todos(), B.obras or None)


def _sem_clt(B: Base) -> list | None:
    if not B.clt_todos():
        return [nota("Faltam os recibos da folha deste mês: envie o PDF em Importações V2.")]
    if not _clt_filtrada(B):
        return [nota("Nenhum colaborador CLT nas obras escolhidas.")]
    return None


def _he(m) -> str:
    return DD.fmt_horas(m)


def b_clt_cards(B: Base) -> list:
    r = _sem_clt(B)
    if r:
        return r
    lista = _clt_filtrada(B)
    cf = DD.cards_folha(lista)
    t = cf["total"]
    rows = [("norm", [e["empresa"][:30], str(e["n"]), _n0(e["liquido"]), _n0(e["he_dsr"]), _he(e["he_min"]), str(e["n_he"]), _pc(e["he_pct"]), _z0(e["pensao"]), _z0(e["taxa_assist"])]) for e in cf["por_empresa"]]
    rows.append(("tot", ["Total", str(t["n"]), _n0(t["liquido"]), _n0(t["he_dsr"]), _he(t["he_min"]), str(t["n_he"]), _pc(t["he_pct"]), _n0(t["pensao"]), _n0(t["taxa_assist"])]))
    els = [sec(f"Folha consolidada · {_rot(B.mes)}" + (f" · obras {', '.join(B.obras)}" if B.filtra_obra else "")),
           kpis([K("Colaboradores CLT", f"{t['n']:,}".replace(",", ".")), K("Líquido da folha", _mi(t["liquido"])), K("HE + DSR", _mi(t["he_dsr"]), (_pc(t["he_pct"]) + " da remuneração") if t["he_pct"] is not None else ""),
                 K("Horas extras", _he(t["he_min"]) + (" h" if t["he_min"] else ""), f"{t['n_he']} colaboradores com HE"), K("Pensão judicial", _n2(t["pensao"])), K("Taxa assistencial", _n2(t["taxa_assist"]))], 3),
           tab(["Empresa", "Colab.", "Líquido", "HE + DSR", "Horas extras", "Com HE", "HE ÷ rem.", "Pensão", "Taxa assist."], rows, [2.4, 0.7, 1.2, 1.1, 1.0, 0.7, 0.9, 0.9, 1.0], fs=6.4),
           nota("Fonte: recibos da folha importados. HE ÷ remuneração segue a regra da contabilidade (proventos − HE − DSR − descontos). Valores em R$ (sem centavos).")]
    return els


def b_clt_top_obras(B: Base) -> list:
    r = _sem_clt(B)
    if r:
        return r
    cf = DD.cards_folha(_clt_filtrada(B))
    if not cf["top_obras"]:
        return [nota("Nenhuma obra com horas extras na seleção.")]
    nomes = B.nomes_obras()
    return [kpis([K(f"{o['obra']} · {nomes.get(o['obra']) or o['nome'] or 'sem nome'}"[:42], _mi(o["he_dsr"]), f"{_he(o['he_min'])} h · {o['n_he']} de {o['n']} com HE") for o in cf["top_obras"]], 3)]


def b_clt_selecao(B: Base) -> list:
    r = _sem_clt(B)
    if r:
        return r
    lista = _clt_filtrada(B)
    t = DD.somar_clt(lista)
    return [sec("Seleção: " + (f"obras {', '.join(B.obras)}" if B.filtra_obra else "todas as obras")),
            kpis([K("Colaboradores CLT na seleção", str(len(lista))), K("Líquido CLT", _mi(t["liquido"])), K("HE + DSR", _mi(t["he_dsr"])),
                  K("Horas extras", _he(t["he_min"]) + (" h" if t["he_min"] else "")), K("HE ÷ remuneração", _pc(t["he_pct"]))], 3)]


def b_clt_he_receita(B: Base) -> list:
    ctx = B.ctx
    pes = ctx["pessoas"]
    sf = HIST.serie_he_combinada(B.hist, pes["serie"] if pes else [])
    ev = DD.evolucao_he_receita(sf, ctx["serie"], B.meses_g)
    com = [x for x in ev if x["he_pct"] is not None]
    if len(com) < 2:
        return [nota("A série mensal de HE aparece com 2 ou mais meses de folha (ou com o histórico do painel).")]
    fv = lambda x: "n/d" if x is None else _pc(x, 1)                              # noqa: E731
    rows = [("norm", [_rot(x["mes"]), _pc(x["he_pct"]) if x["he_pct"] is not None else "–", _z0(x["he"]) if x["he"] is not None else "–", fv(x["var_he"]), _z0(x["receita"]) if x["receita"] is not None else "–",
                      fv(x["var_receita"])]) for x in ev]
    cp = DD.comparar_periodos(sf, ctx["serie"], B.mes_ini, B.mes)
    els = [barras([_rot_curto(x["mes"]) for x in com], [round(x["he_pct"] * 100, 1) for x in com], fmt="p1", unidade="% HE ÷ remuneração", titulo="HE + DSR ÷ remuneração, mês a mês (%)", h=90),
           tab(["Mês", "HE ÷ rem.", "Custo de HE (R$)", "Var. HE", "Receita (R$)", "Var. receita"], rows, [1, 1, 1.4, 0.9, 1.5, 0.9], fs=6.6)]
    fvp = lambda x: "n/d" if x is None else _pc(x, 1)                                # noqa: E731
    els.append(nota(f"Período {B.per_rot} × período anterior ({PER.rotulo(cp['meses_anterior'][0], cp['meses_anterior'][-1])}): custo de HE {fvp(cp['var_he'])}"
                    + (f" ({_mi(cp['he_anterior'])} → {_mi(cp['he_atual'])})" if cp["var_he"] is not None else "") + f"; receita {fvp(cp['var_receita'])}"
                    + (f" ({_mi(cp['receita_anterior'])} → {_mi(cp['receita_atual'])})" if cp["var_receita"] is not None else "") + ". n/d = falta algum mês de dado num dos períodos."))
    if {x["origem"] for x in sf} == {"historico", "app"}:
        els.append(nota("Atenção: os meses do histórico (painel da contabilidade) usam como base proventos menos HE; os meses com folha no app usam a remuneração líquida. Pode haver um degrau entre as duas fontes."))
    return els


def b_clt_empresa_obra(B: Base) -> list:
    pes = B.ctx["pessoas"]
    if not pes:
        return [nota("Faltam os recibos da folha deste mês: envie o PDF em Importações V2.")]
    fo = pes["folha"]
    po = sorted(fo["por_obra"].values(), key=lambda x: -x["colab"])
    if B.filtra_obra:
        po = [x for x in po if x["codigo"] in B.obras]
    els = [tab(["Empresa", "Colab.", "Remuneração", "HE + DSR", "HE ÷ rem.", "Custo (proventos + FGTS)"],
               [("norm", [e["empresa"][:30], str(e["colab"]), _n0(e["base_he"]), _n0(e["hora_extra"] + e["dsr_he"]), _pc(e["he_pct"]), _n0(e["custo"])]) for e in fo["por_empresa"]], [2.6, 0.8, 1.3, 1.2, 1.0, 1.7])]
    if po:
        els.append(tab(["Obra", "Nome", "Colab.", "Remuneração", "HE + DSR", "HE ÷ rem."], [("norm", [x["codigo"], (x["nome"] or "")[:34], str(x["colab"]), _n0(x["base_he"]), _n0(x["hora_extra"] + x["dsr_he"]), _pc(x["he_pct"])]) for x in po],
                       [0.7, 3.0, 0.7, 1.4, 1.2, 1.0], ["l", "l", "r", "r", "r", "r"]))
    els.append(nota("A tabela por empresa é a do mês todo (a folha por empresa não é dividida por obra)." if B.filtra_obra else "Custo = proventos + FGTS do mês (não inclui INSS patronal, férias/13º provisionados nem PJ)."))
    return els


def b_clt_lista(B: Base) -> list:
    r = _sem_clt(B)
    if r:
        return r
    lista = _clt_filtrada(B)
    rows = [("norm", [x["nome"][:30], (x["cargo"] or "")[:26], x["empresa"][:14], x["obra"], (x["canteiro"] or "")[:22], _n2(x["liquido"]), _he(x["he_min"]), _z0(x["he"]) if x["he"] > 0.005 else "–",
                      _z0(x["dsr"]) if x["dsr"] > 0.005 else "–"]) for x in lista]
    t = DD.somar_clt(lista)
    rows.append(("tot", [f"Total · {t['n']}", "", "", "", "", _n2(t["liquido"]), _he(t["he_min"]), _n0(t["he"]), _n0(t["dsr"])]))
    return [tab(["Colaborador", "Cargo", "Empresa", "Obra", "Canteiro", "Líquido", "HE (h)", "HE (R$)", "DSR (R$)"], rows, [2.2, 1.9, 1.0, 0.6, 1.6, 1.1, 0.8, 0.8, 0.8],
                ["l", "l", "l", "l", "l", "r", "r", "r", "r"], fs=5.8, rh=11.2),
            nota("Lista nominal com salário líquido: compartilhe com cuidado. Fonte: recibos da folha importados.")]


# ------------------------------------------------------------------ INDICADORES FINANCEIROS e FINANCIAMENTOS
def _ind(B: Base) -> dict:
    return B.memo("ind", lambda: I.ciclo_e_capital(B.conn, B.mes, False, B.hoje, mes_ini=B.mes_ini, completo=False))


def b_ind_prazos(B: Base) -> list:
    ind = _ind(B)
    pmr, pmp = ind["pmr"], ind["pmp"]
    return [kpis([K("PMR simples", _dias(pmr["simples"]), f"{pmr['n']} títulos a receber"), K("PMR ponderado", _dias(pmr["ponderado"]), "pelo valor do título"),
                  K("PMP simples", _dias(pmp["simples"]), f"{pmp['n']} títulos a pagar"), K("PMP ponderado", _dias(pmp["ponderado"]), "pelo valor do título")], 4),
            kpis([K("Ciclo financeiro · simples (PMR − PMP)", _dias(ind["ciclo_simples"]), "negativo = recebe antes de pagar"),
                  K("Ciclo financeiro · ponderado (PMR − PMP)", _dias(ind["ciclo_ponderado"]), "negativo = recebe antes de pagar")], 2),
            nota(f"Período: {B.per_rot}. Prazo = dias entre a emissão e o vencimento dos títulos EMITIDOS no período, sem documentos de previsão nem títulos desfeitos. Só fornecedores e clientes de verdade: "
                 f"ficaram de fora {pmr['n_fora']} títulos a receber e {pmp['n_fora']} a pagar (sem credor, banco/caixa, financiamentos e empresas do grupo ENERMAIS).")]


def b_ind_giro(B: Base) -> list:
    ind = _ind(B)
    g = ind["gasto"]
    return [kpis([K(f"Gasto do período · {B.per_rot}", _mi(g["total"]), f"{g['dias']} dias"), K("Gasto diário", _mi(g["diario"]), "gasto do período ÷ dias"),
                  K("Necessidade · ponderado", _mi(ind["ncg_ponderado"]), (f"{_n2(g['diario'])} × {_dias(ind['ciclo_ponderado'])}") if ind["ciclo_ponderado"] is not None else ""),
                  K("Necessidade · simples", _mi(ind["ncg_simples"]), (f"{_n2(g['diario'])} × {_dias(ind['ciclo_simples'])}") if ind["ciclo_simples"] is not None else "")], 4),
            nota("Gasto = pagamentos feitos no período, sem previsão e sem transferências entre contas. Necessidade = gasto diário × ciclo financeiro; só aparece valor quando o ciclo é positivo (paga antes de receber).")]


def b_ind_inad(B: Base) -> list:
    venc_ate, pago_ate = I.data_posicao(B.mes, B.hoje, ate_hoje=True)
    ina = B.memo("inad", lambda: I.inadimplencia(B.conn, venc_ate, pago_ate, False, completo=False))
    els = [kpis([K("Vencido a receber", _mi(ina["receber"]["total"]), f"{ina['receber']['n']} títulos"), K("Vencido a pagar", _mi(ina["pagar"]["total"]), f"{ina['pagar']['n']} títulos")], 2),
           nota(f"Posição: vencidos até {_data(venc_ate)} e não pagos até {_data(pago_ate)}. A receber sem clientes do grupo ENERMAIS. "
                + ("Vencimento ORIGINAL (o primeiro vencimento registrado; prorrogação não esconde a dívida)." if ina["usa_vencimento_original"] else "Vencimento atual do título."))]
    for chave, rot, quem in (("receber", "a receber", "Cliente"), ("pagar", "a pagar", "Credor")):
        els.append(tab(["Faixa de atraso", "Títulos", "Valor (R$)"], [("norm", [f["faixa"], str(f["n"]), _n0(f["valor"])]) for f in ina[chave]["faixas"]], [2.2, 0.8, 1.4], titulo=f"Por faixa de atraso · {rot}"))
        if ina[chave]["top"]:
            els.append(tab([quem, "Títulos", "Vencido há mais tempo", "Valor (R$)"], [("norm", [x["nome"][:44], str(x["n"]), _data(x["mais_antigo"]), _n0(x["valor"])]) for x in ina[chave]["top"]],
                           [3.4, 0.7, 1.4, 1.3], ["l", "r", "r", "r"], titulo=f"Maiores · {rot}"))
    return els


def b_ind_receitas(B: Base) -> list:
    _, pago_ate = I.data_posicao(B.mes, B.hoje, ate_hoje=True)
    rec = B.memo("receitas_abertas", lambda: I.receitas_em_aberto(B.conn, pago_ate, False, completo=False))
    if not rec:
        return [nota("Nenhuma conta a receber em aberto na posição.")]
    rows = [("norm", [str(x["cliente"])[:40], str(x["nota"])[:16], _data(x["vencimento"]), _n2(x["valor"]), str(x["atraso"])]) for x in rec]
    rows.append(("tot", [f"Total · {len(rec)} contas", "", "", _n2(sum(float(x["valor"]) for x in rec)), ""]))
    return [tab(["Cliente", "Nota", "Vencimento", "Em aberto (R$)", "Dias de atraso"], rows, [3.2, 1.3, 1.2, 1.5, 1.0], ["l", "l", "r", "r", "r"], fs=6.4, rh=11.8)]


def _fin(B: Base, grupo: str) -> dict:
    return B.memo(("fin", grupo), lambda: I.financiamentos(B.conn, B.hoje, False, grupo))


def _fin_kpis(B: Base, grupo: str) -> list:
    inv = grupo == "investimentos"
    f = _fin(B, grupo)
    nome = "investimento" if inv else "financiamento"
    if not f["por_contrato"]:
        return [nota(f"Nenhum {nome} em aberto na posição de {_data(B.hoje)}.")]
    return [sec(f"Posição de hoje ({_data(B.hoje)}): o que ainda falta pagar; não muda com o período do painel."),
            kpis([K("Saldo devedor", _mi(f["saldo_devedor"]), "demais planos 2.05 (investimentos)" if inv else "capital de giro + financiamentos"), K("Juros a pagar", _mi(f["juros_totais"]), "2.03.02"),
                  K("Desembolso restante", _mi(f["desembolso_total"]), "principal + juros"), K("Contratos ativos", f"{f['contratos']}", f"{f['documentos']} documentos lançados"),
                  K("Custo médio", _pc(f["custo_medio"]), f["custo_medio_origem"] or ""), K("Encerramento mais longo", f["encerramento_mais_longo"].strftime("%m/%Y") if f["encerramento_mais_longo"] else "–", "última parcela em aberto")], 3)]


def _fin_curva(B: Base, grupo: str) -> list:
    f = _fin(B, grupo)
    cur = f["curva"]
    if not cur:
        return [nota("Sem parcelas em aberto para a curva.")]
    tot = [x["principal"] + x["juros"] for x in cur]
    return [barras([str(x["mes"])[-5:] if len(str(x["mes"])) > 7 else str(x["mes"]) for x in cur], tot, fmt="mi", titulo="Desembolso por mês de vencimento (principal + juros)", h=100),
            tab(["Mês", "Principal (R$)", "Juros (R$)", "Total (R$)"], [("norm", [str(x["mes"]), _n0(x["principal"]), _n0(x["juros"]), _n0(x["principal"] + x["juros"])]) for x in cur], [1, 1.5, 1.3, 1.5], fs=6.4, rh=11.6)]


def _fin_categoria(B: Base, grupo: str) -> list:
    f = _fin(B, grupo)
    cat: dict = {}
    for c in f["por_contrato"]:
        a = cat.setdefault(c["categoria"], {"n": 0, "p": 0.0, "j": 0.0})
        a["n"] += 1
        a["p"] += c["principal"]
        a["j"] += c["juros"]
    if not cat:
        return [nota("Sem contratos em aberto.")]
    return [tab(["Categoria", "Contratos", "Principal (R$)", "Juros (R$)"], [("norm", [k[:46], str(v["n"]), _n0(v["p"]), _n0(v["j"])]) for k, v in sorted(cat.items(), key=lambda kv: -kv[1]["p"])], [3.4, 0.9, 1.5, 1.3])]


def _fin_credores(B: Base, grupo: str) -> list:
    f = _fin(B, grupo)
    if not f["por_credor"]:
        return [nota("Sem credores com parcelas em aberto.")]
    return [tab(["Credor", "Contratos", "Principal", "Juros", "% carteira", "Taxa mensal", "Encerramento"],
                [("norm", [x["credor"][:38], str(x["contratos"]), _n0(x["principal"]), _n0(x["juros"]), _pc(x["pct_carteira"]), _pc(x["taxa_mensal"], 2), x["encerramento"].strftime("%m/%Y") if x["encerramento"] else "–"])
                 for x in f["por_credor"]], [3.0, 0.8, 1.3, 1.1, 0.9, 0.9, 1.0], fs=6.4),
            nota("Taxa mensal = taxa cadastrada do contrato; sem cadastro, usa a aproximação implícita. Credor = média ponderada pelo saldo.")]


def _fin_contratos(B: Base, grupo: str) -> list:
    f = _fin(B, grupo)
    if not f["por_contrato"]:
        return [nota("Sem contratos em aberto.")]
    rows = [("norm", [c["credor"][:26], c["categoria"][:22], (c["objeto"] or "")[:22], str(c["chave"])[:14], str(c["parcelas"]), _n0(c["principal"]), _n0(c["juros"]), _data(c["proximo"]),
                      c["encerramento"].strftime("%m/%Y") if c["encerramento"] else "–", _pc(c["taxa_mensal"], 2)]) for c in f["por_contrato"]]
    return [tab(["Credor", "Categoria", "Objeto", "Contrato", "Parc.", "Principal", "Juros", "Próx. venc.", "Encerr.", "Taxa mês"], rows, [1.9, 1.6, 1.6, 1.0, 0.5, 1.1, 0.9, 1.0, 0.8, 0.8],
                ["l", "l", "l", "l", "r", "r", "r", "r", "r", "r"], fs=5.8, rh=11.4)]


# ------------------------------------------------------------------ montagem
FUNCOES = {
    "res_formula": b_res_formula, "res_desvio": b_res_desvio, "res_recomp": b_res_recomp, "res_receita": b_res_receita, "res_dre": b_res_dre,
    "ob_kpis": b_ob_kpis, "ob_tabela": b_ob_tabela, "ob_detalhe": b_ob_detalhe, "ob_categorias": b_ob_categorias, "ob_credores": b_ob_credores, "ob_prejuizo": b_ob_prejuizo, "ob_colab": b_ob_colab,
    "adm_kpis": b_adm_kpis, "adm_serie": b_adm_serie, "adm_grupos": b_adm_grupos, "adm_contas": b_adm_contas, "adm_unidades": b_adm_unidades, "adm_credores": b_adm_credores,
    "desp_kpis": b_desp_kpis, "desp_top12": b_desp_top12, "desp_top5": b_desp_top5, "desp_evolucao": b_desp_evolucao, "desp_credores": b_desp_credores, "desp_obras": b_desp_obras,
    "pes_kpis": b_pes_kpis, "pes_headcount": b_pes_headcount, "pes_custos": b_pes_custos, "pes_credores": b_pes_credores, "pes_obras": b_pes_obras,
    "pj_cards": b_pj_cards, "pj_kpis": b_pj_kpis, "pj_top_obras": b_pj_top_obras, "pj_obras": b_pj_obras, "pj_colab": b_pj_colab, "pj_docs": b_pj_docs,
    "clt_cards": b_clt_cards, "clt_top_obras": b_clt_top_obras, "clt_selecao": b_clt_selecao, "clt_he_receita": b_clt_he_receita, "clt_empresa_obra": b_clt_empresa_obra, "clt_lista": b_clt_lista,
    "ind_prazos": b_ind_prazos, "ind_giro": b_ind_giro, "ind_inad": b_ind_inad, "ind_receitas": b_ind_receitas,
    "fin_kpis": lambda B: _fin_kpis(B, "financiamentos"), "fin_curva": lambda B: _fin_curva(B, "financiamentos"), "fin_categoria": lambda B: _fin_categoria(B, "financiamentos"),
    "fin_credores": lambda B: _fin_credores(B, "financiamentos"), "fin_contratos": lambda B: _fin_contratos(B, "financiamentos"),
    "inv_kpis": lambda B: _fin_kpis(B, "investimentos"), "inv_curva": lambda B: _fin_curva(B, "investimentos"), "inv_categoria": lambda B: _fin_categoria(B, "investimentos"),
    "inv_credores": lambda B: _fin_credores(B, "investimentos"), "inv_contratos": lambda B: _fin_contratos(B, "investimentos"),
}
assert set(FUNCOES) == set(TODAS_CHAVES), set(FUNCOES) ^ set(TODAS_CHAVES)


def texto_filtros(modo: str, mes_ini: str, mes: str, escopo: dict | None, nomes_obras: dict | None = None) -> list:
    """Linhas de texto do que vale neste relatorio (vai na capa)."""
    esc = escopo or {}
    out = [f"Período: {PER.rotulo(mes_ini, mes)} ({modo}) · mês de referência {_rot(mes)}"]
    nomes = nomes_obras or {}
    out.append("Obras: " + (", ".join(f"{c} · {nomes[c]}" if nomes.get(c) else str(c) for c in esc["obras"]) if esc.get("obras") else "todas (geral)"))
    if esc.get("empresas"):
        out.append("Empresa que pagou (PJ): " + ", ".join(FP.nome_empresa_curto(e) for e in esc["empresas"]))
    if esc.get("situacoes"):
        out.append("Situação (PJ): " + ", ".join(esc["situacoes"]))
    return out


def montar(conn, mes_ini: str, mes: str, blocos, modo: str = PER.ANO, escopo: dict | None = None, ctx: dict | None = None, usuario: str = "", mostra_inv: bool = True, hoje=None) -> dict:
    """Calcula so' os blocos marcados. Devolve {'meta', 'abas': [{'aba','rotulo','blocos':[{'key','titulo','els'}]}]} na ordem do painel; bloco que falha vira aviso."""
    escolhidos = [k for k in TODAS_CHAVES if k in set(blocos or ())]
    if not mostra_inv:
        escolhidos = [k for k in escolhidos if not k.startswith("inv_")]
    B = Base(conn, mes_ini, mes, modo, escopo, ctx, hoje)
    abas = []
    for a, rot, itens in CATALOGO:
        out = []
        for k, _r, _p, _o, titulo in itens:
            if k not in escolhidos:
                continue
            try:
                els = FUNCOES[k](B)
            except Exception as exc:                                    # noqa: BLE001
                try:
                    conn.rollback()
                except Exception:                                       # noqa: BLE001
                    pass
                els = [nota(f"Esta informação não pôde ser montada ({type(exc).__name__}). Os dados continuam na tela do painel.")]
            if B.filtra_obra and not BLOCOS_INFO[k]["obra"]:
                els = els + [nota("Esta informação é do grupo todo: não segue o filtro de obras.")]
            out.append({"key": k, "titulo": titulo, "els": els})
        if out:
            abas.append({"aba": a, "rotulo": rot, "blocos": out})
    meta = {"mes": mes, "mes_ini": mes_ini, "modo": modo, "per_rot": PER.rotulo(mes_ini, mes), "gerado_em": agora_br().strftime("%d/%m/%Y %H:%M"), "usuario": usuario,
            "filtros": texto_filtros(modo, mes_ini, mes, escopo, B.nomes_obras() if B.filtra_obra else None), "n_blocos": len(escolhidos)}
    return {"meta": meta, "abas": abas}


def opcoes_obras(conn, mes_ini: str, mes: str, ctx: dict | None = None) -> list:
    """[(codigo, 'codigo · nome')] das obras que aparecem na tabela de Obras do periodo (mais a administracao central, '99'), para o filtro de obras do relatorio."""
    B = Base(conn, mes_ini, mes, PER.ANO, None, ctx)
    nomes = B.nomes_obras()
    ob = B.obras_periodo()[0]
    cods = [l["obra"] for l in ob["linhas"] if l["obra"] != "DEM"] if ob else []
    out = [(c, f"{c} · {nomes.get(c) or c}" if nomes.get(c) else c) for c in cods]
    if "99" not in cods:
        out.append(("99", "99 · Administração central"))
    return out
