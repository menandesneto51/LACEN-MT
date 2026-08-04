# -*- coding: utf-8 -*-
"""Treino sklearn com validação temporal, calibração e modelos por família."""
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
    "precipitation_sum_mm",
    "temperature_2m_max",
    "n_eventos_climaticos",
    "cnes_estabelecimentos",
    "cnes_leitos_total",
    "cnes_equipes_esf",
    "vizinhos_em_alerta",
    "confianca_dado",
    "gap_sinan_sem_exame",
    "exames_por_notif",
    "tests_pct_estadual",
    "semanas_consec_sem_exame",
]

FEATURE_COLS_SILENCIO = [
    "tests",
    "tests_ma8",
    "notificacoes",
    "semanas_sem_exame",
    "semanas_consec_sem_exame",
    "indice_vulnerabilidade",
    "solicitacoes_100k",
    "positividade",
    "vizinhos_em_alerta",
    "silencio_com_vizinho_alerta",
    "confianca_dado",
    "gap_sinan_sem_exame",
    "cnes_estabelecimentos",
    "exames_por_notif",
]

FAMILIAS = ("arbovirose", "tuberculose", "hepatite", "respiratorio", "outros")


def familia_agravo(target: object) -> str:
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


def _sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except Exception:
        return False


def _make_labels(features: pd.DataFrame) -> pd.DataFrame:
    """
    Rótulos futuros (SE+1 / SE+2) — híbrido lab + epi.
    y_alerta: aumento de positivos/notif OU risco/positividade elevados.
    y_silencio: próxima janela sem exames (reforçado se há notif ou vizinho).
    """
    df = features.sort_values(["municipio", "target", "epi_year", "epi_week"]).copy()
    g = df.groupby(["municipio", "target"], sort=False)

    next_tests = g["tests"].shift(-1)
    next2_tests = g["tests"].shift(-2)
    next_risco = g["risco_composto"].shift(-1) if "risco_composto" in df.columns else 0
    next_pos = g["positividade"].shift(-1) if "positividade" in df.columns else 0
    next_pos2 = g["positividade"].shift(-2) if "positividade" in df.columns else 0
    next_posi = g["positives"].shift(-1) if "positives" in df.columns else 0
    next_notif = g["notificacoes"].shift(-1) if "notificacoes" in df.columns else 0
    cur_posi = df["positives"] if "positives" in df.columns else 0

    next_risco = pd.to_numeric(next_risco, errors="coerce").fillna(0)
    next_pos = pd.to_numeric(next_pos, errors="coerce").fillna(0)
    next_pos2 = pd.to_numeric(next_pos2, errors="coerce").fillna(0)
    next_posi = pd.to_numeric(next_posi, errors="coerce").fillna(0)
    next_notif = pd.to_numeric(next_notif, errors="coerce").fillna(0)
    next_tests = pd.to_numeric(next_tests, errors="coerce").fillna(0)
    next2_tests = pd.to_numeric(next2_tests, errors="coerce").fillna(0)
    cur_posi = pd.to_numeric(cur_posi, errors="coerce").fillna(0)

    # Alerta confirmável: limiares mais realistas + tendência de positivos + SINAN
    df["y_alerta"] = (
        (next_risco >= 1.2)
        | ((next_pos >= 0.25) & (next_tests >= 2))
        | ((next_pos2 >= 0.25) & (next2_tests >= 2))
        | (next_posi >= 2)
        | ((next_posi > cur_posi) & (next_posi >= 1) & (next_tests >= 2))
        | ((next_notif >= 3) & (next_tests >= 1) & (next_pos >= 0.15))
    ).astype(int)

    # Silêncio operacional
    sil_op = next_tests <= 0
    # Silêncio epidemiológico-laboratorial (mais grave)
    viz = df["vizinhos_em_alerta"] if "vizinhos_em_alerta" in df.columns else 0
    viz = pd.to_numeric(viz, errors="coerce").fillna(0)
    sil_epi = sil_op & ((next_notif > 0) | (viz > 0))
    df["y_silencio"] = sil_op.astype(int)
    df["y_silencio_epi"] = sil_epi.astype(int)
    df["familia"] = df["target"].map(familia_agravo)
    return df.dropna(subset=["y_alerta", "y_silencio"])


def _matrix(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    use = [c for c in cols if c in df.columns]
    X = df[use].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return X, use


def _best_threshold(y_true: np.ndarray, y_prob: np.ndarray) -> tuple[float, float]:
    """Escolhe limiar que maximiza F1 (útil com classe rara)."""
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    best_t, best_f1 = 0.5, -1.0
    for t in np.linspace(0.05, 0.85, 17):
        pred = (y_prob >= t).astype(int)
        tp = ((pred == 1) & (y_true == 1)).sum()
        fp = ((pred == 1) & (y_true == 0)).sum()
        fn = ((pred == 0) & (y_true == 1)).sum()
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t, float(best_f1)


def _precision_at_k(y_true: np.ndarray, y_prob: np.ndarray, k: int = 50) -> float:
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    if len(y_true) == 0:
        return float("nan")
    k = min(k, len(y_true))
    order = np.argsort(-y_prob)[:k]
    return float(y_true[order].mean())


def _fit_gb(Xtr, ytr, calibrate: bool = True):
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.calibration import CalibratedClassifierCV

    base = GradientBoostingClassifier(
        random_state=42, max_depth=3, n_estimators=80, learning_rate=0.08,
    )
    if calibrate and len(Xtr) >= 200 and ytr.nunique() > 1:
        # split interno temporal aproximado: últimas 20% linhas (já ordenadas por semana no caller)
        cut = max(50, int(len(Xtr) * 0.8))
        if cut < len(Xtr) - 20 and ytr.iloc[:cut].nunique() > 1 and ytr.iloc[cut:].nunique() > 1:
            try:
                clf = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
                base.fit(Xtr.iloc[:cut], ytr.iloc[:cut])
                clf.fit(Xtr.iloc[cut:], ytr.iloc[cut:])
                return clf, base
            except Exception:
                pass
    base.fit(Xtr, ytr)
    return base, base


def _feature_importance(model, feature_names: list[str]) -> list[dict]:
    raw = getattr(model, "feature_importances_", None)
    if raw is None and hasattr(model, "estimator"):
        raw = getattr(model.estimator, "feature_importances_", None)
    if raw is None and hasattr(model, "calibrated_classifiers_"):
        try:
            raw = model.calibrated_classifiers_[0].estimator.feature_importances_
        except Exception:
            raw = None
    if raw is None:
        return []
    pairs = sorted(zip(feature_names, map(float, raw)), key=lambda x: -x[1])
    return [{"feature": f, "importance": round(v, 5)} for f, v in pairs[:15]]


def train_and_save(features: pd.DataFrame, store_dir: Path | str = STORE) -> dict:
    """Treina GB global + por família; calibra limiares; grava joblibs + meta."""
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meta = {"sklearn": False, "modelo_versao": "sklearn_v2", "n_rows": 0}

    if not _sklearn_available():
        (store / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    from sklearn.metrics import roc_auc_score
    import joblib

    labeled = _make_labels(features)
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
    train_df = labeled[labeled["_split"] == "train"].sort_values(["epi_year", "epi_week"])
    test_df = labeled[labeled["_split"] == "test"].sort_values(["epi_year", "epi_week"])

    results = {}

    def _train_one(name: str, cols: list[str], ycol: str, train: pd.DataFrame, test: pd.DataFrame, tag: str = "global"):
        Xtr, used = _matrix(train, cols)
        ytr = train[ycol].astype(int)
        Xte, _ = _matrix(test, used)
        yte = test[ycol].astype(int)
        if ytr.nunique() < 2 or len(Xtr) < 50:
            return {"status": "skipped", "reason": "pouca variabilidade/amostra", "tag": tag}
        clf, base = _fit_gb(Xtr, ytr, calibrate=True)
        Xte = Xte.reindex(columns=used, fill_value=0.0)
        prob = clf.predict_proba(Xte)[:, 1]
        auc = None
        if len(yte) >= 20 and yte.nunique() > 1:
            try:
                auc = float(roc_auc_score(yte, clf.predict_proba(Xte)[:, 1]))
            except Exception:
                auc = None
        thr, f1 = _best_threshold(yte.to_numpy(), prob)
        pak20 = _precision_at_k(yte.to_numpy(), prob, 20)
        pak50 = _precision_at_k(yte.to_numpy(), prob, 50)
        imp = _feature_importance(base, used)
        suffix = "" if tag == "global" else f"_{tag}"
        path = store / f"{name}_gb{suffix}.joblib"
        joblib.dump({
            "model": clf,
            "features": used,
            "threshold": thr,
            "familia": tag,
            "importance": imp,
        }, path)
        return {
            "status": "ok",
            "path": str(path.name),
            "tag": tag,
            "features": used,
            "n_train": int(len(Xtr)),
            "n_test": int(len(Xte)),
            "auc_test": auc,
            "threshold": thr,
            "f1_at_threshold": f1,
            "precision_at_20": pak20,
            "precision_at_50": pak50,
            "pos_rate_train": float(ytr.mean()),
            "importance": imp,
        }

    for name, cols, ycol in (
        ("risco", FEATURE_COLS_RISCO, "y_alerta"),
        ("silencio", FEATURE_COLS_SILENCIO, "y_silencio"),
    ):
        results[name] = _train_one(name, cols, ycol, train_df, test_df, "global")

        # Modelos por família (risco)
        if name == "risco":
            fam_results = {}
            for fam in FAMILIAS:
                tr = train_df[train_df["familia"] == fam]
                te = test_df[test_df["familia"] == fam]
                if len(tr) < 80 or len(te) < 15:
                    fam_results[fam] = {"status": "skipped", "reason": "amostra insuficiente"}
                    continue
                fam_results[fam] = _train_one(name, cols, ycol, tr, te, fam)
            results[f"{name}_por_familia"] = fam_results

    meta.update({
        "sklearn": True,
        "modelo_versao": "sklearn_v2",
        "n_rows": int(len(labeled)),
        "n_train_weeks": int(len(train_w)),
        "n_test_weeks": int(len(test_w)),
        "models": results,
    })
    (store / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Limiares operacionais resumidos
    thr_rows = []
    for k, v in results.items():
        if isinstance(v, dict) and v.get("threshold") is not None:
            thr_rows.append({"modelo": k, "familia": "global", "threshold": v["threshold"],
                             "auc": v.get("auc_test"), "precision_at_20": v.get("precision_at_20")})
        if k.endswith("_por_familia") and isinstance(v, dict):
            for fam, fv in v.items():
                if isinstance(fv, dict) and fv.get("threshold") is not None:
                    thr_rows.append({"modelo": "risco", "familia": fam, "threshold": fv["threshold"],
                                     "auc": fv.get("auc_test"), "precision_at_20": fv.get("precision_at_20")})
    if thr_rows:
        pd.DataFrame(thr_rows).to_csv(store / "thresholds.csv", index=False, encoding="utf-8-sig")
    return meta


def load_bundle(name: str, store_dir: Path | str = STORE, familia: Optional[str] = None) -> Optional[dict]:
    store = Path(store_dir)
    if familia and familia != "global":
        path = store / f"{name}_gb_{familia}.joblib"
        if path.exists() and _sklearn_available():
            import joblib
            return joblib.load(path)
    path = store / f"{name}_gb.joblib"
    if not path.exists() or not _sklearn_available():
        return None
    import joblib
    return joblib.load(path)


def predict_proba_bundle(bundle: dict, df: pd.DataFrame) -> np.ndarray:
    feats = bundle["features"]
    X, _ = _matrix(df, feats)
    X = X.reindex(columns=feats, fill_value=0.0)
    return bundle["model"].predict_proba(X)[:, 1]


def explain_row(bundle: dict, row: pd.Series, top_n: int = 5) -> str:
    """Explicação simples: importância × |valor| das features."""
    feats = bundle.get("features") or []
    imp_list = bundle.get("importance") or []
    imp = {d["feature"]: d["importance"] for d in imp_list}
    scored = []
    for f in feats:
        val = float(pd.to_numeric(row.get(f, 0), errors="coerce") or 0.0)
        w = float(imp.get(f, 0.0))
        scored.append((f, abs(val) * (w + 1e-6), val, w))
    scored.sort(key=lambda x: -x[1])
    parts = [f"{f}={v:.3g} (imp={w:.3g})" for f, _, v, w in scored[:top_n]]
    return "; ".join(parts)
