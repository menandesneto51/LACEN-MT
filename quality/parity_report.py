# -*- coding: utf-8 -*-
"""Relatório de paridade legado × V2 — LACEN-MT.

Compara denominadores, taxas e cobertura territorial sem promover a camada V2.
Divergência não é automaticamente erro: o objetivo é torná-la explícita,
auditável e acionável antes de qualquer migração.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("solicitacoes_100k", "solicitacoes_100k_v2"),
    ("incidencia_100k", "incidencia_100k_v2"),
    ("notificacoes_100k", "notificacoes_100k_v2"),
    ("mortalidade_100k", "mortalidade_100k_v2"),
)


@dataclass
class ParitySummary:
    rows: int
    rows_with_v2_population: int
    rows_without_v2_population: int
    ibge_rows: int
    name_fallback_rows: int
    max_population_rel_diff: float | None
    max_rate_rel_diff: float | None
    status: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_rel_diff(a: pd.Series, b: pd.Series) -> pd.Series:
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    denom = a.abs().replace(0, np.nan)
    return ((b - a).abs() / denom).replace([np.inf, -np.inf], np.nan)


def build_parity_report(
    weekly: pd.DataFrame,
    *,
    warn_population_rel_diff: float = 0.05,
    block_population_rel_diff: float = 0.20,
    warn_rate_rel_diff: float = 0.05,
    block_rate_rel_diff: float = 0.20,
) -> tuple[pd.DataFrame, ParitySummary]:
    if weekly is None or weekly.empty:
        detail = pd.DataFrame()
        return detail, ParitySummary(
            rows=0,
            rows_with_v2_population=0,
            rows_without_v2_population=0,
            ibge_rows=0,
            name_fallback_rows=0,
            max_population_rel_diff=None,
            max_rate_rel_diff=None,
            status="WARN",
            warnings=["Base integrada ausente ou vazia; paridade não calculada."],
        )

    d = weekly.copy()
    if "territory_key" not in d.columns:
        code = d.get("municipio_ibge", pd.Series(pd.NA, index=d.index, dtype="string")).astype("string")
        name = d.get("municipio", pd.Series("", index=d.index)).astype(str).str.strip().str.upper()
        d["territory_key"] = "NAME:" + name
        valid = code.str.fullmatch(r"\d{7}", na=False)
        d.loc[valid, "territory_key"] = "IBGE:" + code[valid]

    for col in ("populacao", "populacao_v2"):
        if col not in d.columns:
            d[col] = np.nan
        d[col] = pd.to_numeric(d[col], errors="coerce")

    d["population_rel_diff"] = _safe_rel_diff(d["populacao"], d["populacao_v2"])
    d["population_abs_diff"] = (d["populacao_v2"] - d["populacao"]).abs()

    rate_rel_cols: list[str] = []
    for legacy, v2 in RATE_PAIRS:
        if legacy not in d.columns:
            d[legacy] = np.nan
        if v2 not in d.columns:
            d[v2] = np.nan
        col = f"{legacy}_rel_diff_v2"
        d[col] = _safe_rel_diff(d[legacy], d[v2])
        rate_rel_cols.append(col)

    d["max_rate_rel_diff"] = d[rate_rel_cols].max(axis=1, skipna=True)
    d["parity_reason"] = ""
    d.loc[d["populacao_v2"].isna(), "parity_reason"] = "V2_SEM_DENOMINADOR"

    pop_warn = d["population_rel_diff"] > warn_population_rel_diff
    pop_block = d["population_rel_diff"] > block_population_rel_diff
    rate_warn = d["max_rate_rel_diff"] > warn_rate_rel_diff
    rate_block = d["max_rate_rel_diff"] > block_rate_rel_diff

    d["parity_status"] = "PASS"
    d.loc[d["populacao_v2"].isna(), "parity_status"] = "WARN"
    d.loc[pop_warn | rate_warn, "parity_status"] = "WARN"
    d.loc[pop_block | rate_block, "parity_status"] = "BLOCK"

    warnings: list[str] = []
    without_v2 = int(d["populacao_v2"].isna().sum())
    if without_v2:
        warnings.append(f"{without_v2} linha(s) sem denominador V2; taxas V2 não comparáveis.")

    max_pop = d["population_rel_diff"].max(skipna=True)
    max_rate = d["max_rate_rel_diff"].max(skipna=True)
    max_pop_val = None if pd.isna(max_pop) else float(max_pop)
    max_rate_val = None if pd.isna(max_rate) else float(max_rate)

    if (max_pop_val is not None and max_pop_val > block_population_rel_diff) or (
        max_rate_val is not None and max_rate_val > block_rate_rel_diff
    ):
        status = "BLOCK"
        warnings.append("Divergência crítica legado × V2 acima do limiar de bloqueio de promoção.")
    elif without_v2 or (
        max_pop_val is not None and max_pop_val > warn_population_rel_diff
    ) or (
        max_rate_val is not None and max_rate_val > warn_rate_rel_diff
    ):
        status = "WARN"
    else:
        status = "PASS"

    summary = ParitySummary(
        rows=int(len(d)),
        rows_with_v2_population=int(d["populacao_v2"].notna().sum()),
        rows_without_v2_population=without_v2,
        ibge_rows=int(d["territory_key"].astype(str).str.startswith("IBGE:").sum()),
        name_fallback_rows=int(d["territory_key"].astype(str).str.startswith("NAME:").sum()),
        max_population_rel_diff=max_pop_val,
        max_rate_rel_diff=max_rate_val,
        status=status,
        warnings=warnings,
    )
    return d, summary


def write_parity_report(
    detail: pd.DataFrame,
    summary: ParitySummary,
    outdir: Path | str,
) -> dict[str, Path]:
    import json

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    detail_csv = out / "paridade_legado_v2_detalhe.csv"
    summary_json = out / "paridade_legado_v2_resumo.json"
    summary_txt = out / "paridade_legado_v2_resumo.txt"

    detail.to_csv(detail_csv, index=False, encoding="utf-8-sig")
    try:
        detail.to_parquet(out / "paridade_legado_v2_detalhe.parquet", index=False)
    except Exception:
        pass

    summary_json.write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2 — PARIDADE LEGADO × V2",
        f"status: {summary.status}",
        f"linhas: {summary.rows}",
        f"com_populacao_v2: {summary.rows_with_v2_population}",
        f"sem_populacao_v2: {summary.rows_without_v2_population}",
        f"territorios_ibge: {summary.ibge_rows}",
        f"fallback_nome: {summary.name_fallback_rows}",
        f"max_population_rel_diff: {summary.max_population_rel_diff}",
        f"max_rate_rel_diff: {summary.max_rate_rel_diff}",
        "",
        *[f"AVISO: {w}" for w in summary.warnings],
    ]
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"detail_csv": detail_csv, "summary_json": summary_json, "summary_txt": summary_txt}
