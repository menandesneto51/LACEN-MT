# -*- coding: utf-8 -*-
"""Feature store leve a partir de integrated_weekly_surveillance."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

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
    # clima / capacidade (quando presentes no weekly)
    "precipitation_sum_mm",
    "temperature_2m_max",
    "relative_humidity_2m_min",
    "n_eventos_climaticos",
    "cnes_estabelecimentos",
    "cnes_leitos_total",
    "cnes_equipes_esf",
)


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def prepare_weekly(weekly: pd.DataFrame, max_weeks: int = 104) -> pd.DataFrame:
    df = weekly.copy()
    for c in (
        "epi_year", "epi_week", "tests", "positives", "notificacoes", "obitos_sim",
        "positividade", "incidencia_100k", "risco_composto", "indice_vulnerabilidade",
        "solicitacoes_100k", "populacao",
        "precipitation_sum_mm", "temperature_2m_max", "relative_humidity_2m_min",
        "n_eventos_climaticos", "cnes_estabelecimentos", "cnes_leitos_total", "cnes_equipes_esf",
    ):
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


def _merge_context(panel: pd.DataFrame, outdir: Optional[Path]) -> pd.DataFrame:
    """Anexa vizinhos em alerta e confiança do dado (contexto territorial)."""
    if outdir is None:
        return panel
    outdir = Path(outdir)
    panel = panel.copy()
    panel["municipio"] = panel["municipio"].astype(str).str.strip().str.upper()

    sil_path = outdir / "municipios_silenciosos.csv"
    if sil_path.exists():
        try:
            sil = pd.read_csv(sil_path, low_memory=False)
            sil["municipio"] = sil["municipio"].astype(str).str.strip().str.upper()
            cols = [c for c in ("municipio", "vizinhos_em_alerta", "silencio_com_vizinho_alerta") if c in sil.columns]
            if len(cols) > 1:
                agg = sil[cols].groupby("municipio", as_index=False).max(numeric_only=False)
                panel = panel.merge(agg, on="municipio", how="left")
        except Exception:
            pass
    if "vizinhos_em_alerta" not in panel.columns:
        panel["vizinhos_em_alerta"] = 0
    if "silencio_com_vizinho_alerta" not in panel.columns:
        panel["silencio_com_vizinho_alerta"] = 0
    panel["vizinhos_em_alerta"] = pd.to_numeric(panel["vizinhos_em_alerta"], errors="coerce").fillna(0)
    panel["silencio_com_vizinho_alerta"] = (
        panel["silencio_com_vizinho_alerta"].fillna(False).astype(int)
    )

    qual_path = outdir / "qualidade_dado_municipal.csv"
    if qual_path.exists():
        try:
            q = pd.read_csv(qual_path, low_memory=False)
            q["municipio"] = q["municipio"].astype(str).str.strip().str.upper()
            keep = [c for c in ("municipio", "confianca_dado", "gap_sinan_sem_exame") if c in q.columns]
            if len(keep) > 1:
                panel = panel.merge(q[keep], on="municipio", how="left")
        except Exception:
            pass
    if "confianca_dado" not in panel.columns:
        panel["confianca_dado"] = 0.5
    if "gap_sinan_sem_exame" not in panel.columns:
        panel["gap_sinan_sem_exame"] = 0
    panel["confianca_dado"] = pd.to_numeric(panel["confianca_dado"], errors="coerce").fillna(0.5)
    panel["gap_sinan_sem_exame"] = panel["gap_sinan_sem_exame"].fillna(False).astype(int)
    return panel


def build_panel_features(
    weekly: pd.DataFrame,
    windows: Iterable[int] = (4, 8),
    outdir: Optional[Path | str] = None,
) -> pd.DataFrame:
    """Agrega por município-alvo-semana e cria lags / médias móveis / tendência."""
    df = prepare_weekly(weekly)
    metrics = [m for m in FEATURE_METRICS if m in df.columns]
    sum_cols = {"tests", "positives", "notificacoes", "obitos_sim", "n_eventos_climaticos"}
    agg = {m: "sum" if m in sum_cols else "mean" for m in metrics}
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
        if f"{m}_ma4" in panel.columns and f"{m}_ma8" in panel.columns:
            panel[f"{m}_trend"] = panel[f"{m}_ma4"] - panel[f"{m}_ma8"]

    if "tests" in panel.columns:
        panel["semanas_sem_exame"] = np.where(panel["tests"].fillna(0) > 0, 0.0, 1.0)
        if "tests_ma8" in panel.columns:
            panel["semanas_sem_exame"] = np.where(
                panel["tests_ma8"].fillna(0) < 0.5,
                panel["semanas_sem_exame"] + 4.0,
                panel["semanas_sem_exame"],
            )
        # atraso relativo: quantas semanas consecutivas sem exame (proxy)
        zero = (panel["tests"].fillna(0) <= 0).astype(int)
        panel["semanas_consec_sem_exame"] = zero.groupby(
            [panel["municipio"], panel["target"]]
        ).cumsum() * zero

    if "notificacoes" in panel.columns and "tests" in panel.columns:
        panel["exames_por_notif"] = np.where(
            panel["notificacoes"].fillna(0) > 0,
            panel["tests"] / panel["notificacoes"].replace(0, np.nan),
            np.nan,
        )

    # Percentil estadual de testes na semana (contexto relativo)
    if "tests" in panel.columns:
        panel["tests_pct_estadual"] = panel.groupby(["epi_year", "epi_week"])["tests"].rank(pct=True)

    panel = _merge_context(panel, Path(outdir) if outdir else None)
    panel["modelo_versao"] = "features_v2"
    return panel


def latest_week_snapshot(features: pd.DataFrame) -> pd.DataFrame:
    """Última observação disponível por município-alvo (dados laboratoriais são esparsos)."""
    if features.empty:
        return features
    idx = features.groupby(["municipio", "target"], sort=False).tail(1).index
    return features.loc[idx].copy()
