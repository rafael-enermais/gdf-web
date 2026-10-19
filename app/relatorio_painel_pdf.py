# -*- coding: utf-8 -*-
"""GDF V2 - PDF do Painel EnerMais (RASCUNHO: o layout ainda depende de confirmacao do Rafael/contabilidade e pode mudar).
Reaproveita o padrao visual dos demonstrativos (Poppins, navy/laranja, quadros de KPI, tabelas e barras de relatorio_pdf.py).
O PDF e' gerado em memoria (bytes); nada e' gravado em disco. Cada pagina sem dado vira um aviso ("falta importar X"), nunca estoura erro.
Nenhum calculo novo aqui: os numeros vem das mesmas funcoes de painel_db usadas nas abas do painel."""
from __future__ import annotations

import io

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import historico as HIST
import relatorio_pdf as R
from relatorio_fmt import fnum, mm, mmn, neg, pct
from relatorio_pdf import (ASSETS, BLUES, calc_levels, cascata, BORDER, CW, GREY, GREY_BG, H, MX, NAVY, NEG_TXT, ORANGE, W, WHITE, barras, caixa_nota, hline, kpi,
                           lista_barras, para, rect, secao, tabela, titulo, txt, unidade)

TOPY = H - 84
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _rot_mes(m: str) -> str:
    return f"{m[5:]}/{m[:4]}"


def _mes_extenso(m: str) -> str:
    return f"{_MESES[int(m[5:]) - 1]} de {m[:4]}"


def _pc(v) -> str:
    return pct(v, 1) if v is not None else "–"


def _nomes_obras(conn) -> dict:
    """{codigo_obra: nome completo} do de-para de centros de custo (o mais frequente por codigo); sem a tabela devolve {}."""
    out: dict = {}
    for sql in ("SELECT codigo_obra, obra_nome FROM pnl_centro_grupo WHERE codigo_obra IS NOT NULL AND obra_nome IS NOT NULL GROUP BY 1, 2 ORDER BY count(*) DESC, 2",
                "SELECT codigo_obra, obra_nome FROM pnl_folha_depto_obra WHERE codigo_obra IS NOT NULL AND obra_nome IS NOT NULL GROUP BY 1, 2 ORDER BY count(*) DESC, 2"):
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                for cod, nome in cur.fetchall():
                    out.setdefault(cod, nome.strip())
        except Exception:                                       # noqa: BLE001
            try:
                conn.rollback()
            except Exception:                                   # noqa: BLE001
                pass
    return out


# ------------------------------------------------------------------ montagem dos dados (usa so as funcoes ja existentes do painel)
def montar_ctx(conn, mes: str, gerado_em: str = "") -> dict:
    """Junta tudo que o PDF mostra para o mes 'AAAA-MM'. Parte que nao tem dado vira None (a pagina explica o que falta)."""
    import painel_db as P

    ctx = {"mes": mes, "gerado_em": gerado_em, "dre": None, "serie": [], "obras": None, "proj": None, "adm": None, "desp": None, "pessoas": None, "hist": None, "avisos": []}

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
    import datetime as _dt
    _hoje = _dt.date.today()
    ctx["serie"] = P.receita_mensal(conn, mes_atual=f"{_hoje.year}-{_hoje.month:02d}")      # mes em andamento fica de fora (incompleto)

    # --- Obras (DRE oficial importado)
    try:
        if mes in P.meses_com_dre(conn):
            ob = P.obras_do_dre(conn, mes)
            folha = P.folha_do_mes(conn, mes)
            ob["colab"] = P.colab_por_linha_obras(ob["linhas"], folha) if folha else {}
            extra = P.nomes_obras_extra(conn)
            ob["nome_cheio"] = _nomes_obras(conn)
            ctx["obras"] = ob
            proj = P.projecao_do_mes(conn, mes)
            if proj:
                ctx["proj"] = P.projecao_x_realizado(proj, ob, extra)
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
                adm["linhas"] = linhas                                   # para o detalhe (unidade > credor > conta) do Painel da Diretoria
        orc = P.orcamento_ativo(conn) if P.orcamento_instalado(conn) else None
        if orc and mes in orc["meses"]:
            adm["orcamento"] = P.orcamento_resumo(conn, orc["id"], mes)
            adm["acumulado"] = P.orcamento_resumo(conn, orc["id"], mes, acumulado=True)
            adm["serie_orc"] = P.orcamento_serie_mensal(conn, orc["id"]) if hasattr(P, "orcamento_serie_mensal") else []
        if adm["resumo"] or adm["orcamento"]:
            ctx["adm"] = adm
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Administração: {type(exc).__name__}")

    # --- Despesas pagas no mes (mesma regra da aba Despesas)
    try:
        if P.meses_com_dados(conn):
            regras_d = P.regras_ativas(conn, "DESPESAS")
            linhas_d = P.despesas_do_mes(conn, mes, P.prefixos_excluidos(regras_d), sem_previsao=P.exclui_previsao(regras_d))
            if linhas_d:
                ctx["desp"] = {"linhas": linhas_d, "total": round(sum(l["valor"] for l in linhas_d), 2)}
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Despesas: {type(exc).__name__}")

    # --- Pessoas (recibos da folha)
    try:
        if mes in P.folha_meses(conn):
            ctx["pessoas"] = {"folha": P.folha_do_mes(conn, mes), "serie": [x for x in P.folha_serie(conn) if x["he_pct"] is not None]}
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Pessoas: {type(exc).__name__}")

    # --- Historico do ano (painel da contabilidade importado em Importacoes (V2)): acumulado, desvio mensal, recomposicao, HE e custos com pessoas
    try:
        h = HIST.ativo(conn)
        if h:
            ctx["hist"] = HIST.resumo(h)
            ctx["hist"]["arquivo"] = h["arquivo"]
    except Exception as exc:                                    # noqa: BLE001
        ctx["avisos"].append(f"Histórico: {type(exc).__name__}")
    return ctx


# ------------------------------------------------------------------ paginas
class _Estado:
    status = "RASCUNHO"


def _moldura(c, n, N, secao_nome, ctx):
    wm = ImageReader(str(ASSETS / "torre_watermark.png"))
    c.drawImage(wm, 6, 28, width=340, height=343, mask="auto")                      # torres alinhadas a esquerda, como no EGC
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
    p.moveTo(W * 0.80, H); p.lineTo(W, H); p.lineTo(W, 0); p.lineTo(W * 0.72, 0); p.close(); c.drawPath(p, fill=1, stroke=0)   # faixa estreita, como no EGC
    mk = ImageReader(str(ASSETS / "capa_marca_pale.png"))
    c.saveState(); c.setFillAlpha(0.45); c.drawImage(mk, W * 0.835, 40, width=70, height=70 * 1409 / 983, mask="auto"); c.restoreState()   # marca pequena no rodape da faixa
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


def _nome_obra(l, nome_cheio):
    """Nome da obra para o PDF: o do de-para (completo) quando existe; senao o do DRE (so o cliente)."""
    cheio = (nome_cheio or {}).get(l["obra"]) or ""
    return cheio or (l.get("nome") or "")


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
    nc = ob.get("nome_cheio", {})
    rows = [("norm", [l["obra"], _nome_obra(l, nc)[:34], fnum(l["receita"]), fnum(l["custo"]), (fnum(l["bdi"]), NEG_TXT) if neg(l["bdi"]) else fnum(l["bdi"]), _pc(l["margem"])]
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
                txt(c, x_, yy, f"{l['obra']} · {_nome_obra(l, ob.get('nome_cheio', {}))[:24]}", "P", 7, GREY)
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


def p_resultado(c, n, N, ctx):
    _moldura(c, n, N, "Resultado", ctx)
    y = titulo(c, TOPY, "Receita − Custo = BDI − Administração = Resultado", _mes_extenso(ctx["mes"]))
    ob, a = ctx["obras"], ctx["adm"]
    if not ob or not a or not a.get("orcamento"):
        _vazio(c, y, "Esta página precisa do DRE oficial por obra (para receita, custo e BDI) e do Orçamento ADM (para a administração realizada) do mês. "
                     "Importe o que falta na aba Importações (V2).")
        return
    rec, cus, bdi = ob["total"]["receita"], ob["total"]["custo"], ob["total"]["bdi"]
    adm = a["orcamento"]["total"]["realizado"]
    res = round(bdi - adm, 2)
    kw = (CW - 4 * 10) / 5
    for i, (r_, val, sub) in enumerate([("Receita", mm(rec), "DRE oficial"), ("Custo direto", mm(-cus if cus < 0 else cus), "obras"),
                                        ("BDI", mm(bdi), "receita − custo"), ("Administração", mm(adm), "realizado do mês (orçamento ADM)"),
                                        ("Resultado", mm(res), "BDI − administração")]):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=(i == 4), vsize=11.5)
    y -= 84
    y = secao(c, y, "Do faturamento ao resultado (R$ MM)")
    et = [("Receita", rec, "total"), ("Custo direto", -abs(cus), "delta"), ("BDI", bdi, "total"), ("Administração", -abs(adm), "delta"), ("Resultado", res, "final")]
    calc_levels(et)
    cascata(c, MX + 30, y - 190, CW - 60, 160, et, size=7)
    y -= 230
    ac = a.get("acumulado")
    if ac:
        y = caixa_nota(c, y, f"Administração no acumulado do ano (orçamento ADM): orçado {mm(ac['total']['orcado'])}, realizado {mm(ac['total']['realizado'])}, "
                             f"desvio {mm(ac['total']['desvio'], 2, True)} ({_pc(ac['total']['desvio_pct'])}).")
    caixa_nota(c, y, "Receita e custo vêm do DRE oficial do Sienge (somando todas as obras); a administração é o realizado do Orçamento ADM. "
                     "O acumulado do ano e o desvio mensal estão na página seguinte ao Resultado do mês, quando o histórico do painel da contabilidade está importado.")


def p_proj(c, n, N, ctx):
    _moldura(c, n, N, "Previsto × realizado", ctx)
    y = titulo(c, TOPY, "Previsto × realizado por obra", "Projeção de receitas × DRE oficial do mês")
    cm = ctx.get("proj")
    if not cm:
        _vazio(c, y, "Falta a projeção de receitas do mês (planilha xlsx) e/ou o DRE oficial. Importe na aba Importações (V2).")
        return
    kw = (CW - 3 * 10) / 4
    dv = cm["receita_real_total"] - cm["receita_proj_total"]
    for i, (r_, val, sub) in enumerate([("Receita projetada", mm(cm["receita_proj_total"]), "planilha de projeção"), ("Receita real", mm(cm["receita_real_total"]), "DRE oficial"),
                                        ("Desvio", mm(dv, 2, True), _pc(dv / cm["receita_proj_total"]) if abs(cm["receita_proj_total"]) > 0.005 else "–"), ("BDI previsto", mm(cm["total"]["bdi_proj"]), "receita − custo previsto")]):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=(i == 2))
    y -= 78
    cols = [(130, "l"), (62, "r"), (62, "r"), (62, "r"), (44, "r"), (60, "r"), (60, "r"), (35, "r")]
    rows = [("norm", [x["obra_proj"][:28], fnum(x["receita_proj"], 0), fnum(x["receita_real"], 0), (fnum(x["desvio"], 0), NEG_TXT) if neg(x["desvio"]) else fnum(x["desvio"], 0),
                      _pc(x["desvio_pct"]), fnum(x["bdi_proj"], 0), fnum(x["bdi_real"], 0), x["codigo"]]) for x in cm["linhas"][:30]]
    y = tabela(c, MX, y, cols, ["Obra (projeção)", "Receita proj.", "Receita real", "Desvio", "Desvio %", "BDI previsto", "BDI real", "Cód."], rows, rh=12.6, fs=6.8)
    y -= 10
    if cm["sem_correspondencia"]:
        y = caixa_nota(c, y, "Obras da projeção sem correspondência única no DRE: " + "; ".join(f"{o['obra']} ({fnum(o['receita'], 0)})" for o in cm["sem_correspondencia"][:6]) + ".")
    caixa_nota(c, y, "Custo previsto e BDI previsto vêm da própria planilha de projeção; BDI real = receita bruta − custos diretos do DRE oficial.")


def p_despesas(c, n, N, ctx):
    _moldura(c, n, N, "Despesas", ctx)
    y = titulo(c, TOPY, "Despesas pagas no mês", "Mesmas regras da aba Despesas: sem pessoal, encargos e transferências; sem documentos de previsão")
    d = ctx.get("desp")
    if not d:
        _vazio(c, y, "Falta sincronizar as contas pagas do mês (aba Sincronizar com o Sienge).")
        return
    L, tot = d["linhas"], d["total"]
    top5 = sum(l["valor"] for l in L[:5])
    kw = (CW - 2 * 10) / 3
    for i, (r_, val, sub) in enumerate([("Pago no mês", mm(tot), "contas de despesa"), ("Top 5 do mês", _pc(top5 / tot) if tot else "–", mm(top5)), ("Contas com movimento", str(len(L)), "no plano financeiro")]):
        kpi(c, MX + i * (kw + 10), y, kw, 58, r_, val, sub, dark=(i == 0))
    y -= 76
    y = lista_barras(c, MX, y, CW, "Top 5 do mês", [(f"{l['plano_cod']} · {l['plano_nome']}"[:46], l["valor"]) for l in L[:5]], max(top5, 1), rot_w=230)
    y -= 6
    cols = [(60, "l"), (285, "l"), (100, "r"), (70, "r")]
    rows = [("norm", [l["plano_cod"], (l["plano_nome"] or "")[:60], fnum(l["valor"]), _pc(l["valor"] / tot) if tot else "–"]) for l in L[:12]]
    y = secao(c, y, "12 maiores contas do mês")
    y = tabela(c, MX, y, cols, ["Conta", "Nome", "Valor (R$)", "% do mês"], rows, rh=13, fs=7)
    y -= 10
    caixa_nota(c, y, "O acumulado jan–set das contas aparece quando o histórico dos meses anteriores estiver carregado no painel. INSS e FGTS ficam na parte de Pessoas.")


def p_adm2(c, n, N, ctx):
    _moldura(c, n, N, "Administração — credores", ctx)
    a = ctx["adm"]
    y = titulo(c, TOPY, "Administração: unidades e credores", "Pagamentos do mês nos centros de custo ADM")
    r = a["resumo"] if a else None
    if not r:
        _vazio(c, y, "Falta sincronizar as contas pagas do mês.")
        return
    un = [(g["nome"][:34], g["valor"]) for g in r["por_unidade"][:8] if g["valor"] > 0]
    if un:
        y = lista_barras(c, MX, y, CW, "Por unidade de negócio", un, max(sum(v for _, v in un), 1), rot_w=200)
        y -= 6
    rk = r["ranking"][:15]
    cols = [(330, "l"), (110, "r"), (75, "r")]
    rows = [("norm", [g["credor"][:60], fnum(g["valor"]), _pc(g["pct"])]) for g in rk]
    rows.append(("sub", ["Outros credores/Dir (fora do ranking)", fnum(r["outros"]["valor"]), _pc(r["outros"]["pct"])]))
    y = secao(c, y, "Principais credores do mês")
    y = tabela(c, MX, y, cols, ["Credor", "Valor (R$)", "% do total"], rows, rh=13, fs=7)



def p_pessoas(c, n, N, ctx):
    _moldura(c, n, N, "Pessoas", ctx)
    p = ctx["pessoas"]
    y = titulo(c, TOPY, "Pessoas e folha (CLT)", "Recibos de pagamento importados")
    if not p:
        _vazio(c, y, "Faltam os PDFs de recibos da folha deste mês (aba Importações (V2)).")
        return
    fo = p["folha"]; t = fo["total"]
    kw = (CW - 3 * 10) / 4
    for i, (r_, val, sub) in enumerate([("Colaboradores CLT", str(t["colab"]), "nos recibos"), ("Remuneração", mm(t["base_he"]), "base da hora extra"),
                                        ("Horas extras + DSR", mm(t["hora_extra"] + t["dsr_he"]), "HE 50 a 110% + DSR"), ("HE + DSR ÷ remuneração", _pc(t["he_pct"]), "peso das horas extras")]):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=(i == 3))
    y -= 78
    cols = [(120, "l"), (50, "r"), (90, "r"), (90, "r"), (65, "r"), (100, "r")]
    rows = [("norm", [e["empresa"], str(e["colab"]), fnum(e["base_he"]), fnum(e["hora_extra"] + e["dsr_he"]), _pc(e["he_pct"]), fnum(e["custo"])]) for e in fo["por_empresa"]]
    y = tabela(c, MX, y, cols, ["Empresa", "Colab.", "Remuneração", "HE + DSR", "HE ÷ rem.", "Custo (proventos + FGTS)"], rows, rh=13)
    y -= 24
    obras = sorted(fo["por_obra"].values(), key=lambda o: -o["colab"])[:12]
    if obras:
        y = secao(c, y, "Colaboradores por obra (12 maiores)")
        cols = [(44, "l"), (170, "l"), (45, "r"), (85, "r"), (85, "r"), (86, "r")]
        rows = [("norm", [o["codigo"], o["nome"][:36], str(o["colab"]), fnum(o["base_he"]), fnum(o["hora_extra"] + o["dsr_he"]), _pc(o["he_pct"])]) for o in obras]
        y = tabela(c, MX, y, cols, ["Obra", "Nome", "Colab.", "Remuneração", "HE + DSR", "HE ÷ rem."], rows, rh=12.6, fs=6.9)
        y -= 14
    sf = HIST.serie_he_combinada(ctx.get("hist"), p["serie"])             # meses do histórico da contabilidade + meses com folha no app
    if len(sf) >= 2 and y > 170:
        y = secao(c, y, "HE + DSR ÷ remuneração, mês a mês (%)")
        barras(c, MX + 6, y - 100, CW - 12, 84, [_rot_mes(x["mes"]) for x in sf], [round(x["he_pct"] * 100, 1) for x in sf], fmt=lambda v_: fnum(v_, 1), size=6)
        y -= 124
    if y > 90:
        caixa_nota(c, y, "Remuneração (base da HE, definição da contabilidade) = proventos que não são HE nem DSR s/ HE, menos todos os descontos do recibo (remuneração líquida). Horas extras = eventos de HE 50/60/80/100/110% mais DSR sobre HE. Custo = proventos + FGTS do mês "
                         "(não inclui INSS patronal, férias/13º provisionados nem PJ).")


def _fk(v) -> str:
    """Valor em R$ mil (sem decimais) para as tabelas largas do historico."""
    return fnum(v / 1000.0, 0)


def p_ano(c, n, N, ctx):
    _moldura(c, n, N, "Acumulado do ano", ctx)
    h = ctx.get("hist")
    y = titulo(c, TOPY, "Acumulado do ano e desvio mensal", "Realizado × previsto, de janeiro ao mês do painel")
    if not h:
        _vazio(c, y, "Falta importar o histórico do painel da contabilidade (HTML) na aba Importações (V2): dele vêm o acumulado jan–set e o desvio mensal.")
        return
    a = h["acumulado"]
    kw = (CW - 4 * 10) / 5
    for i, (r_, val, sub) in enumerate([("Receita", mm(a["rec"]), "acumulado do ano"), ("Custo direto", mm(a["cus"]), "obras"), ("BDI", mm(a["bdi"]), "receita − custo"),
                                        ("Administração", mm(a["adm"]), "acumulado do ano"), ("Resultado", mm(a["res"]), "BDI − administração")]):
        kpi(c, MX + i * (kw + 10), y, kw, 62, r_, val, sub, dark=(i == 4), vsize=11.5)
    y -= 84
    et = [("Receita", a["rec"], "total"), ("Custo direto", -abs(a["cus"]), "delta"), ("BDI", a["bdi"], "total"), ("Administração", -abs(a["adm"]), "delta"), ("Resultado", a["res"], "final")]
    calc_levels(et)
    y = secao(c, y, "Do faturamento ao resultado, acumulado do ano (R$ MM)")
    cascata(c, MX + 30, y - 150, CW - 60, 124, et, size=7)
    y -= 176
    ml = [m["rotulo"] for m in h["desvio_meses"]]
    y = secao(c, y, "Desvio mensal: realizado − previsto (R$ mil)")
    wl = 100
    wc = (CW - wl) / (len(ml) + 1)
    cols = [(wl, "l")] + [(wc, "r")] * (len(ml) + 1)
    rows = []
    for nome, vals in h["desvio_linhas"].items():
        acu = h["desvio_acumulado"].get({"Base-line (Receita)": "rec", "Custos": "cus", "BDI - Resultado": "bdi", "Despesas ADM": "adm", "Lucro do Período": "res"}.get(nome, ""), sum(vals))
        rows.append(("sub" if nome.startswith("Lucro") else "norm", [nome] + [_fk(v) for v in vals] + [_fk(acu)]))
    y = tabela(c, MX, y, cols, ["Linha"] + ml + ["Acum."], rows, rh=13, fs=6.4)
    y -= 22
    luc = h["desvio_linhas"].get("Lucro do Período")
    if luc and y > 150:
        y = secao(c, y, "Desvio do lucro do período, mês a mês (R$ MM)")
        barras(c, MX + 6, y - 86, CW - 12, 70, ml, [round(v / 1e6, 2) for v in luc], fmt=lambda v_: fnum(v_, 2), size=6)
        y -= 108
    caixa_nota(c, y, "Para custos e despesas ADM, valor positivo indica estouro (gasto acima do previsto); para receita e BDI, valor negativo indica abaixo do previsto. "
                     "Janeiro = desvio acumulado menos a soma de fevereiro ao mês do painel. Valores do histórico do painel da contabilidade (arquivo " + (h.get("arquivo") or "importado") + ").")


def p_recomp(c, n, N, ctx):
    _moldura(c, n, N, "Recomposição e custos com pessoas", ctx)
    h = ctx.get("hist")
    y = titulo(c, TOPY, "Recomposição out–dez e custos com pessoas", "Faturamento necessário e principais custos de pessoal")
    if not h:
        _vazio(c, y, "Falta importar o histórico do painel da contabilidade (HTML) na aba Importações (V2).")
        return
    rc = h["recomposicao"]
    if rc:
        y = secao(c, y, "Recomposição out–dez: faturamento necessário para cobrir o déficit acumulado de base-line")
        cols = [(120, "l"), (190, "r"), (205, "r")]
        rows = [("norm", [r["rotulo"], fnum(r["projecao"]), fnum(r["para_cobrir"])]) for r in rc]
        rows.append(("sub", ["Out–Dez", fnum(sum(r["projecao"] for r in rc)), fnum(sum(r["para_cobrir"] for r in rc))]))
        y = tabela(c, MX, y, cols, ["Mês", "Projeção (R$)", "Para cobrir o déficit (R$)"], rows, rh=13, fs=7.2)
        tp, tc = sum(r["projecao"] for r in rc), sum(r["para_cobrir"] for r in rc)
        if tp > 0:
            y = caixa_nota(c, y - 8, f"Distribuído proporcionalmente à projeção: o faturamento precisa ficar {_pc(tc / tp - 1)} acima da projeção em out–dez.")
        y -= 10
    pe = h["pessoas"]
    if pe:
        y = secao(c, y, "Custos prioritários com pessoas (valores pagos)")
        cols = [(255, "l"), (130, "r"), (130, "r")]
        rows = [("norm", [r["nome"][:52], fnum(r["mes"]), fnum(r["acumulado"])]) for r in pe[:14]]
        y = tabela(c, MX, y, cols, ["Custo", "No mês (R$)", "Acumulado do ano (R$)"], rows, rh=12.6, fs=7)
        y -= 8
    if y > 80:
        caixa_nota(c, y, "Valores do histórico do painel da contabilidade" + (f" (arquivo {h['arquivo']})" if h.get("arquivo") else "") + ". O detalhe por colaborador não é guardado no app.")


def p_notas(c, n, N, ctx):
    _moldura(c, n, N, "Notas e limitações", ctx)
    y = titulo(c, TOPY, "Notas e limitações deste rascunho")
    itens = ["Este PDF é um RASCUNHO: o layout está sendo validado e pode mudar. Os números são os mesmos das abas do painel (nenhum cálculo novo).",
             "O DRE usa a confirmação da contabilidade quando existe; sem ela, mostra o DRE oficial importado ou a reconstrução pela API, sempre identificando a origem.",
             "Edições do painel valem para dados importados e resultados gerados; não alteram o que vem da API do Sienge.",
             "Regras confirmadas pela contabilidade em 19/10/2026: previsões fora das despesas, distrato e títulos desfeitos/multas AEJ fora; INSS/FGTS pela guia fica (a guia entra depois da emissão do PDF).",
             "Pessoas: custo da folha não inclui PJ, INSS patronal nem provisões de férias e 13º. A % de horas extras usa como base a remuneração (proventos que não são HE nem DSR s/ HE, menos todos os descontos: remuneração líquida), definição confirmada pela contabilidade em 20/10/2026; a diferença para o painel dela (~R$ 139 mil de proventos) vem dos recibos, que prevalecem.",
             "Histórico do ano (acumulado, desvio mensal, recomposição out–dez e custos com pessoas): vem do painel da contabilidade importado em Importações (V2); sem essa importação, as páginas explicam o que falta."]
    for a in ctx["avisos"]:
        itens.append("Atenção na montagem do relatório: " + a + " (a seção correspondente pode estar incompleta).")
    for it in itens:
        y = para(c, "• " + it, MX + 6, y, CW - 12, size=8, lead=12, gap=5)


PAGINAS = [p_capa, p_resumo, p_dre, p_resultado, p_obras, p_proj, p_despesas, p_adm, p_adm2, p_pessoas, p_ano, p_recomp, p_notas]


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
