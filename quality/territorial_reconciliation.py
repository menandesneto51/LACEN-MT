# -*- coding: utf-8 -*-
"""Relatório de reconciliação territorial — LACEN-MT V2.1.

Transforma a fila de investigação da paridade de linkage em uma lista acionável
para saneamento de chaves territoriais e validação antes da promoção V2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime
import hashlib

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


def _stable_issue_id(row: pd.Series) -> str:
    parts = [
        str(row.get("fonte_linkage") or ""),
        str(row.get("linkage_parity") or ""),
        str(row.get("municipio_ibge") or ""),
        str(row.get("municipio") or ""),
        str(row.get("epi_year") or ""),
        str(row.get("epi_week") or ""),
        str(row.get("agravo_sinan") or row.get("cid_familia") or ""),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return "TR-" + digest.upper()


def merge_resolution_state(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    *,
    now: str | None = None,
) -> pd.DataFrame:
    """Preserva decisões humanas anteriores por issue_id entre execuções."""
    if current is None:
        return pd.DataFrame()
    out = current.copy()
    now = now or datetime.now().isoformat(timespec="seconds")
    if "issue_id" not in out.columns:
        out["issue_id"] = out.apply(_stable_issue_id, axis=1)

    lifecycle_defaults = {
        "responsavel_atual": pd.NA,
        "decisao": pd.NA,
        "evidencia": pd.NA,
        "correcao_aplicada": pd.NA,
        "validacao_pos_correcao": pd.NA,
        "data_abertura": now,
        "data_atualizacao": now,
        "data_fechamento": pd.NA,
    }
    for col, default in lifecycle_defaults.items():
        if col not in out.columns:
            out[col] = default

    if previous is None or previous.empty or "issue_id" not in previous.columns:
        return out

    prev = previous.drop_duplicates(subset=["issue_id"], keep="last").set_index("issue_id")
    preserved = [
        "responsavel_atual", "decisao", "evidencia", "correcao_aplicada",
        "validacao_pos_correcao", "data_abertura", "data_atualizacao",
        "data_fechamento", "estado_reconciliacao",
    ]
    for idx, issue in out["issue_id"].items():
        if issue not in prev.index:
            continue
        for col in preserved:
            if col in prev.columns:
                val = prev.at[issue, col]
                if pd.notna(val) and str(val) != "":
                    out.at[idx, col] = val
    return out


def apply_resolution(
    report: pd.DataFrame,
    issue_id: str,
    *,
    estado: str,
    responsavel: str | None = None,
    decisao: str | None = None,
    evidencia: str | None = None,
    correcao_aplicada: str | None = None,
    validacao_pos_correcao: str | None = None,
    now: str | None = None,
) -> pd.DataFrame:
    """Aplica transição explícita a um item; não fecha automaticamente."""
    allowed = {"ABERTO", "EM_ANALISE", "CORRECAO_APLICADA", "VALIDADO", "FECHADO"}
    if estado not in allowed:
        raise ValueError(f"Estado inválido: {estado}")
    out = report.copy()
    mask = out["issue_id"].astype(str) == str(issue_id)
    if not mask.any():
        raise KeyError(f"issue_id não encontrado: {issue_id}")
    now = now or datetime.now().isoformat(timespec="seconds")
    out.loc[mask, "estado_reconciliacao"] = estado
    out.loc[mask, "data_atualizacao"] = now
    if responsavel is not None:
        out.loc[mask, "responsavel_atual"] = responsavel
    if decisao is not None:
        out.loc[mask, "decisao"] = decisao
    if evidencia is not None:
        out.loc[mask, "evidencia"] = evidencia
    if correcao_aplicada is not None:
        out.loc[mask, "correcao_aplicada"] = correcao_aplicada
    if validacao_pos_correcao is not None:
        out.loc[mask, "validacao_pos_correcao"] = validacao_pos_correcao
    if estado == "FECHADO":
        required = {
            "decisao": decisao if decisao is not None else out.loc[mask, "decisao"].iloc[0],
            "evidencia": evidencia if evidencia is not None else out.loc[mask, "evidencia"].iloc[0],
            "correcao_aplicada": correcao_aplicada if correcao_aplicada is not None else out.loc[mask, "correcao_aplicada"].iloc[0],
            "validacao_pos_correcao": validacao_pos_correcao if validacao_pos_correcao is not None else out.loc[mask, "validacao_pos_correcao"].iloc[0],
        }
        missing = [k for k, v in required.items() if pd.isna(v) or str(v).strip() == ""]
        if missing:
            raise ValueError(
                "FECHADO exige decisão, evidência, correção aplicada e validação pós-correção. "
                + "Ausentes: " + ", ".join(missing)
            )
        out.loc[mask, "data_fechamento"] = now
    return out



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
    d["issue_id"] = d.apply(_stable_issue_id, axis=1)

    order = {"CRITICA": 0, "ALTA": 1, "MODERADA": 2, "BAIXA": 3}
    d["_ord"] = d["prioridade"].map(order).fillna(9)
    sort_cols = ["_ord", "fonte_linkage", "municipio"]
    d = d.sort_values(sort_cols).drop(columns="_ord").reset_index(drop=True)

    first = [
        "issue_id", "prioridade", "fonte_linkage", "linkage_parity", "municipio",
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
            "closed_items": 0,
            "critical_open": 0,
            "high_open": 0,
            "moderate_open": 0,
            "invalid_closed_items": 0,
            "promotion_ready": True,
        }

    d = report.copy()
    if "estado_reconciliacao" not in d.columns:
        d["estado_reconciliacao"] = "ABERTO"
    state = d["estado_reconciliacao"].astype(str)
    open_mask = state != "FECHADO"
    closed_mask = state == "FECHADO"
    p = d["prioridade"].astype(str)

    required_cols = ("decisao", "evidencia", "correcao_aplicada", "validacao_pos_correcao")
    invalid_closed = pd.Series(False, index=d.index)
    for col in required_cols:
        if col not in d.columns:
            d[col] = pd.NA
        invalid_closed = invalid_closed | (closed_mask & (d[col].isna() | d[col].astype(str).str.strip().eq("")))

    critical_open = int((open_mask & (p == "CRITICA")).sum())
    high_open = int((open_mask & (p == "ALTA")).sum())
    moderate_open = int((open_mask & (p == "MODERADA")).sum())
    invalid_closed_items = int(invalid_closed.sum())

    return {
        "open_items": int(open_mask.sum()),
        "closed_items": int(closed_mask.sum()),
        "critical_open": critical_open,
        "high_open": high_open,
        "moderate_open": moderate_open,
        "invalid_closed_items": invalid_closed_items,
        "promotion_ready": (
            critical_open == 0
            and high_open == 0
            and invalid_closed_items == 0
        ),
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

    previous = pd.DataFrame()
    if csv_path.exists():
        try:
            previous = pd.read_csv(csv_path, low_memory=False)
        except Exception:
            previous = pd.DataFrame()
    report = merge_resolution_state(report, previous)
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
        f"itens_fechados: {summary['closed_items']}",
        f"criticos_abertos: {summary['critical_open']}",
        f"altos_abertos: {summary['high_open']}",
        f"moderados_abertos: {summary['moderate_open']}",
        f"fechados_invalidos: {summary['invalid_closed_items']}",
        f"promotion_ready: {str(summary['promotion_ready']).lower()}",
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "txt": txt_path}
