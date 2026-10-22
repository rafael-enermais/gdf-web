# -*- coding: utf-8 -*-
"""
GDF - rotina diaria do REGISTRO DE METRICAS: calcula os indicadores do painel de metas (I03, I22, I27) e grava em gdf.metrica_registro.
Roda no GitHub Actions (.github/workflows/registrar-metricas-gdf.yml), depois da carga do Sienge, para o painel de outros apps (ex.: o do Edilson,
lendo diretoria.metricas_atual) andar sozinho sem ninguem clicar em "Calcular e gravar" na tela Metricas do mes.

O que grava: o mes ATUAL (posicao de hoje). Nos 5 primeiros dias do mes grava tambem o mes ANTERIOR (posicao de fim de mes), para fixar o fechamento.
Regravar e' seguro: so' muda o que mudou (historico em metrica_registro_hist) e linha corrigida a mao (origem 'manual') nao e' sobrescrita.

Variavel de ambiente (GitHub -> Secrets): DATABASE_URL (pooler do Supabase, usuario gdf_app.<ref>). Opcional GDF_METRICAS_MESES="2026-09,2026-10" (forca os meses).
Nao fala com o Sienge (le so' o que a carga ja gravou no banco). O repositorio e' PUBLICO e o log tambem: imprime so' contagens e o codigo do indicador.
Codigo de saida 1 se algum indicador nao puder ser calculado (o GitHub avisa por e-mail).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import metricas_registro as M  # noqa: E402

USUARIO_ROTINA = "rotina-metricas"
DIAS_FECHAMENTO = 5


def hoje_brasilia() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    except Exception:                                   # sem tzdata: UTC-3 fixo
        return (dt.datetime.utcnow() - dt.timedelta(hours=3)).date()


def _mes(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def meses_a_registrar(hoje: dt.date, forcados: str = "") -> list:
    """Mes atual; nos primeiros dias do mes, o anterior tambem (fechamento). `forcados` = 'AAAA-MM,AAAA-MM' (validado)."""
    if (forcados or "").strip():
        meses = [m.strip() for m in forcados.split(",") if m.strip()]
        for m in meses:
            if len(m) != 7 or m[4] != "-" or not (m[:4] + m[5:]).isdigit() or not 1 <= int(m[5:]) <= 12:
                raise ValueError(f"GDF_METRICAS_MESES inválido ({m!r}); use AAAA-MM separados por vírgula.")
        return sorted(set(meses))
    atual = _mes(hoje)
    if hoje.day <= DIAS_FECHAMENTO:
        anterior = _mes(hoje.replace(day=1) - dt.timedelta(days=1))
        return [anterior, atual]
    return [atual]


def executar(conn, meses: list, hoje: dt.date, log=print) -> int:
    """Calcula e grava cada mes. Devolve 0 se tudo foi calculado, 1 se algum indicador falhou (o resto e' gravado do mesmo jeito)."""
    falhas = 0
    for mes in meses:
        res = M.registrar_mes(conn, mes, USUARIO_ROTINA, hoje)
        log(f"{mes}: {res['novas']} nova(s), {res['atualizadas']} atualizada(s), {res['iguais']} sem mudança, {res['preservadas_manual']} preservada(s) (manual)")
        for item, msg in res["erros"].items():
            falhas += 1
            log(f"ERRO {mes} {item}: não calculado ({msg.split(chr(10))[0][:120]})")
    return 1 if falhas else 0


def main(env=None, conn=None, hoje=None, log=print) -> int:
    env = os.environ if env is None else env
    hoje = hoje or hoje_brasilia()
    meses = meses_a_registrar(hoje, env.get("GDF_METRICAS_MESES", ""))
    proprio = conn is None
    if proprio:
        url = (env.get("DATABASE_URL") or "").strip()
        if not url:
            log("ERRO: DATABASE_URL não configurado (Settings > Secrets > Actions).")
            return 1
        import psycopg2
        conn = psycopg2.connect(url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET search_path TO gdf")
    try:
        if not M.instalado(conn):
            log("ERRO: tabelas do registro não existem (rode o SQL-34).")
            return 1
        log(f"registrando métricas: {', '.join(meses)}")
        return executar(conn, meses, hoje, log)
    finally:
        if proprio:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
