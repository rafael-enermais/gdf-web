# -*- coding: utf-8 -*-
"""GDF - Dexie: a assistente de IA do app. So' para quem EDITA (o login de visualizacao da diretoria nem registra esta pagina).
Conversa em linguagem natural, consulta os dados do app por ferramentas de LEITURA (dexie_ferramentas), consulta a base de conhecimento (contabilidade, tributos,
reforma tributaria), desenha graficos e gera relatorio (PDF/Excel) da ultima consulta, e pode PROPOR acoes (sincronizar o Sienge, atualizar cadastros) que so' rodam
depois do clique em "Confirmar e executar". Memoria enxuta por usuario (SQL-31, ultimas 24 mensagens); sem o SQL-31 a conversa vive so' na sessao.
Chave da IA: secret ANTHROPIC_API_KEY (nunca no codigo).

Licoes de layout do EGC/TIA aplicadas aqui (veja o vault: TIA.go/erros-observacoes.md):
  * st.chat_input so' fica fixo no rodape quando esta no CORPO da pagina (fora de colunas/containers) -> fica no fim do script, no nivel de cima;
  * historico num container de altura fixa (rola por dentro) e a mensagem nova NUNCA e' desenhada a mao: padrao de 2 fases (grava no session_state + rerun,
    depois processa + rerun), assim a ordem das mensagens nunca quebra, por mais que a IA demore;
  * '$' escapado so' na hora de mostrar (senao 'R$ ... R$' vira formula e engole o negrito);
  * eixo do grafico com a ordem original (nao deixa o Vega reordenar por ordem alfabetica);
  * o prompt recebe o e-mail de quem esta logado (nada de adivinhar o nome).
"""
import io

import altair as alt
import pandas as pd
import streamlit as st

import acesso
import dexie_acoes as DA
import dexie_aprendizado as APR
import dexie_chat as DC
import dexie_memoria as DM
import dexie_relatorio as DR
import estilo
import painel_db as P
from auth import usuario_atual
from conexao import get_conn, sidebar_rodape
from fuso import agora_br

NAVY, ORANGE, AZUL = "#171C60", "#F99D20", "#5C6091"
ALTURA_CHAT = 520          # altura minima (px) do quadro da conversa; o CSS abaixo a ajusta a altura da janela

# O quadro da conversa acompanha a altura da tela (some o vazio embaixo em tela grande; em tela pequena nao passa de um minimo legivel).
st.markdown("""<style>
/* o Streamlit fixa a altura do quadro no ENVOLTORIO (flex 0 0 520px), por isso o CSS mexe nele e o quadro enche o envoltorio */
[data-testid="stLayoutWrapper"]:has(> .st-key-dexie_chat_box){ flex: 0 0 auto !important; height: max(22rem, calc(100vh - 24rem)) !important; }
.st-key-dexie_chat_box{ flex: 1 1 auto !important; height: 100% !important; max-height: none !important; }
</style>""", unsafe_allow_html=True)

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title(f"{DC.NOME} — assistente do GDF")
estilo.painel_adaptavel()

try:                                                   # defesa em profundidade: o menu do visualizador ja nao tem esta pagina
    if acesso.papel(conn, usuario) == acesso.VISUALIZADOR:
        st.error("Esta página é só para quem edita o app.")
        st.stop()
except Exception:                                      # banco fora do ar: nao libera por engano
    st.error("Não foi possível verificar o seu acesso agora. Tente novamente em instantes.")
    st.stop()


def _segredo(nome: str):
    try:
        return st.secrets[nome] if nome in st.secrets else None
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _cliente(chave: str):
    import anthropic
    return anthropic.Anthropic(api_key=chave, timeout=90.0, max_retries=2)


def _sem_latex(t: str) -> str:
    return t.replace("$", "\\$")


def _excel(tab: list) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(tab).to_excel(buf, index=False, sheet_name="Consulta")
    return buf.getvalue()


def _grafico(tab: list, g: dict):
    df = pd.DataFrame(tab)
    x, y = g["x"], g["y"]
    longo = df.melt(id_vars=[x], value_vars=y, var_name="Série", value_name="Valor").rename(columns={x: "Categoria"})
    longo["Valor"] = pd.to_numeric(longo["Valor"], errors="coerce")
    ordem = list(dict.fromkeys(df[x].astype(str)))                    # ordem original (o Vega reordenaria por ordem alfabetica)
    longo["Categoria"] = longo["Categoria"].astype(str)
    cor = alt.Color("Série:N", scale=alt.Scale(range=[NAVY, ORANGE, AZUL]), legend=alt.Legend(orient="bottom", title=None) if len(y) > 1 else None)
    tip = ["Categoria", "Série", alt.Tooltip("Valor:Q", format=",.2f")]
    base = alt.Chart(longo).properties(height=380, title=g.get("titulo") or "")
    if g["tipo"] == "linhas":
        c = base.mark_line(point=True).encode(x=alt.X("Categoria:N", sort=ordem, axis=alt.Axis(labelAngle=-30, title=None)), y=alt.Y("Valor:Q", title=None), color=cor, tooltip=tip)
    elif g["tipo"] == "barras_horizontais":
        c = base.mark_bar().encode(y=alt.Y("Categoria:N", sort=ordem, axis=alt.Axis(title=None)), x=alt.X("Valor:Q", title=None), color=cor, yOffset="Série:N", tooltip=tip)
    else:
        c = base.mark_bar().encode(x=alt.X("Categoria:N", sort=ordem, axis=alt.Axis(labelAngle=-30, title=None)), y=alt.Y("Valor:Q", title=None), color=cor, xOffset="Série:N", tooltip=tip)
    estilo.altair(c, width="stretch")


_ROTULO_TIPO = {"regra": "Regra da casa", "definicao": "Definição", "conhecimento": "Conhecimento"}


def _chave_tabela_anotacoes() -> str:
    return f"dexie_an_tabela_{st.session_state.get('dexie_an_geracao', 0)}"


def _limpa_selecao_anotacoes():
    """Troca a chave da tabela: ela volta sem linha marcada (o clique antigo apontava para um numero de linha que mudou)."""
    st.session_state["dexie_an_geracao"] = st.session_state.get("dexie_an_geracao", 0) + 1


def _resumo(t: str, n: int = 90) -> str:
    t = " ".join(str(t or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _editor_anotacao(conn, usuario, a):
    """Editor da anotacao escolhida na tabela: ver, editar (versao nova, a antiga fica guardada), desativar ou reativar. Nada se apaga."""
    ativa = a["status"] == "ativo"
    st.markdown(f"**{_sem_latex(a['titulo'])}** · {_ROTULO_TIPO.get(a['tipo'], a['tipo'])} · {'ativa' if ativa else 'desativada'}")
    quem = "sugerida pela Dexie" if a["origem"] == "dexie" else "digitada"
    extra = "" if ativa else f" · desativada por {a['revisado_por'] or '—'}: {a['motivo'] or '—'}"
    st.caption(_sem_latex(f"Guardada em {a['criado_em']} por {a['criado_por']} ({quem}){' · substitui a anotação nº ' + str(a['substitui_id']) if a['substitui_id'] else ''}{extra}"))
    if not ativa:
        st.markdown(_sem_latex(a["texto"]))
        if st.button("Reativar esta anotação", key=f"dexie_reativa_{a['id']}"):
            try:
                APR.reativar(conn, usuario, a["id"])
                P.registrar_log(conn, "DEXIE_ANOTACAO", "INFO", usuario, None, {"acao": "reativar", "titulo": a["titulo"][:80]})
                _limpa_selecao_anotacoes()
                st.rerun()
            except APR.ErroAnotacao as exc:
                st.error(str(exc))
        return
    with st.form(f"dexie_edita_{a['id']}"):
        tipo = st.selectbox("Tipo", list(APR.TIPOS), index=list(APR.TIPOS).index(a["tipo"]), format_func=lambda t: _ROTULO_TIPO[t], key=f"dexie_ety_{a['id']}")
        nt = st.text_input("Título", value=a["titulo"], max_chars=APR.MAX_TITULO, key=f"dexie_et_{a['id']}")
        nx = st.text_area("Texto (a regra ou definição, sem valores de período nem dados pessoais)", value=a["texto"], max_chars=APR.MAX_TEXTO, height=140, key=f"dexie_ex_{a['id']}")
        nf = st.text_input("Fonte (opcional)", value=a["fonte"] or "", max_chars=APR.MAX_FONTE, key=f"dexie_ef_{a['id']}")
        c1, c2 = st.columns(2)
        salvar = c1.form_submit_button("Salvar nova versão", type="primary")
        desat = c2.form_submit_button("Desativar")
    if salvar:
        try:
            APR.editar(conn, usuario, a["id"], tipo, nt, nx, nf)
            P.registrar_log(conn, "DEXIE_ANOTACAO", "INFO", usuario, None, {"acao": "editar", "titulo": nt[:80]})
            _limpa_selecao_anotacoes()                                       # a linha escolhida mudou de numero: tabela nova, sem linha marcada
            st.rerun()
        except APR.ErroAnotacao as exc:
            st.error(str(exc))
    if desat:
        if APR.desativar(conn, usuario, a["id"], "desativada na tela"):
            P.registrar_log(conn, "DEXIE_ANOTACAO", "INFO", usuario, None, {"acao": "desativar", "titulo": a["titulo"][:80]})
        _limpa_selecao_anotacoes()
        st.rerun()


def _anotacoes(conn, usuario):
    """Aba 'Anotacoes': o que a Dexie aprendeu (aprovado pela equipe). Visao geral em tabela (busca/filtros), clique na linha para editar
    (versao nova), desativar ou reativar; adicionar. Nada se apaga."""
    if not APR.instalado(conn):
        st.info("As anotações ainda não estão ativas: falta rodar o **SQL-33** no Supabase (arquivo `sql/v2_dexie_aprendizado.sql`). Enquanto isso a Dexie funciona normal, só não guarda anotações.")
        return
    st.caption("Regras da casa, definições e conhecimento que a equipe aprovou. A Dexie consulta isto nas conversas, mas não muda regra de segurança nem executa nada por causa daqui. Ela só sugere; vale depois do seu clique.")
    todas = APR.listar(conn, None)
    ativas = [x for x in todas if x["status"] == "ativo"]
    if not ativas:
        st.caption("Nenhuma anotação ativa ainda. Ensine uma regra à Dexie na conversa ou adicione abaixo.")
    if todas:
        f1, f2, f3 = st.columns([3, 2, 2])
        busca = f1.text_input("Buscar", placeholder="palavra do título, texto ou fonte", key="dexie_an_busca", label_visibility="collapsed")
        situacao = f2.selectbox("Situação", ["Ativas", "Desativadas", "Todas"], key="dexie_an_situacao", label_visibility="collapsed")
        tipo_f = f3.selectbox("Tipo", ["Todos os tipos"] + list(APR.TIPOS), format_func=lambda t: _ROTULO_TIPO.get(t, t), key="dexie_an_tipo", label_visibility="collapsed")
        termo = busca.strip().lower()
        vistas = [x for x in todas
                  if (situacao == "Todas" or (x["status"] == "ativo") == (situacao == "Ativas"))
                  and (tipo_f.startswith("Todos") or x["tipo"] == tipo_f)
                  and (not termo or termo in f"{x['titulo']} {x['texto']} {x['fonte'] or ''}".lower())]
        st.caption(f"{len(ativas)} ativa(s) · {len(todas) - len(ativas)} desativada(s) (versões antigas ficam guardadas) · mostrando {len(vistas)}. Clique numa linha para ver e editar.")
        if vistas:
            df = pd.DataFrame([{"Nº": x["id"], "Título": x["titulo"], "Tipo": _ROTULO_TIPO.get(x["tipo"], x["tipo"]), "Resumo": _resumo(x["texto"]),
                                "Fonte": x["fonte"] or "—", "Situação": "Ativa" if x["status"] == "ativo" else "Desativada", "Guardada em": x["criado_em"]} for x in vistas])
            ev = st.dataframe(df, hide_index=True, width="stretch", height=int(min(max(len(df) * 35 + 40, 75), 300)),
                              on_select="rerun", selection_mode="single-row", key=_chave_tabela_anotacoes())
            linhas = list(ev.selection.rows) if ev is not None and ev.selection else []
            if linhas and linhas[0] < len(vistas):
                with st.container(border=True):
                    _editor_anotacao(conn, usuario, vistas[linhas[0]])
        else:
            st.caption("Nenhuma anotação com esse filtro.")
    with st.expander("Adicionar anotação"):
        with st.form("dexie_nova_anotacao", clear_on_submit=True):
            tipo = st.selectbox("Tipo", list(APR.TIPOS), format_func=lambda t: _ROTULO_TIPO[t])
            titulo = st.text_input("Título", max_chars=APR.MAX_TITULO)
            texto = st.text_area("Texto (a regra ou definição, sem valores de período nem dados pessoais)", max_chars=APR.MAX_TEXTO)
            fonte = st.text_input("Fonte (opcional)", max_chars=APR.MAX_FONTE)
            if st.form_submit_button("Guardar"):
                try:
                    APR.guardar(conn, usuario, tipo, titulo, texto, fonte, origem="pessoa")
                    P.registrar_log(conn, "DEXIE_ANOTACAO", "INFO", usuario, None, {"acao": "adicionar", "titulo": titulo[:80], "tipo": tipo})
                    st.rerun()
                except APR.ErroAnotacao as exc:
                    st.error(str(exc))


# ------------------------------------------------------------------ estado da conversa
S = st.session_state
S.setdefault("dexie_estado", DC.novo_estado())
S.setdefault("dexie_n", 0)
S.setdefault("dexie_avisos", [])
if "dexie_hist" not in S:                               # 1a abertura da sessao: relê a memoria do usuario (ultimas 24 mensagens), se o SQL-31 existir
    S["dexie_memoria_ativa"] = DM.instalado(conn)
    S["dexie_hist"] = DM.carregar(conn, usuario) if S["dexie_memoria_ativa"] else []
estado = S["dexie_estado"]

chave = _segredo("ANTHROPIC_API_KEY")
modelo = _segredo("ANTHROPIC_MODEL") or DC.MODELO_PADRAO
if not chave:
    st.warning("A chave da IA ainda não está configurada. Cadastre o secret **ANTHROPIC_API_KEY** em Streamlit Cloud → Settings → Secrets (a chave nunca vai para o repositório) e reinicie o app.")

st.caption("Eu **leio** os dados do app (não gravo, não apago e não importo nada), consulto contabilidade e reforma tributária e **proponho** ações que só executo depois do seu clique.")
_MEMORIA = ("Memória ativa (últimas 24 mensagens)." if S.get("dexie_memoria_ativa")
            else "Memória desligada (falta o SQL-31).")

# ------------------------------------------------------------------ caixa de digitacao: no CORPO da pagina (fixa no rodape) e fase 1 do envio
pergunta = st.chat_input(f"Pergunte à {DC.NOME}…", max_chars=DC.MAX_PERGUNTA, disabled=not chave) or S.pop("dexie_sugestao", None)
if pergunta and chave and not S.get("dexie_pendente"):
    if S["dexie_n"] >= DC.LIMITE_PERGUNTAS_SESSAO:
        S["dexie_avisos"] = [("aviso", f"Limite de {DC.LIMITE_PERGUNTAS_SESSAO} perguntas nesta conversa (controle de custo). Clique em **Nova conversa** para continuar.")]
    else:
        S["dexie_avisos"] = []
        S["dexie_hist"].append({"role": "user", "content": pergunta})
        S["dexie_pendente"] = pergunta
        DM.gravar(conn, usuario, "user", pergunta)
        st.rerun()                                                  # fase 1: a pergunta ja aparece no historico antes de a IA responder

c_chat, c_painel = st.columns([3, 2], gap="large")

with c_chat:
    topo = st.columns([2, 2, 3], vertical_alignment="center")
    topo[2].caption(_MEMORIA)
    if topo[0].button("Nova conversa", key="dexie_nova", disabled=bool(S.get("dexie_pendente"))):
        DM.arquivar(conn, usuario)                                  # arquiva, nunca apaga
        S["dexie_hist"], S["dexie_estado"], S["dexie_n"], S["dexie_avisos"] = [], DC.novo_estado(), 0, []
        st.rerun()
    if S["dexie_hist"]:
        md = "\n\n".join(f"**{'Você' if m['role'] == 'user' else DC.NOME}:** {m['content']}" for m in S["dexie_hist"])
        topo[1].download_button("Baixar conversa", md.encode("utf-8"), "conversa_dexie.md", "text/markdown", key="dexie_baixar")

    historico = st.container(height=ALTURA_CHAT, border=True, key="dexie_chat_box")       # rola por dentro; altura vem do CSS acima (adaptativa)
    with historico:
        if not S["dexie_hist"]:
            st.markdown(f"Oi! Eu sou a {DC.NOME}. Posso consultar os números do GDF, explicar contabilidade e a reforma tributária, montar gráficos e relatórios. Algumas ideias:")
            sug = ["O que tem de dado no banco hoje? Quais meses estão completos?",
                   "Como foi o resultado do ano até o último mês com DRE confirmado?",
                   "Quais as 10 maiores despesas do último mês, por credor?",
                   "O Sienge está atualizado? Quando foi a última busca?",
                   "Explique a reforma tributária e o impacto para construção e incorporação.",
                   "Qual o cronograma da transição do IBS e da CBS até 2033?"]
            for i, s_ in enumerate(sug):
                if st.button(s_, key=f"dexie_sug_{i}", disabled=not chave, width="stretch"):
                    S["dexie_sugestao"] = s_
                    st.rerun()
        for m in S["dexie_hist"]:
            with st.chat_message("user" if m["role"] == "user" else "assistant"):
                st.markdown(_sem_latex(m["content"]))
        if S.get("dexie_pendente") and chave:                       # fase 2: processa dentro do historico e so' entao grava a resposta
            with st.chat_message("assistant"):
                with st.spinner(f"{DC.NOME} está consultando…"):
                    r = DC.responder(_cliente(chave), conn, modelo, S["dexie_hist"][:-1], S["dexie_pendente"], usuario, estado)
            S["dexie_hist"].append({"role": "assistant", "content": r["texto"]})
            S["dexie_n"] += 1
            DM.gravar(conn, usuario, "assistant", r["texto"])
            P.registrar_log(conn, "DEXIE_PERGUNTA", "INFO" if r["ok"] else "AVISO", usuario, None,
                            {"caracteres": len(S["dexie_pendente"]), "ferramentas": r["ferramentas"][:12], "ok": r["ok"], **({"erro": r["erro"]} if r.get("erro") else {}), **({"valores_a_conferir": r["conferir"]} if r.get("conferir") else {})})
            S["dexie_pendente"] = None
            st.rerun()

    for nivel, texto in S["dexie_avisos"]:                 # resultado da ultima acao confirmada / avisos (sobrevivem ao rerun)
        {"ok": st.success, "aviso": st.warning}.get(nivel, st.error)(_sem_latex(texto))

    pend = estado.get("acao_pendente")
    if pend:                                                # cartao de aprovacao: so' executa com o clique
        with st.container(border=True):
            st.markdown("**Ação proposta — aguardando a sua confirmação**")
            st.markdown(_sem_latex(pend["descricao"]))
            if pend.get("motivo"):
                st.caption(_sem_latex(f"Motivo: {pend['motivo']}"))
            b1, b2, _ = st.columns([1.2, 1, 3])
            if b1.button("Confirmar e executar", type="primary", key="dexie_confirma"):
                with st.spinner("Executando… (a busca no Sienge pode levar de 1 a 3 minutos)"):
                    r = DA.executar(conn, pend["acao"], usuario, st.secrets)
                st.cache_data.clear()                      # os paineis releem o banco
                S["dexie_avisos"] = [(n, t) for n, t in r["mensagens"]]
                msg = ("Ação executada: " if r["ok"] else "A ação terminou com problemas: ") + pend["descricao"]
                S["dexie_hist"].append({"role": "assistant", "content": msg})
                DM.gravar(conn, usuario, "assistant", msg)
                estado["acao_pendente"] = None
                st.rerun()
            if b2.button("Cancelar", key="dexie_cancela"):
                S["dexie_hist"].append({"role": "assistant", "content": "Ação cancelada. Nada foi executado."})
                DM.gravar(conn, usuario, "assistant", "Ação cancelada. Nada foi executado.")
                estado["acao_pendente"] = None
                st.rerun()

    apr = estado.get("aprendizado_pendente")
    if apr:                                                 # cartao de anotacao: so' guarda com o clique de quem edita
        with st.container(border=True):
            st.markdown("**Anotação sugerida — vale só depois da sua confirmação**")
            st.markdown(_sem_latex(f"**{apr['titulo']}** ({apr['tipo']})"))
            st.markdown(_sem_latex(apr["texto"]))
            if apr.get("fonte"):
                st.caption(_sem_latex(f"Fonte: {apr['fonte']}"))
            a1, a2, _ = st.columns([1.3, 1, 3])
            if a1.button("Guardar anotação", type="primary", key="dexie_guarda_anotacao"):
                try:
                    APR.guardar(conn, usuario, apr["tipo"], apr["titulo"], apr["texto"], apr.get("fonte"), origem="dexie")
                    P.registrar_log(conn, "DEXIE_ANOTACAO", "INFO", usuario, None, {"titulo": apr["titulo"][:80], "tipo": apr["tipo"], "origem": "dexie"})
                    msg = f"Anotação guardada: {apr['titulo']}. Vou considerá-la nas próximas conversas."
                except APR.ErroAnotacao as exc:
                    msg = f"Não guardei a anotação: {exc}"
                S["dexie_hist"].append({"role": "assistant", "content": msg})
                DM.gravar(conn, usuario, "assistant", msg)
                estado["aprendizado_pendente"] = None
                st.rerun()
            if a2.button("Descartar", key="dexie_descarta_anotacao"):
                S["dexie_hist"].append({"role": "assistant", "content": "Anotação descartada. Nada foi guardado."})
                DM.gravar(conn, usuario, "assistant", "Anotação descartada. Nada foi guardado.")
                estado["aprendizado_pendente"] = None
                st.rerun()

# ------------------------------------------------------------------ painel ao lado: tabela, grafico e relatorio da ultima consulta
with c_painel:
    st.markdown("**Última consulta**")
    tab = estado.get("ultima_tabela")
    g = estado.get("grafico")
    aba_t, aba_g, aba_r, aba_a = st.tabs(["Tabela", "Gráfico", "Relatório", "Anotações"])
    with aba_t:
        if not tab:
            st.caption("Quando eu consultar os dados, a tabela, o gráfico e o relatório aparecem aqui.")
        else:
            st.caption(f"Consulta: {estado.get('ultima_ferramenta')} · {len(tab)} linhas")
            st.dataframe(pd.DataFrame(tab), hide_index=True, width="stretch", height=int(min(max(len(tab) * 35 + 38, 110), 560)))   # altura pelo numero de linhas (sem vazio)
            st.download_button("Baixar em Excel", _excel(tab), "consulta_dexie.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dexie_excel")
    with aba_g:
        if g and tab:
            _grafico(tab, g)
        else:
            st.caption("Peça um gráfico (ex.: “faça um gráfico de barras disso”) e ele aparece aqui.")
    with aba_r:
        if tab:
            st.caption("Relatório em PDF no padrão EnerMais: título, resumo da última resposta, gráfico (se houver) e a tabela.")
            titulo_pdf = st.text_input("Título do relatório", value=(g or {}).get("titulo") or f"Consulta — {estado.get('ultima_ferramenta')}", key="dexie_titulo_pdf", max_chars=80)
            com_resumo = st.checkbox("Incluir a última resposta da Dexie como resumo", value=True, key="dexie_com_resumo")
            if st.button("Gerar PDF", key="dexie_gerar_pdf"):
                resumo = next((m["content"] for m in reversed(S["dexie_hist"]) if m["role"] == "assistant"), "") if com_resumo else ""
                try:
                    S["dexie_pdf"] = DR.gerar_pdf(titulo_pdf, tab, g, resumo, usuario, agora_br().strftime("%d/%m/%Y %H:%M"), f"Consulta: {estado.get('ultima_ferramenta')} · dados do banco do GDF")
                    P.registrar_log(conn, "DEXIE_RELATORIO", "INFO", usuario, None, {"consulta": estado.get("ultima_ferramenta"), "linhas": len(tab), "grafico": bool(g)})
                except Exception:                                    # noqa: BLE001
                    S.pop("dexie_pdf", None)
                    st.error("Não consegui montar o PDF desta consulta. A tabela continua disponível em Excel.")
            if S.get("dexie_pdf"):
                st.download_button("Baixar o PDF", S["dexie_pdf"], "relatorio_dexie.pdf", "application/pdf", key="dexie_baixar_pdf")
            st.divider()
        else:
            st.caption("O relatório da consulta aparece quando eu consultar os dados.")
        st.caption("PDF da conversa inteira (perguntas e respostas, em ordem).")
        if st.button("Gerar PDF da conversa", key="dexie_gerar_conversa", disabled=not S["dexie_hist"]):
            try:
                S["dexie_pdf_conversa"] = DR.gerar_conversa_pdf(S["dexie_hist"], usuario, agora_br().strftime("%d/%m/%Y %H:%M"))
                P.registrar_log(conn, "DEXIE_RELATORIO", "INFO", usuario, None, {"consulta": "conversa", "mensagens": len(S["dexie_hist"])})
            except Exception:                                        # noqa: BLE001
                S.pop("dexie_pdf_conversa", None)
                st.error("Não consegui montar o PDF da conversa. O botão 'Baixar conversa' (texto) continua disponível.")
        if S.get("dexie_pdf_conversa"):
            st.download_button("Baixar o PDF da conversa", S["dexie_pdf_conversa"], "conversa_dexie.pdf", "application/pdf", key="dexie_baixar_conversa")
    with aba_a:
        _anotacoes(conn, usuario)
