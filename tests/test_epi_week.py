# -*- coding: utf-8 -*-
"""Virada de ano ISO: 2026 tem SE 53, 2027 tem 52."""
from etl.epi_week import semanas_no_ano, shift_se


def test_semanas_no_ano():
    assert semanas_no_ano(2026) == 53
    assert semanas_no_ano(2027) == 52
    assert semanas_no_ano(2020) == 53


def test_shift_virada_2026_2027():
    assert shift_se(2026, 52, 1) == (2026, 53)
    assert shift_se(2026, 53, 1) == (2027, 1)
    assert shift_se(2027, 1, -1) == (2026, 53)
    assert shift_se(2027, 52, 1) == (2028, 1)
    assert shift_se(2027, 2, -3) == (2026, 52)


def test_shift_semana_invalida_limitada():
    # SE 53 não existe em 2027 → tratada como SE 52
    assert shift_se(2027, 53, 0) == (2027, 52)


def test_helpers_legados_delegam():
    import lacen_semana_maturacao as m
    from ml.models import _advance_epiweek

    assert m._shift_se(2027, 1, -1) == (2026, 53)
    assert _advance_epiweek(2027, 52, 1) == (2028, 1)
