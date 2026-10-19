from lacen_semana_maturacao import _shift_se


def test_shift_se_respects_iso_week_53():
    assert _shift_se(2020, 53, 1) == (2021, 1)
    assert _shift_se(2021, 1, -1) == (2020, 53)


def test_shift_se_regular_year_boundary():
    assert _shift_se(2021, 52, 1) == (2022, 1)
