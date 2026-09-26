# -*- coding: utf-8 -*-
"""Relatório de reconciliação territorial — LACEN-MT V2.1.

Transforma a fila de investigação da paridade de linkage em uma lista acionável
para saneamento de chaves territoriais e validação antes da promoção V2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


_REASON_MAP = {
    "PERDIDO_COM_IBGE": (
        "O join por nome encontra valor, mas a chave IBGE não encontra correspondência.",
        "Verificar ausência/formato do código IBGE na fonte direita e na dimensão territorial. Corrigir a origem/dimensão; não criar fuzzy match.",
        "ALTA",
    ),
    "CONFLITO": (
        "Join por nome e por IBGE encontram valores diferentes para a mesma unidade analítica.",
        "Auditar duplicidade, código IBGE divergente, agregação territorial e granularidade da fonte antes de promover a V2.",
        "CRITICA",
    ),
    "SEM_MATCH": (
        "Nenhum dos métodos encontrou correspondência para a unidade analisada.",
        "Verificar cobertura temporal, disponibilidade da fonte, código IBGE, grafia do município e granularidade epidemiológica.",
        "MODERADA",
    ),
}


def build_reconciliation_report(investigations: pd.DataFrame) -> pd.DataFrame:
    if investigations is None or investigations.empty:
        return pd.DataFrame(columns=[
            "prioridade", "fonte_linkage", "linkage_parity", "municipio",
            "municipio_ibge", "legacy_match_value", "v2_match_value",
            "hipotese_tecnica", "acao_recomendada", "responsavel_sugerido",
            "estado_reconciliacao",
        ])

    d = investigations.copy()
    for col in (
        "fonte_linkage", "linkage_parity", "municipio", "municipio_ibge",
        "legacy_match_value", "v2_match_value",
    ):
        if col not in d.columns:
            d[col] = pd.NA

    hypotheses = []
    actions = []
    priorities = []
    owners = []
    for _, row in d.iterrows():
        status = str(row.get("linkage_parity") or "")
        hypothesis, action, priority = _REASON_MAP.get(
            status,
            (
                "Divergência territorial não classificada.",
                "Revisar o artefato de paridade e a origem antes de qualquer correção.",
                "MODERADA",
            ),
        )
        source = str(row.get("fonte_linkage") or "")
        if "SINAN" in source:
            owner = "Data Governance + Vigilância Epidemiológica"
        elif "SIM" in source:
            owner = "Data Governance + Vigilância do Óbito"
        elif "SIH" in source or "SIA" in source:
            owner = "Data Governance + Inteligência Assistencial"
        else:
            owner = "Data Governance"
        hypotheses.append(hypothesis)
        actions.append(action)
        priorities.append(priority)
        owners.append(owner)

    d["prioridade"] = priorities
    d["hipotese_tecnica"] = hypotheses
    d["acao_recomendada"] = actions
    d["responsavel_sugerido"] = owners
    d["estado_reconciliacao"] = "ABERTO"

    order = {"CRITICA": 0, "ALTA": 1, "MODERADA": 2, "BAIXA": 3}
    d["_ord"] = d["prioridade"].map(order).fillna(9)
    sort_cols = ["_ord", "fonte_linkage", "municipio"]
    d = d.sort_values(sort_cols).drop(columns="_ord").reset_index(drop=True)

    first = [
        "prioridade", "fonte_linkage", "linkage_parity", "municipio",
        "municipio_ibge", "legacy_match_value", "v2_match_value",
        "hipotese_tecnica", "acao_recomendada", "responsavel_sugerido",
        "estado_reconciliacao",
    ]
    remaining = [c for c in d.columns if c not in first]
    return d[first + remaining]


def summarize_reconciliation(report: pd.DataFrame) -> dict[str, Any]:
    if report is None or report.empty:
        return {
            "open_items": 0,
            "critical": 0,
            "high": 0,
            "moderate": 0,
            "promotion_ready": True,
        }
    p = report["prioridade"].astype(str)
    return {
        "open_items": int(len(report)),
        "critical": int((p == "CRITICA").sum()),
        "high": int((p == "ALTA").sum()),
        "moderate": int((p == "MODERADA").sum()),
        "promotion_ready": not bool(p.isin(["CRITICA", "ALTA"]).any()),
    }


def write_reconciliation_report(
    report: pd.DataFrame,
    outdir: Path | str,
) -> dict[str, Path]:
    import json

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "reconciliacao_territorial.csv"
    json_path = out / "reconciliacao_territorial_resumo.json"
    txt_path = out / "reconciliacao_territorial_resumo.txt"

    report.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        report.to_parquet(out / "reconciliacao_territorial.parquet", index=False)
    except Exception:
        pass

    summary = summarize_reconciliation(report)
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "LACEN-MT V2 — RECONCILIAÇÃO TERRITORIAL",
        f"itens_abertos: {summary['open_items']}",
        f"criticos: {summary['critical']}",
        f"altos: {summary['high']}",
        f"moderados: {summary['moderate']}",
        f"promotion_ready: {str(summary['promotion_ready']).lower()}",
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "txt": txt_path}
