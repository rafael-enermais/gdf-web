# -*- coding: utf-8 -*-
"""GDF — Importar balancete (CSV do sistema contábil): leitura, conferências do arquivo e gravação sem apagar nada."""
import streamlit as st

import db
import motor
from auth import usuario_atual
from conexao import empresa_atual, flash, get_conn, mostrar_flash, sidebar_rodape
from importador_csv import ErroImportacao, ler_bytes

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Importar balancete")
mostrar_flash()
st.caption("Envie o CSV do relatório **Balancete – Débito/Crédito (Texto)** do sistema contábil: um arquivo por mês "
           "(01/01 a 31/01, 01/02 a 28/02...). O CSV acumulado (01/01 até o mês) também é aceito e serve para conferir os meses.")

empresa_atual(conn)
st.session_state.setdefault("upl_n", 0)
arquivos = st.file_uploader("Arquivos CSV", type=["csv"], accept_multiple_files=True, key=f"upl_{st.session_state['upl_n']}")

ICONE = {True: "✅", False: "❌"}


def _tabela_conf(conf):
    import pandas as pd
    return pd.DataFrame([{"": ICONE[c["ok"]], "Conferência": c["descricao"], "Detalhe": c["detalhe"]} for c in conf])


prontos = []
for arq in arquivos or []:
    raw = arq.getvalue()
    with st.container(border=True):
        st.markdown(f"**{arq.name}**")
        try:
            cab, contas = ler_bytes(raw, arq.name)
        except ErroImportacao as exc:
            st.error(str(exc))
            continue
        emp = db.empresa_por_cnpj(conn, cab["cnpj"])
        if not emp:
            st.error(f"O CNPJ {cab['cnpj']} ({cab['empresa']}) não está cadastrado no GDF. Peça o cadastro da empresa antes de importar.")
            continue
        mapa = db.mapa_vigente(conn, emp["id"])
        conf = motor.conferencias_arquivo(contas, mapa, cab["periodo"])
        acum_info = None
        if cab["tipo"] == "ACUMULADO":
            mensais = db.periodos_mensais_ativos(conn, emp["id"])
            ate = cab["periodo"]
            precisa = [f"{ate[:4]}-{m:02d}" for m in range(1, int(ate[5:7]) + 1)]
            if all(m in mensais for m in precisa):
                b = motor.Balancetes({m: mensais[m] for m in precisa}, mapa)
                conf += motor.conferir_acumulado(b, contas, ate)
            else:
                acum_info = "Ainda não há todos os balancetes mensais de janeiro até este mês; a conferência mensal × acumulado fica para depois."
        tipo_txt = "mês isolado" if cab["tipo"] == "MENSAL" else "acumulado do ano"
        st.write(f"{emp['razao_social']} · {tipo_txt} · {cab['ini']:%d/%m/%Y} a {cab['fim']:%d/%m/%Y} · {cab['n_contas']} contas")
        st.dataframe(_tabela_conf(conf), hide_index=True, use_container_width=True)
        if acum_info:
            st.info(acum_info)
        falhas = [c for c in conf if not c["ok"]]
        item = {"cab": cab, "contas": contas, "emp": emp, "conf": conf, "falhas": falhas, "substituir": False, "forcar": True}
        if falhas:
            st.warning(f"{len(falhas)} conferência(s) com falha. Confira os detalhes acima antes de importar.")
            item["forcar"] = st.checkbox("Importar mesmo assim (fica como RASCUNHO e o aviso fica registrado)", key=f"forcar_{cab['sha256']}")
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo FROM importacao WHERE empresa_id=%s AND arquivo_sha256=%s", (emp["id"], cab["sha256"]))
            dup = cur.fetchone()
            cur.execute("SELECT id FROM importacao WHERE empresa_id=%s AND tipo=%s AND periodo_ini=%s AND periodo_fim=%s AND ativo",
                        (emp["id"], cab["tipo"], cab["ini"], cab["fim"]))
            ativa = cur.fetchone()
        if dup:
            st.info(f"Este arquivo já foi importado (importação #{dup[0]}{'' if dup[1] else ', hoje inativa — reative no Histórico'}). Nada a fazer.")
            continue
        if ativa:
            item["substituir"] = st.checkbox(f"Já existe a importação #{ativa[0]} ativa para este período. Substituir? (a anterior fica guardada, inativa)",
                                             key=f"subst_{cab['sha256']}")
            if not item["substituir"]:
                st.caption("Marque a caixa acima para importar este arquivo no lugar da importação ativa.")
                continue
        if falhas and not item["forcar"]:
            continue
        prontos.append(item)

if prontos:
    if st.button(f"Importar {len(prontos)} arquivo(s)", type="primary"):
        for it in prontos:
            cab = it["cab"]
            try:
                imp_id = db.inserir_importacao(conn, it["emp"]["id"], cab, it["contas"], usuario, it["conf"], substituir=it["substituir"])
                flash("ok" if not it["falhas"] else "warn",
                      f"{cab['arquivo']}: importado (#{imp_id}, {cab['periodo']})" + (f" com {len(it['falhas'])} aviso(s)." if it["falhas"] else "."))
            except (db.ImportacaoDuplicada, db.PeriodoJaImportado) as exc:
                flash("warn", f"{cab['arquivo']}: {exc}")
            except Exception as exc:
                db.registrar_evento(conn, "importar", "erro", f"Falha ao importar {cab['arquivo']}: {exc}", empresa_id=it["emp"]["id"], usuario=usuario)
                flash("erro", f"{cab['arquivo']}: não consegui gravar ({exc}). Nada foi alterado.")
        st.session_state["upl_n"] += 1            # troca a chave do uploader para limpar os arquivos
        st.rerun()
