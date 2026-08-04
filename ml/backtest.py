# -*- coding: utf-8 -*-
"""Backtest semanal: o alerta de SE t se confirmou em SE t+1?"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .train import FEATURE_COLS_RISCO, FEATURE_COLS_SILENCIO, _make_labels, _matrix, _sklearn_available


def _familia(target: object) -> str:
    t = str(target or "").casefold()
    if any(x in t for x in ("tuberculose", "baciloscopia", "rifampicina", "lf_lam")):
        return "tuberculose"
    if "hepatite" in t:
        return "hepatite"
    if any(x in t for x in ("dengue", "zika", "chikungunya", "oropouche", "mayaro", "febre_amarela")):
        return "arbovirose"
    if any(x in t for x in ("influenza", "sars_cov", "covid", "respirat", "virus_respiratorio")):
        return "respiratorio"
    return "outros"


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=float), -20, 20)
    return 1.0 / (1.0 + np.exp(-x))


def _metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    if len(y_true) == 0:
        return {
            "n": 0, "n_alerta_emitido": 0, "n_confirmado": 0,
            "auc": None, "precision": None, "recall": None,
            "brier": None, "confirmacao": None, "pos_rate": None,
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
    }


def _baseline_prob_risco(df: pd.DataFrame) -> np.ndarray:
    pos = pd.to_numeric(df.get("positividade", 0), errors="coerce").fillna(0)
    pos_t = pd.to_numeric(df.get("positividade_trend", 0), errors="coerce").fillna(0)
    risco = pd.to_numeric(df.get("risco_composto", 0), errors="coerce").fillna(0)
    tests = pd.to_numeric(df.get("tests", 0), errors="coerce").fillna(0)
    notif = pd.to_numeric(df.get("notificacoes", 0), errors="coerce").fillna(0)
    vuln = pd.to_numeric(df.get("indice_vulnerabilidade", 0), errors="coerce").fillna(0)
    tests_t = pd.to_numeric(df.get("tests_trend", 0), errors="coerce").fillna(0)
    logit = (
        -2.2
        + 2.0 * pos
        + 1.5 * np.tanh(pos_t * 5)
        + 0.35 * risco.clip(0, 10)
        + 0.15 * np.log1p(tests)
        + 0.12 * np.log1p(notif)
        + 0.25 * vuln.clip(-3, 3)
        + 0.4 * np.tanh(tests_t / 5.0)
    )
    return _sigmoid(logit.to_numpy())


def _baseline_prob_silencio(df: pd.DataFrame) -> np.ndarray:
    tests = pd.to_numeric(df.get("tests", 0), errors="coerce").fillna(0)
    tests_ma8 = pd.to_numeric(df.get("tests_ma8", 0), errors="coerce").fillna(0)
    notif = pd.to_numeric(df.get("notificacoes", 0), errors="coerce").fillna(0)
    weeks_zero = pd.to_numeric(df.get("semanas_sem_exame", 0), errors="coerce").fillna(0)
    vuln = pd.to_numeric(df.get("indice_vulnerabilidade", 0), errors="coerce").fillna(0)
    uso = pd.to_numeric(df.get("solicitacoes_100k", 0), errors="coerce").fillna(0)
    logit = (
        -1.0
        + 0.55 * weeks_zero.clip(0, 12)
        + 0.8 * (tests <= 0).astype(float)
        + 0.35 * (tests_ma8 < 1).astype(float)
        + 0.25 * np.log1p(notif)
        + 0.2 * vuln.clip(-3, 3)
        - 0.15 * np.log1p(uso.clip(lower=0))
    )
    return _sigmoid(logit.to_numpy())


def run_backtest(features: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    """
    Split temporal 80/20: treina GB no passado e avalia na janela recente.
    Reporta AUC, precisão/confirmação e métricas por família de agravo.
    """
    rows: list[dict] = []
    labeled = _make_labels(features)
    if labeled.empty or len(labeled) < 80:
        return pd.DataFrame([{
            "modelo": "risco",
            "escopo": "global",
            "status": "skipped",
            "motivo": "amostra insuficiente",
            "n": int(len(labeled)),
        }])

    weeks = (
        labeled[["epi_year", "epi_week"]]
        .drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
        .reset_index(drop=True)
    )
    cut = max(1, int(len(weeks) * 0.8))
    train_w = weeks.iloc[:cut].assign(_split="train")
    test_w = weeks.iloc[cut:].assign(_split="test")
    split = pd.concat([train_w, test_w], ignore_index=True)
    labeled = labeled.merge(split, on=["epi_year", "epi_week"], how="inner")
    train_df = labeled[labeled["_split"] == "train"]
    test_df = labeled[labeled["_split"] == "test"]

    use_sklearn = _sklearn_available() and len(train_df) >= 50 and len(test_df) >= 20

    if use_sklearn:
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
                rows.append({
                    "modelo": name, "escopo": "global", "status": "skipped",
                    "motivo": "pouca variabilidade", "n": int(len(Xtr)),
                })
                continue
            clf = GradientBoostingClassifier(
                random_state=42, max_depth=3, n_estimators=80, learning_rate=0.08,
            )
            clf.fit(Xtr, ytr)
            Xte = Xte.reindex(columns=used, fill_value=0.0)
            prob = clf.predict_proba(Xte)[:, 1]
            thresholds = (0.5, 0.25, 0.15) if name == "risco" else (0.5,)
            for thr in thresholds:
                met = _metrics(yte.to_numpy(), prob, thr)
                rows.append({
                    "modelo": name,
                    "escopo": "global",
                    "status": "ok",
                    "metodo": "sklearn_gb_temporal_80_20",
                    "threshold": thr,
                    "n_train": int(len(Xtr)),
                    "n_test": int(len(Xte)),
                    "n_train_weeks": int(len(train_w)),
                    "n_test_weeks": int(len(test_w)),
                    **met,
                })
            # Famílias no limiar operacional 0.25 (eventos raros)
            if name == "risco":
                test_eval = test_df.copy()
                test_eval["_prob"] = prob
                test_eval["_fam"] = test_eval["target"].map(_familia)
                for fam, sub in test_eval.groupby("_fam"):
                    if len(sub) < 30 or sub[ycol].nunique() < 2:
                        continue
                    met_f = _metrics(sub[ycol].to_numpy(), sub["_prob"].to_numpy(), 0.25)
                    rows.append({
                        "modelo": name,
                        "escopo": f"familia:{fam}",
                        "status": "ok",
                        "metodo": "sklearn_gb_temporal_80_20",
                        "threshold": 0.25,
                        "n_train_weeks": int(len(train_w)),
                        "n_test_weeks": int(len(test_w)),
                        **met_f,
                    })
            continue  # already handled familia above; skip old block
    else:
        for name, ycol, prob_fn in (
            ("risco", "y_alerta", _baseline_prob_risco),
            ("silencio", "y_silencio", _baseline_prob_silencio),
        ):
            if test_df.empty or test_df[ycol].nunique() < 2:
                continue
            prob = prob_fn(test_df)
            met = _metrics(test_df[ycol].to_numpy(), prob, threshold)
            rows.append({
                "modelo": name,
                "escopo": "global",
                "status": "ok_baseline",
                "metodo": "baseline_logit_v1",
                "threshold": threshold,
                "n_train_weeks": int(len(train_w)),
                "n_test_weeks": int(len(test_w)),
                **met,
            })

    return pd.DataFrame(rows)
