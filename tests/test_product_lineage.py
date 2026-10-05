from quality.product_lineage import (
    build_product_lineage,
    contains_absolute_local_path,
    write_lineage_registry,
)


def test_product_lineage_normalizes_sources():
    item = build_product_lineage(
        product="integrated_weekly_surveillance",
        logical_sources=["VW_GAL", "SINAN", "VW_GAL"],
        cutoff="2026-SE37",
        dependencies=["territory_key"],
    )
    assert item.logical_sources == ["SINAN", "VW_GAL"]
    assert item.pipeline_version == "v2.1"


def test_lineage_detects_absolute_windows_path():
    assert contains_absolute_local_path(r"C:\Users\name\file.csv") is True


def test_lineage_detects_home_path():
    assert contains_absolute_local_path("/home/user/file.csv") is True


def test_lineage_accepts_logical_source_names():
    assert contains_absolute_local_path("DW:VW_GAL") is False


def test_lineage_registry_writes_artifacts(tmp_path):
    item = build_product_lineage(
        product="paridade_legado_v2",
        logical_sources=["VW_GAL", "POPULACAO_TCU"],
        cutoff="2026-09-26",
    )
    paths = write_lineage_registry([item], tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()
