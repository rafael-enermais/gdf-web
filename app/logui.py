# -*- coding: utf-8 -*-
"""GDF — log organizado por categoria (Importações, Relatórios, Edições, Erros e avisos) e painel de importação.
Só leitura do que já está na tabela `evento`; a única escrita é registrar tentativas de importação que não gravaram nada."""
import pandas as pd
import streamlit as st

import db
from fuso import fmt_br

CATEGORIAS = ("Importações", "Relatórios", "Edições")
ROTULO_ORIGEM = {"importar": "Importação", "historico": "Histórico", "mapa": "Mapa de contas", "composicao": "Apelidos", "relatorio": "Relatório"}
ROTULO_NIVEL = {"info": "Info", "aviso": "Aviso", "erro": "Erro"}


def categoria_evento(origem: str, mensagem: str = "") -> str:
    """Importações / Relatórios / Edições (ou 'Outros'). Erros e avisos são tratados à parte, pelo nível."""
    if origem in ("importar", "historico"):
        return "Importações"
    if origem == "relatorio":
        return "Edições" if (mensagem or "").startswith("Configuração") else "Relatórios"
    if origem in ("mapa", "composicao"):
        return "Edições"
    return "Outros"


def tabela_eventos(eventos: list) -> pd.DataFrame:
    return pd.DataFrame([{"Quando": fmt_br(e["criado_em"]), "Nível": ROTULO_NIVEL.get(e["nivel"], e["nivel"]),
                          "Tipo": ROTULO_ORIGEM.get(e["origem"], e["origem"]), "Mensagem": e["mensagem"], "Usuário": e["usuario"]} for e in eventos])


def _mostrar(eventos: list, vazio: str) -> None:
    if eventos:
        st.dataframe(tabela_eventos(eventos), hide_index=True, width="stretch")
    else:
        st.caption(vazio)


def abas_log(eventos: list) -> None:
    """Abas do log: Todos · Importações · Relatórios · Edições · Erros e avisos (com a contagem em cada rótulo)."""
    por_cat = {c: [e for e in eventos if categoria_evento(e["origem"], e["mensagem"]) == c] for c in CATEGORIAS}
    problemas = [e for e in eventos if e["nivel"] in ("erro", "aviso")]
    nomes = [f"Todos ({len(eventos)})"] + [f"{c} ({len(por_cat[c])})" for c in CATEGORIAS] + [f"Erros e avisos ({len(problemas)})"]
    abas = st.tabs(nomes)
    with abas[0]:
        _mostrar(eventos, "Sem eventos.")
    for aba, c in zip(abas[1:4], CATEGORIAS):
        with aba:
            _mostrar(por_cat[c], "Nada registrado nesta categoria.")
    with abas[4]:
        _mostrar(problemas, "Nenhum erro ou aviso. ✅")


def registrar_uma_vez(conn, chave, origem: str, nivel: str, mensagem: str, empresa_id=None, usuario=None) -> None:
    """Grava no log uma tentativa que não gravou nada (arquivo repetido, ilegível...), uma única vez por sessão e por arquivo.
    O Streamlit roda a tela de novo a cada clique; sem isso a mesma linha se repetiria."""
    vistos = st.session_state.setdefault("_log_vistos", set())
    if chave in vistos:
        return
    vistos.add(chave)
    db.registrar_evento(conn, origem, nivel, mensagem[:400], empresa_id=empresa_id, usuario=usuario)


def painel_importacao(conn, empresas: list) -> None:
    """Quadro no fim da tela Importar: últimas importações e o log de importação, para acompanhar conforme os arquivos entram."""
    st.divider()
    st.subheader("Log de importação")
    st.caption("Acompanhe aqui o que entrou, o que foi ignorado (arquivo repetido) e os erros. O log completo, por categoria, fica em **Histórico → Log de eventos**.")
    imps = []
    for emp in empresas:
        imps += db.listar_importacoes(conn, emp["id"])
    imps.sort(key=lambda i: i["id"], reverse=True)
    aba_imp, aba_ev = st.tabs([f"Últimas importações ({min(len(imps), 10)})", "Eventos recentes"])
    with aba_imp:
        if not imps:
            st.caption("Nenhuma importação ainda.")
        else:
            st.dataframe(pd.DataFrame([{
                "#": i["id"], "Arquivo": i["arquivo_nome"],
                "Período": (f"{i['periodo_fim']:%m/%Y}" if i["tipo"] == "MENSAL" else f"{i['periodo_ini']:%d/%m/%Y} a {i['periodo_fim']:%d/%m/%Y}"),
                "Tipo": "Mês" if i["tipo"] == "MENSAL" else "Acumulado", "Status": i["status"], "Ativa": "sim" if i["ativo"] else "não (desfeita)",
                "Falhas": int(i["falhas"]), "Por": i["importado_por"], "Em": fmt_br(i["importado_em"])} for i in imps[:10]]),
                hide_index=True, width="stretch")
    with aba_ev:
        ev = []
        for emp in empresas:
            ev += db.listar_eventos(conn, emp["id"], limite=80)
        vistos, unicos = set(), []
        for e in ev:                                  # eventos sem empresa aparecem em todas as consultas: tira a repetição
            k = (e["criado_em"], e["mensagem"], e["usuario"])
            if k not in vistos:
                vistos.add(k)
                unicos.append(e)
        unicos.sort(key=lambda e: e["criado_em"], reverse=True)
        _mostrar([e for e in unicos if categoria_evento(e["origem"], e["mensagem"]) == "Importações"][:15], "Nenhum evento de importação ainda.")
