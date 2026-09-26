from quality.promotion_gate import (
    build_gate_from_artifacts,
    evaluate_promotion_gate,
    write_promotion_gate,
)


def test_promotion_gate_not_ready_on_block():
    result = evaluate_promotion_gate(
        data_quality_status="PASS",
        parity_status="BLOCK",
        linkage_parity_status="PASS",
        territorial_promotion_ready=True,
        ci_status="PASS",
        architecture_review="APPROVED",
        epidemiology_review="APPROVED",
    )
    assert result.status == "NOT_READY"
    assert result.automatic_promotion_allowed is False
    assert any("Paridade legado" in x for x in result.blocking_reasons)


def test_promotion_gate_conditional_when_external_reviews_missing():
    result = evaluate_promotion_gate(
        data_quality_status="PASS",
        parity_status="PASS",
        linkage_parity_status="PASS",
        territorial_promotion_ready=True,
        ci_status=None,
        architecture_review=None,
        epidemiology_review=None,
    )
    assert result.status == "CONDITIONAL"
    assert result.blocking_reasons == []
    assert len(result.conditions) >= 3


def test_promotion_gate_ready_for_review_only_with_all_evidence():
    result = evaluate_promotion_gate(
        data_quality_status="PASS",
        parity_status="PASS",
        linkage_parity_status="PASS",
        territorial_promotion_ready=True,
        ci_status="SUCCESS",
        architecture_review="APPROVED",
        epidemiology_review="APPROVED",
    )
    assert result.status == "READY_FOR_REVIEW"
    assert result.conditions == []
    assert result.automatic_promotion_allowed is False


def test_territorial_not_ready_blocks_promotion():
    result = evaluate_promotion_gate(
        data_quality_status="PASS",
        parity_status="PASS",
        linkage_parity_status="PASS",
        territorial_promotion_ready=False,
        ci_status="PASS",
        architecture_review="APPROVED",
        epidemiology_review="APPROVED",
    )
    assert result.status == "NOT_READY"
    assert any("Reconciliação territorial" in x for x in result.blocking_reasons)


def test_build_gate_from_artifacts(tmp_path):
    (tmp_path / "data_quality_gate_ultimo.json").write_text(
        '{"status":"PASS"}', encoding="utf-8"
    )
    (tmp_path / "paridade_legado_v2_resumo.json").write_text(
        '{"status":"PASS"}', encoding="utf-8"
    )
    (tmp_path / "paridade_linkage_resumo.json").write_text(
        '{"promotion_status":"PASS"}', encoding="utf-8"
    )
    (tmp_path / "reconciliacao_territorial_resumo.json").write_text(
        '{"promotion_ready":true}', encoding="utf-8"
    )
    result = build_gate_from_artifacts(
        tmp_path,
        ci_status="PASS",
        architecture_review="APPROVED",
        epidemiology_review="APPROVED",
    )
    assert result.status == "READY_FOR_REVIEW"


def test_promotion_gate_writes_artifacts(tmp_path):
    result = evaluate_promotion_gate(
        data_quality_status="PASS",
        parity_status="WARN",
        linkage_parity_status="PASS",
        territorial_promotion_ready=True,
        ci_status="PASS",
        architecture_review="APPROVED",
        epidemiology_review="APPROVED",
    )
    paths = write_promotion_gate(result, tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()
