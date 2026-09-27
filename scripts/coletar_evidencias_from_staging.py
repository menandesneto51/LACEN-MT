# -*- coding: utf-8 -*-
"""Coleta evidencias DEC-001/002 a partir do staging local (freeze-safe).

Usar quando DW/VPN/pyodbc nao estiver disponivel, mas saida_pipeline/staging_dw
ja existir.

  python scripts/coletar_evidencias_from_staging.py --outdir saida_pipeline
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from quality.gal_temporal_anchor_analysis import (
    analyze_temporal_anchor,
    write_temporal_anchor_analysis,
)
from quality.population_source_comparison import (
    compare_population_sources,
    write_population_source_comparison,
)
from quality.territorial_dimension import (
    build_population_dimension_from_staging,
    write_population_dimension,
)
from quality.decision_briefs import write_decision_briefs
from quality.decision_readiness import (
    evaluate_decision_readiness,
    write_decision_readiness_report,
)
from quality.decision_registry import (
    load_decision_registry,
    evaluate_decision_registry,
    write_decision_registry_report,
)


def _build_dossier(quality: Path) -> str:
    path = ROOT / "scripts" / "gerar_dossier_sala_decisao_v2_1.py"
    spec = importlib.util.spec_from_file_location("dossier_mod", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.build_dossier(quality)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", type=Path, default=ROOT / "saida_pipeline")
    ap.add_argument("--analysis-year", type=int, default=None)
    args = ap.parse_args(argv)

    outdir = args.outdir
    stage = outdir / "staging_dw"
    quality = outdir / "quality"
    quality.mkdir(parents=True, exist_ok=True)

    micro_path = stage / "vw_gal_micro_recent.parquet"
    if not micro_path.exists():
        print(f"[FALHA] Staging ausente: {micro_path}")
        return 2

    micro = pd.read_parquet(micro_path)
    weekly, summary = analyze_temporal_anchor(micro)
    write_temporal_anchor_analysis(weekly, summary, quality)

    pop_dim = build_population_dimension_from_staging(stage)
    if not pop_dim.empty:
        write_population_dimension(pop_dim, quality)
    valid = (
        pop_dim[pop_dim["populacao"].notna() & (pop_dim["populacao"] > 0)]
        if not pop_dim.empty
        else pop_dim
    )
    years = (
        sorted(int(y) for y in valid["ano_referencia"].dropna().unique().tolist())
        if not valid.empty
        else []
    )
    analysis_year = args.analysis_year or (years[-1] if years else 2021)
    detail, pairwise, pop_summary = compare_population_sources(
        pop_dim, analysis_year=analysis_year
    )
    write_population_source_comparison(detail, pairwise, pop_summary, quality)

    gov_src = ROOT / "config" / "population_governance_v2_1.json"
    if gov_src.exists():
        shutil.copy(gov_src, quality / "population_governance_v2_1.json")

    write_decision_briefs(quality)
    readiness = evaluate_decision_readiness(quality)
    write_decision_readiness_report(readiness, quality)
    registry = load_decision_registry(ROOT / "config" / "decision_status_v2_1.json")
    write_decision_registry_report(
        evaluate_decision_registry(registry, evidence_dir=quality),
        quality,
    )

    meta = {
        "mode": "staging_replay_evidence_only",
        "automatic_decision_allowed": False,
        "analysis_year_population": analysis_year,
        "gal_micro_rows": int(len(micro)),
        "readiness_overall": readiness.get("overall_status"),
        "notes": [
            "CodigoMunicipio/CODIGO no staging com 6 digitos: IBGE 7 nao inventado.",
            "POPULACAO_TCU sem ano_referencia pode ficar fora da comparacao anual.",
            "Nenhuma alternativa DEC-001/DEC-002 foi selecionada automaticamente.",
        ],
    }
    (quality / "evidence_collection_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (quality / "dossier_sala_decisao_v2_1.md").write_text(
        _build_dossier(quality), encoding="utf-8"
    )

    print("[OK] evidencias staging geradas em", quality)
    print("[OK] readiness:", readiness.get("overall_status"))
    print("[OK] dossie: dossier_sala_decisao_v2_1.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
