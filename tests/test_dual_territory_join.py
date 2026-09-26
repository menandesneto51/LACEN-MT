import pandas as pd

from lacen_integracao_final_only import _merge_metrics_dual_territory_key


def _left(code="5103403", municipio="CUIABÁ"):
    return pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": [municipio],
        "municipio_ibge": [code],
    })


def test_dual_join_prefers_ibge_when_both_have_code():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABA"],
        "municipio_ibge": ["5103403"],
        "notificacoes": [5],
    })
    out = _merge_metrics_dual_territory_key(
        _left(),
        right,
        base_keys=("epi_year", "epi_week", "agravo_sinan"),
        metric_cols=("notificacoes",),
        method_col="match_method",
    )
    assert out.loc[0, "notificacoes"] == 5
    assert out.loc[0, "match_method"] == "IBGE"


def test_dual_join_falls_back_to_exact_name_when_source_has_no_code():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": [pd.NA],
        "notificacoes": [3],
    })
    out = _merge_metrics_dual_territory_key(
        _left(),
        right,
        base_keys=("epi_year", "epi_week", "agravo_sinan"),
        metric_cols=("notificacoes",),
        method_col="match_method",
    )
    assert out.loc[0, "notificacoes"] == 3
    assert out.loc[0, "match_method"] == "NAME_EXACT_FALLBACK"


def test_dual_join_does_not_fallback_when_valid_codes_conflict():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5108402"],
        "notificacoes": [7],
    })
    out = _merge_metrics_dual_territory_key(
        _left(),
        right,
        base_keys=("epi_year", "epi_week", "agravo_sinan"),
        metric_cols=("notificacoes",),
        method_col="match_method",
    )
    assert pd.isna(out.loc[0, "notificacoes"])
    assert out.loc[0, "match_method"] == "UNMATCHED"


def test_dual_join_does_not_use_fuzzy_or_accent_folding():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABA"],
        "municipio_ibge": [pd.NA],
        "notificacoes": [4],
    })
    out = _merge_metrics_dual_territory_key(
        _left(),
        right,
        base_keys=("epi_year", "epi_week", "agravo_sinan"),
        metric_cols=("notificacoes",),
        method_col="match_method",
    )
    assert pd.isna(out.loc[0, "notificacoes"])
    assert out.loc[0, "match_method"] == "UNMATCHED"


def test_dual_join_fallback_rejects_ambiguous_exact_name():
    right = pd.DataFrame({
        "epi_year": [2026, 2026],
        "epi_week": [37, 37],
        "agravo_sinan": ["dengue", "dengue"],
        "municipio": ["CUIABÁ", "CUIABÁ"],
        "municipio_ibge": [pd.NA, pd.NA],
        "notificacoes": [2, 3],
    })
    out = _merge_metrics_dual_territory_key(
        _left(),
        right,
        base_keys=("epi_year", "epi_week", "agravo_sinan"),
        metric_cols=("notificacoes",),
        method_col="match_method",
    )
    assert pd.isna(out.loc[0, "notificacoes"])
    assert out.loc[0, "match_method"] == "UNMATCHED"


def test_dual_join_aggregates_name_variants_with_same_ibge_without_row_duplication():
    right = pd.DataFrame({
        "epi_year": [2026, 2026],
        "epi_week": [37, 37],
        "agravo_sinan": ["dengue", "dengue"],
        "municipio": ["CUIABÁ", "CUIABA"],
        "municipio_ibge": ["5103403", "5103403"],
        "notificacoes": [2, 3],
    })
    out = _merge_metrics_dual_territory_key(
        _left(),
        right,
        base_keys=("epi_year", "epi_week", "agravo_sinan"),
        metric_cols=("notificacoes",),
        method_col="match_method",
    )
    assert len(out) == 1
    assert out.loc[0, "notificacoes"] == 5
    assert out.loc[0, "match_method"] == "IBGE"
