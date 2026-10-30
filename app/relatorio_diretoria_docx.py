# -*- coding: utf-8 -*-
"""GDF V2 - Relatorio do Painel da Diretoria em WORD (.docx), v0.63.1: o mesmo visual do PDF (A4 retrato, capa com a marca, cabecalho e rodape por aba,
cartoes, tabelas azul-marinho, notas, caixa de observacao, graficos de barras) com TEXTO EDITAVEL. Usa a MESMA estrutura (`relatorio_diretoria_dados.montar`) do PDF.
Os graficos entram como imagem (o Word nao edita) e, logo abaixo, uma tabela pequena com os valores do grafico, para editar. Nada vai ao banco."""
from __future__ import annotations

import io
from pathlib import Path

from relatorio_fmt import fnum, mmn

ASSETS = Path(__file__).resolve().parent / "assets_relatorio"
_FMT = {
    "mi": lambda v: mmn(v, 1),
    "mi2": lambda v: mmn(v, 2),
    "int": lambda v: fnum(v, 0),
    "p1": lambda v: fnum(v, 1),
    "mil": lambda v: fnum(v / 1000.0, 0),
}
NAVY, ORANGE, GREY, GREY_BG, BORDER = "171C60", "EA9527", "525252", "F6F8FB", "DADFE8"
NEG_TXT, NEG_FILL, TOT_BG, OBS_BG = "9A5200", "E9962A", "E4E7F2", "FFF6EA"
BLUES = ["B4B9D6", "9A9CC4", "7F84AE", "5C6091", "3A3F7A", "171C60"]
FONTE = "Arial"
_CW_PT = 515.0                    # largura util (pt), igual ao PDF (A4 retrato, margem 40 pt)
_POR_LINHA_BARRAS = 12


def _cel_txt(v) -> str:
    return str(v[0] if isinstance(v, tuple) else v)


def _eh_neg(s: str) -> bool:
    return str(s).strip().startswith("−") or str(s).strip().startswith("-")


# ------------------------------------------------------------------ pecas de baixo nivel (XML do Word)
def _xml(tag: str, **attrs):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn("w:" + k), str(v))
    return el


_APOS_SHD = ("w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark")


def _sombra(cell, cor: str) -> None:
    cell._tc.get_or_add_tcPr().insert_element_before(_xml("w:shd", val="clear", color="auto", fill=cor), *_APOS_SHD)


def _tr(row, tag: str, **attrs) -> None:
    """Propriedade de linha (cantSplit, trHeight, tblHeader) na ordem que o Word exige."""
    ordem = ["w:cantSplit", "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden"]
    row._tr.get_or_add_trPr().insert_element_before(_xml(tag, **attrs), *ordem[ordem.index(tag) + 1:])


def _bordas(cell, **lados) -> None:
    """lados: top/bottom/left/right = (cor, tamanho em 1/8 pt) ou None (sem borda)."""
    tcPr = cell._tc.get_or_add_tcPr()
    b = _xml("w:tcBorders")
    for lado in ("top", "left", "bottom", "right"):
        v = lados.get(lado)
        b.append(_xml("w:" + lado, val="nil") if not v else _xml("w:" + lado, val="single", sz=v[1], space=0, color=v[0]))
    tcPr.insert_element_before(b, "w:shd", *_APOS_SHD)


def _largura(cell, pt: float) -> None:
    from docx.shared import Pt
    cell.width = Pt(pt)


def _tabela(doc, linhas: int, larguras: list):
    """Tabela sem estilo, largura fixa (pt) e margens internas pequenas."""
    from docx.shared import Pt
    t = doc.add_table(rows=linhas, cols=len(larguras))
    t.autofit = False
    tblPr = t._tbl.tblPr
    tblPr.insert_element_before(_xml("w:tblLayout", type="fixed"), "w:tblCellMar", "w:tblLook")
    mar = _xml("w:tblCellMar")
    for lado, v in (("top", 35), ("left", 80), ("bottom", 35), ("right", 80)):
        mar.append(_xml("w:" + lado, w=v, type="dxa"))
    tblPr.insert_element_before(mar, "w:tblLook")
    for i, w in enumerate(larguras):
        t.columns[i].width = Pt(w)
        for r in t.rows:
            _largura(r.cells[i], w)
    return t


def _run(p, texto, tam=8.0, negrito=False, cor=None, italico=False):
    from docx.shared import Pt, RGBColor
    r = p.add_run(str(texto))
    r.bold, r.italic = negrito, italico
    r.font.size = Pt(tam)
    r.font.name = FONTE
    r._element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", FONTE)
    if cor:
        r.font.color.rgb = RGBColor.from_string(cor)
    return r


def _par(cell_ou_doc, texto="", tam=8.0, negrito=False, cor=None, dir_=False, centro=False, italico=False, antes=0, depois=0, primeiro=False):
    """Escreve um paragrafo (no primeiro paragrafo da celula, se `primeiro`)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    p = cell_ou_doc.paragraphs[0] if primeiro else cell_ou_doc.add_paragraph()
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(antes), Pt(depois)
    if dir_:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif centro:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if texto != "":
        _run(p, texto, tam, negrito, cor, italico)
    return p


def _campo(p, instr: str, tam=6.8, cor=GREY) -> None:
    """Campo do Word (PAGE / NUMPAGES): o numero aparece e se atualiza sozinho (cada parte numa corrida com a mesma fonte)."""
    def parte(el):
        r = _run(p, "", tam, False, cor)
        r._r.append(el)
    parte(_xml("w:fldChar", fldCharType="begin"))
    it = _xml("w:instrText")
    it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    it.text = f" {instr} "
    parte(it)
    parte(_xml("w:fldChar", fldCharType="separate"))
    _run(p, "1", tam, False, cor)
    parte(_xml("w:fldChar", fldCharType="end"))


def _linha_sob(p, cor: str, sz: int) -> None:
    pPr = p._p.get_or_add_pPr()
    b = _xml("w:pBdr")
    b.append(_xml("w:bottom", val="single", sz=sz, space=2, color=cor))
    pPr.insert_element_before(b, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
                              "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                              "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


# ------------------------------------------------------------------ cabecalho, rodape e capa
def _cabecalho(section, mes_rot: str, secao: str) -> None:
    from docx.shared import Cm, Pt
    h = section.header
    h.is_linked_to_previous = False
    p0 = h.paragraphs[0]
    t = h.add_table(2, 2, Pt(_CW_PT))
    t.autofit = False
    p0._p.getparent().remove(p0._p)
    fim = h.add_paragraph()                                                             # o cabecalho do Word termina sempre em paragrafo
    fim.paragraph_format.space_before = fim.paragraph_format.space_after = Pt(0)
    _run(fim, "", 1)
    larg = [Pt(_CW_PT * 0.62), Pt(_CW_PT * 0.38)]
    for r in t.rows:
        for i, c in enumerate(r.cells):
            c.width = larg[i]
    for i, cor in enumerate((NAVY, ORANGE)):                                            # faixa fina azul + laranja do topo
        c = t.rows[0].cells[i]
        _sombra(c, cor)
        _par(c, "", 1, primeiro=True)
    _tr(t.rows[0], "w:trHeight", val=70, hRule="exact")
    a, b = t.rows[1].cells
    _par(a, "", primeiro=True, antes=4).add_run().add_picture(str(ASSETS / "GRUPO.png"), height=Cm(0.95))
    _par(b, "PAINEL ENERMAIS · " + mes_rot, 6.4, True, NAVY, dir_=True, primeiro=True, antes=8)
    _par(b, secao, 8, True, NAVY, dir_=True)
    for c in (a, b):
        _bordas(c, bottom=(BORDER, 5))


def _rodape(section, gerado: str) -> None:
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Pt
    f = section.footer
    f.is_linked_to_previous = False
    p = f.paragraphs[0]
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    for pos in (234, 468):                                                              # tabulacoes padrao do estilo de rodape do Word: saem
        p.paragraph_format.tab_stops.add_tab_stop(Pt(pos), WD_TAB_ALIGNMENT.CLEAR)
    p.paragraph_format.tab_stops.add_tab_stop(Pt(_CW_PT / 2), WD_TAB_ALIGNMENT.CENTER)
    p.paragraph_format.tab_stops.add_tab_stop(Pt(_CW_PT), WD_TAB_ALIGNMENT.RIGHT)
    _run(p, gerado, 6, True, ORANGE)
    _run(p, "\tPágina ", 6.8, False, GREY)
    _campo(p, "PAGE")
    _run(p, " de ", 6.8, False, GREY)
    _campo(p, "NUMPAGES")
    _run(p, "\tGrupo EnerMais", 6, False, GREY)


def _capa(doc, meta: dict) -> None:
    from docx.shared import Cm
    t = _tabela(doc, 1, [_CW_PT * 0.80, _CW_PT * 0.20])                               # faixa do topo: azul + laranja
    for c, cor in zip(t.rows[0].cells, (NAVY, ORANGE)):
        _sombra(c, cor)
        _par(c, "", 1, primeiro=True)
    _tr(t.rows[0], "w:trHeight", val=80, hRule="exact")
    p = _par(doc, "", antes=70)
    p.add_run().add_picture(str(ASSETS / "GRUPO.png"), width=Cm(7.6))
    _par(doc, "", antes=70)
    b = _tabela(doc, 1, [52])
    _sombra(b.rows[0].cells[0], ORANGE)
    _par(b.rows[0].cells[0], "", 1, primeiro=True)
    _tr(b.rows[0], "w:trHeight", val=60, hRule="exact")
    _par(doc, "Relatório do", 27, True, NAVY, antes=14)
    _par(doc, "Painel da Diretoria", 27, True, NAVY)
    _par(doc, "Informações escolhidas para este relatório", 9.5, False, GREY, antes=10)
    _par(doc, "Referência: " + _mes_extenso(meta.get("mes", "")), 9.5, False, GREY)
    _par(doc, "", 2, antes=8)
    pill = _tabela(doc, 1, [330])
    c = pill.rows[0].cells[0]
    _sombra(c, ORANGE)
    _par(c, "PERÍODO · " + str(meta.get("per_rot", "")).upper(), 7.6, True, "FFFFFF", centro=True, primeiro=True, antes=3, depois=3)
    _par(doc, "", antes=4)
    for ln in (meta.get("filtros") or [])[1:]:
        _par(doc, str(ln), 7.6, False, GREY)
    _par(doc, "Informações do Sienge (API) e dos arquivos importados no painel. Valores em R$ salvo indicação.", 6.4, False, GREY, antes=60)
    gerado = f"Gerado em {meta.get('gerado_em', '')}" + (f" por {meta['usuario']}" if meta.get("usuario") else "")
    _par(doc, gerado, 6, True, ORANGE)


_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _mes_extenso(mes: str) -> str:
    try:
        return f"{_MESES[int(mes[5:7]) - 1]} de {mes[:4]}"
    except Exception:                                                                     # noqa: BLE001
        return str(mes or "")


def _mes_rot(mes: str) -> str:
    return f"{mes[5:7]}/{mes[:4]}" if len(str(mes)) >= 7 else str(mes or "")


# ------------------------------------------------------------------ elementos
def _titulo(doc, texto: str, nivel: int) -> None:
    """Titulo de informacao (nivel 2) ou subtitulo (3): azul-marinho em negrito com filete laranja, como no PDF."""
    from docx.shared import Pt
    p = doc.add_heading("", level=nivel)
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(10 if nivel == 2 else 6), Pt(4)
    p.paragraph_format.keep_with_next = True
    _run(p, texto, 12 if nivel == 2 else 9.5, True, NAVY)
    _linha_sob(p, ORANGE, 8 if nivel == 2 else 4)


def _nota(doc, texto: str) -> None:
    t = _tabela(doc, 1, [_CW_PT])
    c = t.rows[0].cells[0]
    _sombra(c, GREY_BG)
    _bordas(c, top=(BORDER, 4), bottom=(BORDER, 4), left=(BORDER, 4), right=(BORDER, 4))
    _par(c, texto, 7.6, False, GREY, primeiro=True, antes=2, depois=2)
    _par(doc, "", 2, depois=2)


def _obs(doc, texto: str) -> None:
    t = _tabela(doc, 1, [_CW_PT])
    c = t.rows[0].cells[0]
    _sombra(c, OBS_BG)
    _bordas(c, top=(ORANGE, 6), bottom=(ORANGE, 6), right=(ORANGE, 6), left=(ORANGE, 24))
    _par(c, "OBSERVAÇÃO", 6.6, True, ORANGE, primeiro=True, antes=2)
    for ln in str(texto).split("\n"):
        _par(c, ln.strip(), 7.8, False, NAVY, depois=1)
    _par(doc, "", 2)


def _kpis(doc, e: dict) -> None:
    itens = e.get("itens") or []
    por = max(1, int(e.get("n", 4)))
    gap = 8.0
    w = (_CW_PT - (por - 1) * gap) / por
    larg = []
    for j in range(por):
        larg += [w] + ([gap] if j < por - 1 else [])
    for i in range(0, len(itens), por):
        t = _tabela(doc, 1, larg)
        for j, it in enumerate(itens[i:i + por]):
            c = t.rows[0].cells[2 * j]
            neg = str(it.get("val", "")).startswith("−")
            if it.get("dark"):
                _sombra(c, NAVY)
                _par(c, str(it.get("rot", "")).upper(), 6.2, True, "F99D20", primeiro=True, antes=4)
                _par(c, str(it.get("val", "")), 14, True, "FFFFFF", antes=2)
                if it.get("sub"):
                    _par(c, str(it["sub"]), 6.6, False, "D6D9EA", depois=4)
            else:
                _sombra(c, GREY_BG)
                _bordas(c, left=(NAVY, 24))
                _par(c, str(it.get("rot", "")).upper(), 6.2, True, NAVY, primeiro=True, antes=4)
                _par(c, str(it.get("val", "")), 14, True, NEG_TXT if neg else NAVY, antes=2)
                if it.get("sub"):
                    _par(c, str(it["sub"]), 6.6, False, GREY, depois=4)
        _par(doc, "", 2, depois=2)


def _larguras(head: list, rows: list, pesos: list, alin: list, fs: float) -> list:
    """Larguras (pt) das colunas: proporcionais aos pesos, mas as de numero nunca menores que o maior valor."""
    tp = float(sum(pesos)) or 1.0
    base = [_CW_PT * p / tp for p in pesos]
    mins = []
    for j in range(len(base)):
        if alin[j] == "r":
            m = max([len(w_) for w_ in str(head[j]).split()] + [len(_cel_txt(cel[j])) if j < len(cel) else 0 for _t, cel in rows] + [1]) * fs * 0.62 + 12
        else:
            m = 40.0
        mins.append(m)
    larg = [max(b, m) if alin[j] == "r" else b for j, (b, m) in enumerate(zip(base, mins))]
    excesso = sum(larg) - _CW_PT
    if excesso > 0:
        livres = [j for j in range(len(larg)) if alin[j] != "r"]
        for j in livres:
            larg[j] = max(mins[j], larg[j] - excesso / (len(livres) or 1))
        s = sum(larg)
        if s > _CW_PT:
            larg = [x * _CW_PT / s for x in larg]
    return larg


def _tab(doc, e: dict) -> None:
    from docx.shared import Pt
    head, rows = list(e.get("head") or []), list(e.get("rows") or [])
    if not head and not rows:
        return
    n = len(head) if head else len(rows[0][1])
    alin = list(e.get("alin") or (["l"] + ["r"] * (n - 1)))
    pesos = list(e.get("pesos") or [1] * n)
    fs = float(e.get("fs", 6.9))
    if e.get("titulo"):
        p = _par(doc, str(e["titulo"]), 8.5, True, NAVY, antes=4, depois=2)
        p.paragraph_format.keep_with_next = True
    larg = _larguras(head, rows, pesos, alin, fs)
    t = _tabela(doc, (1 if head else 0) + len(rows), larg)
    k = 0
    if head:
        _tr(t.rows[0], "w:cantSplit")
        _tr(t.rows[0], "w:tblHeader")                                                   # cabecalho repete em cada pagina
        for j, hd in enumerate(head):
            c = t.rows[0].cells[j]
            _sombra(c, NAVY)
            _par(c, _cel_txt(hd), 6.6, True, "FFFFFF", dir_=(alin[j] == "r"), primeiro=True, antes=2, depois=2)
        k = 1
    for i, (tipo, cel) in enumerate(rows):
        row = t.rows[k + i]
        _tr(row, "w:cantSplit")
        forte = tipo in ("sub", "tot", "sec")
        for j in range(n):
            v = cel[j] if j < len(cel) else ""
            s, cor = (v[0], v[1]) if isinstance(v, tuple) else (str(v), None)
            c = row.cells[j]
            if tipo == "tot":
                _sombra(c, TOT_BG)
            elif tipo in ("sub", "sec"):
                _sombra(c, GREY_BG)
            _bordas(c, bottom=(BORDER, 4))
            cor_txt = NEG_TXT if _eh_neg(s) else (NAVY if forte else "262626")
            _par(c, s, fs + (0.2 if tipo == "tot" else 0), forte, cor_txt, dir_=(alin[j] == "r"), primeiro=True, antes=1, depois=1)
    _par(doc, "", 2, depois=4)


def _png_barras(labels, vals, fmt, unidade: str, titulo, h_pt: float) -> bytes:
    """Grafico de barras no mesmo estilo do PDF (azul em degrade, negativo laranja, valor sobre a barra). Desenhado com Pillow, 4 px por ponto."""
    from PIL import Image, ImageDraw, ImageFont
    import relatorio_pdf as R
    S = 4
    W, top, bot = int(_CW_PT * S), 22 * S, 22 * S
    H = int(top + h_pt * S + bot)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def fonte(nome, pt):
        return ImageFont.truetype(str(ASSETS / "fonts" / f"Poppins-{nome}.ttf"), int(pt * S))

    fb, fr = fonte("Bold", 6.2), fonte("Regular", 6)
    if titulo:
        d.text((0, 2 * S), str(titulo), font=fonte("Bold", 8.5), fill="#" + NAVY)
    wd = int(d.textlength(unidade, font=fonte("Bold", 5.8)) + 10 * S)
    d.rounded_rectangle((W - wd, 2 * S, W, 13 * S), radius=5 * S, fill="#" + GREY_BG, outline="#" + BORDER)
    d.text((W - wd / 2, 7.5 * S), unidade, font=fonte("Bold", 5.8), fill="#" + GREY, anchor="mm")
    nums = [v for v in vals if v is not None] or [0]
    lo, hi = R.eixo_y(nums)
    sc = h_pt * S / (hi - lo)
    y0 = top + hi * sc                                                                 # linha do zero
    n = len(vals)
    slot = (W - 12 * S) / n
    bw = slot * 0.56
    d.line((6 * S, y0, W - 6 * S, y0), fill="#9AA0B8", width=max(1, int(0.7 * S)))
    mx = max(abs(v) for v in nums) or 1
    passo_lab = max(1, int(max(d.textlength(str(lb), font=fr) for lb in labels) / slot) + 1) if labels else 1
    passo_val = max(1, int(max((d.textlength(fmt(v), font=fb) for v in vals if v is not None), default=0) / slot) + 1)
    for i, v in enumerate(vals):
        x = 6 * S + i * slot + (slot - bw) / 2
        cx = x + bw / 2
        if v is None:
            d.text((cx, y0 - 4 * S), "n/d", font=fr, fill="#" + GREY, anchor="mm")
        else:
            bh = abs(v) * sc
            if v >= 0:
                k = 2 + int(round((abs(v) / mx) * 3))
                d.rectangle((x, y0 - bh, x + bw, y0), fill="#" + BLUES[min(k, 5)])
            else:
                d.rectangle((x, y0, x + bw, y0 + bh), fill="#" + NEG_FILL)
            if i % passo_val == 0:
                d.text((cx, (y0 - bh - 4.5 * S) if v >= 0 else (y0 + bh + 5 * S)), fmt(v), font=fb, fill="#" + (NEG_TXT if v < 0 else NAVY), anchor="mm")
        if i % passo_lab == 0:
            d.text((cx, H - 8 * S), str(labels[i]), font=fr, fill="#" + GREY, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(72 * S, 72 * S))
    return buf.getvalue()


def _barras(doc, e: dict) -> None:
    from docx.shared import Pt
    labels, vals = [str(x) for x in (e.get("labels") or [])], list(e.get("vals") or [])
    if not vals:
        return
    fmt = _FMT.get(e.get("fmt") or "mi", _FMT["mi"])
    try:
        png = _png_barras(labels, vals, fmt, e.get("unidade") or "R$ MM", e.get("titulo"), float(e.get("h", 100)))
        p = _par(doc, "", antes=2)
        p.add_run().add_picture(io.BytesIO(png), width=Pt(_CW_PT))
        p.paragraph_format.keep_with_next = True
    except Exception:                                                                   # noqa: BLE001  (sem a imagem, ficam so' os valores)
        if e.get("titulo"):
            _par(doc, str(e["titulo"]), 8.5, True, NAVY)
    # valores do grafico, para editar (pequenos, em cinza)
    for i in range(0, len(vals), _POR_LINHA_BARRAS):
        lb, vs = labels[i:i + _POR_LINHA_BARRAS], vals[i:i + _POR_LINHA_BARRAS]
        w = _CW_PT / len(lb)
        t = _tabela(doc, 2, [w] * len(lb))
        for j in range(len(lb)):
            _par(t.rows[0].cells[j], lb[j], 6, False, GREY, dir_=True, primeiro=True)
            _par(t.rows[1].cells[j], "–" if vs[j] is None else fmt(vs[j]), 6.4, True, NAVY, dir_=True, primeiro=True)
            for r in t.rows:
                _bordas(r.cells[j], bottom=(BORDER, 4))
    _par(doc, "", 2, depois=4)


# ------------------------------------------------------------------ documento
def gerar_docx(dados: dict) -> bytes:
    """Word (bytes) do relatorio. `dados` = relatorio_diretoria_dados.montar(...)."""
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.shared import Cm, Pt, RGBColor
    meta = dados["meta"]
    mes_rot = _mes_rot(meta.get("mes", ""))
    gerado = f"Gerado em {meta.get('gerado_em', '')}"
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONTE, Pt(9)
    for nome in ("Heading 2", "Heading 3"):
        s = doc.styles[nome]
        s.font.name, s.font.bold, s.font.color.rgb = FONTE, True, RGBColor.from_string(NAVY)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Pt(40)
    sec.top_margin, sec.bottom_margin = Cm(2.6), Cm(1.8)
    sec.header_distance, sec.footer_distance = Cm(0), Cm(0.7)
    doc.core_properties.title = f"Relatório do Painel da Diretoria — {meta.get('per_rot', '')}"
    doc.core_properties.author = "Grupo EnerMais — GDF"
    sec.top_margin = Cm(1.2)                                                            # capa sem cabecalho
    _capa(doc, meta)
    for ab in dados.get("abas", []):
        s = doc.add_section(WD_SECTION.NEW_PAGE)
        s.top_margin, s.bottom_margin = Cm(2.25), Cm(1.8)
        s.header_distance, s.footer_distance = Cm(0), Cm(0.7)
        _cabecalho(s, mes_rot, str(ab.get("rotulo") or ab.get("aba")))
        _rodape(s, gerado)
        for bl in ab.get("blocos", []):
            _titulo(doc, str(bl.get("titulo") or ""), 2)
            for e in bl.get("els", []):
                t = e.get("t")
                if t == "kpis":
                    _kpis(doc, e)
                elif t == "tab":
                    _tab(doc, e)
                elif t == "barras":
                    _barras(doc, e)
                elif t == "sec":
                    _titulo(doc, str(e.get("texto") or ""), 3)
                elif t == "nota":
                    _nota(doc, str(e.get("texto") or ""))
        if ab.get("obs"):
            _obs(doc, ab["obs"])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
