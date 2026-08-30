# -*- coding: utf-8 -*-
"""Semana epidemiológica (ISO / alinhada ao pipeline LACEN e DATEPART iso_week no DW).

Convenção do sistema: `datetime.isocalendar()` (segunda–domingo), igual a
`DATEPART(iso_week, …)` / `DATEPART(isoyear, …)` no SQL Server.
A SE de referência operacional é a **última semana completa** relativa a `hoje`
(a semana corrente ainda em curso não é tratada como “atual” sem banner).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Tuple, Union

DateLike = Union[date, datetime, None]


def _as_date(d: DateLike = None) -> date:
    if d is None:
        return date.today()
    if isinstance(d, datetime):
        return d.date()
    return d


def date_to_epi(d: DateLike = None) -> Tuple[int, int]:
    """Retorna (ano_se, semana_epidemiologica) ISO para a data."""
    dd = _as_date(d)
    iso = dd.isocalendar()
    return int(iso.year), int(iso.week)


def ano_se(d: DateLike = None) -> int:
    return date_to_epi(d)[0]


def semana_epidemiologica(d: DateLike = None) -> int:
    return date_to_epi(d)[1]


def semana_completa_mais_recente(hoje: DateLike = None) -> Tuple[int, int]:
    """Última SE ISO já encerrada antes de `hoje`.

    Ex.: se hoje cai no meio (ou no domingo) da SE W, a referência é W−1.
    """
    dd = _as_date(hoje)
    # isoweekday: seg=1 … dom=7 → voltar ao domingo anterior = fim da SE anterior
    ref = dd - timedelta(days=dd.isoweekday())
    return date_to_epi(ref)


def format_se(ano: int, semana: int) -> str:
    return f"{int(ano)}-SE{int(semana):02d}"


def epi_ordinal(ano: int, semana: int) -> int:
    """Ordenação aproximada ano×semana (suporta SE 1–53)."""
    return int(ano) * 100 + int(semana)


def atraso_semanas(
    se_esperada: Tuple[int, int],
    se_usada: Tuple[int, int],
) -> int:
    """Diferença em semanas (esperada − usada). Positivo = dados atrasados."""
    y0, w0 = se_esperada
    y1, w1 = se_usada
    # Conversão grosseira via ordinal ISO (bom o bastante para flag operacional)
    d0 = date.fromisocalendar(int(y0), int(w0), 1)
    d1 = date.fromisocalendar(int(y1), int(w1), 1)
    return int((d0 - d1).days // 7)


def atraso_dias_desde_fim_se(ano: int, semana: int, hoje: DateLike = None) -> int:
    """Dias desde o domingo (fim) da SE usada até `hoje`."""
    dd = _as_date(hoje)
    fim = date.fromisocalendar(int(ano), int(semana), 7)  # domingo ISO
    return max(0, (dd - fim).days)
