# -*- coding: utf-8 -*-
"""
GDF - Gerador do relatorio PDF "Demonstrativos Financeiros" (A4, padrao visual do Grupo Enermais: Poppins, navy/laranja).
Layout do esboco v0.2 (aprovado por Rafael "por enquanto"; refinar apos o retorno do Edilson). Tudo que muda por empresa vem em
`ctx["empresa"]`; numeros e textos vem prontos de relatorio_dados (nenhum calculo contabil aqui). O PDF e' sempre gerado em
memoria (bytes): nada e' gravado em disco e nenhum PDF assinado e' lido ou regravado.
"""
from __future__ import annotations

import io
import os
import threading
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import relatorio_dados as RD
import tabelas
from relatorio_fmt import brl, fnum, mm, mmn, neg, pct, razao, varp

ASSETS = Path(__file__).resolve().parent / "assets_relatorio"
_LOCK = threading.Lock()
_FONTES = False

# ------------------------------------------------------------------ tokens (padrao Enermais)
NAVY = HexColor("#171C60"); ORANGE = HexColor("#EA9527"); BRAND_OR = HexColor("#F99D20")
GREY = HexColor("#525252"); GREY_BG = HexColor("#F6F8FB"); BORDER = HexColor("#DADFE8")
NEG_FILL = HexColor("#E9962A"); NEG_TXT = HexColor("#9A5200"); POS_TXT = HexColor("#1A7A3C")
ROSE = HexColor("#C98A98"); WHITE = HexColor("#FFFFFF")
BLUES = [HexColor(h) for h in ["#B4B9D6", "#9A9CC4", "#7F84AE", "#5C6091", "#3A3F7A", "#171C60"]]
MID = HexColor("#5C6091"); LIGHT = HexColor("#B4B9D6")
W, H = 595.28, 841.89
MX = 40.0; CW = W - 2 * MX


def _registrar_fontes():
    global _FONTES
    if _FONTES:
        return
    for n, f in [("P", "Poppins-Regular"), ("PM", "Poppins-Medium"), ("PB", "Poppins-Bold"), ("PI", "Poppins-Italic")]:
        pdfmetrics.registerFont(TTFont(n, str(ASSETS / "fonts" / (f + ".ttf"))))
    _FONTES = True


# estado da geracao em andamento (preenchido por gerar_pdf, sob trava)
X = {}      # ctx de relatorio_dados.montar
T = {}      # textos de leitura (padrao + edicoes da contadora)
STATUS = {"txt": "RASCUNHO", "gerado": ""}


def BP(k, i=2): return X["bp"][k][i]          # i: 0=31/12 anterior, 1=mes anterior, 2=mes de referencia, 3=var R$, 4=var %
def DR(k, i=2): return X["dre"][k][i]         # i: 0=acumulado ate' mes anterior, 1=mes, 2=acumulado
def IN(k, i=2): return X["ind"][k][i]
def E(k): return X["empresa"][k]


def _logo():
    f = E("logo")
    p = ASSETS / f if f else None
    return ImageReader(str(p)) if p and p.exists() else None


def paras(c, chave, y, size=8.2, lead=12.2, gap=4):
    """Escreve o texto de leitura `chave` (varios paragrafos separados por linha em branco)."""
    ks = sorted(k for k in T if k == chave or k.startswith(chave + "_"))
    s = "\n".join(b.strip() for k in ks for b in (T.get(k) or "").split("\n") if b.strip())
    return para(c, s, MX, y, CW, size=size, lead=lead, gap=gap) if s else y

def col(c, color): c.setFillColor(color); c.setStrokeColor(color)
def txt(c, x, y, s, font="P", size=8, color=GREY, al="l"):
    c.setFont(font, size); c.setFillColor(color)
    if al == "l": c.drawString(x, y, s)
    elif al == "r": c.drawRightString(x, y, s)
    else: c.drawCentredString(x, y, s)
def para(c, s, x, y, w, font="P", size=8.2, lead=12.2, color=GREY, gap=5):
    """parágrafo(s) com quebra automática; retorna novo y."""
    for blk in s.split("\n"):
        lines = simpleSplit(blk, font, size, w)
        for ln in lines:
            txt(c, x, y, ln, font, size, color); y -= lead
        y -= gap
    return y
def rect(c, x, y, w, h, fill=None, stroke=None, r=0, lw=0.6):
    if fill is not None: c.setFillColor(fill)
    if stroke is not None: c.setStrokeColor(stroke); c.setLineWidth(lw)
    if r: c.roundRect(x, y, w, h, r, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)
    else: c.rect(x, y, w, h, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)
def hline(c, x1, x2, y, color=BORDER, lw=0.5):
    c.setStrokeColor(color); c.setLineWidth(lw); c.line(x1, y, x2, y)
def numcolor(v, base=NAVY): return NEG_TXT if (v is not None and not isinstance(v, str) and neg(v)) else base

def titulo(c, y, t, sub=None):
    txt(c, MX, y, t, "PB", 15, NAVY)
    if sub: txt(c, MX, y - 15, sub, "P", 8, GREY)
    return y - (32 if sub else 20)
def secao(c, y, t, x=MX, w=CW):
    txt(c, x, y, t, "PB", 9.5, NAVY); return y - 15
def caixa_nota(c, y, s, h=None, x=MX, w=CW, size=7.6, fill=GREY_BG):
    lines = simpleSplit(s, "P", size, w - 22)
    hh = h or (len(lines) * (size + 3.4) + 14)
    rect(c, x, y - hh, w, hh, fill=fill, stroke=BORDER, r=5, lw=0.5)
    yy = y - 14
    for ln in lines: txt(c, x + 11, yy, ln, "P", size, GREY); yy -= size + 3.4
    return y - hh - 8

def unidade(c, xr, y, s="R$ MM"):
    """Etiqueta discreta com a unidade do grafico (canto direito, alinhada em xr)."""
    wd = pdfmetrics.stringWidth(s, "PB", 5.8) + 10
    rect(c, xr - wd, y - 2.5, wd, 11, fill=GREY_BG, stroke=BORDER, r=5.5, lw=0.4)
    txt(c, xr - wd / 2, y + 0.6, s, "PB", 5.8, GREY, "c")


def kpi(c, x, y, w, h, rot, valor, sub, dark=False, accent=None, vsize=15, maxl=2):
    if dark:
        rect(c, x, y - h, w, h, fill=NAVY, r=6)
        txt(c, x + 11, y - 15, rot.upper(), "PB", 6.2, BRAND_OR)
        txt(c, x + 11, y - 15 - 21, valor, "PB", vsize, WHITE)
        for i, ln in enumerate(simpleSplit(sub, "P", 6.6, w - 28)[:maxl]): txt(c, x + 11, y - 15 - 34 - i * 8.6, ln, "P", 6.6, HexColor("#D6D9EA"))
    else:
        rect(c, x, y - h, w, h, fill=GREY_BG, r=4)
        rect(c, x, y - h, 3, h, fill=accent or NAVY)
        txt(c, x + 11, y - 14, rot.upper(), "PB", 6.2, accent if accent else NAVY)
        vcol = NEG_TXT if valor.startswith("−") else NAVY
        txt(c, x + 11, y - 14 - 21, valor, "PB", vsize, vcol)
        for i, ln in enumerate(simpleSplit(sub, "P", 6.6, w - 26)[:maxl]): txt(c, x + 11, y - 14 - 33 - i * 8.6, ln, "P", 6.6, GREY)
def variacoes(c, x, y, w, itens, lab_w=190, rh=14):
    area = w - lab_w - 60
    mn = max([-v for _, v in itens if v < 0] or [0]); mp = max([v for _, v in itens if v > 0] or [0])
    sc = area / ((mn + mp) or 1); zx = x + lab_w + mn * sc
    top = y + 8
    for lab, v in itens:
        txt(c, x, y, lab, "P", 7.2, GREY)
        bw = abs(v) * sc
        if v < 0: rect(c, zx - bw, y - 2, bw, 8, fill=NEG_FILL)
        else: rect(c, zx, y - 2, bw, 8, fill=BLUES[3])
        txt(c, x + w, y, ("+" if v > 0 else "") + mmn(v, 2), "PB", 7.2, NEG_TXT if v < 0 else NAVY, "r")
        y -= rh
    c.setStrokeColor(HexColor("#9AA0B8")); c.setLineWidth(0.6); c.line(zx, top, zx, y + rh - 4)
    return y
def eixo_y(vals, pad=0.16):
    lo = min(0, min(vals)); hi = max(0, max(vals))
    span = (hi - lo) or 1
    return lo - (span * pad if lo < 0 else 0), hi + span * pad
def barras(c, x, y, w, h, labels, vals, fmt=lambda v: mmn(v), hl=None, cor_pos=None, rot=0, size=6.2, lbl_every=1, destaque=None):
    """barras verticais; positivo em azul (degradê), negativo laranja; y = base inferior da área."""
    lo, hi = eixo_y(vals)
    sc = h / (hi - lo); y0 = y + (-lo) * sc
    n = len(vals); slot = w / n; bw = slot * 0.56
    hline(c, x, x + w, y0, HexColor("#9AA0B8"), 0.7)
    mx = max(abs(v) for v in vals) or 1
    for i, v in enumerate(vals):
        bx = x + i * slot + (slot - bw) / 2; bh = abs(v) * sc
        if v >= 0:
            k = 2 + int(round((abs(v) / mx) * 3)); fill = cor_pos or BLUES[min(k, 5)]
            rect(c, bx, y0, bw, bh, fill=fill)
        else:
            rect(c, bx, y0 - bh, bw, bh, fill=NEG_FILL)
        if destaque is not None and i in destaque:
            pass
        if i % lbl_every == 0:
            s = fmt(v); ty = y0 + bh + 3.5 if v >= 0 else y0 - bh - 8.5
            txt(c, bx + bw / 2, ty, s, "PB", size, NEG_TXT if v < 0 else NAVY, "c")
        txt(c, bx + bw / 2, y - 11 - (0 if lo == 0 else 0), labels[i], "P", 6, GREY, "c") if lo >= 0 else txt(c, bx + bw / 2, y - 11, labels[i], "P", 6, GREY, "c")
    return y0
def legenda(c, x, y, itens):
    for cor, nome, tipo in itens:
        if tipo == "bar": rect(c, x, y - 1, 8, 8, fill=cor)
        else:
            c.setStrokeColor(cor); c.setLineWidth(2); c.line(x - 1, y + 3, x + 11, y + 3); c.setFillColor(cor); c.circle(x + 5, y + 3, 2.3, fill=1, stroke=0)
        txt(c, x + 15, y, nome, "P", 6.8, GREY); x += 20 + pdfmetrics.stringWidth(nome, "P", 6.8) + 8
def cascata(c, x, y, w, h, etapas, size=6.4):
    """etapas: (rotulo, valor, tipo) tipo: 'total'|'delta'|'final'. y = base inferior da área"""
    acc = 0; spans = []
    for lab, v, t in etapas:
        if t == "delta": a, b = acc, acc + v; acc = b
        else: a, b = 0, v; acc = v
        spans.append((min(a, b), max(a, b)))
    lo = min(0, min(s[0] for s in spans)); hi = max(0, max(s[1] for s in spans))
    span = hi - lo; lo -= span * 0.10 if lo < 0 else 0; hi += span * 0.14
    sc = h / (hi - lo); y0 = y + (-lo) * sc
    n_ = len(etapas); slot = w / n_; bw = slot * 0.58
    hline(c, x, x + w, y0, HexColor("#9AA0B8"), 0.7)
    prev_end = None
    for i, ((lab, v, t), (a, b)) in enumerate(zip(etapas, spans)):
        bx = x + i * slot + (slot - bw) / 2
        if t == "total": fill = NAVY
        elif t == "final": fill = ORANGE if v < 0 else BLUES[3]
        else: fill = ROSE if v < 0 else BLUES[2]
        bh = max((b - a) * sc, 1.2)
        rect(c, bx, y0 + a * sc, bw, bh, fill=fill)
        s = mm(v, 2, sign=(t == "delta" and v > 0))
        top = y0 + b * sc
        txt(c, bx + bw / 2, (top + 4) if (v >= 0 or t == "delta") else (y0 + a * sc - 9), s, "PB", size, NEG_TXT if v < 0 else NAVY, "c") if not (t != "delta" and v < 0) else txt(c, bx + bw / 2, y0 + a * sc - 9, s, "PB", size, NEG_TXT, "c")
        if t == "delta" and v < 0: pass
        for k, ln in enumerate(simpleSplit(lab, "P", 6.2, slot - 4)[:2]): txt(c, bx + bw / 2, y - 12 - k * 8, ln, "P", 6.2, GREY, "c")
        if i + 1 < n_:
            endv = (b if v >= 0 or t != "delta" else a) if t == "delta" else (v)
            lvl = acc_levels[i]
            c.setStrokeColor(HexColor("#9AA0B8")); c.setLineWidth(0.4); c.setDash(1.5, 1.5)
            c.line(bx + bw, y0 + lvl * sc, bx + slot, y0 + lvl * sc); c.setDash()
    return y0
acc_levels = []
def calc_levels(etapas):
    acc = 0; out = []
    for lab, v, t in etapas:
        acc = acc + v if t == "delta" else v; out.append(acc)
    acc_levels[:] = out
def tabela(c, x, y, cols, header, rows, rh=12.4, fs=7.2, head_h=24):
    """cols: [(largura, 'l'|'r')]; rows: (tipo, [cel...]) tipo: norm|sec|sub|tot|ind ; cel str ou (str, cor)"""
    tw = sum(w for w, _ in cols)
    rect(c, x, y - head_h, tw, head_h, fill=NAVY)
    cx = x
    for (w, al), h in zip(cols, header):
        for k, ln in enumerate(simpleSplit(h, "PB", 6.6, w - 8)[:2]):
            yy = y - head_h / 2 - 2 + (4 if len(simpleSplit(h, "PB", 6.6, w - 8)) > 1 else 0) - k * 8
            if al == "l": txt(c, cx + 5, yy, ln, "PB", 6.6, WHITE)
            else: txt(c, cx + w - 5, yy, ln, "PB", 6.6, WHITE, "r")
        cx += w
    y -= head_h
    for tipo, cells in rows:
        h_ = rh + (4 if tipo == "sec" else 0)
        wraps = None
        if tipo == "ind":
            wraps = []
            for j, ((w, al), cel) in enumerate(zip(cols, cells)):
                s_ = cel[0] if isinstance(cel, tuple) else cel
                wraps.append(simpleSplit(s_, "P", fs, w - 12) if al == "l" and s_ else [s_])
            h_ = max(rh, max(len(x) for x in wraps) * (fs + 1.6) + 6)
        if tipo in ("sub", "tot"):
            rect(c, x, y - h_, tw, h_, fill=NAVY if tipo == "tot" else HexColor("#E8EAF3"))
        elif tipo == "sec":
            pass
        cx = x
        for j, ((w, al), cel) in enumerate(zip(cols, cells)):
            s, cc = (cel if isinstance(cel, tuple) else (cel, None))
            font = "PB" if tipo in ("sec", "sub", "tot") else "P"
            if tipo == "tot": color = WHITE if cc is None else cc
            elif cc is not None: color = cc
            else: color = NAVY if tipo in ("sec", "sub") else (GREY if j == 0 else NAVY)
            if tipo == "ind" and j == 0: pass
            xx = cx + (5 + (8 if tipo == "ind" and j == 0 else 0)) if al == "l" else cx + w - 5
            yy = y - h_ + (3.4 if tipo != "sec" else 2.4)
            c.setFont(font, fs if tipo != "tot" else fs + 0.2); c.setFillColor(color)
            if wraps is not None and al == "l" and len(wraps[j]) > 1:
                top_ = y - 3 - fs
                for k_, ln_ in enumerate(wraps[j]): c.drawString(xx, top_ - k_ * (fs + 1.6) , ln_)
            else:
                if wraps is not None: yy = y - h_ / 2 - fs * 0.35
                if al == "l": c.drawString(xx, yy, s)
                else: c.drawRightString(xx, yy, s)
            cx += w
        if tipo not in ("sub", "tot", "sec"): hline(c, x, x + tw, y - h_, HexColor("#EEF0F6"), 0.4)
        y -= h_
    return y

def num_cell(v, d=2, tot=False):
    s = fnum(v, d)
    if tot: return (s, HexColor("#FFD9A8") if neg(v, d) else WHITE)
    return (s, NEG_TXT) if neg(v, d) else (s, None)
def barra_h(c, x, y, w, h, partes, escala_total):
    """partes: [(valor, cor)] ; largura proporcional a escala_total"""
    xx = x
    for v, cor in partes:
        ww = v / escala_total * w
        rect(c, xx, y, ww - 1.6, h, fill=cor); xx += ww
    return xx
def lista_barras(c, x, y, w, titulo_, itens, total, cor=BLUES[3], rot_w=150, maxn=None, destaque_ultimo=False):
    txt(c, x, y, titulo_, "PB", 9, NAVY)
    txt(c, x + w - 38, y, "R$", "PB", 6, GREY, "r"); txt(c, x + w, y, "% do grupo", "PB", 6, GREY, "r"); y -= 6
    hline(c, x, x + w, y, BORDER, 0.5); y -= 13
    mx = max(v for _, v in itens)
    bw_max = w - rot_w - 92
    for i, (lab, v) in enumerate(itens):
        l = lab if pdfmetrics.stringWidth(lab, "P", 6.9) <= rot_w - 6 else lab[: int(len(lab) * (rot_w - 8) / pdfmetrics.stringWidth(lab, "P", 6.9))] + "…"
        txt(c, x, y, l, "P", 6.9, GREY)
        last = destaque_ultimo and i == len(itens) - 1
        rect(c, x + rot_w, y - 1.5, max(bw_max * v / mx, 0.8), 7.2, fill=LIGHT if last else cor)
        txt(c, x + w - 38, y, fnum(v, 2), "P", 6.9, NAVY, "r")
        txt(c, x + w, y, ("< 0,1%" if 0 < v / total < 0.0005 else pct(v / total)), "PB", 6.9, NAVY, "r")
        y -= 15.6
    hline(c, x, x + w, y + 8, BORDER, 0.5)
    txt(c, x, y - 3, "Total", "PB", 7.2, NAVY); txt(c, x + w - 38, y - 3, fnum(total, 2), "PB", 7.2, NAVY, "r"); txt(c, x + w, y - 3, "100,0%", "PB", 7.2, NAVY, "r")
    return y - 22

# ------------------------------------------------------------------ paginas
PAGES = []
def pagina(fn): PAGES.append(fn); return fn


def moldura(c, n, N, secao_nome, marca=True):
    if marca:
        wm = ImageReader(str(ASSETS / "torre_watermark.png"))
        c.drawImage(wm, W / 2 - 170, 28, width=340, height=343, mask="auto")
    rect(c, 0, H - 4, W * 0.62, 4, fill=NAVY); rect(c, W * 0.62, H - 4, W * 0.38, 4, fill=ORANGE)
    lg = _logo()
    if lg:
        iw, ih = lg.getSize(); lh = 30
        c.drawImage(lg, MX, H - 50, width=lh * iw / ih, height=lh, mask="auto")
    else:
        txt(c, MX, H - 40, E("curto"), "PB", 14, NAVY)
    txt(c, W - MX, H - 28, "DEMONSTRATIVOS FINANCEIROS · " + X["data_base"], "PB", 6.4, NAVY, "r")
    txt(c, W - MX, H - 39, secao_nome, "PB", 8, NAVY, "r")
    hline(c, MX, W - MX, H - 58, BORDER, 0.6)
    hline(c, MX, W - MX, 38, BORDER, 0.5)
    txt(c, MX, 26, STATUS["txt"], "PB", 6, ORANGE)
    txt(c, W / 2, 26, f"Página {n} de {N}", "P", 6.8, GREY, "c")
    txt(c, W - MX, 26, E("nome"), "P", 6, GREY, "r")
TOPY = H - 84


# ================================================================== 1. CAPA
@pagina
def p_capa(c, n, N):
    c.setFillColor(NAVY); p = c.beginPath()
    p.moveTo(W * 0.80, H); p.lineTo(W, H); p.lineTo(W, 0); p.lineTo(W * 0.60, 0); p.close(); c.drawPath(p, fill=1, stroke=0)
    mk = ImageReader(str(ASSETS / "capa_marca_pale.png"))
    c.saveState(); c.setFillAlpha(0.10); c.drawImage(mk, W * 0.66, 60, width=250, height=250 * 1409 / 983, mask="auto"); c.restoreState()
    rect(c, 0, H - 4, W * 0.80, 4, fill=NAVY)
    lg = _logo()
    if lg:
        iw, ih = lg.getSize(); lw_ = 215
        c.drawImage(lg, MX + 8, H - 330, width=lw_, height=lw_ * ih / iw, mask="auto")
    else:
        txt(c, MX + 8, H - 200, E("curto"), "PB", 30, NAVY)
    rect(c, MX + 8, 405, 52, 3, fill=ORANGE)
    txt(c, MX + 8, 372, "Demonstrativos", "PB", 27, NAVY); txt(c, MX + 8, 342, "Financeiros", "PB", 27, NAVY)
    txt(c, MX + 8, 312, E("nome"), "P", 9.5, GREY)
    txt(c, MX + 8, 297, "CNPJ " + E("cnpj"), "P", 9.5, GREY)
    txt(c, MX + 8, 282, "Posição em " + X["data_base"], "P", 9.5, GREY)
    rect(c, MX + 8, 238, 232, 24, fill=ORANGE, r=12)
    txt(c, MX + 8 + 116, 246.5, "PERÍODO · " + X["periodo_curto"], "PB", 7.6, WHITE, "c")
    if E("logo_grupo_capa"):                       # Anastacio: sem logo do grupo na capa; outra empresa pode ligar com a config logo_grupo_capa
        g = ImageReader(str(ASSETS / "GRUPO.png")); gw, gh = g.getSize()
        c.drawImage(g, MX + 8, 84, width=84, height=84 * gh / gw, mask="auto")
    txt(c, MX + 8, 70, "Informações elaboradas pelo Grupo Enermais a partir dos Balancetes Societários.", "P", 6.4, GREY)
    txt(c, MX + 8, 26, STATUS["txt"], "PB", 6, ORANGE)


# ================================================================== 2. DESTAQUES
@pagina
def p_destaques(c, n, N):
    moldura(c, n, N, "Destaques do Período")
    ate = f"Jan–{X['mes_abrev']}" if X["mes"] > 1 else "Jan"
    y = titulo(c, TOPY, "Destaques em " + X["data_base"], E("nome") + " — " + X["periodo"].lower())
    ativo, caixa, caixa0 = BP("ativo"), BP("caixa_eq"), BP("caixa_eq", 0)
    divb, divl = IN("div_bruta"), IN("div_liquida")
    cw2 = (CW - 12) / 2
    sub_res = "Custos de construção sem a receita correspondente (ver nota na página 4)" if E("nota_resultado") else "Resultado líquido acumulado do ano"
    kpi(c, MX, y, cw2, 66, f"Resultado líquido {ate.lower()}", mm(DR("res_liq")), sub_res, dark=True, vsize=19)
    kpi(c, MX + cw2 + 12, y, cw2, 66, "Caixa e equivalentes", mm(caixa),
        f"Variação de {mm(caixa - caixa0, 2, True)} desde {X['abertura']}" + (f" ({pct(razao(caixa - caixa0, abs(caixa0)))})" if abs(caixa0) >= 0.005 else ""), vsize=19)
    y -= 78
    cw3 = (CW - 24) / 3
    conc = BP("conc_liq")
    cards = [("Ativo total", mm(ativo), f"Ativo de concessão líquido: {mm(conc)}" if abs(conc) >= 0.005 else ""),
             ("Dívida bruta (BNDES)", mm(divb), f"Dívida líquida: {mm(divl)}"),
             ("Patrimônio líquido", mm(BP("pl")), f"Em {X['abertura']}: {mm(BP('pl', 0))}"),
             ("Capital aportado", mm(IN("capital_aportado")), "Capital social + AFAC"),
             ("Resultado financeiro", mm(DR("res_fin"), 2, True), f"Receitas menos despesas financeiras, {ate.lower()}"),
             ("Fornecedores a pagar", mm(BP("fornec")), f"Em {X['abertura']}: {mm(BP('fornec', 0))}")]
    for i, (a, b_, d_) in enumerate(cards):
        kpi(c, MX + (i % 3) * (cw3 + 12), y - (i // 3) * 62, cw3, 52, a, b_, d_, accent=NEG_FILL if b_.startswith("−") else NAVY, vsize=13)
    y -= 2 * 62 + 10
    y = secao(c, y, "Leitura Executiva")
    y = paras(c, "dest", y, size=8.4, lead=12.6, gap=6)
    nota = ("Como ler: valores em reais (R$); MM = milhões. Valores negativos aparecem com sinal “−” e em laranja. Informações extraídas dos Balancetes Societários, sem auditoria."
            + (" " + E("nota_resultado") if E("nota_resultado") else ""))
    y = caixa_nota(c, y - 4, nota, size=7.4)
    y = secao(c, y - 6, "Neste relatório")
    itens = [("3", "Evolução mensal", "Caixa, dívida, custo de construção e patrimônio líquido, mês a mês"),
             ("4–5", "Resultado", "Formação do resultado e DRE (até o mês anterior, mês e acumulado)"),
             ("6–7", "Balanço Patrimonial", "Posição patrimonial e balanço completo, com variações"),
             ("8", "Indicadores", "Liquidez, endividamento e estrutura de capital, em linguagem simples"),
             ("9–10", "Composição de saldos", "Caixa, dívida, fornecedores, adiantamentos e acionistas")]
    for pg, a, b_ in itens:
        rect(c, MX, y - 3, 30, 12, fill=NAVY, r=3); txt(c, MX + 15, y, pg, "PB", 6.6, WHITE, "c")
        txt(c, MX + 38, y, a, "PB", 7.8, NAVY); txt(c, MX + 148, y, b_, "P", 7.4, GREY); y -= 17
    y = secao(c, y - 8, f"Principais variações desde {X['abertura']}")
    unidade(c, MX + CW, y + 14)
    itens = [(f"Resultado do período ({ate.lower()})", DR("res_liq")), ("Caixa e equivalentes", caixa - caixa0),
             ("Dívida bruta (BNDES)", divb - IN("div_bruta", 0)), ("Fornecedores", BP("fornec", 3)),
             ("Adiantamento p/ futuro aumento de capital", BP("afac", 3))]
    variacoes(c, MX, y, CW, itens)


def _passo(v):
    """Passo 'bonito' (1-2-5) para as linhas de grade do grafico."""
    if v <= 0:
        return 1e6
    import math
    e = 10 ** math.floor(math.log10(v)); f = v / e
    return (1 if f < 1.5 else 2 if f < 3.5 else 5 if f < 7.5 else 10) * e


# ================================================================== 3. EVOLUÇÃO MENSAL
@pagina
def p_evolucao(c, n, N):
    S = X["serie"]; MESES = S["rotulos"]; SC, SD, SPL, SF, SCC = S["caixa"], S["bndes"], S["pl"], S["fornec"], S["custo_constr"]
    moldura(c, n, N, "Evolução Mensal")
    y = titulo(c, TOPY, f"Evolução de {MESES[0].lower()} a {MESES[-1].lower()}", "Saldos no fim de cada mês · valores em R$ milhões · posições mensais dos Balancetes Societários")
    y = secao(c, y, "Caixa e equivalentes × dívida bruta (BNDES)")
    legenda(c, MX + 262, y + 14, [(BLUES[3], "Caixa e equivalentes", "bar"), (NAVY, "Dívida bruta", "line")])
    unidade(c, MX + CW, y + 14)
    gh = 135; gy = y - gh - 14; gx = MX + 4; gw = CW - 8
    lo, hi = eixo_y(SC + SD)
    sc = gh / (hi - lo); n_ = len(MESES); slot = gw / n_; bw = slot * 0.5
    passo = _passo(hi / 4)
    for g in range(1, int(hi // passo) + 1):
        hline(c, gx, gx + gw, gy + g * passo * sc, HexColor("#E6E9F1"), 0.4)
    hline(c, gx, gx + gw, gy, HexColor("#9AA0B8"), 0.7)
    pts = []
    for i in range(n_):
        bx = gx + i * slot + (slot - bw) / 2; bh = max(SC[i], 0) * sc
        rect(c, bx, gy, bw, bh, fill=BLUES[3])
        txt(c, bx + bw / 2, gy + bh + 3, mmn(SC[i]), "PB", 6 if n_ <= 10 else 5.2, NAVY, "c")
        txt(c, bx + bw / 2, gy - 11, MESES[i], "P", 6 if n_ <= 10 else 5.2, GREY, "c")
        pts.append((bx + bw / 2, gy + SD[i] * sc))
    c.setStrokeColor(NAVY); c.setLineWidth(2)
    for a, b_ in zip(pts, pts[1:]): c.line(a[0], a[1], b_[0], b_[1])
    for px, py in pts:
        c.setFillColor(WHITE); c.circle(px, py, 3, fill=1, stroke=0); c.setFillColor(NAVY); c.circle(px, py, 2.2, fill=1, stroke=0)
    for i in range(0, n_, 1 if n_ <= 9 else 2): txt(c, pts[i][0], pts[i][1] + 6, mmn(SD[i]), "PB", 6.4, NAVY, "c")
    y = gy - 34
    half = (CW - 20) / 2
    txt(c, MX, y, "Custo de construção do mês", "PB", 9, NAVY)
    unidade(c, MX + half, y)
    gy2 = y - 12 - 112
    barras(c, MX + 2, gy2, half - 4, 108, [m[:3] for m in S["meses"]], list(SCC), fmt=lambda v: mmn(v), size=6.2 if len(SCC) <= 9 else 5.2)
    x2 = MX + half + 20
    txt(c, x2, y, "Patrimônio líquido no fim do mês", "PB", 9, NAVY)
    unidade(c, MX + CW, y)
    barras(c, x2 + 2, gy2, half - 4, 108, [m[:3] for m in MESES], SPL, fmt=lambda v: mmn(v, 1), size=5.6 if n_ <= 10 else 4.8)
    y = gy2 - 30
    wcol = (CW - 104) / n_
    cols = [(104, "l")] + [(wcol, "r")] * n_
    f2 = lambda v: (fnum(v / 1e6, 2), NEG_TXT) if neg(v / 1e6, 2) else (fnum(v / 1e6, 2), None)
    rws = [("norm", [("Caixa e equivalentes", None)] + [f2(v) for v in SC]),
           ("norm", [("Dívida bruta (BNDES)", None)] + [f2(v) for v in SD]),
           ("norm", [("Fornecedores", None)] + [f2(v) for v in SF]),
           ("norm", [("Patrimônio líquido", None)] + [f2(v) for v in SPL]),
           ("norm", [("Custo de construção do mês", None), ("–", None)] + [f2(v) for v in SCC])]
    y = tabela(c, MX, y, cols, ["R$ MM"] + MESES, rws, rh=12.6, fs=6.7 if n_ <= 10 else 5.8, head_h=16)
    y -= 16
    y = secao(c, y, "Leitura do Período")
    paras(c, "evo", y)


# ================================================================== 4. RESULTADO
@pagina
def p_resultado(c, n, N):
    S = X["serie"]
    moldura(c, n, N, "Formação do Resultado")
    y = titulo(c, TOPY, f"Formação do resultado de janeiro a {X['mes_nome']}/{X['ano']}" if X["mes"] > 1 else f"Formação do resultado de janeiro/{X['ano']}",
               "Da receita líquida ao resultado líquido do período — valores em R$ milhões")
    RES, RESF, CUSTO, OPEX = DR("res_liq"), DR("res_fin"), DR("custo_constr"), DR("desp_adm")
    et = [("Receita líquida (após deduções)", DR("rec_liq"), "total"), ("Custo de construção", CUSTO, "delta"),
          ("Fretes sobre compras", DR("fretes"), "delta"), ("Despesas operacionais", OPEX, "delta"),
          ("Resultado financeiro", RESF, "delta")]
    if abs(DR("ir_cs")) >= 0.005:
        et.append(("IRPJ e CSLL", DR("ir_cs"), "delta"))
    et.append(("Resultado líquido do período", RES, "final"))
    calc_levels(et)
    unidade(c, MX + CW, y + 6)
    gy = y - 175
    cascata(c, MX + 4, gy, CW - 8, 150, et)
    y = gy - 34
    cs = [("Custo de construção", mm(-CUSTO), f"Equivale a {pct(razao(CUSTO, RES))} do resultado líquido" if abs(RES) >= 0.005 else "Custo do período"),
          ("Média mensal do custo", mm(-CUSTO / max(X["n_meses"], 1)), f"Acumulado ÷ {X['n_meses']} meses"),
          ("Despesas operacionais", mm(-OPEX), "Serviços, cartório, seguro e outras"),
          ("Resultado financeiro", mm(RESF, 2, True), "Aplicações e descontos obtidos")]
    gap4 = 8
    cw4 = (CW - 3 * gap4) / 4
    for i, (a, b_, d_) in enumerate(cs): kpi(c, MX + i * (cw4 + gap4), y, cw4, 66, a, b_, d_, accent=NEG_FILL if b_.startswith("−") else NAVY, vsize=10.5, maxl=3)
    y -= 88
    txt(c, MX, y, "Resultado líquido do mês", "PB", 9, NAVY)
    unidade(c, MX + CW, y)
    gy2 = y - 12 - 92
    barras(c, MX + 2, gy2, CW - 4, 88, S["meses"], S["resultado_mes"], fmt=lambda v: mmn(v), size=6.4)
    y = gy2 - 26
    y = secao(c, y, "Leitura do Resultado")
    y = paras(c, "res", y)
    if E("nota_resultado"):
        caixa_nota(c, y - 2, "Nota sobre o resultado intermediário: " + E("nota_resultado"), size=7.4)


# ================================================================== 5. DRE
_DRE_SUB = {"deducoes", "rec_liq", "custos_serv", "res_bruto", "desp_adm", "ebit", "rec_fin", "desp_fin", "res_fin", "res_antes_ir"}
@pagina
def p_dre(c, n, N):
    moldura(c, n, N, "Demonstração do Resultado")
    mes, ano = X["mes"], X["ano"]
    y = titulo(c, TOPY, "Demonstração do Resultado do Exercício", f"Em R$ — período de 01/01/{ano} a {X['data_base']} · contas de resultado encerradas mensalmente")
    cols = [(235, "l"), (92, "r"), (92, "r"), (96, "r")]
    ab = RD.MESES_ABREV
    hdr = ["", (f"Jan–{ab[mes - 2]}/{ano}" if mes > 1 else "—"), f"{ab[mes - 1]}/{ano}", f"Acumulado Jan–{ab[mes - 1]}/{ano}" if mes > 1 else f"Acumulado Jan/{ano}"]
    rows = []
    for rotulo, lid, tipo in tabelas.DRE_LINHAS_EXIBIR:
        if tipo == "secao":
            rows.append(("sec", [(rotulo, None), "", "", ""])); continue
        t = "tot" if lid == "res_liq" else ("sub" if lid in _DRE_SUB else "norm")
        lab = X["rot"].get(lid, lid)
        if t == "norm": lab = "   " + lab
        v = X["dre"][lid]
        rows.append((t, [(lab, None), num_cell(v[0], 2, t == "tot") if mes > 1 else ("–", None), num_cell(v[1], 2, t == "tot"), num_cell(v[2], 2, t == "tot")]))
    y = tabela(c, MX, y, cols, hdr, rows, rh=13.6, fs=7.2)
    y -= 12
    notas = [f"(1) Resultado acumulado = resultado dos meses anteriores + resultado de {X['mes_nome']}; as contas de resultado de cada mês são encerradas no próprio mês."]
    if E("nota_resultado"):
        notas.append("(2) " + E("nota_resultado"))
    if abs(X["ajustes"]) >= 0.005:
        notas.append(f"({len(notas) + 1}) “Outros ajustes líquidos” (R$ {fnum(X['ajustes'])} no acumulado): estornos de centavos apurados no encerramento do mês.")
    caixa_nota(c, y, "Notas: " + " ".join(notas), size=7)


# ================================================================== 6. POSIÇÃO PATRIMONIAL
@pagina
def p_posicao(c, n, N):
    moldura(c, n, N, "Posição Patrimonial")
    ATIVO, PL, PL0, RES, CONC = BP("ativo"), BP("pl"), BP("pl", 0), DR("res_liq"), BP("conc_liq")
    y = titulo(c, TOPY, "Posição patrimonial em " + X["data_base"], f"Total do ativo: {brl(ATIVO)} · Total do passivo + patrimônio líquido: {brl(BP('passivo_pl'))}")
    AC, ANC, PC, PNC = BP("ac"), BP("anc"), BP("pc"), BP("pnc")
    exig = PC + PNC; escala = max(ATIVO, exig, 1)
    bw_ = CW - 90
    txt(c, MX, y, "ATIVO", "PB", 7.4, NAVY)
    barra_h(c, MX, y - 24, bw_ * ATIVO / escala, 16, [(max(AC, 0), BLUES[1]), (max(ANC, 0), BLUES[4])], max(ATIVO, 1))
    txt(c, MX + bw_ * ATIVO / escala + 6, y - 19, mm(ATIVO, 1), "PB", 7, NAVY)
    legenda(c, MX, y - 38, [(BLUES[1], f"Circulante — {pct(razao(AC, ATIVO))} ({mm(AC)})", "bar"),
                            (BLUES[4], f"Não circulante — {pct(razao(ANC, ATIVO))} ({mm(ANC)})" + (f", dos quais ativo de concessão {mm(CONC)}" if abs(CONC) >= 0.005 else ""), "bar")])
    y -= 56
    txt(c, MX, y, "PASSIVO EXIGÍVEL (obrigações)", "PB", 7.4, NAVY)
    barra_h(c, MX, y - 24, bw_ * exig / escala, 16, [(max(PC, 0), ORANGE), (max(PNC, 0), BLUES[3])], max(exig, 1))
    xa = MX + bw_ * ATIVO / escala
    c.setStrokeColor(NAVY); c.setLineWidth(1); c.setDash(2, 2); c.line(xa, y - 28, xa, y - 4); c.setDash()
    txt(c, MX + bw_ * exig / escala + 6, y - 19, mm(exig, 1), "PB", 7, NAVY)
    legenda(c, MX, y - 38, [(ORANGE, f"Circulante — {mm(PC)}", "bar"), (BLUES[3], f"Não circulante — {mm(PNC)}", "bar")])
    txt(c, W - MX, y - 38, "Linha tracejada = tamanho do ativo total", "PI", 6.4, GREY, "r")
    txt(c, MX, y - 48, f"Patrimônio líquido: {mm(PL)} ({pct(razao(PL, ATIVO))} do ativo) — passivo exigível equivale a {pct(razao(exig, ATIVO))} do ativo", "PB", 6.9, NEG_TXT if PL < 0 else NAVY)
    y -= 70
    y = secao(c, y, f"Do patrimônio líquido de {X['abertura']} ao de {X['data_base']}")
    unidade(c, MX + CW, y + 14)
    d_cap = round(BP("capital", 3) + BP("afac", 3), 2)
    outras = round(PL - PL0 - d_cap - RES, 2)
    et = [(f"PL em {X['abertura']}", PL0, "total"), ("Capital social e AFAC", d_cap, "delta"), (f"Resultado até {X['mes_abrev'].lower()}", RES, "delta")]
    if abs(outras) >= 0.5:
        et.append(("Outras variações", outras, "delta"))
    et.append((f"PL em {X['data_base']}", PL, "final"))
    calc_levels(et)
    gy = y - 135 - 16
    cascata(c, MX + 30, gy, CW - 60, 125, et, size=6.6)
    y = gy - 32
    cw3 = (CW - 16) / 3
    for i, (a, b_, d_) in enumerate([("Liquidez corrente", fnum(IN("liq_corrente")) + "x", "Ativo circulante ÷ passivo circulante"),
                                     ("Endividamento geral", pct(IN("endiv_geral")), "Obrigações ÷ ativo total"),
                                     ("PL / ativo total", pct(IN("pl_ativo")), "Participação de capital próprio")]):
        kpi(c, MX + i * (cw3 + 8), y, cw3, 54, a, b_, d_, accent=NEG_FILL if b_.startswith("−") else NAVY, vsize=13)
    y -= 76
    y = secao(c, y, "Leitura do Balanço")
    paras(c, "bal", y, size=8, lead=11.8, gap=3)


# ================================================================== 7. BALANÇO
_BP_SUB = {"caixa_eq", "ac", "rlp", "conc_liq", "anc", "pc", "pnc", "pl"}
@pagina
def p_balanco(c, n, N):
    moldura(c, n, N, "Balanço Patrimonial")
    yy = str(X["ano"])[2:]; yy0 = str(X["ano"] - 1)[2:]; ab = X["mes_abrev"].lower()
    y = titulo(c, TOPY, "Balanço Patrimonial", f"Em R$ — posição em {X['abertura']}, {X['data_ant']} e {X['data_base']} · variação entre dezembro/{yy0} e {ab}/{yy}")
    cols = [(188, "l"), (66, "r"), (66, "r"), (66, "r"), (66, "r"), (63, "r")]

    def bloco(linhas):
        out = []
        for rotulo, lid, tipo in linhas:
            if tipo == "secao":
                out.append(("sec", [(rotulo.upper(), None), "", "", "", "", ""])); continue
            t = "tot" if lid in ("ativo", "passivo_pl") else ("sub" if lid in _BP_SUB else "norm")
            lab = X["rot"].get(lid, lid)
            v = X["bp"][lid]
            out.append((t, [(("   " + lab) if t == "norm" else lab, None)] + [num_cell(v[i], 2, t == "tot") for i in range(4)] + [(varp(v[4]), None if t != "tot" else WHITE)]))
        return out
    hdr = ["ATIVO", X["abertura"], X["data_ant"], X["data_base"], f"Var. R$ dez/{yy0} a {ab}/{yy}", "Var. %"]
    y = tabela(c, MX, y, cols, hdr, bloco(tabelas.BP_ATIVO_LINHAS), rh=11.3, fs=6.8, head_h=22)
    y -= 8
    hdr2 = ["PASSIVO E PATRIMÔNIO LÍQUIDO"] + hdr[1:]
    y = tabela(c, MX, y, cols, hdr2, bloco(tabelas.BP_PASSIVO_LINHAS), rh=11.3, fs=6.8, head_h=22)
    y -= 8
    txt(c, MX, y, f"n.s. = variação não significativa (acima de 999%). Saldos extraídos dos Balancetes Societários; a posição de {X['data_base']} é o saldo final do balancete do mês.", "P", 6.4, GREY)


# ================================================================== 8. INDICADORES
@pagina
def p_indicadores(c, n, N):
    moldura(c, n, N, "Indicadores")
    y = titulo(c, TOPY, "Indicadores econômico-financeiros", "Calculados a partir do Balanço Patrimonial e da DRE · com explicação em linguagem simples")
    cw4 = (CW - 24) / 4
    ab0 = f"Dez/{str(X['ano'] - 1)[2:]}"
    for i, (a, b_, d_) in enumerate([("Liquidez corrente", fnum(IN("liq_corrente")) + "x", f"{ab0}: {fnum(IN('liq_corrente', 0))}x"),
                                     ("Dívida líquida", mm(IN("div_liquida")), f"{ab0}: {mm(IN('div_liquida', 0))}"),
                                     ("Capital circulante líquido", mm(IN("ccl")), f"{ab0}: {mm(IN('ccl', 0))}"),
                                     ("PL / ativo total", pct(IN("pl_ativo")), f"{ab0}: {pct(IN('pl_ativo', 0))}")]):
        kpi(c, MX + i * (cw4 + 8), y, cw4, 52, a, b_, d_, accent=NEG_FILL if b_.startswith("−") else NAVY, vsize=11.5)
    y -= 64
    cols = [(138, "l"), (50, "r"), (50, "r"), (50, "r"), (227, "l")]
    hdr = ["Indicador", X["abertura"], X["data_ant"], X["data_base"], "O que mede (em linguagem simples)"]
    rows = []
    for rotulo, chave, kind, formula in tabelas.INDICADORES_LINHAS:
        if chave is None:
            rows.append(("sec", [(rotulo, None), "", "", "", ""])); continue
        k = KINDS_PDF[kind]
        def fm(v, k=k):
            if v is None or isinstance(v, str): return ("–", None)
            if k == "x": return (fnum(v) + "x", None)
            if k == "p": return (pct(v), NEG_TXT) if v < 0 else (pct(v), None)
            return (fnum(v / 1e6, 2) + " MM", NEG_TXT) if v < 0 else (fnum(v / 1e6, 2) + " MM", None)
        rows.append(("ind", [(rotulo, None)] + [fm(v) for v in X["ind"][chave]] + [(RD.EXPLICACAO.get(chave, formula), GREY)]))
    y = tabela(c, MX, y, cols, hdr, rows, rh=14.5, fs=6.5, head_h=20)
    y -= 10
    caixa_nota(c, y, "Prazo médio de recebimento/pagamento (PMR, PMP) e cobertura do serviço da dívida (ICSD) não foram calculados enquanto não houver receita de construção/"
               "remuneração reconhecida. Valores em R$ milhões (MM) onde indicado.", size=7)
KINDS_PDF = {"x": "x", "%": "p", "R$": "R"}


# ================================================================== 9-10. COMPOSIÇÃO
def _bloco_comp(c, y, g, cor, destaque_ultimo=True):
    if not g["itens"]:
        txt(c, MX, y, g["titulo"], "PB", 9, NAVY)
        txt(c, MX, y - 16, "Sem saldo nesta data.", "PI", 7.4, GREY)
        return y - 40
    return lista_barras(c, MX, y, CW, g["titulo"], g["itens"], g["total"] if abs(g["total"]) >= 0.005 else 1, rot_w=190, cor=cor, destaque_ultimo=destaque_ultimo and g["demais"])


@pagina
def p_comp1(c, n, N):
    moldura(c, n, N, "Composição de Saldos (1/2)")
    y = titulo(c, TOPY, "Composição dos principais saldos — 1/2", "Em R$ — posição em " + X["data_base"] + " · valores e % do total de cada grupo")
    g = {k["chave"]: k for k in X["comp"]}
    for ch, cor in (("caixa", BLUES[3]), ("divida", BLUES[4]), ("adiant", BLUES[2])):
        if ch in g: y = _bloco_comp(c, y - (6 if ch != "caixa" else 0), g[ch], cor)
    paras(c, "comp_1", y - 4, size=8.2, lead=12.4, gap=3)


@pagina
def p_comp2(c, n, N):
    moldura(c, n, N, "Composição de Saldos (2/2)")
    y = titulo(c, TOPY, "Composição dos principais saldos — 2/2", "Em R$ — posição em " + X["data_base"] + " · valores e % do total de cada grupo")
    g = {k["chave"]: k for k in X["comp"]}
    if "fornec" in g: y = _bloco_comp(c, y, g["fornec"], BLUES[3])
    if "capital" in g: y = _bloco_comp(c, y - 6, g["capital"], BLUES[2], destaque_ultimo=True)
    paras(c, "comp_2", y - 4, size=8.2, lead=12.4, gap=3)


# ================================================================== 11. FECHAMENTO
@pagina
def p_fechamento(c, n, N):
    moldura(c, n, N, "Fechamento")
    y = titulo(c, TOPY, "Nota sobre este relatório")
    db = X["data_base"]
    t1 = (f"Os valores deste relatório foram extraídos dos Balancetes Societários de 01/01/{X['ano']} a {db} da {E('nome')}, não auditados, e organizados em Balanço Patrimonial, "
          f"Demonstração do Resultado, indicadores e composição de saldos. Os saldos patrimoniais correspondem à posição de {db}; o resultado é acumulado de janeiro a {X['mes_nome']}.")
    t3 = ("Indicadores (liquidez, endividamento, estrutura de capital) são medidas de apoio à gestão, calculadas a partir das demonstrações acima, e não substituem o parecer contábil. "
          "Os textos de leitura são gerados por modelo padronizado, preenchido com os valores das demonstrações, e podem ser ajustados pela contadora responsável antes da emissão.")
    for t_ in [t1] + ([E("nota_resultado")] if E("nota_resultado") else []) + [t3]:
        y = para(c, t_, MX, y, CW, size=8.4, lead=12.8, gap=7)
    y -= 70
    ass = [a for a in E("assinantes") if a[0] or a[1]][:6]
    cw2 = (CW - 30) / 2
    for i, (nome, cargo) in enumerate(ass):
        r, col = divmod(i, 2)
        x = MX + col * (cw2 + 30); yi = y - r * 48
        hline(c, x, x + cw2, yi, NAVY, 0.9)
        txt(c, x, yi - 12, nome or cargo, "PB", 8.4, NAVY)
        if nome: txt(c, x, yi - 23, cargo, "P", 7.4, GREY)
    y -= (max(1, (len(ass) + 1) // 2) - 1) * 48
    txt(c, MX, y - 44, ("Documento emitido para assinatura digital dos responsáveis." if STATUS.get("final") else
                        "Assinatura digital dos responsáveis: a definir (fora do escopo desta versão)."), "PI", 6.8, GREY)
    yy = y - 100
    rect(c, MX, yy - 70, CW, 70, fill=WHITE, stroke=BORDER, r=6)
    lg = _logo(); tx = MX + 16
    if lg:
        iw, ih = lg.getSize()
        c.drawImage(lg, MX + 16, yy - 48, width=40 * iw / ih, height=40, mask="auto"); tx = MX + 16 + 40 * iw / ih + 16
    txt(c, tx, yy - 22, E("nome"), "PB", 8.4, NAVY)
    txt(c, tx, yy - 34, "CNPJ " + E("cnpj"), "P", 7.2, GREY)
    if E("tipo"): txt(c, tx, yy - 45, E("tipo"), "P", 7.2, GREY)
    g_ = ImageReader(str(ASSETS / "GRUPO.png")); gw, gh = g_.getSize()
    c.drawImage(g_, W - MX - 16 - 70, yy - 40, width=70, height=70 * gh / gw, mask="auto")
    txt(c, W / 2, yy - 90, "Relatório gerado pelo sistema GDF — Gestão de Demonstrativo Financeiro · Grupo Enermais", "P", 6.6, GREY, "c")


# ------------------------------------------------------------------ build
ROTULO_STATUS = {"RASCUNHO": "RASCUNHO", "REVISADO": "VERSÃO FINAL"}


def gerar_pdf(ctx: dict, textos: dict | None = None, status: str = "RASCUNHO", gerado_em: str = "", versao: int | None = None) -> bytes:
    """Gera o PDF em memoria. status: RASCUNHO (marca de rascunho no rodape) ou REVISADO (versao final, para assinatura). `textos`: edicoes da contadora (chave -> texto); o que faltar usa o modelo padrao."""
    _registrar_fontes()
    with _LOCK:
        X.clear(); X.update(ctx)
        T.clear(); T.update(RD.textos_padrao(ctx)); T.update({k: v for k, v in (textos or {}).items() if k in T and (v or "").strip()})
        rot = ROTULO_STATUS.get(status, status)
        STATUS["final"] = status == "REVISADO"
        STATUS["txt"] = rot + (f" · v{versao}" if versao else "") + (f" · gerado em {gerado_em}" if gerado_em else "")
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(W, H), invariant=1)
        c.setTitle(f"Demonstrativos Financeiros — {E('nome')} — {X['data_base']}"); c.setAuthor("Grupo Enermais — GDF"); c.setSubject(f"{rot} · {X['periodo']}")
        N = len(PAGES)
        for i, fn in enumerate(PAGES, 1):
            fn(c, i, N); c.showPage()
        c.save()
        return buf.getvalue()
