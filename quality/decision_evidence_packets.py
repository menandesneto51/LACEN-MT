# -*- coding: utf-8 -*-
"""Pacotes de evidencia para decisoes institucionais — LACEN-MT V2.1.

Preenche DEC-001/DEC-002 com fatos quantitativos dos artefatos do ETL.
Nunca marca alternativa, nunca aprova, nunca altera a ancora temporal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("America/Cuiaba")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fmt(value: Any, *, pct: bool = False) -> str:
    if value is None:
        return "—"
    if pct:
        try:
            return f"{float(value) * 100:.1f}%".replace(".", ",")
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, float):
        return f"{value:.2f}".replace(".", ",")
    return str(value)


def _impact_proxy(summary: dict[str, Any], weekly_path: Path) -> str:
    weeks_delta = summary.get("weeks_with_count_delta")
    weeks = summary.get("weeks_compared")
    max_diff = summary.get("max_absolute_weekly_count_diff")
    sum_diff = summary.get("sum_absolute_weekly_count_diff")
    parts = [
        "Proxy tecnico (nao substitui analise de baseline/alerta):",
        f"semanas com diferenca agregada = {_fmt(weeks_delta)} de {_fmt(weeks)};",
        f"maior |delta| semanal = {_fmt(max_diff)};",
        f"soma |delta| = {_fmt(sum_diff)}.",
    ]
    if weekly_path.exists():
        try:
            df = pd.read_csv(weekly_path)
            if not df.empty and "abs_diff" in df.columns:
                top = df.sort_values("abs_diff", ascending=False).head(3)
                rows = [
                    f"{int(r.epi_year)}-SE{int(r.epi_week):02d} (|delta|={int(r.abs_diff)})"
                    for r in top.itertuples()
                ]
                parts.append("Top semanas por |delta|: " + "; ".join(rows) + ".")
        except Exception:
            pass
    parts.append(
        "Impacto direto em baseline/anomalia/alerta: nao recalculado nesta remessa "
        "(requer reprocessamento paralelo sob a ancora alternativa)."
    )
    return " ".join(parts)


def build_dec001_evidence_packet(
    quality_dir: Path | str, *, template_path: Path | str | None = None
) -> str:
    q = Path(quality_dir)
    summary = _load_json(q / "gal_temporal_anchor_summary.json")
    weekly = q / "gal_temporal_anchor_weekly_comparison.csv"
    brief = _load_json(q / "decision_brief_DEC-001.json")
    tpl = Path(template_path) if template_path else (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "decisions"
        / "DEC-001-ancora-temporal-gal.md"
    )
    template = tpl.read_text(encoding="utf-8") if tpl.exists() else ""

    evidence_block = f"""## Evidencias preenchidas automaticamente (somente leitura)

Gerado em: {datetime.now(TZ).isoformat(timespec="seconds")}
Fonte: `gal_temporal_anchor_summary.json` + comparacao semanal.
**Este pacote NAO escolhe alternativa A/B/C/D e NAO remove o BLOCK epidemiologico.**

- Cobertura Data de Solicitacao: {_fmt(summary.get("coverage_solicitacao"), pct=True)}
- Cobertura Data da Coleta: {_fmt(summary.get("coverage_coleta"), pct=True)}
- Registros totais: {_fmt(summary.get("rows_total"))}
- Registros com ambas as datas: {_fmt(summary.get("rows_both_dates"))}
- Mediana atraso solicitacao-coleta: {_fmt(summary.get("median_delay_days"))} dias
- P90 atraso solicitacao-coleta: {_fmt(summary.get("p90_delay_days"))} dias
- Registros que mudam de SE: {_fmt(summary.get("changed_epi_week_rows"))} ({_fmt(summary.get("changed_epi_week_pct"), pct=True)})
- Registros que mudam de ano epidemiologico: {_fmt(summary.get("changed_epi_year_rows"))} ({_fmt(summary.get("changed_epi_year_pct"), pct=True)})
- Semanas com diferencas agregadas: {_fmt(summary.get("weeks_with_count_delta"))} de {_fmt(summary.get("weeks_compared"))} ({_fmt(summary.get("weeks_with_count_delta_pct"), pct=True)})
- Maior diferenca absoluta semanal: {_fmt(summary.get("max_absolute_weekly_count_diff"))}
- Soma das diferencas absolutas semanais: {_fmt(summary.get("sum_absolute_weekly_count_diff"))}
- Impacto observado em baseline/anomalia/alerta: {_impact_proxy(summary, weekly)}

### Opcoes (ainda nao decididas)

"""
    for opt in brief.get("options") or []:
        evidence_block += f"- [ ] {opt.get('id')} — {opt.get('label')}\n"

    evidence_block += """
### Status da decisao

- Status institucional: PENDENTE
- Decisao automatica: proibida
- Criterio para remover BLOCK: preencher e validar `docs/decisions/DEC-001-ancora-temporal-gal.md` + teste de regressao do comportamento escolhido.
"""

    header = "# Pacote de evidencia — DEC-001 (preenchimento tecnico)\n\n"
    note = (
        "> Copia de trabalho para a sala de decisao. O documento institucional "
        "permanece em `docs/decisions/DEC-001-ancora-temporal-gal.md` ate assinatura humana.\n\n"
    )
    return header + note + evidence_block + "\n---\n\n## Modelo institucional (referencia)\n\n" + template


def build_dec002_evidence_packet(
    quality_dir: Path | str, *, template_path: Path | str | None = None
) -> str:
    q = Path(quality_dir)
    summary = _load_json(q / "population_source_comparison_summary.json")
    gov = _load_json(q / "population_governance_v2_1.json")
    if not gov:
        root_gov = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "population_governance_v2_1.json"
        )
        gov = _load_json(root_gov)
    tpl = Path(template_path) if template_path else (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "decisions"
        / "DEC-002-prioridade-fontes-populacionais.md"
    )
    template = tpl.read_text(encoding="utf-8") if tpl.exists() else ""

    sources = summary.get("sources") or []
    coverage = summary.get("source_coverage") or {}
    cov_lines: list[str] = []
    if isinstance(coverage, dict):
        for src, val in coverage.items():
            if isinstance(val, float) and val <= 1:
                cov_lines.append(f"  - {src}: {_fmt(val, pct=True)}")
            else:
                cov_lines.append(f"  - {src}: {_fmt(val)}")
    elif isinstance(coverage, list):
        for item in coverage:
            cov_lines.append(f"  - {item}")

    rel = summary.get("max_relative_difference")
    if isinstance(rel, (int, float)) and float(rel) <= 1:
        rel_txt = _fmt(rel, pct=True)
    else:
        rel_txt = _fmt(rel)

    body = f"""## Evidencias preenchidas automaticamente (somente leitura)

Gerado em: {datetime.now(TZ).isoformat(timespec="seconds")}
Fonte: `population_source_comparison_summary.json` + `population_governance_v2_1.json`.
**Este pacote NAO aprova prioridade populacional e NAO altera denominadores legados.**

- Ano de analise: {_fmt(summary.get("analysis_year"))}
- Fontes observadas: {", ".join(map(str, sources)) if sources else "—"}
- Territorios totais: {_fmt(summary.get("territories_total"))}
- Territorios com multiplas fontes: {_fmt(summary.get("territories_with_multiple_sources"))}
- Territorios com qualquer diferenca: {_fmt(summary.get("territories_with_any_difference"))}
- Maior diferenca absoluta: {_fmt(summary.get("max_absolute_difference"))}
- Maior diferenca relativa: {rel_txt}
- Cobertura por fonte:
{chr(10).join(cov_lines) if cov_lines else "  - —"}
- Status da governanca versionada: {_fmt(gov.get("status"))}
- Aprovada?: {_fmt(gov.get("approved"))}
- Prioridade atual configurada: {_fmt(gov.get("source_priority"))}
- Bloqueios de governanca: {", ".join(map(str, gov.get("blockers") or [])) or "—"}

### Status da decisao

- Status institucional: PENDENTE
- Decisao automatica: proibida
- Enquanto nao aprovado: denominador V2 permanece ausente quando houver ambiguidade de fontes.
"""
    header = "# Pacote de evidencia — DEC-002 (preenchimento tecnico)\n\n"
    note = (
        "> Copia de trabalho para a sala de decisao. O documento institucional "
        "permanece em `docs/decisions/DEC-002-prioridade-fontes-populacionais.md` ate assinatura humana.\n\n"
    )
    return header + note + body + "\n---\n\n## Modelo institucional (referencia)\n\n" + template


def write_decision_evidence_packets(quality_dir: Path | str) -> dict[str, Path]:
    q = Path(quality_dir)
    q.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    p1 = q / "DEC-001_evidence_packet.md"
    p1.write_text(build_dec001_evidence_packet(q), encoding="utf-8")
    out["dec001"] = p1
    p2 = q / "DEC-002_evidence_packet.md"
    p2.write_text(build_dec002_evidence_packet(q), encoding="utf-8")
    out["dec002"] = p2
    meta = {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "automatic_decision_allowed": False,
        "packets": {k: v.name for k, v in out.items()},
    }
    meta_path = q / "decision_evidence_packets_meta.json"
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    out["meta"] = meta_path
    return out
