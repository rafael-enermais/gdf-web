# -*- coding: utf-8 -*-
"""
GDF - Motor de demonstrativos.

Entrada : contas de balancete por periodo (lista de dicts: id, sint, cl, nome, ant, deb, cred, sal),
          vindas do importador do CSV exportado do sistema contabil.
Saida   : Balanco (3 datas), DRE (3 colunas), 17 indicadores e conferencias.
Sem banco, sem rede, sem Streamlit: so calculo (testavel).

Regras contabeis confirmadas pela contadora em 08/10/2026:
  - o resultado do mes so vai para Prejuizos Acumulados (2.4.13) na virada do mes; o PL do relatorio e' o saldo
    de 2.4.13 + o saldo da conta 8 (resultado em aberto);
  - "Outros ajustes liquidos" e' mantido: plug = resultado implicito no balanco - soma das contas de resultado;
  - EBITDA = EBIT enquanto nao houver depreciacao (dezembro: EBITDA = EBIT + D&A);
  - mes encerrado (classes 4 e 5 com saldo zero): o valor do mes vem do debito, com sinal pela natureza da conta;
    a linha 8 do balancete mensal NAO e' confiavel em mes encerrado.
"""
from __future__ import annotations

TOL = 0.005

# ------------------------------------------------------------------ mapa de contas padrao (Anastacio, v1.0)
# chave, rotulo, secao, prefixos de classificacao, natureza (so resultado: D despesa/custo, C receita)
MAPA_PADRAO = [
    ("dep_vista", "Caixa e depósitos bancários", "BP", ["1.1.01.002"], None),
    ("aplic", "Aplicações financeiras de liquidez imediata", "BP", ["1.1.01.003"], None),
    ("adiant", "Adiantamentos a fornecedores", "BP", ["1.1.04.013"], None),
    ("trib_rec", "Tributos a recuperar", "BP", ["1.1.04.021"], None),
    ("desp_ant_cp", "Despesas pagas antecipadamente", "BP", ["1.1.10"], None),
    ("dep_jud", "Depósitos judiciais", "BP", ["1.2.01.003.013"], None),
    ("desp_ant_lp", "Despesas antecipadas", "BP", ["1.2.01.005"], None),
    ("conc_bruto", "Ativo de concessão — linhas de transmissão (bruto)", "BP", ["1.2.08.001.900"], None),
    ("conc_red", "(−) Ativo de concessão — redutora", "BP", ["1.2.08.001.901"], None),
    ("bndes_cp", "Empréstimos e financiamentos — BNDES (CP)", "BP", ["2.1.01.001"], None),
    ("fornec", "Fornecedores", "BP", ["2.1.03.001"], None),
    ("prov_constr", "Provisão de custo de construção incorrido", "BP", ["2.1.03.002"], None),
    ("imp_rec", "Impostos e contribuições a recolher", "BP", ["2.1.05.001"], None),
    ("trib_ret", "Tributos retidos a recolher", "BP", ["2.1.05.003"], None),
    ("bndes_lp", "Empréstimos e financiamentos — BNDES (LP)", "BP", ["2.2.01.001"], None),
    ("trib_dif", "Tributos diferidos (PIS, COFINS, IRPJ, CSLL)", "BP", ["2.2.01.011.008"], None),
    ("capital", "Capital social", "BP", ["2.4.01.001.900", "2.4.01.001.901", "2.4.01.001.902", "2.4.01.001.903"], None),
    ("afac", "Adiantamento para futuro aumento de capital (AFAC)", "BP", ["2.4.01.001.909"], None),
    ("res_legal", "Reserva legal", "BP", ["2.4.09.001"], None),
    ("res_ret", "Reserva de retenção de lucros", "BP", ["2.4.09.002"], None),
    ("prej", "Prejuízos acumulados / resultado do período", "BP", ["2.4.13"], None),
    ("pis", "(−) PIS sobre receitas", "DRE", ["4.1.03.005.004"], "D"),
    ("cofins", "(−) COFINS sobre receitas", "DRE", ["4.1.03.005.005"], "D"),
    ("custo_constr", "(−) Custo de construção do ativo de concessão", "DRE", ["5.1.05.001.001"], "D"),
    ("fretes", "(−) Fretes sobre compras", "DRE", ["5.1.03.001.007"], "D"),
    ("serv_prof", "(−) Serviços profissionais", "DRE", ["5.7.03.015.006"], "D"),
    ("cartorio", "(−) Despesas com cartório", "DRE", ["5.7.03.015.024"], "D"),
    ("seguro", "(−) Seguro garantia de fiel cumprimento", "DRE", ["5.7.03.015.900"], "D"),
    ("importacao", "(−) Custos com importação", "DRE", ["5.7.03.015.012"], "D"),
    ("rend_aplic", "Rendimentos sobre aplicações financeiras", "DRE", ["5.7.10.001.901"], "C"),
    ("rec_nt", "Receitas sobre aplicações financeiras (NT)", "DRE", ["5.7.10.001.900"], "C"),
    ("descontos", "Descontos obtidos", "DRE", ["5.7.10.001.001"], "C"),
    ("desp_banc", "(−) Despesas bancárias", "DRE", ["5.7.11.001.002"], "D"),
    ("juros", "(−) Juros pagos ou incorridos", "DRE", ["5.7.11.001.005"], "D"),
]
MAPA = MAPA_PADRAO                      # nome antigo, mantido
CHAVES_BP = [m[0] for m in MAPA_PADRAO if m[2] == "BP"]
CHAVES_DRE = [m[0] for m in MAPA_PADRAO if m[2] == "DRE"]
NAT = {m[0]: m[4] for m in MAPA_PADRAO if m[4]}
CHAVES_PL_FIXAS = ["capital", "afac", "res_legal", "res_ret"]

# linhas calculadas: id -> (rotulo, [(termo, sinal)]), termo = chave ou outra linha
BP_ATIVO = {
    "caixa_eq": ("Caixa e equivalentes de caixa", [("dep_vista", 1), ("aplic", 1)]),
    "ac": ("Total do ativo circulante", [("caixa_eq", 1), ("adiant", 1), ("trib_rec", 1), ("desp_ant_cp", 1)]),
    "rlp": ("Realizável a longo prazo", [("dep_jud", 1), ("desp_ant_lp", 1)]),
    "conc_liq": ("Ativo de concessão líquido", [("conc_bruto", 1), ("conc_red", 1)]),
    "anc": ("Total do ativo não circulante", [("rlp", 1), ("conc_liq", 1)]),
    "ativo": ("TOTAL DO ATIVO", [("ac", 1), ("anc", 1)]),
}
BP_PASSIVO = {
    "pc": ("Total do passivo circulante", [("bndes_cp", 1), ("fornec", 1), ("prov_constr", 1), ("imp_rec", 1), ("trib_ret", 1)]),
    "pnc": ("Total do passivo não circulante", [("bndes_lp", 1), ("trib_dif", 1)]),
    "pl": ("Total do patrimônio líquido", [("capital", 1), ("afac", 1), ("res_legal", 1), ("res_ret", 1), ("prej", 1)]),
    "passivo_pl": ("TOTAL DO PASSIVO E PATRIMÔNIO LÍQUIDO", [("pc", 1), ("pnc", 1), ("pl", 1)]),
}
DRE_LINHAS = {
    "deducoes": ("Deduções da receita", [("pis", 1), ("cofins", 1)]),
    "rec_liq": ("RECEITA OPERACIONAL LÍQUIDA", [("deducoes", 1)]),
    "custos_serv": ("Custos dos serviços prestados", [("custo_constr", 1), ("fretes", 1)]),
    "res_bruto": ("RESULTADO BRUTO", [("rec_liq", 1), ("custos_serv", 1)]),
    "desp_adm": ("Despesas administrativas e gerais", [("serv_prof", 1), ("cartorio", 1), ("seguro", 1), ("importacao", 1), ("ajustes", 1)]),
    "ebit": ("RESULTADO OPERACIONAL (EBIT)", [("res_bruto", 1), ("desp_adm", 1)]),
    "rec_fin": ("Receitas financeiras", [("rend_aplic", 1), ("rec_nt", 1), ("descontos", 1)]),
    "desp_fin": ("Despesas financeiras", [("desp_banc", 1), ("juros", 1)]),
    "res_fin": ("RESULTADO FINANCEIRO LÍQUIDO", [("rec_fin", 1), ("desp_fin", 1)]),
    "res_antes_ir": ("RESULTADO ANTES DO IRPJ E CSLL", [("ebit", 1), ("res_fin", 1)]),
    "res_liq": ("RESULTADO LÍQUIDO DO PERÍODO", [("res_antes_ir", 1), ("ir_cs", 1)]),
}
ROTULOS = {m[0]: m[1] for m in MAPA_PADRAO}
ROTULOS.update({k: v[0] for d in (BP_ATIVO, BP_PASSIVO, DRE_LINHAS) for k, v in d.items()})
ROTULOS.update({"ajustes": "Outros ajustes líquidos", "ir_cs": "(−) IRPJ e CSLL"})


class ErroDados(Exception):
    """Dados insuficientes ou inconsistentes para calcular (mensagem em linguagem simples)."""


# ------------------------------------------------------------------ utilidades
def normalizar_mapa(mapa):
    """Aceita lista de tuplas (chave, rotulo, secao, prefixos, natureza) ou de dicts; devolve lista de tuplas."""
    out = []
    for m in mapa:
        if isinstance(m, dict):
            out.append((m["chave"], m.get("rotulo", m["chave"]), m["secao"], list(m["prefixos"]), m.get("natureza")))
        else:
            out.append((m[0], m[1], m[2], list(m[3]), m[4]))
    return out


def chave_da_conta(cl: str, mapa=None):
    """Chave do mapa pelo prefixo mais longo da classificacao (None se nao mapeada)."""
    best = None
    for k, _, _, pref, _ in (mapa or MAPA_PADRAO):
        for p in pref:
            if cl == p or cl.startswith(p + "."):
                if best is None or len(p) > best[1]:
                    best = (k, len(p))
    return best[0] if best else None


def _avaliar(defs, base):
    """Calcula linhas somadas (em ordem de definicao); base: dict com chaves e linhas ja calculadas."""
    out = dict(base)
    for lid, (_, termos) in defs.items():
        out[lid] = round(sum(sinal * out.get(t, 0.0) for t, sinal in termos), 2)
    return out


def meses_faltando(periodos) -> list[str]:
    """Meses ('AAAA-MM') que faltam entre janeiro e o ultimo periodo informado (lista vazia = sequencia completa)."""
    if not periodos:
        return []
    ps = sorted(periodos)
    ano = ps[0][:4]
    if any(p[:4] != ano for p in ps):
        raise ErroDados("Os balancetes são de anos diferentes; use um ano por vez.")
    ultimo = int(ps[-1][5:7])
    return [f"{ano}-{m:02d}" for m in range(1, ultimo + 1) if f"{ano}-{m:02d}" not in ps]


class Balancetes:
    """Contas de balancete por periodo ('2026-01'...). Periodos em ordem cronologica; precisa comecar em janeiro."""

    def __init__(self, periodos: dict, mapa=None):
        self.mapa = normalizar_mapa(mapa) if mapa else list(MAPA_PADRAO)
        self.chaves_bp = [m[0] for m in self.mapa if m[2] == "BP"]
        self.chaves_dre = [m[0] for m in self.mapa if m[2] == "DRE"]
        self.nat = {m[0]: m[4] for m in self.mapa if m[4]}
        self.p = {k: list(v) for k, v in periodos.items()}
        self.ordem = sorted(self.p)
        self._an = {k: [c for c in v if not c["sint"]] for k, v in self.p.items()}
        self._sn = {k: [c for c in v if c["sint"]] for k, v in self.p.items()}
        self._chv = {}

    def chave(self, cl):
        if cl not in self._chv:
            self._chv[cl] = chave_da_conta(cl, self.mapa)
        return self._chv[cl]

    def exigir_sequencia(self, ate=None):
        """Garante janeiro..ate sem buracos (o Balanco usa a abertura de janeiro e o DRE soma o ano)."""
        ordem = [p for p in self.ordem if ate is None or p <= ate]
        if not ordem:
            raise ErroDados("Nenhum balancete mensal importado.")
        falta = meses_faltando(ordem)
        if ordem[0][5:7] != "01" or falta:
            lista = ", ".join(f"{m[5:7]}/{m[:4]}" for m in ([f"{ordem[0][:4]}-01"] if ordem[0][5:7] != "01" else []) + falta)
            raise ErroDados(f"Faltam balancetes mensais: {lista}. Importe todos os meses de janeiro até o mês escolhido.")

    def sint(self, per, cl):
        for c in self._sn[per]:
            if c["cl"] == cl:
                return c
        return None

    # ---- balanco
    def saldo(self, per, chave):
        tot = sum(c["sal"] for c in self._an[per] if self.chave(c["cl"]) == chave)
        if chave == "prej":                      # resultado do mes ainda aberto (conta 8) faz parte do PL
            c8 = self.sint(per, "8")
            tot += c8["sal"] if c8 else 0.0
        return round(tot, 2)

    def abertura(self, chave):
        """Saldo em 31/12 anterior = saldo anterior do primeiro periodo do ano."""
        per = self.ordem[0]
        return round(sum(c["ant"] for c in self._an[per] if self.chave(c["cl"]) == chave), 2)

    # ---- resultado
    def encerrado(self, per):
        """Mes com contas de resultado encerradas: classes 4 e 5 com saldo zero e movimento (debito = credito)."""
        for cl in ("4", "5"):
            s = self.sint(per, cl)
            if s and abs(s["sal"]) < TOL and s["deb"] > TOL:
                return True
        return False

    def _mov_conta(self, c, enc):
        """Mov. do mes (credito - debito). Mes encerrado: usa o debito e a natureza da conta (D despesa, C receita)."""
        if enc and abs(c["sal"]) < TOL and c["deb"] > TOL:
            nat = self.nat.get(self.chave(c["cl"])) or ("C" if c["cl"][0] == "4" else "D")
            return c["deb"] if nat == "C" else -c["deb"]
        return c["cred"] - c["deb"]

    def mov(self, per, chave):
        enc = self.encerrado(per)
        return round(sum(self._mov_conta(c, enc) for c in self._an[per] if self.chave(c["cl"]) == chave), 2)

    def _pl_implicito(self, per):
        """PL pelo balanco = ativo - passivo exigivel (2.1 + 2.2)."""
        a = self.sint(per, "1")["sal"]
        e = self.sint(per, "2.1")["sal"] + self.sint(per, "2.2")["sal"]
        return round(a - e, 2)

    def resultado_acumulado_implicito(self, per):
        """Resultado acumulado do ano implicito no balanco: PL - (capital + AFAC + reservas)."""
        fixas = sum(self.saldo(per, k) for k in CHAVES_PL_FIXAS)
        return round(self._pl_implicito(per) - fixas, 2)

    def ajuste_mes(self, per):
        """'Outros ajustes liquidos': resultado do mes implicito no balanco - soma das contas de resultado."""
        i = self.ordem.index(per)
        acum_ant = self.resultado_acumulado_implicito(self.ordem[i - 1]) if i > 0 else 0.0
        impl = self.resultado_acumulado_implicito(per) - acum_ant
        soma = sum(self.mov(per, k) for k in self.chaves_dre)
        adj = round(impl - soma, 2)
        return 0.0 if abs(adj) < 0.05 else adj          # 1 centavo de arredondamento nao e ajuste


# ------------------------------------------------------------------ demonstrativos
def balanco(b: Balancetes, mes_ref: str, mes_ant: str | None = None):
    """3 colunas: 31/12 anterior (abertura), mes anterior, mes de referencia."""
    b.exigir_sequencia(mes_ref)
    if mes_ant is None:
        i = b.ordem.index(mes_ref)
        mes_ant = b.ordem[i - 1] if i > 0 else mes_ref
    cols = {}
    for nome, getter in (("abertura", lambda k: b.abertura(k)), ("mes_ant", lambda k: b.saldo(mes_ant, k)),
                         ("mes_ref", lambda k: b.saldo(mes_ref, k))):
        base = {k: 0.0 for k in CHAVES_BP}                  # chave tirada do mapa vira zero (e a conta aparece como "sem chave")
        base.update({k: getter(k) for k in b.chaves_bp})
        if nome == "abertura":                    # na abertura nao ha resultado em aberto; prej = saldo anterior de 2.4.13
            base["prej"] = b.abertura("prej")
        v = _avaliar(BP_ATIVO, base)
        v = _avaliar(BP_PASSIVO, v)
        cols[nome] = v
    return cols


def dre(b: Balancetes, mes_ref: str):
    """Colunas: acumulado ate o mes anterior, mes de referencia e acumulado do ano."""
    b.exigir_sequencia(mes_ref)
    i = b.ordem.index(mes_ref)
    ate_ant = b.ordem[:i]

    def soma(meses):
        d = {k: 0.0 for k in CHAVES_DRE}
        d.update({k: round(sum(b.mov(m, k) for m in meses), 2) for k in b.chaves_dre})
        d["ajustes"] = round(sum(b.ajuste_mes(m) for m in meses), 2)
        d["ir_cs"] = 0.0
        return _avaliar(DRE_LINHAS, d)

    return {"ate_mes_ant": soma(ate_ant), "mes": soma([mes_ref]), "acumulado": soma(ate_ant + [mes_ref])}


def _div(a, b):
    return None if (b is None or abs(b) < TOL) else a / b


def indicadores(bp: dict, dre_acum: dict | None):
    """17 indicadores do relatorio. bp: dict de linhas de UMA data; dre_acum: acumulado do ano ate a data (ou None)."""
    ac, pc, pnc, rlp = bp["ac"], bp["pc"], bp["pnc"], bp["rlp"]
    caixa = bp["caixa_eq"]
    divb = round(bp["bndes_cp"] + bp["bndes_lp"], 2)
    divl = round(divb - caixa, 2)
    return {
        "liq_corrente": _div(ac, pc), "liq_imediata": _div(caixa, pc), "liq_geral": _div(ac + rlp, pc + pnc),
        "ccl": round(ac - pc, 2),
        "div_bruta": divb, "caixa_neg": -caixa, "div_liquida": divl,
        "div_cp_sobre_bruta": _div(bp["bndes_cp"], divb), "div_bruta_ativo": _div(divb, bp["ativo"]),
        "div_liq_sobre_concessao": _div(divl, bp["conc_liq"]),
        "endiv_geral": _div(pc + pnc, bp["ativo"]), "comp_endiv_cp": _div(pc, pc + pnc), "pl_ativo": _div(bp["pl"], bp["ativo"]),
        "capital_aportado": round(bp["capital"] + bp["afac"], 2),
        "res_fin": dre_acum["res_fin"] if dre_acum else None,
        "ebit_ebitda": dre_acum["ebit"] if dre_acum else None,
        "res_liq": dre_acum["res_liq"] if dre_acum else None,
    }


# ------------------------------------------------------------------ conferencias (log de erros da importacao)
def _reg(R, grupo, per, desc, ok, det=""):
    R.append({"grupo": grupo, "periodo": per, "descricao": desc, "ok": bool(ok), "detalhe": det})


def _conf_arquivo(b: Balancetes, per, R):
    """Conferencias que so dependem do proprio arquivo/periodo."""
    A = b._an[per]
    s1, s2 = b.sint(per, "1"), b.sint(per, "2")
    if s1 is None or s2 is None:
        _reg(R, "Fechamento", per, "Contas 1 (Ativo) e 2 (Passivo) presentes no arquivo", False, "O arquivo não traz as contas sintéticas 1 e 2.")
        return
    a1, p2 = s1["sal"], s2["sal"]
    c8 = b.sint(per, "8")
    s8 = c8["sal"] if c8 else 0.0
    _reg(R, "Fechamento", per, "Ativo = Passivo + PL (incluindo o resultado em aberto, conta 8)", abs(a1 - (p2 + s8)) < TOL,
         f"ativo={a1:.2f} passivo={p2:.2f} conta8={s8:.2f}")
    bad = []
    for s in b._sn[per]:
        filhas = [c for c in A if c["cl"].startswith(s["cl"] + ".")]
        if filhas and abs(sum(c["sal"] for c in filhas) - s["sal"]) > 0.015:
            bad.append(s["cl"])
    _reg(R, "Soma das contas", per, "Conta sintética = soma das analíticas", not bad, ", ".join(bad[:10]))
    bad = [c["cl"] for c in A if not (abs(c["ant"] + c["deb"] - c["cred"] - c["sal"]) < TOL or abs(c["ant"] - c["deb"] + c["cred"] - c["sal"]) < TOL)]
    _reg(R, "Movimento", per, "Saldo anterior + movimento = saldo", not bad, ", ".join(bad[:10]))
    sem = [c["cl"] for c in A if b.chave(c["cl"]) is None and c["cl"][0] in "1245" and
           ((abs(c["sal"]) > TOL) if c["cl"][0] in "12" else (abs(c["deb"]) > TOL or abs(c["cred"]) > TOL))]
    _reg(R, "Mapa de contas", per, "Toda conta com saldo/movimento tem chave no mapa", not sem, ", ".join(sem[:10]))


def conferencias_arquivo(contas: list, mapa=None, periodo="arquivo"):
    """Conferencias de UM arquivo recem-importado (antes de gravar)."""
    b = Balancetes({periodo: contas}, mapa)
    R: list = []
    _conf_arquivo(b, periodo, R)
    return R


def conferencias(b: Balancetes):
    """Lista de dicts {grupo, periodo, descricao, ok, detalhe}. Falha = precisa de olhar antes de gerar relatorio."""
    R: list = []
    ordem = b.ordem
    acc = 0.0
    for i, per in enumerate(ordem):
        A = b._an[per]
        _conf_arquivo(b, per, R)
        if i > 0:
            ant = {c["id"]: c for c in b._an[ordem[i - 1]]}
            bad = []
            for c in A:
                if c["cl"][0] not in "12" or c["cl"].startswith("2.4.13"):
                    continue
                ref = ant.get(c["id"])
                rv = ref["sal"] if ref else 0.0
                if abs(c["ant"] - rv) > TOL:
                    bad.append(c["cl"])
            _reg(R, "Continuidade", per, "Saldo anterior = saldo final do mês anterior (exceto Prejuízos Acumulados)", not bad, ", ".join(bad[:10]))
        ant_pj = sum(c["ant"] for c in A if c["cl"].startswith("2.4.13"))
        _reg(R, "Encerramento", per, "Prejuízos Acumulados (saldo anterior) = soma dos resultados dos meses anteriores",
             abs(ant_pj - acc) < 0.02, f"{ant_pj:.2f} x {acc:.2f}")
        acc += sum(b.mov(per, k) for k in b.chaves_dre) + b.ajuste_mes(per)
        if b.sint(per, "1") is not None and b.sint(per, "2") is not None:
            bp = balanco(b, per, per if i == 0 else ordem[i - 1])["mes_ref"]
            a1 = b.sint(per, "1")["sal"]
            _reg(R, "Balanço calculado", per, "Total do ativo calculado = conta 1 do balancete", abs(bp["ativo"] - a1) < TOL, f"{bp['ativo']:.2f} x {a1:.2f}")
            _reg(R, "Balanço calculado", per, "Ativo = Passivo + PL calculados", abs(bp["ativo"] - bp["passivo_pl"]) < TOL, f"{bp['ativo']:.2f} x {bp['passivo_pl']:.2f}")
    return R


def conferir_acumulado(b: Balancetes, acum_contas: list, ate: str, rotulo="acumulado"):
    """Compara a soma dos balancetes mensais (jan..ate) com um balancete ACUMULADO do mesmo periodo.
    Diferenca por chave so e' aceita se a soma das diferencas for igual ao 'Outros ajustes liquidos' do periodo."""
    R: list = []
    meses = [m for m in b.ordem if m <= ate]
    ba = Balancetes({rotulo: acum_contas}, b.mapa)
    difs, tot = {}, 0.0
    for k in b.chaves_dre:
        m = round(sum(b.mov(p, k) for p in meses), 2)
        a = round(ba.mov(rotulo, k), 2)
        if abs(m - a) > 0.011:
            difs[k] = round(a - m, 2)
            tot += a - m
    ajuste = round(sum(b.ajuste_mes(p) for p in meses), 2)
    ok = (not difs) or abs(round(tot, 2) - ajuste) < 0.011
    det = "; ".join(f"{ROTULOS.get(k, k)}: {v:+.2f}" for k, v in difs.items()) or "sem diferença"
    _reg(R, "Mensal x acumulado", ate, f"Soma dos meses de janeiro até {ate[5:7]}/{ate[:4]} = balancete acumulado (diferença só pode ser o 'Outros ajustes líquidos')",
         ok, f"{det} | ajuste do período: {ajuste:.2f}")
    c8 = ba.sint(rotulo, "8")
    if c8 is not None:
        res = dre(b, ate)["acumulado"]["res_liq"]
        _reg(R, "Mensal x acumulado", ate, "Linha 8 do acumulado = resultado líquido acumulado da DRE", abs(c8["sal"] - res) < 0.011,
             f"{c8['sal']:.2f} x {res:.2f}")
    return R
