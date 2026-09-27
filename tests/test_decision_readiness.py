import json
import pandas as pd

from quality.decision_readiness import (
    DATA_QUALITY_BLOCK,
    NEEDS_EVIDENCE,
    READY,
    evaluate_dec001_readiness,
    evaluate_dec002_readiness,
    evaluate_decision_readiness,
    write_decision_readiness_report,
)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dec001_ready_when_required_evidence_exists(tmp_path):
    _write(tmp_path / "gal_temporal_anchor_summary.json", {
        "rows_total": 100,
        "rows_both_dates": 90,
        "coverage_solicitacao": 0.98,
        "coverage_coleta": 0.91,
        "median_delay_days": 1,
        "p90_delay_days": 3,
        "changed_epi_week_rows": 10,
        "changed_epi_week_pct": 0.11,
        "changed_epi_year_rows": 1,
        "changed_epi_year_pct": 0.01,
        "weeks_compared": 12,
        "weeks_with_count_delta": 4,
        "weeks_with_count_delta_pct": 0.33,
        "max_absolute_weekly_count_diff": 5,
        "sum_absolute_weekly_count_diff": 12,
    })
    (tmp_path / "gal_temporal_anchor_weekly_comparison.csv").write_text(
        "epi_year,epi_week\n2026,37\n", encoding="utf-8"
    )
    (tmp_path / "decision_brief_DEC-001.md").write_text("# brief", encoding="utf-8")
    result = evaluate_dec001_readiness(tmp_path)
    assert result["status"] == READY
    assert result["evidence_complete"] is True


def test_dec001_blocks_when_no_paired_dates(tmp_path):
    _write(tmp_path / "gal_temporal_anchor_summary.json", {
        "rows_total": 10,
        "rows_both_dates": 0,
        "coverage_solicitacao": 1.0,
        "coverage_coleta": 0.0,
        "median_delay_days": 0,
        "p90_delay_days": 0,
        "changed_epi_week_rows": 0,
        "changed_epi_week_pct": 0,
        "changed_epi_year_rows": 0,
        "changed_epi_year_pct": 0,
        "weeks_compared": 0,
        "weeks_with_count_delta": 0,
        "weeks_with_count_delta_pct": 0,
        "max_absolute_weekly_count_diff": 0,
        "sum_absolute_weekly_count_diff": 0,
    })
    (tmp_path / "gal_temporal_anchor_weekly_comparison.csv").write_text(
        "epi_year,epi_week\n", encoding="utf-8"
    )
    (tmp_path / "decision_brief_DEC-001.md").write_text("# brief", encoding="utf-8")
    result = evaluate_dec001_readiness(tmp_path)
    assert result["status"] == DATA_QUALITY_BLOCK


def test_dec002_needs_evidence_when_files_missing(tmp_path):
    result = evaluate_dec002_readiness(tmp_path)
    assert result["status"] in {NEEDS_EVIDENCE, DATA_QUALITY_BLOCK}


def test_dec002_ready_when_comparison_complete_and_no_internal_conflicts(tmp_path):
    _write(tmp_path / "population_source_comparison_summary.json", {
        "analysis_year": 2026,
        "sources": ["A", "B"],
        "territories_total": 142,
        "territories_with_multiple_sources": 100,
        "territories_with_any_difference": 30,
        "max_absolute_difference": 1000,
        "max_relative_difference": 0.03,
        "source_coverage": {"A": 142, "B": 120},
    })
    pd.DataFrame({
        "territory_key": ["IBGE:5103403"],
        "fonte": ["A"],
        "internal_conflict": [False],
    }).to_csv(tmp_path / "population_source_coverage_detail.csv", index=False)
    pd.DataFrame({
        "territory_key": ["IBGE:5103403"],
        "source_a": ["A"],
        "source_b": ["B"],
    }).to_csv(tmp_path / "population_source_pairwise_comparison.csv", index=False)
    _write(tmp_path / "population_governance_v2_1.json", {
        "status": "PENDING_APPROVAL"
    })
    (tmp_path / "decision_brief_DEC-002.md").write_text("# brief", encoding="utf-8")
    result = evaluate_dec002_readiness(tmp_path)
    assert result["status"] == READY
    assert result["internal_conflicts"] == 0


def test_dec002_blocks_on_internal_conflict(tmp_path):
    _write(tmp_path / "population_source_comparison_summary.json", {
        "analysis_year": 2026,
        "sources": ["A"],
        "source_coverage": {"A": 1},
    })
    pd.DataFrame({
        "territory_key": ["IBGE:5103403"],
        "fonte": ["A"],
        "internal_conflict": [True],
    }).to_csv(tmp_path / "population_source_coverage_detail.csv", index=False)
    pd.DataFrame().to_csv(tmp_path / "population_source_pairwise_comparison.csv", index=False)
    _write(tmp_path / "population_governance_v2_1.json", {
        "status": "PENDING_APPROVAL"
    })
    (tmp_path / "decision_brief_DEC-002.md").write_text("# brief", encoding="utf-8")
    result = evaluate_dec002_readiness(tmp_path)
    assert result["status"] == DATA_QUALITY_BLOCK


def test_decision_readiness_report_writes_artifacts(tmp_path):
    report = evaluate_decision_readiness(tmp_path)
    paths = write_decision_readiness_report(report, tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()
