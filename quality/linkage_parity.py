# -*- coding: utf-8 -*-
"""Paridade de pareamentos territoriais legado (nome) × V2 (IBGE).

Não altera joins de produção. Mede o efeito da migração de chave e produz
artefatos de auditoria para GAL×SINAN, GAL×SIM, GAL×SIH e GAL×SIA.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class LinkageParitySummary:
    source: str
    rows_left: int
    both_same: int
    recovered_by_ibge: int
    lost_by_ibge: int
    conflict: int
    no_match: int
    promotion_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm_name(s: pd.Series) -> pd.Series:
    return s.astype("string").fillna("").str.strip().str.upper()


def _norm_ibge(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    return out.where(out.str.fullmatch(r"\d{7}", na=False))


def _prepare_keys(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "municipio" not in d.columns:
        d["municipio"] = ""
    if "municipio_ibge" not in d.columns:
        d["municipio_ibge"] = pd.NA
    d["_name_key"] = _norm_name(d["municipio"])
    d["_ibge_key"] = _norm_ibge(d["municipio_ibge"])
    return d


def compare_linkage(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    source: str,
    dimensions: tuple[str, ...],
    metric_col: str,
) -> tuple[pd.DataFrame, LinkageParitySummary]:
    """Compara o valor pareado por nome versus IBGE para as mesmas dimensões."""
    l = _prepare_keys(left)
    r = _prepare_keys(right)

    missing_l = [c for c in dimensions if c not in l.columns]
    missing_r = [c for c in dimensions if c not in r.columns]
    if missing_l or missing_r or metric_col not in r.columns:
        detail = pd.DataFrame()
        summary = LinkageParitySummary(
            source=source,
            rows_left=int(len(l)),
            both_same=0,
            recovered_by_ibge=0,
            lost_by_ibge=0,
            conflict=0,
            no_match=int(len(l)),
            promotion_status="WARN",
        )
        return detail, summary

    r[metric_col] = pd.to_numeric(r[metric_col], errors="coerce").fillna(0)

    legacy_group = (
        r.groupby([*dimensions, "_name_key"], dropna=False, as_index=False)[metric_col]
        .sum()
        .rename(columns={metric_col: "legacy_match_value"})
    )
    v2_group = (
        r[r["_ibge_key"].notna()]
        .groupby([*dimensions, "_ibge_key"], dropna=False, as_index=False)[metric_col]
        .sum()
        .rename(columns={metric_col: "v2_match_value"})
    )

    out = l.merge(
        legacy_group,
        on=[*dimensions, "_name_key"],
        how="left",
    )
    out = out.merge(
        v2_group,
        on=[*dimensions, "_ibge_key"],
        how="left",
    )

    legacy_present = out["legacy_match_value"].notna()
    v2_present = out["v2_match_value"].notna()
    same = (
        legacy_present
        & v2_present
        & (out["legacy_match_value"] == out["v2_match_value"])
    )
    recovered = ~legacy_present & v2_present
    lost = legacy_present & ~v2_present & out["_ibge_key"].notna()
    conflict = (
        legacy_present
        & v2_present
        & (out["legacy_match_value"] != out["v2_match_value"])
    )
    no_match = ~legacy_present & ~v2_present

    out["linkage_parity"] = "SEM_MATCH"
    out.loc[same, "linkage_parity"] = "IGUAL"
    out.loc[recovered, "linkage_parity"] = "RECUPERADO_POR_IBGE"
    out.loc[lost, "linkage_parity"] = "PERDIDO_COM_IBGE"
    out.loc[conflict, "linkage_parity"] = "CONFLITO"

    if int(conflict.sum()) > 0 or int(lost.sum()) > 0:
        promotion_status = "BLOCK"
    elif int(recovered.sum()) > 0 or int(no_match.sum()) > 0:
        promotion_status = "WARN"
    else:
        promotion_status = "PASS"

    summary = LinkageParitySummary(
        source=source,
        rows_left=int(len(out)),
        both_same=int(same.sum()),
        recovered_by_ibge=int(recovered.sum()),
        lost_by_ibge=int(lost.sum()),
        conflict=int(conflict.sum()),
        no_match=int(no_match.sum()),
        promotion_status=promotion_status,
    )
    keep = [
        *[c for c in dimensions if c in out.columns],
        "municipio",
        "municipio_ibge",
        "_name_key",
        "_ibge_key",
        "legacy_match_value",
        "v2_match_value",
        "linkage_parity",
    ]
    return out[keep].copy(), summary


def write_linkage_parity(
    reports: dict[str, tuple[pd.DataFrame, LinkageParitySummary]],
    outdir: Path | str,
) -> dict[str, Any]:
    import json

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    for source, (detail, summary) in reports.items():
        safe = source.lower().replace("/", "_").replace("×", "x").replace(" ", "_")
        detail.to_csv(out / f"paridade_linkage_{safe}.csv", index=False, encoding="utf-8-sig")
        try:
            detail.to_parquet(out / f"paridade_linkage_{safe}.parquet", index=False)
        except Exception:
            pass
        summaries.append(summary.to_dict())

    overall = "PASS"
    if any(s["promotion_status"] == "BLOCK" for s in summaries):
        overall = "BLOCK"
    elif any(s["promotion_status"] == "WARN" for s in summaries):
        overall = "WARN"

    payload = {"promotion_status": overall, "sources": summaries}
    (out / "paridade_linkage_resumo.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["LACEN-MT V2 — PARIDADE DE PAREAMENTOS", f"promotion_status: {overall}", ""]
    for s in summaries:
        lines.append(
            f"{s['source']}: {s['promotion_status']} | igual={s['both_same']} | "
            f"recuperado_ibge={s['recovered_by_ibge']} | perdido_ibge={s['lost_by_ibge']} | "
            f"conflito={s['conflict']} | sem_match={s['no_match']}"
        )
    (out / "paridade_linkage_resumo.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
