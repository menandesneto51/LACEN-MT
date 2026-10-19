import pandas as pd

from quality.gal_temporal_anchor_analysis import (
    analyze_temporal_anchor,
    write_temporal_anchor_analysis,
)


def test_temporal_anchor_detects_week_change():
    df = pd.DataFrame({
        "Data_Solicitacao": ["2026-09-07", "2026-09-08"],
        "Data_Coleta": ["2026-09-06", "2026-09-08"],
    })
    detail, summary = analyze_temporal_anchor(df)
    assert summary.rows_total == 2
    assert summary.rows_both_dates == 2
    assert summary.changed_epi_week_rows == 1
    assert summary.changed_epi_week_pct == 0.5
    assert summary.weeks_compared == 2
    assert summary.weeks_with_count_delta == 2
    assert summary.weeks_with_count_delta_pct == 1.0
    assert summary.max_absolute_weekly_count_diff == 1
    assert summary.sum_absolute_weekly_count_diff == 2
    assert detail["delay_days"].tolist() == [1, 0]


def test_temporal_anchor_detects_iso_year_change():
    df = pd.DataFrame({
        "Data_Solicitacao": ["2021-01-04"],
        "Data_Coleta": ["2021-01-03"],
    })
    _, summary = analyze_temporal_anchor(df)
    assert summary.changed_epi_year_rows == 1
    assert summary.changed_epi_year_pct == 1.0


def test_temporal_anchor_handles_missing_dates():
    df = pd.DataFrame({
        "Data_Solicitacao": ["2026-09-07", None],
        "Data_Coleta": [None, "2026-09-08"],
    })
    detail, summary = analyze_temporal_anchor(df)
    assert summary.rows_both_dates == 0
    assert summary.coverage_solicitacao == 0.5
    assert summary.coverage_coleta == 0.5
    assert detail.empty


def test_temporal_anchor_requires_both_date_columns():
    df = pd.DataFrame({"Data_Solicitacao": ["2026-09-07"]})
    try:
        analyze_temporal_anchor(df)
    except ValueError:
        pass
    else:
        raise AssertionError("deveria exigir data de solicitação e coleta")


def test_temporal_anchor_writes_artifacts(tmp_path):
    df = pd.DataFrame({
        "Data_Solicitacao": ["2026-09-07"],
        "Data_Coleta": ["2026-09-06"],
    })
    detail, summary = analyze_temporal_anchor(df)
    paths = write_temporal_anchor_analysis(detail, summary, tmp_path)
    assert paths["detail_csv"].exists()
    assert paths["weekly_comparison_csv"].exists()
    assert paths["summary_json"].exists()
    assert paths["summary_txt"].exists()
