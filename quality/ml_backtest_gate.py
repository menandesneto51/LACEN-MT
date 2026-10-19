# -*- coding: utf-8 -*-
"""Gate técnico de backtest ML — LACEN-MT V2.1.

Não define regra epidemiológica. Verifica apenas se saídas preditivas possuem
evidência mínima de discriminação antes de serem tratadas como sinal operacional.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import pandas as pd


def evaluate_ml_backtest(backtest: pd.DataFrame) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if backtest is None or backtest.empty:
        return {
            "status": "WARN",
            "findings": [],
            "conditions": ["backtest ausente"],
            "operational_scopes": [],
            "blocked_scopes": [],
        }

    for _, row in backtest.iterrows():
        model = str(row.get("modelo") or "")
        scope = str(row.get("escopo") or "")
        status = str(row.get("status") or "")
        key = f"{model}:{scope}"

        if status != "ok":
            findings.append({
                "scope": key,
                "status": "WARN",
                "reason": f"backtest status={status or 'ausente'}",
            })
            continue

        auc = pd.to_numeric(pd.Series([row.get("auc")]), errors="coerce").iloc[0]
        precision = pd.to_numeric(
            pd.Series([row.get("precision")]), errors="coerce"
        ).iloc[0]
        pos_rate = pd.to_numeric(
            pd.Series([row.get("pos_rate")]), errors="coerce"
        ).iloc[0]
        n = pd.to_numeric(pd.Series([row.get("n")]), errors="coerce").iloc[0]
        n_alert = pd.to_numeric(
            pd.Series([row.get("n_alerta_emitido")]), errors="coerce"
        ).iloc[0]
        n_confirm = pd.to_numeric(
            pd.Series([row.get("n_confirmado")]), errors="coerce"
        ).iloc[0]

        if pd.isna(auc):
            findings.append({
                "scope": key,
                "status": "WARN",
                "reason": "AUC indisponível; discriminação não demonstrada",
            })
            continue

        if float(auc) < 0.5:
            findings.append({
                "scope": key,
                "status": "BLOCK",
                "reason": f"AUC={float(auc):.4f} < 0,5 (abaixo do aleatório)",
            })
            continue

        if (
            pd.notna(precision)
            and pd.notna(pos_rate)
            and float(precision) <= float(pos_rate)
        ):
            findings.append({
                "scope": key,
                "status": "WARN",
                "reason": (
                    f"precisão={float(precision):.4f} não supera "
                    f"prevalência={float(pos_rate):.4f}"
                ),
            })
            continue

        if (
            pd.notna(n_alert)
            and float(n_alert) > 0
            and pd.notna(n_confirm)
            and float(n_confirm) == 0
        ):
            findings.append({
                "scope": key,
                "status": "WARN",
                "reason": "alertas emitidos sem confirmação no holdout",
            })
            continue

        findings.append({
            "scope": key,
            "status": "PASS",
            "reason": (
                f"AUC={float(auc):.4f}; n={int(n) if pd.notna(n) else 'NA'}"
            ),
        })

    blocked = [x["scope"] for x in findings if x["status"] == "BLOCK"]
    warned = [x["scope"] for x in findings if x["status"] == "WARN"]
    passed = [x["scope"] for x in findings if x["status"] == "PASS"]

    overall = "BLOCK" if blocked else ("WARN" if warned else "PASS")
    return {
        "status": overall,
        "findings": findings,
        "operational_scopes": passed,
        "warning_scopes": warned,
        "blocked_scopes": blocked,
        "rule": "AUC<0.5 blocks operational interpretation; no epidemiological threshold is created.",
    }


def evaluate_ml_backtest_file(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return evaluate_ml_backtest(pd.DataFrame())
    return evaluate_ml_backtest(pd.read_csv(p, low_memory=False))


def write_ml_backtest_gate(report: dict[str, Any], outdir: Path | str) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "ml_model_gate_v2_1.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
