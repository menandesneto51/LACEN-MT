# -*- coding: utf-8 -*-
"""Governança da seleção de fontes populacionais — LACEN-MT V2.1."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import json

import pandas as pd


@dataclass
class PopulationGovernanceDecision:
    status: str
    approved: bool
    source_priority: tuple[str, ...]
    allow_previous_year: bool
    findings: list[str]
    blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_priority"] = list(self.source_priority)
        return d


def load_population_governance(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def evaluate_population_governance(
    dim: pd.DataFrame,
    *,
    analysis_year: int,
    policy: dict[str, Any],
) -> PopulationGovernanceDecision:
    findings: list[str] = []
    blockers: list[str] = []

    status = str(policy.get("status") or "PENDING_APPROVAL").upper()
    priority = tuple(str(x).strip() for x in (policy.get("source_priority") or []) if str(x).strip())
    approved = status == "APPROVED"

    if dim is None or dim.empty:
        findings.append("Nenhuma fonte populacional disponível no staging.")
        return PopulationGovernanceDecision(
            status=status,
            approved=approved,
            source_priority=priority,
            allow_previous_year=bool(policy.get("allow_previous_year", False)),
            findings=findings,
            blockers=blockers,
        )

    d = dim.copy()
    d["ano_referencia"] = pd.to_numeric(d["ano_referencia"], errors="coerce").astype("Int64")
    current = d[d["ano_referencia"] == int(analysis_year)].copy()
    if current.empty:
        blockers.append(f"Não há denominador populacional para o ano {analysis_year}.")

    available = sorted(current["fonte"].dropna().astype(str).unique().tolist()) if not current.empty else []
    findings.append("Fontes disponíveis no ano: " + (", ".join(available) or "nenhuma"))

    if len(available) > 1 and not priority:
        blockers.append("Há múltiplas fontes candidatas e nenhuma prioridade aprovada/configurada.")

    if priority:
        unknown = [src for src in priority if src not in available]
        if unknown:
            findings.append("Fontes priorizadas ausentes neste ano: " + ", ".join(unknown))

    if not approved:
        blockers.append("Política populacional ainda não está APPROVED.")

    # Conflito interno na mesma fonte/território/ano não pode ser resolvido por keep-first.
    if not current.empty:
        work = current.copy()
        name_key = work["municipio"].astype("string").str.strip().str.upper()
        work["_territory_key"] = work["municipio_ibge"].astype("string")
        work["_territory_key"] = work["_territory_key"].where(
            work["municipio_ibge"].notna(),
            "NAME:" + name_key,
        )
        conflicts = (
            work.groupby(["fonte", "_territory_key"], dropna=False)["populacao"]
            .nunique(dropna=True)
        )
        n_conflicts = int((conflicts > 1).sum())
        if n_conflicts:
            blockers.append(
                f"{n_conflicts} conflito(s) interno(s) de denominador na mesma fonte/território/ano."
            )

    return PopulationGovernanceDecision(
        status=status,
        approved=approved,
        source_priority=priority,
        allow_previous_year=bool(policy.get("allow_previous_year", False)),
        findings=findings,
        blockers=blockers,
    )


def write_population_governance_report(
    decision: PopulationGovernanceDecision,
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "population_governance_v2_1.json"
    txt_path = out / "population_governance_v2_1.txt"

    json_path.write_text(
        json.dumps(decision.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2.1 — GOVERNANÇA POPULACIONAL",
        f"status: {decision.status}",
        f"approved: {str(decision.approved).lower()}",
        f"source_priority: {', '.join(decision.source_priority) or '—'}",
        f"allow_previous_year: {str(decision.allow_previous_year).lower()}",
        "",
        "BLOQUEIOS:",
        *([f"- {x}" for x in decision.blockers] or ["- nenhum"]),
        "",
        "ACHADOS:",
        *([f"- {x}" for x in decision.findings] or ["- nenhum"]),
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path}
