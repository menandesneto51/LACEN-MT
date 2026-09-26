# -*- coding: utf-8 -*-
"""Data Quality Agent — gate de confiabilidade do LACEN-MT V2.

Este módulo não interpreta surtos nem altera regras epidemiológicas.
Ele avalia se os dados estão aptos para alimentar cálculo, alerta, ML e relatório.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("America/Cuiaba")


class QualityStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class QualityFinding:
    check_id: str
    status: QualityStatus
    message: str
    source: str = ""
    metric: str = ""
    value: Any = None
    threshold: Any = None
    action: str = ""


@dataclass
class QualityReport:
    generated_at: str
    status: QualityStatus
    findings: list[QualityFinding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def publishable(self) -> bool:
        return self.status != QualityStatus.BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "status": self.status.value,
            "publishable": self.publishable,
            "metadata": self.metadata,
            "findings": [
                {**asdict(f), "status": f.status.value} for f in self.findings
            ],
        }


def _worst(findings: Iterable[QualityFinding]) -> QualityStatus:
    statuses = {f.status for f in findings}
    if QualityStatus.BLOCK in statuses:
        return QualityStatus.BLOCK
    if QualityStatus.WARN in statuses:
        return QualityStatus.WARN
    return QualityStatus.PASS


def check_epi_week(df: pd.DataFrame, source: str) -> list[QualityFinding]:
    out: list[QualityFinding] = []
    required = {"epi_year", "epi_week"}
    missing = sorted(required - set(df.columns))
    if missing:
        return [QualityFinding(
            "DQ_SCHEMA_EPI_WEEK", QualityStatus.BLOCK,
            f"Colunas epidemiológicas ausentes: {', '.join(missing)}.",
            source=source, action="Corrigir contrato da fonte antes da publicação."
        )]
    y = pd.to_numeric(df["epi_year"], errors="coerce")
    w = pd.to_numeric(df["epi_week"], errors="coerce")
    invalid = int((y.isna() | w.isna() | ~w.between(1, 53)).sum())
    out.append(QualityFinding(
        "DQ_EPI_WEEK_RANGE",
        QualityStatus.BLOCK if invalid else QualityStatus.PASS,
        "Ano/SE inválidos detectados." if invalid else "Ano/SE dentro do domínio esperado.",
        source=source, metric="invalid_rows", value=invalid, threshold=0,
        action="Recalcular a SE pela âncora temporal oficial." if invalid else "",
    ))
    return out


def check_counts(df: pd.DataFrame, source: str) -> list[QualityFinding]:
    out: list[QualityFinding] = []
    for col in ("tests", "positives"):
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        invalid = int((s < 0).fillna(False).sum())
        out.append(QualityFinding(
            f"DQ_NEGATIVE_{col.upper()}",
            QualityStatus.BLOCK if invalid else QualityStatus.PASS,
            f"{col}: valores negativos detectados." if invalid else f"{col}: sem valores negativos.",
            source=source, metric="invalid_rows", value=invalid, threshold=0,
        ))
    if {"tests", "positives"}.issubset(df.columns):
        tests = pd.to_numeric(df["tests"], errors="coerce")
        pos = pd.to_numeric(df["positives"], errors="coerce")
        invalid = int((pos > tests).fillna(False).sum())
        out.append(QualityFinding(
            "DQ_POSITIVES_GT_TESTS",
            QualityStatus.BLOCK if invalid else QualityStatus.PASS,
            "Positivos maiores que exames válidos." if invalid else "Positivos compatíveis com exames.",
            source=source, metric="invalid_rows", value=invalid, threshold=0,
        ))
    return out


def check_population(
    df: pd.DataFrame,
    source: str,
    *,
    analysis_year: int | None = None,
    max_age_years: int = 2,
) -> list[QualityFinding]:
    year_col = next((c for c in ("ano", "year", "ano_populacao") if c in df.columns), None)
    pop_col = next((c for c in ("populacao", "population", "pop") if c in df.columns), None)
    findings: list[QualityFinding] = []
    if not year_col:
        return [QualityFinding(
            "DQ_POPULATION_YEAR_MISSING", QualityStatus.BLOCK,
            "Fonte populacional sem ano explícito.", source=source,
            action="Versionar população por município × ano × fonte."
        )]
    years = pd.to_numeric(df[year_col], errors="coerce")
    invalid_year = int(years.isna().sum())
    findings.append(QualityFinding(
        "DQ_POPULATION_YEAR_VALID",
        QualityStatus.BLOCK if invalid_year else QualityStatus.PASS,
        "Ano populacional inválido." if invalid_year else "Ano populacional explícito.",
        source=source, value=invalid_year, threshold=0,
    ))
    if analysis_year is not None and years.notna().any():
        newest = int(years.dropna().max())
        age = analysis_year - newest
        findings.append(QualityFinding(
            "DQ_POPULATION_FRESHNESS",
            QualityStatus.BLOCK if age > max_age_years else (QualityStatus.WARN if age > 0 else QualityStatus.PASS),
            f"Denominador populacional mais recente: {newest}; análise: {analysis_year}.",
            source=source, metric="age_years", value=age, threshold=max_age_years,
            action="Usar fonte populacional compatível com o período ou documentar fallback." if age else "",
        ))
    if pop_col:
        pop = pd.to_numeric(df[pop_col], errors="coerce")
        invalid_pop = int((pop.isna() | (pop <= 0)).sum())
        findings.append(QualityFinding(
            "DQ_POPULATION_VALUE",
            QualityStatus.BLOCK if invalid_pop else QualityStatus.PASS,
            "População ausente/não positiva." if invalid_pop else "Valores populacionais positivos.",
            source=source, value=invalid_pop, threshold=0,
        ))
    return findings


def check_tat(
    df: pd.DataFrame,
    source: str,
    *,
    received_col: str = "Data_Recebimento_dt",
    released_col: str = "Data_Liberacao_dt",
    extreme_days: float = 90.0,
) -> list[QualityFinding]:
    if received_col not in df.columns or released_col not in df.columns:
        return [QualityFinding(
            "DQ_TAT_COLUMNS", QualityStatus.WARN,
            "TAT não pôde ser auditado: timestamps de recebimento/liberação indisponíveis.",
            source=source,
        )]
    received = pd.to_datetime(df[received_col], errors="coerce")
    released = pd.to_datetime(df[released_col], errors="coerce")
    tat = (released - received).dt.total_seconds() / 86400.0
    negative = int((tat < 0).fillna(False).sum())
    extreme = int((tat > extreme_days).fillna(False).sum())
    return [
        QualityFinding(
            "DQ_TAT_NEGATIVE", QualityStatus.BLOCK if negative else QualityStatus.PASS,
            "TAT negativo detectado." if negative else "Sem TAT negativo.",
            source=source, value=negative, threshold=0,
        ),
        QualityFinding(
            "DQ_TAT_EXTREME", QualityStatus.WARN if extreme else QualityStatus.PASS,
            f"TAT acima de {extreme_days:g} dias requer auditoria." if extreme else "Sem TAT extremo pelo limiar configurado.",
            source=source, value=extreme, threshold=extreme_days,
            action="Estratificar outliers por agravo, status, laboratório e datas de origem." if extreme else "",
        ),
    ]


def run_quality_gate(
    *,
    weekly: pd.DataFrame | None = None,
    gal_micro: pd.DataFrame | None = None,
    population: pd.DataFrame | None = None,
    analysis_year: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> QualityReport:
    findings: list[QualityFinding] = []
    if weekly is not None:
        findings += check_epi_week(weekly, "weekly")
        findings += check_counts(weekly, "weekly")
    else:
        findings.append(QualityFinding(
            "DQ_WEEKLY_MISSING", QualityStatus.BLOCK,
            "Base semanal não fornecida ao gate.", source="weekly"
        ))
    if gal_micro is not None:
        findings += check_tat(gal_micro, "GAL")
    if population is not None:
        findings += check_population(population, "population", analysis_year=analysis_year)
    elif analysis_year is not None:
        findings.append(QualityFinding(
            "DQ_POPULATION_MISSING", QualityStatus.BLOCK,
            "Denominador populacional não fornecido para análise de taxas.",
            source="population"
        ))
    return QualityReport(
        generated_at=datetime.now(TZ).isoformat(timespec="seconds"),
        status=_worst(findings),
        findings=findings,
        metadata=metadata or {},
    )


def write_report(report: QualityReport, outdir: Path | str) -> tuple[Path, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "data_quality_gate_ultimo.json"
    txt_path = out / "data_quality_gate_ultimo.txt"
    payload = report.to_dict()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "LACEN-MT V2 — DATA QUALITY GATE",
        f"gerado_em: {report.generated_at}",
        f"status: {report.status.value}",
        f"publicavel: {str(report.publishable).lower()}",
        "",
    ]
    for f in report.findings:
        lines.append(f"[{f.status.value}] {f.check_id} — {f.message}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path
