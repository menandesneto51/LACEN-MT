import pandas as pd

from quality.population_source_comparison import (
    compare_population_sources,
    write_population_source_comparison,
)


def _dim():
    return pd.DataFrame({
        "municipio_ibge": ["5103403", "5103403", "5108402"],
        "municipio": ["CUIABÁ", "CUIABÁ", "VÁRZEA GRANDE"],
        "ano_referencia": [2026, 2026, 2026],
        "populacao": [700000, 710000, 300000],
        "fonte": ["DW:POPULACAO", "DW:POPULACAO_TCU", "DW:POPULACAO"],
    })


def test_population_source_comparison_detects_coverage_and_difference():
    source_detail, pair_detail, summary = compare_population_sources(
        _dim(),
        analysis_year=2026,
    )
    assert summary.territories_total == 2
    assert summary.territories_with_multiple_sources == 1
    assert summary.territories_with_any_difference == 1
    assert summary.source_coverage["DW:POPULACAO"] == 2
    assert summary.source_coverage["DW:POPULACAO_TCU"] == 1
    assert len(pair_detail) == 1
    assert float(pair_detail.loc[0, "absolute_difference"]) == 10000


def test_population_source_comparison_marks_internal_conflict():
    dim = pd.DataFrame({
        "municipio_ibge": ["5103403", "5103403"],
        "municipio": ["CUIABÁ", "CUIABÁ"],
        "ano_referencia": [2026, 2026],
        "populacao": [700000, 710000],
        "fonte": ["DW:POPULACAO", "DW:POPULACAO"],
    })
    source_detail, pair_detail, summary = compare_population_sources(
        dim,
        analysis_year=2026,
    )
    assert bool(source_detail.loc[0, "internal_conflict"]) is True
    assert pair_detail.empty
    assert summary.territories_total == 1


def test_population_source_comparison_ignores_other_years():
    dim = _dim().copy()
    dim.loc[len(dim)] = ["5103403", "CUIABÁ", 2025, 690000, "DW:OUTRA"]
    _, _, summary = compare_population_sources(dim, analysis_year=2026)
    assert "DW:OUTRA" not in summary.sources


def test_population_source_comparison_writes_artifacts(tmp_path):
    source_detail, pair_detail, summary = compare_population_sources(
        _dim(),
        analysis_year=2026,
    )
    paths = write_population_source_comparison(
        source_detail,
        pair_detail,
        summary,
        tmp_path,
    )
    assert paths["source_detail_csv"].exists()
    assert paths["pair_detail_csv"].exists()
    assert paths["summary_json"].exists()
    assert paths["summary_txt"].exists()
