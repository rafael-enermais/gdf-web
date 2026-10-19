# -*- coding: utf-8 -*-
"""
GDF V2 - leitor dos RECIBOS DE PAGAMENTO (folha) em PDF: "Demonstrativo de Pagamento de Salario" (Enermais Construtora / Enermais Energia).
Cada pagina traz o mesmo recibo DUAS vezes (via da empresa e via do colaborador); o leitor guarda uma so' (chave empresa + cadastro + FL).
De cada recibo sai: cadastro, nome, CBO, cargo, local (nivel 1 = obra), departamento (001.NNN = subnivel do canteiro), texto do subnivel,
admissao, os EVENTOS (codigo, descricao, referencia, provento, desconto), os totais e o FGTS do mes.
Le so' TEXTO (pdfplumber), por POSICAO das palavras (colunas Proventos/Descontos); o arquivo nunca e' alterado. Sem streamlit, sem banco.
Confere: soma dos proventos e dos descontos dos eventos = Total do recibo; liquido = proventos - descontos.
Aviso: o PDF real tem nomes de pessoas - nada daqui vai para o log do Actions nem para o repositorio (testes usam dados inventados).
"""
from __future__ import annotations

import io
import re
from collections import Counter

NUM = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
_RE_NUM = re.compile(rf"^{NUM}$")
_RE_CAB = re.compile(r"^(\d+)\s+(.+?)\s+(\d{4,7})\s+(\d+)\s+(\d+)\s+(\d{3}\.\d{3})\s+(\d+)$")
_RE_CARGO = re.compile(r"^(.*?)\s*Data Admiss[aã]o:\s*(\d\d)/(\d\d)/(\d{4})")
_RE_PERIODO = re.compile(r"(\d\d)/(\d{4})\s+(Mensal|Adiantamento|13)", re.I)

# Eventos de HORA EXTRA e DSR (regra da contabilidade, 13/10/2026: "somar todos os eventos de hora extra + DSR - somente").
# 110% = evento 1029 (achado no recibo de set/2026). 37 (60%) e 43 (80%) tambem sao hora extra no recibo: entram; 311/699 = HE de mes anterior.
EVENTOS_HE = {35, 37, 43, 49, 1029, 311, 699}
EVENTOS_DSR = {59}
EVENTO_SALARIO = 1                      # "Horas Normais Diurnas" = salario CLT do mes (base da razao HE / salarios)


class ErroFolha(ValueError):
    """Mensagem em portugues simples, pronta para mostrar na tela."""


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _linhas(palavras: list) -> list:
    """Agrupa palavras na mesma linha (tolerancia de 3 pontos na vertical), cada linha ordenada da esquerda para a direita."""
    out, atual, topo = [], [], None
    for w in sorted(palavras, key=lambda w: (round(w["top"]), w["x0"])):
        if topo is None or abs(w["top"] - topo) <= 3:
            atual.append(w)
            topo = w["top"] if topo is None else topo
        else:
            out.append(sorted(atual, key=lambda x: x["x0"]))
            atual, topo = [w], w["top"]
    if atual:
        out.append(sorted(atual, key=lambda x: x["x0"]))
    return out


def _texto(linha: list) -> str:
    return " ".join(w["text"] for w in linha)


def _ler_bloco(palavras: list, aviso) -> dict | None:
    """Um recibo (uma metade de pagina). Devolve None se nao parecer um recibo."""
    linhas = _linhas(palavras)
    textos = [_texto(l) for l in linhas]
    if not any("Demonstrativo de Pagamento" in t for t in textos):
        return None
    # posicao das colunas, lida do cabecalho da tabela de eventos
    x_ref = x_prov_1 = x_desc_0 = None
    for l in linhas:
        for w in l:
            if w["text"] == "Refer\u00eancia":
                x_ref = w["x0"]
            elif w["text"] == "Proventos":
                x_prov_1 = w["x1"]
            elif w["text"] == "Descontos":
                x_desc_0 = w["x0"]
    if x_ref is None or x_prov_1 is None or x_desc_0 is None:
        return None
    limite_desc = (x_prov_1 + x_desc_0) / 2.0           # dinheiro a direita disso = desconto; entre a referencia e isso = provento
    rec = {"empresa": None, "cadastro": None, "nome": None, "cbo": None, "cargo": None, "local": None, "departamento": None, "fl": None,
           "subnivel_texto": None, "admissao": None, "competencia": None, "eventos": [], "total_proventos": None, "total_descontos": None,
           "liquido": None, "fgts_mes": None, "salario_base": None}
    estado = "cab"
    pendente = None
    for i, (l, t) in enumerate(zip(linhas, textos)):
        mp = _RE_PERIODO.search(t)
        if mp and rec["competencia"] is None and "Mensal" in t:
            rec["competencia"] = f"{mp.group(2)}-{mp.group(1)}"
        if t.startswith("Cadastro "):
            estado = "cab_dados"
            continue
        if estado == "cab_dados":
            m = _RE_CAB.match(t)
            if m:
                rec.update(cadastro=m.group(1), nome=m.group(2), cbo=m.group(3), empresa=m.group(4), local=m.group(5), departamento=m.group(6), fl=m.group(7))
                estado = "cargo"
            continue
        if estado == "cargo":
            m = _RE_CARGO.match(t)
            if m:
                rec["cargo"] = m.group(1).strip() or None
                rec["admissao"] = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
                estado = "tabela"
            continue
        if estado == "tabela":
            if t.startswith("Ev ") or t.startswith("Banco:") or t.startswith("Contrato:"):
                continue
            if "Total L\u00edquido" in t:
                esq = []
                for w in l:
                    if w["text"] == "Total":
                        break
                    esq.append(w["text"])
                rec["subnivel_texto"] = " ".join(esq).strip() or None
                vals = [_num(w["text"]) for w in l if _RE_NUM.match(w["text"])]
                if vals:
                    rec["liquido"] = vals[-1]
                continue
            # Linha "Total": pode vir com mensagem a esquerda na mesma linha ("Parabens ! Feliz Aniversario 23/10 Total 5.724,87 782,11"),
            # entao procura a palavra "Total" (que nao seja "Total Liquido") em qualquer posicao e le so' os numeros a direita dela.
            ix_total = next((k for k, w in enumerate(l) if w["text"] == "Total" and not (k + 1 < len(l) and l[k + 1]["text"].startswith("L\u00edquido"))), None)
            if ix_total is not None:
                nums_t = [w for w in l[ix_total + 1:] if _RE_NUM.match(w["text"])]
                vals = [_num(w["text"]) for w in nums_t]
                if len(vals) == 2:
                    rec["total_proventos"], rec["total_descontos"] = vals
                elif len(vals) == 1:                   # so' um dos lados preenchido: o lado vem da posicao
                    w = nums_t[0]
                    if w["x1"] > limite_desc:
                        rec["total_proventos"], rec["total_descontos"] = 0.0, vals[0]
                    else:
                        rec["total_proventos"], rec["total_descontos"] = vals[0], 0.0
                continue
            primeiro = l[0]["text"]
            if re.fullmatch(r"\d{1,4}(?:\.\d+)?", primeiro) and l[0]["x0"] < x_ref - 150:
                partes = [w for w in l[1:]]
                # dinheiro de provento/desconto fica a direita da coluna Referencia; numeros da propria referencia ("27,50 %") ficam a esquerda
                dinheiro = [w for w in partes if _RE_NUM.match(w["text"]) and w["x1"] >= x_prov_1 - 40]
                desc_words = [w for w in partes if w["x0"] < x_ref - 2 and w not in dinheiro]
                ref_words = [w for w in partes if w["x0"] >= x_ref - 2 and w not in dinheiro]
                descricao = " ".join(w["text"] for w in desc_words).strip()
                if descricao.startswith("-"):           # linha de continuacao do evento anterior ("1 - NOME DO DEPENDENTE ... 153,24")
                    if pendente is not None and dinheiro:
                        for w in dinheiro:
                            if w["x1"] > limite_desc:
                                pendente["desconto"] = round(pendente["desconto"] + _num(w["text"]), 2)
                            else:
                                pendente["provento"] = round(pendente["provento"] + _num(w["text"]), 2)
                        pendente = None
                    continue
                if not dinheiro:                        # evento cujo valor vem na(s) linha(s) seguinte(s)
                    pendente = {"ev": int(primeiro.split(".")[0]), "descricao": descricao, "referencia": " ".join(w["text"] for w in ref_words).strip(),
                                "provento": 0.0, "desconto": 0.0, "informativo": False}
                    rec["eventos"].append(pendente)
                    continue
                pendente = None
                prov = des = 0.0
                for w in dinheiro:
                    if w["x1"] > limite_desc:
                        des += _num(w["text"])
                    else:
                        prov += _num(w["text"])
                ev = {"ev": int(primeiro.split(".")[0]), "descricao": descricao, "referencia": " ".join(w["text"] for w in ref_words).strip(),
                      "provento": round(prov, 2), "desconto": round(des, 2), "informativo": False}
                if descricao.startswith("Inf.") or "Aux\u00edlio Doen" in descricao:   # linha so' informativa (vale alimentacao, auxilio doenca): nao entra no total do recibo
                    ev.update(informativo=True, provento=0.0, desconto=0.0, referencia=(ev["referencia"] + f" (informativo R$ {prov + des:.2f})").strip())
                rec["eventos"].append(ev)
                continue
            if t.startswith("Sal\u00e1rio Base"):
                estado = "rodape"
                continue
            # linha do total liquido com o texto do subnivel a esquerda esta tratada abaixo
        if estado in ("tabela", "rodape") and t.startswith("Sal\u00e1rio Base"):
            estado = "rodape"
            continue
        if estado == "rodape":
            vals = [_num(w["text"]) for w in l if _RE_NUM.match(w["text"])]
            if len(vals) >= 4:
                rec["salario_base"], rec["fgts_mes"] = vals[0], vals[3]
                estado = "fim"
    if rec["cadastro"] is None:
        return None
    return rec


def _marcar_informativos(r: dict) -> None:
    """Se a soma dos proventos dos eventos passa do Total do recibo, procura 1 a 3 eventos que, retirados, fecham a conta
    (eventos so' informativos que o recibo mostra mas nao soma) e os marca como informativos."""
    from itertools import combinations
    if r["total_proventos"] is None:
        return
    ev = r["eventos"]
    dif = round(sum(e["provento"] for e in ev) - r["total_proventos"], 2)
    if abs(dif) <= 0.02:
        return
    cand = [e for e in ev if e["provento"] > 0 and not e["informativo"]]
    for n in (1, 2, 3):
        for comb in combinations(cand, n):
            if abs(sum(e["provento"] for e in comb) - dif) <= 0.02:
                for e in comb:
                    e["referencia"] = (e["referencia"] + f" (informativo R$ {e['provento']:.2f})").strip()
                    e.update(informativo=True, provento=0.0)
                return


def ler_recibos_pdf(conteudo: bytes) -> dict:
    """Le o PDF de recibos. Devolve {'competencia','recibos':[...], 'avisos':[...], 'paginas', 'recibos_lidos'}.
    Cada recibo: ver `_ler_bloco`. Recibo repetido (via da empresa + via do colaborador) conta uma vez."""
    import pdfplumber
    if not conteudo or conteudo[:4] != b"%PDF":
        raise ErroFolha("Este arquivo nao e' um PDF. Envie o PDF dos recibos de pagamento (Demonstrativo de Pagamento de Salario).")
    recibos, vistos, por_pessoa, avisos, lidos = [], {}, {}, [], 0
    try:
        pdf = pdfplumber.open(io.BytesIO(conteudo))
    except Exception:
        raise ErroFolha("Nao consegui abrir o PDF. Confira se o arquivo nao esta protegido ou corrompido.")
    with pdf:
        paginas = len(pdf.pages)
        for n, pg in enumerate(pdf.pages, 1):
            ws = pg.extract_words(keep_blank_chars=False, use_text_flow=False)
            topos = sorted(w["top"] for w in ws if w["text"] == "Demonstrativo")
            if not topos:
                continue
            # cada recibo vai do "Demonstrativo" (o cabecalho comeca ~36 pontos acima da linha de Cadastro) ate o proximo
            cortes = topos + [pg.height + 1]
            for k in range(len(topos)):
                ini = cortes[k] - 10
                fim = cortes[k + 1] - 10 if k + 1 < len(topos) else pg.height + 1
                bloco = [w for w in ws if ini <= w["top"] < fim]
                rec = _ler_bloco(bloco, avisos.append)
                if rec is None:
                    avisos.append(f"Pagina {n}: um recibo nao pode ser lido (layout diferente do esperado).")
                    continue
                lidos += 1
                chave = (rec["empresa"], rec["cadastro"], rec["fl"])
                if chave in vistos:
                    if vistos[chave] != rec["eventos"]:
                        avisos.append(f"Pagina {n}: a segunda via do cadastro {rec['cadastro']} (empresa {rec['empresa']}) e' diferente da primeira; foi mantida a primeira.")
                    continue
                vistos[chave] = [dict(e) for e in rec["eventos"]]          # copia: a junta de paginas (FL 02) altera o recibo guardado
                ant = por_pessoa.get((rec["empresa"], rec["cadastro"]))
                if ant is None:
                    por_pessoa[(rec["empresa"], rec["cadastro"])] = rec
                    recibos.append(rec)
                else:                                   # continuacao do recibo (FL 02...): junta os eventos; totais vem da folha que os traz
                    ant["eventos"].extend(rec["eventos"])
                    for k in ("total_proventos", "total_descontos", "liquido", "fgts_mes", "salario_base", "subnivel_texto"):
                        if rec[k] is not None:
                            ant[k] = rec[k]
    if not recibos:
        raise ErroFolha("Nao encontrei recibos neste PDF. Envie o PDF 'Recibos de Pagamento' (Demonstrativo de Pagamento de Salario).")
    comps = Counter(r["competencia"] for r in recibos if r["competencia"])
    competencia = comps.most_common(1)[0][0] if comps else None
    if len(comps) > 1:
        avisos.append(f"O PDF tem mais de uma competencia ({', '.join(sorted(comps))}); vale a mais frequente ({competencia}).")
    empresas = sorted({r["empresa"] for r in recibos})
    for r in recibos:
        if r["total_proventos"] is None or r["total_descontos"] is None:
            # rede de seguranca: nunca deixar o total em branco (um recibo sem total some do custo da folha sem ninguem perceber)
            sp0 = round(sum(e["provento"] for e in r["eventos"]), 2)
            sd0 = round(sum(e["desconto"] for e in r["eventos"]), 2)
            if r["total_proventos"] is None:
                r["total_proventos"] = sp0
            if r["total_descontos"] is None:
                r["total_descontos"] = sd0
            avisos.append(f"Cadastro {r['cadastro']} (empresa {r['empresa']}): nao li o total do recibo; usei a soma dos eventos (proventos {sp0:.2f}, descontos {sd0:.2f}). Confira.")
        _marcar_informativos(r)
        sp = round(sum(e["provento"] for e in r["eventos"]), 2)
        sd = round(sum(e["desconto"] for e in r["eventos"]), 2)
        if r["total_proventos"] is not None and abs(sp - r["total_proventos"]) > 0.02:
            avisos.append(f"Cadastro {r['cadastro']} (empresa {r['empresa']}): soma dos proventos {sp:.2f} difere do total do recibo {r['total_proventos']:.2f}.")
        if r["total_descontos"] is not None and abs(sd - r["total_descontos"]) > 0.02:
            avisos.append(f"Cadastro {r['cadastro']} (empresa {r['empresa']}): soma dos descontos {sd:.2f} difere do total do recibo {r['total_descontos']:.2f}.")
        if r["liquido"] is not None and r["total_proventos"] is not None and abs(r["total_proventos"] - r["total_descontos"] - r["liquido"]) > 0.02:
            avisos.append(f"Cadastro {r['cadastro']} (empresa {r['empresa']}): liquido {r['liquido']:.2f} nao fecha com proventos - descontos.")
        if not r["subnivel_texto"]:
            avisos.append(f"Cadastro {r['cadastro']} (empresa {r['empresa']}): nao achei o texto do subnivel (departamento {r['departamento']}).")
    return {"competencia": competencia, "empresas": empresas, "paginas": paginas, "recibos_lidos": lidos, "recibos": recibos, "avisos": avisos}


def resumo_por_recibo(r: dict) -> dict:
    """Numeros do recibo que o painel usa: salario CLT (evento 1), hora extra, DSR s/HE, proventos e custo (proventos + FGTS)."""
    ev = r["eventos"]
    g = lambda cods: round(sum(e["provento"] for e in ev if e["ev"] in cods), 2)
    return {"salario": g({EVENTO_SALARIO}), "hora_extra": g(EVENTOS_HE), "dsr_he": g(EVENTOS_DSR),
            "proventos": r["total_proventos"] or 0.0, "fgts": r["fgts_mes"] or 0.0}
