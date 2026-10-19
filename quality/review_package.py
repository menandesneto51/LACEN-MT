# -*- coding: utf-8 -*-
"""Pacote de revisão humana da V2.1 — LACEN-MT.

Reúne evidências dos gates e organiza uma pauta objetiva para revisão do
Chief Architect e do especialista epidemiológico. Não aprova nem promove.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from quality.agent_reviews import AgentReview, default_agent_reviews, summarize_agent_reviews


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_review_package(
    quality_dir: Path | str,
    *,
    pr_number: int | None = None,
    head_sha: str | None = None,
    reviews_path: Path | str | None = None,
) -> dict[str, Any]:
    q = Path(quality_dir)
    dq = _load(q / "data_quality_gate_ultimo.json")
    parity = _load(q / "paridade_legado_v2_resumo.json")
    linkage = _load(q / "paridade_linkage_resumo.json")
    recon = _load(q / "reconciliacao_territorial_resumo.json")
    promotion = _load(q / "promotion_gate_v2_1.json")
    temporal_anchor = _load(q / "gal_temporal_anchor_summary.json")
    population_governance = _load(q / "population_governance_v2_1.json")
    population_source_comparison = _load(q / "population_source_comparison_summary.json")
    decision_registry = _load(q / "decision_status_registry_v2_1.json")
    decision_readiness = _load(q / "decision_readiness_v2_1.json")

    architecture_focus = [
        "Confirmar separação entre gate global de qualidade e gate de promoção da V2.",
        "Confirmar que joins V2 usam IBGE quando disponível e não introduzem fuzzy matching em produção.",
        "Revisar persistência do workflow de reconciliação e estabilidade de issue_id.",
        "Confirmar que nenhum caminho promove V2 automaticamente.",
        "Revisar contratos de lineage, configuração e compatibilidade local → servidor SES.",
    ]
    epidemiology_focus = [
        "Confirmar que anomalia estatística, prioridade epidemiológica e surto permanecem semanticamente separados.",
        "Revisar significado dos pareamentos GAL×SINAN/SIM/SIH/SIA e respectivas limitações.",
        "Confirmar que produtos de taxa usam denominador versionado e explicitam fonte/ano.",
        "Revisar manutenção da âncora temporal GAL sem alteração silenciosa.",
        "Confirmar que ausência de correspondência não é descrita automaticamente como subnotificação.",
    ]

    blockers = list(promotion.get("blocking_reasons") or [])
    conditions = list(promotion.get("conditions") or [])
    open_recon = int(recon.get("open_items") or 0)
    invalid_closed = int(recon.get("invalid_closed_items") or 0)
    if open_recon:
        conditions.append(f"Existem {open_recon} item(ns) de reconciliação territorial ainda abertos.")
    if invalid_closed:
        blockers.append(f"Existem {invalid_closed} fechamento(s) territorial(is) inválido(s).")

    agent_reviews = default_agent_reviews()
    if reviews_path is not None:
        reviews_payload = _load(Path(reviews_path))
    else:
        reviews_payload = _load(q / "reviews" / "v2_1_initial_reviews.json")
        if not reviews_payload:
            reviews_payload = _load(
                Path(__file__).resolve().parent / "reviews" / "v2_1_initial_reviews.json"
            )
    for key, payload in (reviews_payload.get("reviews") or {}).items():
        if key not in agent_reviews:
            continue
        agent_reviews[key] = AgentReview(
            agent=payload.get("agent") or agent_reviews[key].agent,
            status=payload.get("status") or "PENDING",
            findings=list(payload.get("findings") or []),
            blockers=list(payload.get("blockers") or []),
            recommendations=list(payload.get("recommendations") or []),
            evidence=dict(payload.get("evidence") or {}),
            decision=payload.get("decision"),
            reviewer=payload.get("reviewer"),
            reviewed_at=payload.get("reviewed_at"),
        )
    agent_review_summary = summarize_agent_reviews(agent_reviews)

    for item in agent_review_summary.get("blockers", []):
        blockers.append(item)
    if agent_review_summary.get("overall_status") != "PASS":
        conditions.append(
            "Pareceres multiagente ainda não estão todos em PASS."
        )

    return {
        "package_version": "v2.1-review-2",
        "pr_number": pr_number,
        "head_sha": head_sha,
        "promotion_gate_status": promotion.get("status", "UNKNOWN"),
        "automatic_promotion_allowed": False,
        "blocking_reasons": blockers,
        "conditions": conditions,
        "evidence": {
            "data_quality": dq,
            "parity": parity,
            "linkage": linkage,
            "territorial_reconciliation": recon,
            "promotion_gate": promotion,
            "gal_temporal_anchor": temporal_anchor,
            "population_governance": population_governance,
            "population_source_comparison": population_source_comparison,
            "decision_registry": decision_registry,
            "decision_readiness": decision_readiness,
        },
        "architecture_review": {
            "status": "PENDING",
            "focus": architecture_focus,
            "decision": None,
            "reviewer": None,
            "reviewed_at": None,
        },
        "epidemiology_review": {
            "status": "PENDING",
            "focus": epidemiology_focus,
            "decision": None,
            "reviewer": None,
            "reviewed_at": None,
        },
        "agent_reviews": {
            key: review.to_dict() for key, review in agent_reviews.items()
        },
        "agent_review_summary": agent_review_summary,
        "release_decision": {
            "status": "PENDING",
            "decision": None,
            "decided_by": None,
            "decided_at": None,
        },
    }


def write_review_package(
    package: dict[str, Any],
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "review_package_v2_1.json"
    md_path = out / "review_package_v2_1.md"

    json_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# LACEN-MT V2.1 — Pacote de revisão",
        "",
        f"- PR: {package.get('pr_number')}",
        f"- HEAD: {package.get('head_sha')}",
        f"- Promotion Gate: **{package.get('promotion_gate_status')}**",
        "- Promoção automática: **não permitida**",
        "",
        "## Bloqueios",
    ]
    blockers = package.get("blocking_reasons") or []
    lines += [f"- {x}" for x in blockers] or ["- Nenhum bloqueio registrado."]
    lines += ["", "## Condições pendentes"]
    conditions = package.get("conditions") or []
    lines += [f"- {x}" for x in conditions] or ["- Nenhuma condição pendente registrada."]

    lines += ["", "## Revisão arquitetural"]
    for item in package["architecture_review"]["focus"]:
        lines.append(f"- [ ] {item}")

    lines += ["", "## Evidência temporal GAL"]
    if package.get("evidence", {}).get("gal_temporal_anchor"):
        for key, value in package["evidence"]["gal_temporal_anchor"].items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Análise de sensibilidade ainda não disponível.")

    lines += ["", "## Governança populacional"]
    if package.get("evidence", {}).get("population_governance"):
        for key, value in package["evidence"]["population_governance"].items():
            if key == "findings":
                continue
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Relatório de governança populacional ainda não disponível.")

    lines += ["", "## Comparação das fontes populacionais"]
    if package.get("evidence", {}).get("population_source_comparison"):
        for key, value in package["evidence"]["population_source_comparison"].items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Comparação de fontes ainda não disponível.")

    lines += ["", "## Decision Status Registry"]
    registry = package.get("evidence", {}).get("decision_registry") or {}
    if registry:
        lines.append(f"- overall_status: {registry.get('overall_status')}")
        for decision_id, item in (registry.get("decisions") or {}).items():
            lines.append(
                f"- {decision_id}: {item.get('status')} | valid={item.get('valid')}"
            )
    else:
        lines.append("- Registry ainda não disponível.")

    lines += ["", "## Decision Readiness"]
    readiness = package.get("evidence", {}).get("decision_readiness") or {}
    if readiness:
        lines.append(f"- overall_status: {readiness.get('overall_status')}")
        for decision_id, item in (readiness.get("decisions") or {}).items():
            lines.append(
                f"- {decision_id}: {item.get('status')} | evidence_complete={item.get('evidence_complete')}"
            )
    else:
        lines.append("- Pré-validação técnica ainda não disponível.")

    lines += ["", "## Revisão epidemiológica"]
    for item in package["epidemiology_review"]["focus"]:
        lines.append(f"- [ ] {item}")

    lines += ["", "## Pareceres multiagente"]
    for key, review in package.get("agent_reviews", {}).items():
        lines += [
            f"### {review.get('agent', key)}",
            f"- Status: {review.get('status', 'PENDING')}",
            f"- Decisão: {review.get('decision') or '—'}",
        ]

    lines += [
        "",
        "## Decisão de release",
        "- Status: PENDING",
        "- A V2.1 não deve substituir o legado até decisão humana explícita.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
