# -*- coding: utf-8 -*-
"""Treino sklearn com validação temporal (opcional — fallback = baseline)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

STORE = Path(__file__).resolve().parent / "models_store"

FEATURE_COLS_RISCO = [
    "positividade",
    "positividade_trend",
    "risco_composto",
    "tests",
    "notificacoes",
    "indice_vulnerabilidade",
    "tests_trend",
    "incidencia_100k",
    "tests_ma8",
    "positividade_ma8",
]

FEATURE_COLS_SILENCIO = [
    "tests",
    "tests_ma8",
    "notificacoes",
    "semanas_sem_exame",
    "indice_vulnerabilidade",
    "solicitacoes_100k",
    "positividade",
]


def _sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except Exception:
        return False


def _make_labels(features: pd.DataFrame) -> pd.DataFrame:
    """Rótulos futuros a partir da própria série (próxima observação do par)."""
    df = features.sort_values(["municipio", "target", "epi_year", "epi_week"]).copy()
    g = df.groupby(["municipio", "target"], sort=False)
    next_tests = g["tests"].shift(-1)
    next_risco = g["risco_composto"].shift(-1) if "risco_composto" in df.columns else pd.Series(np.nan, index=df.index)
    next_pos = g["positividade"].shift(-1) if "positividade" in df.columns else pd.Series(np.nan, index=df.index)

    # Alerta futuro: risco alto OU positividade elevada com volume
    df["y_alerta"] = (
        (next_risco.fillna(0) >= 2.0)
        | ((next_pos.fillna(0) >= 0.4) & (next_tests.fillna(0) >= 3))
    ).astype(int)

    # Silêncio futuro: próxima janela sem exames
    df["y_silencio"] = (next_tests.fillna(0) <= 0).astype(int)
    return df.dropna(subset=["y_alerta", "y_silencio"])


def _matrix(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    use = [c for c in cols if c in df.columns]
    X = df[use].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return X, use


def train_and_save(features: pd.DataFrame, store_dir: Path | str = STORE) -> dict:
    """Treina GradientBoosting binário para risco e silêncio; grava em models_store."""
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meta = {"sklearn": False, "modelo_versao": "sklearn_v1", "n_rows": 0}

    if not _sklearn_available():
        (store / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    import joblib

    labeled = _make_labels(features)
    # Split temporal: treino = tudo exceto últimas ~20% semanas
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

    results = {}
    for name, cols, ycol in (
        ("risco", FEATURE_COLS_RISCO, "y_alerta"),
        ("silencio", FEATURE_COLS_SILENCIO, "y_silencio"),
    ):
        Xtr, used = _matrix(train_df, cols)
        ytr = train_df[ycol].astype(int)
        Xte, _ = _matrix(test_df, used)
        yte = test_df[ycol].astype(int)

        if ytr.nunique() < 2 or len(Xtr) < 50:
            results[name] = {"status": "skipped", "reason": "pouca variabilidade/amostra"}
            continue

        clf = GradientBoostingClassifier(
            random_state=42,
            max_depth=3,
            n_estimators=80,
            learning_rate=0.08,
        )
        clf.fit(Xtr, ytr)
        auc = None
        if len(yte) >= 20 and yte.nunique() > 1:
            try:
                auc = float(roc_auc_score(yte, clf.predict_proba(Xte)[:, 1]))
            except Exception:
                auc = None

        path = store / f"{name}_gb.joblib"
        joblib.dump({"model": clf, "features": used}, path)
        results[name] = {
            "status": "ok",
            "path": str(path.name),
            "features": used,
            "n_train": int(len(Xtr)),
            "n_test": int(len(Xte)),
            "auc_test": auc,
            "pos_rate_train": float(ytr.mean()),
        }

    meta.update({
        "sklearn": True,
        "modelo_versao": "sklearn_v1",
        "n_rows": int(len(labeled)),
        "models": results,
    })
    (store / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load_bundle(name: str, store_dir: Path | str = STORE) -> Optional[dict]:
    store = Path(store_dir)
    path = store / f"{name}_gb.joblib"
    if not path.exists() or not _sklearn_available():
        return None
    import joblib
    return joblib.load(path)


def predict_proba_bundle(bundle: dict, df: pd.DataFrame) -> np.ndarray:
    feats = bundle["features"]
    X, _ = _matrix(df, feats)
    # alinhar colunas na ordem do treino
    X = X.reindex(columns=feats, fill_value=0.0)
    return bundle["model"].predict_proba(X)[:, 1]
