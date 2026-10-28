# -*- coding: utf-8 -*-
"""GDF V2 - Painel da Diretoria: replica do painel da contabilidade (Resultado, Obras, Administracao, Despesas, Pessoas), interativo e so' de leitura.
Unica pagina do papel VISUALIZADOR. Cada aba abre com o resumo (formula / KPIs) e desce em detalhe ao clicar numa linha (conta -> credor -> obra).
Os dados vem do banco. O resultado fica guardado (cache de ate 30 min) e se renova SOZINHO quando o 'carimbo' do banco muda (carga do Sienge, upload,
regra ou de-para); o botao Atualizar agora limpa na hora (util logo depois de gerar algo). Nao grava nada. So' a aba aberta e' calculada."""
import datetime as dt
import time

import altair as alt
import pandas as pd
import streamlit as st

import acesso
import custos_obra_nivel as CON
import estilo
import diretoria_dados as DD
import diretoria_indicadores_ui as DI
import folha_pj_ui as FPU
import formatacao as F
import grupo_enermais as GE
import historico as HIST
import painel_db as P
import periodo as PER
import relatorio_painel_pdf as RPP
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape
from fuso import agora_br

NAVY, ORANGE, AZUL, CINZA = "#171C60", "#F99D20", "#5C6091", "#B9C3D4"
BOM, RUIM = "#1F8A55", "#C0392B"

_T0 = time.perf_counter()                                       # medidor de tempo da tela (aparece so' para quem edita, no rodape)
usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()


def _sem_latex(f):
    """O Streamlit trata '$...$' como formula: 'R$ 9,29 mi · custos R$ 9,36 mi' vira texto verde. Escapa o cifrao nos textos corridos (so' nesta pagina)."""
    def _f(body, *a, **k):
        return f(body.replace("$", "\\$") if isinstance(body, str) else body, *a, **k)
    return _f


_cap, _md, _info, _warn = _sem_latex(st.caption), _sem_latex(st.markdown), _sem_latex(st.info), _sem_latex(st.warning)


@st.cache_data(ttl=30, show_spinner=False)
def _carimbo(_conn) -> str:
    """Estado dos dados no banco (varias consultas ao banco, por isso guardado 30 s: cliques seguidos nao repetem). Faz parte da chave dos caches abaixo."""
    return P.carimbo_dados(_conn)


# Os resultados ficam guardados ate 30 min, mas valem so' enquanto o carimbo for o mesmo: carga do Sienge, upload ou regra nova -> recalcula sozinho.
@st.cache_data(ttl=1800, show_spinner="Atualizando os dados…")
def _ctx(_conn, mes: str, carimbo: str) -> dict:
    return RPP.montar_ctx(_conn, mes, agora_br().strftime("%d/%m/%Y %H:%M"))


@st.cache_data(ttl=1800, show_spinner=False)
def _meses(_conn, carimbo: str) -> list:
    return sorted(set(P.meses_com_dre(_conn)) | set(P.meses_confirmados(_conn)) | set(P.meses_com_dados(_conn)) | set(P.folha_meses(_conn)))


@st.cache_data(ttl=1800, show_spinner=False)
def _confirmados(_conn, carimbo: str) -> list:
    return P.meses_confirmados(_conn)


@st.cache_data(ttl=1800, show_spinner="Lendo as contas pagas do período…")
def _pagos(_conn, mes_ini: str, mes: str, carimbo: str):
    """Contas pagas de `mes_ini` ate o mes (credor, centro de custo, obra) + as contas excluidas das Despesas pelas regras. Devolve (linhas, prefixos_fora)."""
    regras = P.regras_ativas(_conn, "DESPESAS")
    linhas = DD.pagos_detalhe(_conn, mes_ini, mes, sem_previsao=P.exclui_previsao(regras))
    return DD.para_df(linhas), P.prefixos_excluidos(regras)                    # ja' como tabela (DataFrame): guardar/ler do cache e' ~10x mais rapido que lista de dicts


@st.cache_data(ttl=1800, show_spinner=False)
def _pj_mes(_conn, mes_ini: str, mes: str, carimbo: str) -> dict:
    """PJ do mes (contas pagas 'Salarios PJ'); guardado: o calculo nao se repete a cada clique."""
    return DD.pj_do_mes(_pagos(_conn, mes_ini, mes, carimbo)[0], mes)


@st.cache_data(ttl=1800, show_spinner=False)
def _pj_obra(_conn, mes_ini: str, mes: str, carimbo: str) -> list:
    return DD.pj_por_obra(_pagos(_conn, mes_ini, mes, carimbo)[0], mes)


@st.cache_data(ttl=1800, show_spinner=False)
def _credores_pj_nomes(_conn, mes_ini: str, mes: str, carimbo: str) -> set:
    return DD.credores_pj(_pagos(_conn, mes_ini, mes, carimbo)[0])


@st.cache_data(ttl=1800, show_spinner=False)
def _despesas(_conn, mes_ini: str, mes: str, carimbo: str) -> pd.DataFrame:
    """Contas pagas sem as contas excluidas das Despesas pelas regras (guardado)."""
    df, fora = _pagos(_conn, mes_ini, mes, carimbo)
    return DD.despesas_df(df, fora)


@st.cache_data(ttl=1800, show_spinner=False)
def _despesas_sem_pj(_conn, mes_ini: str, mes: str, carimbo: str) -> pd.DataFrame:
    """Despesas sem os credores que sao colaboradores PJ (eles ja' estao na lista de colaboradores)."""
    return DD.sem_credores(_despesas(_conn, mes_ini, mes, carimbo), _credores_pj_nomes(_conn, mes_ini, mes, carimbo))


@st.cache_data(ttl=1800, show_spinner=False)
def _pessoas_df(_conn, mes_ini: str, mes: str, carimbo: str) -> pd.DataFrame:
    return DD.pessoas_df(_pagos(_conn, mes_ini, mes, carimbo)[0])


@st.cache_data(ttl=1800, show_spinner=False)
def _pessoas_sem_grupo(_conn, mes_ini: str, mes: str, carimbo: str) -> pd.DataFrame:
    return DD.sem_grupo_enermais(_pessoas_df(_conn, mes_ini, mes, carimbo), _nucleos_grupo(_conn, carimbo))


@st.cache_data(ttl=1800, show_spinner=False)
def _folha_colaboradores(_conn, mes: str, carimbo: str) -> list:
    return P.folha_colaboradores(_conn, mes)


@st.cache_data(ttl=1800, show_spinner=False)
def _folha_pessoas(_conn, mes: str, carimbo: str) -> list:
    """Colaboradores CLT do mes com liquido, HE (horas e R$), canteiro, pensao e taxa assistencial (v0.49.0)."""
    return P.folha_pessoas_mes(_conn, mes)


@st.cache_data(ttl=1800, show_spinner=False)
def _termo_mes(_conn, m: str, carimbo: str):
    """Termos do Resultado de UM mes (DRE confirmado > API padrao; PDF so' antes da API; None onde nao ha dado). Guardado por mes: trocar o periodo reaproveita os meses ja' calculados."""
    return P.termos_do_mes(_conn, m)


def _termos_meses(_conn, meses_t: tuple, carimbo: str) -> list:
    return [_termo_mes(_conn, m, carimbo) for m in meses_t]


@st.cache_data(ttl=1800, show_spinner=False)
def _obras_aux(_conn, carimbo: str):
    """Apoio da tabela de obras (nomes extras e meses com obras), guardado."""
    return P.nomes_obras_extra(_conn), set(P.meses_com_obras(_conn))


@st.cache_data(ttl=1800, show_spinner="Somando as obras do mês…")
def _obras_mes(_conn, m: str, carimbo: str):
    """(tabela de obras SEM reagrupar, projecao x realizado) de UM mes, ou (None, None) se nao ha dado. A tabela vem da fonte do mes (API padrao; PDF so' se confirmado em PDF)."""
    extra, com_obras = _obras_aux(_conn, carimbo)
    ob_m = P.obras_do_mes(_conn, m) if m in com_obras else None
    px = None
    if ob_m:
        pj_ = P.projecao_do_mes(_conn, m)
        px = P.projecao_x_realizado(pj_, ob_m, extra) if pj_ else None
    return ob_m, px


def _obras_meses(_conn, meses_t: tuple, carimbo: str):
    return [_obras_mes(_conn, m, carimbo) for m in meses_t]


@st.cache_data(ttl=1800, show_spinner=False)
def _custos_nivel(_conn, mes_ini: str, mes: str, carimbo: str) -> list:
    """Linhas (obra, mes, conta, resultado) dos titulos emitidos no periodo, so' contas das 7 categorias de custo por obra (guardado)."""
    return P.custos_obra_linhas(_conn, mes_ini, mes)


@st.cache_data(ttl=1800, show_spinner=False)
def _nomes_obras(_conn, carimbo: str) -> dict:
    """{codigo da obra: nome completo} (de-para de centros de custo) — a mesma linguagem da aba Obras."""
    return RPP._nomes_obras(_conn)


@st.cache_data(ttl=1800, show_spinner=False)
def _nucleos_grupo(_conn, carimbo: str) -> list:
    return GE.nucleos_do_grupo(_conn)


@st.cache_data(ttl=1800, show_spinner=False)
def _fantasias(_conn, carimbo: str) -> dict:
    """{credor normalizado: nome fantasia} do cadastro de credores do Sienge (vazio se o SQL-30 / a atualizacao ainda nao foram feitos)."""
    return P.fantasia_por_credor(_conn)


@st.cache_data(ttl=1800, show_spinner=False)
def _outros_dir(_conn, carimbo: str) -> list:
    """Chaves (nomes) do grupo 'Outros credores/Dir' da Administracao."""
    return [c["chave"] for c in P.credor_grupo_ativos(_conn)] if P.credor_grupo_instalado(_conn) else []


@st.cache_data(ttl=1800, show_spinner=False)
def _demais_pj(_conn, carimbo: str) -> list:
    """Chaves (nomes) do grupo 'Demais colaboradores-PJ' (lista 'PJ do mes' da aba Pessoas)."""
    return [c["chave"] for c in P.credor_grupo_ativos(_conn, "DEMAIS_PJ")] if P.credor_grupo_instalado(_conn) else []


@st.cache_data(ttl=1800, show_spinner="Lendo a administração do período…")
def _adm_periodo(_conn, mes_ini: str, mes: str, carimbo: str):
    """Administracao no periodo: pagamentos das unidades ADM (mes de referencia e periodo todo) e orcado x realizado (mes, periodo e serie). None se nao ha nada."""
    linhas_mes, linhas_per = [], []
    if P.meses_com_dados(_conn) and P.centro_grupo_instalado(_conn):
        regras = P.regras_ativas(_conn, "DESPESAS")
        fora_adm = [p for p in P.prefixos_excluidos(regras) if p != "2.02.01"]          # o orcamento ADM inclui o pessoal ADM (2.02.01)
        sem_prev = P.exclui_previsao(regras)
        linhas_mes = P.adm_linhas(_conn, mes, mes, fora_adm, sem_previsao=sem_prev)
        linhas_per = P.adm_linhas(_conn, mes_ini, mes, fora_adm, sem_previsao=sem_prev) if mes_ini != mes else linhas_mes
    orc = P.orcamento_ativo(_conn) if P.orcamento_instalado(_conn) else None
    orc_mes = orc_per = None
    serie, serie_g = [], []
    if orc:
        meses_orc = [m for m in PER.meses_entre(mes_ini, mes) if m in orc["meses"]]
        if mes in orc["meses"]:
            orc_mes = P.orcamento_resumo(_conn, orc["id"], mes)
        if meses_orc:
            orc_per = P.orcamento_resumo(_conn, orc["id"], mes, acumulado=True, mes_ini=meses_orc[0])
        serie_todas = P.orcamento_serie_mensal(_conn, orc["id"])
        serie = [x for x in serie_todas if mes_ini <= x["mes"] <= mes]
        serie_g = [x for x in serie_todas if PER.somar_meses(mes, -11) <= x["mes"] <= mes]       # grafico: 12 meses ate o mes de referencia
    if not (linhas_per or orc_per or orc_mes):
        return None
    return {"linhas_mes": linhas_mes, "linhas_per": linhas_per, "orc_mes": orc_mes, "orc_per": orc_per, "serie_orc": serie, "serie_orc_g": serie_g}


def _fmt_num(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", ".")


def _fmt_pct(v):
    return "–" if v is None or pd.isna(v) else f"{v * 100:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def _estilo(df, numeros=(), percentuais=()):
    """Mostra celula vazia como '–' (em vez de 'None') e numeros no mesmo formato; a ordenacao continua pelo valor."""
    fm = {c: _fmt_num for c in numeros if c in df.columns}
    fm.update({c: _fmt_pct for c in percentuais if c in df.columns})
    return df.style.format(fm, na_rep="–")


def _m(v, vazio="–"):
    return F.moeda_br(v, vazio) if v is not None else vazio


def _mi(v, sinal=False):
    """R$ em milhoes (ou mil), compacto, para os cartoes. Com sinal=True mostra '+'/'-' (usa hifen para a cor do delta do st.metric)."""
    if v is None:
        return "–"
    a = abs(v)
    s = ("-" if v < 0 else ("+" if sinal and v > 0 else "")) if sinal else ("−" if v < 0 else "")
    if a >= 1e6:
        return s + "R$ " + f"{a / 1e6:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"
    if a >= 1e3:
        return s + "R$ " + f"{a / 1e3:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mil"
    return s + "R$ " + f"{a:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _rot(m: str) -> str:
    return f"{m[5:]}/{m[:4]}"


def _selecionada(ev, df):
    """Linha clicada (dict) de um st.dataframe com selecao, ou None."""
    try:
        rows = ev.selection.rows
    except Exception:
        return None
    return df.iloc[rows[0]].to_dict() if rows and rows[0] < len(df) else None


def _chave(base: str, *dep) -> str:
    """Chave de um st.dataframe com selecao que muda quando muda o que o alimenta (a selecao por posicao nao fica 'grudada' em outra linha)."""
    import zlib
    return f"{base}_{zlib.crc32(repr(dep).encode()) % 100000}"


def _selecionadas(ev, df):
    """TODAS as linhas marcadas (caixinhas) de um st.dataframe com selecao multipla -> DataFrame (vazio se nenhuma)."""
    try:
        rows = [r for r in ev.selection.rows if r < len(df)]
    except Exception:
        rows = []
    return df.iloc[rows] if rows else df.iloc[0:0]


def _txt_sel(itens, vazio: str, ate: int = 2) -> str:
    """Rotulo curto do que esta marcado: 'A, B' ate' `ate` itens; acima disso 'N selecionados'; sem marcacao -> `vazio`."""
    itens = [str(i) for i in itens]
    if not itens:
        return vazio
    return ", ".join(itens) if len(itens) <= ate else f"{len(itens)} selecionados"


def _busca(df, texto, colunas):
    if not texto.strip():
        return df
    t = texto.strip().lower()
    m = pd.Series(False, index=df.index)
    for c in colunas:
        m |= df[c].astype(str).str.lower().str.contains(t, regex=False)
    return df[m]


def _filtra_obra(chave: str, cod: str):
    """Clique num card: deixa so' essa obra marcada no filtro da aba Pessoas (roda ANTES de a tela ser redesenhada)."""
    st.session_state[chave] = [cod]


def _delta(real, prev):
    """Texto do desvio (real - previsto) para o st.metric: '+R$ 1,00 mi · +3,2%'."""
    if real is None or prev is None:
        return None
    dv = real - prev
    p = f" · {F.pct_br(dv / abs(prev), 1).replace('−', '-')}" if abs(prev) > 0.005 else ""
    return _mi(dv, True) + p


def _barras_mes(rotulos, valores, titulo_y="R$ milhões", cor=NAVY, destaque=None, divisor=1e6, altura=240):
    df = pd.DataFrame({"Mês": rotulos, "v": [x / divisor for x in valores], "dest": [(i == destaque) for i in range(len(valores))]})
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("Mês:N", sort=rotulos, axis=alt.Axis(labelAngle=0, title=None)), y=alt.Y("v:Q", title=titulo_y),
        color=alt.condition("datum.dest", alt.value(ORANGE), alt.value(cor)), tooltip=["Mês", alt.Tooltip("v:Q", title=titulo_y, format=",.2f")]).properties(height=altura)


# ------------------------------------------------------------------ cabecalho
st.title("Painel da Diretoria")
estilo.painel_adaptavel()                                  # layout que se adapta ao tamanho da tela (estilo.py)
CARIMBO = _carimbo(conn)
meses = _meses(conn, CARIMBO)
if not meses:
    _info("Ainda não há dados no painel. Assim que a contabilidade importar e o Sienge sincronizar, eles aparecem aqui.")
    st.stop()
_cab = st.container(key="dir_cab")
h1, h2, h3, h4 = _cab.columns([1.3, 1, 1, 1], vertical_alignment="bottom")          # Periodo | De (ou Mes) | Ate (ou texto do periodo) | Atualizar
conf = _confirmados(conn, CARIMBO)
padrao = conf[-1] if conf else meses[-1]
modo_per = h1.selectbox("Período", PER.MODOS, index=PER.MODOS.index(PER.PADRAO), key="dir_per_modo",
                        help="Vale para todas as abas. 'Ano até o mês' = janeiro até o mês de referência (como o painel era). Resultado e Obras somam os meses com DRE.")
if modo_per == PER.PERSONALIZADO:
    # primeiro o INICIO ("De"), depois o FIM ("Até"): a ordem em que a pessoa pensa. O "Até" só oferece meses a partir do "De".
    _de_pad = next((i for i, m in enumerate(meses) if m >= f"{padrao[:4]}-01"), 0)
    mes_de = h2.selectbox("De", meses, index=_de_pad, format_func=_rot, key="dir_mes_de")
    _ate_opcoes = [m for m in meses if m >= mes_de]
    if st.session_state.get("dir_mes_ate") not in _ate_opcoes:
        st.session_state.pop("dir_mes_ate", None)
    mes = h3.selectbox("Até", _ate_opcoes, index=_ate_opcoes.index(padrao) if padrao in _ate_opcoes else len(_ate_opcoes) - 1, format_func=_rot, key="dir_mes_ate")
else:
    mes = h2.selectbox("Mês de referência" if modo_per != PER.MES else "Mês", meses, index=meses.index(padrao), format_func=_rot, key="dir_mes")
    mes_de = None
    h3.markdown(f"<div class='gdf-periodo-txt'>Período: <b>{PER.rotulo(*PER.resolver(modo_per, mes))}</b></div>", unsafe_allow_html=True)
mes_ini, mes = PER.resolver(modo_per, mes, mes_de)
PER_ROT = PER.rotulo(mes_ini, mes)                           # '01/2026 a 10/2026'
MES_INI_G = PER.somar_meses(mes, -11)                        # GRAFICOS: sempre os 12 meses ate o mes de referencia (nao seguem o filtro de periodo; cartoes e tabelas seguem)
MESES_G = PER.meses_entre(MES_INI_G, mes)
ACUM = PER.curto(mes_ini, mes)                               # cabecalho de coluna: 'Jan–Out/26'
UM_MES = mes_ini == mes
_T_CAB = time.perf_counter() - _T0                          # cabecalho + carimbo + listas de meses
ctx = _ctx(conn, mes, CARIMBO)
_T_CTX = time.perf_counter() - _T0 - _T_CAB                 # contexto do mes (cartoes, obras, adm...): lido do cache na maioria dos cliques
_cap(f"Dados do banco em {ctx['gerado_em']} · DRE de {_rot(mes)}: **{ctx['dre']['origem']}**" + (" · confirmado pela contabilidade" if ctx["dre"].get("quem") else " · ainda não confirmado")
     + f" · período: **{PER_ROT}**")
if h4.button("Atualizar agora", key="dir_atualizar"):
    st.cache_data.clear()
    st.rerun()

dre, ob, adm, proj, desp, pes = ctx["dre"], ctx["obras"], ctx["adm"], ctx.get("proj"), ctx["desp"], ctx["pessoas"]
hist = ctx.get("hist")
v = dre["valores"]
rec = ob["total"]["receita"] if ob else v["01"]
cus = abs(ob["total"]["custo"]) if ob else abs(v["04"])
bdi = ob["total"]["bdi"] if ob else v["05"]
orc_mes = adm["orcamento"] if adm and adm.get("orcamento") else None
adm_real = orc_mes["total"]["realizado"] if orc_mes else None
adm_orc = orc_mes["total"]["orcado"] if orc_mes else None
resultado = round(bdi - adm_real, 2) if adm_real is not None else None

_TODAS = bool(st.session_state.get("dir_todas_abas"))        # so' os testes ligam: renderiza todas as abas de uma vez
@st.cache_data(ttl=30, show_spinner=False)
def _acessos(_conn, email: str):
    """(e' editor?, mostra Investimentos?) guardado 30 s: sao 3 consultas ao banco que nao precisam repetir a cada clique."""
    eh_editor = acesso.papel(_conn, email) != acesso.VISUALIZADOR
    return eh_editor, eh_editor or acesso.investimentos_para_visualizador(_conn)


try:                                                         # editor ve tudo; visualizador so' ve Investimentos se o editor liberou (SQL-29). Na duvida (erro), esconde.
    _eh_editor, _mostra_inv = _acessos(conn, usuario)
except Exception:
    _eh_editor, _mostra_inv = False, False
_rotulos = ["Resultado", "Obras", "Administração", "Despesas", "Pessoas", "Folha PJ", "Indicadores financeiros", "Financiamentos"] + (["Investimentos"] if _mostra_inv else [])
_abas = st.tabs(_rotulos, key="dir_abas", on_change="rerun")
aba_res, aba_ob, aba_adm, aba_desp, aba_pes, aba_pj, aba_ind, aba_fin = _abas[:8]
aba_inv = _abas[8] if _mostra_inv else None


# ------------------------------------------------------------------ dados compartilhados entre abas (PJ e colaboradores)
def _pagos_df():
    return _pagos(conn, mes_ini, mes, CARIMBO)


def _colaboradores():
    """Colaboradores do mes: CLT (recibos da folha) + PJ (contas pagas 'Salarios PJ'). -> dict com total, obra, adm, pj, por_obra_pj; None onde falta fonte."""
    pj = _pj_mes(conn, mes_ini, mes, CARIMBO)
    clt = pes["folha"]["total"]["colab"] if pes else None
    return {"pj": pj, "clt": clt}


# ------------------------------------------------------------------ 1) RESULTADO
def _termos(modo: str = "mes"):
    """Receita - Custo = BDI - Administracao = Resultado do MES de referencia: [(chave: (realizado, previsto))]. Previsto None quando nao ha fonte."""
    rec_p = bdi_p = cus_p = None
    if proj and abs(proj["receita_proj_total"]) > 0.005:
        rec_p = proj["receita_proj_total"]
        bdi_p = proj["total"]["bdi_proj"]
        cus_p = round(rec_p - bdi_p, 2)
    res_p = round(bdi_p - adm_orc, 2) if bdi_p is not None and adm_orc is not None else None
    return {"rec": (rec, rec_p), "cus": (cus, cus_p), "bdi": (bdi, bdi_p), "adm": (adm_real, adm_orc), "res": (resultado, res_p)}


def _mes_anterior(m: str) -> str:
    return PER.somar_meses(m, -1)


def _historico_cobre() -> bool:
    return bool(hist and hist.get("ate") in (mes, _mes_anterior(mes)))


def _ano_pela_api():
    """Ano ate o mes: o REALIZADO (receita, custos, BDI) e' a soma mes a mes de janeiro ate o mes pela mesma regra de fonte do app (confirmado > API). O que a API nao
    fornece, previsto (projecao) e administracao (orcamento ADM), completa-se com o historico do painel da contabilidade ate o mes anterior + o mes atual do app.
    -> (termos ou None, meses fora da soma, True se o historico completou algo)."""
    t, falt = _termos_periodo()
    if not t:
        return None, falt, False
    if not _historico_cobre():
        return t, falt, False
    ate, ac, dev = hist["ate"], hist["acumulado"], hist.get("desvio_acumulado", {})
    atual, usou = _termos("mes"), False
    out = dict(t)

    def do_hist(k):
        real_h = ac.get(k)
        prev_h = (real_h - dev[k]) if real_h is not None and k in dev else None
        if ate == mes:
            return real_h, prev_h
        r_m, p_m = atual[k]
        return (None if real_h is None or r_m is None else real_h + r_m, None if prev_h is None or p_m is None else prev_h + p_m)

    for k in ("rec", "cus", "bdi", "adm"):
        real, prev = out[k]
        h_real, h_prev = do_hist(k)
        if prev is None and h_prev is not None:
            prev, usou = h_prev, True
        if k == "adm" and real is None and h_real is not None:
            real, usou = h_real, True
        out[k] = (real, prev)
    bdi_real, bdi_prev = out["bdi"]
    adm_real_, adm_prev_ = out["adm"]
    res_real, res_prev = out["res"]
    if res_real is None and bdi_real is not None and adm_real_ is not None:
        res_real, usou = round(bdi_real - adm_real_, 2), True
    h_res_prev = do_hist("res")[1]
    if res_prev is None:
        res_prev = round(bdi_prev - adm_prev_, 2) if bdi_prev is not None and adm_prev_ is not None else h_res_prev
        usou = usou or res_prev is not None
    out["res"] = (res_real, res_prev)
    return out, falt, usou


def _comparar_historico():
    """Tabela de conferencia: acumulado do historico da contabilidade (ate o mes que ele cobre) x o mesmo periodo pelo app (confirmado/API). Nao entra em nenhuma conta."""
    if not _historico_cobre():
        return None
    ate = hist["ate"]
    ms_h = PER.meses_entre(mes_ini, ate)
    app = P.somar_termos(_termos_meses(conn, tuple(ms_h), CARIMBO))
    if not app:
        return None
    nomes = {"rec": "Receita (base-line)", "cus": "Custos", "bdi": "BDI", "adm": "Administração", "res": "Resultado"}
    linhas = []
    for k, nome in nomes.items():
        h_, a_ = hist["acumulado"].get(k), app[k][0]
        linhas.append({"Linha": nome, f"Histórico da contabilidade (até {_rot(ate)})": _m(h_) if h_ is not None else "–", "App (confirmado/API)": _m(a_) if a_ is not None else "–",
                       "Diferença (app − histórico)": _m(a_ - h_) if h_ is not None and a_ is not None else "–"})
    return pd.DataFrame(linhas), ate


def _termos_periodo():
    """Soma dos meses do periodo com DRE CONFIRMADO. -> (termos ou None, meses fora da soma)."""
    ms_p = PER.meses_entre(mes_ini, mes)
    lst = _termos_meses(conn, tuple(ms_p), CARIMBO)
    return P.somar_termos(lst), [m for m, t in zip(ms_p, lst) if not t]


def _formula(modo: str, termos=None):
    termos = termos if termos is not None else _termos(modo)
    if not termos:
        _info("Não há dados de DRE (confirmado ou API do Sienge) em nenhum mês deste período." if modo == "per" else
              "Não há dados de DRE no ano até este mês.")
        return
    rot = [("rec", "Receita (base-line)", True), ("cus", "Custos", False), ("bdi", "BDI", True), ("adm", "Administração", False), ("res", "Resultado", True)]
    cols = st.container(key="dir_formula").columns([5, 1, 5, 1, 5, 1, 5, 1, 5], vertical_alignment="center")
    for i, (k, nome, maior_melhor) in enumerate(rot):
        real_, prev_ = termos[k]
        with cols[i * 2]:
            with st.container(border=True):
                st.metric(nome, _mi(real_), _delta(real_, prev_), delta_color="normal" if maior_melhor else "inverse")
                _cap(f"previsto {_mi(prev_)}" if prev_ is not None else "previsto n/d")
        if i < 4:
            cols[i * 2 + 1].markdown(f"<div style='text-align:center;font-size:1.6rem;font-weight:800;color:#7A859A'>{'−' if i % 2 == 0 else '='}</div>", unsafe_allow_html=True)
    # frase do que aconteceu (calculada, nao fixa)
    partes = []
    for k, nome, maior_melhor in rot:
        real_, prev_ = termos[k]
        if real_ is None or prev_ is None:
            continue
        dv = real_ - prev_
        if abs(dv) < 0.005:
            continue
        acima = dv > 0
        partes.append(f"{nome.split(' (')[0].lower()} {_mi(abs(dv)).replace('−', '')} {'acima' if acima else 'abaixo'} do previsto")
    if partes:
        _cap("Em relação ao previsto: " + "; ".join(partes) + ". Para custos e administração, acima do previsto é estouro.")


if aba_res.open or _TODAS:
    with aba_res:
        if modo_per == PER.MES:
            _formula("mes")
        else:
            _ano = modo_per == PER.ANO
            _t_per, _falt, _usou_h = _ano_pela_api() if _ano else (*_termos_periodo(), False)
            if _t_per:
                _formula("per", _t_per)
            else:
                _warn(f"Nenhum mês de {PER_ROT} tem dados de DRE (confirmado ou API do Sienge); abaixo, o resultado do mês de referência ({_rot(mes)}).")
                _formula("mes")
            if _t_per:
                _cap(f"Soma de {len(_t_per['meses'])} {'mês' if len(_t_per['meses']) == 1 else 'meses'} com dados em {PER_ROT}: {', '.join(_rot(m) for m in _t_per['meses'])}. Fonte de cada mês: confirmado pela contabilidade ou API do Sienge (padrão; o PDF só entra se a contabilidade o escolher na confirmação)."
                     + (f" Fora da soma por falta de dados: {', '.join(_rot(m) for m in _falt)}." if _falt else "")
                     + (" Previsto e administração (que a API não fornece) completados com o histórico do painel da contabilidade até o mês anterior + o mês atual do app." if _usou_h
                        else " Administração/Resultado só aparecem se todos os meses somados têm Orçamento ADM; previsto só se todos têm projeção."))
            if _ano:
                _cmp = _comparar_historico()
                if _cmp is not None:
                    with st.expander(f"Conferência: histórico da contabilidade × app (jan–{_rot(_cmp[1])})"):
                        st.dataframe(_cmp[0], hide_index=True, width="stretch")
                        _cap("Só para conferir: o histórico (HTML da contabilidade) não entra na conta do realizado. Diferença costuma vir de ajustes manuais do BM/reclassificações que a API não traz; se a contabilidade quiser um ajuste fixo no app, é só pedir.")
        g1, g2 = st.columns(2)
        with g1:
            _md("**Desvio mensal (realizado − previsto)**")
            _idx_h = [i for i, m in enumerate(hist["desvio_meses"]) if MES_INI_G <= m["mes"] <= mes] if hist and hist["desvio_linhas"] else []      # grafico: 12 meses ate o mes de referencia
            if hist and hist["desvio_linhas"] and not _idx_h:
                _info(f"O histórico do painel da contabilidade (até {_rot(hist['ate'])}) não tem desvio mensal nos 12 meses até {_rot(mes)}.")
            elif hist and hist["desvio_linhas"]:
                linhas_h = list(hist["desvio_linhas"])
                sel_h = st.selectbox("Métrica", linhas_h, index=len(linhas_h) - 1, key="dir_ano_linha", label_visibility="collapsed")
                ml = [hist["desvio_meses"][i]["rotulo"] for i in _idx_h]
                vals_h = [hist["desvio_linhas"][sel_h][i] for i in _idx_h]
                estouro = sel_h in ("Custos", "Despesas ADM")        # nessas linhas, positivo = gastou mais que o previsto (ruim)
                dfd = pd.DataFrame({"Mês": ml, "Desvio (R$ mi)": [x / 1e6 for x in vals_h]})
                dfd["cor"] = ["bom" if ((x >= 0) != estouro) else "ruim" for x in vals_h]
                estilo.altair(alt.Chart(dfd).mark_bar().encode(
                    x=alt.X("Mês:N", sort=ml, axis=alt.Axis(labelAngle=0, title=None)), y=alt.Y("Desvio (R$ mi):Q", title="R$ milhões"),
                    color=alt.Color("cor:N", scale=alt.Scale(domain=["bom", "ruim"], range=[BOM, RUIM]), legend=None),
                    tooltip=["Mês", alt.Tooltip("Desvio (R$ mi):Q", format=",.2f")]).properties(height=240), width="stretch")
                _cap(f"Gráfico fixo nos últimos 12 meses ({PER.rotulo(MES_INI_G, mes)}; histórico do painel da contabilidade). Para Custos e Despesas ADM, valor positivo indica estouro. Janeiro = desvio acumulado menos a soma de fevereiro em diante.")
            else:
                _info("O desvio mensal aparece quando o histórico do painel da contabilidade é importado.")
        with g2:
            _md("**Recomposição out–dez**")
            _cap("Visão do fim do ano; não muda com o período escolhido.")
            if hist and hist["recomposicao"]:
                rc = hist["recomposicao"]
                st.dataframe(pd.DataFrame([{"Mês": r["rotulo"], "Projeção": _m(r["projecao"]), "Para cobrir o déficit": _m(r["para_cobrir"])} for r in rc]
                                          + [{"Mês": "Out–Dez", "Projeção": _m(sum(r["projecao"] for r in rc)), "Para cobrir o déficit": _m(sum(r["para_cobrir"] for r in rc))}]),
                             hide_index=True, width="stretch")
                _cap("Faturamento necessário para cobrir o déficit acumulado de base-line, distribuído proporcionalmente à projeção.")
            else:
                _info("A recomposição aparece quando o histórico do painel da contabilidade é importado.")
        serie = [x for x in ctx["serie"] if MES_INI_G <= x["mes"] <= mes]       # grafico: sempre 12 meses ate o mes de referencia
        if len(serie) >= 2:
            _md("**Receita mês a mês**")
            rots = [_rot(x["mes"]) for x in serie]
            dfs = pd.DataFrame({"Mês": rots, "Receita (R$ mi)": [x["receita"] / 1e6 for x in serie], "Fonte": [x["fonte"] for x in serie], "destaque": [mes_ini <= x["mes"] <= mes for x in serie]})
            estilo.altair(alt.Chart(dfs).mark_bar().encode(
                x=alt.X("Mês:N", sort=rots, axis=alt.Axis(labelAngle=-60, title=None)), y=alt.Y("Receita (R$ mi):Q", title="R$ milhões"),
                color=alt.condition("datum.destaque", alt.value(NAVY), alt.value("#9A9CC4")), tooltip=["Mês", alt.Tooltip("Receita (R$ mi):Q", format=",.2f"), "Fonte"]).properties(height=220), width="stretch")
            if any(x["fonte"].startswith("API") for x in serie):
                _cap("Meses cinza-claros com fonte “API (a conferir)” ainda não têm DRE oficial confirmado.")
        with st.expander(f"DRE do mês de referência, {_rot(mes)} (linha a linha)"):
            rb = v["01"]
            rows = []
            for cod, nome, val in dre["linhas"]:
                rows.append({"Linha": cod, "Descrição": nome, "Valor": _m(val), "% da receita bruta": F.pct_br(val / rb) if abs(rb) > 0.005 and "." not in cod else "",
                             "Fonte": dre["fontes"].get(cod, "") if "." in cod else ""})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=35 * 25)
            if dre["manuais"]:
                _cap("Linhas ajustadas à mão pela contabilidade (com observação registrada): " + ", ".join(dre["manuais"]) + ".")
            for av in ctx["avisos"]:
                _cap(f"Atenção: {av}")


# ------------------------------------------------------------------ 2) OBRAS
def _obras_do_periodo():
    """Tabela de Obras do periodo: o mes de referencia (ctx) ou a SOMA dos meses com dado (PDF oficial ou API). -> (ob, proj, meses somados, meses sem dado)."""
    if UM_MES:
        return ob, proj, 1, []
    ms_p = PER.meses_entre(mes_ini, mes)
    pares = _obras_meses(conn, tuple(ms_p), CARIMBO)
    oks = [(o, px) for o, px in pares if o]
    falt = [m for m, (o, _) in zip(ms_p, pares) if not o]
    soma = P.somar_obras([o for o, _ in oks])
    if not soma:
        return None, None, 0, falt
    proj_s = P.somar_projecoes([px for _, px in oks])
    com_proj = {x["codigo"] for x in (proj_s or {}).get("linhas", []) if x.get("codigo") and x.get("receita_proj")}
    soma.update(P.agrupar_demais_obras(soma, com_proj))
    soma["nome_cheio"] = _nomes_obras(conn, CARIMBO)
    folha_f = P.folha_do_mes(conn, mes)
    soma["colab"] = P.colab_por_linha_obras(soma["linhas"], folha_f) if folha_f else {}
    return soma, proj_s, len(oks), falt


_ob_mes, _proj_mes = ob, proj
if aba_ob.open or _TODAS:                               # dentro da aba, ob/proj passam a ser os do PERIODO (e voltam ao do mes no fim)
    ob, proj, _n_ob, _falt_ob = _obras_do_periodo()
    with aba_ob:
        if not ob:
            _info("Sem dados por obra " + ("neste mês (nenhum título emitido carregado pela API e nenhum PDF importado)." if UM_MES else "em nenhum mês deste período."))
        else:
            if not UM_MES:
                _cap(f"Soma de {_n_ob} {'mês' if _n_ob == 1 else 'meses'} com dados por obra em {PER_ROT} (PDF oficial ou API do Sienge)." + (f" Sem dados (fora da soma): {', '.join(_rot(m) for m in _falt_ob)}." if _falt_ob else "")
                     + " Colaboradores = os do mês de referência; faturamento e custo por colaborador = média mensal do período.")
            colab_info = _colaboradores()
            pj_linhas = _pj_obra(conn, mes_ini, mes, CARIMBO)                                   # cada PJ aparece em todas as obras em que recebeu (com o %)
            pj_obra = {}
            for _x in pj_linhas:
                pj_obra.setdefault(_x["obra"], set()).add(_x["credor"])
            nome_cheio = ob.get("nome_cheio", {})
            proprias = {l["obra"] for l in ob["linhas"] if l["obra"] != "DEM"}
            prev_por_obra = {x["codigo"]: x for x in (proj["linhas"] if proj else [])}
            regs = []
            for l in ob["linhas"]:
                clt = ob["colab"].get(l["obra"], 0)
                pj_n = (len(set().union(*[cr for c, cr in pj_obra.items() if c not in proprias and c not in ("ADM", "99", "sem de-para")]))
                        if l["obra"] == "DEM" else len(pj_obra.get(l["obra"], ())))
                pr = prev_por_obra.get(l["obra"])
                hc = clt + pj_n
                regs.append({"Obra": l["obra"], "Nome": RPP._nome_obra(l, nome_cheio), "Receita": l["receita"], "Custos": abs(l["custo"]), "BDI previsto": pr["bdi_proj"] if pr else None,
                             "BDI real": l["bdi"], "Desvio BDI": (l["bdi"] - pr["bdi_proj"]) / abs(pr["bdi_proj"]) if pr and abs(pr["bdi_proj"]) > 0.005 else None,
                             "CLT": clt, "PJ": pj_n, "Colab.": hc, "Fat./colab.": (l["receita"] / _n_ob / hc) if hc and l["obra"] != "DEM" else None,
                             "Custo/colab.": (abs(l["custo"]) / _n_ob / hc) if hc and l["obra"] != "DEM" else None,
                             "Margem": l["margem"], "receita_proj": pr["receita_proj"] if pr else None})
            base = pd.DataFrame(regs)
            main = base[base["Obra"] != "DEM"]
            tr, tc, tb = ob["total"]["receita"], abs(ob["total"]["custo"]), ob["total"]["bdi"]
            rec_p = proj["receita_proj_total"] if proj else None
            bdi_p = proj["total"]["bdi_proj"] if proj else None
            cus_p = (rec_p - bdi_p) if rec_p is not None and bdi_p is not None else None
            neg = int((main["BDI real"] < 0).sum())
            k = st.columns(6)
            k[0].metric("Receita realizada", _mi(tr), _delta(tr, rec_p), border=True)
            k[1].metric("Custos", _mi(tc), _delta(tc, cus_p), delta_color="inverse", border=True)
            k[2].metric("BDI", _mi(tb), _delta(tb, bdi_p), border=True)
            k[3].metric("Obras com prejuízo", f"{neg} de {len(main)}", "BDI negativo no período" if not UM_MES else "BDI negativo no mês", delta_color="off", border=True)
            if len(main):
                mx, mn = main.loc[main["BDI real"].idxmax()], main.loc[main["BDI real"].idxmin()]
                k[4].metric("Maior BDI", str(mx["Nome"] or mx["Obra"])[:22], _mi(mx["BDI real"], True), border=True)
                k[5].metric("Menor BDI", str(mn["Nome"] or mn["Obra"])[:22], _mi(mn["BDI real"], True), border=True)
            busca = st.text_input("Pesquisar obra (código ou nome)", key="dir_ob_busca", placeholder="ex.: 104, lote 03, Eletrobras")
            vis = _busca(base, busca, ["Obra", "Nome"]).reset_index(drop=True)
            _cap("Marque a caixinha de uma ou mais obras para ver o detalhe (várias marcadas somam); clique no cabeçalho para ordenar. Previsto = projeção de receitas do mês.")
            mostra = vis[["Obra", "Nome", "Receita", "Custos", "BDI previsto", "BDI real", "Desvio BDI", "Margem", "Colab.", "Fat./colab.", "Custo/colab."]]
            ev = st.dataframe(_estilo(mostra, numeros=("Receita", "Custos", "BDI previsto", "BDI real", "Colab.", "Fat./colab.", "Custo/colab."),
                                      percentuais=("Desvio BDI", "Margem")),
                              hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key="dir_ob_df")
            sel_df = _selecionadas(ev, vis)
            cods_sel = list(sel_df["Obra"])
            if len(sel_df) == 1:
                sel = sel_df.iloc[0].to_dict()
            elif len(sel_df) > 1:                                              # varias obras marcadas: soma
                _rp = sel_df["receita_proj"].dropna()
                _rec, _cus, _bdi = float(sel_df["Receita"].sum()), float(sel_df["Custos"].sum()), float(sel_df["BDI real"].sum())
                _hc = int(sel_df["Colab."].sum())
                sel = {"Obra": ", ".join(cods_sel), "Nome": f"{len(sel_df)} obras selecionadas", "Receita": _rec, "Custos": _cus, "BDI real": _bdi, "receita_proj": float(_rp.sum()) if len(_rp) else float("nan"),
                       "Margem": (_bdi / _rec) if abs(_rec) > 0.005 else None, "Colab.": _hc, "CLT": int(sel_df["CLT"].sum()), "PJ": int(sel_df["PJ"].sum()),
                       "Fat./colab.": (_rec / _n_ob / _hc) if _hc and "DEM" not in cods_sel else float("nan")}
            else:
                sel = None
            _pj_unicos = set().union(*[cr for c, cr in pj_obra.items() if c not in ("ADM", "99", "sem de-para")]) if pj_obra else set()
            _cap(f"Total: receita {_mi(tr)} · custos {_mi(tc)} · BDI {_mi(tb)} · {int(base['CLT'].sum()) + len(_pj_unicos)} colaboradores nas obras (cada PJ contado uma vez, mesmo atendendo várias obras).")
            if sel:
                _md(f"#### {sel['Obra']} · {sel['Nome']}")
                a, b, c, d = st.columns(4)
                a.metric("Receita realizada", _mi(sel["Receita"]), border=True)
                b.metric("Receita prevista", _mi(sel["receita_proj"]) if pd.notna(sel["receita_proj"]) else "sem projeção", border=True)
                c.metric("Custos", _mi(sel["Custos"]), border=True)
                d.metric("BDI real", _mi(sel["BDI real"]), F.pct_br(sel["Margem"]) + " de margem" if sel["Margem"] is not None else None, border=True)
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("Colaboradores", int(sel["Colab."]), f"{int(sel['CLT'])} CLT + {int(sel['PJ'])} PJ", delta_color="off", border=True)
                e2.metric("Faturamento por colaborador", _mi(sel["Fat./colab."]) if pd.notna(sel["Fat./colab."]) else "–", border=True)
                e3.metric("Custo por colaborador", _mi(sel["Custos"] / _n_ob / sel["Colab."]) if sel["Colab."] else "–", border=True)
                _pos = [pes["folha"]["por_obra"].get(c) for c in cods_sel] if pes else []
                _pos = [x for x in _pos if x]
                po = {"custo": sum(x["custo"] for x in _pos), "colab": sum(x["colab"] for x in _pos)} if _pos else None
                e4.metric("Custo da folha CLT por colaborador", _m(po["custo"] / po["colab"]) if po and po["colab"] else "–", border=True)
            _cap("Colaboradores = CLT da folha do mês + PJ alocado na obra onde mais recebeu em “Salários PJ” (contas pagas). Obras sem projeção não têm BDI previsto.")

            # ---- cascata da obra clicada: principais credores + colaboradores alocados (o clique na linha escolhe a obra nos dois blocos)
            nomes_ob = {l["obra"]: (RPP._nome_obra(l, nome_cheio) or l["obra"]) for l in ob["linhas"]}
            nao_obra = ("ADM", "99", "")
            proprias_l = sorted(proprias)

            def _destino_ob(cod: str):
                """Codigo do de-para -> opcao da lista: obra propria, 'DEM' (demais obras) ou None (administracao / sem de-para ficam fora)."""
                if cod in proprias:
                    return cod
                return None if cod in nao_obra or cod == "sem de-para" else "DEM"

            regs_c = [{"Nome": c["nome"], "Função": c["cargo"], "Tipo": "CLT", "dest": _destino_ob(c["obra"])} for c in _folha_colaboradores(conn, mes, CARIMBO)]
            _fant = _fantasias(conn, CARIMBO)
            for x in _pj_obra(conn, mes_ini, mes, CARIMBO):
                _nf = DD.nome_fantasia(x["credor"], _fant)                                     # contabilidade 21/10: PJ aparece pelo nome fantasia do cadastro do credor
                regs_c.append({"Nome": _nf, "Função": f"Prestador de serviço (PJ) — {round(x['pct'] * 100)}% nesta obra" + (f" · razão social: {x['credor']}" if _nf != x["credor"] else ""),
                               "Tipo": "PJ", "dest": _destino_ob(x["obra"])})
            col_df = pd.DataFrame([r for r in regs_c if r["dest"]], columns=["Nome", "Função", "Tipo", "dest"])
            _rot_obras = _txt_sel([("demais obras" if c == "DEM" else nomes_ob.get(c, c)) for c in cods_sel], "todas as obras")
            # ---- custos por categoria (relatorio "Custos por obra - nivel" da contabilidade): segue as obras marcadas na tabela
            _md(f"**Custos por categoria · {_rot_obras}**")
            _lin_n = _custos_nivel(conn, mes_ini, mes, CARIMBO)
            _tab_n = CON.tabela(_lin_n, cods_sel, lambda o: o if o in proprias else "DEM", mes) if _lin_n else []
            cats_sel: list = []                                               # codigos de categoria marcados (vazio = todas)
            if _tab_n and abs(_tab_n[0]["periodo"]) > 0.005:
                _df_n = pd.DataFrame({"Código": [x["codigo"] for x in _tab_n],
                                      "Categoria": [("      " if "." in x["codigo"] else "") + x["categoria"] for x in _tab_n],
                                      f"Acumulado {ACUM}": [_m(x["periodo"]) for x in _tab_n],
                                      "% do total": [F.pct_br(x["pct"]) if x["pct"] is not None else "–" for x in _tab_n],
                                      _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in _tab_n]})
                _cap("Marque a caixinha de uma ou mais categorias ou subcategorias: os credores abaixo passam a mostrar só as contas delas (marcar a categoria inclui as subcategorias).")
                _ev_n = st.dataframe(_df_n, hide_index=True, width="stretch", height=min(35 * (len(_tab_n) + 1) + 3, 735),
                                     on_select="rerun", selection_mode="multi-row", key=_chave("dir_ob_cat", tuple(cods_sel), mes_ini, mes))
                cats_sel = list(_selecionadas(_ev_n, _df_n)["Código"])
                if cats_sel:
                    _topo = [c for c in cats_sel if "." in c and c.split(".")[0] not in cats_sel or "." not in c]             # sem contar duas vezes (categoria + subcategoria dela)
                    _val = {x["codigo"]: x["periodo"] for x in _tab_n}
                    _soma = sum(_val.get(c, 0.0) for c in _topo)
                    _cap(f"Selecionado: {_m(_soma)} ({F.pct_br(_soma / _tab_n[0]['periodo'])} do custo total) em {len(cats_sel)} linha{'s' if len(cats_sel) > 1 else ''}.")
                _cap(f"Custos dos títulos emitidos em {PER_ROT} (análise “comprometido”, como no relatório de custos por obra da contabilidade), sem previsões e títulos desfeitos e sem os centros da administração. "
                     "Segue as obras marcadas na tabela acima (nenhuma marcada = todas). Valor negativo é crédito. O total acompanha a coluna “Custos” da tabela de obras (padrão da contabilidade: DRE 04+06+08+09+10+12).")
            else:
                _cap("Sem custos por categoria para esta seleção (faltam títulos emitidos no período ou o de-para de centros de custo → obra).")
            _contas_cat = CON.contas_das_categorias(cats_sel) if cats_sel else None
            _rot_cat = _txt_sel(cats_sel, "") if cats_sel else ""
            _md(f"**Principais credores · {_rot_obras}" + (f" · categoria {_rot_cat}" if cats_sel else "") + "**")
            _pj_nomes = _credores_pj_nomes(conn, mes_ini, mes, CARIMBO)               # contabilidade 21/10: quem e' colaborador PJ ja' esta na lista de colaboradores, nao em credores
            dd_ob = _despesas_sem_pj(conn, mes_ini, mes, CARIMBO)
            if _contas_cat is not None and len(dd_ob):
                dd_ob = dd_ob[dd_ob["plano_cod"].isin(_contas_cat)]
            if cods_sel:
                alvo = [c for c in cods_sel if c != "DEM"]
                if "DEM" in cods_sel:
                    alvo += [c for c in dd_ob["obra"].unique() if c not in proprias and c not in nao_obra] if len(dd_ob) else []
            else:
                alvo = None
            cr_ob = DD.credores_da_obra(dd_ob, alvo, mes)
            if cr_ob["linhas"]:
                st.dataframe(pd.DataFrame({"Credor": [x["chave"] for x in cr_ob["linhas"]], f"Acumulado {ACUM}": [_m(x["acumulado"]) for x in cr_ob["linhas"]],
                                           "%": [F.pct_br(x["acumulado"] / cr_ob["total"]) if cr_ob["total"] else "–" for x in cr_ob["linhas"]],
                                           _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in cr_ob["linhas"]]}), hide_index=True, width="stretch")
                _cap(("Todos os credores." if cr_ob["n"] <= len(cr_ob["linhas"]) else f"Top {len(cr_ob['linhas'])} de {cr_ob['n']} credores.")
                           + f" Contas pagas em {PER_ROT}, sem pessoal e encargos (estão na lista de colaboradores e na aba Pessoas) e sem os credores que são colaboradores PJ"
                           + (f" ({len(_pj_nomes)} fora da lista)" if _pj_nomes else "") + ". Obra pelo centro de custo do lançamento.")
            else:
                _cap("Sem contas pagas para esta seleção (ou falta o de-para de centros de custo → obra)."
                     + (" Pessoal e encargos (categoria 01) não entram na lista de credores: estão em Colaboradores e na aba Pessoas." if any(c.startswith("01") for c in cats_sel) else ""))

            _md(f"**Colaboradores alocados nas obras — {_rot(mes)}**")
            q_col = st.text_input("Buscar nome ou função", key="dir_col_busca", placeholder="ex.: engenheiro, silva")
            _cap("A lista segue as obras marcadas na tabela acima (nenhuma marcada = todas as obras).")
            lista = col_df if not cods_sel else col_df[col_df["dest"].isin(cods_sel)]
            lista = _busca(lista, q_col, ["Nome", "Função"]) if len(lista) else lista
            if len(lista):
                mostra_c = lista[["Nome", "Função"]].copy()
                if not cods_sel or len(cods_sel) > 1:
                    mostra_c["Obra"] = lista["dest"].map(lambda c: "Demais obras" if c == "DEM" else f"{c} · {nomes_ob.get(c, c)}")
                st.dataframe(mostra_c, hide_index=True, width="stretch", height=min(35 * (len(mostra_c) + 1) + 3, 420))
                n_clt = int((lista["Tipo"] == "CLT").sum())
                n_pj = int(lista.loc[lista["Tipo"] == "PJ", "Nome"].nunique())
                linhas_pj = int((lista["Tipo"] == "PJ").sum())
                _cap(f"{n_clt + n_pj} colaboradores ({n_clt} CLT + {n_pj} PJ)"
                           + (f"; {linhas_pj - n_pj} linhas a mais porque PJ que atendem mais de uma obra aparecem em cada uma, com o % do valor pago naquela obra" if linhas_pj > n_pj else "")
                           + ". CLT pelos recibos da folha do mês; PJ pelos credores de “Salários PJ” pagos no mês. Administração fora da lista.")
            else:
                _cap("Sem colaboradores para esta seleção (folha do mês ainda não importada ou obra sem pessoal).")
            if ob["top_prejuizo"]:
                _md("**Obras com maior prejuízo " + ("no mês**" if UM_MES else "no período**"))
                st.dataframe(pd.DataFrame([{"Obra": x["obra"], "Nome": RPP._nome_obra(x, nome_cheio), "BDI": _m(x["bdi"]), "Margem": F.pct_br(x["margem"]) if x["margem"] is not None else "–"}
                                           for x in ob["top_prejuizo"]]), hide_index=True, width="stretch")
ob, proj = _ob_mes, _proj_mes


# ------------------------------------------------------------------ 3) ADMINISTRACAO
if aba_adm.open or _TODAS:
    with aba_adm:
        ap = _adm_periodo(conn, mes_ini, mes, CARIMBO)
        if not ap:
            _info("Falta sincronizar as contas pagas do período e/ou importar o Orçamento ADM.")
        else:
            o, ac, so = ap["orc_mes"], ap["orc_per"], ap["serie_orc"]
            linhas_mes, linhas_per = ap["linhas_mes"], ap["linhas_per"]
            grp_sel = None
            contas_sel: list = []                                      # contas marcadas (a tabela de contas so' aparece com algum grupo marcado)
            if o or ac:
                k = st.columns(5)
                k[0].metric(f"Orçado {_rot(mes)}", _mi(o["total"]["orcado"]) if o else "–", border=True)
                k[1].metric(f"Realizado {_rot(mes)}", _mi(o["total"]["realizado"]) if o else "–", _delta(o["total"]["realizado"], o["total"]["orcado"]) if o else None, delta_color="inverse", border=True)
                k[2].metric(f"Orçado no período", _mi(ac["total"]["orcado"]) if ac else "–", PER_ROT, delta_color="off", border=True)
                k[3].metric("Realizado no período", _mi(ac["total"]["realizado"]) if ac else "–", _delta(ac["total"]["realizado"], ac["total"]["orcado"]) if ac else None, delta_color="inverse", border=True)
                acima_n = sum(1 for x in so if x["realizado"] > x["orcado"])
                k[4].metric("Meses acima do orçado", f"{acima_n} de {len(so)}" if so else "–", "realizado > orçado", delta_color="off", border=True)
                so_g = ap.get("serie_orc_g") or []
                if len(so_g) > 1:
                    _md("**Despesas ADM — orçado × realizado por mês (12 meses)**")
                    linhas_g = []
                    for x in so_g:
                        linhas_g.append({"Mês": _rot(x["mes"]), "Série": "Orçado", "v": x["orcado"] / 1e6})
                        linhas_g.append({"Mês": _rot(x["mes"]), "Série": "Realizado acima do orçado" if x["realizado"] > x["orcado"] else "Realizado", "v": x["realizado"] / 1e6})
                    dg = pd.DataFrame(linhas_g)
                    ordem_m = [_rot(x["mes"]) for x in so_g]
                    estilo.altair(alt.Chart(dg).mark_bar().encode(
                        x=alt.X("Mês:N", sort=ordem_m, axis=alt.Axis(labelAngle=0, title=None)), xOffset=alt.XOffset("Série:N"),
                        y=alt.Y("v:Q", title="R$ milhões"),
                        color=alt.Color("Série:N", scale=alt.Scale(domain=["Orçado", "Realizado", "Realizado acima do orçado"], range=[CINZA, NAVY, RUIM]), legend=alt.Legend(orient="bottom", title=None)),
                        tooltip=["Mês", "Série", alt.Tooltip("v:Q", title="R$ mi", format=",.2f")]).properties(height=260), width="stretch")
                # por grupo de despesa (orcado x realizado, mes e periodo); clicar filtra os credores E as contas abaixo
                _md("**Por grupo de despesa**")
                gm = {g["codigo"]: g for g in (o["grupos"] if o else [])}
                ga = {g["codigo"]: g for g in (ac["grupos"] if ac else [])}
                linhas_grp = []
                for cod in sorted(set(gm) | set(ga)):
                    g1_, g2_ = gm.get(cod), ga.get(cod)
                    reg = {"Código": cod, "Grupo": ("   " * cod.count(".")) + ((g1_ or g2_)["conta"] or cod)}
                    gu = g1_ or (g2_ if UM_MES else None)
                    reg.update({f"Orçado {_rot(mes)}": gu["orcado"] if gu else None, f"Realizado {_rot(mes)}": gu["realizado"] if gu else None, f"Desvio {_rot(mes)}": gu["desvio"] if gu else None})
                    if not UM_MES:
                        reg.update({f"Orçado {ACUM}": g2_["orcado"] if g2_ else None, f"Realizado {ACUM}": g2_["realizado"] if g2_ else None, f"Desvio {ACUM}": g2_["desvio"] if g2_ else None})
                    linhas_grp.append(reg)
                grp = pd.DataFrame(linhas_grp)
                if len(grp):
                    cfg_g = {c: st.column_config.NumberColumn(c, format="localized") for c in grp.columns if c not in ("Código", "Grupo")}
                    _cap("Marque a caixinha de um ou mais grupos para filtrar as contas e os credores abaixo (várias marcadas somam; nenhuma = total). Desvio = realizado − orçado: positivo é estouro. O orçamento está consolidado das unidades.")
                    ev_g = st.dataframe(grp, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key="dir_adm_grp", column_config=cfg_g)
                    grp_sel = _selecionadas(ev_g, grp)
                filtros_g = list(grp_sel["Código"]) if grp_sel is not None and len(grp_sel) else []
                base_c = ac or o
                _no_g = lambda c: (not filtros_g) or any(c == g or c.startswith(g + ".") for g in filtros_g)               # noqa: E731
                if filtros_g:
                    cs = [x for x in base_c["contas"] if _no_g(x["codigo"])]
                    _md(f"**Contas {'do grupo ' + filtros_g[0] if len(filtros_g) == 1 else 'dos ' + str(len(filtros_g)) + ' grupos marcados'} — orçado × realizado ({PER_ROT})**")
                    _cap("Marque a caixinha de uma ou mais contas (ex.: Seguros, Aluguéis) para ver só elas e, mais abaixo, quem recebeu nelas. Maiores estouros primeiro; desvio negativo = gastou menos que o orçado.")
                    if cs:
                        _tab_c = pd.DataFrame({"Código": [x["codigo"] for x in cs], "Conta": [x["conta"] for x in cs], "Orçado": [_m(x["orcado"]) for x in cs],
                                               "Realizado": [_m(x["realizado"]) for x in cs], "Desvio": [_m(x["desvio"]) for x in cs]})
                        ev_cc = st.dataframe(_tab_c, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=_chave("dir_adm_contas", filtros_g))
                        contas_sel = list(_selecionadas(ev_cc, _tab_c)["Código"])
                    else:
                        _cap("Nenhuma conta com orçamento neste filtro.")
                else:
                    cs = base_c["acima"]
                    _md(f"**Contas que mais passaram do orçado ({PER_ROT})**")
                    if cs:
                        st.dataframe(pd.DataFrame([{"Conta": f"{x['codigo']} · {x['conta']}", "Orçado": _m(x["orcado"]), "Realizado": _m(x["realizado"]), "Desvio": _m(x["desvio"])} for x in cs]),
                                     hide_index=True, width="stretch")
                    else:
                        _cap("Nenhuma conta com orçamento neste filtro.")
            if linhas_per or linhas_mes:
                filtros_cod = list(grp_sel["Código"]) if grp_sel is not None and len(grp_sel) else []
                _no_grupo = lambda c: ((not filtros_cod) or any(c == g or c.startswith(g + ".") for g in filtros_cod)) and ((not contas_sel) or any(c == k or c.startswith(k + ".") for k in contas_sel))      # noqa: E731
                chaves_dir = _outros_dir(conn, CARIMBO)
                df_l = DD.marcar_outros_dir(pd.DataFrame(linhas_mes, columns=["plano_cod", "plano_nome", "credor", "unidade", "valor"]), chaves_dir)
                df_l = df_l[df_l["plano_cod"].map(_no_grupo)] if len(df_l) else df_l
                df_a = DD.marcar_outros_dir(pd.DataFrame(linhas_per or linhas_mes, columns=["plano_cod", "plano_nome", "credor", "unidade", "valor"]), chaves_dir)
                df_a = df_a[df_a["plano_cod"].map(_no_grupo)] if len(df_a) else df_a
                _md("#### Quem recebeu: unidade → credor → contas" + (f" · {_txt_sel(filtros_cod, '', 1).replace(' selecionados', ' grupos')}" if filtros_cod else "") + (f" · {len(contas_sel)} conta(s) filtrada(s)" if contas_sel else ""))
                if not len(df_l) and not len(df_a):
                    _info("Nenhum pagamento da administração neste grupo no período.")
                else:
                    un_mes = df_l.groupby("unidade")["valor"].sum() if len(df_l) else pd.Series(dtype=float)
                    un_ano = df_a.groupby("unidade")["valor"].sum() if len(df_a) else pd.Series(dtype=float)
                    un = pd.DataFrame({"unidade": sorted(set(un_mes.index) | set(un_ano.index))})
                    un["mes"] = un["unidade"].map(lambda u: float(un_mes.get(u, 0.0)))
                    un["ano"] = un["unidade"].map(lambda u: float(un_ano.get(u, 0.0)))
                    un = un.sort_values(["ano", "mes"], ascending=False).reset_index(drop=True)
                    tot_u = float(un["ano"].sum())
                    _cap(f"Pago nas unidades da administração (contas pagas, inclui pessoal). 1) Marque uma ou mais unidades (ou deixe sem marcação para ver todas). 2) Marque um ou mais credores para ver as contas deles. "
                         f"Mês = {_rot(mes)}; período = {PER_ROT}.")
                    un_m = pd.DataFrame({"Unidade": un["unidade"], _rot(mes): un["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–"), ACUM: un["ano"].map(_m),
                                         "% do período": un["ano"].map(lambda x: F.pct_br(x / tot_u) if tot_u else "–")})
                    ev_u = st.dataframe(un_m, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=_chave("dir_adm_un", filtros_cod, contas_sel))
                    su = list(_selecionadas(ev_u, un)["unidade"])
                    if su:
                        df_l = df_l[df_l["unidade"].isin(su)]
                        df_a = df_a[df_a["unidade"].isin(su)]
                        _md(f"Credores em **{_txt_sel(su, '', 2)}**")
                    bc = st.text_input("Pesquisar credor", key="dir_adm_busca")
                    c_mes = df_l.groupby("credor_exib")["valor"].sum() if len(df_l) else pd.Series(dtype=float)
                    c_ano = df_a.groupby("credor_exib")["valor"].sum() if len(df_a) else pd.Series(dtype=float)
                    cr = pd.DataFrame({"credor": sorted(set(c_mes.index) | set(c_ano.index))})
                    cr["mes"] = cr["credor"].map(lambda c: float(c_mes.get(c, 0.0)))
                    cr["ano"] = cr["credor"].map(lambda c: float(c_ano.get(c, 0.0)))
                    cr = _busca(cr.sort_values(["ano", "mes"], ascending=False), bc, ["credor"]).reset_index(drop=True)
                    tot_c = float(df_a["valor"].sum())
                    cr_m = pd.DataFrame({"Credor": cr["credor"], _rot(mes): cr["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–"), ACUM: cr["ano"].map(_m),
                                         "% do filtro": cr["ano"].map(lambda x: F.pct_br(x / tot_c) if tot_c else "–")}).head(60)
                    ev_c = st.dataframe(cr_m, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=_chave("dir_adm_cr", filtros_cod, contas_sel, su, bc))
                    sc = list(_selecionadas(ev_c, cr)["credor"])
                    if chaves_dir and len(df_a) and (df_a["credor_exib"] == "Outros credores/Dir").any():
                        _cap("“Outros credores/Dir” junta numa linha só os credores do grupo definido pela contabilidade (marque a caixinha da linha para ver quem são).")
                    if sc:
                        outros_sel = "Outros credores/Dir" in sc
                        d_a, d_l = df_a[df_a["credor_exib"].isin(sc)], df_l[df_l["credor_exib"].isin(sc)]
                        if outros_sel and len(d_a):
                            _o_a, _o_l = d_a[d_a["credor_exib"] == "Outros credores/Dir"], d_l[d_l["credor_exib"] == "Outros credores/Dir"]
                            _md("Quem está em **Outros credores/Dir**")
                            q_a = _o_a.groupby("credor")["valor"].sum().sort_values(ascending=False)
                            q_l = _o_l.groupby("credor")["valor"].sum() if len(_o_l) else pd.Series(dtype=float)
                            st.dataframe(pd.DataFrame({"Credor": q_a.index, _rot(mes): [(_m(q_l.get(c)) if abs(float(q_l.get(c, 0.0))) > 0.005 else "–") for c in q_a.index], ACUM: q_a.map(_m).values}),
                                         hide_index=True, width="stretch")
                        ct_a = d_a.groupby(["plano_cod", "plano_nome"], as_index=False)["valor"].sum().sort_values("valor", ascending=False)
                        ct_m = d_l.groupby("plano_cod")["valor"].sum() if len(d_l) else pd.Series(dtype=float)
                        _md(f"Contas pagas a **{_txt_sel(sc, '', 2)}**")
                        st.dataframe(pd.DataFrame({"Conta": ct_a["plano_cod"] + " · " + ct_a["plano_nome"].fillna(""), _rot(mes): ct_a["plano_cod"].map(lambda c: _m(ct_m.get(c)) if abs(float(ct_m.get(c, 0.0))) > 0.005 else "–"),
                                                   ACUM: ct_a["valor"].map(_m)}), hide_index=True, width="stretch")
                    _cap("Conferência: o Realizado do orçamento (tabela de grupos) vem do relatório de Orçamento ADM importado; aqui é o valor efetivamente pago no Sienge (contas pagas). "
                         "Podem diferir por competência × caixa, previsões e reapropriações.")
            _cap("Orçamento ADM consolidado das unidades. O orçado por unidade ainda não vem do banco (só o consolidado); o realizado por unidade vem das contas pagas.")


# ------------------------------------------------------------------ 4) DESPESAS (acumulado do periodo, em cascata conta -> credor -> obra)
if aba_desp.open or _TODAS:
    with aba_desp:
        dfp, fora = _pagos_df()
        if not len(dfp):
            _info("Falta sincronizar as contas pagas do período.")
        else:
            dd = _despesas(conn, mes_ini, mes, CARIMBO)
            ms = PER.meses_entre(mes_ini, mes)
            rots = [m[5:] + "/" + m[2:4] for m in ms]
            tot_ano = float(dd["valor"].sum()) if len(dd) else 0.0
            dm = dd[dd["mes"] == mes]
            tot_mes = float(dm["valor"].sum()) if len(dm) else 0.0
            contas_ano = DD.total_por(dd)
            contas_mes = DD.total_por(dm)
            top5 = sum(x[1] for x in contas_mes[:5])
            top12 = sum(x[1] for x in contas_ano[:12])
            k = st.columns(4)
            k[0].metric(f"Pago em {_rot(mes)}", _mi(tot_mes), "exceto contas de pessoas", delta_color="off", border=True)
            k[1].metric(f"Top 5 de {_rot(mes)}", F.pct_br(top5 / tot_mes) if tot_mes else "–", "do total do mês", delta_color="off", border=True)
            k[2].metric(f"Pago {ACUM}", _mi(tot_ano), "exceto contas de pessoas", delta_color="off", border=True)
            k[3].metric(f"Top 12 {ACUM}", F.pct_br(top12 / tot_ano) if tot_ano else "–", "do total do período", delta_color="off", border=True)
            e1, e2 = st.columns(2)
            with e1:
                _md(f"**Top 12 contas — acumulado {ACUM}**")
                top = contas_ano[:12]
                df_top = pd.DataFrame({"Conta": [x[0] for x in top], "Acumulado": [x[1] for x in top]})
                _cap("Marque a caixinha de uma ou mais contas para detalhar (evolução, credores e obras; várias marcadas somam); sem marcação = total.")
                ev_t = st.dataframe(pd.DataFrame({"Conta": df_top["Conta"], "Acumulado": df_top["Acumulado"].map(_mi), "% do período": df_top["Acumulado"].map(lambda x: F.pct_br(x / tot_ano) if tot_ano else "–")}),
                                    hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key="dir_desp_top")
                conta = list(_selecionadas(ev_t, df_top)["Conta"]) or None
                _md(f"**Top 5 de {_rot(mes)}**")
                st.dataframe(pd.DataFrame({"Conta": [x[0] for x in contas_mes[:5]], _rot(mes): [_m(x[1]) for x in contas_mes[:5]],
                                           "% do mês": [F.pct_br(x[1] / tot_mes) if tot_mes else "–" for x in contas_mes[:5]]}), hide_index=True, width="stretch")
                _cap("Contas pagas, exceto as contas de pessoas e encargos (aba Pessoas). Conforme as regras da aba “Regras” do Painel EnerMais.")
            with e2:
                _md(f"**Evolução mensal · {_txt_sel(conta or [], 'todas as contas')} (12 meses)**")
                if mes_ini <= MES_INI_G:
                    dd12 = dd
                else:                                                            # periodo curto: carrega os 12 meses so' para o grafico (cartoes e tabelas seguem o periodo)
                    dd12 = _despesas(conn, MES_INI_G, mes, CARIMBO)
                vals = DD.serie_mensal(dd12, MESES_G, conta)
                estilo.altair(_barras_mes([m[5:] + "/" + m[2:4] for m in MESES_G], vals, destaque=len(MESES_G) - 1), width="stretch")
                cr = DD.agrupar(dd, "credor", mes, conta=conta)
                _md(f"**Principais credores · {_txt_sel(conta or [], 'todas as contas')}**")
                cr_df = pd.DataFrame({"Credor": [x["chave"] for x in cr["linhas"]], "ac": [x["acumulado"] for x in cr["linhas"]], "mes": [x["mes"] for x in cr["linhas"]]})
                cr_sel = pd.DataFrame({"Credor": []})
                if len(cr_df):
                    ev_cr = st.dataframe(pd.DataFrame({"Credor": cr_df["Credor"], ACUM: cr_df["ac"].map(_m), "% do filtro": cr_df["ac"].map(lambda x: F.pct_br(x / cr["total"]) if cr["total"] else "–"),
                                                       _rot(mes): cr_df["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–")}),
                                         hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=_chave("dir_desp_cr", conta))
                    cr_sel = _selecionadas(ev_cr, cr_df)
                    _cap(("Todos os credores da conta." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores") + " Marque um ou mais credores para filtrar as obras abaixo.")
                cred = list(cr_sel["Credor"]) or None
                ob_ = DD.agrupar(dd, "cc", mes, conta=conta, credor=cred)
                _md(f"**Por obra / centro de custo · {_txt_sel(cred or conta or [], 'todas as contas')}**")
                if ob_["linhas"]:
                    st.dataframe(pd.DataFrame({"Obra / centro de custo": [x["chave"] for x in ob_["linhas"]], ACUM: [_m(x["acumulado"]) for x in ob_["linhas"]],
                                               "%": [F.pct_br(x["acumulado"] / ob_["total"]) if ob_["total"] else "–" for x in ob_["linhas"]],
                                               _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in ob_["linhas"]]}), hide_index=True, width="stretch")
                    _cap("Obra pelo centro de custo do lançamento no pagamento." + ("" if ob_["n"] <= len(ob_["linhas"]) else f" Top {len(ob_['linhas'])} de {ob_['n']}."))


# ------------------------------------------------------------------ 5) PESSOAS
if aba_pes.open or _TODAS:
    with aba_pes:
        dfp, _fora = _pagos_df()
        info = _colaboradores()
        pj = info["pj"]
        clt = info["clt"]
        ms = PER.meses_entre(mes_ini, mes)
        n_mes = (clt + pj["total"]) if clt is not None and (pj["total"] or len(dfp)) else None
        hc_hist = list(hist["headcount"]) if hist and hist.get("headcount") else []
        hc_por_mes = {f"{hist['ate'][:4]}-{i + 1:02d}": v for i, v in enumerate(hc_hist)} if hist else {}      # historico do painel: janeiro em diante, do ano do historico
        if n_mes is None and mes in hc_por_mes:
            n_mes = hc_por_mes[mes]
        # headcount dos meses do periodo ANTES do mes de referencia (para o R$/colab. acumulado): so' conta se todos tem historico
        _antes = [m for m in ms if m < mes]
        soma_antes = sum(hc_por_mes[m] for m in _antes) if _antes and all(m in hc_por_mes for m in _antes) else None
        if not pes and not len(dfp) and not hc_por_mes:
            _info("Faltam os recibos da folha e as contas pagas deste mês.")
        else:
            rec_ref = rec
            k = st.columns(5)
            if n_mes:
                k[0].metric(f"Colaboradores {_rot(mes)}", f"{int(n_mes):,}".replace(",", "."), (f"{clt} CLT + {pj['total']} PJ" if clt is not None else None), delta_color="off", border=True)
                k[1].metric("Receita por colaborador", _mi(rec_ref / n_mes), border=True)
                k[2].metric("Custo por colaborador", _mi(cus / n_mes), border=True)
                k[3].metric("BDI por colaborador", _mi(bdi / n_mes), border=True)
            if pes:
                t = pes["folha"]["total"]
                k[4].metric(f"Horas extras + DSR {_rot(mes)}", _mi(t["hora_extra"] + t["dsr_he"]), (F.pct_br(t["he_pct"]) + " da remuneração") if t["he_pct"] is not None else None, delta_color="off", border=True)
            c1, c2 = st.columns(2)
            with c1:
                _md("**Colaboradores ativos**")
                _hc = [(m, hc_por_mes.get(m, n_mes if m == mes else None)) for m in MESES_G]       # grafico: 12 meses
                _hc = [(m, x) for m, x in _hc if x is not None]
                if _hc:
                    rots_hc = [m[5:] + "/" + m[2:4] for m, _ in _hc]
                    estilo.altair(_barras_mes(rots_hc, [x for _, x in _hc], titulo_y="colaboradores", destaque=len(_hc) - 1, divisor=1, altura=220), width="stretch")
                _cap(f"Colaboradores = CLT pelos recibos da folha + PJ pelos credores de “Salários PJ” pagos no mês" + (f" ({pj['obra']} em obras e {pj['adm']} na administração)." if pj["total"] else "."))
            with c2:
                _md("**Horas extras × receita**")
                sf = HIST.serie_he_combinada(hist, pes["serie"] if pes else [])
                ms_g = MESES_G                                                                   # grafico: sempre 12 meses ate o mes de referencia
                ev_g = DD.evolucao_he_receita(sf, ctx["serie"], ms_g)
                if sum(1 for x in ev_g if x["he_pct"] is not None) >= 2:
                    rots_g = [_rot(x["mes"]) for x in ev_g]
                    base_g = alt.Chart(pd.DataFrame({"Mês": rots_g})).encode(x=alt.X("Mês:N", sort=rots_g, axis=alt.Axis(labelAngle=-45, title=None)))
                    dfp1 = pd.DataFrame([{"Mês": _rot(x["mes"]), "%": round(x["he_pct"] * 100, 1)} for x in ev_g if x["he_pct"] is not None])
                    l_he = alt.Chart(dfp1).mark_line(point=True, color=ORANGE).encode(x=alt.X("Mês:N", sort=rots_g, axis=alt.Axis(labelAngle=-45, title=None)), y=alt.Y("%:Q", title="% HE ÷ remuneração", axis=alt.Axis(titleColor=ORANGE)),
                                                                                      tooltip=["Mês", alt.Tooltip("%:Q", title="HE ÷ remuneração (%)")])
                    var_rows = []
                    for x in ev_g:
                        if x["var_he"] is not None:
                            var_rows.append({"Mês": _rot(x["mes"]), "Série": "Custo de HE (var. %)", "Variação %": round(x["var_he"] * 100, 1)})
                        if x["var_receita"] is not None:
                            var_rows.append({"Mês": _rot(x["mes"]), "Série": "Receita (var. %)", "Variação %": round(x["var_receita"] * 100, 1)})
                    layers = [l_he]
                    if var_rows:
                        l_var = alt.Chart(pd.DataFrame(var_rows)).mark_line(point=True, strokeDash=[5, 3]).encode(
                            x=alt.X("Mês:N", sort=rots_g), y=alt.Y("Variação %:Q", title="Var. % s/ mês anterior", axis=alt.Axis(titleColor=NAVY)),
                            color=alt.Color("Série:N", scale=alt.Scale(domain=["Custo de HE (var. %)", "Receita (var. %)"], range=["#C97A00", NAVY]),
                                            legend=alt.Legend(orient="bottom", title=None)), tooltip=["Mês", "Série", alt.Tooltip("Variação %:Q", format=",.1f")])
                        layers.append(l_var)
                    estilo.altair(alt.layer(*layers).resolve_scale(y="independent").properties(height=280), width="stretch")
                    cp = DD.comparar_periodos(sf, ctx["serie"], mes_ini, mes)
                    _fv = lambda x: "n/d" if x is None else F.pct_br(x, 1)                      # noqa: E731
                    _cap(f"Período {PER_ROT} × período anterior ({PER.rotulo(cp['meses_anterior'][0], cp['meses_anterior'][-1])}): custo de HE {_fv(cp['var_he'])}"
                         + (f" ({_mi(cp['he_anterior'])} → {_mi(cp['he_atual'])})" if cp["var_he"] is not None else "") + f"; receita {_fv(cp['var_receita'])}"
                         + (f" ({_mi(cp['receita_anterior'])} → {_mi(cp['receita_atual'])})" if cp["var_receita"] is not None else "") + ". n/d = falta algum mês de dado num dos períodos.")
                    _cap("Linha cheia (laranja, eixo esquerdo) = horas extras + DSR ÷ remuneração. Linhas tracejadas (eixo direito) = quanto o custo de HE e a receita variaram sobre o mês anterior — "
                         "para ver se a HE cresce mais que o faturamento. Receita = DRE confirmado/oficial (meses em andamento ficam de fora).")
                    if {x["origem"] for x in sf} == {"historico", "app"}:
                        _cap("Atenção à comparação: os meses do histórico (painel da contabilidade) usam como base proventos menos HE, sem descontar INSS/IRRF etc.; "
                             "os meses com folha no app usam a remuneração líquida (menos todos os descontos), como a contabilidade pediu em 20/10/2026. Por isso pode haver um degrau entre as duas fontes.")
                elif pes:
                    _cap("A série mensal de HE aparece com 2 ou mais meses de folha (ou com o histórico do painel).")
            # custos prioritarios com pessoas, por colaborador
            if len(dfp):
                pdf_ = _pessoas_df(conn, mes_ini, mes, CARIMBO)
                _md("**Custos prioritários com pessoas — por colaborador**")
                tabp = DD.tabela_pessoas(pdf_, mes, n_mes, soma_antes, meses=ms)
                todas = st.radio("Linhas", ["Top 5", "Todas"], horizontal=True, key="dir_pes_linhas", label_visibility="collapsed")
                tabp_v = [x for x in tabp if x["mes"] or x["acum_antes"]] if todas == "Todas" else tabp[:5]
                if tabp_v:
                    tdf = pd.DataFrame(tabp_v)
                    tot_m = sum(x["mes"] for x in tabp)
                    _cap("Marque a caixinha de uma ou mais contas para ver credores e obras (várias marcadas somam); sem marcação = total.")
                    _tab_p = {"Conta": tdf["conta"], _rot(mes): tdf["mes"].map(_m), "% do mês": tdf["pct_mes"].map(lambda x: F.pct_br(x, 2)), "R$/colab. mês": tdf["por_colab_mes"].map(_m),
                              "Acum. até mês anterior": tdf["acum_antes"].map(_m), "R$/colab. acum.": tdf["por_colab_acum"].map(_m), "Variação": tdf["variacao"].map(lambda x: F.pct_br(x) if x is not None else "N/A")}
                    if not UM_MES:                                                           # periodo de varios meses: acrescenta o total do PERIODO (meses antes + mes de referencia)
                        _tab_p = {**{k: v for k, v in _tab_p.items() if k != "Variação"}, f"Total {ACUM}": tdf["periodo"].map(_m), f"R$/colab. {ACUM}": tdf["por_colab_periodo"].map(_m),
                                  "Variação": _tab_p["Variação"]}
                    ev_p = st.dataframe(pd.DataFrame(_tab_p), hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key="dir_pes_tab")
                    conta_p = list(_selecionadas(ev_p, tdf.rename(columns={"conta": "Conta"}))["Conta"]) or None
                    _cap(f"Contas de pessoal de obra (2.01.02) e ADM (2.02.01), sem salários CLT/PJ e premiações. Total do mês (todas as contas): {_m(tot_m)}. "
                               "R$/colab. acumulado = acumulado até o mês anterior ÷ soma do headcount mensal desses meses" + ("." if soma_antes else " (indisponível sem o headcount dos meses anteriores)."))
                    d1, d2 = st.columns(2)
                    pdf_cr = _pessoas_sem_grupo(conn, mes_ini, mes, CARIMBO)       # contabilidade 21/10: credores do grupo ENERMAIS fora das listas
                    with d1:
                        cr = DD.agrupar(pdf_cr, "credor", mes, conta=conta_p)
                        _md(f"**Principais credores · {_txt_sel(conta_p or [], 'todas as contas')}**")
                        cr_df = pd.DataFrame({"Credor": [x["chave"] for x in cr["linhas"]], "ac": [x["acumulado"] for x in cr["linhas"]], "mes": [x["mes"] for x in cr["linhas"]]})
                        cr_sel = pd.DataFrame({"Credor": []})
                        if len(cr_df):
                            ev_cr = st.dataframe(pd.DataFrame({"Credor": cr_df["Credor"], ACUM: cr_df["ac"].map(_m), "%": cr_df["ac"].map(lambda x: F.pct_br(x / cr["total"]) if cr["total"] else "–"),
                                                               _rot(mes): cr_df["mes"].map(lambda x: _m(x) if abs(x) > 0.005 else "–")}),
                                                 hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=_chave("dir_pes_cr", conta_p))
                            cr_sel = _selecionadas(ev_cr, cr_df)
                            _cap(("Todos os credores." if cr["n"] <= len(cr["linhas"]) else f"Top {len(cr['linhas'])} de {cr['n']} credores.") + " Marque um ou mais credores para filtrar as obras. Sem os credores do grupo ENERMAIS (as seis empresas).")
                    with d2:
                        cred_p = list(cr_sel["Credor"]) or None
                        ob_ = DD.agrupar(DD.rotular_obras(pdf_cr, _nomes_obras(conn, CARIMBO)), "obra_rot", mes, conta=conta_p, credor=cred_p, top=25)
                        _md(f"**Por obra · {_txt_sel(cred_p or conta_p or [], 'todas as contas')}**")
                        if ob_["linhas"]:
                            st.dataframe(pd.DataFrame({"Obra": [x["chave"] for x in ob_["linhas"]], ACUM: [_m(x["acumulado"]) for x in ob_["linhas"]],
                                                       "%": [F.pct_br(x["acumulado"] / ob_["total"]) if ob_["total"] else "–" for x in ob_["linhas"]],
                                                       _rot(mes): [_m(x["mes"]) if abs(x["mes"]) > 0.005 else "–" for x in ob_["linhas"]]}), hide_index=True, width="stretch")
                            _cap("Os centros de custo foram ligados à obra pelo de-para (ex.: “EE - ANASTACIO - LOTE 11” e “CON - ANASTACIO - LOTE 11” somam na obra ANASTÁCIO - LOTE 11), "
                                 "na mesma linguagem da aba Obras. Administração e centros sem de-para aparecem à parte."
                                 + ("" if ob_["n"] <= len(ob_["linhas"]) else f" Top {len(ob_['linhas'])} de {ob_['n']}."))
            # ---- v0.49.0: colaboradores por obra e canteiro (CLT + PJ), filtro obra -> canteiro e cards da folha consolidada
            _clt_todos = _folha_pessoas(conn, mes, CARIMBO)
            _pj_todos = pj["colaboradores"]
            _obras_sel, _cant_sel = [], []
            if _clt_todos or _pj_todos:
                _md("**Colaboradores por obra e canteiro (CLT e PJ)**")
                _opc = DD.opcoes_obras(_clt_todos, _pj_todos, _nomes_obras(conn, CARIMBO))
                _rot_op = dict(_opc)
                _k_obras = _chave("dir_pes_obras", mes, tuple(c for c, _ in _opc))
                if _clt_todos:
                    _cf = DD.cards_folha(_clt_todos)
                    _t = _cf["total"]
                    _md(f"**Folha consolidada · {_rot(mes)}**")
                    c_ = st.columns(6)
                    c_[0].metric("Colaboradores CLT", f"{_t['n']:,}".replace(",", "."), border=True)
                    c_[1].metric("Líquido da folha", _mi(_t["liquido"]), border=True)
                    c_[2].metric("HE + DSR", _mi(_t["he_dsr"]), (F.pct_br(_t["he_pct"]) + " da remuneração") if _t["he_pct"] is not None else None, delta_color="off", border=True)
                    c_[3].metric("Horas extras", DD.fmt_horas(_t["he_min"]) + (" h" if _t["he_min"] else ""), f"{_t['n_he']} colaboradores com HE", delta_color="off", border=True)
                    c_[4].metric("Pensão judicial", _m(_t["pensao"]), border=True)                       # valores pequenos: R$ exato (em mil ficava "R$ 1 mil")
                    c_[5].metric("Taxa assistencial", _m(_t["taxa_assist"]), border=True)
                    st.dataframe(pd.DataFrame([{"Empresa": e["empresa"], "Colab.": e["n"], "Líquido": _m(e["liquido"]), "HE + DSR": _m(e["he_dsr"]), "Horas extras": DD.fmt_horas(e["he_min"]),
                                                "Com HE": e["n_he"], "HE ÷ remuneração": F.pct_br(e["he_pct"]) if e["he_pct"] is not None else "–", "Pensão judicial": _m(e["pensao"]),
                                                "Taxa assistencial": _m(e["taxa_assist"])} for e in _cf["por_empresa"]]), hide_index=True, width="stretch")
                    if _cf["top_obras"]:
                        _md("**Obras com mais horas extras** (clique no botão para filtrar a lista abaixo)")
                        tc = st.columns(len(_cf["top_obras"]))
                        for col_, o_ in zip(tc, _cf["top_obras"]):
                            col_.metric(f"{o_['obra']} · {_nomes_obras(conn, CARIMBO).get(o_['obra']) or o_['nome'] or 'sem nome'}"[:40], _mi(o_["he_dsr"]),
                                        f"{DD.fmt_horas(o_['he_min'])} h · {o_['n_he']} de {o_['n']} com HE", delta_color="off", border=True)
                            col_.button("Filtrar esta obra", key=f"dir_pes_top_{o_['obra']}", on_click=_filtra_obra, args=(_k_obras, o_["obra"]), width="stretch")
                f1, f2 = st.columns(2)
                _obras_sel = f1.multiselect("Obra", [c for c, _ in _opc], format_func=lambda c: _rot_op.get(c, c), key=_k_obras, placeholder="Todas as obras")
                _cant_sel = f2.multiselect("Canteiro (CLT)", DD.opcoes_canteiros(_clt_todos, _obras_sel), key=_chave("dir_pes_cant", mes, tuple(_obras_sel)),
                                           placeholder="Todos os canteiros da obra" if _obras_sel else "Todos os canteiros")
                _cap("Marcar uma obra soma todos os canteiros dela; marcar um canteiro mostra só ele (o PJ não tem canteiro: some da lista quando um canteiro está marcado).")
                _clt_f = DD.filtrar_clt(_clt_todos, _obras_sel, _cant_sel)
                _pj_f = DD.filtrar_pj(_pj_todos, _obras_sel, _cant_sel)
                _tf = DD.somar_clt(_clt_f)
                kf = st.columns(5)
                kf[0].metric("Colaboradores na seleção", len(_clt_f) + len(_pj_f), f"{len(_clt_f)} CLT + {len(_pj_f)} PJ", delta_color="off", border=True)
                kf[1].metric("Líquido CLT", _mi(_tf["liquido"]), border=True)
                kf[2].metric("HE + DSR", _mi(_tf["he_dsr"]), border=True)
                kf[3].metric("Horas extras", DD.fmt_horas(_tf["he_min"]) + (" h" if _tf["he_min"] else ""), border=True)
                kf[4].metric("HE ÷ remuneração", F.pct_br(_tf["he_pct"]) if _tf["he_pct"] is not None else "–", border=True)
                if _clt_f:
                    with st.expander(f"CLT do mês: {len(_clt_f)} colaboradores (fonte: recibos da folha)"):
                        _bus = st.text_input("Pesquisar colaborador (nome ou cargo)", key="dir_pes_clt_busca")
                        _vis = DD.filtrar_clt(_clt_f, busca=_bus)
                        _dfc = pd.DataFrame([{"Colaborador": x["nome"], "Cargo": x["cargo"], "Empresa": x["empresa"], "Obra": x["obra"], "Canteiro": x["canteiro"], "Salário líquido": _m(x["liquido"]),
                                              "HE (horas)": DD.fmt_horas(x["he_min"]), "HE (R$)": _m(x["he"]) if x["he"] > 0.005 else "–", "DSR s/ HE (R$)": _m(x["dsr"]) if x["dsr"] > 0.005 else "–"} for x in _vis])
                        if len(_dfc):
                            _evc = st.dataframe(_dfc, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                                                key=_chave("dir_pes_clt", mes, tuple(_obras_sel), tuple(_cant_sel), _bus))
                            _rows = [r for r in _evc.selection.rows if r < len(_vis)] if _evc is not None else []
                            _ts = DD.somar_clt([_vis[r] for r in _rows] if _rows else _vis)
                            _cap(("Marcados" if _rows else "Total da lista") + f": {_ts['n']} colaboradores · líquido {_m(_ts['liquido'])} · HE {_m(_ts['he'])} em {DD.fmt_horas(_ts['he_min'])} h · DSR s/ HE {_m(_ts['dsr'])}. "
                                 "Marque a caixinha de um ou mais colaboradores para somar só eles.")
                        else:
                            _cap("Nenhum colaborador com essa busca.")
                        _cap("Fonte: recibos da folha importados (sem digitar nada). HE em horas = referência dos eventos de hora extra; HE (R$) = eventos de HE; a razão HE ÷ remuneração segue a regra da contabilidade (proventos − HE − DSR − descontos).")
            else:
                _pj_f = _pj_todos
            # folha CLT por empresa / obra (recibos) e PJ do mes
            if pes:
                fo = pes["folha"]
                with st.expander("Folha CLT do mês: por empresa e por obra"):
                    st.dataframe(pd.DataFrame([{"Empresa": e["empresa"], "Colab.": e["colab"], "Remuneração": _m(e["base_he"]), "HE + DSR": _m(e["hora_extra"] + e["dsr_he"]),
                                                "HE ÷ remuneração": F.pct_br(e["he_pct"]) if e["he_pct"] is not None else "–", "Custo (proventos + FGTS)": _m(e["custo"])} for e in fo["por_empresa"]]),
                                 hide_index=True, width="stretch")
                    po = sorted(fo["por_obra"].values(), key=lambda x: -x["colab"])
                    st.dataframe(pd.DataFrame([{"Obra": x["codigo"], "Nome": x["nome"], "Colab.": x["colab"], "Remuneração": _m(x["base_he"]), "HE + DSR": _m(x["hora_extra"] + x["dsr_he"]),
                                                "HE ÷ remuneração": F.pct_br(x["he_pct"]) if x["he_pct"] is not None else "–"} for x in po]), hide_index=True, width="stretch")
            if _pj_f:
                with st.expander(f"PJ do mês: {pj['total'] if len(_pj_f) == pj['total'] else str(len(_pj_f)) + ' de ' + str(pj['total'])} colaboradores (fonte: contas pagas “Salários PJ”)"):
                    _fant = _fantasias(conn, CARIMBO)
                    _pj_exib = DD.agrupar_pj_demais(_pj_f, _demais_pj(conn, CARIMBO))                  # cadastro: Importacoes V2 > credores > Demais colaboradores-PJ
                    _lin_pj = [({"Colaborador PJ": c["credor"], "Razão social": f"{c['n']} colaboradores", "Alocado em": c["destino"], "Pago no mês": _m(c["valor"])} if c.get("agrupado")
                                else {"Colaborador PJ": DD.nome_fantasia(c["credor"], _fant), "Razão social": c["credor"], "Alocado em": c["destino"], "Pago no mês": _m(c["valor"])}) for c in _pj_exib]
                    st.dataframe(pd.DataFrame(_lin_pj), hide_index=True, width="stretch")
                    _n_ag = next((c["n"] for c in _pj_exib if c.get("agrupado")), 0)
                    if _n_ag:
                        _cap(f"“Demais colaboradores-PJ”: {_n_ag} colaboradores cadastrados para aparecer somados numa linha só (o total de {pj['total']} colaboradores acima continua contando todos).")
                    if not _fant:
                        _cap("Nome fantasia: ainda não carregado. Executar o SQL-30 e clicar em “Atualizar cadastros” no Painel EnerMais (aba de sincronização) para mostrar o nome fantasia no lugar da razão social.")
                    _cap("Regra (contabilidade, 20/10/2026): a fonte do PJ são as contas pagas, sem regras próprias. Cada credor com valor positivo conta 1 colaborador, alocado na obra (ou na administração) "
                               "onde recebeu mais no mês.")


# ------------------------------------------------------------------ 6) FOLHA PJ (ao lado de Pessoas; Sienge + Flash + mapa de colaboradores)
if aba_pj.open or _TODAS:
    with aba_pj:
        if mes_ini != mes:
            _cap(f"A Folha PJ mostra sempre o mês de referência ({_rot(mes)}), não soma o período.")
        FPU.aba_folha_pj(conn, mes, CARIMBO, _rot(mes))


# ------------------------------------------------------------------ 7) INDICADORES FINANCEIROS  e  8) FINANCIAMENTOS (so' Sienge)
if aba_ind.open or _TODAS:
    with aba_ind:
        DI.aba_indicadores(conn, mes_ini, mes, CARIMBO)

if aba_fin.open or _TODAS:
    with aba_fin:
        DI.aba_financiamentos(conn, CARIMBO)

# ------------------------------------------------------------------ 8) INVESTIMENTOS (o restante do 2.05; separado dos financiamentos, o editor decide se o visualizador ve)
def _controle_investimentos():
    """So' o editor: checkbox que libera (ou esconde) esta aba para o login de visualizacao. Efeito na proxima vez que o visualizador abrir o painel."""
    if not _eh_editor:
        return
    if not acesso.config_instalada(conn):
        _warn("Falta executar o **SQL-29** (`sql/v2_config.sql`) no Supabase para poder liberar esta aba ao visualizador. Até lá, só o editor vê.")
        return
    atual = acesso.investimentos_para_visualizador(conn)
    novo = st.checkbox("Mostrar a aba Investimentos para quem entra com login de visualização", value=atual, key="dir_inv_visu",
                       help="Desmarcado (padrão): só quem edita vê esta aba. Marque para liberar ao visualizador. Dá para desmarcar de novo quando quiser.")
    if novo != atual:
        try:
            acesso.definir_investimentos_para_visualizador(conn, novo, usuario)
            _acessos.clear()
            st.toast("Aba Investimentos " + ("liberada para o visualizador." if novo else "escondida do visualizador."), icon="✅")
        except Exception as exc:
            st.error(f"Não consegui salvar a escolha: {exc}")
    _cap("Quem edita sempre vê esta aba. " + ("Hoje o visualizador **vê**." if novo else "Hoje o visualizador **não vê**."))


if aba_inv is not None and (aba_inv.open or _TODAS):
    with aba_inv:
        DI.aba_financiamentos(conn, CARIMBO, "investimentos", _controle_investimentos)


if _eh_editor:
    _cap(f"Tempo para montar esta tela: {time.perf_counter() - _T0:.1f} s (cabeçalho {_T_CAB:.1f} s · dados do mês {_T_CTX:.1f} s · abas e tabelas o restante). Só quem edita vê esta linha.")
