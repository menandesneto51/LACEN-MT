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


def check_freshness(
    df: pd.DataFrame,
    source: str,
    *,
    date_candidates: tuple[str, ...] = ("data_corte", "updated_at", "extracted_at", "Data_Liberacao_dt", "Data_Solicitacao_dt"),
    reference_date: datetime | None = None,
    warn_after_days: int | None = None,
    block_after_days: int | None = None,
) -> list[QualityFinding]:
    """Avalia frescor somente quando há coluna temporal e limiares explicitamente configurados."""
    date_col = next((col for col in date_candidates if col in df.columns), None)
    if not date_col:
        return [QualityFinding(
            "DQ_FRESHNESS_DATE_MISSING", QualityStatus.WARN,
            "Frescor não pôde ser calculado: nenhuma coluna temporal configurada está disponível.",
            source=source,
        )]
    dates = pd.to_datetime(df[date_col], errors="coerce")
    if not dates.notna().any():
        return [QualityFinding(
            "DQ_FRESHNESS_DATE_INVALID", QualityStatus.WARN,
            f"Frescor não pôde ser calculado: {date_col} sem datas válidas.",
            source=source,
        )]
    if warn_after_days is None and block_after_days is None:
        return [QualityFinding(
            "DQ_FRESHNESS_UNCONFIGURED", QualityStatus.WARN,
            f"Data mais recente disponível em {date_col}: {dates.max()}; limiar de frescor ainda não configurado.",
            source=source, metric="max_date", value=str(dates.max()),
            action="Definir SLA/frescor por fonte antes de converter este aviso em bloqueio.",
        )]
    ref = reference_date or datetime.now(TZ)
    max_date = dates.max()
    if getattr(max_date, "tzinfo", None) is None:
        max_date = max_date.tz_localize(TZ)
    age_days = max(0, int((ref - max_date.to_pydatetime()).total_seconds() // 86400))
    status = QualityStatus.PASS
    if block_after_days is not None and age_days > block_after_days:
        status = QualityStatus.BLOCK
    elif warn_after_days is not None and age_days > warn_after_days:
        status = QualityStatus.WARN
    return [QualityFinding(
        "DQ_FRESHNESS", status,
        f"Frescor da fonte calculado pela coluna {date_col}.",
        source=source, metric="age_days", value=age_days,
        threshold={"warn_after_days": warn_after_days, "block_after_days": block_after_days},
    )]


def check_completeness(
    df: pd.DataFrame,
    source: str,
    *,
    required_columns: tuple[str, ...],
    warn_below_pct: float | None = None,
    block_below_pct: float | None = None,
) -> list[QualityFinding]:
    """Completude de campos críticos; limiares são de governança e devem ser configurados."""
    findings: list[QualityFinding] = []
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        return [QualityFinding(
            "DQ_COMPLETENESS_SCHEMA", QualityStatus.BLOCK,
            "Campos críticos ausentes: " + ", ".join(missing_cols) + ".",
            source=source, action="Corrigir contrato da fonte antes do consumo downstream.",
        )]
    if df.empty:
        return [QualityFinding(
            "DQ_COMPLETENESS_EMPTY", QualityStatus.WARN,
            "Fonte vazia; completude não é interpretável.",
            source=source,
        )]
    for col in required_columns:
        pct = float(df[col].notna().mean() * 100.0)
        status = QualityStatus.PASS
        if block_below_pct is not None and pct < block_below_pct:
            status = QualityStatus.BLOCK
        elif warn_below_pct is not None and pct < warn_below_pct:
            status = QualityStatus.WARN
        elif warn_below_pct is None and block_below_pct is None and pct < 100.0:
            status = QualityStatus.WARN
        findings.append(QualityFinding(
            f"DQ_COMPLETENESS_{col.upper()}", status,
            f"Completude de {col}: {pct:.1f}%.",
            source=source, metric="completeness_pct", value=round(pct, 2),
            threshold={"warn_below_pct": warn_below_pct, "block_below_pct": block_below_pct},
        ))
    return findings


def check_duplicates(
    df: pd.DataFrame,
    source: str,
    *,
    key_columns: tuple[str, ...] | None = None,
) -> list[QualityFinding]:
    if not key_columns:
        return [QualityFinding(
            "DQ_DUPLICATES_UNCONFIGURED", QualityStatus.WARN,
            "Detecção de duplicidade não executada: chave natural não configurada.",
            source=source,
            action="Definir chave de negócio sem usar identificador nominal de paciente por conveniência.",
        )]
    missing = [col for col in key_columns if col not in df.columns]
    if missing:
        return [QualityFinding(
            "DQ_DUPLICATES_KEY_MISSING", QualityStatus.WARN,
            "Chave de duplicidade parcialmente ausente: " + ", ".join(missing) + ".",
            source=source,
        )]
    dup = int(df.duplicated(list(key_columns), keep=False).sum())
    return [QualityFinding(
        "DQ_DUPLICATES", QualityStatus.WARN if dup else QualityStatus.PASS,
        "Registros duplicados pela chave configurada." if dup else "Sem duplicidade pela chave configurada.",
        source=source, metric="duplicate_rows", value=dup, threshold=0,
    )]


def check_encoding(
    df: pd.DataFrame,
    source: str,
    *,
    columns: tuple[str, ...] | None = None,
) -> list[QualityFinding]:
    suspicious = ("Ã", "Â", "�", "\ufffd")
    cols = list(columns or tuple(c for c in df.columns if df[c].dtype == "object"))
    bad = 0
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col].dropna().astype(str)
        bad += sum(any(token in value for token in suspicious) for value in s)
    return [QualityFinding(
        "DQ_ENCODING", QualityStatus.WARN if bad else QualityStatus.PASS,
        "Possíveis caracteres corrompidos detectados." if bad else "Sem padrão evidente de corrupção de encoding.",
        source=source, metric="suspicious_values", value=int(bad), threshold=0,
        action="Corrigir na camada de normalização sem alterar silenciosamente o dado bruto." if bad else "",
    )]



def check_municipality_ibge(
    df: pd.DataFrame,
    source: str,
    *,
    code_candidates: tuple[str, ...] = ("municipio_ibge", "codigo_ibge", "cod_ibge", "ibge"),
) -> list[QualityFinding]:
    """Valida formato do código IBGE quando a fonte já o disponibiliza."""
    code_col = next((col for col in code_candidates if col in df.columns), None)
    if not code_col:
        return [QualityFinding(
            "DQ_IBGE_CODE_MISSING", QualityStatus.WARN,
            "Código IBGE municipal não disponível; chave territorial canônica ainda não pode ser validada.",
            source=source,
            action="Propagar código IBGE da origem/dimensão territorial; não criar correção nominal hardcoded.",
        )]
    raw = df[code_col]
    normalized = raw.astype("string").str.replace(r"\.0$", "", regex=True).str.strip()
    valid = normalized.str.fullmatch(r"\d{7}", na=False)
    invalid = int((~valid & raw.notna()).sum())
    missing = int(raw.isna().sum())
    status = QualityStatus.WARN if (invalid or missing) else QualityStatus.PASS
    return [QualityFinding(
        "DQ_IBGE_CODE", status,
        "Código IBGE municipal com ausências/formato inválido." if status == QualityStatus.WARN
        else "Código IBGE municipal disponível em formato de 7 dígitos.",
        source=source,
        metric="invalid_or_missing_rows",
        value={"invalid": invalid, "missing": missing, "column": code_col},
        threshold=0,
        action="Resolver via dimensão territorial versionada." if status == QualityStatus.WARN else "",
    )]


def run_quality_gate(
    *,
    weekly: pd.DataFrame | None = None,
    gal_micro: pd.DataFrame | None = None,
    population: pd.DataFrame | None = None,
    analysis_year: int | None = None,
    population_required: bool = False,
    metadata: dict[str, Any] | None = None,
) -> QualityReport:
    findings: list[QualityFinding] = []
    if weekly is not None:
        findings += check_epi_week(weekly, "weekly")
        findings += check_counts(weekly, "weekly")
        findings += check_completeness(
            weekly, "weekly",
            required_columns=("epi_year", "epi_week", "tests", "positives"),
        )
        findings += check_duplicates(
            weekly, "weekly",
            key_columns=tuple(
                c for c in ("epi_year", "epi_week", "municipio", "agravo")
                if c in weekly.columns
            ) or None,
        )
        findings += check_encoding(weekly, "weekly")
        findings += check_municipality_ibge(weekly, "weekly")
    else:
        findings.append(QualityFinding(
            "DQ_WEEKLY_MISSING", QualityStatus.BLOCK,
            "Base semanal não fornecida ao gate.", source="weekly"
        ))
    if gal_micro is not None:
        findings += check_tat(gal_micro, "GAL")
        findings += check_freshness(gal_micro, "GAL")
        findings += check_encoding(gal_micro, "GAL")
    if population is not None:
        findings += check_population(population, "population", analysis_year=analysis_year)
    elif population_required:
        findings.append(QualityFinding(
            "DQ_POPULATION_MISSING", QualityStatus.BLOCK,
            "Denominador populacional obrigatório não fornecido para produto dependente de taxa.",
            source="population",
            action="Fornecer população versionada por município × ano × fonte.",
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
        f"pipeline: {report.metadata.get('pipeline', '—')}",
        f"fonte_dados: {report.metadata.get('fonte_dados', '—')}",
        f"extraido_em: {report.metadata.get('extracted_at', '—')}",
        f"se_esperada: {report.metadata.get('se_esperada', '—')}",
        f"fontes_extraidas: {report.metadata.get('sources_extracted', [])}",
        "",
    ]
    for f in report.findings:
        lines.append(f"[{f.status.value}] {f.check_id} — {f.message}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path
