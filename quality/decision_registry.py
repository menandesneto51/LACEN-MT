# -*- coding: utf-8 -*-
"""Registro consolidado das decisões institucionais — LACEN-MT V2.1."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import json


ALLOWED_DECISION_STATUS = {"PENDING", "APPROVED", "REJECTED"}


@dataclass
class DecisionStatus:
    decision_id: str
    title: str
    status: str
    decided_by: str | None
    decided_at: str | None
    evidence: list[str]
    decision: Any
    valid: bool
    validation_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_decision_registry(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def validate_decision(
    decision_id: str,
    payload: dict[str, Any],
) -> DecisionStatus:
    status = str(payload.get("status") or "PENDING").upper()
    errors: list[str] = []
    if status not in ALLOWED_DECISION_STATUS:
        errors.append(f"Status inválido: {status}")

    decided_by = payload.get("decided_by")
    decided_at = payload.get("decided_at")
    evidence = [str(x) for x in (payload.get("evidence") or []) if str(x).strip()]
    decision = payload.get("decision")

    if status in {"APPROVED", "REJECTED"}:
        if not decided_by:
            errors.append("Decisão concluída exige decided_by.")
        if not decided_at:
            errors.append("Decisão concluída exige decided_at.")
        if not evidence:
            errors.append("Decisão concluída exige ao menos uma evidência.")
        if decision in (None, "", {}):
            errors.append("Decisão concluída exige conteúdo em decision.")

    return DecisionStatus(
        decision_id=decision_id,
        title=str(payload.get("title") or decision_id),
        status=status,
        decided_by=decided_by,
        decided_at=decided_at,
        evidence=evidence,
        decision=decision,
        valid=not errors,
        validation_errors=errors,
    )


def evaluate_decision_registry(registry: dict[str, Any]) -> dict[str, Any]:
    decisions_payload = registry.get("decisions") or {}
    decisions: dict[str, DecisionStatus] = {}
    for decision_id in ("DEC-001", "DEC-002"):
        decisions[decision_id] = validate_decision(
            decision_id,
            dict(decisions_payload.get(decision_id) or {}),
        )

    blockers: list[str] = []
    conditions: list[str] = []
    for decision_id, item in decisions.items():
        if not item.valid:
            blockers.append(
                f"{decision_id} possui registro inválido: "
                + "; ".join(item.validation_errors)
            )
            continue
        if item.status == "REJECTED":
            blockers.append(f"{decision_id} foi REJECTED.")
        elif item.status == "PENDING":
            conditions.append(f"{decision_id} permanece PENDING.")

    if blockers:
        overall = "BLOCK"
    elif conditions:
        overall = "PENDING"
    else:
        overall = "APPROVED"

    return {
        "overall_status": overall,
        "automatic_decision_allowed": False,
        "decisions": {key: value.to_dict() for key, value in decisions.items()},
        "blockers": blockers,
        "conditions": conditions,
        "all_required_decisions_approved": overall == "APPROVED",
    }


def write_decision_registry_report(
    evaluated: dict[str, Any],
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "decision_status_registry_v2_1.json"
    txt_path = out / "decision_status_registry_v2_1.txt"

    json_path.write_text(
        json.dumps(evaluated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2.1 — DECISION STATUS REGISTRY",
        f"overall_status: {evaluated.get('overall_status')}",
        "automatic_decision_allowed: false",
        "",
    ]
    for decision_id, item in (evaluated.get("decisions") or {}).items():
        lines += [
            f"[{decision_id}]",
            f"title: {item.get('title')}",
            f"status: {item.get('status')}",
            f"valid: {item.get('valid')}",
            f"decided_by: {item.get('decided_by') or '—'}",
            f"decided_at: {item.get('decided_at') or '—'}",
            "",
        ]
    if evaluated.get("blockers"):
        lines.append("BLOQUEIOS:")
        lines += [f"- {x}" for x in evaluated["blockers"]]
        lines.append("")
    if evaluated.get("conditions"):
        lines.append("CONDICOES:")
        lines += [f"- {x}" for x in evaluated["conditions"]]
        lines.append("")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path}
