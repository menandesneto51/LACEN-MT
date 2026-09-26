import pandas as pd

from quality.territorial_reconciliation import (
    apply_resolution,
    build_reconciliation_report,
    merge_resolution_state,
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


def test_issue_id_is_stable_for_same_occurrence():
    a = build_reconciliation_report(_investigation("CONFLITO"))
    b = build_reconciliation_report(_investigation("CONFLITO"))
    assert a.loc[0, "issue_id"] == b.loc[0, "issue_id"]
    assert a.loc[0, "issue_id"].startswith("TR-")


def test_apply_resolution_tracks_lifecycle_and_close_time():
    report = build_reconciliation_report(_investigation("CONFLITO"))
    issue_id = report.loc[0, "issue_id"]
    report = merge_resolution_state(report, None, now="2026-09-26T18:00:00")
    updated = apply_resolution(
        report,
        issue_id,
        estado="FECHADO",
        responsavel="Data Governance",
        decisao="Código IBGE corrigido na origem.",
        evidencia="ticket-123",
        correcao_aplicada="Atualização da dimensão territorial.",
        validacao_pos_correcao="Paridade reexecutada sem conflito.",
        now="2026-09-26T19:00:00",
    )
    assert updated.loc[0, "estado_reconciliacao"] == "FECHADO"
    assert updated.loc[0, "responsavel_atual"] == "Data Governance"
    assert updated.loc[0, "data_fechamento"] == "2026-09-26T19:00:00"


def test_merge_resolution_state_preserves_previous_human_decision():
    current = build_reconciliation_report(_investigation("CONFLITO"))
    current = merge_resolution_state(current, None, now="2026-09-26T18:00:00")
    issue_id = current.loc[0, "issue_id"]
    previous = apply_resolution(
        current,
        issue_id,
        estado="EM_ANALISE",
        responsavel="VE",
        decisao="Aguardando correção na origem.",
        now="2026-09-26T18:30:00",
    )
    refreshed = build_reconciliation_report(_investigation("CONFLITO"))
    merged = merge_resolution_state(
        refreshed,
        previous,
        now="2026-09-26T19:00:00",
    )
    assert merged.loc[0, "estado_reconciliacao"] == "EM_ANALISE"
    assert merged.loc[0, "responsavel_atual"] == "VE"
    assert merged.loc[0, "decisao"] == "Aguardando correção na origem."


def test_invalid_resolution_state_is_rejected():
    report = build_reconciliation_report(_investigation("CONFLITO"))
    issue_id = report.loc[0, "issue_id"]
    report = merge_resolution_state(report, None)
    try:
        apply_resolution(report, issue_id, estado="AUTO_FECHADO")
    except ValueError:
        pass
    else:
        raise AssertionError("estado inválido deveria gerar ValueError")
