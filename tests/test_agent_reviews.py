import pytest

from quality.agent_reviews import (
    AgentReview,
    default_agent_reviews,
    summarize_agent_reviews,
    write_agent_reviews,
)


def test_default_agent_reviews_start_pending():
    reviews = default_agent_reviews()
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PENDING"
    assert len(summary["pending_agents"]) == 10
    assert summary["all_required_reviews_passed"] is False


def test_block_requires_explicit_blocker():
    review = AgentReview(
        agent="Chief Architect",
        status="BLOCK",
        decision="Não aprovar.",
    )
    with pytest.raises(ValueError):
        review.validate()


def test_completed_review_requires_decision():
    review = AgentReview(agent="QA", status="PASS")
    with pytest.raises(ValueError):
        review.validate()


def test_all_pass_produces_pass_summary():
    reviews = default_agent_reviews()
    for review in reviews.values():
        review.status = "PASS"
        review.decision = "Aprovado no escopo do parecer."
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PASS"
    assert summary["all_required_reviews_passed"] is True


def test_warn_keeps_overall_pending():
    reviews = default_agent_reviews()
    for review in reviews.values():
        review.status = "PASS"
        review.decision = "Aprovado."
    reviews["qa"].status = "WARN"
    reviews["qa"].decision = "Aprovado com ressalvas."
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PENDING"
    assert "QA" in summary["warning_agents"]


def test_block_dominates_summary():
    reviews = default_agent_reviews()
    for review in reviews.values():
        review.status = "PASS"
        review.decision = "Aprovado."
    reviews["security_data_governance"].status = "BLOCK"
    reviews["security_data_governance"].decision = "Não aprovar."
    reviews["security_data_governance"].blockers = ["Lineage insuficiente."]
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "BLOCK"
    assert any("Lineage insuficiente" in x for x in summary["blockers"])


def test_agent_review_artifacts(tmp_path):
    reviews = default_agent_reviews()
    paths = write_agent_reviews(reviews, tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()


def test_agent_review_preserves_evidence_in_artifact(tmp_path):
    reviews = default_agent_reviews()
    reviews["qa"].status = "PASS"
    reviews["qa"].decision = "Aprovado."
    reviews["qa"].evidence = {
        "workflow_run_number": 262,
        "head_sha": "6bf4d2978c80b62043b2faa7ea482e24334c20e7",
        "conclusion": "success",
    }
    paths = write_agent_reviews(reviews, tmp_path)
    payload = paths["json"].read_text(encoding="utf-8")
    assert '"workflow_run_number": 262' in payload
    assert '"conclusion": "success"' in payload


def test_not_applicable_is_valid_completed_state_and_does_not_block_summary():
    reviews = default_agent_reviews()
    for review in reviews.values():
        review.status = "PASS"
        review.decision = "Aprovado."
    reviews["supply_chain_specialist"].status = "NOT_APPLICABLE"
    reviews["supply_chain_specialist"].decision = "Fora do escopo atual."
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PASS"
    assert summary["all_required_reviews_passed"] is True


def test_specialist_warn_keeps_review_visible_as_pending():
    reviews = default_agent_reviews()
    for review in reviews.values():
        review.status = "PASS"
        review.decision = "Aprovado."
    reviews["ml_specialist"].status = "WARN"
    reviews["ml_specialist"].decision = "Requer backtest real."
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PENDING"
    assert "ML Specialist" in summary["warning_agents"]


def test_genomic_warn_keeps_project_review_pending():
    reviews = default_agent_reviews()
    for review in reviews.values():
        review.status = "PASS"
        review.decision = "Aprovado."
    reviews["genomic_intelligence_specialist"].status = "WARN"
    reviews["genomic_intelligence_specialist"].decision = "Fonte genômica ainda em readiness."
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PENDING"
    assert "Genomic Intelligence Specialist" in summary["warning_agents"]
