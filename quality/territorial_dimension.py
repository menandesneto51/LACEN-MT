# -*- coding: utf-8 -*-
"""Dimensão territorial e população versionada — LACEN-MT V2.1.

Este módulo não escolhe silenciosamente uma fonte populacional "oficial".
Ele normaliza fontes disponíveis do staging e preserva origem, ano e versão
para que produtos dependentes de taxa possam declarar explicitamente o
denominador utilizado.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


IBGE_CODE_CANDIDATES = (
    "municipio_ibge",
    "codigo_ibge",
    "cod_ibge",
    "ibge",
    "codigo_municipio",
    "cod_municipio",
    "co_municipio",
    "co_municipio_ibge",
)
MUNICIPIO_CANDIDATES = (
    "municipio",
    "nome_municipio",
    "municipio_nome",
    "nm_municipio",
    "municipio_residencia",
)
YEAR_CANDIDATES = (
    "ano",
    "year",
    "ano_referencia",
    "ano_populacao",
    "nu_ano",
)
POP_CANDIDATES = (
    "populacao",
    "population",
    "pop",
    "populacao_total",
    "qt_populacao",
    "nu_populacao",
)

STAGING_POPULATION_STEMS = (
    "vw_populacao",
    "populacao",
    "populacao_total",
    "populacao_tcu",
)


@dataclass(frozen=True)
class PopulationSource:
    stem: str
    source_name: str


def _pick(columns: Iterable[str], candidates: tuple[str, ...]) -> str | None:
    by_lower = {str(c).strip().lower(): str(c) for c in columns}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def normalize_ibge_code(series: pd.Series) -> pd.Series:
    out = series.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    return out.where(out.str.fullmatch(r"\d{7}", na=False))


def normalize_population_source(
    df: pd.DataFrame,
    *,
    source_name: str,
    extracted_at: str | None = None,
    source_version: str | None = None,
) -> pd.DataFrame:
    """Normaliza uma fonte sem inventar código IBGE, ano ou população."""
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "municipio_ibge", "municipio", "ano_referencia", "populacao",
                "fonte", "versao_fonte", "extraido_em", "is_fallback",
            ]
        )

    code_col = _pick(df.columns, IBGE_CODE_CANDIDATES)
    mun_col = _pick(df.columns, MUNICIPIO_CANDIDATES)
    year_col = _pick(df.columns, YEAR_CANDIDATES)
    pop_col = _pick(df.columns, POP_CANDIDATES)

    out = pd.DataFrame(index=df.index)
    out["municipio_ibge"] = normalize_ibge_code(df[code_col]) if code_col else pd.NA
    out["municipio"] = (
        df[mun_col].astype("string").str.strip() if mun_col else pd.Series(pd.NA, index=df.index, dtype="string")
    )
    out["ano_referencia"] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64") if year_col else pd.Series(pd.NA, index=df.index, dtype="Int64")
    out["populacao"] = pd.to_numeric(df[pop_col], errors="coerce") if pop_col else pd.Series(float("nan"), index=df.index)
    out["fonte"] = source_name
    out["versao_fonte"] = source_version or "staging"
    out["extraido_em"] = extracted_at or datetime.now().isoformat(timespec="seconds")
    out["is_fallback"] = False

    # Mantém apenas linhas potencialmente identificáveis; qualidade é tratada no gate.
    keep = out["municipio_ibge"].notna() | out["municipio"].notna() | out["populacao"].notna()
    return out.loc[keep].reset_index(drop=True)


def _read_staging_file(stage: Path, stem: str) -> pd.DataFrame | None:
    pq = stage / f"{stem}.parquet"
    csv = stage / f"{stem}.csv"
    try:
        if pq.exists():
            return pd.read_parquet(pq)
        if csv.exists():
            return pd.read_csv(csv, low_memory=False)
    except Exception:
        return None
    return None


def build_population_dimension_from_staging(
    stage: Path | str,
    *,
    extracted_at: str | None = None,
) -> pd.DataFrame:
    """Concatena fontes disponíveis sem selecionar uma fonte vencedora."""
    stage = Path(stage)
    frames: list[pd.DataFrame] = []
    for stem in STAGING_POPULATION_STEMS:
        df = _read_staging_file(stage, stem)
        if df is None or df.empty:
            continue
        norm = normalize_population_source(
            df,
            source_name=f"DW:{stem.upper()}",
            extracted_at=extracted_at,
            source_version=stem,
        )
        if not norm.empty:
            frames.append(norm)
    if not frames:
        return pd.DataFrame(
            columns=[
                "municipio_ibge", "municipio", "ano_referencia", "populacao",
                "fonte", "versao_fonte", "extraido_em", "is_fallback",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(
        subset=["municipio_ibge", "municipio", "ano_referencia", "populacao", "fonte"],
        keep="last",
    ).reset_index(drop=True)


def select_population_for_year(
    dim: pd.DataFrame,
    analysis_year: int,
    *,
    source_priority: tuple[str, ...] = (),
    allow_previous_year: bool = False,
) -> pd.DataFrame:
    """Seleciona denominador somente por regra explícita e auditável.

    Sem fonte prioritária configurada, retorna todas as fontes candidatas para
    o ano solicitado. Fallback temporal só ocorre quando explicitamente habilitado.
    """
    if dim is None or dim.empty:
        return dim.copy() if isinstance(dim, pd.DataFrame) else pd.DataFrame()

    d = dim.copy()
    d["ano_referencia"] = pd.to_numeric(d["ano_referencia"], errors="coerce").astype("Int64")
    exact = d[d["ano_referencia"] == int(analysis_year)].copy()

    if exact.empty and allow_previous_year:
        prior = d[d["ano_referencia"].notna() & (d["ano_referencia"] < int(analysis_year))].copy()
        if not prior.empty:
            max_year = int(prior["ano_referencia"].max())
            exact = prior[prior["ano_referencia"] == max_year].copy()
            exact["is_fallback"] = True

    if exact.empty or not source_priority:
        return exact.reset_index(drop=True)

    rank = {name: i for i, name in enumerate(source_priority)}
    exact["_source_rank"] = exact["fonte"].map(rank).fillna(len(rank)).astype(int)
    name_key = exact["municipio"].astype("string").str.strip().str.upper()
    exact["_territory_key"] = exact["municipio_ibge"].astype("string")
    exact["_territory_key"] = exact["_territory_key"].where(
        exact["municipio_ibge"].notna(),
        "NAME:" + name_key,
    )
    exact = exact.sort_values(["_territory_key", "_source_rank", "fonte"])
    return (
        exact.drop_duplicates(subset=["_territory_key"], keep="first")
        .drop(columns=["_source_rank", "_territory_key"])
        .reset_index(drop=True)
    )


def write_population_dimension(dim: pd.DataFrame, outdir: Path | str) -> tuple[Path, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "dim_populacao_versionada.csv"
    pq_path = out / "dim_populacao_versionada.parquet"
    dim.to_csv(csv_path, index=False, encoding="utf-8-sig")
    dim.to_parquet(pq_path, index=False)
    return csv_path, pq_path
