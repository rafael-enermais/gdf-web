# -*- coding: utf-8 -*-
"""GDF — Importar balancete (CSV ou PDF do sistema contábil): leitura, conferências do arquivo e gravação sem apagar nada."""
import streamlit as st

import db
import logui
import motor
from auth import usuario_atual
from conexao import empresa_atual, flash, get_conn, mostrar_flash, sidebar_rodape
from importador import ErroImportacao, ler_bytes

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Importar balancete")
mostrar_flash()
st.caption("Envie o balancete do sistema contábil em **CSV** (relatório *Balancete – Débito/Crédito (Texto)*) ou em **PDF** (*Balancete – Societário*, "
           "inclusive o assinado — o PDF só é lido, nunca alterado). Um arquivo por mês (01/01 a 31/01, 01/02 a 28/02...). "
           "O acumulado (01/01 até o mês) também é aceito e serve para conferir os meses. Os dois formatos dão os mesmos números e passam pelas mesmas conferências.")

empresas = empresa_atual(conn)
st.session_state.setdefault("upl_n", 0)
arquivos = st.file_uploader("Arquivos CSV ou PDF", type=["csv", "pdf"], accept_multiple_files=True, key=f"upl_{st.session_state['upl_n']}")

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
            logui.registrar_uma_vez(conn, ("ilegivel", arq.name, len(raw)), "importar", "erro", f"Arquivo {arq.name} não foi lido: {exc}", usuario=usuario)
            continue
        emp = db.empresa_por_cnpj(conn, cab["cnpj"])
        if not emp:
            st.error(f"O CNPJ {cab['cnpj']} ({cab['empresa']}) não está cadastrado no GDF. Peça o cadastro da empresa antes de importar.")
            logui.registrar_uma_vez(conn, ("cnpj", cab["sha256"]), "importar", "erro",
                                    f"Arquivo {arq.name} não importado: CNPJ {cab['cnpj']} não cadastrado", usuario=usuario)
            continue
        mapa = db.mapa_vigente(conn, emp["id"])
        conf = motor.conferencias_arquivo(contas, mapa, cab["periodo"])
        ign = cab.get("ignoradas") or []
        conf.insert(0, {"grupo": "arquivo", "periodo": cab["periodo"], "descricao": "Todas as linhas de conta do arquivo foram lidas", "ok": not ign,
                        "detalhe": "sim" if not ign else f"{len(ign)} linha(s) não lida(s): " + " | ".join(ign[:3])})
        acum_info = None
        if cab["tipo"] == "ACUMULADO":
            mensais = db.periodos_mensais_ativos(conn, emp["id"])
            ate = cab["periodo"]
            precisa = [f"{ate[:4]}-{m:02d}" for m in range(1, int(ate[5:7]) + 1)]
            if all(m in mensais for m in precisa):
                b = motor.Balancetes({m: mensais[m] for m in precisa}, mapa)
                conf += motor.conferir_acumulado(b, contas, ate)
            else:
                acum_info = "Ainda não há todos os balancetes mensais de janeiro até este mês; a conferência mensal × acumulado é feita automaticamente nos Demonstrativos assim que todos os meses estiverem importados (a ordem do envio não importa)."
        tipo_txt = "mês isolado" if cab["tipo"] == "MENSAL" else "acumulado do ano"
        st.write(f"{emp['razao_social']} · {cab.get('formato', 'CSV')} · {tipo_txt} · {cab['ini']:%d/%m/%Y} a {cab['fim']:%d/%m/%Y} · {cab['n_contas']} contas")
        st.dataframe(_tabela_conf(conf), hide_index=True, width="stretch")
        if acum_info:
            st.info(acum_info)
        falhas = [c for c in conf if not c["ok"]]
        item = {"cab": cab, "contas": contas, "emp": emp, "conf": conf, "falhas": falhas, "substituir": False, "forcar": True, "status": "RASCUNHO"}
        if falhas:
            st.warning(f"{len(falhas)} conferência(s) com falha. Confira os detalhes acima antes de importar.")
            item["forcar"] = st.checkbox("Importar mesmo assim (fica como RASCUNHO e o aviso fica registrado)", key=f"forcar_{cab['sha256']}")
        with conn.cursor() as cur:
            cur.execute("SELECT id, ativo, status FROM importacao WHERE empresa_id=%s AND arquivo_sha256=%s", (emp["id"], cab["sha256"]))
            dup = cur.fetchone()
            cur.execute("SELECT id, status FROM importacao WHERE empresa_id=%s AND tipo=%s AND periodo_ini=%s AND periodo_fim=%s AND ativo",
                        (emp["id"], cab["tipo"], cab["ini"], cab["fim"]))
            ativa = cur.fetchone()
        if dup:
            # o mesmo arquivo nunca entra duas vezes (os dados ja estao guardados); em vez de "nada a fazer", oferece o que faz sentido
            d_id, d_ativo, d_status = dup
            logui.registrar_uma_vez(conn, ("dup", cab["sha256"]), "importar", "info",
                                    f"Arquivo {arq.name} já estava importado (#{d_id}, {'ativa' if d_ativo else 'inativa'}, {d_status}) — nenhuma importação nova",
                                    empresa_id=emp["id"], usuario=usuario)
            if d_ativo and d_status == "REVISADA":
                st.info(f"Este arquivo já está importado (importação #{d_id}, ativa, REVISADA). Nada a fazer.")
            elif d_ativo:
                st.info(f"Este arquivo já está importado (importação #{d_id}, ativa), mas ainda como {d_status}.")
                if st.button(f"Confirmar #{d_id} como REVISADA", key=f"dup_rev_{cab['sha256']}"):
                    db.definir_status(conn, d_id, "REVISADA", usuario)
                    flash("ok", f"Importação #{d_id} confirmada como REVISADA.")
                    st.session_state["upl_n"] += 1
                    st.rerun()
            else:
                outra_txt = f" A #{ativa[0]}, hoje ativa neste período, fica guardada (inativa)." if ativa else ""
                st.info(f"Este arquivo já foi importado antes (importação #{d_id}, hoje inativa). Os dados dele estão guardados.")
                if st.button(f"Usar este arquivo de novo (reativar #{d_id})", key=f"dup_reat_{cab['sha256']}"):
                    trocada = db.reativar_trocando(conn, d_id, usuario)
                    flash("ok", f"Importação #{d_id} reativada." + (f" A #{trocada} ficou guardada, inativa." if trocada else ""))
                    st.session_state["upl_n"] += 1
                    st.rerun()
                if outra_txt:
                    st.caption(outra_txt.strip())
            continue
        if ativa:
            if ativa[1] == "REVISADA":
                st.warning(f"Atenção: o mês {cab['fim']:%m/%Y} já está **validado** (importação #{ativa[0]}, REVISADA). Substituir muda os números deste mês; "
                           "o arquivo novo precisa ser confirmado de novo.")
            if cab["tipo"] == "MENSAL":
                afetados = [r for r in db.listar_relatorios(conn, emp["id"]) if r["periodo"] >= cab["fim"].replace(day=1)]
                if afetados:
                    st.warning("Já existem relatórios que usam este mês (" + ", ".join(f"{r['periodo']:%m/%Y} v{r['versao']} {r['status']}" for r in afetados[:6])
                               + "). Depois da troca eles aparecem como \"desatualizados\" na tela Relatório PDF; gere uma nova versão.")
            item["substituir"] = st.checkbox(f"Já existe a importação #{ativa[0]} ativa para este período. Substituir? (a anterior fica guardada, inativa)",
                                             key=f"subst_{cab['sha256']}")
            if not item["substituir"]:
                st.caption("Marque a caixa acima para importar este arquivo no lugar da importação ativa.")
                continue
        if falhas and not item["forcar"]:
            continue
        if falhas:
            st.caption("Com conferência falhando o balancete entra como RASCUNHO; depois de corrigir, confirme no Histórico.")
        else:
            if st.checkbox("Revisei os números e confirmo: este balancete confere com a contabilidade (entra já como REVISADA, com o seu nome)",
                           key=f"rev_{cab['sha256']}"):
                item["status"] = "REVISADA"
        prontos.append(item)

if prontos:
    if st.button(f"Importar {len(prontos)} arquivo(s)", type="primary"):
        for it in prontos:
            cab = it["cab"]
            try:
                imp_id = db.inserir_importacao(conn, it["emp"]["id"], cab, it["contas"], usuario, it["conf"], status=it["status"], substituir=it["substituir"])
                flash("ok" if not it["falhas"] else "warn",
                      f"{cab['arquivo']}: importado (#{imp_id}, {cab['periodo']}, {it['status']})" + (f" com {len(it['falhas'])} aviso(s)." if it["falhas"] else "."))
            except (db.ImportacaoDuplicada, db.PeriodoJaImportado) as exc:
                flash("warn", f"{cab['arquivo']}: {exc}")
            except Exception as exc:
                db.registrar_evento(conn, "importar", "erro", f"Falha ao importar {cab['arquivo']}: {exc}", empresa_id=it["emp"]["id"], usuario=usuario)
                flash("erro", f"{cab['arquivo']}: não consegui gravar ({exc}). Nada foi alterado.")
        st.session_state["upl_n"] += 1            # troca a chave do uploader para limpar os arquivos
        st.rerun()

logui.painel_importacao(conn, empresas)
