# -*- coding: utf-8 -*-
"""Análise de sensibilidade da âncora temporal GAL — solicitação × coleta."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class TemporalAnchorSummary:
    rows_total: int
    rows_both_dates: int
    coverage_solicitacao: float
    coverage_coleta: float
    median_delay_days: float | None
    p90_delay_days: float | None
    changed_epi_week_rows: int
    changed_epi_week_pct: float
    changed_epi_year_rows: int
    changed_epi_year_pct: float
    weeks_compared: int
    weeks_with_count_delta: int
    weeks_with_count_delta_pct: float
    max_absolute_weekly_count_diff: int
    sum_absolute_weekly_count_diff: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pick_col(columns, candidates):
    lower = {str(c).lower(): str(c) for c in columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def build_weekly_anchor_comparison(paired: pd.DataFrame) -> pd.DataFrame:
    """Compara contagens semanais usando solicitação versus coleta."""
    if paired is None or paired.empty:
        return pd.DataFrame(columns=[
            "epi_year", "epi_week", "n_solicitacao", "n_coleta",
            "diff_coleta_minus_solicitacao", "abs_diff",
        ])

    sol = (
        paired.groupby(["sol_epi_year", "sol_epi_week"], dropna=False)
        .size()
        .rename("n_solicitacao")
        .reset_index()
        .rename(columns={"sol_epi_year": "epi_year", "sol_epi_week": "epi_week"})
    )
    col = (
        paired.groupby(["coleta_epi_year", "coleta_epi_week"], dropna=False)
        .size()
        .rename("n_coleta")
        .reset_index()
        .rename(columns={"coleta_epi_year": "epi_year", "coleta_epi_week": "epi_week"})
    )
    out = sol.merge(col, on=["epi_year", "epi_week"], how="outer")
    out["n_solicitacao"] = out["n_solicitacao"].fillna(0).astype(int)
    out["n_coleta"] = out["n_coleta"].fillna(0).astype(int)
    out["diff_coleta_minus_solicitacao"] = out["n_coleta"] - out["n_solicitacao"]
    out["abs_diff"] = out["diff_coleta_minus_solicitacao"].abs()
    return out.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)


def analyze_temporal_anchor(df: pd.DataFrame) -> tuple[pd.DataFrame, TemporalAnchorSummary]:
    if df is None or df.empty:
        summary = TemporalAnchorSummary(
            rows_total=0,
            rows_both_dates=0,
            coverage_solicitacao=0.0,
            coverage_coleta=0.0,
            median_delay_days=None,
            p90_delay_days=None,
            changed_epi_week_rows=0,
            changed_epi_week_pct=0.0,
            changed_epi_year_rows=0,
            changed_epi_year_pct=0.0,
            weeks_compared=0,
            weeks_with_count_delta=0,
            weeks_with_count_delta_pct=0.0,
            max_absolute_weekly_count_diff=0,
            sum_absolute_weekly_count_diff=0,
        )
        return pd.DataFrame(), summary

    d = df.copy()
    sol_col = _pick_col(
        d.columns,
        (
            "Data_Solicitacao_dt",
            "Data_Solicitacao",
            "data_solicitacao",
            "dt_solicitacao",
        ),
    )
    col_col = _pick_col(
        d.columns,
        (
            "Data_Coleta_dt",
            "Data_Coleta",
            "data_coleta",
            "dt_coleta",
        ),
    )
    if sol_col is None or col_col is None:
        raise ValueError("A base precisa conter data de solicitação e data de coleta.")

    d["dt_solicitacao"] = pd.to_datetime(d[sol_col], errors="coerce")
    d["dt_coleta"] = pd.to_datetime(d[col_col], errors="coerce")

    total = len(d)
    cov_sol = float(d["dt_solicitacao"].notna().mean()) if total else 0.0
    cov_col = float(d["dt_coleta"].notna().mean()) if total else 0.0

    paired = d.dropna(subset=["dt_solicitacao", "dt_coleta"]).copy()
    if paired.empty:
        summary = TemporalAnchorSummary(
            rows_total=total,
            rows_both_dates=0,
            coverage_solicitacao=cov_sol,
            coverage_coleta=cov_col,
            median_delay_days=None,
            p90_delay_days=None,
            changed_epi_week_rows=0,
            changed_epi_week_pct=0.0,
            changed_epi_year_rows=0,
            changed_epi_year_pct=0.0,
            weeks_compared=0,
            weeks_with_count_delta=0,
            weeks_with_count_delta_pct=0.0,
            max_absolute_weekly_count_diff=0,
            sum_absolute_weekly_count_diff=0,
        )
        return paired, summary

    paired["delay_days"] = (
        paired["dt_solicitacao"].dt.normalize() - paired["dt_coleta"].dt.normalize()
    ).dt.days

    sol_iso = paired["dt_solicitacao"].dt.isocalendar()
    col_iso = paired["dt_coleta"].dt.isocalendar()
    paired["sol_epi_year"] = sol_iso["year"].astype("Int64")
    paired["sol_epi_week"] = sol_iso["week"].astype("Int64")
    paired["coleta_epi_year"] = col_iso["year"].astype("Int64")
    paired["coleta_epi_week"] = col_iso["week"].astype("Int64")

    changed_week = (
        (paired["sol_epi_year"] != paired["coleta_epi_year"])
        | (paired["sol_epi_week"] != paired["coleta_epi_week"])
    )
    changed_year = paired["sol_epi_year"] != paired["coleta_epi_year"]

    median = paired["delay_days"].median()
    p90 = paired["delay_days"].quantile(0.90)

    weekly_comparison = build_weekly_anchor_comparison(paired)
    weeks_compared = int(len(weekly_comparison))
    weeks_with_delta = int((weekly_comparison["abs_diff"] > 0).sum()) if weeks_compared else 0
    max_abs_diff = int(weekly_comparison["abs_diff"].max()) if weeks_compared else 0
    sum_abs_diff = int(weekly_comparison["abs_diff"].sum()) if weeks_compared else 0

    summary = TemporalAnchorSummary(
        rows_total=total,
        rows_both_dates=int(len(paired)),
        coverage_solicitacao=cov_sol,
        coverage_coleta=cov_col,
        median_delay_days=None if pd.isna(median) else float(median),
        p90_delay_days=None if pd.isna(p90) else float(p90),
        changed_epi_week_rows=int(changed_week.sum()),
        changed_epi_week_pct=float(changed_week.mean()),
        changed_epi_year_rows=int(changed_year.sum()),
        changed_epi_year_pct=float(changed_year.mean()),
        weeks_compared=weeks_compared,
        weeks_with_count_delta=weeks_with_delta,
        weeks_with_count_delta_pct=(float(weeks_with_delta / weeks_compared) if weeks_compared else 0.0),
        max_absolute_weekly_count_diff=max_abs_diff,
        sum_absolute_weekly_count_diff=sum_abs_diff,
    )
    return paired, summary


def write_temporal_anchor_analysis(
    detail: pd.DataFrame,
    summary: TemporalAnchorSummary,
    outdir: Path | str,
) -> dict[str, Path]:
    import json

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    detail_path = out / "gal_temporal_anchor_detail.csv"
    weekly_path = out / "gal_temporal_anchor_weekly_comparison.csv"
    summary_path = out / "gal_temporal_anchor_summary.json"
    txt_path = out / "gal_temporal_anchor_summary.txt"

    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    build_weekly_anchor_comparison(detail).to_csv(
        weekly_path, index=False, encoding="utf-8-sig"
    )
    summary_path.write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join([
            "LACEN-MT V2 — ANÁLISE ÂNCORA TEMPORAL GAL",
            f"rows_total: {summary.rows_total}",
            f"rows_both_dates: {summary.rows_both_dates}",
            f"coverage_solicitacao: {summary.coverage_solicitacao:.4f}",
            f"coverage_coleta: {summary.coverage_coleta:.4f}",
            f"median_delay_days: {summary.median_delay_days}",
            f"p90_delay_days: {summary.p90_delay_days}",
            f"changed_epi_week_rows: {summary.changed_epi_week_rows}",
            f"changed_epi_week_pct: {summary.changed_epi_week_pct:.4f}",
            f"changed_epi_year_rows: {summary.changed_epi_year_rows}",
            f"changed_epi_year_pct: {summary.changed_epi_year_pct:.4f}",
            f"weeks_compared: {summary.weeks_compared}",
            f"weeks_with_count_delta: {summary.weeks_with_count_delta}",
            f"weeks_with_count_delta_pct: {summary.weeks_with_count_delta_pct:.4f}",
            f"max_absolute_weekly_count_diff: {summary.max_absolute_weekly_count_diff}",
            f"sum_absolute_weekly_count_diff: {summary.sum_absolute_weekly_count_diff}",
            "decision: PENDING",
        ]) + "\n",
        encoding="utf-8",
    )
    return {
        "detail_csv": detail_path,
        "weekly_comparison_csv": weekly_path,
        "summary_json": summary_path,
        "summary_txt": txt_path,
    }
