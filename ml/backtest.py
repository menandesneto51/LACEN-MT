# -*- coding: utf-8 -*-
"""Backtest semanal com precisão@K e limiares calibrados."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .train import (
    FEATURE_COLS_RISCO,
    FEATURE_COLS_SILENCIO,
    _best_threshold,
    _make_labels,
    _matrix,
    _precision_at_k,
    _sklearn_available,
    familia_agravo,
)


def _metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    if len(y_true) == 0:
        return {
            "n": 0, "n_alerta_emitido": 0, "n_confirmado": 0,
            "auc": None, "precision": None, "recall": None,
            "brier": None, "confirmacao": None, "pos_rate": None,
            "precision_at_20": None, "precision_at_50": None,
        }

    pred = (y_prob >= threshold).astype(int)
    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    brier = float(np.mean((y_prob - y_true) ** 2))
    auc = None
    if len(np.unique(y_true)) > 1:
        try:
            from sklearn.metrics import roc_auc_score
            auc = float(roc_auc_score(y_true, y_prob))
        except Exception:
            auc = None
    return {
        "n": int(len(y_true)),
        "n_alerta_emitido": int(pred.sum()),
        "n_confirmado": tp,
        "auc": auc,
        "precision": precision,
        "recall": recall,
        "brier": brier,
        "confirmacao": precision,
        "pos_rate": float(y_true.mean()),
        "precision_at_20": _precision_at_k(y_true, y_prob, 20),
        "precision_at_50": _precision_at_k(y_true, y_prob, 50),
    }


def run_backtest(features: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    rows: list[dict] = []
    labeled = _make_labels(features)
    if labeled.empty or len(labeled) < 80:
        return pd.DataFrame([{
            "modelo": "risco", "escopo": "global", "status": "skipped",
            "motivo": "amostra insuficiente", "n": int(len(labeled)),
        }])

    weeks = (
        labeled[["epi_year", "epi_week"]].drop_duplicates()
        .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    )
    cut = max(1, int(len(weeks) * 0.8))
    train_w = weeks.iloc[:cut].assign(_split="train")
    test_w = weeks.iloc[cut:].assign(_split="test")
    split = pd.concat([train_w, test_w], ignore_index=True)
    labeled = labeled.merge(split, on=["epi_year", "epi_week"], how="inner")
    train_df = labeled[labeled["_split"] == "train"].sort_values(["epi_year", "epi_week"])
    test_df = labeled[labeled["_split"] == "test"].sort_values(["epi_year", "epi_week"])

    if not (_sklearn_available() and len(train_df) >= 50 and len(test_df) >= 20):
        return pd.DataFrame([{
            "modelo": "risco", "escopo": "global", "status": "skipped",
            "motivo": "sklearn/amostra insuficiente",
        }])

    from sklearn.ensemble import GradientBoostingClassifier

    for name, cols, ycol in (
        ("risco", FEATURE_COLS_RISCO, "y_alerta"),
        ("silencio", FEATURE_COLS_SILENCIO, "y_silencio"),
    ):
        Xtr, used = _matrix(train_df, cols)
        ytr = train_df[ycol].astype(int)
        Xte, _ = _matrix(test_df, used)
        yte = test_df[ycol].astype(int)
        if ytr.nunique() < 2:
            rows.append({"modelo": name, "escopo": "global", "status": "skipped",
                         "motivo": "pouca variabilidade", "n": int(len(Xtr))})
            continue
        clf = GradientBoostingClassifier(
            random_state=42, max_depth=3, n_estimators=80, learning_rate=0.08,
        )
        clf.fit(Xtr, ytr)
        Xte = Xte.reindex(columns=used, fill_value=0.0)
        prob = clf.predict_proba(Xte)[:, 1]
        thr_opt, f1 = _best_threshold(yte.to_numpy(), prob)
        for thr, label in ((thr_opt, "calibrado"), (0.5, "fixo"), (threshold, "default")):
            met = _metrics(yte.to_numpy(), prob, thr)
            rows.append({
                "modelo": name, "escopo": "global", "status": "ok",
                "metodo": f"sklearn_gb_temporal_80_20_{label}",
                "threshold": thr, "f1_at_threshold": f1 if label == "calibrado" else None,
                "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
                "n_train_weeks": int(len(train_w)), "n_test_weeks": int(len(test_w)),
                **met,
            })
        if name == "risco":
            test_eval = test_df.copy()
            test_eval["_prob"] = prob
            test_eval["_fam"] = test_eval["target"].map(familia_agravo)
            for fam, sub in test_eval.groupby("_fam"):
                if len(sub) < 30 or sub[ycol].nunique() < 2:
                    continue
                thr_f, _ = _best_threshold(sub[ycol].to_numpy(), sub["_prob"].to_numpy())
                met_f = _metrics(sub[ycol].to_numpy(), sub["_prob"].to_numpy(), thr_f)
                rows.append({
                    "modelo": name, "escopo": f"familia:{fam}", "status": "ok",
                    "metodo": "sklearn_gb_temporal_80_20_calibrado",
                    "threshold": thr_f,
                    "n_train_weeks": int(len(train_w)), "n_test_weeks": int(len(test_w)),
                    **met_f,
                })

    return pd.DataFrame(rows)
