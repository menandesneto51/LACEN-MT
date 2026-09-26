import pandas as pd

from quality.population_governance import (
    evaluate_population_governance,
    write_population_governance_report,
)


def _dim():
    return pd.DataFrame({
        "municipio_ibge": ["5103403", "5103403"],
        "municipio": ["CUIABÁ", "CUIABÁ"],
        "ano_referencia": [2026, 2026],
        "populacao": [700000, 705000],
        "fonte": ["DW:VW_POPULACAO", "DW:POPULACAO_TCU"],
    })


def test_multiple_sources_without_priority_blocks():
    decision = evaluate_population_governance(
        _dim(),
        analysis_year=2026,
        policy={
            "status": "PENDING_APPROVAL",
            "source_priority": [],
            "allow_previous_year": False,
        },
    )
    assert decision.approved is False
    assert any("múltiplas fontes" in x for x in decision.blockers)
    assert any("APPROVED" in x for x in decision.blockers)


def test_approved_priority_removes_ambiguity_block():
    decision = evaluate_population_governance(
        _dim(),
        analysis_year=2026,
        policy={
            "status": "APPROVED",
            "source_priority": ["DW:POPULACAO_TCU", "DW:VW_POPULACAO"],
            "allow_previous_year": False,
        },
    )
    assert decision.approved is True
    assert not any("múltiplas fontes" in x for x in decision.blockers)
    assert not any("APPROVED" in x for x in decision.blockers)


def test_internal_conflict_same_source_blocks():
    dim = pd.DataFrame({
        "municipio_ibge": ["5103403", "5103403"],
        "municipio": ["CUIABÁ", "CUIABÁ"],
        "ano_referencia": [2026, 2026],
        "populacao": [700000, 710000],
        "fonte": ["DW:VW_POPULACAO", "DW:VW_POPULACAO"],
    })
    decision = evaluate_population_governance(
        dim,
        analysis_year=2026,
        policy={
            "status": "APPROVED",
            "source_priority": ["DW:VW_POPULACAO"],
            "allow_previous_year": False,
        },
    )
    assert any("conflito(s) interno(s)" in x for x in decision.blockers)


def test_missing_analysis_year_blocks():
    dim = _dim()
    decision = evaluate_population_governance(
        dim,
        analysis_year=2027,
        policy={
            "status": "APPROVED",
            "source_priority": ["DW:POPULACAO_TCU"],
            "allow_previous_year": False,
        },
    )
    assert any("Não há denominador" in x for x in decision.blockers)


def test_population_governance_writes_artifacts(tmp_path):
    decision = evaluate_population_governance(
        _dim(),
        analysis_year=2026,
        policy={
            "status": "PENDING_APPROVAL",
            "source_priority": [],
            "allow_previous_year": False,
        },
    )
    paths = write_population_governance_report(decision, tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()


def test_approved_strict_policy_blocks_uncovered_territory():
    dim = pd.DataFrame({
        "municipio_ibge": ["5103403", "5108402"],
        "municipio": ["CUIABÁ", "VÁRZEA GRANDE"],
        "ano_referencia": [2026, 2026],
        "populacao": [700000, 300000],
        "fonte": ["DW:POPULACAO_TCU", "DW:POPULACAO"],
    })
    decision = evaluate_population_governance(
        dim,
        analysis_year=2026,
        policy={
            "status": "APPROVED",
            "source_priority": ["DW:POPULACAO_TCU"],
            "allow_previous_year": False,
            "rules": {"allow_unlisted_sources": False},
        },
    )
    assert any("território(s) sem fonte populacional aprovada" in x for x in decision.blockers)
