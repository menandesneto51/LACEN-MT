# -*- coding: utf-8 -*-
"""Regressão: DEC-001/002 aprovadas institucionalmente sem auto-decisão."""
from __future__ import annotations

import json
from pathlib import Path

from quality.agent_reviews import load_agent_reviews, summarize_agent_reviews
from quality.decision_registry import evaluate_decision_registry, load_decision_registry
from quality.population_governance import load_population_governance


ROOT = Path(__file__).resolve().parents[1]


def test_dec_001_approved_as_solicitacao_anchor_a():
    registry = load_decision_registry(ROOT / "config" / "decision_status_v2_1.json")
    evaluated = evaluate_decision_registry(registry)
    assert evaluated["overall_status"] == "APPROVED"
    d1 = evaluated["decisions"]["DEC-001"]
    assert d1["status"] == "APPROVED"
    assert d1["valid"] is True
    decision = d1["decision"]
    assert decision["alternative"] == "A"
    assert decision["anchor"] == "solicitacao"
    assert decision["historical_series"] == "nao_reprocessar"


def test_dec_002_approved_population_priority():
    registry = load_decision_registry(ROOT / "config" / "decision_status_v2_1.json")
    d2 = registry["decisions"]["DEC-002"]
    assert d2["status"] == "APPROVED"
    assert d2["decision"]["source_priority"] == ["DW:POPULACAO_TOTAL"]

    policy = load_population_governance(
        ROOT / "config" / "population_governance_v2_1.json"
    )
    assert policy["status"] == "APPROVED"
    assert policy["source_priority"] == ["DW:POPULACAO_TOTAL"]
    assert policy["allow_previous_year"] is False
    assert policy["rules"]["allow_unlisted_sources"] is False


def test_agent_reviews_pass_after_institutional_approval():
    reviews = load_agent_reviews(
        ROOT / "quality" / "reviews" / "v2_1_initial_reviews.json"
    )
    summary = summarize_agent_reviews(reviews)
    assert summary["overall_status"] == "PASS"
    assert reviews["clinical_epidemiological_specialist"].status == "PASS"
    assert reviews["security_data_governance"].status == "PASS"
    assert reviews["clinical_epidemiological_specialist"].blockers == []


def test_adrs_marked_approved():
    d1 = (ROOT / "docs" / "decisions" / "DEC-001-ancora-temporal-gal.md").read_text(
        encoding="utf-8"
    )
    d2 = (
        ROOT / "docs" / "decisions" / "DEC-002-prioridade-fontes-populacionais.md"
    ).read_text(encoding="utf-8")
    assert "**Status:** APROVADA" in d1
    assert "[x] A — Solicitação" in d1 or "[x] A — Solicitacao" in d1
    assert "**Status:** APROVADA" in d2
    assert "DW:POPULACAO_TOTAL" in d2


def test_config_still_forbids_automatic_decision():
    registry = json.loads(
        (ROOT / "config" / "decision_status_v2_1.json").read_text(encoding="utf-8")
    )
    assert registry["automatic_decision_allowed"] is False
