import json
from pathlib import Path


MANIFEST = Path("config/agent_orchestration_v2_1.json")


def _load():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_agent_orchestration_manifest_exists_and_is_versioned():
    payload = _load()
    assert payload["schema_version"] == "1.0"
    assert payload["project"] == "LACEN-MT"
    assert payload["release"] == "v2.1"
    assert payload["automatic_release_allowed"] is False


def test_ses_data_catalog_is_first_and_blocks_missing_preflight():
    payload = _load()
    assert payload["orchestration_order"][0] == "SES_DATA_CATALOG"
    catalog = payload["agents"]["SES_DATA_CATALOG"]
    assert catalog["output"] == "CatalogEvidencePack"
    assert catalog["blocking_rule"] == "missing_catalog_evidence_for_new_data_dependency"
    assert "indicator_change" in catalog["required_when"]


def test_required_specialist_agents_are_declared():
    payload = _load()
    required = {
        "ML_SPECIALIST",
        "STATISTICS_SPECIALIST",
        "LAB_INTELLIGENCE_SPECIALIST",
        "GENOMIC_INTELLIGENCE_SPECIALIST",
        "SUPPLY_CHAIN_SPECIALIST",
        "TECHNICAL_WRITING_ABNT",
        "RISK_REGISTER_STEWARD",
        "EMERGENCY_RESPONSE_COORDINATOR",
    }
    assert required.issubset(payload["agents"])


def test_epidemiological_and_documentation_safety_constraints_are_preserved():
    payload = _load()
    lab = payload["agents"]["LAB_INTELLIGENCE_SPECIALIST"]["constraints"]
    writing = payload["agents"]["TECHNICAL_WRITING_ABNT"]["constraints"]
    assert "exam_is_not_case" in lab
    assert "ABNT_NBR_6023_references" in writing
    assert "titles_for_tables_figures_images_charts" in writing
    assert "sources_for_tables_figures_images_charts" in writing


def test_cursor_and_human_governance_remain_explicit():
    payload = _load()
    rules = set(payload["global_rules"])
    assert "Cursor_is_the_default_implementation_environment" in rules
    assert "human_decision_required_for_institutional_policy" in rules
    assert "BLOCK_must_not_be_bypassed" in rules


def test_genomic_intelligence_is_always_in_scope_for_lacen_mt():
    payload = _load()
    genomic = payload["agents"]["GENOMIC_INTELLIGENCE_SPECIALIST"]
    assert genomic["always_in_scope"] is True
    assert genomic["readiness_contract"] == "docs/vigilancia_genomica_v2_1.md"
    assert "lacen_mt_product" in genomic["required_when"]
    assert "WARN_or_BLOCK" in genomic["status_rule"]


def test_risk_agents_preserve_human_decision_and_no_auto_emergency():
    payload = _load()
    steward = payload["agents"]["RISK_REGISTER_STEWARD"]
    coordinator = payload["agents"]["EMERGENCY_RESPONSE_COORDINATOR"]
    assert "no_automatic_risk_closure" in steward["constraints"]
    assert "residual_risk_required_for_control_or_closure" in steward["constraints"]
    assert "no_automatic_emergency_declaration" in coordinator["constraints"]
    assert "no_automatic_coes_activation" in coordinator["constraints"]
