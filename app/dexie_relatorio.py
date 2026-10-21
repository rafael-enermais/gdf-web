# -*- coding: utf-8 -*-
"""GDF - Dexie: RELATORIO em PDF (e Excel) da ultima consulta: titulo, resumo da resposta, grafico e tabela, no padrao visual dos demais PDFs do GDF
(Poppins, navy/laranja, logo do Grupo). Gerado em memoria (bytes), sem gravar nada em disco. Nao calcula nada: so' desenha a tabela que a ferramenta devolveu
e o grafico que a pessoa pediu; o resumo e' o texto da resposta da Dexie, ja limpo."""
from __future__ import annotations

import io
import re

from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

import relatorio_pdf as R
from relatorio_fmt import fnum, pct
from relatorio_pdf import ASSETS, BORDER, BRAND_OR, CW, GREY, H, MID, MX, NAVY, W, caixa_nota, hline, rect, tabela, txt

TOPY = H - 84
MAX_LINHAS_PDF = 150
MAX_COLUNAS = 5
_ROT_PCT = re.compile(r"(pct|margem|taxa|variacao|var)", re.I)


def _plano(s) -> str:
    """Resposta em markdown -> texto corrido simples (sem **, #, crases, escapes de cifrao)."""
    t = re.sub(r"[*_`#>]+", "", str(s or ""))
    t = t.replace("\\$", "$")
    t = re.sub(r"^\s*[-•]\s+", "• ", t, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _celula(col: str, v) -> str:
    if v is None or v == "":
        return "–"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and _ROT_PCT.search(col) and abs(v) <= 5:
            return pct(v)
        return fnum(v, 2) if isinstance(v, float) else str(v)
    return str(v)


def _moldura(c, n, N, titulo_, gerado_em, usuario):
    rect(c, 0, H - 4, W * 0.62, 4, fill=NAVY); rect(c, W * 0.62, H - 4, W * 0.38, 4, fill=BRAND_OR)
    g = ImageReader(str(ASSETS / "GRUPO.png")); gw, gh = g.getSize(); lh = 30
    c.drawImage(g, MX, H - 50, width=lh * gw / gh, height=lh, mask="auto")
    txt(c, W - MX, H - 28, "DEXIE · RELATÓRIO DE CONSULTA", "PB", 6.4, NAVY, "r")
    txt(c, W - MX, H - 39, titulo_[:70], "PB", 8, NAVY, "r")
    hline(c, MX, W - MX, H - 58, BORDER, 0.6)
    hline(c, MX, W - MX, 38, BORDER, 0.5)
    txt(c, MX, 26, f"Gerado em {gerado_em}" + (f" · por {usuario}" if usuario else ""), "P", 6.2, GREY)
    txt(c, W / 2, 26, f"Página {n} de {N}", "P", 6.8, GREY, "c")
    txt(c, W - MX, 26, "Grupo EnerMais · GDF", "P", 6, GREY, "r")


def _grafico(c, y, tab, g, altura=170):
    """Desenha o grafico pedido (barras, barras_horizontais ou linhas) a partir da tabela. Devolve o novo y."""
    x_col, y_cols = g["x"], g["y"]
    linhas = [l for l in tab if isinstance(l.get(y_cols[0]), (int, float))][:24]
    if not linhas:
        return y
    rot = [str(l.get(x_col, ""))[:11] for l in linhas]
    if g.get("titulo"):
        txt(c, MX, y, g["titulo"][:90], "PB", 9, NAVY); y -= 10
    if g["tipo"] == "linhas":
        series = [[l.get(k) if isinstance(l.get(k), (int, float)) else None for l in linhas] for k in y_cols]
        todos = [v for s in series for v in s if v is not None]
        lo, hi = min(todos + [0]), max(todos + [0.0001])
        base, w = y - altura, CW
        sc = (altura - 12) / (hi - lo or 1)
        hline(c, MX, MX + w, base + (-lo) * sc, BORDER, 0.7)
        n = max(len(linhas) - 1, 1)
        for si, s in enumerate(series):
            cor = [NAVY, BRAND_OR, MID][si]
            c.setStrokeColor(cor); c.setLineWidth(1.4)
            ant = None
            for i, v in enumerate(s):
                if v is None:
                    ant = None
                    continue
                px, py = MX + 12 + (w - 24) * i / n, base + (v - lo) * sc
                if ant:
                    c.line(ant[0], ant[1], px, py)
                c.setFillColor(cor); c.circle(px, py, 1.8, fill=1, stroke=0)
                ant = (px, py)
            txt(c, MX + w - si * 95, y + 10, f"— {y_cols[si][:16]}", "PB", 6.2, cor, "r")                 # legenda na linha do titulo
        passo = max(1, len(linhas) // 12)
        for i, r_ in enumerate(rot):
            if i % passo == 0:
                txt(c, MX + 12 + (w - 24) * i / n, base - 9, r_, "P", 5.8, GREY, "c")
        return base - 22
    vals = [float(l[y_cols[0]]) for l in linhas]
    if g["tipo"] == "barras_horizontais" and all(v >= 0 for v in vals) and sum(vals) > 0:
        h_ = 12 * len(linhas)
        mx = max(vals) or 1
        yy = y - 6
        for r_, v in zip([str(l.get(x_col, ""))[:34] for l in linhas], vals):
            txt(c, MX, yy, r_, "P", 6.8, GREY)
            rect(c, MX + 160, yy - 1.5, max((CW - 250) * v / mx, 0.8), 7.2, fill=NAVY)
            txt(c, MX + CW, yy, fnum(v, 2), "P", 6.8, NAVY, "r")
            yy -= 12
        return yy - 6
    R.barras(c, MX, y - altura, CW, altura - 22, rot, vals, fmt=lambda v: fnum(v, 0))
    if len(y_cols) > 1:
        txt(c, MX + CW, y + 2, f"(1ª série: {y_cols[0][:30]})", "P", 6, GREY, "r")
    return y - altura - 14


def _desenhar(c, N, titulo_, resumo, tab, g, gerado_em, usuario, origem):
    n = 1
    _moldura(c, n, N, titulo_, gerado_em, usuario)
    y = TOPY
    txt(c, MX, y, titulo_[:80], "PB", 15, NAVY); y -= 16
    txt(c, MX, y, origem[:120], "P", 8, GREY); y -= 18
    if resumo:
        y = R.para(c, _plano(resumo)[:2500], MX, y, CW, size=8.2, lead=12.2, color=GREY, gap=4) - 4
    if g and tab:
        if y < 260:
            c.showPage(); n += 1; _moldura(c, n, N, titulo_, gerado_em, usuario); y = TOPY
        y = _grafico(c, y, tab, g)
    if tab:
        cols = list(tab[0].keys())[:MAX_COLUNAS]
        if y < 160:
            c.showPage(); n += 1; _moldura(c, n, N, titulo_, gerado_em, usuario); y = TOPY
        y -= 4
        w0 = CW * (0.4 if len(cols) > 1 else 1.0)
        larg = [(w0, "l")] + [((CW - w0) / max(len(cols) - 1, 1), "r") for _ in cols[1:]]
        cab = [k.replace("_", " ") for k in cols]
        linhas = [("norm", [_celula(k, l.get(k)) for k in cols]) for l in tab[:MAX_LINHAS_PDF]]
        por_pag = lambda yy: int((yy - 60) // 12.4)                                  # noqa: E731
        while linhas:
            cabem = max(por_pag(y - 24), 1)
            tabela(c, MX, y, larg, cab, linhas[:cabem])
            linhas = linhas[cabem:]
            if linhas:
                c.showPage(); n += 1; _moldura(c, n, N, titulo_, gerado_em, usuario); y = TOPY
            else:
                y -= 24 + 12.4 * cabem
        if len(tab) > MAX_LINHAS_PDF:
            txt(c, MX, 48, f"Mostradas as primeiras {MAX_LINHAS_PDF} de {len(tab)} linhas; o Excel traz tudo.", "P", 6.4, GREY)
    caixa_nota(c, max(y - 6, 110), "Relatório gerado pela Dexie a partir de consulta ao banco do GDF. Dado 'a conferir' não é número oficial; confira com a contabilidade antes de usar em decisão ou divulgação.")
    return n


def gerar_pdf(titulo_: str, tabela_: list, grafico: dict | None, resumo: str, usuario: str | None, gerado_em: str, origem: str = "") -> bytes:
    """PDF (bytes) da consulta. Nunca levanta por causa do conteudo: se o grafico nao puder ser desenhado, segue so' com a tabela."""
    R._registrar_fontes()
    titulo_ = (titulo_ or "Consulta").strip()[:80]
    with R._LOCK:
        for g_ in ((grafico, None) if grafico else (None,)):
            try:
                N = _desenhar(canvas.Canvas(io.BytesIO(), pagesize=(W, H), invariant=1), 1, titulo_, resumo, tabela_, g_, gerado_em, usuario, origem)      # ensaio: conta as paginas
                buf = io.BytesIO()
                c = canvas.Canvas(buf, pagesize=(W, H), invariant=1)
                c.setTitle(titulo_); c.setAuthor("Grupo EnerMais — GDF (Dexie)")
                _desenhar(c, N, titulo_, resumo, tabela_, g_, gerado_em, usuario, origem)
                c.showPage(); c.save()
                return buf.getvalue()
            except Exception:                                                              # noqa: BLE001
                if g_ is None:
                    raise
        raise RuntimeError("PDF nao gerado")


# ------------------------------------------------------------------ PDF da CONVERSA inteira
def _linhas_conversa(historico: list) -> list:
    """[(papel, [linhas de texto])] a partir do historico (so' texto). Tabela markdown vira linhas 'a · b · c'; markdown simples sai."""
    out = []
    for m in historico or []:
        if m.get("role") not in ("user", "assistant") or not str(m.get("content") or "").strip():
            continue
        bruto = []
        for ln in _plano(m["content"]).split("\n"):
            if re.match(r"^\s*\|?\s*:?-{2,}", ln):
                continue                                   # linha separadora da tabela (|---|---|)
            if ln.strip().startswith("|"):
                ln = "  ·  ".join(p.strip() for p in ln.strip().strip("|").split("|"))
            bruto.append(ln)
        out.append((m["role"], bruto))
    return out


def gerar_conversa_pdf(historico: list, usuario: str | None, gerado_em: str, titulo_: str = "Conversa com a Dexie") -> bytes:
    """PDF (bytes) da conversa inteira (perguntas e respostas, em ordem). Sem ferramentas/tabelas internas: so' o que a tela mostrou."""
    R._registrar_fontes()
    titulo_ = (titulo_ or "Conversa com a Dexie").strip()[:80]
    turnos = _linhas_conversa(historico)
    if not turnos:
        raise ValueError("Conversa vazia.")

    def desenhar(c, N):
        n = 1
        _moldura(c, n, N, titulo_, gerado_em, usuario)
        y = TOPY
        txt(c, MX, y, titulo_, "PB", 15, NAVY); y -= 16
        txt(c, MX, y, f"{len(turnos)} mensagens · registro da conversa, não é demonstrativo oficial", "P", 8, GREY); y -= 20
        for papel, linhas in turnos:
            quem, cor = ("Você", NAVY) if papel == "user" else ("Dexie", BRAND_OR)
            if y < 110:
                c.showPage(); n += 1; _moldura(c, n, N, titulo_, gerado_em, usuario); y = TOPY
            txt(c, MX, y, quem.upper(), "PB", 7, cor); y -= 11
            for ln in linhas:
                partes = simpleSplit(ln, "P", 8.2, CW) or [""]
                for p_ in partes:
                    if y < 56:
                        c.showPage(); n += 1; _moldura(c, n, N, titulo_, gerado_em, usuario); y = TOPY
                    txt(c, MX, y, p_, "P", 8.2, GREY if papel == "assistant" else NAVY); y -= 11.4
            y -= 8
        return n

    with R._LOCK:
        N = desenhar(canvas.Canvas(io.BytesIO(), pagesize=(W, H), invariant=1), 1)                 # ensaio: conta as paginas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(W, H), invariant=1)
        c.setTitle(titulo_); c.setAuthor("Grupo EnerMais — GDF (Dexie)")
        desenhar(c, N)
        c.showPage(); c.save()
        return buf.getvalue()
