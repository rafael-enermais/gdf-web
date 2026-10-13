# -*- coding: utf-8 -*-
"""
GDF V2 - rotina diaria: busca no Sienge (SOMENTE LEITURA) as contas pagas e a receber do mes atual e do mes anterior
e grava no Supabase (schema gdf, role gdf_app). Roda no GitHub Actions (.github/workflows/ingest-sienge-gdf.yml), fora do Streamlit.

Variaveis de ambiente (GitHub -> Settings -> Secrets and variables -> Actions; valor PURO, sem aspas):
  SIENGE_USER, SIENGE_PASSWORD, SIENGE_BASE_URL (opcional), DATABASE_URL (pooler do Supabase, usuario gdf_app.<ref>)
Opcionais: GDF_MESES="2026-09,2026-10" (forca os meses); GDF_MODO=ano (janeiro ate o mes atual; usado na conferencia semanal);
sem nenhum dos dois: mes anterior e mes atual (hora de Brasilia).
O Sienge limita as chamadas por minuto (HTTP 429): o cliente espera entre as chamadas e tenta de novo com espera crescente.

O repositorio e' PUBLICO e o log do Actions tambem: este script imprime SO contagens e mensagens ja sem segredo; nunca valores/linhas.
Codigo de saida 1 se alguma busca falhar (o GitHub avisa por e-mail).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import painel_db as P  # noqa: E402
import sienge_api as S  # noqa: E402

USUARIO_ROTINA = "rotina-diaria"
LADOS = ("P", "R")
PAUSA_ENTRE_CHAMADAS = 6      # segundos (o Sienge devolve 429 se passar de ~uma dezena de chamadas em poucos segundos)
ESPERAS_429 = (30, 60, 120, 240)
TIPOS = ("P", "I")          # P = pagamento/recebimento (Despesas, Realizado) | I = emissao (DRE comprometido)


def hoje_brasilia() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    except Exception:                                   # sem tzdata: UTC-3 fixo
        return (dt.datetime.utcnow() - dt.timedelta(hours=3)).date()


def meses_padrao(hoje: dt.date | None = None) -> list:
    """Mes anterior e mes atual ('AAAA-MM'), nessa ordem. O mes anterior continua sendo reaberto por lancamentos tardios."""
    hoje = hoje or hoje_brasilia()
    ant = (hoje.replace(day=1) - dt.timedelta(days=1))
    return [f"{ant.year:04d}-{ant.month:02d}", f"{hoje.year:04d}-{hoje.month:02d}"]


def meses_do_ano(hoje: dt.date | None = None) -> list:
    """De janeiro do ano corrente ate o mes atual (a conferencia semanal pega ajustes retroativos em meses antigos)."""
    hoje = hoje or hoje_brasilia()
    return [f"{hoje.year:04d}-{m:02d}" for m in range(1, hoje.month + 1)]


def ler_meses(env) -> list:
    bruto = (env.get("GDF_MESES") or "").strip()
    if not bruto:
        return meses_do_ano() if (env.get("GDF_MODO") or "").strip() == "ano" else meses_padrao()
    meses = [m.strip() for m in bruto.split(",") if m.strip()]
    for m in meses:
        if len(m) != 7 or m[4] != "-" or not (m[:4] + m[5:]).isdigit() or not 1 <= int(m[5:]) <= 12:
            raise ValueError(f"GDF_MESES inválido ({m!r}); use AAAA-MM separados por vírgula.")
    return meses


def executar(conn, cli, meses: list, buscar=None, normalizar=None, atualizar_cadastros: bool = True, log=print) -> int:
    """Roda a rotina numa conexao ja aberta. Devolve 0 (tudo ok) ou 1 (alguma busca falhou)."""
    falhas = 0
    if atualizar_cadastros:
        try:
            cont = P.gravar_cadastros(conn, S.normalizar_cadastros(S.buscar_cadastros(cli)))
            log("cadastros: " + ", ".join(f"{k} {v}" for k, v in cont.items()))
        except Exception as exc:                          # cadastro velho nao impede buscar os titulos
            falhas += 1
            log(f"ERRO cadastros: {exc}")
    for mes in meses:
        limite = False
        for r in P.sincronizar_mes(conn, cli, mes, USUARIO_ROTINA, lados=LADOS, tipos=TIPOS, buscar=buscar, normalizar=normalizar):
            lado = "pagar" if r["lado"] == "P" else "receber"
            if r["ok"]:
                av = {k: v for k, v in (r.get("avisos") or {}).items() if v}
                log(f"{mes} {lado} data {r['tipo']}: {r['titulos']} títulos, {r['baixas']} baixas, {r['rateios']} rateios"
                    + (f" | avisos: {av}" if av else ""))
            else:
                falhas += 1
                log(f"ERRO {mes} {lado} data {r['tipo']}: {r['erro']}")
                limite = limite or "HTTP 429" in (r["erro"] or "")
        if limite:
            log("Limite de chamadas do Sienge persistiu: parei aqui. Os meses seguintes ficam para a próxima execução.")
            break
    return 1 if falhas else 0


def main(env=None) -> int:
    env = os.environ if env is None else env
    import psycopg2
    try:
        user, pwd, base = S.credenciais(None, env)
        meses = ler_meses(env)
    except (S.ErroSienge, ValueError) as exc:
        print(f"ERRO de configuração: {exc}")
        return 1
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
            usuario = cur.fetchone()[0]
        if usuario != "gdf_app":
            print(f"ERRO: a DATABASE_URL conecta como `{usuario}`; só a role gdf_app é permitida (usuário gdf_app.<ref> no pooler).")
            return 1
        if not P.v2_instalado(conn):
            print("ERRO: as tabelas do Painel (V2) não existem; execute sql/v2_painel_schema.sql no Supabase.")
            return 1
    except Exception as exc:
        print(f"ERRO ao conectar no banco ({type(exc).__name__}).")   # nao imprime a mensagem: pode conter o endereco/usuario
        return 1
    print(f"meses: {', '.join(meses)}")
    try:
        return executar(conn, S.Cliente(user, pwd, base, pausa=PAUSA_ENTRE_CHAMADAS, esperas_429=ESPERAS_429), meses)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
