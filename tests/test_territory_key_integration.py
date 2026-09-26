import pandas as pd

from etl.build_weekly_from_gal import weekly_from_dw_agg
from lacen_integracao_final_only import _add_territory_key, prepare_sinan_for_join, prepare_sim_for_join


def test_weekly_from_dw_agg_preserves_ibge_code():
    agg = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "agravo_raw": ["dengue"],
        "exame_raw": ["ns1"],
        "n_registros": [10],
        "n_positivos_proxy": [2],
    })
    tests, pos = weekly_from_dw_agg(agg)
    assert tests.loc[0, "municipio_ibge"] == "5103403"
    assert pos.loc[0, "municipio_ibge"] == "5103403"
    assert int(pos.loc[0, "tests"]) == 10
    assert int(pos.loc[0, "positives"]) == 2


def test_territory_key_prefers_ibge_over_name():
    df = pd.DataFrame({
        "municipio": ["CUIABA"],
        "municipio_ibge": ["5103403"],
    })
    out = _add_territory_key(df)
    assert out.loc[0, "territory_key"] == "IBGE:5103403"


def test_territory_key_falls_back_to_normalized_name_without_fuzzy_match():
    df = pd.DataFrame({"municipio": ["  Cuiabá  "]})
    out = _add_territory_key(df)
    assert out.loc[0, "territory_key"] == "NAME:CUIABÁ"
    assert pd.isna(out.loc[0, "municipio_ibge"])


def test_prepare_sinan_groups_by_territory_key():
    sinan = pd.DataFrame({
        "epi_year": [2026, 2026],
        "epi_week": [37, 37],
        "municipio": ["Cuiabá", "CUIABA"],
        "municipio_ibge": ["5103403", "5103403"],
        "target": ["dengue", "dengue"],
        "notificacoes": [2, 3],
        "obitos_sinan": [0, 0],
        "encerrados_sinan": [1, 1],
    })
    out = prepare_sinan_for_join(sinan)
    assert len(out) == 1
    assert out.loc[0, "territory_key"] == "IBGE:5103403"
    assert int(out.loc[0, "notificacoes"]) == 5


def test_prepare_sim_groups_by_territory_key():
    sim = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "ano": [2026],
        "municipio": ["Cuiabá"],
        "municipio_ibge": ["5103403"],
        "target": ["dengue"],
        "obitos_sim": [1],
    })
    out = prepare_sim_for_join(sim)
    assert len(out) == 1
    assert out.loc[0, "territory_key"] == "IBGE:5103403"
    assert int(out.loc[0, "obitos_sim"]) == 1
