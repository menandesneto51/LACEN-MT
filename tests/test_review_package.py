from quality.review_package import build_review_package, write_review_package


def _write_json(path, payload):
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_review_package_collects_evidence_and_pending_reviews(tmp_path):
    _write_json(tmp_path / "data_quality_gate_ultimo.json", {"status": "PASS"})
    _write_json(tmp_path / "paridade_legado_v2_resumo.json", {"status": "PASS"})
    _write_json(tmp_path / "paridade_linkage_resumo.json", {"promotion_status": "PASS"})
    _write_json(tmp_path / "reconciliacao_territorial_resumo.json", {
        "promotion_ready": True,
        "open_items": 0,
        "invalid_closed_items": 0,
    })
    _write_json(tmp_path / "promotion_gate_v2_1.json", {
        "status": "READY_FOR_REVIEW",
        "blocking_reasons": [],
        "conditions": [],
    })

    package = build_review_package(
        tmp_path,
        pr_number=7,
        head_sha="abc123",
        reviews_path=tmp_path / "no_reviews.json",
    )
    assert package["promotion_gate_status"] == "READY_FOR_REVIEW"
    assert package["automatic_promotion_allowed"] is False
    assert package["architecture_review"]["status"] == "PENDING"
    assert package["epidemiology_review"]["status"] == "PENDING"
    assert package["release_decision"]["status"] == "PENDING"


def test_review_package_surfaces_open_reconciliation_items(tmp_path):
    _write_json(tmp_path / "reconciliacao_territorial_resumo.json", {
        "promotion_ready": False,
        "open_items": 3,
        "invalid_closed_items": 1,
    })
    _write_json(tmp_path / "promotion_gate_v2_1.json", {
        "status": "NOT_READY",
        "blocking_reasons": ["Reconciliação territorial pendente."],
        "conditions": [],
    })
    package = build_review_package(tmp_path, reviews_path=tmp_path / "no_reviews.json")
    assert any("3 item(ns)" in x for x in package["conditions"])
    assert any("1 fechamento" in x for x in package["blocking_reasons"])


def test_review_package_writes_json_and_markdown(tmp_path):
    package = build_review_package(
        tmp_path,
        pr_number=7,
        head_sha="deadbeef",
        reviews_path=tmp_path / "no_reviews.json",
    )
    paths = write_review_package(package, tmp_path)
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    md = paths["markdown"].read_text(encoding="utf-8")
    assert "Revisão arquitetural" in md
    assert "Revisão epidemiológica" in md
    assert "Promoção automática" in md
