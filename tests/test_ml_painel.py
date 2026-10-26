# -*- coding: utf-8 -*-
"""Painel de features denso, SE de referência e rótulos sem futuro inventado."""
import pandas as pd
import pytest

from ml.features import (
    build_panel_features,
    canon_municipio,
    densify_panel,
    latest_week_snapshot,
    reference_week,
)
from ml.train import _make_labels


@pytest.fixture(autouse=True)
def _sem_override(monkeypatch):
    monkeypatch.delenv("LACEN_SE_REFERENCIA", raising=False)
    monkeypatch.setenv("LACEN_ML_SOMENTE_MT", "1")


def _weekly(rows):
    return pd.DataFrame(rows, columns=["municipio", "target", "epi_year", "epi_week", "tests", "positives"])


def test_painel_denso_preenche_semanas_sem_exame_com_zero():
    w = _weekly([
        ("CUIABA", "dengue", 2026, 30, 10, 2),
        ("CUIABA", "dengue", 2026, 33, 4, 0),
        ("SINOP", "dengue", 2026, 31, 3, 1),
        ("SINOP", "dengue", 2026, 32, 2, 0),
    ])
    f = build_panel_features(w, ref=(2026, 33))
    cba = f[f.municipio == "CUIABA"].sort_values("epi_week")
    assert cba["epi_week"].tolist() == [30, 31, 32, 33]
    assert cba["tests"].tolist() == [10, 0, 0, 4]
    # lag1 = semana de calendário anterior, não a última semana com exame
    assert cba["tests_lag1"].tolist()[1:] == [10, 0, 0]
    assert cba["semanas_consec_sem_exame"].tolist() == [0, 1, 2, 0]
    sin = f[f.municipio == "SINOP"].sort_values("epi_week")
    assert sin["epi_week"].tolist() == [31, 32, 33]  # começa na 1ª observação do par
    assert sin["tests"].tolist() == [3, 2, 0]


def test_snapshot_so_tem_a_se_de_referencia():
    w = _weekly([
        ("CUIABA", "dengue", 2025, 10, 5, 1),  # par parado há muito tempo
        ("SINOP", "dengue", 2026, 33, 3, 1),
    ])
    f = build_panel_features(w, ref=(2026, 33))
    snap = latest_week_snapshot(f)
    assert set(zip(snap.epi_year, snap.epi_week)) == {(2026, 33)}
    assert set(snap.municipio) == {"CUIABA", "SINOP"}
    assert snap.loc[snap.municipio == "CUIABA", "tests"].iloc[0] == 0


def test_semana_em_curso_nao_vira_referencia():
    w = _weekly([
        ("CUIABA", "dengue", 2026, 35, 10, 1),
        ("CUIABA", "dengue", 2026, 36, 4, 0),  # SE36 ainda em curso em 11/09/2026
    ])
    assert reference_week(w, hoje=pd.Timestamp("2026-09-11").date()) == (2026, 35)
    f = build_panel_features(w, ref=(2026, 35))
    assert f["epi_week"].max() == 35


def test_reference_week_pode_ser_forcada(monkeypatch):
    monkeypatch.setenv("LACEN_SE_REFERENCIA", "2026-SE30")
    assert reference_week(_weekly([("CUIABA", "dengue", 2026, 35, 1, 0)])) == (2026, 30)


def test_rotulos_ignoram_linhas_sem_semana_seguinte():
    w = _weekly([
        ("CUIABA", "dengue", 2026, 31, 10, 2),
        ("CUIABA", "dengue", 2026, 32, 0, 0),
        ("CUIABA", "dengue", 2026, 33, 5, 1),
    ]).assign(notificacoes=0, risco_composto=0.0)
    lab = _make_labels(build_panel_features(w, ref=(2026, 33)).assign(vizinhos_em_alerta=0))
    assert lab["epi_week"].tolist() == [31, 32]
    assert lab["y_silencio"].tolist() == [1, 0]


def test_filtro_mt_e_apostrofo_duplicado():
    w = _weekly([
        ("MIRASSOL D''OESTE", "dengue", 2026, 33, 6, 1),
        ("JOINVILLE", "dengue", 2026, 33, 9, 1),
    ])
    f = build_panel_features(w, ref=(2026, 33))
    assert f["municipio"].tolist() == ["MIRASSOL D'OESTE"]
    assert canon_municipio(pd.Series(["Mirassol d'Oeste"])).iloc[0] == "MIRASSOL D'OESTE"


def test_densify_vazio():
    assert densify_panel(pd.DataFrame(), (2026, 1)).empty
