import pandas as pd

from lacen_analise_avancada import _internacoes_mun, _territory_key_from_row
from lacen_integracao_final_only import _load_population_v2


def test_advanced_territory_key_prefers_ibge():
    row = {"municipio": "CUIABÁ", "municipio_ibge": "5103403"}
    assert _territory_key_from_row(row) == "IBGE:5103403"


def test_advanced_sih_linkage_uses_ibge_when_available():
    sih = [{
        "epi_year": "2026",
        "epi_week": "37",
        "municipio": "CUIABA",
        "municipio_ibge": "5103403",
        "cid_familia": "tuberculose",
        "n_internacoes": "4",
    }]
    assert _internacoes_mun(
        sih,
        (2026, 37),
        "IBGE:5103403",
        familia="tuberculose",
    ) == 4


def test_population_v2_keeps_single_unambiguous_source(tmp_path):
    stage = tmp_path / "staging_dw"
    stage.mkdir()
    pd.DataFrame({
        "codigo_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [700000],
    }).to_csv(stage / "populacao.csv", index=False)
    out = _load_population_v2(tmp_path, 2026, policy_path=tmp_path / "missing_policy.json")
    assert len(out) == 1
    assert out.loc[0, "territory_key"] == "IBGE:5103403"
    assert float(out.loc[0, "populacao_v2"]) == 700000
    assert out.loc[0, "populacao_v2_fonte"] == "DW:POPULACAO"


def test_population_v2_drops_ambiguous_sources_without_priority(tmp_path):
    stage = tmp_path / "staging_dw"
    stage.mkdir()
    pd.DataFrame({
        "codigo_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [700000],
    }).to_csv(stage / "populacao.csv", index=False)
    pd.DataFrame({
        "codigo_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [710000],
    }).to_csv(stage / "populacao_tcu.csv", index=False)
    out = _load_population_v2(tmp_path, 2026, policy_path=tmp_path / "missing_policy.json")
    assert out.empty


def test_population_v2_respects_approved_versioned_priority(tmp_path):
    import json

    stage = tmp_path / "staging_dw"
    stage.mkdir()
    pd.DataFrame({
        "codigo_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [700000],
    }).to_csv(stage / "populacao.csv", index=False)
    pd.DataFrame({
        "codigo_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [710000],
    }).to_csv(stage / "populacao_tcu.csv", index=False)

    policy = tmp_path / "population_policy.json"
    policy.write_text(
        json.dumps({
            "status": "APPROVED",
            "source_priority": ["DW:POPULACAO_TCU", "DW:POPULACAO"],
            "allow_previous_year": False,
        }),
        encoding="utf-8",
    )
    out = _load_population_v2(tmp_path, 2026, policy_path=policy)
    assert len(out) == 1
    assert out.loc[0, "populacao_v2_fonte"] == "DW:POPULACAO_TCU"
    assert float(out.loc[0, "populacao_v2"]) == 710000


def test_population_v2_excludes_internal_conflict_same_source(tmp_path):
    import json

    stage = tmp_path / "staging_dw"
    stage.mkdir()
    pd.DataFrame({
        "codigo_ibge": ["5103403", "5103403"],
        "municipio": ["Cuiabá", "Cuiabá"],
        "ano": [2026, 2026],
        "populacao": [700000, 710000],
    }).to_csv(stage / "populacao.csv", index=False)

    policy = tmp_path / "population_policy.json"
    policy.write_text(
        json.dumps({
            "status": "APPROVED",
            "source_priority": ["DW:POPULACAO"],
            "allow_previous_year": False,
        }),
        encoding="utf-8",
    )
    out = _load_population_v2(tmp_path, 2026, policy_path=policy)
    assert out.empty


def test_population_v2_rejects_unlisted_source_when_policy_is_strict(tmp_path):
    import json

    stage = tmp_path / "staging_dw"
    stage.mkdir()
    pd.DataFrame({
        "codigo_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [700000],
    }).to_csv(stage / "populacao.csv", index=False)

    policy = tmp_path / "population_policy.json"
    policy.write_text(
        json.dumps({
            "status": "APPROVED",
            "source_priority": ["DW:POPULACAO_TCU"],
            "allow_previous_year": False,
            "rules": {"allow_unlisted_sources": False},
        }),
        encoding="utf-8",
    )

    out = _load_population_v2(tmp_path, 2026, policy_path=policy)
    assert out.empty


def test_advanced_sih_linkage_falls_back_to_exact_name_when_source_lacks_code():
    sih = [{
        "epi_year": "2026",
        "epi_week": "37",
        "municipio": "CUIABÁ",
        "municipio_ibge": "",
        "cid_familia": "tuberculose",
        "n_internacoes": "4",
    }]
    assert _internacoes_mun(
        sih,
        (2026, 37),
        "IBGE:5103403",
        municipio_key="CUIABÁ",
        familia="tuberculose",
    ) == 4


def test_advanced_sih_linkage_does_not_fallback_on_conflicting_valid_code():
    sih = [{
        "epi_year": "2026",
        "epi_week": "37",
        "municipio": "CUIABÁ",
        "municipio_ibge": "5108402",
        "cid_familia": "tuberculose",
        "n_internacoes": "4",
    }]
    assert _internacoes_mun(
        sih,
        (2026, 37),
        "IBGE:5103403",
        municipio_key="CUIABÁ",
        familia="tuberculose",
    ) == 0
