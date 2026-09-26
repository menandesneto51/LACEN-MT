# -*- coding: utf-8 -*-
"""Promotion Gate consolidado — LACEN-MT V2.1.

Consolida evidências de qualidade e governança. Nunca promove automaticamente
a camada V2; apenas informa se ela está NOT_READY, CONDITIONAL ou READY_FOR_REVIEW.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import json


@dataclass
class PromotionGateResult:
    status: str
    blocking_reasons: list[str]
    conditions: list[str]
    evidence: dict[str, Any]
    automatic_promotion_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_promotion_gate(
    *,
    data_quality_status: str | None,
    parity_status: str | None,
    linkage_parity_status: str | None,
    territorial_promotion_ready: bool | None,
    ci_status: str | None = None,
    architecture_review: str | None = None,
    epidemiology_review: str | None = None,
    agent_reviews_status: str | None = None,
    population_governance_approved: bool | None = None,
    population_governance_blockers: list[str] | None = None,
) -> PromotionGateResult:
    """Avalia prontidão para revisão humana, nunca para promoção automática."""
    blocking: list[str] = []
    conditions: list[str] = []

    dq = (data_quality_status or "UNKNOWN").upper()
    parity = (parity_status or "UNKNOWN").upper()
    linkage = (linkage_parity_status or "UNKNOWN").upper()
    ci = (ci_status or "UNKNOWN").upper()
    arch = (architecture_review or "PENDING").upper()
    epi = (epidemiology_review or "PENDING").upper()
    agents = (agent_reviews_status or "PENDING").upper()
    pop_blockers = list(population_governance_blockers or [])

    if dq == "BLOCK":
        blocking.append("Data Quality Gate em BLOCK.")
    elif dq in {"WARN", "UNKNOWN"}:
        conditions.append(f"Data Quality Gate ainda em {dq}.")

    if parity == "BLOCK":
        blocking.append("Paridade legado × V2 bloqueia promoção.")
    elif parity in {"WARN", "UNKNOWN"}:
        conditions.append(f"Paridade legado × V2 em {parity}.")

    if linkage == "BLOCK":
        blocking.append("Paridade de linkage territorial bloqueia promoção.")
    elif linkage in {"WARN", "UNKNOWN"}:
        conditions.append(f"Paridade de linkage territorial em {linkage}.")

    if territorial_promotion_ready is False:
        blocking.append("Reconciliação territorial possui itens críticos/altos pendentes ou fechamento inválido.")
    elif territorial_promotion_ready is None:
        conditions.append("Reconciliação territorial ainda sem decisão de prontidão.")

    if ci == "FAIL":
        blocking.append("CI falhou.")
    elif ci not in {"PASS", "SUCCESS"}:
        conditions.append("CI ainda não confirmado como verde para o HEAD avaliado.")

    if arch not in {"APPROVED", "PASS"}:
        conditions.append("Revisão arquitetural ainda pendente.")
    if epi not in {"APPROVED", "PASS"}:
        conditions.append("Revisão epidemiológica ainda pendente.")

    if agents == "BLOCK":
        blocking.append("Pareceres multiagente contêm BLOCK.")
    elif agents != "PASS":
        conditions.append(f"Pareceres multiagente em {agents}.")

    if pop_blockers:
        blocking.extend([f"Governança populacional: {x}" for x in pop_blockers])
    elif population_governance_approved is False:
        conditions.append("Governança populacional ainda não aprovada.")
    elif population_governance_approved is None:
        conditions.append("Governança populacional sem evidência de aprovação.")

    if blocking:
        status = "NOT_READY"
    elif conditions:
        status = "CONDITIONAL"
    else:
        status = "READY_FOR_REVIEW"

    return PromotionGateResult(
        status=status,
        blocking_reasons=blocking,
        conditions=conditions,
        evidence={
            "data_quality_status": dq,
            "parity_status": parity,
            "linkage_parity_status": linkage,
            "territorial_promotion_ready": territorial_promotion_ready,
            "ci_status": ci,
            "architecture_review": arch,
            "epidemiology_review": epi,
            "agent_reviews_status": agents,
            "population_governance_approved": population_governance_approved,
            "population_governance_blockers": pop_blockers,
        },
        automatic_promotion_allowed=False,
    )


def load_json(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_gate_from_artifacts(
    quality_dir: Path | str,
    *,
    ci_status: str | None = None,
    architecture_review: str | None = None,
    epidemiology_review: str | None = None,
    agent_reviews_status: str | None = None,
    population_governance_approved: bool | None = None,
    population_governance_blockers: list[str] | None = None,
) -> PromotionGateResult:
    q = Path(quality_dir)
    dq = load_json(q / "data_quality_gate_ultimo.json")
    parity = load_json(q / "paridade_legado_v2_resumo.json")
    linkage = load_json(q / "paridade_linkage_resumo.json")
    recon = load_json(q / "reconciliacao_territorial_resumo.json")

    return evaluate_promotion_gate(
        data_quality_status=dq.get("status"),
        parity_status=parity.get("status"),
        linkage_parity_status=linkage.get("promotion_status"),
        territorial_promotion_ready=recon.get("promotion_ready"),
        ci_status=ci_status,
        architecture_review=architecture_review,
        epidemiology_review=epidemiology_review,
        agent_reviews_status=agent_reviews_status,
        population_governance_approved=population_governance_approved,
        population_governance_blockers=population_governance_blockers,
    )


def write_promotion_gate(
    result: PromotionGateResult,
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "promotion_gate_v2_1.json"
    txt_path = out / "promotion_gate_v2_1.txt"

    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2.1 — PROMOTION GATE",
        f"status: {result.status}",
        "automatic_promotion_allowed: false",
        "",
        "BLOQUEIOS:",
        *([f"- {x}" for x in result.blocking_reasons] or ["- nenhum"]),
        "",
        "CONDICOES:",
        *([f"- {x}" for x in result.conditions] or ["- nenhuma"]),
        "",
        "EVIDENCIAS:",
        *[f"- {k}: {v}" for k, v in result.evidence.items()],
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path}
