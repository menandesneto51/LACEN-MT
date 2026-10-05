# -*- coding: utf-8 -*-
"""Comparação auditável entre fontes populacionais — LACEN-MT V2.1."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import combinations
from pathlib import Path
from typing import Any
import json

import pandas as pd


@dataclass
class PopulationSourceComparisonSummary:
    analysis_year: int
    sources: list[str]
    territories_total: int
    territories_with_multiple_sources: int
    territories_with_any_difference: int
    max_absolute_difference: float | None
    max_relative_difference: float | None
    source_coverage: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _territory_key(df: pd.DataFrame) -> pd.Series:
    code = df["municipio_ibge"].astype("string")
    name = df["municipio"].astype("string").str.strip().str.upper()
    return code.where(code.notna(), "NAME:" + name)


def compare_population_sources(
    dim: pd.DataFrame,
    *,
    analysis_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame, PopulationSourceComparisonSummary]:
    if dim is None or dim.empty:
        empty = pd.DataFrame()
        summary = PopulationSourceComparisonSummary(
            analysis_year=analysis_year,
            sources=[],
            territories_total=0,
            territories_with_multiple_sources=0,
            territories_with_any_difference=0,
            max_absolute_difference=None,
            max_relative_difference=None,
            source_coverage={},
        )
        return empty, empty, summary

    d = dim.copy()
    d["ano_referencia"] = pd.to_numeric(d["ano_referencia"], errors="coerce").astype("Int64")
    d["populacao"] = pd.to_numeric(d["populacao"], errors="coerce")
    d = d[d["ano_referencia"] == int(analysis_year)].copy()
    if d.empty:
        return compare_population_sources(pd.DataFrame(), analysis_year=analysis_year)

    d["territory_key"] = _territory_key(d)
    d = d[d["territory_key"].notna() & d["populacao"].notna()].copy()

    # Conflito dentro da mesma fonte/território é preservado no detalhe.
    source_values = (
        d.groupby(["territory_key", "fonte"], dropna=False)["populacao"]
        .agg(["nunique", "min", "max", "first"])
        .reset_index()
        .rename(columns={
            "nunique": "n_values",
            "min": "population_min",
            "max": "population_max",
            "first": "population_value",
        })
    )
    source_values["internal_conflict"] = source_values["n_values"] > 1

    sources = sorted(source_values["fonte"].dropna().astype(str).unique().tolist())
    coverage = {
        src: int(source_values.loc[source_values["fonte"] == src, "territory_key"].nunique())
        for src in sources
    }

    pair_rows: list[dict[str, Any]] = []
    by_source = {
        src: source_values[
            (source_values["fonte"] == src) & ~source_values["internal_conflict"]
        ].set_index("territory_key")["population_value"]
        for src in sources
    }
    for a, b in combinations(sources, 2):
        common = by_source[a].index.intersection(by_source[b].index)
        for key in common:
            va = float(by_source[a].loc[key])
            vb = float(by_source[b].loc[key])
            abs_diff = abs(vb - va)
            base = abs(va)
            rel_diff = abs_diff / base if base > 0 else None
            pair_rows.append({
                "territory_key": key,
                "source_a": a,
                "source_b": b,
                "population_a": va,
                "population_b": vb,
                "absolute_difference": abs_diff,
                "relative_difference": rel_diff,
                "same_value": abs_diff == 0,
            })

    pairs = pd.DataFrame(pair_rows)
    territory_source_counts = source_values.groupby("territory_key")["fonte"].nunique()
    multi = int((territory_source_counts > 1).sum())
    any_diff = (
        int(pairs.loc[~pairs["same_value"], "territory_key"].nunique())
        if not pairs.empty else 0
    )
    max_abs = (
        float(pairs["absolute_difference"].max())
        if not pairs.empty else None
    )
    max_rel = (
        float(pairs["relative_difference"].dropna().max())
        if not pairs.empty and pairs["relative_difference"].notna().any()
        else None
    )
    summary = PopulationSourceComparisonSummary(
        analysis_year=int(analysis_year),
        sources=sources,
        territories_total=int(source_values["territory_key"].nunique()),
        territories_with_multiple_sources=multi,
        territories_with_any_difference=any_diff,
        max_absolute_difference=max_abs,
        max_relative_difference=max_rel,
        source_coverage=coverage,
    )
    return source_values, pairs, summary


def write_population_source_comparison(
    source_detail: pd.DataFrame,
    pair_detail: pd.DataFrame,
    summary: PopulationSourceComparisonSummary,
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    source_path = out / "population_source_coverage_detail.csv"
    pair_path = out / "population_source_pairwise_comparison.csv"
    json_path = out / "population_source_comparison_summary.json"
    txt_path = out / "population_source_comparison_summary.txt"

    source_detail.to_csv(source_path, index=False, encoding="utf-8-sig")
    pair_detail.to_csv(pair_path, index=False, encoding="utf-8-sig")
    json_path.write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2.1 — COMPARAÇÃO DE FONTES POPULACIONAIS",
        f"analysis_year: {summary.analysis_year}",
        f"sources: {', '.join(summary.sources) or '—'}",
        f"territories_total: {summary.territories_total}",
        f"territories_with_multiple_sources: {summary.territories_with_multiple_sources}",
        f"territories_with_any_difference: {summary.territories_with_any_difference}",
        f"max_absolute_difference: {summary.max_absolute_difference}",
        f"max_relative_difference: {summary.max_relative_difference}",
        "source_coverage:",
        *[f"- {k}: {v}" for k, v in summary.source_coverage.items()],
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "source_detail_csv": source_path,
        "pair_detail_csv": pair_path,
        "summary_json": json_path,
        "summary_txt": txt_path,
    }
