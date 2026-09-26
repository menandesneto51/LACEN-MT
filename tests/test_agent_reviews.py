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
    assert len(summary["pending_agents"]) == 4
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
