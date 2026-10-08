# -*- coding: utf-8 -*-
"""GDF — Demonstrativos: Balanço, DRE, Indicadores e conferências calculados pelo motor a partir dos balancetes ativos."""
import streamlit as st

import db
import formatacao as F
import motor
import tabelas
from auth import usuario_atual
from conexao import empresa_atual, get_conn, sidebar_rodape

usuario = usuario_atual()
conn = get_conn()
sidebar_rodape()

st.title("Demonstrativos")
empresas = empresa_atual(conn)
emp = st.selectbox("Empresa", empresas, format_func=lambda e: e["razao_social"], key="dem_empresa")

meses = db.listar_meses_ativos(conn, emp["id"])
validos = [m for m in meses if all(f"{m[:4]}-{i:02d}" in meses for i in range(1, int(m[5:7]) + 1))]
if not meses:
    st.info("Ainda não há balancete mensal importado para esta empresa. Use **Importar balancete**.")
    st.stop()
if not validos:
    st.warning("Há balancetes importados, mas falta o mês de janeiro (ou um mês no meio). Os demonstrativos precisam da sequência "
               "completa de janeiro até o mês escolhido. Meses importados: " + ", ".join(F.mes_br(m) for m in meses) + ".")
    st.stop()

mes_ref = st.selectbox("Mês de referência", validos, index=len(validos) - 1, format_func=F.mes_br, key="dem_mes")
if len(validos) < len(meses):
    st.caption("Meses que não aparecem na lista não têm todos os meses anteriores importados: " + ", ".join(F.mes_br(m) for m in meses if m not in validos) + ".")

mapa = db.mapa_vigente(conn, emp["id"])
periodos = {m: v for m, v in db.periodos_mensais_ativos(conn, emp["id"]).items() if m <= mes_ref}
b = motor.Balancetes(periodos, mapa)
try:
    i = b.ordem.index(mes_ref)
    mes_ant = b.ordem[i - 1] if i > 0 else mes_ref
    bp = motor.balanco(b, mes_ref, mes_ant)
    d = motor.dre(b, mes_ref)
    conf = motor.conferencias(b)
    for ate, contas in db.acumulados_ativos(conn, emp["id"]).items():
        if ate <= mes_ref and ate in b.ordem:
            conf += motor.conferir_acumulado(motor.Balancetes({m: periodos[m] for m in b.ordem if m <= ate}, mapa), contas, ate)
except motor.ErroDados as exc:
    st.error(str(exc))
    st.stop()

falhas = [c for c in conf if not c["ok"]]
if falhas:
    st.warning(f"{len(falhas)} de {len(conf)} conferências com falha. Veja a aba **Conferências** antes de usar estes números.")
else:
    st.success(f"Todas as {len(conf)} conferências passaram.")

aba_bp, aba_dre, aba_ind, aba_conf = st.tabs(["Balanço Patrimonial", "DRE", "Indicadores", "Conferências"])
with aba_bp:
    st.caption(f"Em R$ — posição em 31/12/{int(mes_ref[:4]) - 1}, {tabelas._data_fim_mes(mes_ant)} e {tabelas._data_fim_mes(mes_ref)}. O resultado do período compõe o patrimônio líquido.")
    for df, est in tabelas.tabela_balanco(bp, mes_ref, mes_ant):
        st.dataframe(tabelas.estilizar(df, est), hide_index=True, use_container_width=True, height=min(35 * (len(df) + 1) + 3, 760))
with aba_dre:
    st.caption(f"Em R$ — período de 01/01/{mes_ref[:4]} a {tabelas._data_fim_mes(mes_ref)}.")
    df, est = tabelas.tabela_dre(d, mes_ref)
    st.dataframe(tabelas.estilizar(df, est), hide_index=True, use_container_width=True, height=min(35 * (len(df) + 1) + 3, 1100))
    aj = d["acumulado"]["ajustes"]
    notas = ["A receita de construção e a remuneração do ativo de contrato são reconhecidas ao final do exercício e/ou na entrada em operação da obra "
             "de concessão; o resultado intermediário reflete apenas os custos incorridos e não é representativo do resultado anual."]
    if abs(aj) >= 0.005:
        notas.append(f"'Outros ajustes líquidos' (R$ {F.num_br(aj)} no acumulado): estornos de centavos apurados no encerramento do mês.")
    for n in notas:
        st.caption(n)
with aba_ind:
    st.caption("Calculados a partir do Balanço e da DRE. Resultados são acumulados no ano.")
    df, est = tabelas.tabela_indicadores(bp, d, mes_ref, mes_ant)
    st.dataframe(tabelas.estilizar(df, est), hide_index=True, use_container_width=True, height=min(35 * (len(df) + 1) + 3, 900))
    st.caption("PMR, PMP e ICSD não são calculados enquanto não houver receita de construção/remuneração reconhecida.")
with aba_conf:
    import pandas as pd
    if conf:
        tab = pd.DataFrame([{"": "✅" if c["ok"] else "❌", "Período": F.mes_br(c["periodo"]) if c["periodo"][:2] == "20" else c["periodo"],
                             "Grupo": c["grupo"], "Conferência": c["descricao"], "Detalhe": c["detalhe"]} for c in conf])
        so_falhas = st.checkbox("Mostrar só as que falharam", value=bool(falhas), key="dem_so_falhas")
        st.dataframe(tab[tab[""] == "❌"] if so_falhas else tab, hide_index=True, use_container_width=True)
