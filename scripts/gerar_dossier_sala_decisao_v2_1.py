# -*- coding: utf-8 -*-
"""Dossie unico para sala de decisao institucional — LACEN-MT V2.1.

Consolida evidencias DEC-001/DEC-002 sem selecionar alternativa nem aprovar.
Uso:
  python scripts/gerar_dossier_sala_decisao_v2_1.py --quality-dir saida_pipeline/quality
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Cuiaba")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return f"(ausente: {path.name})"
    text = path.read_text(encoding="utf-8")
    if limit is not None and len(text) > limit:
        return text[:limit] + "\n\n…(truncado)\n"
    return text


def build_dossier(quality_dir: Path) -> str:
    q = Path(quality_dir)
    readiness = _load_json(q / "decision_readiness_v2_1.json")
    registry = _load_json(q / "decision_status_registry_v2_1.json")
    temporal = _load_json(q / "gal_temporal_anchor_summary.json")
    pop = _load_json(q / "population_source_comparison_summary.json")
    meta = _load_json(q / "evidence_collection_meta.json")

    decs = readiness.get("decisions") or {}
    d1 = decs.get("DEC-001") or {}
    d2 = decs.get("DEC-002") or {}

    lines = [
        "# Dossie — Sala de Decisao LACEN-MT V2.1",
        "",
        f"Gerado em: {datetime.now(TZ).isoformat(timespec='seconds')}",
        "**Decisao automatica: proibida.** Este dossie nao escolhe A/B/C/D nem aprova fontes populacionais.",
        "",
        "## Painel de status",
        "",
        f"- Decision Readiness geral: `{readiness.get('overall_status', '—')}`",
        f"- DEC-001 (ancora temporal GAL): `{d1.get('status', '—')}`",
        f"- DEC-002 (fontes populacionais): `{d2.get('status', '—')}`",
        f"- Decision Registry: `{registry.get('overall_status', '—')}`",
        "- Parecer Clinical/Epidemiological Specialist: permanece **BLOCK** ate DEC-001 assinada",
        "- Parecer Security/Data Governance: permanece **WARN** ate DEC-002/politica aprovada",
        "",
        "## Como decidir",
        "",
        "1. Abrir `docs/decisions/DEC-001-ancora-temporal-gal.md` e marcar A/B/C/D + assinaturas.",
        "2. Abrir `docs/decisions/DEC-002-prioridade-fontes-populacionais.md` e definir `source_priority`.",
        "3. Atualizar `config/decision_status_v2_1.json` para `APPROVED` somente apos assinatura.",
        "4. Reexecutar Promotion Gate / pareceres; so entao avaliar saida do technical freeze.",
        "",
        "## DEC-001 — fatos quantitativos",
        "",
        f"- Registros: {temporal.get('rows_total')}",
        f"- Ambas as datas: {temporal.get('rows_both_dates')}",
        f"- Cobertura solicitacao: {temporal.get('coverage_solicitacao')}",
        f"- Cobertura coleta: {temporal.get('coverage_coleta')}",
        f"- Mediana atraso (dias): {temporal.get('median_delay_days')}",
        f"- P90 atraso (dias): {temporal.get('p90_delay_days')}",
        f"- Mudam de SE: {temporal.get('changed_epi_week_rows')} ({temporal.get('changed_epi_week_pct')})",
        f"- Mudam de ano epidemiologico: {temporal.get('changed_epi_year_rows')} ({temporal.get('changed_epi_year_pct')})",
        f"- Semanas com delta: {temporal.get('weeks_with_count_delta')} / {temporal.get('weeks_compared')}",
        f"- Maior |delta| semanal: {temporal.get('max_absolute_weekly_count_diff')}",
        "",
        "Pacote completo: `DEC-001_evidence_packet.md`",
        "Brief: `decision_brief_DEC-001.md`",
        "",
        "## DEC-002 — fatos quantitativos",
        "",
        f"- Ano de analise: {pop.get('analysis_year')}",
        f"- Fontes: {pop.get('sources')}",
        f"- Territorios: {pop.get('territories_total')}",
        f"- Com multiplas fontes: {pop.get('territories_with_multiple_sources')}",
        f"- Com divergencia: {pop.get('territories_with_any_difference')}",
        f"- Cobertura: {pop.get('source_coverage')}",
        "",
        "Pacote completo: `DEC-002_evidence_packet.md`",
        "Brief: `decision_brief_DEC-002.md`",
        "",
        "## Notas tecnicas da coleta",
        "",
    ]
    for note in meta.get("notes") or []:
        lines.append(f"- {note}")
    if not meta.get("notes"):
        lines.append("- (sem meta adicional)")

    lines += [
        "",
        "## Anexos (trechos)",
        "",
        "### decision_brief_DEC-001.md",
        "",
        "```markdown",
        _read(q / "decision_brief_DEC-001.md", limit=2500),
        "```",
        "",
        "### decision_brief_DEC-002.md",
        "",
        "```markdown",
        _read(q / "decision_brief_DEC-002.md", limit=2500),
        "```",
        "",
        "---",
        "",
        "Fim do dossie. Nenhuma decisao foi tomada por este script.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gera dossie da sala de decisao V2.1")
    ap.add_argument(
        "--quality-dir",
        type=Path,
        default=Path("saida_pipeline") / "quality",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Padrao: <quality-dir>/dossier_sala_decisao_v2_1.md",
    )
    args = ap.parse_args(argv)
    q = args.quality_dir
    out = args.out or (q / "dossier_sala_decisao_v2_1.md")
    q.mkdir(parents=True, exist_ok=True)
    text = build_dossier(q)
    out.write_text(text, encoding="utf-8")
    print(f"Dossie gerado: {out}")
    print(f"Readiness: {(_load_json(q / 'decision_readiness_v2_1.json')).get('overall_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
