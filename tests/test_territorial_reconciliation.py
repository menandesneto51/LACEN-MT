import pandas as pd

from quality.territorial_reconciliation import (
    build_reconciliation_report,
    summarize_reconciliation,
    write_reconciliation_report,
)


def _investigation(status="CONFLITO", source="GALxSINAN"):
    return pd.DataFrame({
        "fonte_linkage": [source],
        "linkage_parity": [status],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "legacy_match_value": [2],
        "v2_match_value": [5],
    })


def test_conflict_becomes_critical_reconciliation_item():
    report = build_reconciliation_report(_investigation("CONFLITO"))
    assert report.loc[0, "prioridade"] == "CRITICA"
    assert report.loc[0, "estado_reconciliacao"] == "ABERTO"
    assert "Vigilância Epidemiológica" in report.loc[0, "responsavel_sugerido"]


def test_lost_by_ibge_becomes_high_priority():
    report = build_reconciliation_report(_investigation("PERDIDO_COM_IBGE", "GALxSIM"))
    assert report.loc[0, "prioridade"] == "ALTA"
    assert "Vigilância do Óbito" in report.loc[0, "responsavel_sugerido"]


def test_no_match_is_moderate_not_critical():
    report = build_reconciliation_report(_investigation("SEM_MATCH", "GALxSIH"))
    assert report.loc[0, "prioridade"] == "MODERADA"
    assert "Inteligência Assistencial" in report.loc[0, "responsavel_sugerido"]


def test_reconciliation_summary_blocks_promotion_when_high_or_critical():
    report = build_reconciliation_report(pd.concat([
        _investigation("SEM_MATCH"),
        _investigation("CONFLITO"),
    ], ignore_index=True))
    summary = summarize_reconciliation(report)
    assert summary["open_items"] == 2
    assert summary["critical"] == 1
    assert summary["promotion_ready"] is False


def test_empty_reconciliation_is_promotion_ready():
    report = build_reconciliation_report(pd.DataFrame())
    summary = summarize_reconciliation(report)
    assert summary["open_items"] == 0
    assert summary["promotion_ready"] is True


def test_reconciliation_writes_artifacts(tmp_path):
    report = build_reconciliation_report(_investigation("CONFLITO"))
    paths = write_reconciliation_report(report, tmp_path)
    assert paths["csv"].exists()
    assert paths["json"].exists()
    assert paths["txt"].exists()
