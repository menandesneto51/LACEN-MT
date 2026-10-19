import json

import numpy as np
import pandas as pd

from quality.parity_report import build_parity_report, write_parity_report


def _base(pop_legacy=100000, pop_v2=100000):
    return pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "target": ["dengue"],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "territory_key": ["IBGE:5103403"],
        "tests": [100],
        "positives": [10],
        "notificacoes": [12],
        "obitos_sim": [1],
        "populacao": [pop_legacy],
        "populacao_v2": [pop_v2],
        "populacao_v2_fonte": ["DW:POPULACAO"],
        "populacao_v2_ano": [2026],
        "solicitacoes_100k": [100.0],
        "solicitacoes_100k_v2": [100000 * 100 / pop_v2],
        "incidencia_100k": [10.0],
        "incidencia_100k_v2": [100000 * 10 / pop_v2],
        "notificacoes_100k": [12.0],
        "notificacoes_100k_v2": [100000 * 12 / pop_v2],
        "mortalidade_100k": [1.0],
        "mortalidade_100k_v2": [100000 * 1 / pop_v2],
    })


def test_parity_pass_when_legacy_and_v2_match():
    detail, summary = build_parity_report(_base())
    assert summary.status == "PASS"
    assert detail.loc[0, "parity_status"] == "PASS"
    assert summary.ibge_rows == 1
    assert summary.rows_without_v2_population == 0


def test_parity_warns_when_v2_denominator_missing():
    df = _base()
    df["populacao_v2"] = np.nan
    for col in (
        "solicitacoes_100k_v2",
        "incidencia_100k_v2",
        "notificacoes_100k_v2",
        "mortalidade_100k_v2",
    ):
        df[col] = np.nan
    detail, summary = build_parity_report(df)
    assert summary.status == "WARN"
    assert detail.loc[0, "parity_status"] == "WARN"
    assert detail.loc[0, "parity_reason"] == "V2_SEM_DENOMINADOR"


def test_parity_blocks_promotion_on_large_denominator_difference():
    detail, summary = build_parity_report(_base(pop_v2=70000))
    assert summary.status == "BLOCK"
    assert detail.loc[0, "parity_status"] == "BLOCK"
    assert summary.max_population_rel_diff > 0.20


def test_parity_warns_on_small_material_difference():
    detail, summary = build_parity_report(_base(pop_v2=94000))
    assert summary.status == "WARN"
    assert detail.loc[0, "parity_status"] == "WARN"


def test_parity_report_writes_auditable_artifacts(tmp_path):
    detail, summary = build_parity_report(_base())
    paths = write_parity_report(detail, summary, tmp_path)
    assert paths["detail_csv"].exists()
    assert paths["summary_json"].exists()
    assert paths["summary_txt"].exists()
    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["rows"] == 1
