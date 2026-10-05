# -*- coding: utf-8 -*-
"""Regressão: decisões institucionais seguem o endosso formal, não chat."""
from __future__ import annotations

import json
from pathlib import Path

from quality.agent_reviews import load_agent_reviews, summarize_agent_reviews
from quality.decision_registry import evaluate_decision_registry, load_decision_registry
from quality.population_governance import load_population_governance


ROOT = Path(__file__).resolve().parents[1]


def test_endorsement_file_is_present_and_valid():
    import importlib.util

    path = ROOT / "config" / "institutional_endorsement_v2_1.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "aplicar", ROOT / "scripts" / "aplicar_aprovacao_institucional_v2_1.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert mod.validate_endorsement(payload) == []
    assert "chat cursor" not in json.dumps(payload).casefold()


def test_dec_001_002_approved_from_endorsement():
    registry = load_decision_registry(ROOT / "config" / "decision_status_v2_1.json")
    evaluated = evaluate_decision_registry(registry)
    assert evaluated["overall_status"] == "APPROVED"
    d1 = evaluated["decisions"]["DEC-001"]
    d2 = evaluated["decisions"]["DEC-002"]
    assert d1["status"] == "APPROVED"
    assert d2["status"] == "APPROVED"
    assert d1["decision"]["alternative"] == "A"
    assert d1["decision"]["anchor"] == "solicitacao"
    assert d2["decision"]["source_priority"] == ["DW:POPULACAO_TOTAL"]
    assert "Menandes Neto" in str(d1["decided_by"])
    assert "institutional_endorsement_v2_1.json" in d1["evidence"]


def test_population_governance_approved_from_endorsement():
    policy = load_population_governance(
        ROOT / "config" / "population_governance_v2_1.json"
    )
    assert policy["status"] == "APPROVED"
    assert policy["source_priority"] == ["DW:POPULACAO_TOTAL"]
    assert policy["allow_previous_year"] is False
    assert "Menandes Neto" in str(policy["approved_by"])


def test_core_institutional_reviews_pass_after_formal_endorsement():
    reviews = load_agent_reviews(
        ROOT / "quality" / "reviews" / "v2_1_initial_reviews.json"
    )
    summary = summarize_agent_reviews(reviews)
    # DEC-001/DEC-002 estão aprovadas, mas especialistas operacionais podem
    # manter WARN legítimo sem reabrir a decisão institucional.
    assert summary["overall_status"] == "PENDING"
    assert reviews["clinical_epidemiological_specialist"].status == "PASS"
    assert reviews["security_data_governance"].status == "PASS"
    assert reviews["laboratory_intelligence_specialist"].status == "PASS"
    assert reviews["statistics_specialist"].status == "PASS"
    assert reviews["clinical_epidemiological_specialist"].blockers == []
    assert "ML Specialist" in summary["warning_agents"]
    assert "Genomic Intelligence Specialist" in summary["warning_agents"]
    assert "Technical Writing/ABNT" in summary["warning_agents"]


def test_adrs_mark_approved_without_chat_language():
    d1 = (ROOT / "docs" / "decisions" / "DEC-001-ancora-temporal-gal.md").read_text(
        encoding="utf-8"
    )
    d2 = (
        ROOT / "docs" / "decisions" / "DEC-002-prioridade-fontes-populacionais.md"
    ).read_text(encoding="utf-8")
    assert "**Status:** APROVADA" in d1
    assert "**Status:** APROVADA" in d2
    assert "Menandes Neto" in d1
    assert "considerar tudo aprovado" not in d1.casefold()
    assert "chat cursor" not in d1.casefold()
    assert "DW:POPULACAO_TOTAL" in d2


def test_automatic_decision_still_forbidden():
    registry = json.loads(
        (ROOT / "config" / "decision_status_v2_1.json").read_text(encoding="utf-8")
    )
    assert registry["automatic_decision_allowed"] is False
