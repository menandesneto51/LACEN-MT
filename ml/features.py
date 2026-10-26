# -*- coding: utf-8 -*-
"""Feature store leve a partir de integrated_weekly_surveillance."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from etl.epi_week import semana_completa_mais_recente

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


# Contagens semanais: semana sem registro = 0 (não "dado ausente").
COUNT_METRICS = ("tests", "positives", "notificacoes", "obitos_sim", "n_eventos_climaticos")
# Taxas derivadas de contagens: semana sem registro = 0.
RATE_METRICS_ZERO = ("incidencia_100k", "solicitacoes_100k")
# Contexto estrutural/climático: repete o último valor conhecido do par município×alvo.
CONTEXT_FFILL = (
    "populacao",
    "indice_vulnerabilidade",
    "precipitation_sum_mm",
    "temperature_2m_max",
    "relative_humidity_2m_min",
    "cnes_estabelecimentos",
    "cnes_leitos_total",
    "cnes_equipes_esf",
)


GEO_MT = Path(__file__).resolve().parents[1] / "geo" / "mt_municipios.geojson"


def canon_municipio(s: pd.Series) -> pd.Series:
    """Nome em maiúsculas sem acento; corrige apóstrofo duplicado (D''OESTE)."""
    import unicodedata

    def _one(x: object) -> str:
        t = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode()
        return " ".join(t.upper().replace("''", "'").split())

    return s.map(_one)


def municipios_mt() -> set[str]:
    """141 municípios de MT (malha em geo/). Vazio se a malha não existir."""
    import json

    try:
        feats = json.loads(GEO_MT.read_text(encoding="utf-8"))["features"]
    except Exception:
        return set()
    return set(canon_municipio(pd.Series([f["properties"].get("name", "") for f in feats])))


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
        df["municipio"] = df["municipio"].astype(str).str.strip().str.upper().str.replace("''", "'", regex=False)
        # Alertas municipais são para MT: o GAL inclui residentes de outros
        # estados (≈2 mil municípios) que inflavam o painel e as listas.
        mt = municipios_mt() if os.getenv("LACEN_ML_SOMENTE_MT", "1") != "0" else set()
        if mt:
            df = df[canon_municipio(df["municipio"]).isin(mt)]
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


def _parse_se_env(value: str | None) -> Optional[tuple[int, int]]:
    import re

    m = re.search(r"(20\d{2})\s*[-_/]?\s*SE\s*(\d{1,2})", str(value or ""), re.I)
    return (int(m.group(1)), int(m.group(2))) if m else None


def reference_week(df: pd.DataFrame, hoje=None) -> Optional[tuple[int, int]]:
    """SE de referência = última SE presente nos dados que já esteja encerrada.

    Semanas posteriores à última SE completa do calendário (semana em curso)
    nunca viram referência. `LACEN_SE_REFERENCIA=2026-SE36` força um valor.
    """
    forced = _parse_se_env(os.getenv("LACEN_SE_REFERENCIA"))
    if forced:
        return forced
    if df is None or df.empty:
        return None
    weeks = df[["epi_year", "epi_week"]].dropna().drop_duplicates()
    if weeks.empty:
        return None
    ordv = weeks["epi_year"].astype(int) * 100 + weeks["epi_week"].astype(int)
    lim_y, lim_w = semana_completa_mais_recente(hoje)
    ok = ordv[ordv <= lim_y * 100 + lim_w]
    best = int(ok.max() if not ok.empty else ordv.min())
    return best // 100, best % 100


def densify_panel(panel: pd.DataFrame, ref: tuple[int, int]) -> pd.DataFrame:
    """Uma linha por município×alvo×SE, da 1ª observação do par até `ref`.

    Sem isso, lags e médias móveis são calculados sobre as últimas semanas
    *com exame* (não sobre semanas de calendário) e o silêncio fica invisível.
    """
    if panel.empty:
        return panel
    keys = ["municipio", "target"]
    ref_ord = int(ref[0]) * 100 + int(ref[1])
    panel = panel.copy()
    panel["_ord"] = panel["epi_year"].astype(int) * 100 + panel["epi_week"].astype(int)
    panel = panel[panel["_ord"] <= ref_ord]
    cal = sorted(set(panel["_ord"].tolist()) | {ref_ord})
    pos = {o: i for i, o in enumerate(cal)}
    panel["_i"] = panel["_ord"].map(pos).astype(int)

    first = panel.groupby(keys, sort=False)["_i"].min().reset_index()
    n = (len(cal) - first["_i"]).to_numpy()
    grid = first.loc[first.index.repeat(n), keys].reset_index(drop=True)
    starts = np.repeat(first["_i"].to_numpy(), n)
    offs = np.arange(len(grid)) - np.repeat(np.cumsum(n) - n, n)
    grid["_i"] = starts + offs
    cal_arr = np.asarray(cal)
    grid["epi_year"] = cal_arr[grid["_i"]] // 100
    grid["epi_week"] = cal_arr[grid["_i"]] % 100

    out = grid.merge(panel.drop(columns=["epi_year", "epi_week", "_ord"]), on=keys + ["_i"], how="left")
    out = out.sort_values(keys + ["_i"]).reset_index(drop=True)
    g = out.groupby(keys, sort=False)
    for c in COUNT_METRICS + RATE_METRICS_ZERO:
        if c in out.columns:
            out[c] = out[c].fillna(0.0)
    for c in CONTEXT_FFILL:
        if c in out.columns:
            out[c] = g[c].ffill()
    if {"positives", "tests"}.issubset(out.columns):
        out["positividade"] = np.where(out["tests"] > 0, out["positives"] / out["tests"], np.nan)
    if "risco_composto" in out.columns:
        out["risco_composto"] = out["risco_composto"].fillna(0.0)
    return out.drop(columns=["_i"])


def build_panel_features(
    weekly: pd.DataFrame,
    windows: Iterable[int] = (4, 8),
    outdir: Optional[Path | str] = None,
    ref: Optional[tuple[int, int]] = None,
) -> pd.DataFrame:
    """Agrega por município-alvo-SE (painel denso até a SE de referência) e cria
    lags / médias móveis / tendência sobre semanas de calendário."""
    df = prepare_weekly(weekly)
    ref = ref or reference_week(df)
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

    if ref is not None:
        panel = densify_panel(panel, ref)

    gcols = ["municipio", "target"]
    for m in metrics:
        grp = panel.groupby(gcols, sort=False)[m]
        panel[f"{m}_lag1"] = grp.shift(1)
        for w in windows:
            panel[f"{m}_ma{w}"] = (
                grp.rolling(w, min_periods=max(2, w // 2)).mean().reset_index(level=[0, 1], drop=True)
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
        # semanas consecutivas sem exame até a SE da linha (zera a cada semana com exame)
        zero = (panel["tests"].fillna(0) <= 0).astype(int)
        bloco = (zero == 0).groupby([panel["municipio"], panel["target"]]).cumsum()
        panel["semanas_consec_sem_exame"] = zero.groupby(
            [panel["municipio"], panel["target"], bloco]
        ).cumsum()

        # Série ativa: ≥ 2 exames nas últimas 8 SE. Silêncio só faz sentido aqui;
        # pares parados há meses não são "silêncio" novo, são séries inativas.
        panel["serie_ativa"] = (panel.get("tests_ma8", pd.Series(0.0, index=panel.index)).fillna(0) >= 0.25).astype(int)

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


def latest_week_snapshot(features: pd.DataFrame, ref: Optional[tuple[int, int]] = None) -> pd.DataFrame:
    """Todos os pares município×alvo **na SE de referência** (painel denso).

    Antes usava a última linha com dado de cada par, o que misturava semanas
    de 2024/2025 com a SE atual nos alertas.
    """
    if features.empty:
        return features
    if ref is None:
        ordv = features["epi_year"].astype(int) * 100 + features["epi_week"].astype(int)
        top = int(ordv.max())
        ref = (top // 100, top % 100)
    mask = (features["epi_year"].astype(int) == int(ref[0])) & (features["epi_week"].astype(int) == int(ref[1]))
    return features.loc[mask].copy()
