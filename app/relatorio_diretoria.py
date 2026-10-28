# -*- coding: utf-8 -*-
"""GDF V2 - PDF do RELATORIO do Painel da Diretoria (v0.54.0). Desenha o que `relatorio_diretoria_dados.montar` entregou.

Em linguagem simples: pega a lista de abas/informacoes que a pessoa marcou (ja calculadas) e desenha no mesmo layout dos outros relatorios
(Poppins, navy/laranja, moldura com logo e torres): capa, sumario com os filtros usados e uma secao por aba. Tabelas e graficos quebram de pagina
sozinhos (cabecalho da tabela se repete). O PDF e' gerado em memoria (bytes); nada e' gravado em disco.
Nenhum calculo aqui: so' desenho."""
from __future__ import annotations

import io
import math

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

import relatorio_painel_pdf as RPP
import relatorio_pdf as R
from relatorio_fmt import fnum, mmn
from relatorio_pdf import ASSETS, BORDER, CW, GREY, H, MX, NAVY, NEG_TXT, ORANGE, W, WHITE, hline, kpi, rect, tabela, txt, unidade

TOPY = H - 84
BOT = 50.0
_NEG_TOT = HexColor("#FFD9A8")


# ------------------------------------------------------------------ pequenos ajudantes
def _clip(s: str, font: str, fs: float, maxw: float) -> str:
    s = str(s)
    if pdfmetrics.stringWidth(s, font, fs) <= maxw:
        return s
    while s and pdfmetrics.stringWidth(s + "…", font, fs) > maxw:
        s = s[:-1]
    return s.rstrip() + "…"


def _negativo(s: str) -> bool:
    return len(s) > 1 and s[0] in "−-" and not s.startswith("--")


def _fit_size(s: str, font: str, size: float, maxw: float, minimo: float = 7.5) -> float:
    while size > minimo and pdfmetrics.stringWidth(s, font, size) > maxw:
        size -= 0.5
    return size


def _kpi_ajustado(c, x, y, w, h, it):
    """Quadro de KPI com o valor reduzido para caber na largura (R.kpi usa tamanho fixo)."""
    val = str(it["val"])
    vs = _fit_size(val, "PB", 15, w - 24)
    kpi(c, x, y, w, h, _clip(str(it["rot"]).upper(), "PB", 6.2, w - 22), val, str(it["sub"]), dark=bool(it.get("dark")), vsize=vs)


_FMT_BARRAS = {
    "mi": lambda v: mmn(v, 1),
    "mi2": lambda v: mmn(v, 2),
    "int": lambda v: fnum(v, 0),
    "p1": lambda v: fnum(v, 1),
}


# ------------------------------------------------------------------ documento em fluxo
class _Doc:
    def __init__(self, c, N: int, ctx: dict, mapa_ant: dict | None = None):
        self.c, self.N, self.ctx = c, N, ctx
        self.n = 0
        self.y = TOPY
        self.sec = ""
        self.mapa: dict = {}
        self.ant = mapa_ant or {}

    # ---- paginas
    def pagina(self, secao_nome: str, continuacao: bool = False):
        if self.n:
            self.c.showPage()
        self.n += 1
        self.sec = secao_nome
        RPP._moldura(self.c, self.n, self.N, secao_nome + (" · continuação" if continuacao else ""), self.ctx)
        self.y = TOPY

    def garante(self, h: float):
        """Se nao cabe h na pagina, abre a proxima (mesma secao)."""
        if self.y - h < BOT:
            self.pagina(self.sec, continuacao=True)

    # ---- elementos
    def sec_(self, texto: str):
        self.garante(46)
        self.y = R.secao(self.c, self.y, _clip(texto, "PB", 9.5, CW))

    def nota_(self, texto: str):
        linhas = simpleSplit(texto, "P", 7.6, CW - 22)[:40]
        hh = len(linhas) * (7.6 + 3.4) + 14
        self.garante(hh + 8)
        self.y = R.caixa_nota(self.c, self.y, " ".join(linhas), h=hh)

    def kpis_(self, itens: list, por_linha: int):
        por_linha = max(1, por_linha)
        gap, kh = 10.0, 58.0
        w = (CW - (por_linha - 1) * gap) / por_linha
        for i in range(0, len(itens), por_linha):
            self.garante(kh + 8)
            for j, it in enumerate(itens[i:i + por_linha]):
                _kpi_ajustado(self.c, MX + j * (w + gap), self.y, w, kh, it)
            self.y -= kh + 8
        self.y -= 2

    def barras_(self, e: dict):
        labels, vals = list(e["labels"]), list(e["vals"])
        if not vals:
            return
        h = float(e.get("h", 100))
        self.garante(22 + h + 24)
        if e.get("titulo"):
            txt(self.c, MX, self.y - 8, _clip(e["titulo"], "PB", 8.5, CW - 110), "PB", 8.5, NAVY)
        unidade(self.c, W - MX, self.y - 8 + 2, e.get("unidade") or "R$ MM")
        n = len(vals)
        passo = 1 if n <= 24 else math.ceil(n / 20)
        labs = [lb if i % passo == 0 else "" for i, lb in enumerate(labels)]
        fmt = _FMT_BARRAS.get(e.get("fmt") or "mi", _FMT_BARRAS["mi"])
        base = self.y - 22 - h
        R.barras(self.c, MX + 6, base, CW - 12, h, labs, vals, fmt=fmt, size=6.2 if n <= 14 else 5.6, lbl_every=passo)
        self.y = base - 24

    @staticmethod
    def _h_nota(e: dict | None) -> float:
        if not e or e.get("t") != "nota":
            return 0.0
        return len(simpleSplit(e["texto"], "P", 7.6, CW - 22)[:40]) * (7.6 + 3.4) + 14 + 8

    def tab_(self, e: dict, reserva: float = 0.0):
        c = self.c
        head, rows, pesos, alin = e["head"], e["rows"], e["pesos"], e["alin"]
        fs, rh = float(e.get("fs", 6.9)), float(e.get("rh", 12.6))
        tp = float(sum(pesos)) or 1.0
        larg = [CW * p / tp for p in pesos]
        cols = list(zip(larg, alin))
        head_h = 24.0
        # prepara celulas (corta o que nao cabe; negativo em laranja escuro)
        prontas = []
        for tipo, cel in rows:
            font = "PB" if tipo in ("sub", "tot", "sec") else "P"
            nova = []
            for (w_, _al), v in zip(cols, cel):
                if isinstance(v, tuple):
                    s, cor = v
                else:
                    s, cor = str(v), None
                s = _clip(s, font, fs, w_ - 10)
                if cor is None and _negativo(s):
                    cor = _NEG_TOT if tipo == "tot" else NEG_TXT
                nova.append((s, cor) if cor is not None else s)
            prontas.append((tipo, nova))
        if e.get("titulo"):
            self.garante(head_h + 2 * rh + 20)
            txt(c, MX, self.y - 8, _clip(e["titulo"], "PB", 8.5, CW), "PB", 8.5, NAVY)
            self.y -= 14
        i = 0
        while i < len(prontas):
            self.garante(head_h + 2 * rh + 4)
            disp = self.y - BOT - head_h
            k, soma = i, 0.0
            while k < len(prontas):
                hh = rh + (4 if prontas[k][0] == "sec" else 0)
                if soma + hh > disp:
                    break
                soma += hh
                k += 1
            if k == i:                                               # nao coube nem uma linha: pagina nova
                self.pagina(self.sec, continuacao=True)
                continue
            if reserva and k == len(prontas) and soma + reserva + 10 > disp and k - i >= 3:
                k -= 1                                               # a nota que vem logo depois da tabela nao fica sozinha numa pagina so'
            if len(prontas) - k == 1 and k - i > 3 and prontas[-1][0] == "tot":
                k -= 1                                               # nao deixa so' a linha de total sozinha na pagina seguinte
            self.y = tabela(c, MX, self.y, cols, head, prontas[i:k], rh=rh, fs=fs, head_h=head_h)
            i = k
            if i < len(prontas):
                self.pagina(self.sec, continuacao=True)
        self.y -= 10

    def elemento(self, e: dict, prox: dict | None = None):
        t = e.get("t")
        if t == "kpis":
            self.kpis_(e["itens"], e.get("n", 4))
        elif t == "tab":
            self.tab_(e, self._h_nota(prox))
        elif t == "barras":
            self.barras_(e)
        elif t == "nota":
            self.nota_(e["texto"])
        elif t == "sec":
            self.sec_(e["texto"])

    def bloco(self, b: dict):
        self.garante(92)
        self.mapa[b["key"]] = self.n
        txt(self.c, MX, self.y - 10, _clip(b["titulo"], "PB", 11.5, CW), "PB", 11.5, NAVY)
        hline(self.c, MX, W - MX, self.y - 16, ORANGE, 0.9)
        self.y -= 28
        els = b["els"]
        for i, e in enumerate(els):
            try:
                self.elemento(e, els[i + 1] if i + 1 < len(els) else None)
            except Exception as exc:                                  # noqa: BLE001
                self.nota_(f"Parte desta informação não pôde ser desenhada ({type(exc).__name__}). Os dados continuam na tela do painel.")


# ------------------------------------------------------------------ capa e sumario
def _capa(c, meta: dict):
    c.setFillColor(NAVY)
    p = c.beginPath()
    p.moveTo(W * 0.80, H); p.lineTo(W, H); p.lineTo(W, 0); p.lineTo(W * 0.72, 0); p.close()
    c.drawPath(p, fill=1, stroke=0)
    mk = ImageReader(str(ASSETS / "capa_marca_pale.png"))
    c.saveState(); c.setFillAlpha(0.45); c.drawImage(mk, W * 0.835, 40, width=70, height=70 * 1409 / 983, mask="auto"); c.restoreState()
    rect(c, 0, H - 4, W * 0.80, 4, fill=NAVY)
    g = ImageReader(str(ASSETS / "GRUPO.png")); gw, gh = g.getSize(); lw_ = 215
    c.drawImage(g, MX + 8, H - 330, width=lw_, height=lw_ * gh / gw, mask="auto")
    rect(c, MX + 8, 405, 52, 3, fill=ORANGE)
    txt(c, MX + 8, 372, "Relatório do", "PB", 27, NAVY)
    txt(c, MX + 8, 342, "Painel da Diretoria", "PB", 27, NAVY)
    txt(c, MX + 8, 312, "Informações escolhidas para este relatório", "P", 9.5, GREY)
    txt(c, MX + 8, 297, "Referência: " + RPP._mes_extenso(meta["mes"]), "P", 9.5, GREY)
    rot = "PERÍODO · " + str(meta["per_rot"]).upper()
    pw = max(232.0, pdfmetrics.stringWidth(rot, "PB", 7.6) + 28)
    pw = min(pw, W * 0.72 - MX - 24)
    rect(c, MX + 8, 238, pw, 24, fill=ORANGE, r=12)
    txt(c, MX + 8 + pw / 2, 246.5, _clip(rot, "PB", 7.6, pw - 16), "PB", 7.6, WHITE, "c")
    y = 215.0
    for ln in meta.get("filtros", [])[1:]:
        for sub in simpleSplit(ln, "P", 7.6, W * 0.72 - MX - 24)[:3]:
            txt(c, MX + 8, y, sub, "P", 7.6, GREY)
            y -= 11
    txt(c, MX + 8, 70, "Informações do Sienge (API) e dos arquivos importados no painel. Valores em R$ salvo indicação.", "P", 6.4, GREY)
    txt(c, MX + 8, 26, RPP._Estado.status, "PB", 6, ORANGE)


def _sumario(d: _Doc, dados: dict):
    meta = dados["meta"]
    d.pagina("Sumário e filtros")
    c = d.c
    txt(c, MX, d.y, "Filtros deste relatório", "PB", 12, NAVY)
    d.y -= 18
    for ln in meta.get("filtros", []):
        for sub in simpleSplit(ln, "P", 8.2, CW)[:4]:
            txt(c, MX, d.y, sub, "P", 8.2, GREY)
            d.y -= 11.5
    d.y -= 4
    txt(c, MX, d.y, f"Gerado em {meta['gerado_em']}" + (f" · por {meta['usuario']}" if meta.get("usuario") else ""), "P", 7, GREY)
    d.y -= 22
    hline(c, MX, W - MX, d.y + 8, BORDER, 0.6)
    txt(c, MX, d.y - 6, "Conteúdo", "PB", 12, NAVY)
    d.y -= 26
    if not dados["abas"]:
        d.nota_("Nenhuma informação foi marcada para este relatório.")
        return
    for a in dados["abas"]:
        d.garante(14 + 10.4 * 2)
        pg = d.ant.get(("aba", a["aba"]))
        txt(c, MX, d.y, a["rotulo"], "PB", 9, NAVY)
        if pg:
            txt(c, W - MX, d.y, str(pg), "PB", 9, NAVY, "r")
        d.y -= 14
        for b in a["blocos"]:
            d.garante(11)
            pg = d.ant.get(b["key"])
            tt = _clip(b["titulo"], "P", 7.8, CW - 70)
            txt(c, MX + 12, d.y, tt, "P", 7.8, GREY)
            if pg:
                wt = pdfmetrics.stringWidth(tt, "P", 7.8)
                c.setStrokeColor(BORDER); c.setLineWidth(0.4); c.setDash(1, 2)
                c.line(MX + 12 + wt + 5, d.y + 2, W - MX - 18, d.y + 2); c.setDash()
                txt(c, W - MX, d.y, str(pg), "P", 7.8, GREY, "r")
            d.y -= 10.4
        d.y -= 5


# ------------------------------------------------------------------ geracao
def _desenhar(dados: dict, c, N: int, mapa_ant: dict | None) -> tuple:
    meta = dados["meta"]
    ctx = {"mes": meta["mes"]}
    # capa (pagina 1) usa o proprio desenho; as demais usam a moldura
    _capa(c, meta)
    d = _Doc(c, N, ctx, mapa_ant)
    d.n = 1                                                          # a capa conta como pagina 1
    _sumario(d, dados)
    for a in dados["abas"]:
        d.pagina(a["rotulo"])
        d.mapa[("aba", a["aba"])] = d.n
        for b in a["blocos"]:
            d.bloco(b)
    return d.n, d.mapa


def gerar_pdf(dados: dict, status: str = "") -> bytes:
    """PDF (bytes) do relatorio do Painel da Diretoria. `dados` = relatorio_diretoria_dados.montar(...). Duas passadas: a 1a conta as paginas e anota onde cada informacao caiu
    (para o sumario e o 'Pagina n de N'); a 2a desenha de verdade."""
    meta = dados["meta"]
    R._registrar_fontes()
    with R._LOCK:
        RPP._Estado.status = status or f"Gerado em {meta['gerado_em']}"
        N, mapa = _desenhar(dados, canvas.Canvas(io.BytesIO(), pagesize=(W, H), invariant=1), 0, None)       # ensaio
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(W, H), invariant=1)
        c.setTitle(f"Relatório do Painel da Diretoria — {meta['per_rot']}")
        c.setAuthor("Grupo EnerMais — GDF")
        c.setSubject("Painel da Diretoria")
        _desenhar(dados, c, N, mapa)
        c.save()
        return buf.getvalue()
