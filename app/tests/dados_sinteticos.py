# -*- coding: utf-8 -*-
"""
Balancetes SINTETICOS (valores inventados, nenhum dado real) no mesmo formato do CSV do sistema contabil.
Servem para testar motor, importador, banco e telas sem depender de dados reais (o repositorio e' publico).

Modelo: caixa 1.000.000 + concessao 5.000.000 = BNDES LP 3.000.000 + capital 3.000.000 (abertura).
Cada mes: custo de construcao E (a pagar ao fornecedor), rendimento R (entra no caixa), PIS P (sai do caixa).
Sinais iguais aos do sistema: classe 1/2 saldo positivo na natureza; classe 5 = debito - credito; classe 4 = credito - debito;
conta 8 = -(saldo5 - saldo4). Mes encerrado: contas de resultado com saldo 0 (debito = credito) e o resultado vai para 2.4.13.
"""
from __future__ import annotations

import calendar
import io

# (classificacao, nome, natureza D/C do saldo) das contas analiticas
CONTAS = [
    ("1.1.01.002.001", "Banco Alfa C/C", "D", "1.1.01.002"),
    ("1.2.08.001.900", "Ativo de concessao", "D", None),
    ("2.1.03.001.001", "Fornecedor Beta Ltda", "C", None),
    ("2.2.01.001.001.001", "Banco Bndes", "C", None),
    ("2.4.01.001.900", "Acionista Gama Ltda", "C", None),
    ("2.4.13.001.002", "Prejuizos Acumulados", "C", None),
    ("5.1.05.001.001", "Custo de construcao", "R5", None),
    ("5.7.10.001.901", "Rendimentos s/ aplicacoes", "R5", None),
    ("4.1.03.005.004", "PIS sobre receitas", "R4", None),
]
ABERTURA = {"1.1.01.002.001": 1_000_000.00, "1.2.08.001.900": 5_000_000.00, "2.2.01.001.001.001": 3_000_000.00, "2.4.01.001.900": 3_000_000.00}
NOMES_SINT = {"1": "Ativo", "1.1": "Circulante", "1.1.01": "Disponivel", "1.1.01.002": "Depositos Bancarios a Vista", "1.2": "Nao Circulante",
              "1.2.08": "Imobilizado", "1.2.08.001": "Concessao", "2": "Passivo", "2.1": "Circulante", "2.1.03": "Fornecedores",
              "2.1.03.001": "Fornecedores Nacionais", "2.2": "Nao Circulante", "2.2.01": "Instituicoes Financeiras", "2.2.01.001": "Emprestimos",
              "2.2.01.001.001": "Emprestimos", "2.4": "Patrimonio Liquido", "2.4.01": "Capital Social", "2.4.01.001": "Capital Subscrito",
              "2.4.13": "Prejuizos", "2.4.13.001": "Prejuizos Acumulados", "4": "Receitas", "4.1": "Receita Bruta", "4.1.03": "Impostos", "4.1.03.005": "Deducoes",
              "5": "Custos e Despesas", "5.1": "Custos", "5.1.05": "Construcao", "5.1.05.001": "Custo de construcao", "5.7": "Resultado Financeiro",
              "5.7.10": "Receitas Financeiras", "5.7.10.001": "Receitas Financeiras", "8": "*** Resultado do Exercicio ***"}


def _ancestrais(cl):
    p = cl.split(".")
    return [".".join(p[:i]) for i in range(1, len(p))]


def gerar_meses(operacoes: list, ano: int = 2026, encerrar_ultimo: bool = False):
    """operacoes: lista de (E, R, P) por mes (jan, fev...). Retorna {'AAAA-MM': contas} no formato do motor."""
    saldos = dict(ABERTURA)               # saldo final por conta de balanco
    perdas_ant = 0.0                      # soma dos resultados dos meses ja' fechados em 2.4.13 (valor negativo)
    out = {}
    ids = {cl: str(7000 + i) for i, (cl, *_r) in enumerate(CONTAS)}
    for idx, (E, R, P) in enumerate(operacoes):
        enc = encerrar_ultimo and idx == len(operacoes) - 1
        mov = {cl: [0.0, 0.0] for cl, *_ in CONTAS}               # [debito, credito]
        mov["5.1.05.001.001"][0] += E
        mov["2.1.03.001.001"][1] += E
        mov["1.1.01.002.001"][0] += R
        mov["5.7.10.001.901"][1] += R
        mov["4.1.03.005.004"][0] += P
        mov["1.1.01.002.001"][1] += P
        resultado = R - E - P                                    # negativo = prejuizo
        analiticas = []
        for cl, nome, nat, _ in CONTAS:
            deb, cred = mov[cl]
            if cl == "2.4.13.001.002":
                ant = round(perdas_ant, 2)
                if enc:
                    deb, cred = round(-resultado, 2) if resultado < 0 else 0.0, round(resultado, 2) if resultado > 0 else 0.0
                    sal = round(ant - deb + cred, 2)
                else:
                    sal = ant
            elif nat in ("D", "C"):
                ant = round(saldos.get(cl, 0.0), 2)
                sal = round(ant + deb - cred, 2) if nat == "D" else round(ant + cred - deb, 2)
                saldos[cl] = sal
            else:                                                 # resultado: ant = 0 (balancete mensal)
                ant = 0.0
                if enc:                                           # encerrado: debito = credito, saldo 0
                    if nat == "R5" and cl == "5.7.10.001.901":
                        deb = cred = R
                    elif nat == "R5":
                        cred = deb
                    else:
                        cred = deb
                    sal = 0.0
                else:
                    sal = round(deb - cred, 2) if nat == "R5" else round(cred - deb, 2)
            analiticas.append({"id": ids[cl], "sint": False, "cl": cl, "nome": nome, "ant": ant, "deb": round(deb, 2), "cred": round(cred, 2), "sal": sal})
        if enc:
            perdas_ant = round(perdas_ant + resultado, 2)         # so' vale para o proximo mes (nao ha' proximo)
        contas = list(analiticas)
        agg = {}
        for a in analiticas:
            for anc in _ancestrais(a["cl"]):
                g = agg.setdefault(anc, {"ant": 0.0, "deb": 0.0, "cred": 0.0, "sal": 0.0})
                for k in g:
                    g[k] += a[k]
        s5, s4 = agg["5"], agg["4"]
        agg["8"] = {"ant": 0.0, "deb": -(s5["deb"] - s4["deb"]), "cred": -(s5["cred"] - s4["cred"]), "sal": -(s5["sal"] - s4["sal"])}
        for n, (cl, g) in enumerate(sorted(agg.items(), key=lambda kv: [int(x) for x in kv[0].split(".")])):
            contas.append({"id": str(1 + n) if cl != "8" else "4854", "sint": True, "cl": cl, "nome": NOMES_SINT.get(cl, cl),
                           **{k: round(v, 2) for k, v in g.items()}})
        contas.sort(key=lambda c: [int(x) for x in c["cl"].split(".")] + ([0] if c["sint"] else [1]))
        # fecha o mes seguinte: perdas do mes viram saldo anterior de 2.4.13 (so' quando o mes NAO foi encerrado ainda aqui)
        if not enc:
            perdas_ant = round(perdas_ant + resultado, 2)
        out[f"{ano}-{idx + 1:02d}"] = contas
    return out


def _num(v):
    t = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"({t})" if v < 0 else t


def csv_texto(contas: list, cnpj="00.000.000/0001-91", empresa="EMPRESA SINTETICA LTDA", ini="01/01/2026", fim="31/01/2026") -> bytes:
    """CSV no layout do sistema contabil (cp1252, ';', negativo entre parenteses)."""
    f = io.StringIO()
    f.write(f'\r\n\r\n"0001  {empresa}\r\nCNPJ: {cnpj}\r\n";"08/10/2026 10:22 Pág:0001"\r\n"Período: {ini} a {fim}"\r\n"Balancete – Societário"\r\n""\r\n\r\n\r\n')
    f.write('"Balancete"\r\n"Valores expressos em Reais (R$)"\r\n\r\n"Conta";"S";"Classificação";"Saldo Ant.";"Débito";"Crédito";"Saldo"\r\n"____"\r\n\r\n')
    for c in contas:
        f.write(f'{c["id"]};{"\"S\"" if c["sint"] else ""};"{c["cl"]}   {c["nome"]}";{_num(c["ant"])};;{_num(c["deb"])};{_num(c["cred"])};{_num(c["sal"])};\r\n\r\n')
    f.write('"";\r\n"FULANO";"CICRANO"\r\n"Administrador";"Contador"\r\n')
    return f.getvalue().encode("cp1252")


def fim_do_mes(ano, mes):
    return f"{calendar.monthrange(ano, mes)[1]:02d}/{mes:02d}/{ano}"


def pdf_balancete(contas: list, cnpj="00.000.000/0001-91", empresa="EMPRESA SINTETICA LTDA", ini="01/01/2026", fim="31/01/2026",
                  ult_mov=False, linhas_por_pagina=40, linhas_extras=()) -> bytes:
    """PDF (texto) no layout do 'Balancete - Societario' do sistema contabil, com varias paginas (cabecalho repetido). So' para testes."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    def br(v):
        s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"({s})" if v < 0 else s

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    W, H = landscape(A4)
    paginas = [contas[i:i + linhas_por_pagina] for i in range(0, max(len(contas), 1), linhas_por_pagina)]
    for n, lote in enumerate(paginas, 1):
        y = H - 30
        c.setFont("Helvetica", 7)
        for txt in (f"0001 {empresa}    08/10/2026 10:22 Pág:{n:04d}", f"CNPJ: {cnpj}", f"Período: {ini} a {fim}",
                    "Balancete – Societário", "Balancete", "Valores expressos em Reais (R$)"):
            c.drawString(30, y, txt); y -= 10
        cab = "Conta S Classificação" + (" Ult. Mov." if ult_mov else "") + " Saldo Ant. Débito Crédito Saldo"
        c.drawString(30, y, cab); y -= 12
        for k in lote:
            um = " 28/01/26" if (ult_mov and not k["sint"]) else ""
            c.drawString(30, y, f'{k["id"]} {"S " if k["sint"] else ""}{k["cl"]} {k["nome"]}{um} {br(k["ant"])} {br(k["deb"])} {br(k["cred"])} {br(k["sal"])}')
            y -= 10
        if n == len(paginas):
            for txt in linhas_extras:
                c.drawString(30, y, txt); y -= 10
        c.showPage()
    c.save()
    return buf.getvalue()
