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
    out = _load_population_v2(tmp_path, 2026)
    assert len(out) == 1
    assert out.loc[0, "territory_key"] == "IBGE:5103403"
    assert float(out.loc[0, "populacao_v2"]) == 700000
    assert out.loc[0, "populacao_v2_fonte"] == "DW:POPULACAO"


def test_population_v2_drops_ambiguous_sources_without_priority(tmp_path, monkeypatch):
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
    monkeypatch.delenv("LACEN_POPULATION_SOURCE_PRIORITY", raising=False)
    out = _load_population_v2(tmp_path, 2026)
    assert out.empty


def test_population_v2_respects_explicit_priority(tmp_path, monkeypatch):
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
    monkeypatch.setenv(
        "LACEN_POPULATION_SOURCE_PRIORITY",
        "DW:POPULACAO_TCU,DW:POPULACAO",
    )
    out = _load_population_v2(tmp_path, 2026)
    assert len(out) == 1
    assert out.loc[0, "populacao_v2_fonte"] == "DW:POPULACAO_TCU"
    assert float(out.loc[0, "populacao_v2"]) == 710000
