import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_genomic_catalog_preflight_keeps_sample_anchor_and_source_gap_explicit():
    payload = _load("catalog_evidence_genomics_v2_1.json")
    assert payload["agent"] == "SES_DATA_CATALOG"
    assert payload["decision"] == "NEW_SOURCE_REQUIRED"
    matches = payload["catalog_matches"]
    assert any(item["object"] == "dbo.VW_GAL" for item in matches)
    gal = next(item for item in matches if item["object"] == "dbo.VW_GAL")
    assert "Codigo_Amostra" in gal["fields"]
    assert payload["explicit_term_matches"] == []
    assert "não inventar API/tabela/fonte genômica" in payload["constraints"]


def test_supply_chain_catalog_preflight_reuses_suins_without_inventing_stock():
    payload = _load("catalog_evidence_supply_chain_v2_1.json")
    assert payload["agent"] == "SES_DATA_CATALOG"
    assert payload["decision"] == "EXTEND_EXISTING"
    match = payload["catalog_matches"][0]
    assert match["object"] == "dbo.SUINS_INSUMOS_ENTRADAS_SAIDAS"
    assert "Quantidade_Entregue" in match["fields"]
    assert "Quantidade_Fornecida" in match["fields"]
    assert any("saldo atual" in item for item in payload["constraints"])
