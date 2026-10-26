# -*- coding: utf-8 -*-
"""Semana epidemiológica (SE) no calendário do Ministério da Saúde / SINAN.

Convenção do sistema: SE de **domingo a sábado**. A SE 1 do ano é a semana que
contém mais dias de janeiro (equivalente: a semana cuja quarta-feira cai no ano).
Logo: ``ano_se = ano(quarta)`` e ``se = (dia_do_ano(quarta) − 1) // 7 + 1``.

Atenção: isso **não** é a semana ISO (segunda–domingo). Em 2026, por exemplo,
a SE MS 1 começa em 04/01/2026 e a semana ISO fica 1 número à frente na maior
parte dos dias. Todos os módulos devem calcular SE por este arquivo
(`date_to_epi`, `epi_from_series`, `sql_epi_exprs`), nunca via `isocalendar()`.

A SE de referência operacional é a **última semana completa** relativa a `hoje`
(a semana corrente ainda em curso não é tratada como “atual” sem banner).

Âncora temporal GAL: a SE do exame é calculada pela **data da solicitação**
(`Data_Solicitacao*`); coleta/liberação seguem para TAT e frescor do extract.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Tuple, Union

DateLike = Union[date, datetime, None]

# Ordem de preferência para âncora da SE no GAL (solicitação primeiro).
GAL_SE_DATE_CANDIDATES: tuple[str, ...] = (
    "Data_Solicitacao_dt",
    "Data_Solicitacao",
    "Data_da_Solicitacao",
    "Dt_Solicitacao",
    "Data_Pedido",
    "Data_Requisicao",
    # Fallbacks se a view não expuser solicitação
    "Data_Coleta_dt",
    "Data_Coleta",
    "Data_Liberacao_dt",
    "Data_Liberacao",
)


def pick_gal_se_date_col(columns: Iterable[str]) -> Optional[str]:
    """Primeira coluna disponível para calcular SE a partir do GAL."""
    cols = set(columns)
    for name in GAL_SE_DATE_CANDIDATES:
        if name in cols:
            return name
    return None


def gal_se_date_is_solicitacao(col: str | None) -> bool:
    """True se a coluna escolhida é de solicitação (não fallback coleta/liberação)."""
    if not col:
        return False
    c = col.casefold()
    return "solicit" in c or "pedido" in c or "requisic" in c


def _as_date(d: DateLike = None) -> date:
    if d is None:
        return date.today()
    if isinstance(d, datetime):
        return d.date()
    return d


def _quarta_da_se(dd: date) -> date:
    """Quarta-feira da SE (domingo–sábado) que contém `dd`."""
    dias_desde_domingo = (dd.weekday() + 1) % 7  # seg=0 … dom=6 → dom=0
    return dd - timedelta(days=dias_desde_domingo) + timedelta(days=3)


def date_to_epi(d: DateLike = None) -> Tuple[int, int]:
    """Retorna (ano_se, semana_epidemiologica) no calendário MS/SINAN."""
    quarta = _quarta_da_se(_as_date(d))
    return int(quarta.year), int((quarta.timetuple().tm_yday - 1) // 7 + 1)


def epi_week_start(ano: int, semana: int) -> date:
    """Domingo (início) da SE `semana` do ano epidemiológico `ano`."""
    jan4 = date(int(ano), 1, 4)  # SE 1 sempre contém 4 de janeiro
    domingo_se1 = jan4 - timedelta(days=(jan4.weekday() + 1) % 7)
    return domingo_se1 + timedelta(weeks=int(semana) - 1)


def epi_week_end(ano: int, semana: int) -> date:
    """Sábado (fim) da SE."""
    return epi_week_start(ano, semana) + timedelta(days=6)


def epi_from_series(dates):
    """Versão vetorizada para pandas: devolve DataFrame com `year` e `week` (Int64).

    Substitui `serie.dt.isocalendar()` mantendo os nomes de coluna usados no
    pipeline (`year`, `week`).
    """
    import pandas as pd

    dt = pd.to_datetime(dates, errors="coerce")
    if not isinstance(dt, pd.Series):
        dt = pd.Series(dt)
    dt = dt.dt.normalize()
    quarta = dt - pd.to_timedelta((dt.dt.day_of_week + 1) % 7, unit="D") + pd.Timedelta(days=3)
    return pd.DataFrame(
        {
            "year": quarta.dt.year.astype("Int64"),
            "week": ((quarta.dt.day_of_year - 1) // 7 + 1).astype("Int64"),
        },
        index=dt.index,
    )


def sql_epi_exprs(date_expr: str) -> Tuple[str, str]:
    """Expressões T-SQL (ano_se, se) no calendário MS, independentes de @@DATEFIRST."""
    quarta = (
        f"DATEADD(day, 3 - ((DATEPART(weekday, {date_expr}) + @@DATEFIRST - 1) % 7), "
        f"CAST({date_expr} AS date))"
    )
    return f"YEAR({quarta})", f"((DATEPART(dayofyear, {quarta}) - 1) / 7 + 1)"


def ano_se(d: DateLike = None) -> int:
    return date_to_epi(d)[0]


def semana_epidemiologica(d: DateLike = None) -> int:
    return date_to_epi(d)[1]


def semana_completa_mais_recente(hoje: DateLike = None) -> Tuple[int, int]:
    """Última SE (domingo–sábado) já encerrada antes de `hoje`.

    Ex.: se hoje cai no meio da SE W (inclusive no sábado), a referência é W−1.
    """
    dd = _as_date(hoje)
    # voltar ao sábado anterior ao domingo que inicia a SE corrente
    ref = dd - timedelta(days=(dd.weekday() + 1) % 7 + 1)
    return date_to_epi(ref)


def format_se(ano: int, semana: int) -> str:
    return f"{int(ano)}-SE{int(semana):02d}"


def epi_ordinal(ano: int, semana: int) -> int:
    """Ordenação ano×semana (suporta SE 1–53)."""
    return int(ano) * 100 + int(semana)


def atraso_semanas(
    se_esperada: Tuple[int, int],
    se_usada: Tuple[int, int],
) -> int:
    """Diferença em semanas (esperada − usada). Positivo = dados atrasados."""
    d0 = epi_week_start(*se_esperada)
    d1 = epi_week_start(*se_usada)
    return int((d0 - d1).days // 7)


def atraso_dias_desde_fim_se(ano: int, semana: int, hoje: DateLike = None) -> int:
    """Dias desde o sábado (fim) da SE usada até `hoje`."""
    dd = _as_date(hoje)
    return max(0, (dd - epi_week_end(ano, semana)).days)


def shift_se(ano: int, semana: int, delta: int) -> Tuple[int, int]:
    """Desloca `delta` semanas respeitando anos com 52 ou 53 SE."""
    return date_to_epi(epi_week_start(ano, semana) + timedelta(weeks=int(delta)))
