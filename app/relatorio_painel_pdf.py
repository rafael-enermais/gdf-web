# -*- coding: utf-8 -*-
"""GDF V2 - PDF do Painel EnerMais (RASCUNHO: o layout ainda depende de confirmacao do Rafael/contabilidade e pode mudar).
Reaproveita o padrao visual dos demonstrativos (Poppins, navy/laranja, quadros de KPI, tabelas e barras de relatorio_pdf.py).
O PDF e' gerado em memoria (bytes); nada e' gravado em disco. Cada pagina sem dado vira um aviso ("falta importar X"), nunca estoura erro.
Nenhum calculo novo aqui: os numeros vem das mesmas funcoes de painel_db usadas nas abas do painel."""
from __future__ import annotations

import io

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import relatorio_pdf as R
from relatorio_fmt import fnum, mm, mmn, neg, pct
from relatorio_pdf import (ASSETS, BLUES, BORDER, CW, GREY, GREY_BG, H, MX, NAVY, NEG_TXT, ORANGE, W, WHITE, barras, caixa_nota, hline, kpi,
                           lista_barras, para, rect, secao, tabela, titulo, txt, unidade)

TOPY = H - 84
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _rot_mes(m: str) -> str:
    return f"{m[5:]}/{m[:4]}"


def _mes_extenso(m: str) -> str:
    return f"{_MESES[int(m[5:]) - 1]} de {m[:4]}"


def _pc(v) -> str:
    return pct(v, 1) if v is not None else "–"


# ------------------------------------------------------------------ montagem dos dados (usa so as funcoes ja existentes do painel)
def montar_ctx(conn, mes: str, gerado_em: str = "") -> dict:
    """Junta tudo que o PDF mostra para o mes 'AAAA-MM'. Parte que nao tem dado vira None (a pagina explica o que falta)."""
    import painel_db as P

    ctx = {"mes": mes, "gerado_em": gerado_em, "dre": None, "serie": [], "obras": None, "adm": None, "pessoas": None, "avisos": []}

    # --- DRE: 1) confirmado  2) DRE oficial importado (PDF)  3) reconstrucao pela API
    conf = P.confirmacao_ativa(conn, mes) if P.confirmacao_instalada(conn) else None
    if conf:
        d = P.dre_de_folhas(conf["valores"] or {})
        fontes = conf["fontes"] or {}
        ctx["dre"] = {"linhas": d["linhas"], "valores": d["valores"], "origem": "DRE confirmado", "fontes": fontes,
                      "quem": conf["quem"], "quando": conf["quando"], "observacao": conf["observacao"],
                      "manuais": sorted(k for k, f in fontes.items() if f == "MANUAL")}
    else:
        imp = P.dre_importacao_ativa(conn, mes)
        if imp:
            contas = [{"plano_cod": c, "plano_nome": "", "valor": v} for c, v in P.dre_contas_importadas(conn, imp["id"]).items()]
            origem = "DRE oficial (PDF) — ainda não confirmado"
        else:
            contas = P.resultado_por_conta(conn, mes, sem_previsao=True)
            origem = "Reconstruído pela API do Sienge — a conferir"
        d = P.dre_do_mes(contas)
        ctx["dre"] = {"linhas": d["linhas"], "valores": d["valores"], "origem": origem, "fontes": {}, "quem": None, "quando": None,
                      "observacao": None, "manuais": []}
    ctx["serie"] = P.receita_mensal(conn)

    # --- Obras (DRE oficial importado)
    try:
        if mes in P.meses_com_dre(conn):
            ob = P.obras_do_dre(conn, mes)
            folha = P.folha_do_mes(conn, mes)
            ob["colab"] = P.colab_por_linha_obras(ob["linhas"], folha) if folha else {}
            ctx["obras"] = ob
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Obras: {type(exc).__name__}")

    # --- Administracao: despesas pagas nas unidades ADM + orcado x realizado
    try:
        adm = {"resumo": None, "orcamento": None, "serie_orc": []}
        meses_a = P.meses_com_dados(conn)
        if meses_a and P.centro_grupo_instalado(conn):
            regras = P.regras_ativas(conn, "DESPESAS")
            linhas = P.adm_linhas(conn, mes, mes, P.prefixos_excluidos(regras), sem_previsao=P.exclui_previsao(regras))
            if linhas:
                outros = P.credor_grupo_ativos(conn) if P.credor_grupo_instalado(conn) else []
                adm["resumo"] = P.adm_resumo(linhas, [c["chave"] for c in outros], P.nomes_plano(conn))
        orc = P.orcamento_ativo(conn) if P.orcamento_instalado(conn) else None
        if orc and mes in orc["meses"]:
            adm["orcamento"] = P.orcamento_resumo(conn, orc["id"], mes)
            adm["acumulado"] = P.orcamento_resumo(conn, orc["id"], mes, acumulado=True)
            adm["serie_orc"] = P.orcamento_serie_mensal(conn, orc["id"]) if hasattr(P, "orcamento_serie_mensal") else []
        if adm["resumo"] or adm["orcamento"]:
            ctx["adm"] = adm
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Administração: {type(exc).__name__}")

    # --- Pessoas (recibos da folha)
    try:
        if mes in P.folha_meses(conn):
            ctx["pessoas"] = {"folha": P.folha_do_mes(conn, mes), "serie": [x for x in P.folha_serie(conn) if x["he_pct"] is not None]}
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Pessoas: {type(exc).__name__}")
    return ctx


# ------------------------------------------------------------------ paginas
class _Estado:
    status = "RASCUNHO"


def _moldura(c, n, N, secao_nome, ctx):
    wm = ImageReader(str(ASSETS / "torre_watermark.png"))
    c.drawImage(wm, W / 2 - 170, 28, width=340, height=343, mask="auto")
    rect(c, 0, H - 4, W * 0.62, 4, fill=NAVY); rect(c, W * 0.62, H - 4, W * 0.38, 4, fill=ORANGE)
    g = ImageReader(str(ASSETS / "GRUPO.png")); gw, gh = g.getSize(); lh = 30
    c.drawImage(g, MX, H - 50, width=lh * gw / gh, height=lh, mask="auto")
    txt(c, W - MX, H - 28, "PAINEL ENERMAIS · " + _rot_mes(ctx["mes"]), "PB", 6.4, NAVY, "r")
    txt(c, W - MX, H - 39, secao_nome, "PB", 8, NAVY, "r")
    hline(c, MX, W - MX, H - 58, BORDER, 0.6)
    hline(c, MX, W - MX, 38, BORDER, 0.5)
    txt(c, MX, 26, _Estado.status, "PB", 6, ORANGE)
    txt(c, W / 2, 26, f"Página {n} de {N}", "P", 6.8, GREY, "c")
    txt(c, W - MX, 26, "Grupo EnerMais", "P", 6, GREY, "r")


def _vazio(c, y, msg):
    return caixa_nota(c, y, msg)


def p_capa(c, n, N, ctx):
    c.setFillColor(NAVY); p = c.beginPath()
    p.moveTo(W * 0.80, H); p.lineTo(W, H); p.lineTo(W, 0); p.lineTo(W * 0.60, 0); p.close(); c.drawPath(p, fill=1, stroke=0)
    mk = ImageReader(str(ASSETS / "capa_marca_pale.png"))
    c.saveState(); c.setFillAlpha(0.10); c.drawImage(mk, W * 0.66, 60, width=250, height=250 * 1409 / 983, mask="auto"); c.restoreState()
    rect(c, 0, H - 4, W * 0.80, 4, fill=NAVY)
    g = ImageReader(str(ASSETS / "GRUPO.png")); gw, gh = g.getSize(); lw_ = 215
    c.drawImage(g, MX + 8, H - 330, width=lw_, height=lw_ * gh / gw, mask="auto")
    rect(c, MX + 8, 405, 52, 3, fill=ORANGE)
    txt(c, MX + 8, 372, "Painel", "PB", 27, NAVY); txt(c, MX + 8, 342, "EnerMais", "PB", 27, NAVY)
    txt(c, MX + 8, 312, "Resultado, obras, administração e pessoas", "P", 9.5, GREY)
    txt(c, MX + 8, 297, "Referência: " + _mes_extenso(ctx["mes"]), "P", 9.5, GREY)
    rect(c, MX + 8, 238, 232, 24, fill=ORANGE, r=12)
    txt(c, MX + 8 + 116, 246.5, "MÊS · " + _rot_mes(ctx["mes"]), "PB", 7.6, WHITE, "c")
    txt(c, MX + 8, 70, "Informações do Sienge (API) e dos arquivos importados no painel, conferidas pela contabilidade.", "P", 6.4, GREY)
    txt(c, MX + 8, 26, _Estado.status, "PB", 6, ORANGE)


def p_resumo(c, n, N, ctx):
    _moldura(c, n, N, "Resumo do mês", ctx)
    y = titulo(c, TOPY, "Resumo do mês", _mes_extenso(ctx["mes"]) + " · " + ctx["dre"]["origem"])
    v = ctx["dre"]["valores"]
    rb, rl = v["01"], v["03"]
    kw = (CW - 3 * 10) / 4
    cards = [("Receita bruta", mm(rb), "linha 01 do DRE", False), ("Receita líquida", mm(rl), "após deduções", False),
             ("Lucro bruto", mm(v["05"]), "margem de contribuição " + _pc(rl and v["05"] / rl if abs(rl) > 0.005 else None), False),
             ("Lucro líquido", mm(v["11"]), "margem líquida " + _pc(v["11"] / rl if abs(rl) > 0.005 else None), True)]
    for i, (r_, val, sub, dark) in enumerate(cards):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=dark)
    y -= 74
    cards2 = [("EBITDA (lucro operacional)", mm(v["07"]), "antes do resultado financeiro"), ("Custos diretos", mm(v["04"]), "obras (04)"),
              ("Despesas administrativas", mm(v["06"]), "ADM central (06)"), ("Após investimentos", mm(v["14"]), "linha 14 do DRE")]
    for i, (r_, val, sub) in enumerate(cards2):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub)
    y -= 84
    y = secao(c, y, "Receita bruta mês a mês")
    serie = ctx["serie"][-12:]
    if len(serie) >= 2:
        unidade(c, W - MX, y + 2)
        barras(c, MX + 6, y - 150, CW - 12, 130, [_rot_mes(x["mes"]) for x in serie], [x["receita"] for x in serie], fmt=lambda v_: mmn(v_, 1), size=6)
        y -= 176
        marcados = sum(1 for x in serie if x["fonte"].startswith("API"))
        if marcados:
            y = caixa_nota(c, y, f"{marcados} mês(es) do gráfico vêm da reconstrução pela API (ainda sem DRE oficial importado ou confirmado) e podem mudar quando forem conferidos.")
    else:
        y = _vazio(c, y, "Ainda não há meses suficientes para mostrar a evolução da receita.")
    d = ctx["dre"]
    if d["manuais"]:
        y = caixa_nota(c, y, "Linhas do DRE ajustadas à mão (com observação registrada): " + ", ".join(d["manuais"]) + ".")
    if d["quem"]:
        txt(c, MX, y - 4, f"DRE confirmado por {d['quem']} em {d['quando']:%d/%m/%Y}." if d["quando"] else f"DRE confirmado por {d['quem']}.", "P", 7, GREY)


def p_dre(c, n, N, ctx):
    _moldura(c, n, N, "DRE gerencial", ctx)
    d = ctx["dre"]
    y = titulo(c, TOPY, "DRE gerencial do mês", d["origem"])
    rb = d["valores"]["01"]
    rows = []
    for cod, nome, val in d["linhas"]:
        pai = "." not in cod
        tipo = "tot" if cod in ("11", "14") else ("sub" if pai else "norm")
        fonte = d["fontes"].get(cod, "") if not pai else ""
        rows.append((tipo, [cod, nome, (fnum(val, 2), NEG_TXT) if neg(val) and tipo != "tot" else fnum(val, 2),
                            _pc(val / rb) if abs(rb) > 0.005 and pai else "", fonte]))
    cols = [(38, "l"), (255, "l"), (110, "r"), (62, "r"), (50, "l")]
    y = tabela(c, MX, y, cols, ["Linha", "Descrição", "Valor (R$)", "% rec. bruta", "Fonte"], rows, rh=14.2, fs=7.2)
    y -= 12
    caixa_nota(c, y, "Sinais: receitas positivas, deduções e custos negativos. Fonte = de onde veio cada linha na confirmação da contabilidade "
                     "(API do Sienge, PDF do DRE oficial ou ajuste manual com observação).")


def p_obras(c, n, N, ctx):
    _moldura(c, n, N, "Obras", ctx)
    ob = ctx["obras"]
    y = titulo(c, TOPY, "Resultado por obra", "DRE oficial do Sienge · BDI real = receita bruta − custos diretos")
    if not ob:
        _vazio(c, y, "Falta o DRE oficial em PDF deste mês (aba Importações (V2) do painel). Importe o arquivo e gere o relatório de novo.")
        return
    t = ob["total"]
    kw = (CW - 3 * 10) / 4
    for i, (r_, val, sub) in enumerate([("Receita bruta", mm(t["receita"]), "todas as obras"), ("Custos diretos", mm(t["custo"]), "obras"),
                                        ("BDI real", mm(t["bdi"]), "receita − custos"), ("Margem de contribuição", _pc(t["margem"]), "BDI ÷ receita")]):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=(i == 3))
    y -= 78
    folha = bool(ob.get("colab"))
    cols = [(38, "l"), (155, "l"), (72, "r"), (72, "r"), (72, "r"), (46, "r"), (60, "r")] if folha else [(44, "l"), (191, "l"), (80, "r"), (80, "r"), (80, "r"), (40, "r")]
    head = ["Obra", "Nome", "Receita", "Custos", "BDI real", "Margem"] + (["Colab. CLT"] if folha else [])
    linhas = ob["linhas"][:34]
    rows = [("norm", [l["obra"], l["nome"][:34], fnum(l["receita"]), fnum(l["custo"]), (fnum(l["bdi"]), NEG_TXT) if neg(l["bdi"]) else fnum(l["bdi"]), _pc(l["margem"])]
            + ([str(ob["colab"].get(l["obra"], 0))] if folha else [])) for l in linhas]
    rows.append(("tot", ["", "Total", fnum(t["receita"]), fnum(t["custo"]), fnum(t["bdi"]), _pc(t["margem"])] + ([str(sum(ob["colab"].values()))] if folha else [])))
    y = tabela(c, MX, y, cols, head, rows, rh=12.6, fs=6.9)
    if len(ob["linhas"]) > len(linhas):
        txt(c, MX, y - 10, f"+ {len(ob['linhas']) - len(linhas)} obra(s) menores na tela do painel (esta página mostra as {len(linhas)} primeiras).", "P", 6.6, GREY)
        y -= 14
    y -= 8
    if y > 150:
        xs = [MX, MX + CW / 2 + 6]
        for x_, tit, itens in ((xs[0], "5 obras com maior BDI", ob["top_lucro"]), (xs[1], "5 obras com maior prejuízo", ob["top_prejuizo"])):
            txt(c, x_, y, tit, "PB", 8.5, NAVY)
            yy = y - 14
            if not itens:
                txt(c, x_, yy, "Nenhuma obra com BDI negativo.", "P", 7, GREY)
            for l in itens[:5]:
                txt(c, x_, yy, f"{l['obra']} · {l['nome'][:22]}", "P", 7, GREY)
                txt(c, x_ + CW / 2 - 12, yy, fnum(l["bdi"]), "PB", 7, NEG_TXT if neg(l["bdi"]) else NAVY, "r")
                yy -= 12


def p_adm(c, n, N, ctx):
    _moldura(c, n, N, "Administração", ctx)
    a = ctx["adm"]
    y = titulo(c, TOPY, "Administração central", "Despesas pagas nas unidades ADM e orçado × realizado")
    if not a:
        _vazio(c, y, "Falta sincronizar as contas pagas do mês e/ou importar o Orçamento ADM (aba Importações (V2)).")
        return
    r = a["resumo"]
    if r:
        kw = (CW - 2 * 10) / 3
        for i, (r_, val, sub) in enumerate([("Pago nas unidades ADM", mm(r["total"]), "sem pessoal, encargos e transferências"), ("Credores no mês", str(r["n_credores"]), "com pagamento"),
                                            ("Outros credores/Dir", mm(r["outros"]["valor"]), "fora do ranking")]):
            kpi(c, MX + i * (kw + 10), y, kw, 58, r_, val, sub)
        y -= 72
        meio = (CW - 18) / 2
        y1 = lista_barras(c, MX, y, meio, "Por grupo de despesa", [(g["nome"], g["valor"]) for g in r["por_grupo"][:6] if g["valor"] > 0] or [("–", 1)],
                          max(sum(g["valor"] for g in r["por_grupo"][:6] if g["valor"] > 0), 1), rot_w=95)
        y2 = lista_barras(c, MX + meio + 18, y, meio, "Maiores contas", [(g["nome"], g["valor"]) for g in r["top_contas"][:6] if g["valor"] > 0] or [("–", 1)],
                          max(sum(g["valor"] for g in r["top_contas"][:6] if g["valor"] > 0), 1), rot_w=95)
        y = min(y1, y2) - 6
    o = a["orcamento"]
    if o:
        y = secao(c, y, "Orçamento ADM: orçado × realizado")
        kw = (CW - 3 * 10) / 4
        tot = o["total"]
        for i, (r_, val, sub) in enumerate([("Orçado", mm(tot["orcado"]), "mês"), ("Realizado", mm(tot["realizado"]), "mês"),
                                            ("Desvio", mm(tot["desvio"], 2, True), "realizado − orçado"), ("Desvio %", _pc(tot["desvio_pct"]), "positivo = gastou mais")]):
            kpi(c, MX + i * (kw + 10), y, kw, 58, r_, val, sub, dark=(i == 2))
        y -= 70
        ac = a.get("acumulado")
        if ac:
            txt(c, MX, y, f"Acumulado do ano: orçado {mm(ac['total']['orcado'])} · realizado {mm(ac['total']['realizado'])} · desvio {mm(ac['total']['desvio'], 2, True)} ({_pc(ac['total']['desvio_pct'])}).", "P", 7.2, GREY)
            y -= 16
        serie = a["serie_orc"]
        if len(serie) > 1 and y > 190:
            y = secao(c, y, "Desvio mês a mês (R$ MM)")
            barras(c, MX + 6, y - 110, CW - 12, 92, [_rot_mes(x["mes"]) for x in serie], [x["desvio"] for x in serie], fmt=lambda v_: mmn(v_, 2), size=5.8)
            y -= 134
    else:
        _vazio(c, y, "Orçamento ADM deste mês não importado: o orçado × realizado aparece depois de importar o PDF na aba Importações (V2).")


def p_pessoas(c, n, N, ctx):
    _moldura(c, n, N, "Pessoas", ctx)
    p = ctx["pessoas"]
    y = titulo(c, TOPY, "Pessoas e folha (CLT)", "Recibos de pagamento importados")
    if not p:
        _vazio(c, y, "Faltam os PDFs de recibos da folha deste mês (aba Importações (V2)).")
        return
    fo = p["folha"]; t = fo["total"]
    kw = (CW - 3 * 10) / 4
    for i, (r_, val, sub) in enumerate([("Colaboradores CLT", str(t["colab"]), "nos recibos"), ("Salários", mm(t["salarios"]), "horas normais"),
                                        ("Horas extras + DSR", mm(t["hora_extra"] + t["dsr_he"]), "HE 50 a 110% + DSR"), ("HE + DSR ÷ salários", _pc(t["he_pct"]), "peso das horas extras")]):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=(i == 3))
    y -= 78
    cols = [(120, "l"), (50, "r"), (90, "r"), (90, "r"), (65, "r"), (100, "r")]
    rows = [("norm", [e["empresa"], str(e["colab"]), fnum(e["salarios"]), fnum(e["hora_extra"] + e["dsr_he"]), _pc(e["he_pct"]), fnum(e["custo"])]) for e in fo["por_empresa"]]
    y = tabela(c, MX, y, cols, ["Empresa", "Colab.", "Salários", "HE + DSR", "HE ÷ sal.", "Custo (proventos + FGTS)"], rows, rh=13)
    y -= 24
    obras = sorted(fo["por_obra"].values(), key=lambda o: -o["colab"])[:12]
    if obras:
        y = secao(c, y, "Colaboradores por obra (12 maiores)")
        cols = [(44, "l"), (170, "l"), (45, "r"), (85, "r"), (85, "r"), (86, "r")]
        rows = [("norm", [o["codigo"], o["nome"][:36], str(o["colab"]), fnum(o["salarios"]), fnum(o["hora_extra"] + o["dsr_he"]), _pc(o["he_pct"])]) for o in obras]
        y = tabela(c, MX, y, cols, ["Obra", "Nome", "Colab.", "Salários", "HE + DSR", "HE ÷ sal."], rows, rh=12.6, fs=6.9)
        y -= 14
    sf = p["serie"]
    if len(sf) >= 2 and y > 170:
        y = secao(c, y, "HE + DSR ÷ salários, mês a mês (%)")
        barras(c, MX + 6, y - 100, CW - 12, 84, [_rot_mes(x["mes"]) for x in sf], [round(x["he_pct"] * 100, 1) for x in sf], fmt=lambda v_: fnum(v_, 1), size=6)
        y -= 124
    if y > 90:
        caixa_nota(c, y, "Salários = evento 1 (horas normais). Horas extras = eventos de HE 50/60/80/100/110% mais DSR sobre HE. Custo = proventos + FGTS do mês "
                         "(não inclui INSS patronal, férias/13º provisionados nem PJ).")


def p_notas(c, n, N, ctx):
    _moldura(c, n, N, "Notas e limitações", ctx)
    y = titulo(c, TOPY, "Notas e limitações deste rascunho")
    itens = ["Este PDF é um RASCUNHO: o layout está sendo validado e pode mudar. Os números são os mesmos das abas do painel (nenhum cálculo novo).",
             "O DRE usa a confirmação da contabilidade quando existe; sem ela, mostra o DRE oficial importado ou a reconstrução pela API, sempre identificando a origem.",
             "Edições do painel valem para dados importados e resultados gerados; não alteram o que vem da API do Sienge.",
             "Regras marcadas como proposta (aba Regras) ainda aguardam confirmação da contabilidade; INSS/FGTS pela guia e títulos desfeitos/multas AEJ estão em validação.",
             "Pessoas: custo da folha não inclui PJ, INSS patronal nem provisões de férias e 13º."]
    for a in ctx["avisos"]:
        itens.append("Atenção na montagem do relatório: " + a + " (a seção correspondente pode estar incompleta).")
    for it in itens:
        y = para(c, "• " + it, MX + 6, y, CW - 12, size=8, lead=12, gap=5)


PAGINAS = [p_capa, p_resumo, p_dre, p_obras, p_adm, p_pessoas, p_notas]


def gerar_pdf_painel(ctx: dict, status: str = "RASCUNHO", gerado_em: str = "") -> bytes:
    """PDF (bytes) do Painel EnerMais para o mes de ctx['mes']. Pagina que nao puder ser desenhada vira aviso, nunca derruba o relatorio."""
    R._registrar_fontes()
    with R._LOCK:
        _Estado.status = status + (f" · gerado em {gerado_em}" if gerado_em else "")
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(W, H), invariant=1)
        c.setTitle(f"Painel EnerMais — {_rot_mes(ctx['mes'])}"); c.setAuthor("Grupo EnerMais — GDF"); c.setSubject(status)
        N = len(PAGINAS)
        for i, fn in enumerate(PAGINAS, 1):
            try:
                fn(canvas.Canvas(io.BytesIO(), pagesize=(W, H), invariant=1), i, N, ctx)       # ensaio
                fn(c, i, N, ctx)
            except Exception as exc:                                                             # noqa: BLE001
                _moldura(c, i, N, "Página indisponível", ctx)
                caixa_nota(c, TOPY, f"Esta página não pôde ser desenhada ({type(exc).__name__}). Os dados dela continuam na tela do painel.")
            c.showPage()
        c.save()
        return buf.getvalue()
