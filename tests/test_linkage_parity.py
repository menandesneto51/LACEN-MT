import pandas as pd

from quality.linkage_parity import compare_linkage, write_linkage_parity


def _left():
    return pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "tests": [10],
    })


def test_linkage_equal_by_name_and_ibge():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "notificacoes": [3],
    })
    detail, summary = compare_linkage(
        _left(), right,
        source="GAL×SINAN",
        dimensions=("epi_year", "epi_week", "agravo_sinan"),
        metric_col="notificacoes",
    )
    assert detail.loc[0, "linkage_parity"] == "IGUAL"
    assert summary.promotion_status == "PASS"


def test_linkage_recovered_by_ibge_when_name_differs():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABA"],
        "municipio_ibge": ["5103403"],
        "notificacoes": [3],
    })
    detail, summary = compare_linkage(
        _left(), right,
        source="GAL×SINAN",
        dimensions=("epi_year", "epi_week", "agravo_sinan"),
        metric_col="notificacoes",
    )
    assert detail.loc[0, "linkage_parity"] == "RECUPERADO_POR_IBGE"
    assert summary.recovered_by_ibge == 1
    assert summary.promotion_status == "WARN"


def test_linkage_lost_by_ibge_blocks_promotion():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": [pd.NA],
        "notificacoes": [3],
    })
    detail, summary = compare_linkage(
        _left(), right,
        source="GAL×SINAN",
        dimensions=("epi_year", "epi_week", "agravo_sinan"),
        metric_col="notificacoes",
    )
    assert detail.loc[0, "linkage_parity"] == "PERDIDO_COM_IBGE"
    assert summary.lost_by_ibge == 1
    assert summary.promotion_status == "BLOCK"


def test_linkage_conflict_blocks_promotion():
    right = pd.DataFrame({
        "epi_year": [2026, 2026],
        "epi_week": [37, 37],
        "agravo_sinan": ["dengue", "dengue"],
        "municipio": ["CUIABÁ", "OUTRO NOME"],
        "municipio_ibge": [pd.NA, "5103403"],
        "notificacoes": [2, 5],
    })
    detail, summary = compare_linkage(
        _left(), right,
        source="GAL×SINAN",
        dimensions=("epi_year", "epi_week", "agravo_sinan"),
        metric_col="notificacoes",
    )
    assert detail.loc[0, "linkage_parity"] == "CONFLITO"
    assert summary.conflict == 1
    assert summary.promotion_status == "BLOCK"


def test_linkage_no_match_is_warn():
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["VÁRZEA GRANDE"],
        "municipio_ibge": ["5108402"],
        "notificacoes": [3],
    })
    detail, summary = compare_linkage(
        _left(), right,
        source="GAL×SINAN",
        dimensions=("epi_year", "epi_week", "agravo_sinan"),
        metric_col="notificacoes",
    )
    assert detail.loc[0, "linkage_parity"] == "SEM_MATCH"
    assert summary.no_match == 1
    assert summary.promotion_status == "WARN"


def test_linkage_report_writes_summary(tmp_path):
    right = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "agravo_sinan": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "notificacoes": [3],
    })
    report = compare_linkage(
        _left(), right,
        source="GAL×SINAN",
        dimensions=("epi_year", "epi_week", "agravo_sinan"),
        metric_col="notificacoes",
    )
    payload = write_linkage_parity({"GALxSINAN": report}, tmp_path)
    assert payload["promotion_status"] == "PASS"
    assert (tmp_path / "paridade_linkage_resumo.json").exists()
    assert (tmp_path / "paridade_linkage_resumo.txt").exists()
