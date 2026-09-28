from quality.decision_registry import (
    evaluate_decision_registry,
    validate_decision,
    write_decision_registry_report,
)


def test_pending_decisions_keep_registry_pending():
    evaluated = evaluate_decision_registry({
        "decisions": {
            "DEC-001": {"status": "PENDING"},
            "DEC-002": {"status": "PENDING"},
        }
    })
    assert evaluated["overall_status"] == "PENDING"
    assert evaluated["all_required_decisions_approved"] is False
    assert len(evaluated["conditions"]) == 2


def test_approved_decision_requires_metadata_and_evidence():
    item = validate_decision("DEC-001", {
        "status": "APPROVED",
        "decision": "Usar coleta.",
        "evidence": ["brief.md"],
    })
    assert item.valid is False
    assert any("decided_by" in x for x in item.validation_errors)
    assert any("decided_at" in x for x in item.validation_errors)


def test_both_approved_make_registry_approved():
    evaluated = evaluate_decision_registry({
        "decisions": {
            "DEC-001": {
                "status": "APPROVED",
                "decided_by": "Comitê A",
                "decided_at": "2026-09-26",
                "evidence": ["gal_temporal_anchor_summary.json"],
                "decision": {"anchor": "collection"},
            },
            "DEC-002": {
                "status": "APPROVED",
                "decided_by": "Comitê B",
                "decided_at": "2026-09-26",
                "evidence": ["population_source_comparison_summary.json"],
                "decision": {"source_priority": ["DW:POPULACAO_TCU"]},
            },
        }
    })
    assert evaluated["overall_status"] == "APPROVED"
    assert evaluated["all_required_decisions_approved"] is True


def test_rejected_decision_blocks_registry():
    evaluated = evaluate_decision_registry({
        "decisions": {
            "DEC-001": {
                "status": "REJECTED",
                "decided_by": "Comitê A",
                "decided_at": "2026-09-26",
                "evidence": ["brief.md"],
                "decision": "Não aprovar mudança.",
            },
            "DEC-002": {"status": "PENDING"},
        }
    })
    assert evaluated["overall_status"] == "BLOCK"
    assert any("DEC-001 foi REJECTED" in x for x in evaluated["blockers"])


def test_invalid_completed_decision_blocks_registry():
    evaluated = evaluate_decision_registry({
        "decisions": {
            "DEC-001": {"status": "APPROVED"},
            "DEC-002": {"status": "PENDING"},
        }
    })
    assert evaluated["overall_status"] == "BLOCK"
    assert any("registro inválido" in x for x in evaluated["blockers"])


def test_decision_registry_writes_artifacts(tmp_path):
    evaluated = evaluate_decision_registry({
        "decisions": {
            "DEC-001": {"status": "PENDING"},
            "DEC-002": {"status": "PENDING"},
        }
    })
    paths = write_decision_registry_report(evaluated, tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()


def test_completed_decision_with_missing_runtime_evidence_blocks(tmp_path):
    evaluated = evaluate_decision_registry(
        {
            "decisions": {
                "DEC-001": {
                    "status": "APPROVED",
                    "decided_by": "Comitê A",
                    "decided_at": "2026-09-26",
                    "evidence": ["missing.json"],
                    "decision": {"anchor": "collection"},
                },
                "DEC-002": {"status": "PENDING"},
            }
        },
        evidence_dir=tmp_path,
    )
    assert evaluated["overall_status"] == "BLOCK"
    assert any("evidência ausente" in x for x in evaluated["blockers"])


def test_completed_decision_with_existing_runtime_evidence_is_valid(tmp_path):
    (tmp_path / "evidence.json").write_text("{}", encoding="utf-8")
    evaluated = evaluate_decision_registry(
        {
            "decisions": {
                "DEC-001": {
                    "status": "APPROVED",
                    "decided_by": "Comitê A",
                    "decided_at": "2026-09-26",
                    "evidence": ["evidence.json"],
                    "decision": {"anchor": "collection"},
                },
                "DEC-002": {"status": "PENDING"},
            }
        },
        evidence_dir=tmp_path,
    )
    assert evaluated["overall_status"] == "PENDING"
    assert not any("evidência ausente" in x for x in evaluated["blockers"])
