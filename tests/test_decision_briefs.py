import json

from quality.decision_briefs import (
    build_population_source_brief,
    build_temporal_anchor_brief,
    write_decision_briefs,
)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_temporal_brief_uses_real_summary_fields(tmp_path):
    _write(tmp_path / "gal_temporal_anchor_summary.json", {
        "rows_total": 100,
        "rows_both_dates": 90,
        "coverage_solicitacao": 0.98,
        "coverage_coleta": 0.91,
        "median_delay_days": 1,
        "p90_delay_days": 3,
        "changed_epi_week_rows": 12,
        "changed_epi_week_pct": 0.1333,
        "changed_epi_year_rows": 1,
        "changed_epi_year_pct": 0.0111,
        "weeks_compared": 10,
        "weeks_with_count_delta": 4,
        "weeks_with_count_delta_pct": 0.4,
        "max_absolute_weekly_count_diff": 5,
        "sum_absolute_weekly_count_diff": 11,
    })
    brief = build_temporal_anchor_brief(tmp_path)
    assert brief["decision_id"] == "DEC-001"
    assert brief["facts"]["changed_epi_week_rows"] == 12
    assert brief["decision"] is None
    assert brief["automatic_decision_allowed"] is False


def test_population_brief_keeps_decision_pending(tmp_path):
    _write(tmp_path / "population_source_comparison_summary.json", {
        "analysis_year": 2026,
        "sources": ["A", "B"],
        "territories_total": 142,
        "territories_with_multiple_sources": 100,
        "territories_with_any_difference": 50,
        "max_absolute_difference": 10000,
        "max_relative_difference": 0.08,
        "source_coverage": {"A": 142, "B": 120},
    })
    _write(tmp_path / "population_governance_v2_1.json", {
        "status": "PENDING_APPROVAL",
        "approved": False,
        "blockers": ["Política pendente."],
        "source_priority": [],
    })
    brief = build_population_source_brief(tmp_path)
    assert brief["decision_id"] == "DEC-002"
    assert brief["facts"]["territories_total"] == 142
    assert brief["decision"]["source_priority"] is None
    assert brief["automatic_decision_allowed"] is False


def test_write_decision_briefs_creates_four_artifacts(tmp_path):
    paths = write_decision_briefs(tmp_path)
    assert paths["temporal_json"].exists()
    assert paths["temporal_markdown"].exists()
    assert paths["population_json"].exists()
    assert paths["population_markdown"].exists()

    temporal_md = paths["temporal_markdown"].read_text(encoding="utf-8")
    population_md = paths["population_markdown"].read_text(encoding="utf-8")
    assert "Decisão automática" in temporal_md
    assert "Decisão automática" in population_md
