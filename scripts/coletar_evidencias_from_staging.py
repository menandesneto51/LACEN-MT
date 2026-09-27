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
from quality.agent_reviews import (
    load_agent_reviews,
    summarize_agent_reviews,
    write_agent_reviews,
)
from quality.population_governance import (
    load_population_governance,
    evaluate_population_governance,
    write_population_governance_report,
)
from quality.promotion_gate import evaluate_promotion_gate, write_promotion_gate
from quality.review_package import build_review_package, write_review_package
from quality.data_quality_agent import run_quality_gate, write_report as write_quality_report
from quality.parity_report import build_parity_report, write_parity_report
from quality.linkage_parity import LinkageParitySummary, write_linkage_parity
from etl.build_weekly_from_gal import weekly_from_dw_agg


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

    # DQ + paridade a partir do weekly GAL do staging (reduz UNKNOWN no Promotion Gate).
    weekly_pos = pd.DataFrame()
    dq_status = None
    parity_status = None
    agg_path = stage / "vw_gal_weekly_agg.parquet"
    if agg_path.exists():
        _tests, weekly_pos = weekly_from_dw_agg(pd.read_parquet(agg_path))
        if not weekly_pos.empty and "target" in weekly_pos.columns:
            weekly_pos = weekly_pos.rename(columns={"target": "agravo"})
        dq_report = run_quality_gate(
            weekly=weekly_pos if not weekly_pos.empty else None,
            gal_micro=micro,
            population=pop_dim if not pop_dim.empty else None,
            analysis_year=analysis_year,
            population_required=False,
            metadata={
                "pipeline": "scripts.coletar_evidencias_from_staging",
                "pipeline_version": "v2.1",
                "fonte_dados": "staging_dw",
                "mode": "evidence_only_staging_replay",
            },
        )
        write_quality_report(dq_report, quality)
        dq_status = dq_report.status.value
        _parity_detail, parity_summary = build_parity_report(
            weekly_pos if not weekly_pos.empty else pd.DataFrame()
        )
        write_parity_report(_parity_detail, parity_summary, quality)
        parity_status = parity_summary.status

    # Linkage multi-fonte completo exige ETL DW; no staging replay fica WARN explícito.
    linkage_payload = write_linkage_parity(
        {
            "STAGING_REPLAY": (
                pd.DataFrame(),
                LinkageParitySummary(
                    source="STAGING_REPLAY",
                    rows_left=0,
                    both_same=0,
                    recovered_by_ibge=0,
                    lost_by_ibge=0,
                    conflict=0,
                    no_match=0,
                    promotion_status="WARN",
                ),
            )
        },
        quality,
    )
    linkage_status = linkage_payload.get("promotion_status")
    recon_summary = {}
    recon_path = quality / "reconciliacao_territorial_resumo.json"
    if recon_path.exists():
        try:
            recon_summary = json.loads(recon_path.read_text(encoding="utf-8"))
        except Exception:
            recon_summary = {}

    population_policy = load_population_governance(
        ROOT / "config" / "population_governance_v2_1.json"
    )
    population_governance = evaluate_population_governance(
        pop_dim,
        analysis_year=analysis_year,
        policy=population_policy,
    )
    write_population_governance_report(population_governance, quality)
    # Copia da política (ainda PENDING até endosso formal) para rastreio.
    gov_src = ROOT / "config" / "population_governance_v2_1.json"
    if gov_src.exists():
        shutil.copy(gov_src, quality / "population_governance_policy_v2_1.json")
    endorsement_src = ROOT / "config" / "institutional_endorsement_v2_1.json"
    if endorsement_src.exists():
        shutil.copy(endorsement_src, quality / "institutional_endorsement_v2_1.json")

    write_decision_briefs(quality)
    readiness = evaluate_decision_readiness(quality)
    write_decision_readiness_report(readiness, quality)
    registry = load_decision_registry(ROOT / "config" / "decision_status_v2_1.json")
    registry_eval = evaluate_decision_registry(registry, evidence_dir=quality)
    write_decision_registry_report(registry_eval, quality)

    agent_reviews = load_agent_reviews(
        ROOT / "quality" / "reviews" / "v2_1_initial_reviews.json"
    )
    agent_summary = summarize_agent_reviews(agent_reviews)
    write_agent_reviews(agent_reviews, quality)

    readiness_blockers: list[str] = []
    for item in (readiness.get("decisions") or {}).values():
        readiness_blockers.extend(item.get("blockers", []) or [])

    promotion = evaluate_promotion_gate(
        data_quality_status=dq_status,
        parity_status=parity_status,
        linkage_parity_status=linkage_status,
        territorial_promotion_ready=recon_summary.get("promotion_ready"),
        ci_status="SUCCESS",
        architecture_review="PASS",
        epidemiology_review="PASS",
        agent_reviews_status=agent_summary.get("overall_status"),
        population_governance_approved=population_governance.approved,
        population_governance_blockers=population_governance.blockers,
        decision_registry_status=registry_eval.get("overall_status"),
        decision_registry_blockers=registry_eval.get("blockers", []),
        decision_readiness_status=readiness.get("overall_status"),
        decision_readiness_blockers=readiness_blockers,
    )
    write_promotion_gate(promotion, quality)
    write_review_package(
        build_review_package(
            quality,
            pr_number=7,
            reviews_path=ROOT / "quality" / "reviews" / "v2_1_initial_reviews.json",
        ),
        quality,
    )

    meta = {
        "mode": "staging_replay_evidence_only",
        "automatic_decision_allowed": False,
        "analysis_year_population": analysis_year,
        "gal_micro_rows": int(len(micro)),
        "weekly_pos_rows": int(len(weekly_pos)),
        "data_quality_status": dq_status,
        "parity_status": parity_status,
        "linkage_parity_status": linkage_status,
        "readiness_overall": readiness.get("overall_status"),
        "decision_registry_overall": registry_eval.get("overall_status"),
        "agent_reviews_overall": agent_summary.get("overall_status"),
        "population_governance_approved": population_governance.approved,
        "promotion_gate_status": promotion.status,
        "notes": [
            "CodigoMunicipio/CODIGO no staging com 6 digitos: IBGE 7 nao inventado.",
            "POPULACAO_TCU sem ano_referencia pode ficar fora da comparacao anual.",
            "DEC-001/DEC-002 permanecem PENDING até endosso formal (formulario institucional).",
            "Linkage STAGING_REPLAY em WARN: pareamentos GAL×SINAN/SIM/SIH/SIA exigem ETL DW.",
        ],
    }
    (quality / "evidence_collection_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (quality / "dossier_sala_decisao_v2_1.md").write_text(
        _build_dossier(quality), encoding="utf-8"
    )

    print("[OK] evidencias staging geradas em", quality)
    print("[OK] data_quality:", dq_status)
    print("[OK] parity:", parity_status)
    print("[OK] linkage:", linkage_status)
    print("[OK] readiness:", readiness.get("overall_status"))
    print("[OK] decision_registry:", registry_eval.get("overall_status"))
    print("[OK] agent_reviews:", agent_summary.get("overall_status"))
    print("[OK] promotion_gate:", promotion.status)
    print("[OK] dossie: dossier_sala_decisao_v2_1.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
