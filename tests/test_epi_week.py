# -*- coding: utf-8 -*-
"""Calendário de semana epidemiológica MS/SINAN (domingo–sábado)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from etl.epi_week import (
    atraso_dias_desde_fim_se,
    atraso_semanas,
    date_to_epi,
    epi_from_series,
    epi_week_end,
    epi_week_start,
    semana_completa_mais_recente,
    shift_se,
    sql_epi_exprs,
)

# Início (domingo) da SE 1 em cada ano, conforme calendário epidemiológico do MS.
INICIO_SE1 = {
    2020: date(2019, 12, 29),
    2021: date(2021, 1, 3),
    2022: date(2022, 1, 2),
    2023: date(2023, 1, 1),
    2024: date(2023, 12, 31),
    2025: date(2024, 12, 29),
    2026: date(2026, 1, 4),
    2027: date(2027, 1, 3),
}


@pytest.mark.parametrize("ano,inicio", INICIO_SE1.items())
def test_inicio_da_se1(ano, inicio):
    assert epi_week_start(ano, 1) == inicio
    assert date_to_epi(inicio) == (ano, 1)
    assert date_to_epi(inicio - timedelta(days=1))[0] == ano - 1


def test_anos_com_53_semanas():
    # 2020 e 2025 têm SE 53 no calendário MS.
    assert date_to_epi(date(2021, 1, 2)) == (2020, 53)
    assert date_to_epi(date(2026, 1, 3)) == (2025, 53)
    assert date_to_epi(date(2024, 12, 28)) == (2024, 52)


def test_semana_vai_de_domingo_a_sabado():
    # Caso que motivou a correção: ISO dizia W36/W37.
    assert date_to_epi(date(2026, 9, 5)) == (2026, 35)  # sábado
    assert date_to_epi(date(2026, 9, 6)) == (2026, 36)  # domingo
    assert date_to_epi(date(2026, 9, 11)) == (2026, 36)  # sexta
    assert epi_week_start(2026, 36) == date(2026, 9, 6)
    assert epi_week_end(2026, 36) == date(2026, 9, 12)


def test_ida_e_volta_em_todos_os_dias():
    d = date(2019, 12, 1)
    while d < date(2028, 2, 1):
        ano, se = date_to_epi(d)
        assert 1 <= se <= 53
        assert epi_week_start(ano, se) <= d <= epi_week_end(ano, se)
        d += timedelta(days=1)


def test_semana_completa_mais_recente():
    assert semana_completa_mais_recente(date(2026, 9, 11)) == (2026, 35)
    assert semana_completa_mais_recente(date(2026, 9, 12)) == (2026, 35)  # sábado: SE36 ainda em curso
    assert semana_completa_mais_recente(date(2026, 9, 13)) == (2026, 36)  # domingo seguinte
    assert semana_completa_mais_recente(date(2026, 1, 5)) == (2025, 53)


def test_shift_e_atrasos_respeitam_se53():
    assert shift_se(2026, 1, -1) == (2025, 53)
    assert shift_se(2025, 53, 1) == (2026, 1)
    assert shift_se(2026, 36, -36) == (2025, 53)
    assert atraso_semanas((2026, 2), (2025, 52)) == 3
    assert atraso_dias_desde_fim_se(2026, 35, date(2026, 9, 11)) == 6


def test_vetorizado_igual_ao_escalar():
    datas = pd.Series(pd.date_range("2019-12-01", "2028-01-31", freq="D"))
    datas = pd.concat([datas, pd.Series([pd.NaT])], ignore_index=True)
    out = epi_from_series(datas)
    esperado = [date_to_epi(d.date()) for d in datas.iloc[:-1]]
    assert list(zip(out["year"].iloc[:-1], out["week"].iloc[:-1])) == esperado
    assert out["year"].isna().iloc[-1]


@pytest.mark.parametrize("datefirst", [1, 7])
def test_expressao_sql_independe_de_datefirst(datefirst):
    """Simula as funções T-SQL usadas em `sql_epi_exprs` e compara com Python."""
    ano_sql, se_sql = sql_epi_exprs("d")
    assert "@@DATEFIRST" in ano_sql and "dayofyear" in se_sql

    def datepart_weekday(d):  # SQL Server: 1..7 a partir de DATEFIRST
        return (d.isoweekday() - datefirst) % 7 + 1

    d = date(2019, 12, 1)
    while d < date(2028, 2, 1):
        quarta = d + timedelta(days=3 - ((datepart_weekday(d) + datefirst - 1) % 7))
        assert (quarta.year, (quarta.timetuple().tm_yday - 1) // 7 + 1) == date_to_epi(d)
        d += timedelta(days=1)
