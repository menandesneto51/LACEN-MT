import pandas as pd
import pytest

from quality.risk_action_management import (
    build_action_register,
    build_risk_register,
    summarize_risk_management,
    update_action,
    update_risk,
)


def _radar():
    return pd.DataFrame([
        {
            "se": "2026-SE39",
            "evento": "Dengue × CUIABA",
            "agravo": "dengue",
            "familia": "arbovirose",
            "municipio": "CUIABA",
            "probabilidade": "alto",
            "impacto": "alto",
            "confianca": "Observado",
            "veredito": "investigar",
            "tipo_sinal": "Observado",
            "regras": "positividade elevada; aumento de demanda",
            "acao_cievs": "Priorizar investigação.",
            "acao_ve_mun": "Investigar casos e notificação.",
            "acao_area_tecnica": "Validar critérios.",
            "acao_lacen": "Priorizar TAT.",
        }
    ])


def test_risk_matrix_creates_critical_risk_and_actions():
    radar = _radar()
    risks = build_risk_register(radar, now="2026-10-04T20:00:00")
    actions = build_action_register(
        radar, risks, now="2026-10-04T20:00:00"
    )
    assert len(risks) == 1
    assert risks.loc[0, "score_inerente"] == 9
    assert risks.loc[0, "prioridade"] == "CRITICA"
    assert risks.loc[0, "estado_risco"] == "ABERTO"
    assert len(actions) == 4
    assert set(actions["estado_acao"]) == {"PLANEJADA"}


def test_human_action_state_is_preserved_between_runs():
    radar = _radar()
    risks = build_risk_register(radar, now="2026-10-04T20:00:00")
    actions = build_action_register(radar, risks, now="2026-10-04T20:00:00")
    aid = actions.loc[0, "action_id"]
    actions = update_action(
        actions,
        aid,
        estado="EM_ANDAMENTO",
        responsavel="Equipe CIEVS",
        now="2026-10-04T21:00:00",
    )
    refreshed = build_action_register(
        radar, risks, previous=actions, now="2026-10-05T08:00:00"
    )
    row = refreshed[refreshed["action_id"] == aid].iloc[0]
    assert row["estado_acao"] == "EM_ANDAMENTO"
    assert row["responsavel"] == "Equipe CIEVS"


def test_completed_action_requires_evidence_and_result():
    radar = _radar()
    risks = build_risk_register(radar)
    actions = build_action_register(radar, risks)
    with pytest.raises(ValueError):
        update_action(
            actions,
            actions.loc[0, "action_id"],
            estado="CONCLUIDA",
        )


def test_risk_cannot_close_without_residual_assessment():
    risks = build_risk_register(_radar())
    with pytest.raises(ValueError):
        update_risk(
            risks,
            risks.loc[0, "risk_id"],
            estado="FECHADO",
        )


def test_risk_cannot_close_with_unvalidated_actions():
    radar = _radar()
    risks = build_risk_register(radar)
    actions = build_action_register(radar, risks)
    rid = risks.loc[0, "risk_id"]
    with pytest.raises(ValueError, match="VALIDADA ou CANCELADA"):
        update_risk(
            risks,
            rid,
            estado="FECHADO",
            actions=actions,
            decisao="Encerrar.",
            evidencia_decisao="Evidência revisada.",
            probabilidade_residual="baixo",
            impacto_residual="baixo",
            justificativa_residual="Mitigado.",
        )


def test_closed_risk_reopens_if_signal_reappears():
    radar = _radar()
    risks = build_risk_register(radar, now="2026-10-01T08:00:00")
    rid = risks.loc[0, "risk_id"]
    risks.loc[0, "estado_risco"] = "FECHADO"
    risks.loc[0, "decisao"] = "Encerrado"
    risks.loc[0, "evidencia_decisao"] = "Validação"
    risks.loc[0, "probabilidade_residual"] = "baixo"
    risks.loc[0, "impacto_residual"] = "baixo"
    risks.loc[0, "justificativa_residual"] = "Controlado"
    risks.loc[0, "data_fechamento"] = "2026-10-02T08:00:00"

    radar2 = radar.copy()
    radar2.loc[0, "se"] = "2026-SE40"
    refreshed = build_risk_register(
        radar2, previous=risks, now="2026-10-04T08:00:00"
    )
    assert refreshed.loc[0, "risk_id"] == rid
    assert refreshed.loc[0, "estado_risco"] == "EM_ANALISE"
    assert pd.isna(refreshed.loc[0, "data_fechamento"])
    assert refreshed.loc[0, "se_primeira_deteccao"] == "2026-SE39"
    assert refreshed.loc[0, "se_ultima_deteccao"] == "2026-SE40"


def test_summary_blocks_critical_open_risk():
    radar = _radar()
    risks = build_risk_register(radar, now="2026-10-04T20:00:00")
    actions = build_action_register(
        radar, risks, now="2026-10-04T20:00:00"
    )
    summary = summarize_risk_management(
        risks, actions, now="2026-10-04T20:01:00"
    )
    assert summary["status"] == "BLOCK"
    assert summary["critical_open"] == 1
    assert summary["promotion_ready"] is False
