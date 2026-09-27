from pathlib import Path

from quality.agent_reviews import load_agent_reviews, summarize_agent_reviews
from quality.decision_registry import load_decision_registry, evaluate_decision_registry


ROOT = Path(__file__).resolve().parents[1]


def test_institutional_decisions_remain_pending_without_specific_approval():
    registry = load_decision_registry(ROOT / "config" / "decision_status_v2_1.json")
    evaluated = evaluate_decision_registry(registry)

    assert evaluated["overall_status"] == "PENDING"
    assert registry["decisions"]["DEC-001"]["status"] == "PENDING"
    assert registry["decisions"]["DEC-002"]["status"] == "PENDING"
    assert registry["decisions"]["DEC-001"]["decided_by"] is None
    assert registry["decisions"]["DEC-002"]["decided_by"] is None
    assert registry["decisions"]["DEC-001"]["decision"] is None
    assert registry["decisions"]["DEC-002"]["decision"] is None


def test_agent_reviews_preserve_block_warn_until_decisions_are_explicit():
    reviews = load_agent_reviews(
        ROOT / "quality" / "reviews" / "v2_1_initial_reviews.json"
    )
    summary = summarize_agent_reviews(reviews)

    assert summary["overall_status"] == "BLOCK"
    assert reviews["clinical_epidemiological_specialist"]["status"] == "BLOCK"
    assert reviews["security_data_governance"]["status"] == "WARN"


def test_adrs_are_pending_and_do_not_claim_approval():
    d1 = (ROOT / "docs" / "decisions" / "DEC-001-ancora-temporal-gal.md").read_text(
        encoding="utf-8"
    )
    d2 = (
        ROOT
        / "docs"
        / "decisions"
        / "DEC-002-prioridade-fontes-populacionais.md"
    ).read_text(encoding="utf-8")

    assert "**Status:** PENDENTE" in d1
    assert "**Status:** PENDENTE" in d2
    assert "autorização explícita no chat Cursor: considerar tudo aprovado" not in d1
    assert "autorização explícita no chat Cursor: considerar tudo aprovado" not in d2


def test_population_governance_is_not_implicitly_approved():
    import json

    policy = json.loads(
        (
            ROOT / "config" / "population_governance_v2_1.json"
        ).read_text(encoding="utf-8")
    )

    assert policy["status"] == "PENDING_APPROVAL"
    assert policy["approved_by"] is None
    assert policy["approved_at"] is None
    assert policy["source_priority"] == []
