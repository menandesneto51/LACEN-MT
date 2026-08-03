# -*- coding: utf-8 -*-
"""Feature store leve a partir de integrated_weekly_surveillance."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

FEATURE_METRICS = (
    "tests",
    "positives",
    "positividade",
    "notificacoes",
    "obitos_sim",
    "incidencia_100k",
    "risco_composto",
    "indice_vulnerabilidade",
    "solicitacoes_100k",
)


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def prepare_weekly(weekly: pd.DataFrame, max_weeks: int = 104) -> pd.DataFrame:
    df = weekly.copy()
    for c in ("epi_year", "epi_week", "tests", "positives", "notificacoes", "obitos_sim",
              "positividade", "incidencia_100k", "risco_composto", "indice_vulnerabilidade",
              "solicitacoes_100k", "populacao"):
        if c in df.columns:
            df[c] = _to_num(df[c])
    if "positividade" not in df.columns and {"positives", "tests"}.issubset(df.columns):
        df["positividade"] = np.where(df["tests"] > 0, df["positives"] / df["tests"], np.nan)
    if "municipio" in df.columns:
        df["municipio"] = df["municipio"].astype(str).str.strip().str.upper()
    if "target" in df.columns:
        df["target"] = df["target"].astype(str).str.strip()
    df = df.dropna(subset=["epi_year", "epi_week", "municipio", "target"], how="any")
    df["epi_year"] = df["epi_year"].astype(int)
    df["epi_week"] = df["epi_week"].astype(int)
    # Janela recente para acelerar feature engineering
    weeks = (
        df[["epi_year", "epi_week"]]
        .drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
    )
    if len(weeks) > max_weeks:
        keep = weeks.tail(max_weeks)
        df = df.merge(keep, on=["epi_year", "epi_week"], how="inner")
    df = df.sort_values(["municipio", "target", "epi_year", "epi_week"]).reset_index(drop=True)
    return df


def build_panel_features(weekly: pd.DataFrame, windows: Iterable[int] = (4, 8)) -> pd.DataFrame:
    """Agrega por município-alvo-semana e cria lags / médias móveis / tendência."""
    df = prepare_weekly(weekly)
    metrics = [m for m in FEATURE_METRICS if m in df.columns]
    agg = {m: "sum" if m in {"tests", "positives", "notificacoes", "obitos_sim"} else "mean" for m in metrics}
    if "populacao" in df.columns:
        agg["populacao"] = "max"

    panel = (
        df.groupby(["municipio", "target", "epi_year", "epi_week"], as_index=False)
        .agg(agg)
        .sort_values(["municipio", "target", "epi_year", "epi_week"])
        .reset_index(drop=True)
    )

    gcols = ["municipio", "target"]
    for m in metrics:
        panel[f"{m}_lag1"] = panel.groupby(gcols)[m].shift(1)
        for w in windows:
            panel[f"{m}_ma{w}"] = panel.groupby(gcols)[m].transform(
                lambda s, ww=w: s.rolling(ww, min_periods=max(2, ww // 2)).mean()
            )
        # tendência: diferença entre média recente (4) e baseline (8)
        if f"{m}_ma4" in panel.columns and f"{m}_ma8" in panel.columns:
            panel[f"{m}_trend"] = panel[f"{m}_ma4"] - panel[f"{m}_ma8"]

    # Semanas desde o último exame observado nesta linha (0 se houve exame)
    if "tests" in panel.columns:
        panel["semanas_sem_exame"] = np.where(
            panel["tests"].fillna(0) > 0,
            0.0,
            1.0,
        )
        # Se ma8 de testes é baixa, reforça sinal de baixa atividade
        if "tests_ma8" in panel.columns:
            panel["semanas_sem_exame"] = np.where(
                panel["tests_ma8"].fillna(0) < 0.5,
                panel["semanas_sem_exame"] + 4.0,
                panel["semanas_sem_exame"],
            )

    panel["modelo_versao"] = "baseline_v1"
    return panel


def latest_week_snapshot(features: pd.DataFrame) -> pd.DataFrame:
    """Última observação disponível por município-alvo (dados laboratoriais são esparsos)."""
    if features.empty:
        return features
    # índice da última linha em cada grupo já ordenado
    idx = features.groupby(["municipio", "target"], sort=False).tail(1).index
    return features.loc[idx].copy()
