# -*- coding: utf-8 -*-
"""Gera um PDF SINTETICO no layout dos 'Recibos de Pagamento' (Demonstrativo de Pagamento de Salario) - pessoas e valores INVENTADOS.
Cada pagina traz o recibo duas vezes (via da empresa e via do colaborador), como no PDF real; um dos colaboradores tem o recibo em 2 folhas (FL 01 e 02)."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def br(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _via(c, y0, emp, cad, nome, cbo, depto, fl, cargo, evs, tot_p=None, tot_d=None, liq=None, sub=None, fgts=None, continua=False, comp="09/2026", msg=None):
    """y0 = topo da via (pontos a partir do topo da pagina). evs: [(codigo, descricao, referencia, provento, desconto)] ou ('sub', texto, desconto)."""
    H = A4[1]
    y = lambda dy: H - (y0 + dy)
    c.setFont("Helvetica", 7)
    c.drawString(9, y(5), f"{emp[0]}-{emp[1]}")
    c.drawString(305, y(5), "Demonstrativo de Pagamento de Salário")
    c.drawString(9, y(18), f"{emp[1]} Maringá - PR")
    c.drawString(440, y(18), f"{comp} Mensal")
    c.drawString(9, y(36), "Cadastro")
    c.drawString(60, y(36), "Nome do Funcionário")
    c.drawString(427, y(36), "Local")
    c.drawString(506, y(36), "Departamento")
    c.drawString(9, y(48), f"{cad}")
    c.drawString(60, y(48), f"{nome}     {cbo}   {emp[0].lstrip("0")}   1    {depto}   {fl}")
    c.drawString(60, y(60), f"{cargo}                    Data Admissão:   02/02/2025")
    c.drawString(9, y(72), "Ev")
    c.drawString(45, y(72), "Descrição")
    c.drawString(354, y(72), "Referência")
    c.drawString(448, y(72), "Proventos")
    c.drawString(547, y(72), "Descontos")
    yy = 84
    for e in evs:
        if e[0] == "sub":
            c.drawString(30, y(yy), e[1])
            c.drawRightString(589, y(yy), br(e[2]))
        else:
            cod, desc, ref, prov, desc_v = e
            c.drawString(9, y(yy), str(cod))
            c.drawString(45, y(yy), desc)
            if ref:
                c.drawString(354, y(yy), ref)
            if prov:
                c.drawRightString(488, y(yy), br(prov))
            if desc_v:
                c.drawRightString(589, y(yy), br(desc_v))
        yy += 12
    yy = max(yy + 6, 200)
    if continua:
        c.drawString(45, y(yy), "Continua...")
        c.drawString(338, y(yy), "Total")
        c.drawString(362, y(yy + 24), "Total Líquido")
        return
    if msg:                                    # mensagem do recibo (ex.: aniversario) na MESMA linha do "Total", como no PDF real
        c.drawString(60, y(yy), msg)
    c.drawString(338, y(yy), "Total")
    c.drawRightString(488, y(yy), br(tot_p))
    c.drawRightString(589, y(yy), br(tot_d))
    c.drawString(45, y(yy + 24), sub)
    c.drawString(338, y(yy + 24), "Total Líquido")
    c.drawRightString(589, y(yy + 24), br(liq))
    c.drawString(60, y(yy + 40), "Salário Base      Sal Cont INSS      Bas Cálc FGTS      FGTS Mês      Base IRRF      Faixa Dep")
    c.drawString(60, y(yy + 52), f"{br(3000)}      {br(tot_p)}      {br(tot_p)}      {br(fgts)}      {br(0)}      {br(0)}   00")


def pdf_folha_sintetico(empresa=("0468", "EMPRESA TESTE LTDA")) -> bytes:
    """3 colaboradores: A (HE 50% + DSR + linha informativa), B (HE 110% + evento com valor na linha de baixo), C (auxilio doenca + recibo em 2 folhas)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    cod = empresa[0].lstrip("0") or "0"
    emp = (empresa[0], empresa[1])
    A = dict(cad=10, nome="ANA FICTICIA SILVA", cbo="724205", depto="001.004", fl="01", cargo="MONTADOR",
             evs=[(1, "Horas Normais Diurnas", "30 Dias", 3000.00, 0), (35, "Horas Extras 50% Diurnas", "010:00 hs", 500.00, 0),
                  (59, "DSR S/Horas Extras Diurnas", "005:00 hs", 100.00, 0), (840, "Inf. Vale Alimentação Ticket/Cartão", "", 600.00, 0),
                  (1950, "INSS", "14,00 %", 0, 300.00)],
             tot_p=3600.00, tot_d=300.00, liq=3300.00, sub="OBRA TESTE UM", fgts=288.00, msg="Parabens ! Feliz Aniversario 23/10")
    B = dict(cad=11, nome="BRUNO IMAGINARIO LIMA", cbo="715615", depto="001.010", fl="01", cargo="ELETRICISTA",
             evs=[(1, "Horas Normais Diurnas", "30 Dias", 4000.00, 0), (1029, "Horas Extra 110% Diurna", "004:00 hs", 200.00, 0),
                  (1817, "Desconto Consultas", "", 0, 0), ("sub", "1 - DEPENDENTE FICTICIO", 90.00), (1950, "INSS", "14,00 %", 0, 400.00)],
             tot_p=4200.00, tot_d=490.00, liq=3710.00, sub="OBRA TESTE DOIS", fgts=336.00)
    C1 = dict(cad=12, nome="CARLA INVENTADA SOUZA", cbo="721210", depto="001.004", fl="01", cargo="ENCARREGADA",
              evs=[(1, "Horas Normais Diurnas", "30 Dias", 3000.00, 0), (49, "Horas Extra 100% Diurna", "006:00 hs", 300.00, 0),
                   (200, "Horas Auxílio Doença Diurnas", "30 Dias", 2000.00, 0)], continua=True)
    C2 = dict(cad=12, nome="CARLA INVENTADA SOUZA", cbo="721210", depto="001.004", fl="02", cargo="ENCARREGADA",
              evs=[(1031, "Taxa Assistencial", "1,50 %", 0, 20.00), (1950, "INSS", "14,00 %", 0, 250.00)],
              tot_p=3300.00, tot_d=270.00, liq=3030.00, sub="OBRA TESTE UM", fgts=264.00)
    for pagina in ([A, A], [B, B], [C1, C1], [C2, C2]):
        for k, d in enumerate(pagina):
            _via(c, 10 + k * 417, emp, **d)
        c.showPage()
    c.save()
    return buf.getvalue()
