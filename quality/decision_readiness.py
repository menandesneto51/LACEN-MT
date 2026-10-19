# -*- coding: utf-8 -*-
"""Pré-validação técnica de decisões institucionais — LACEN-MT V2.1.

Avalia se DEC-001 e DEC-002 possuem evidência técnica suficiente para
submissão humana. Não escolhe alternativa, fonte ou decisão.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import pandas as pd


READY = "READY_FOR_HUMAN_DECISION"
NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
DATA_QUALITY_BLOCK = "DATA_QUALITY_BLOCK"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def evaluate_dec001_readiness(quality_dir: Path | str) -> dict[str, Any]:
    q = Path(quality_dir)
    summary_path = q / "gal_temporal_anchor_summary.json"
    weekly_path = q / "gal_temporal_anchor_weekly_comparison.csv"
    brief_path = q / "decision_brief_DEC-001.md"

    summary = _load_json(summary_path)
    missing_files = [
        p.name for p in (summary_path, weekly_path, brief_path) if not p.exists()
    ]
    required_fields = (
        "rows_total",
        "rows_both_dates",
        "coverage_solicitacao",
        "coverage_coleta",
        "median_delay_days",
        "p90_delay_days",
        "changed_epi_week_rows",
        "changed_epi_week_pct",
        "changed_epi_year_rows",
        "changed_epi_year_pct",
        "weeks_compared",
        "weeks_with_count_delta",
        "weeks_with_count_delta_pct",
        "max_absolute_weekly_count_diff",
        "sum_absolute_weekly_count_diff",
    )
    missing_fields = [k for k in required_fields if summary.get(k) is None]

    blockers: list[str] = []
    conditions: list[str] = []
    if missing_files:
        conditions.append("Arquivos ausentes: " + ", ".join(missing_files))
    if missing_fields:
        conditions.append("Campos ausentes: " + ", ".join(missing_fields))

    rows_both = summary.get("rows_both_dates")
    weeks = summary.get("weeks_compared")
    if rows_both == 0:
        blockers.append("Nenhum registro possui simultaneamente data de solicitação e data de coleta.")
    if weeks == 0:
        blockers.append("Nenhuma semana pôde ser comparada entre as duas âncoras.")

    if blockers:
        status = DATA_QUALITY_BLOCK
    elif conditions:
        status = NEEDS_EVIDENCE
    else:
        status = READY

    return {
        "decision_id": "DEC-001",
        "status": status,
        "blockers": blockers,
        "conditions": conditions,
        "evidence_complete": status == READY,
        "automatic_decision_allowed": False,
    }


def evaluate_dec002_readiness(quality_dir: Path | str) -> dict[str, Any]:
    q = Path(quality_dir)
    summary_path = q / "population_source_comparison_summary.json"
    coverage_path = q / "population_source_coverage_detail.csv"
    pairwise_path = q / "population_source_pairwise_comparison.csv"
    governance_path = q / "population_governance_v2_1.json"
    brief_path = q / "decision_brief_DEC-002.md"

    summary = _load_json(summary_path)
    governance = _load_json(governance_path)
    missing_files = [
        p.name
        for p in (summary_path, coverage_path, pairwise_path, governance_path, brief_path)
        if not p.exists()
    ]

    blockers: list[str] = []
    conditions: list[str] = []
    if missing_files:
        conditions.append("Arquivos ausentes: " + ", ".join(missing_files))

    sources = summary.get("sources") or []
    if not sources:
        blockers.append("Nenhuma fonte populacional candidata foi encontrada para comparação.")

    internal_conflicts = 0
    if coverage_path.exists():
        try:
            detail = pd.read_csv(coverage_path, low_memory=False)
            if "internal_conflict" in detail.columns:
                conflict_series = detail["internal_conflict"].astype(str).str.lower()
                internal_conflicts = int(conflict_series.isin(["true", "1"]).sum())
        except Exception as exc:
            conditions.append(f"Não foi possível ler detalhe de cobertura: {exc}")
    if internal_conflicts:
        blockers.append(
            f"{internal_conflicts} conflito(s) interno(s) de população precisam ser saneados antes da decisão."
        )

    if summary.get("analysis_year") is None:
        conditions.append("Ano de análise populacional não informado.")
    if summary.get("source_coverage") is None:
        conditions.append("Cobertura territorial por fonte não informada.")

    # Política PENDING é esperada antes da decisão; não é bloqueio de readiness.
    if governance and governance.get("status") not in {"PENDING_APPROVAL", "APPROVED"}:
        blockers.append(f"Status inesperado da política populacional: {governance.get('status')}.")

    if blockers:
        status = DATA_QUALITY_BLOCK
    elif conditions:
        status = NEEDS_EVIDENCE
    else:
        status = READY

    return {
        "decision_id": "DEC-002",
        "status": status,
        "blockers": blockers,
        "conditions": conditions,
        "internal_conflicts": internal_conflicts,
        "evidence_complete": status == READY,
        "automatic_decision_allowed": False,
    }


def evaluate_decision_readiness(quality_dir: Path | str) -> dict[str, Any]:
    dec001 = evaluate_dec001_readiness(quality_dir)
    dec002 = evaluate_dec002_readiness(quality_dir)

    statuses = [dec001["status"], dec002["status"]]
    if DATA_QUALITY_BLOCK in statuses:
        overall = DATA_QUALITY_BLOCK
    elif NEEDS_EVIDENCE in statuses:
        overall = NEEDS_EVIDENCE
    else:
        overall = READY

    return {
        "overall_status": overall,
        "automatic_decision_allowed": False,
        "decisions": {
            "DEC-001": dec001,
            "DEC-002": dec002,
        },
        "ready_for_human_decision": overall == READY,
    }


def write_decision_readiness_report(
    report: dict[str, Any],
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "decision_readiness_v2_1.json"
    txt_path = out / "decision_readiness_v2_1.txt"

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2.1 — DECISION READINESS",
        f"overall_status: {report.get('overall_status')}",
        "automatic_decision_allowed: false",
        "",
    ]
    for decision_id, item in (report.get("decisions") or {}).items():
        lines += [
            f"[{decision_id}]",
            f"status: {item.get('status')}",
            f"evidence_complete: {item.get('evidence_complete')}",
        ]
        for blocker in item.get("blockers", []):
            lines.append(f"- BLOCK: {blocker}")
        for condition in item.get("conditions", []):
            lines.append(f"- PENDENTE: {condition}")
        lines.append("")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path}
