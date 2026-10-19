# -*- coding: utf-8 -*-
"""Gera um PDF SINTETICO no layout do 'Comparativo Orcado X Realizado Agrupado' (Orcamento ADM) do Sienge. Valores e contas INVENTADOS.
Layout: paisagem A4; ate 4 meses por bloco de paginas (colunas Orcado/Realizado/Saldo por mes); as contas continuam em varias paginas do bloco
e os meses se repetem em todas as paginas do bloco; no ultimo bloco pode haver uma coluna 'Total'."""
import io

from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas

H = 595
MESES = ["Jan/2026", "Fev/2026", "Mar/2026", "Abr/2026", "Mai/2026", "Jun/2026"]
# (codigo, conta, tipo, orcado por mes, realizado por mes) -- folhas; os totais (T) sao somados
FOLHAS = {
    "1.01.01": ("Receita de teste", "R", [0, 0, 0, 0, 0, 0], [10.0, 0.0, 5.5, 0, 0, 7.25]),
    "1.01.02": ("Rendimentos de teste", "R", [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]),
    "2.01.01": ("Salarios de teste | ADM", "R", [1000, 1000, 1100, 1100, 1200, 1200], [1050.5, 900, 1100, 1250.75, 1190, 1210]),
    "2.01.02": ("Aluguel de teste | ADM", "R", [500, 500, 500, 500, 500, 500], [500, 500, 520, 500, 500, 480]),
    "2.02.01": ("Canteiro de teste", "M", [0, 0, 0, 0, 0, 0], [0, 0, 80, 0, 0, 0]),
}
TOTAIS = {"1.01": ["1.01.01", "1.01.02"], "1.": None, "2.01": ["2.01.01", "2.01.02"], "2.02": ["2.02.01"]}
NOMES_T = {"1": "ENTRADAS | RECEITAS", "1.01": "RECEITAS DE TESTE", "2": "SAIDAS/CUSTOS/DESPESAS", "2.01": "DESPESAS DE TESTE", "2.02": "OUTRAS DE TESTE"}


def br(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tabela(com_filho_errado=False):
    """Lista de linhas [(codigo, conta, tipo, [(orc, real) por mes])] na ordem do relatorio, com totais coerentes (ou 1 total errado)."""
    n = len(MESES)
    folha = {c: [(f[2][i], f[3][i]) for i in range(n)] for c, f in FOLHAS.items()}

    def soma(prefixo):
        return [(round(sum(v[i][0] for c, v in folha.items() if c.startswith(prefixo)), 2), round(sum(v[i][1] for c, v in folha.items() if c.startswith(prefixo)), 2)) for i in range(n)]
    linhas = [("1", NOMES_T["1"], "T", soma("1.")), ("1.01", NOMES_T["1.01"], "T", soma("1.01")),
              ("1.01.01", FOLHAS["1.01.01"][0], "R", folha["1.01.01"]), ("1.01.02", FOLHAS["1.01.02"][0], "R", folha["1.01.02"]),
              ("2", NOMES_T["2"], "T", soma("2.")), ("2.01", NOMES_T["2.01"], "T", soma("2.01")),
              ("2.01.01", FOLHAS["2.01.01"][0], "R", folha["2.01.01"]), ("2.01.02", FOLHAS["2.01.02"][0], "R", folha["2.01.02"]),
              ("2.02", NOMES_T["2.02"], "T", soma("2.02")), ("2.02.01", FOLHAS["2.02.01"][0], "M", folha["2.02.01"])]
    if com_filho_errado:                         # o total 2.01 de Jan fica 10,00 maior que a soma dos filhos
        i = [x[0] for x in linhas].index("2.01")
        v = list(linhas[i][3]); v[0] = (v[0][0], v[0][1] + 10.0)
        linhas[i] = (linhas[i][0], linhas[i][1], linhas[i][2], v)
    return linhas


def _pagina(c, rotulos, linhas_pagina, rodape, titulo=True):
    """Desenha uma pagina. `rotulos` = rotulos de coluna (meses ou 'Total'), ate 4; `linhas_pagina` = [(cod, conta, tipo, [(orc, real, saldo)...])]."""
    c.setFont("Helvetica", 7)
    def y(top):                                   # "top" medido do alto da pagina (como o pdfplumber)
        return H - top - 7
    if titulo:
        c.drawString(445, y(60), "Comparativo Orçado X Realizado Agrupado")
    c.drawString(137, y(107), "Agrupar por Agrupamento")
    c.drawString(159, y(117), "Período 01/01/2026 a 30/06/2026")
    c.drawString(137, y(148), "Agrupamento 11 - ORÇAMENTO TOTAL | ADMINISTRATIVO | 2026")
    x1 = [301, 347, 393]
    for g, rot in enumerate(rotulos):
        c.drawString(309 + 137.5 * g, y(169), rot)
    for g in range(4):                            # cabecalhos Orcado/Realizado/Saldo (os grupos sem mes ficam vazios, como no PDF real)
        for j, nome in enumerate(["Orçado", "Realizado", "Saldo"]):
            c.drawRightString(x1[j] + 137.5 * g, y(178), nome)
    c.drawString(37, y(178), "Código"); c.drawString(83, y(178), "Conta"); c.drawString(242, y(178), "Tipo")
    top = 187
    for cod, conta, tipo, cols in linhas_pagina:
        c.drawString(37, y(top), cod); c.drawString(83, y(top), conta); c.drawString(247, y(top), tipo)
        for g, (orc, real, sal) in enumerate(cols):
            for j, v in enumerate((orc, real, sal)):
                c.drawRightString(x1[j] + 137.5 * g, y(top), br(v))
        top += 8.5
    for nome, cols in rodape:
        c.drawString(37, y(top), nome)
        for g, (orc, real, sal) in enumerate(cols):
            for j, v in enumerate((orc, real, sal)):
                c.drawRightString(x1[j] + 137.5 * g, y(top), br(v))
        top += 8.5
    c.drawString(37, y(551), "SIENGE / STARIAN")
    c.showPage()


def pdf_orcamento_sintetico(com_filho_errado: bool = False, com_total: bool = True) -> bytes:
    """6 meses: bloco 1 = Jan-Abr; bloco 2 = Mai, Jun e (opcional) 'Total' = soma do periodo (Jan-Jun). Cada bloco tem 2 paginas (as contas continuam na 2a)."""
    tab = _tabela(com_filho_errado)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    blocos = [(0, 4), (4, 6)]
    for ini, fim in blocos:
        idx = list(range(ini, fim))
        rotulos = [MESES[i] for i in idx]
        if com_total and ini == 4:
            rotulos.append("Total")
        dados = []
        for cod, conta, tipo, mv in tab:
            cols = [(mv[i][0], mv[i][1], round(mv[i][1] - mv[i][0], 2)) for i in idx]
            if com_total and ini == 4:
                o, r = round(sum(m[0] for m in mv), 2), round(sum(m[1] for m in mv), 2)     # Total = periodo todo
                cols.append((o, r, round(r - o, 2)))
            dados.append((cod, conta, tipo, cols))
        # rodape: Diferenca = entradas - saidas (orcado e realizado), e acumulada
        def tot(cod):
            return next(d for d in dados if d[0] == cod)[3]
        dif = [(round(a[0] - b[0], 2), round(a[1] - b[1], 2), 0.0) for a, b in zip(tot("1"), tot("2"))]
        dif = [(o, r, round(r - o, 2)) for o, r, _ in dif]
        acum, acc = [], [0.0, 0.0]
        for o, r, _ in dif[:len(idx)]:
            acc[0] += o; acc[1] += r
            acum.append((round(acc[0], 2), round(acc[1], 2), round(acc[1] - acc[0], 2)))
        rodape = [("Diferença", dif[:len(idx)]), ("Diferença acumulada", acum)]
        _pagina(c, rotulos, dados[:6], [])
        _pagina(c, rotulos, dados[6:], rodape)
    c.save()
    return buf.getvalue()
