from pathlib import Path
import json

from quality.decision_evidence_packets import (
    build_dec001_evidence_packet,
    write_decision_evidence_packets,
)


def test_dec001_packet_fills_evidence_without_deciding(tmp_path: Path):
    summary = {
        "rows_total": 100,
        "rows_both_dates": 80,
        "coverage_solicitacao": 0.9,
        "coverage_coleta": 0.85,
        "median_delay_days": 2.0,
        "p90_delay_days": 7.0,
        "changed_epi_week_rows": 10,
        "changed_epi_week_pct": 0.125,
        "changed_epi_year_rows": 1,
        "changed_epi_year_pct": 0.0125,
        "weeks_compared": 20,
        "weeks_with_count_delta": 5,
        "weeks_with_count_delta_pct": 0.25,
        "max_absolute_weekly_count_diff": 12,
        "sum_absolute_weekly_count_diff": 40,
    }
    (tmp_path / "gal_temporal_anchor_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    (tmp_path / "decision_brief_DEC-001.json").write_text(
        json.dumps(
            {
                "options": [
                    {"id": "A", "label": "Solicitacao"},
                    {"id": "B", "label": "Coleta"},
                ]
            }
        ),
        encoding="utf-8",
    )
    text = build_dec001_evidence_packet(tmp_path)
    assert "Cobertura Data de Solicitacao: 90,0%" in text
    assert "NAO escolhe alternativa" in text
    assert "- [ ] A —" in text
    assert "- [x]" not in text
    assert "PENDENTE" in text


def test_write_packets_creates_files(tmp_path: Path):
    (tmp_path / "gal_temporal_anchor_summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "population_source_comparison_summary.json").write_text(
        json.dumps({"sources": ["POPULACAO_TCU"], "territories_total": 10}),
        encoding="utf-8",
    )
    (tmp_path / "population_governance_v2_1.json").write_text(
        json.dumps(
            {"status": "PENDING_APPROVAL", "approved": False, "source_priority": []}
        ),
        encoding="utf-8",
    )
    paths = write_decision_evidence_packets(tmp_path)
    assert paths["dec001"].exists()
    assert paths["dec002"].exists()
    text2 = paths["dec002"].read_text(encoding="utf-8")
    assert "DEC-002" in text2
    assert "NAO aprova prioridade" in text2
