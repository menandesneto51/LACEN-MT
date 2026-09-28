# -*- coding: utf-8 -*-
"""Contratos estruturados dos pareceres multiagente — LACEN-MT V2.1.

Os agentes produzem pareceres auditáveis, mas nenhum agente isoladamente
autoriza release ou promoção da camada V2.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any
import json


ALLOWED_REVIEW_STATUS = {"PENDING", "PASS", "WARN", "BLOCK", "NOT_APPLICABLE"}


@dataclass
class AgentReview:
    agent: str
    status: str = "PENDING"
    findings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    decision: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None

    def validate(self) -> None:
        if self.status not in ALLOWED_REVIEW_STATUS:
            raise ValueError(f"Status inválido para {self.agent}: {self.status}")
        if self.status == "BLOCK" and not self.blockers:
            raise ValueError(f"{self.agent}: BLOCK exige ao menos um bloqueio explícito.")
        if self.status in {"PASS", "WARN", "BLOCK", "NOT_APPLICABLE"} and not self.decision:
            raise ValueError(f"{self.agent}: revisão concluída exige decision.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


def default_agent_reviews() -> dict[str, AgentReview]:
    return {
        "chief_architect": AgentReview(agent="Chief Architect"),
        "clinical_epidemiological_specialist": AgentReview(
            agent="Clinical/Epidemiological Specialist"
        ),
        "ml_specialist": AgentReview(agent="ML Specialist"),
        "statistics_specialist": AgentReview(agent="Statistics Specialist"),
        "laboratory_intelligence_specialist": AgentReview(
            agent="Laboratory Intelligence Specialist"
        ),
        "genomic_intelligence_specialist": AgentReview(
            agent="Genomic Intelligence Specialist"
        ),
        "supply_chain_specialist": AgentReview(agent="Supply Chain Specialist"),
        "technical_writing_abnt": AgentReview(agent="Technical Writing/ABNT"),
        "qa": AgentReview(agent="QA"),
        "security_data_governance": AgentReview(agent="Security/Data Governance"),
    }


def summarize_agent_reviews(reviews: dict[str, AgentReview]) -> dict[str, Any]:
    statuses = {key: review.status for key, review in reviews.items()}
    blockers: list[str] = []
    pending: list[str] = []
    warnings: list[str] = []

    for key, review in reviews.items():
        if review.status == "BLOCK":
            blockers.extend([f"{review.agent}: {x}" for x in review.blockers])
        elif review.status == "PENDING":
            pending.append(review.agent)
        elif review.status == "WARN":
            warnings.append(review.agent)

    if blockers:
        overall = "BLOCK"
    elif pending or warnings:
        overall = "PENDING"
    else:
        overall = "PASS"

    return {
        "overall_status": overall,
        "statuses": statuses,
        "blockers": blockers,
        "pending_agents": pending,
        "warning_agents": warnings,
        "all_required_reviews_passed": overall == "PASS",
    }


def write_agent_reviews(
    reviews: dict[str, AgentReview],
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "agent_reviews_v2_1.json"
    txt_path = out / "agent_reviews_v2_1.txt"

    payload = {
        "reviews": {key: review.to_dict() for key, review in reviews.items()},
        "summary": summarize_agent_reviews(reviews),
        "automatic_release_allowed": False,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2.1 — PARECERES MULTIAGENTE",
        f"overall_status: {payload['summary']['overall_status']}",
        "automatic_release_allowed: false",
        "",
    ]
    for key, review in reviews.items():
        lines += [
            f"[{review.agent}]",
            f"status: {review.status}",
            f"decision: {review.decision or '—'}",
            f"reviewer: {review.reviewer or '—'}",
            f"reviewed_at: {review.reviewed_at or '—'}",
            "",
        ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path}


def load_agent_reviews(path: Path | str) -> dict[str, AgentReview]:
    p = Path(path)
    if not p.exists():
        return default_agent_reviews()
    payload = json.loads(p.read_text(encoding="utf-8"))
    reviews = default_agent_reviews()
    for key, item in (payload.get("reviews") or {}).items():
        if key not in reviews:
            continue
        reviews[key] = AgentReview(
            agent=item.get("agent") or reviews[key].agent,
            status=item.get("status") or "PENDING",
            findings=list(item.get("findings") or []),
            blockers=list(item.get("blockers") or []),
            recommendations=list(item.get("recommendations") or []),
            evidence=dict(item.get("evidence") or {}),
            decision=item.get("decision"),
            reviewer=item.get("reviewer"),
            reviewed_at=item.get("reviewed_at"),
        )
        reviews[key].validate()
    return reviews
