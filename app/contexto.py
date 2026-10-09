# -*- coding: utf-8 -*-
"""
GDF - contexto compartilhado das telas que dependem de um mes de referencia (Demonstrativos, Relatorio PDF).
Le o banco, monta os balancetes ate' o mes e calcula Balanco, DRE e conferencias. Sem streamlit.
"""
from __future__ import annotations

import db
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


def carregar(conn, empresa_id: int, mes_ref: str) -> dict:
    """Calcula tudo do mes (so' os balancetes do mesmo ano: abertura em 31/12 anterior, DRE acumulada no ano).
    Levanta motor.ErroDados se faltarem meses."""
    mapa = db.mapa_vigente(conn, empresa_id)
    periodos = {m: v for m, v in db.periodos_mensais_ativos(conn, empresa_id).items() if m <= mes_ref and m[:4] == mes_ref[:4]}
    b = motor.Balancetes(periodos, mapa)
    i = b.ordem.index(mes_ref) if mes_ref in b.ordem else -1
    if i < 0:
        raise motor.ErroDados(f"Não há balancete mensal ativo para {mes_ref[5:7]}/{mes_ref[:4]}.")
    mes_ant = b.ordem[i - 1] if i > 0 else mes_ref
    bp = motor.balanco(b, mes_ref, mes_ant)
    d = motor.dre(b, mes_ref)
    conf = motor.conferencias(b)
    for ate, contas in db.acumulados_ativos(conn, empresa_id).items():
        if ate <= mes_ref and ate in b.ordem:
            conf += motor.conferir_acumulado(motor.Balancetes({m: periodos[m] for m in b.ordem if m <= ate}, mapa), contas, ate)
    return {"mapa": mapa, "periodos": periodos, "b": b, "mes_ant": mes_ant, "bp": bp, "d": d, "conf": conf,
            "falhas": [c for c in conf if not c["ok"]]}


def status_por_mes(conn, empresa_id: int) -> dict:
    """{'AAAA-MM': 'RASCUNHO'|'REVISADA'} das importacoes mensais ativas."""
    return {f"{i['periodo_fim'].year}-{i['periodo_fim'].month:02d}": i["status"]
            for i in db.listar_importacoes(conn, empresa_id) if i["ativo"] and i["tipo"] == "MENSAL"}
