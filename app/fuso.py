# -*- coding: utf-8 -*-
"""GDF - horario de Brasilia. O servidor (Streamlit Cloud) e o banco (Supabase) trabalham em UTC; o usuario le' hora de Brasilia.
Sem isso o rodape do PDF e as telas mostravam 3 horas a frente ("gerado em 13:23" quando eram 10:23)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:                      # sem tzdata (ex.: Windows sem o pacote): Brasilia nao tem horario de verao desde 2019
    BRASILIA = timezone(timedelta(hours=-3))

FORMATO = "%d/%m/%Y %H:%M"


def agora_br() -> datetime:
    return datetime.now(BRASILIA)


def para_br(dt: datetime) -> datetime:
    """Converte um datetime do banco (timestamptz) para Brasilia. Sem fuso informado, assume UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRASILIA)


def fmt_br(dt: datetime | None) -> str:
    return "" if dt is None else para_br(dt).strftime(FORMATO)
