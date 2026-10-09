# -*- coding: utf-8 -*-
"""
GDF - de onde vem cada numero do relatorio, mesmo com meses faltando. Modulo puro (sem banco, sem Streamlit).

Regra de ouro: o app so mostra numero que consegue calcular de forma correta. O que nao da' para calcular vira n/d (None),
com a explicacao do que falta; o que e' calculavel por outro caminho e' calculado por esse caminho, dizendo qual foi.

Colunas do relatorio do mes M (ano A):
  Balanco  - abertura (31/12 anterior) | mes anterior (M-1) | mes M
  DRE      - acumulado de janeiro a M-1 | mes M | acumulado de janeiro a M

Caminhos (do melhor para o alternativo):
  posicao em M ........ balancete mensal de M  >  balancete acumulado ate' M
  posicao em M-1 ...... balancete mensal de M-1  >  coluna "saldo anterior" do mensal de M  >  acumulado ate' M-1
  abertura 31/12 ...... mensal de janeiro  >  "saldo anterior" de qualquer acumulado do ano
  DRE janeiro..k ...... soma dos mensais  >  acumulado ate' k  >  acumulado ate' x (x<k) + mensais x+1..k
  DRE do mes M ........ mensal de M  >  acumulado ate' M - DRE janeiro..M-1
  DRE janeiro..M-1 .... (como janeiro..k)  >  acumulado ate' M - mensal de M
So' entra um acumulado se ele for coerente com o balancete mensal vizinho (saldo final do acumulado = saldo anterior do mes seguinte);
se nao for, ele e' deixado de lado e o motivo aparece nas lacunas.
"""
from __future__ import annotations

import motor
from motor import Balancetes, ErroDados

_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _mk(ano, i: int) -> str:
    return f"{ano}-{i:02d}"


def _br(m: str) -> str:
    return f"{m[5:7]}/{m[:4]}"


def _jan_ate(m: str) -> str:
    """'2026-07' -> 'jan–07/2026'."""
    return f"jan–{m[5:7]}/{m[:4]}" if m[5:7] != "01" else f"01/{m[:4]}"


def _lista(ms) -> str:
    return ", ".join(_br(m) for m in ms)


def saldo_anterior_como_posicao(contas_m: list) -> list:
    """O balancete de M traz, em 'saldo anterior', a posicao de 31/M-1. Monta com isso as contas de M-1 (so' posicao: sem movimento),
    na forma que o motor usa (analiticas das classes 1 e 2 + sinteticas 1, 2.1 e 2.2)."""
    out, soma = [], {"1": 0.0, "2.1": 0.0, "2.2": 0.0}
    for c in contas_m:
        if c["sint"] or c["cl"][0] not in "12":
            continue
        out.append({"id": c["id"], "sint": False, "cl": c["cl"], "nome": c["nome"], "ant": c["ant"], "deb": 0.0, "cred": 0.0, "sal": c["ant"]})
        for cl in soma:
            if c["cl"].startswith(cl + "."):
                soma[cl] += c["ant"]
    for cl, v in soma.items():
        out.append({"id": f"fonte-{cl}", "sint": True, "cl": cl, "nome": cl, "ant": round(v, 2), "deb": 0.0, "cred": 0.0, "sal": round(v, 2)})
    return out


def _por_cl(contas: list, campo: str, incluir_resultado: bool = False) -> dict:
    d: dict = {}
    for c in contas:
        if c["sint"] or c["cl"][0] not in "12" or (not incluir_resultado and c["cl"].startswith("2.4.13")):
            continue
        d[c["cl"]] = d.get(c["cl"], 0.0) + c[campo]
    return d


def _difere(a: dict, b: dict) -> list:
    return sorted(cl for cl in set(a) | set(b) if abs(a.get(cl, 0.0) - b.get(cl, 0.0)) > motor.TOL)


def _comb(a: dict, b: dict, sinal: int) -> dict:
    return {k: round(a[k] + sinal * b[k], 2) for k in a}


class _Calculo:
    def __init__(self, mo: dict, ac: dict, mapa, ano: str):
        self.mo, self.ac, self.mapa, self.ano = mo, ac, mapa, ano
        self._seg_m, self._seg_a, self._ate, self.incoerencias = {}, {}, {}, []
        self._ok_acum: dict = {}

    # ---- pecas
    def seg_mes(self, m: str):
        """DRE bruta do mes m a partir do balancete mensal (o resultado do mes anterior vem do mensal anterior ou do 'saldo anterior' de m)."""
        if m not in self.mo:
            return None
        if m not in self._seg_m:
            per = {m: self.mo[m]}
            if m[5:7] != "01":
                ant = motor._mes_anterior(m)
                per[ant] = self.mo[ant] if ant in self.mo else saldo_anterior_como_posicao(self.mo[m])
            self._seg_m[m] = motor.dre_bruta(Balancetes(per, self.mapa), [m])
        return self._seg_m[m]

    def seg_acum(self, x: str):
        if x not in self._seg_a:
            self._seg_a[x] = motor.dre_bruta(Balancetes({x: self.ac[x]}, self.mapa), [x])
        return self._seg_a[x]

    def acum_coerente(self, x: str) -> bool:
        """Um acumulado so' entra nas contas se bater com o mensal vizinho: saldo final de x = saldo anterior do mes x+1, e abertura = saldo anterior de janeiro."""
        if x not in self._ok_acum:
            ok, problemas = True, []
            n = int(x[5:7])
            seguinte = _mk(self.ano, n + 1) if n < 12 else None
            if seguinte and seguinte in self.mo:
                dif = _difere(_por_cl(self.ac[x], "sal"), _por_cl(self.mo[seguinte], "ant"))
                if dif:
                    ok = False
                    problemas.append(f"o saldo final do acumulado até {_br(x)} não bate com o saldo anterior do mensal de {_br(seguinte)} (contas: {', '.join(dif[:6])})")
            jan = _mk(self.ano, 1)
            if jan in self.mo:
                dif = _difere(_por_cl(self.ac[x], "ant", True), _por_cl(self.mo[jan], "ant", True))
                if dif:
                    ok = False
                    problemas.append(f"o saldo de abertura do acumulado até {_br(x)} não bate com o do mensal de janeiro (contas: {', '.join(dif[:6])})")
            if problemas:
                self.incoerencias.append(f"O balancete acumulado até {_br(x)} não foi usado: " + "; ".join(problemas) + ".")
            self._ok_acum[x] = ok
        return self._ok_acum[x]

    # ---- DRE acumulada de janeiro a k
    def acum_ate(self, k: int):
        """(DRE bruta, descricao, meses mensais usados, acumulados usados) ou None quando nao da' para calcular."""
        if k in self._ate:
            return self._ate[k]
        res = None
        if k == 0:
            zero = {key: 0.0 for key in self.seg_acum_vazio()}
            res = (zero, "início do ano (sem movimento)", [], [])
        else:
            meses = [_mk(self.ano, i) for i in range(1, k + 1)]
            if all(m in self.mo for m in meses):
                bruta = None
                for m in meses:
                    bruta = self.seg_mes(m) if bruta is None else _comb(bruta, self.seg_mes(m), 1)
                res = (bruta, f"soma dos balancetes mensais de {_br(meses[0])} a {_br(meses[-1])}" if k > 1 else f"balancete mensal de {_br(meses[0])}", meses, [])
            else:
                for x in sorted((x for x in self.ac if int(x[5:7]) <= k), reverse=True):
                    resto = [_mk(self.ano, i) for i in range(int(x[5:7]) + 1, k + 1)]
                    if all(m in self.mo for m in resto) and self.acum_coerente(x):
                        bruta = self.seg_acum(x)
                        for m in resto:
                            bruta = _comb(bruta, self.seg_mes(m), 1)
                        desc = f"balancete acumulado {_jan_ate(x)}" + (f" + mensais de {_lista(resto)}" if resto else "")
                        res = (bruta, desc, resto, [x])
                        break
        self._ate[k] = res
        return res

    def seg_acum_vazio(self):
        ref = next(iter(self.mo)) if self.mo else next(iter(self.ac))
        b = Balancetes({ref: (self.mo.get(ref) or self.ac.get(ref))}, self.mapa)
        return motor.dre_bruta(b, [])


def _col_bp(contas, per, mapa):
    return motor.coluna_bp(Balancetes({per: contas}, mapa), per)


def calcular(mensais: dict, acumulados: dict, mapa, mes_ref: str) -> dict:
    """Tudo do mes_ref, com o que existir. Levanta ErroDados so' quando nao ha' nenhum balancete (mensal ou acumulado) desse mes."""
    ano, M = mes_ref[:4], int(mes_ref[5:7])
    mo = {m: v for m, v in mensais.items() if m[:4] == ano and m <= mes_ref}
    ac = {m: v for m, v in acumulados.items() if m[:4] == ano and m <= mes_ref}
    if mes_ref not in mo and mes_ref not in ac:
        raise ErroDados(f"Não há balancete (mensal ou acumulado) ativo para {_br(mes_ref)}. Importe um deles em **Importar balancete**.")
    K = _Calculo(mo, ac, mapa, ano)
    mapa_n = motor.normalizar_mapa(mapa) if mapa else None
    jan, ant = _mk(ano, 1), (motor._mes_anterior(mes_ref) if M > 1 else mes_ref)
    meses_ano = [_mk(ano, i) for i in range(1, M + 1)]
    faltam_mensais = [m for m in meses_ano if m not in mo]
    fontes, lacunas, notas = {}, [], []
    usa_mensais, usa_acum = set(), set()

    def _nd(onde, motivo, resolver):
        lacunas.append({"onde": onde, "motivo": motivo, "resolver": resolver})

    # ---------------- Balanco
    # posicao em M
    if mes_ref in mo:
        col_ref, fontes["bp_ref"] = _col_bp(mo[mes_ref], mes_ref, mapa), f"balancete mensal de {_br(mes_ref)}"
        usa_mensais.add(mes_ref)
    else:
        col_ref, fontes["bp_ref"] = _col_bp(ac[mes_ref], mes_ref, mapa), f"balancete acumulado {_jan_ate(mes_ref)} (não há o mensal de {_br(mes_ref)})"
        usa_acum.add(mes_ref)
    # posicao em M-1
    if M == 1:
        col_ant = None                                         # preenchido com a abertura mais abaixo
    elif ant in mo:
        col_ant, fontes["bp_ant"] = _col_bp(mo[ant], ant, mapa), f"balancete mensal de {_br(ant)}"
        usa_mensais.add(ant)
    elif mes_ref in mo:
        col_ant = _col_bp(saldo_anterior_como_posicao(mo[mes_ref]), ant, mapa)
        fontes["bp_ant"] = f"coluna “saldo anterior” do balancete mensal de {_br(mes_ref)} (não há o mensal de {_br(ant)})"
        usa_mensais.add(mes_ref)
    elif ant in ac and K.acum_coerente(ant):
        col_ant, fontes["bp_ant"] = _col_bp(ac[ant], ant, mapa), f"balancete acumulado {_jan_ate(ant)}"
        usa_acum.add(ant)
    else:
        col_ant = None
        _nd(f"Balanço — coluna do mês anterior ({motor_data(ant)}) e os indicadores dessa data",
            f"não há o balancete mensal de {_br(ant)}, nem o de {_br(mes_ref)} (que traria esse saldo), nem um acumulado até {_br(ant)}",
            f"importe o balancete mensal de {_br(mes_ref)} ou o de {_br(ant)} (ou o acumulado até {_br(ant)})")
    # abertura
    if jan in mo:
        col_ab = motor.coluna_bp(Balancetes({jan: mo[jan]}, mapa), jan, True)
        fontes["bp_abertura"] = f"“saldo anterior” do balancete mensal de {_br(jan)}"
        usa_mensais.add(jan)
    else:
        x = next((x for x in sorted(ac) if K.acum_coerente(x)), None)
        if x:
            col_ab = motor.coluna_bp(Balancetes({x: ac[x]}, mapa), x, True)
            fontes["bp_abertura"] = f"“saldo anterior” do balancete acumulado {_jan_ate(x)}"
            usa_acum.add(x)
        else:
            col_ab = None
            _nd(f"Balanço — coluna de 31/12/{int(ano) - 1} (abertura) e os indicadores dessa data",
                "o saldo de 31/12 só vem do balancete mensal de janeiro ou de um balancete acumulado do ano",
                f"importe o balancete mensal de {_br(jan)} ou um acumulado de janeiro em diante")
    if M == 1:                                                  # o 'mes anterior' de janeiro e' dezembro = a propria abertura
        col_ant = col_ab
        if col_ab is not None:
            fontes["bp_ant"] = fontes["bp_abertura"]

    # ---------------- DRE
    ac_M = K.acum_ate(M)
    ate_ant = K.acum_ate(M - 1)
    mes_b = None
    if mes_ref in mo:
        mes_b = (K.seg_mes(mes_ref), f"balancete mensal de {_br(mes_ref)}")
        usa_mensais.add(mes_ref)
    elif ac_M is not None and ate_ant is not None:
        mes_b = (_comb(ac_M[0], ate_ant[0], -1), f"acumulado {_jan_ate(mes_ref)} menos o acumulado até {_br(ant)}")
    if ate_ant is None and ac_M is not None and mes_b is not None and mes_ref in mo:
        ate_ant = (_comb(ac_M[0], mes_b[0], -1), f"acumulado {_jan_ate(mes_ref)} menos o mensal de {_br(mes_ref)}", [], list(ac_M[3]))
    for nome, v in (("dre_acum", ac_M), ("dre_ate_ant", ate_ant)):
        if v is not None:
            fontes[nome] = v[1]
            usa_mensais.update(v[2])
            usa_acum.update(v[3])
    if mes_b is not None:
        fontes["dre_mes"] = mes_b[1]

    def _pronta(v):
        return motor.dre_calcular(v) if v is not None else None
    d = {"ate_mes_ant": _pronta(ate_ant[0]) if ate_ant else None, "mes": _pronta(mes_b[0]) if mes_b else None,
         "acumulado": _pronta(ac_M[0]) if ac_M else None}
    if d["acumulado"] is None:
        _nd(f"DRE — coluna “Acumulado jan–{_NOME_ABREV(M)}” e os indicadores de resultado",
            "a DRE do ano precisa dos balancetes de todos os meses (ou de um balancete acumulado que cubra os que faltam)",
            (f"importe o balancete acumulado de janeiro a {_br(mes_ref)} (um único arquivo resolve) ou os mensais que faltam: {_lista(faltam_mensais)}"))
    if d["ate_mes_ant"] is None and M > 1:
        _nd(f"DRE — coluna “Jan–{_NOME_ABREV(M - 1)}” (acumulado até o mês anterior)",
            f"faltam os balancetes de {_lista([m for m in meses_ano[:-1] if m not in mo])}, e não há acumulado que cubra esse período",
            f"importe o acumulado de janeiro a {_br(ant)} ou os mensais que faltam: {_lista([m for m in meses_ano[:-1] if m not in mo])}")
    if d["mes"] is None:
        _nd(f"DRE — coluna do mês ({_br(mes_ref)})",
            f"não há o balancete mensal de {_br(mes_ref)} e faltam os acumulados para obter o mês por diferença",
            f"importe o balancete mensal de {_br(mes_ref)}")
    for inc in K.incoerencias:
        _nd("Balancete acumulado", inc, "confira o arquivo acumulado (período e CNPJ) e importe novamente, ou use os balancetes mensais")
    bp = {"abertura": col_ab, "mes_ant": col_ant, "mes_ref": col_ref}

    usados_acum_ids = sorted(usa_acum)
    if faltam_mensais and fonte_ok(bp, d):
        notas.append(f"Não há balancete mensal de {_lista(faltam_mensais)}. Isso não impede o relatório: os números foram obtidos por outro caminho (veja “De onde vêm os números”), "
                     "mas o gráfico de evolução mostra só os meses que têm balancete.")
    fonte = "completo" if not faltam_mensais else ("alternativo" if fonte_ok(bp, d) else "parcial")
    if usa_acum and fonte != "completo":
        notas.append("Parte dos valores vem de balancete acumulado. Os totais e subtotais batem com a soma dos meses; uma linha isolada da DRE pode ter diferença de "
                     "centavos de classificação (o acumulado já traz os estornos líquidos).")

    # ---------------- conferencias
    b = Balancetes(mo, mapa)
    conf = motor.conferencias(b) if mo else []
    for x in sorted(ac):
        if all(_mk(ano, i) in mo for i in range(1, int(x[5:7]) + 1)):
            conf += motor.conferir_acumulado(Balancetes({m: mo[m] for m in b.ordem if m <= x}, mapa), ac[x], x)
        elif x in usa_acum:                                    # acumulado usado nas contas: confere o arquivo em si
            bA = Balancetes({x: ac[x]}, mapa)
            R: list = []
            motor._conf_arquivo(bA, x, R)
            for r in R:
                r["grupo"] = "Acumulado: " + r["grupo"]
                r["periodo"] = f"acum. {_jan_ate(x)}"
            conf += R
    for x in sorted(ac):                                        # acumulado x mensal vizinho (saldo final = saldo anterior do mes seguinte)
        n = int(x[5:7])
        seg = _mk(ano, n + 1) if n < 12 else None
        if seg and seg in mo and seg <= mes_ref:
            dif = _difere(_por_cl(ac[x], "sal"), _por_cl(mo[seg], "ant"))
            conf.append({"grupo": "Acumulado x mensal", "periodo": seg, "ok": not dif,
                         "descricao": f"Saldo final do acumulado {_jan_ate(x)} = saldo anterior do mensal de {_br(seg)}", "detalhe": ", ".join(dif[:10])})

    contas_ref = mo.get(mes_ref) or ac[mes_ref]
    # ---------------- pontos para graficos/painel (um por mes com balancete; o mes de referencia sempre entra)
    pontos = []
    meses_pt = set(mo) | {mes_ref} | ({ant} if M > 1 and col_ant is not None else set())          # o mes anterior entra mesmo sem mensal (posicao vinda de outro caminho)
    for m in sorted(meses_pt):
        bm = col_ref if m == mes_ref else (col_ant if m not in mo else _col_bp(mo[m], m, mapa))
        sm = K.seg_mes(m)
        pontos.append({"per": m, "bp": bm, "dre_mes": motor.dre_calcular(sm) if sm else (d["mes"] if m == mes_ref else None)})
    return {"mapa": mapa, "periodos": mo, "acumulados": ac, "b": b, "mes_ant": ant, "bp": bp, "d": d, "conf": conf,
            "falhas": [c for c in conf if not c["ok"]], "contas_ref": contas_ref, "fonte": fonte, "fontes": fontes,
            "lacunas": lacunas, "notas": notas, "faltam_mensais": faltam_mensais, "pontos": pontos,
            "usados_mensais": sorted(usa_mensais), "usados_acum": usados_acum_ids, "mensais_do_ano": sorted(mo)}


def fonte_ok(bp: dict, d: dict) -> bool:
    return all(v is not None for v in bp.values()) and all(v is not None for v in d.values())


def _NOME_ABREV(m: int) -> str:
    return ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"][m - 1]


def motor_data(m: str) -> str:
    import calendar
    a, n = int(m[:4]), int(m[5:7])
    return f"{calendar.monthrange(a, n)[1]:02d}/{n:02d}/{a}"
