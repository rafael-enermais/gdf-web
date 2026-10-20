# -*- coding: utf-8 -*-
"""
GDF V2 - rotina SEMANAL de titulos EM ABERTO (somente leitura no Sienge): busca por data de VENCIMENTO, de 2023 ate 2032, e grava so' os titulos que ainda
nao foram totalmente pagos/recebidos. Completa a rotina diaria (que olha pagamento e emissao dos ultimos 365 dias) com:
  (a) contas vencidas e nao pagas emitidas antes da janela (inadimplencia antiga);
  (b) parcelas futuras de contratos antigos (financiamentos) -> endividamento.
Variaveis: SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL (opcional), DATABASE_URL (so' para gravar).
  GDF_ABERTOS_GRAVAR = "sim" grava no banco; qualquer outro valor (padrao) so' MEDE (conta titulos/tempo, nao grava nada).
  GDF_ABERTOS_INI / GDF_ABERTOS_FIM = "AAAA-MM" (padrao 2023-01 .. 2032-12).
O repositorio e' PUBLICO e o log tambem: imprime SO contagens e tempos.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import painel_db as P  # noqa: E402
import sienge_api as S  # noqa: E402

USUARIO_ROTINA = "rotina-abertos"
PAUSA_ENTRE_CHAMADAS = 6
ESPERAS_429 = (30, 60, 120, 240)


def executar(conn, cli, ini: str, fim: str, gravar: bool, buscar=None, log=print) -> int:
    """Devolve 0 (ok) ou 1 (alguma busca falhou). `buscar(cli, lado, mes_ini, tipo, mes_fim=)` injetavel para teste."""
    buscar = buscar or S.buscar_bulk
    falhas = 0
    sids = {}
    totais = {"P": [0, 0], "R": [0, 0]}
    campos_vistos = {"P": False, "R": False}
    for lado in ("P", "R"):
        if gravar:
            sids[lado] = P.criar_sync(conn, ini, lado, "D", USUARIO_ROTINA)
        acum = {"titulos": 0, "baixas": 0, "rateios": 0, "liquido": 0.0}
        erro = None
        for (a, b) in S.janelas_abertos(ini, fim):
            t0 = time.monotonic()
            try:
                regs = buscar(cli, lado, a, "D", mes_fim=b)
                abertos = S.somente_abertos(regs, lado)
                if regs and not campos_vistos[lado] and isinstance(regs[0], dict):       # SO os nomes dos campos (nunca valores): confere se existe 'vencimento original'
                    campos_vistos[lado] = True
                    log(f"{lado} campos do título: {', '.join(sorted(regs[0].keys()))}")
                totais[lado][0] += len(regs)
                totais[lado][1] += len(abertos)
                log(f"{lado} vencimento {a}..{b}: {len(regs)} títulos, {len(abertos)} em aberto, {time.monotonic() - t0:.0f}s")
                if gravar and abertos:
                    cont = P.gravar_normalizado(conn, sids[lado], S.normalizar_titulos(lado, abertos))
                    for k in acum:
                        acum[k] += cont.get(k) or 0
            except Exception as exc:
                falhas += 1
                erro = str(exc)
                log(f"ERRO {lado} vencimento {a}..{b}: {exc}")
                if "HTTP 429" in erro:
                    break
        if gravar:
            P.finalizar_sync(conn, sids[lado], "ERRO" if erro else "OK", acum["titulos"], acum["baixas"], acum["rateios"], acum["liquido"], erro)
            P.registrar_log(conn, "ROTINA_ABERTOS", "ERRO" if erro else "INFO", USUARIO_ROTINA, ini,
                            {"lado": lado, "janela": f"{ini}..{fim}", "titulos": acum["titulos"], "baixas": acum["baixas"], "rateios": acum["rateios"]})
    log(f"resumo: pagar {totais['P'][0]} títulos ({totais['P'][1]} em aberto); receber {totais['R'][0]} títulos ({totais['R'][1]} em aberto); gravar={gravar}")
    return 1 if falhas else 0


def main(env=None) -> int:
    env = os.environ if env is None else env
    ini = (env.get("GDF_ABERTOS_INI") or "2023-01").strip()
    fim = (env.get("GDF_ABERTOS_FIM") or "2032-12").strip()
    gravar = (env.get("GDF_ABERTOS_GRAVAR") or "").strip().lower() in ("sim", "true", "1")
    try:
        user, pwd, base = S.credenciais(None, env)
    except S.ErroSienge as exc:
        print(f"ERRO de configuração: {exc}")
        return 1
    cli = S.Cliente(user, pwd, base, pausa=PAUSA_ENTRE_CHAMADAS, esperas_429=ESPERAS_429)
    if not gravar:
        return executar(None, cli, ini, fim, False)
    import psycopg2
    url = (env.get("DATABASE_URL") or "").strip()
    if not url:
        print("ERRO de configuração: falta o secret DATABASE_URL.")
        return 1
    try:
        conn = psycopg2.connect(url, connect_timeout=30)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET search_path TO gdf")
            cur.execute("SELECT current_user")
            if cur.fetchone()[0] != "gdf_app":
                print("ERRO: a DATABASE_URL precisa conectar como gdf_app.")
                return 1
    except Exception as exc:
        print(f"ERRO ao conectar no banco ({type(exc).__name__}).")
        return 1
    try:
        return executar(conn, cli, ini, fim, True)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
