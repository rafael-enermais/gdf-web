# -*- coding: utf-8 -*-
"""
GDF — Gestão de Demonstrativo Financeiro (ponto de entrada Streamlit).

As telas ficam em app/telas/ (fora de qualquer pasta chamada "pages") para que o menu so' exista depois do login:
st.navigation()/st.Page() e' a UNICA fonte da lista de paginas (mesma solucao do EGC).
"""
import streamlit as st

from auth import require_login
import db
import situacao
from conexao import NOME_APP, empresa_atual, get_conn, mostrar_flash, sidebar_rodape

st.set_page_config(page_title="GDF — EnerMais", page_icon="📑", layout="wide")

usuario_logado = require_login()      # st.stop() aqui se nao autenticado


def pagina_inicio():
    st.title(NOME_APP)
    mostrar_flash()
    st.markdown(
        "Importe o balancete do mês (**CSV** ou **PDF** do sistema contábil), confira os avisos e veja o **Balanço**, a **DRE**, os "
        "**indicadores** e a **composição de saldos**, e gere o **relatório em PDF**. Nada é apagado: cada importação pode ser desfeita e reativada no **Histórico**.\n\n"
        "1. **Importar balancete** — envie o CSV ou o PDF de cada mês de janeiro até o mês do relatório.\n"
        "2. **Demonstrativos** — escolha o mês e veja Balanço, DRE, indicadores, composição de saldos e conferências.\n"
        "3. **Relatório PDF** — gera o relatório do mês (textos editáveis, assinantes, versões).\n"
        "4. **Painel** — KPIs e evolução mês a mês para estudo e acompanhamento do histórico.\n"
        "5. **Histórico** — importações, status (rascunho/revisada), desfazer e o log por categoria (importações, relatórios, edições, erros e avisos).\n"
        "6. **Mapa de contas** — como cada conta do balancete vira uma linha do demonstrativo (editável, com histórico).\n"
        "7. **Ajuda** — fluxo do mês, o que fazer quando uma conferência falha e glossário."
    )
    sidebar_rodape()
    _quadro_situacao()


def _quadro_situacao():
    """Quadro 'onde estou' do ano: mes a mes, balancete, status, falhas e relatorio + proxima acao."""
    import pandas as pd
    conn = get_conn()
    st.subheader("Situação do ano")
    for emp in empresa_atual(conn):
        imps = db.listar_importacoes(conn, emp["id"])
        anos = situacao.anos_com_dados(imps)
        if not anos:
            st.info(f"{emp['razao_social']}: ainda não há balancete mensal importado. Comece por **Importar balancete**.")
            continue
        ano = anos[0] if len(anos) == 1 else st.selectbox(f"Ano — {emp['razao_social']}", anos, key=f"ini_ano_{emp['id']}")
        linhas = situacao.quadro(ano, imps, db.listar_relatorios(conn, emp["id"]))
        st.markdown(f"**{emp['razao_social']}** — {situacao.proxima_acao(linhas)}")
        tab = pd.DataFrame([{"Mês": l["rotulo"], "Balancete": "importado" if l["importado"] else "–", "Status": l["status"],
                             "Conferências com falha": "–" if l["falhas"] is None else l["falhas"], "Relatório": l["relatorio"]} for l in linhas])
        st.dataframe(tab, hide_index=True, width="stretch", height=35 * 13 + 3)


paginas = [
    st.Page(pagina_inicio, title="Início", icon="🏠", default=True, url_path="inicio"),
    st.Page("telas/1_Importar_Balancete.py", title="Importar balancete", icon="📥", url_path="importar"),
    st.Page("telas/2_Demonstrativos.py", title="Demonstrativos", icon="📊", url_path="demonstrativos"),
    st.Page("telas/5_Relatorio_PDF.py", title="Relatório PDF", icon="📄", url_path="relatorio"),
    st.Page("telas/6_Painel.py", title="Painel", icon="📈", url_path="painel"),
    st.Page("telas/3_Historico.py", title="Histórico", icon="🗂️", url_path="historico"),
    st.Page("telas/4_Mapa_de_Contas.py", title="Mapa de contas", icon="🧭", url_path="mapa"),
    st.Page("telas/7_Ajuda.py", title="Ajuda", icon="❓", url_path="ajuda"),
]
st.navigation(paginas).run()
