import pandas as pd

from quality.territorial_dimension import (
    normalize_population_source,
    select_population_for_year,
)


def test_normalize_population_source_preserves_lineage():
    raw = pd.DataFrame({
        "CODIGO_IBGE": ["5103403"],
        "MUNICIPIO": ["Cuiabá"],
        "ANO": [2026],
        "POPULACAO": [700000],
    })
    dim = normalize_population_source(
        raw,
        source_name="DW:POPULACAO",
        extracted_at="2026-09-26T14:00:00",
        source_version="populacao",
    )
    assert dim.loc[0, "municipio_ibge"] == "5103403"
    assert dim.loc[0, "ano_referencia"] == 2026
    assert dim.loc[0, "populacao"] == 700000
    assert dim.loc[0, "fonte"] == "DW:POPULACAO"
    assert dim.loc[0, "versao_fonte"] == "populacao"
    assert dim.loc[0, "is_fallback"] == False


def test_invalid_ibge_code_is_not_invented():
    raw = pd.DataFrame({
        "codigo_ibge": ["510340"],
        "municipio": ["Cuiabá"],
        "ano": [2026],
        "populacao": [700000],
    })
    dim = normalize_population_source(raw, source_name="DW:POPULACAO")
    assert pd.isna(dim.loc[0, "municipio_ibge"])


def test_select_population_exact_year_without_silent_priority():
    dim = pd.DataFrame({
        "municipio_ibge": ["5103403", "5103403"],
        "municipio": ["Cuiabá", "Cuiabá"],
        "ano_referencia": [2026, 2026],
        "populacao": [700000, 710000],
        "fonte": ["DW:POPULACAO", "DW:POPULACAO_TCU"],
        "versao_fonte": ["a", "b"],
        "extraido_em": ["x", "x"],
        "is_fallback": [False, False],
    })
    selected = select_population_for_year(dim, 2026)
    assert len(selected) == 2


def test_select_population_uses_explicit_source_priority():
    dim = pd.DataFrame({
        "municipio_ibge": ["5103403", "5103403"],
        "municipio": ["Cuiabá", "Cuiabá"],
        "ano_referencia": [2026, 2026],
        "populacao": [700000, 710000],
        "fonte": ["DW:POPULACAO", "DW:POPULACAO_TCU"],
        "versao_fonte": ["a", "b"],
        "extraido_em": ["x", "x"],
        "is_fallback": [False, False],
    })
    selected = select_population_for_year(
        dim,
        2026,
        source_priority=("DW:POPULACAO_TCU", "DW:POPULACAO"),
    )
    assert len(selected) == 1
    assert selected.loc[0, "fonte"] == "DW:POPULACAO_TCU"
    assert selected.loc[0, "populacao"] == 710000


def test_previous_year_is_only_used_when_explicitly_allowed():
    dim = pd.DataFrame({
        "municipio_ibge": ["5103403"],
        "municipio": ["Cuiabá"],
        "ano_referencia": [2025],
        "populacao": [690000],
        "fonte": ["DW:POPULACAO"],
        "versao_fonte": ["a"],
        "extraido_em": ["x"],
        "is_fallback": [False],
    })
    assert select_population_for_year(dim, 2026).empty
    fallback = select_population_for_year(dim, 2026, allow_previous_year=True)
    assert len(fallback) == 1
    assert bool(fallback.loc[0, "is_fallback"]) is True
