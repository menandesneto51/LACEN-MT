# -*- coding: utf-8 -*-
"""Decision briefs executivos — LACEN-MT V2.1.

Gera resumos de 1 página a partir dos artefatos reais do ETL.
Não toma decisão nem altera configuração automaticamente.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_temporal_anchor_brief(quality_dir: Path | str) -> dict[str, Any]:
    q = Path(quality_dir)
    s = _load(q / "gal_temporal_anchor_summary.json")

    evidence = {
        "rows_total": s.get("rows_total"),
        "rows_both_dates": s.get("rows_both_dates"),
        "coverage_solicitacao": s.get("coverage_solicitacao"),
        "coverage_coleta": s.get("coverage_coleta"),
        "median_delay_days": s.get("median_delay_days"),
        "p90_delay_days": s.get("p90_delay_days"),
        "changed_epi_week_rows": s.get("changed_epi_week_rows"),
        "changed_epi_week_pct": s.get("changed_epi_week_pct"),
        "changed_epi_year_rows": s.get("changed_epi_year_rows"),
        "changed_epi_year_pct": s.get("changed_epi_year_pct"),
        "weeks_compared": s.get("weeks_compared"),
        "weeks_with_count_delta": s.get("weeks_with_count_delta"),
        "weeks_with_count_delta_pct": s.get("weeks_with_count_delta_pct"),
        "max_absolute_weekly_count_diff": s.get("max_absolute_weekly_count_diff"),
        "sum_absolute_weekly_count_diff": s.get("sum_absolute_weekly_count_diff"),
    }

    missing = [k for k, v in evidence.items() if v is None]
    return {
        "decision_id": "DEC-001",
        "title": "Âncora temporal GAL — solicitação × coleta",
        "status": "PENDING",
        "decision_required": True,
        "facts": evidence,
        "missing_evidence": missing,
        "options": [
            {
                "id": "A",
                "label": "Solicitação como âncora única",
                "implications": [
                    "Preserva comportamento atual.",
                    "Mantém comparabilidade histórica existente.",
                    "Pode refletir atraso administrativo em relação à coleta.",
                ],
            },
            {
                "id": "B",
                "label": "Coleta como âncora única",
                "implications": [
                    "Aproxima o evento da obtenção da amostra.",
                    "Pode alterar semana epidemiológica, baseline e alertas.",
                    "Exige avaliação de completude e reprocessamento histórico.",
                ],
            },
            {
                "id": "C",
                "label": "Âncoras distintas por finalidade",
                "implications": [
                    "Permite coleta para produtos epidemiológicos e solicitação para fluxo operacional.",
                    "Exige nomenclatura e governança explícitas.",
                    "Aumenta complexidade de comparação entre produtos.",
                ],
            },
            {
                "id": "D",
                "label": "Manter regra atual temporariamente",
                "implications": [
                    "Não muda a série agora.",
                    "Mantém o BLOCK de promoção até nova decisão.",
                    "Permite acumular evidência adicional.",
                ],
            },
        ],
        "decision": None,
        "approvals_required": [
            "Clinical/Epidemiological Specialist",
            "Chief Architect",
            "Data Governance",
            "Responsável institucional pelo produto",
        ],
        "automatic_decision_allowed": False,
    }


def build_population_source_brief(quality_dir: Path | str) -> dict[str, Any]:
    q = Path(quality_dir)
    comparison = _load(q / "population_source_comparison_summary.json")
    governance = _load(q / "population_governance_v2_1.json")

    return {
        "decision_id": "DEC-002",
        "title": "Prioridade institucional das fontes populacionais",
        "status": "PENDING",
        "decision_required": True,
        "facts": {
            "analysis_year": comparison.get("analysis_year"),
            "sources": comparison.get("sources"),
            "territories_total": comparison.get("territories_total"),
            "territories_with_multiple_sources": comparison.get("territories_with_multiple_sources"),
            "territories_with_any_difference": comparison.get("territories_with_any_difference"),
            "max_absolute_difference": comparison.get("max_absolute_difference"),
            "max_relative_difference": comparison.get("max_relative_difference"),
            "source_coverage": comparison.get("source_coverage"),
            "governance_status": governance.get("status"),
            "governance_approved": governance.get("approved"),
            "governance_blockers": governance.get("blockers"),
            "current_source_priority": governance.get("source_priority"),
        },
        "criteria": [
            "Cobertura territorial",
            "Ano de referência",
            "Consistência interna",
            "Rastreabilidade e versionamento",
            "Aderência ao uso epidemiológico",
            "Disponibilidade futura",
            "Governança institucional",
        ],
        "decision": {
            "source_priority": None,
            "allow_previous_year": None,
            "allow_unlisted_sources": None,
        },
        "approvals_required": [
            "Security/Data Governance",
            "Data Architect",
            "Epidemiologia",
            "Responsável institucional pelo produto",
        ],
        "automatic_decision_allowed": False,
    }


def _format_percent(value: Any) -> str:
    try:
        return f"{100.0 * float(value):.2f}%"
    except Exception:
        return "—"


def write_decision_briefs(quality_dir: Path | str) -> dict[str, Path]:
    q = Path(quality_dir)
    q.mkdir(parents=True, exist_ok=True)

    temporal = build_temporal_anchor_brief(q)
    population = build_population_source_brief(q)

    temporal_json = q / "decision_brief_DEC-001.json"
    temporal_md = q / "decision_brief_DEC-001.md"
    population_json = q / "decision_brief_DEC-002.json"
    population_md = q / "decision_brief_DEC-002.md"

    temporal_json.write_text(json.dumps(temporal, ensure_ascii=False, indent=2), encoding="utf-8")
    population_json.write_text(json.dumps(population, ensure_ascii=False, indent=2), encoding="utf-8")

    f = temporal["facts"]
    temporal_lines = [
        "# DEC-001 — Âncora temporal GAL",
        "",
        "**Status:** PENDENTE  ",
        "**Decisão automática:** proibida",
        "",
        "## Evidência disponível",
        f"- Registros analisados: {f.get('rows_total')}",
        f"- Com ambas as datas: {f.get('rows_both_dates')}",
        f"- Cobertura solicitação: {_format_percent(f.get('coverage_solicitacao'))}",
        f"- Cobertura coleta: {_format_percent(f.get('coverage_coleta'))}",
        f"- Mediana atraso solicitação−coleta: {f.get('median_delay_days')} dias",
        f"- P90 atraso: {f.get('p90_delay_days')} dias",
        f"- Mudam de SE: {f.get('changed_epi_week_rows')} ({_format_percent(f.get('changed_epi_week_pct'))})",
        f"- Mudam de ano epidemiológico: {f.get('changed_epi_year_rows')} ({_format_percent(f.get('changed_epi_year_pct'))})",
        f"- Semanas comparadas: {f.get('weeks_compared')}",
        f"- Semanas com diferença de contagem: {f.get('weeks_with_count_delta')} ({_format_percent(f.get('weeks_with_count_delta_pct'))})",
        f"- Maior diferença absoluta semanal: {f.get('max_absolute_weekly_count_diff')}",
        f"- Soma das diferenças absolutas semanais: {f.get('sum_absolute_weekly_count_diff')}",
        "",
        "## Opções para decisão",
    ]
    for option in temporal["options"]:
        temporal_lines.append(f"### {option['id']} — {option['label']}")
        temporal_lines += [f"- {x}" for x in option["implications"]]
    temporal_lines += [
        "",
        "## Decisão institucional",
        "- Alternativa escolhida: **PENDENTE**",
        "- Fundamentação: **PENDENTE**",
        "- Tratamento da série histórica: **PENDENTE**",
        "",
        "Este brief informa a decisão; não seleciona automaticamente uma alternativa.",
    ]
    temporal_md.write_text("\n".join(temporal_lines) + "\n", encoding="utf-8")

    p = population["facts"]
    population_lines = [
        "# DEC-002 — Prioridade das fontes populacionais",
        "",
        "**Status:** PENDENTE  ",
        "**Decisão automática:** proibida",
        "",
        "## Evidência disponível",
        f"- Ano de análise: {p.get('analysis_year')}",
        f"- Fontes disponíveis: {p.get('sources')}",
        f"- Territórios avaliados: {p.get('territories_total')}",
        f"- Territórios com múltiplas fontes: {p.get('territories_with_multiple_sources')}",
        f"- Territórios com divergência: {p.get('territories_with_any_difference')}",
        f"- Maior diferença absoluta: {p.get('max_absolute_difference')}",
        f"- Maior diferença relativa: {_format_percent(p.get('max_relative_difference'))}",
        f"- Cobertura por fonte: {p.get('source_coverage')}",
        f"- Política atual: {p.get('governance_status')}",
        f"- Política aprovada: {p.get('governance_approved')}",
        "",
        "## Critérios para decisão",
        *[f"- {x}" for x in population["criteria"]],
        "",
        "## Decisão institucional",
        "- Prioridade aprovada: **PENDENTE**",
        "- Fallback temporal: **PENDENTE**",
        "- Uso de fontes não listadas: **PENDENTE**",
        "",
        "Este brief informa a decisão; não escolhe automaticamente uma fonte.",
    ]
    population_md.write_text("\n".join(population_lines) + "\n", encoding="utf-8")

    return {
        "temporal_json": temporal_json,
        "temporal_markdown": temporal_md,
        "population_json": population_json,
        "population_markdown": population_md,
    }
