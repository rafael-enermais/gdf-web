# -*- coding: utf-8 -*-
"""
GDF - contexto compartilhado das telas que dependem de um mes de referencia (Demonstrativos, Relatorio PDF).
Le o banco, monta os balancetes ate' o mes e calcula Balanco, DRE e conferencias. Sem streamlit.
"""
from __future__ import annotations

import db
import fontes
import motor


def meses_validos(meses: list) -> list:
    """Meses com a sequencia completa de janeiro ate' ele (o Balanco e a DRE precisam disso)."""
    return [m for m in meses if all(f"{m[:4]}-{i:02d}" in meses for i in range(1, int(m[5:7]) + 1))]


def meses_faltantes(meses: list) -> list:
    """Meses que faltam (de janeiro até o último importado de cada ano) para a sequência ficar completa. Serve para dizer ao usuário o que subir."""
    falta = []
    for ano in sorted({m[:4] for m in meses}):
        ultimo = max(int(m[5:7]) for m in meses if m[:4] == ano)
        falta += [f"{ano}-{i:02d}" for i in range(1, ultimo + 1) if f"{ano}-{i:02d}" not in meses]
    return falta


def meses_com_dados(conn, empresa_id: int) -> list:
    """Todos os meses ('AAAA-MM') que têm balancete mensal OU acumulado ativo (o relatório pode ser gerado para qualquer um deles)."""
    meses = set()
    for i in db.listar_importacoes(conn, empresa_id):
        if i["ativo"]:
            meses.add(f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}")
    return sorted(meses)


def carregar_base(conn, empresa_id: int) -> tuple:
    """(balancetes mensais ativos, acumulados ativos, mapa vigente) — tudo que o motor precisa, lido uma vez."""
    return db.periodos_mensais_ativos(conn, empresa_id), db.acumulados_ativos(conn, empresa_id), db.mapa_vigente(conn, empresa_id)


def carregar(conn, empresa_id: int, mes_ref: str, mes_ini: int = 1) -> dict:
    """Calcula tudo do mês com o que estiver importado (balancetes mensais e acumulados do mesmo ano): ver fontes.calcular.
    O que não puder ser calculado volta como None (n/d) e a explicação vem em `lacunas`. Levanta motor.ErroDados só se não houver nenhum balancete do mês.
    `mes_ini` > 1 = relatório só do período mes_ini..mes_ref (quando falta um mês no meio do ano)."""
    mensais, acum, mapa = carregar_base(conn, empresa_id)
    return fontes.calcular(mensais, acum, mapa, mes_ref, mes_ini)


def status_por_periodo(conn, empresa_id: int) -> dict:
    """{('MENSAL'|'ACUMULADO', 'AAAA-MM'): 'RASCUNHO'|'REVISADA'} das importações ativas (acumulado: mês final)."""
    return {(i["tipo"], f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}"): i["status"]
            for i in db.listar_importacoes(conn, empresa_id) if i["ativo"]}


def status_usados(dados: dict, status: dict) -> tuple:
    """(n REVISADA, n RASCUNHO, lista de rótulos em rascunho) só dos balancetes que entraram nas contas deste relatório."""
    itens = [("MENSAL", m) for m in dados["usados_mensais"]] + [("ACUMULADO", m) for m in dados["usados_acum"]]
    ras = [(f"mensal {m[5:7]}/{m[:4]}" if t == "MENSAL" else f"acumulado até {m[5:7]}/{m[:4]}") for t, m in itens if status.get((t, m)) != "REVISADA"]
    return len(itens) - len(ras), len(ras), ras


def status_por_mes(conn, empresa_id: int) -> dict:
    """{'AAAA-MM': 'RASCUNHO'|'REVISADA'} das importacoes mensais ativas."""
    return {f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}": i["status"]
            for i in db.listar_importacoes(conn, empresa_id) if i["ativo"] and i["tipo"] == "MENSAL"}
