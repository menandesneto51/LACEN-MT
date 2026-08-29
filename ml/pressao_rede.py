# -*- coding: utf-8 -*-
"""Pressão predita da rede laboratorial (município; família quando houver dados).

Rótulo: alta pressão na próxima SE — proxy semanal do índice de pressão
(volume dinâmico + TAT/backlog/rejeição estruturais da rede) ≥55 OU pico de volume
estadual (percentil ≥0,75) OU spike vs MA8.

Artefatos locais em ml/models_store/ (não no SQL Server).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .features import prepare_weekly
from .train import (
    STORE,
    _best_threshold,
    _feature_importance,
    _fit_gb,
    _matrix,
    _precision_at_k,
    _sklearn_available,
    explain_row,
    familia_agravo,
    load_bundle,
    predict_proba_bundle,
)

FEATURE_COLS_PRESSAO = [
    "tests",
    "tests_lag1",
    "tests_ma4",
    "tests_ma8",
    "tests_trend",
    "tests_pct_estadual",
    "notificacoes",
    "notificacoes_ma4",
    "precipitation_sum_mm",
    "temperature_2m_max",
    "n_eventos_climaticos",
    "cnes_estabelecimentos",
    "cnes_leitos_total",
    "cnes_equipes_esf",
    "vizinhos_em_alerta",
    "confianca_dado",
    "tat_p90_dias",
    "tat_mediano_dias",
    "pct_liberado_48h",
    "pct_liberado_7d",
    "pct_rejeitado",
    "backlog_estimado",
    "volume_norm",
    "backlog_norm",
    "tat_p90_norm",
    "rejeicao_norm",
    "indice_pressao_proxy",
]

LABEL_NOTE = (
    "y_pressao_alta = próxima SE com indice_pressao_proxy≥55 "
    "OU tests_pct_estadual≥0,75 OU (tests≥1,5·MA8 e tests≥5). "
    "Proxy = 100×(0,40·volume_norm + 0,25·backlog_norm + 0,20·tat_p90_norm + 0,15·rejeicao_norm); "
    "volume varia por semana; TAT/backlog/rejeição vêm da rede GAL (estrutural)."
)


def _read_csv(outdir: Path, name: str) -> pd.DataFrame:
    for ext in (".parquet", ".csv"):
        path = outdir / f"{Path(name).stem}{ext}"
        if path.exists():
            try:
                if path.suffix == ".parquet":
                    return pd.read_parquet(path)
                return pd.read_csv(path, low_memory=False)
            except Exception:
                continue
    return pd.DataFrame()


def _rede_norms(rede: pd.DataFrame) -> pd.DataFrame:
    if rede is None or rede.empty or "municipio" not in rede.columns:
        return pd.DataFrame()
    out = rede.copy()
    out["municipio"] = out["municipio"].astype(str).str.strip().str.upper()
    exames = pd.to_numeric(out.get("exames"), errors="coerce").fillna(0.0)
    backlog = pd.to_numeric(out.get("backlog_estimado"), errors="coerce").fillna(0.0)
    tat_p90 = pd.to_numeric(out.get("tat_p90_dias"), errors="coerce")
    reje = pd.to_numeric(out.get("pct_rejeitado"), errors="coerce").fillna(0.0)
    p95 = max(float(exames.quantile(0.95)) if len(exames) else 1.0, 1.0)
    out["backlog_norm"] = (backlog / exames.clip(lower=1)).clip(0, 1)
    out["tat_p90_norm"] = (tat_p90.fillna(14) / 14.0).clip(0, 2) / 2.0
    out["rejeicao_norm"] = (reje / 0.05).clip(0, 2) / 2.0
    keep = [
        "municipio", "tat_p90_dias", "tat_mediano_dias", "pct_liberado_48h",
        "pct_liberado_7d", "pct_rejeitado", "backlog_estimado",
        "backlog_norm", "tat_p90_norm", "rejeicao_norm",
    ]
    return out[[c for c in keep if c in out.columns]].drop_duplicates("municipio")


def build_pressao_panel(
    weekly: pd.DataFrame,
    outdir: Optional[Path | str] = None,
    max_weeks: int = 104,
) -> pd.DataFrame:
    """Painel município-semana com proxy de pressão e contexto de rede."""
    outdir = Path(outdir) if outdir else None
    df = prepare_weekly(weekly, max_weeks=max_weeks)
    if df.empty:
        return df

    # Contexto (vizinhos / confiança) — reutiliza merge do feature store
    from .features import _merge_context

    agg_map: dict[str, str] = {"tests": "sum"}
    for c in ("notificacoes", "positives"):
        if c in df.columns:
            agg_map[c] = "sum"
    for c in (
        "precipitation_sum_mm", "temperature_2m_max", "n_eventos_climaticos",
        "cnes_estabelecimentos", "cnes_leitos_total", "cnes_equipes_esf",
        "indice_vulnerabilidade", "populacao",
    ):
        if c in df.columns:
            if c.startswith(("precip", "temp", "relative", "indice")):
                agg_map[c] = "mean"
            elif c == "n_eventos_climaticos":
                agg_map[c] = "sum"
            else:
                agg_map[c] = "max"

    panel = (
        df.groupby(["municipio", "epi_year", "epi_week"], as_index=False)
        .agg(agg_map)
        .sort_values(["municipio", "epi_year", "epi_week"])
        .reset_index(drop=True)
    )
    # dummy target for _merge_context compatibility (uses municipio only)
    panel = _merge_context(panel, outdir)

    g = panel.groupby("municipio", sort=False)
    panel["tests_lag1"] = g["tests"].shift(1)
    panel["tests_ma4"] = g["tests"].transform(lambda s: s.rolling(4, min_periods=2).mean())
    panel["tests_ma8"] = g["tests"].transform(lambda s: s.rolling(8, min_periods=3).mean())
    panel["tests_trend"] = panel["tests_ma4"] - panel["tests_ma8"]
    if "notificacoes" in panel.columns:
        panel["notificacoes_ma4"] = g["notificacoes"].transform(
            lambda s: s.rolling(4, min_periods=2).mean()
        )
    panel["tests_pct_estadual"] = panel.groupby(["epi_year", "epi_week"])["tests"].rank(pct=True)

    # Volume normalizado na semana (estadual)
    def _vol_norm(s: pd.Series) -> pd.Series:
        p95 = max(float(s.quantile(0.95)) if len(s) else 1.0, 1.0)
        return (s / p95).clip(0, 1)

    panel["volume_norm"] = panel.groupby(["epi_year", "epi_week"])["tests"].transform(_vol_norm)

    rede = _read_csv(outdir, "indicadores_rede_laboratorial.csv") if outdir else pd.DataFrame()
    rn = _rede_norms(rede)
    if not rn.empty:
        panel = panel.merge(rn, on="municipio", how="left")
    for c, default in (
        ("backlog_norm", 0.0), ("tat_p90_norm", 0.5), ("rejeicao_norm", 0.0),
        ("tat_p90_dias", np.nan), ("tat_mediano_dias", np.nan),
        ("pct_liberado_48h", np.nan), ("pct_liberado_7d", np.nan),
        ("pct_rejeitado", 0.0), ("backlog_estimado", 0.0),
    ):
        if c not in panel.columns:
            panel[c] = default
        panel[c] = pd.to_numeric(panel[c], errors="coerce")
        if c.endswith("_norm") or c in ("pct_rejeitado", "backlog_estimado"):
            panel[c] = panel[c].fillna(default if isinstance(default, float) else 0.0)

    panel["indice_pressao_proxy"] = (
        100.0 * (
            0.40 * panel["volume_norm"].fillna(0)
            + 0.25 * panel["backlog_norm"].fillna(0)
            + 0.20 * panel["tat_p90_norm"].fillna(0.5)
            + 0.15 * panel["rejeicao_norm"].fillna(0)
        )
    ).clip(0, 100).round(2)
    panel["faixa_pressao_proxy"] = pd.cut(
        panel["indice_pressao_proxy"],
        bins=[-0.01, 35, 55, 75, 100.01],
        labels=["baixa", "moderada", "alta", "critica"],
    ).astype(str)
    panel["modelo_versao"] = "pressao_v1"
    panel["rotulo_nota"] = LABEL_NOTE
    return panel


def make_pressao_labels(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["municipio", "epi_year", "epi_week"]).copy()
    g = df.groupby("municipio", sort=False)
    next_proxy = pd.to_numeric(g["indice_pressao_proxy"].shift(-1), errors="coerce")
    next_pct = pd.to_numeric(g["tests_pct_estadual"].shift(-1), errors="coerce")
    next_tests = pd.to_numeric(g["tests"].shift(-1), errors="coerce").fillna(0)
    ma8 = pd.to_numeric(df.get("tests_ma8"), errors="coerce").fillna(0)
    df["y_pressao_alta"] = (
        (next_proxy >= 55)
        | (next_pct >= 0.75)
        | ((next_tests >= 1.5 * ma8) & (next_tests >= 5) & (ma8 >= 2))
    ).astype(int)
    return df.dropna(subset=["y_pressao_alta"])


def train_pressao_model(
    panel: pd.DataFrame,
    store_dir: Path | str = STORE,
) -> dict:
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meta = {"sklearn": False, "modelo_versao": "pressao_v1", "label": LABEL_NOTE}

    if not _sklearn_available():
        path = store / "pressao_meta.json"
        path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return meta

    from sklearn.metrics import roc_auc_score
    import joblib

    labeled = make_pressao_labels(panel)
    if labeled.empty or len(labeled) < 80:
        meta["status"] = "skipped"
        meta["reason"] = "amostra insuficiente"
        (store / "pressao_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return meta

    weeks = (
        labeled[["epi_year", "epi_week"]].drop_duplicates()
        .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    )
    cut = max(1, int(len(weeks) * 0.8))
    train_w = weeks.iloc[:cut]
    test_w = weeks.iloc[cut:]
    train_df = labeled.merge(train_w, on=["epi_year", "epi_week"], how="inner").sort_values(
        ["epi_year", "epi_week"]
    )
    test_df = labeled.merge(test_w, on=["epi_year", "epi_week"], how="inner").sort_values(
        ["epi_year", "epi_week"]
    )

    Xtr, used = _matrix(train_df, FEATURE_COLS_PRESSAO)
    ytr = train_df["y_pressao_alta"].astype(int)
    Xte, _ = _matrix(test_df, used)
    yte = test_df["y_pressao_alta"].astype(int)

    if ytr.nunique() < 2 or len(Xtr) < 50:
        meta["status"] = "skipped"
        meta["reason"] = "pouca variabilidade"
        (store / "pressao_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return meta

    clf, base = _fit_gb(Xtr, ytr, calibrate=True)
    Xte = Xte.reindex(columns=used, fill_value=0.0)
    prob = clf.predict_proba(Xte)[:, 1]
    auc = None
    if len(yte) >= 20 and yte.nunique() > 1:
        try:
            auc = float(roc_auc_score(yte, prob))
        except Exception:
            auc = None
    thr, f1 = _best_threshold(yte.to_numpy(), prob)
    pak20 = _precision_at_k(yte.to_numpy(), prob, 20)
    pak50 = _precision_at_k(yte.to_numpy(), prob, 50)
    imp = _feature_importance(base, used)

    joblib.dump({
        "model": clf,
        "features": used,
        "threshold": thr,
        "familia": "global",
        "importance": imp,
        "label": LABEL_NOTE,
    }, store / "pressao_gb.joblib")

    meta.update({
        "sklearn": True,
        "status": "ok",
        "n_rows": int(len(labeled)),
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "n_train_weeks": int(len(train_w)),
        "n_test_weeks": int(len(test_w)),
        "auc_test": auc,
        "threshold": thr,
        "f1_at_threshold": f1,
        "precision_at_20": pak20,
        "precision_at_50": pak50,
        "pos_rate_train": float(ytr.mean()),
        "pos_rate_test": float(yte.mean()) if len(yte) else None,
        "importance": imp,
        "features": used,
        "familia_models": {},
    })
    (store / "pressao_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Atualiza thresholds.csv
    thr_path = store / "thresholds.csv"
    row = {
        "modelo": "pressao",
        "familia": "global",
        "threshold": thr,
        "auc": auc,
        "precision_at_20": pak20,
    }
    if thr_path.exists():
        try:
            old = pd.read_csv(thr_path)
            old = old[old["modelo"].astype(str) != "pressao"]
            pd.concat([old, pd.DataFrame([row])], ignore_index=True).to_csv(
                thr_path, index=False, encoding="utf-8-sig"
            )
        except Exception:
            pd.DataFrame([row]).to_csv(thr_path, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame([row]).to_csv(thr_path, index=False, encoding="utf-8-sig")
    return meta


def build_family_pressao_panel(weekly: pd.DataFrame, outdir: Path | str) -> pd.DataFrame:
    outdir = Path(outdir)
    df = prepare_weekly(weekly, max_weeks=104)
    if df.empty or "target" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["familia"] = df["target"].map(familia_agravo)
    panel = (
        df.groupby(["municipio", "familia", "epi_year", "epi_week"], as_index=False)
        .agg(tests=("tests", "sum"), notificacoes=("notificacoes", "sum") if "notificacoes" in df.columns else ("tests", "sum"))
        .sort_values(["municipio", "familia", "epi_year", "epi_week"])
    )
    g = panel.groupby(["municipio", "familia"], sort=False)
    panel["tests_ma4"] = g["tests"].transform(lambda s: s.rolling(4, min_periods=2).mean())
    panel["tests_ma8"] = g["tests"].transform(lambda s: s.rolling(8, min_periods=3).mean())
    panel["tests_lag1"] = g["tests"].shift(1)
    panel["tests_trend"] = panel["tests_ma4"] - panel["tests_ma8"]
    panel["tests_pct_estadual"] = panel.groupby(["epi_year", "epi_week", "familia"])["tests"].rank(pct=True)
    panel["volume_norm"] = panel.groupby(["epi_year", "epi_week", "familia"])["tests"].transform(
        lambda s: (s / max(float(s.quantile(0.95)) if len(s) else 1.0, 1.0)).clip(0, 1)
    )

    fam_rede = _read_csv(outdir, "indicadores_rede_por_familia.csv")
    if not fam_rede.empty and "granularidade" in fam_rede.columns:
        mf = fam_rede[fam_rede["granularidade"].astype(str) == "municipio_familia"].copy()
        if not mf.empty:
            mf["municipio"] = mf["municipio"].astype(str).str.strip().str.upper()
            mf["familia"] = mf["familia"].astype(str).str.strip().str.lower()
            exames = pd.to_numeric(mf.get("exames"), errors="coerce").fillna(0)
            backlog = pd.to_numeric(mf.get("backlog_estimado"), errors="coerce").fillna(0)
            tat = pd.to_numeric(mf.get("tat_p90_dias"), errors="coerce")
            reje = pd.to_numeric(mf.get("pct_rejeitado"), errors="coerce").fillna(0)
            mf["backlog_norm"] = (backlog / exames.clip(lower=1)).clip(0, 1)
            mf["tat_p90_norm"] = (tat.fillna(14) / 14.0).clip(0, 2) / 2.0
            mf["rejeicao_norm"] = (reje / 0.05).clip(0, 2) / 2.0
            keep = [
                "municipio", "familia", "tat_p90_dias", "pct_liberado_48h", "pct_rejeitado",
                "backlog_estimado", "backlog_norm", "tat_p90_norm", "rejeicao_norm",
            ]
            panel = panel.merge(mf[[c for c in keep if c in mf.columns]], on=["municipio", "familia"], how="left")

    for c in ("backlog_norm", "tat_p90_norm", "rejeicao_norm"):
        if c not in panel.columns:
            panel[c] = 0.0
        panel[c] = pd.to_numeric(panel[c], errors="coerce").fillna(0.0)

    panel["indice_pressao_proxy"] = (
        100.0 * (
            0.40 * panel["volume_norm"].fillna(0)
            + 0.25 * panel["backlog_norm"]
            + 0.20 * panel["tat_p90_norm"]
            + 0.15 * panel["rejeicao_norm"]
        )
    ).clip(0, 100).round(2)
    return panel


def train_pressao_familia(
    weekly: pd.DataFrame,
    outdir: Path | str,
    store_dir: Path | str = STORE,
) -> dict:
    """Treina GB por família quando há painel município-família suficiente."""
    store = Path(store_dir)
    if not _sklearn_available():
        return {"status": "skipped", "reason": "sklearn"}
    import joblib
    from sklearn.metrics import roc_auc_score

    panel = build_family_pressao_panel(weekly, outdir)
    if panel.empty or len(panel) < 200:
        return {"status": "skipped", "reason": "amostra família insuficiente"}

    labeled = panel.sort_values(["municipio", "familia", "epi_year", "epi_week"]).copy()
    g = labeled.groupby(["municipio", "familia"], sort=False)
    next_proxy = pd.to_numeric(g["indice_pressao_proxy"].shift(-1), errors="coerce")
    next_pct = pd.to_numeric(g["tests_pct_estadual"].shift(-1), errors="coerce")
    next_tests = pd.to_numeric(g["tests"].shift(-1), errors="coerce").fillna(0)
    ma8 = pd.to_numeric(labeled["tests_ma8"], errors="coerce").fillna(0)
    labeled["y_pressao_alta"] = (
        (next_proxy >= 55) | (next_pct >= 0.75)
        | ((next_tests >= 1.5 * ma8) & (next_tests >= 5) & (ma8 >= 2))
    ).astype(int)
    labeled = labeled.dropna(subset=["y_pressao_alta"])

    cols = [
        c for c in FEATURE_COLS_PRESSAO
        if c in labeled.columns or c in (
            "tests", "tests_lag1", "tests_ma4", "tests_ma8", "tests_trend",
            "tests_pct_estadual", "notificacoes", "volume_norm", "backlog_norm",
            "tat_p90_norm", "rejeicao_norm", "indice_pressao_proxy",
            "tat_p90_dias", "pct_liberado_48h", "pct_rejeitado", "backlog_estimado",
        )
    ]
    # restringe às colunas existentes
    cols = [c for c in [
        "tests", "tests_lag1", "tests_ma4", "tests_ma8", "tests_trend",
        "tests_pct_estadual", "notificacoes", "volume_norm", "backlog_norm",
        "tat_p90_norm", "rejeicao_norm", "indice_pressao_proxy",
        "tat_p90_dias", "pct_liberado_48h", "pct_rejeitado", "backlog_estimado",
    ] if c in labeled.columns]

    results = {}
    # Prioriza famílias com volume (arbovirose primeiro na documentação/meta)
    fam_order = ["arbovirose", "respiratorio", "tuberculose", "hepatite", "outros"]
    familias = sorted(
        labeled["familia"].dropna().unique(),
        key=lambda f: fam_order.index(str(f)) if str(f) in fam_order else 99,
    )

    for fam in familias:
        sub = labeled[labeled["familia"] == fam].copy()
        # Split temporal por semanas da própria família (evita holdout vazio em SE recentes
        # quando uma família tem cobertura densa no passado e esparsa no presente).
        fam_weeks = (
            sub[["epi_year", "epi_week"]].drop_duplicates()
            .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
        )
        if len(fam_weeks) < 6:
            results[str(fam)] = {
                "status": "skipped",
                "reason": "poucas semanas na família",
                "n_weeks": int(len(fam_weeks)),
                "n_rows": int(len(sub)),
            }
            continue
        # Mira ≥15 linhas de teste; se 20% for fino, amplia holdout até 35%
        cut_frac = 0.80
        tr = te = pd.DataFrame()
        for frac in (0.80, 0.75, 0.70, 0.65):
            cut = max(1, int(len(fam_weeks) * frac))
            if cut >= len(fam_weeks):
                cut = len(fam_weeks) - 1
            train_w, test_w = fam_weeks.iloc[:cut], fam_weeks.iloc[cut:]
            tr = sub.merge(train_w, on=["epi_year", "epi_week"], how="inner")
            te = sub.merge(test_w, on=["epi_year", "epi_week"], how="inner")
            if len(te) >= 15 and len(tr) >= 80:
                cut_frac = frac
                break
        if len(tr) < 80 or len(te) < 10 or tr["y_pressao_alta"].nunique() < 2:
            results[str(fam)] = {
                "status": "skipped",
                "reason": "amostra",
                "n_train": int(len(tr)),
                "n_test": int(len(te)),
                "n_rows": int(len(sub)),
                "nota": (
                    "Amostra insuficiente para treino/holdout estável; "
                    "pipeline segue com modelo global ou baseline logit."
                ),
            }
            continue
        Xtr, used = _matrix(tr, cols)
        ytr = tr["y_pressao_alta"].astype(int)
        Xte, _ = _matrix(te, used)
        yte = te["y_pressao_alta"].astype(int)
        if ytr.nunique() < 2:
            results[str(fam)] = {"status": "skipped", "reason": "pouca variabilidade treino"}
            continue
        clf, base = _fit_gb(Xtr, ytr, calibrate=True)
        Xte = Xte.reindex(columns=used, fill_value=0.0)
        prob = clf.predict_proba(Xte)[:, 1]
        auc = None
        if yte.nunique() > 1 and len(yte) >= 10:
            try:
                auc = float(roc_auc_score(yte, prob))
            except Exception:
                auc = None
        thr, f1 = _best_threshold(yte.to_numpy(), prob)
        imp = _feature_importance(base, used)
        joblib.dump({
            "model": clf, "features": used, "threshold": thr,
            "familia": fam, "importance": imp, "label": LABEL_NOTE,
        }, store / f"pressao_gb_{fam}.joblib")
        results[str(fam)] = {
            "status": "ok", "auc_test": auc, "threshold": thr,
            "f1_at_threshold": f1, "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
            "cut_frac_train": cut_frac,
            "precision_at_20": _precision_at_k(yte.to_numpy(), prob, 20),
        }
    return results


def backtest_pressao(panel: pd.DataFrame) -> pd.DataFrame:
    if not _sklearn_available():
        return pd.DataFrame([{
            "modelo": "pressao", "escopo": "global", "status": "skipped",
            "motivo": "sklearn indisponível",
        }])
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    labeled = make_pressao_labels(panel)
    if labeled.empty or len(labeled) < 80:
        return pd.DataFrame([{
            "modelo": "pressao", "escopo": "global", "status": "skipped",
            "motivo": "amostra insuficiente", "n": int(len(labeled)),
        }])

    weeks = (
        labeled[["epi_year", "epi_week"]].drop_duplicates()
        .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    )
    cut = max(1, int(len(weeks) * 0.8))
    train_df = labeled.merge(weeks.iloc[:cut], on=["epi_year", "epi_week"], how="inner")
    test_df = labeled.merge(weeks.iloc[cut:], on=["epi_year", "epi_week"], how="inner")
    Xtr, used = _matrix(train_df, FEATURE_COLS_PRESSAO)
    ytr = train_df["y_pressao_alta"].astype(int)
    Xte, _ = _matrix(test_df, used)
    yte = test_df["y_pressao_alta"].astype(int)
    if ytr.nunique() < 2 or len(Xte) < 20:
        return pd.DataFrame([{
            "modelo": "pressao", "escopo": "global", "status": "skipped",
            "motivo": "pouca variabilidade no holdout",
        }])
    clf = GradientBoostingClassifier(
        random_state=42, max_depth=3, n_estimators=80, learning_rate=0.08,
    )
    clf.fit(Xtr, ytr)
    Xte = Xte.reindex(columns=used, fill_value=0.0)
    prob = clf.predict_proba(Xte)[:, 1]
    thr, f1 = _best_threshold(yte.to_numpy(), prob)
    pred = (prob >= thr).astype(int)
    tp = int(((pred == 1) & (yte.to_numpy() == 1)).sum())
    fp = int(((pred == 1) & (yte.to_numpy() == 0)).sum())
    fn = int(((pred == 0) & (yte.to_numpy() == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    auc = None
    if yte.nunique() > 1:
        try:
            auc = float(roc_auc_score(yte, prob))
        except Exception:
            auc = None
    return pd.DataFrame([{
        "modelo": "pressao",
        "escopo": "global",
        "status": "ok",
        "metodo": "sklearn_gb_temporal_80_20_calibrado",
        "threshold": thr,
        "f1_at_threshold": f1,
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "n_train_weeks": int(cut),
        "n_test_weeks": int(len(weeks) - cut),
        "n": int(len(yte)),
        "n_alerta_emitido": int(pred.sum()),
        "n_confirmado": tp,
        "auc": auc,
        "precision": precision,
        "recall": recall,
        "confirmacao": precision,
        "pos_rate": float(yte.mean()),
        "precision_at_20": _precision_at_k(yte.to_numpy(), prob, 20),
        "precision_at_50": _precision_at_k(yte.to_numpy(), prob, 50),
        "rotulo": "y_pressao_alta_proxima_se",
        "rotulo_nota": LABEL_NOTE,
    }])


def score_pressao_predito(panel: pd.DataFrame) -> pd.DataFrame:
    """Escores da última SE por município."""
    if panel is None or panel.empty:
        return pd.DataFrame()
    snap = panel.sort_values(["municipio", "epi_year", "epi_week"]).groupby(
        "municipio", sort=False
    ).tail(1).copy()

    bundle = None
    try:
        bundle = load_bundle("pressao")
    except Exception:
        bundle = None

    if bundle is not None:
        probs = predict_proba_bundle(bundle, snap)
        thr = float(bundle.get("threshold", 0.35))
        metodo = "sklearn_gb_pressao_v1"
        drivers = []
        for _, row in snap.iterrows():
            try:
                drivers.append(explain_row(bundle, row))
            except Exception:
                drivers.append("")
        modelo_versao = "pressao_v1"
    else:
        # Fallback logit: proxy atual + tendência de volume
        proxy = pd.to_numeric(snap.get("indice_pressao_proxy", 0), errors="coerce").fillna(0) / 100.0
        trend = pd.to_numeric(snap.get("tests_trend", 0), errors="coerce").fillna(0)
        pct = pd.to_numeric(snap.get("tests_pct_estadual", 0), errors="coerce").fillna(0)
        logit = -1.8 + 2.5 * proxy + 0.8 * pct + 0.35 * np.tanh(trend / 10.0)
        logit = np.clip(logit, -20, 20)
        probs = 1.0 / (1.0 + np.exp(-logit))
        thr = 0.40
        metodo = "baseline_logit_pressao_v1"
        drivers = [
            f"proxy={p:.1f}; pct_estadual={pc:.2f}; trend_tests={t:.2f}"
            for p, pc, t in zip(
                pd.to_numeric(snap.get("indice_pressao_proxy", 0), errors="coerce").fillna(0),
                pct, trend,
            )
        ]
        modelo_versao = "baseline_v1"

    out = snap[["municipio", "epi_year", "epi_week"]].copy()
    out["prob_pressao_alta_proxima_janela"] = np.round(probs, 4)
    out["limiar_operacional"] = thr
    out["acima_limiar"] = out["prob_pressao_alta_proxima_janela"] >= thr
    out["faixa_pressao_predita"] = pd.cut(
        out["prob_pressao_alta_proxima_janela"],
        bins=[-0.01, 0.25, 0.40, 0.60, 1.01],
        labels=["baixa", "moderada", "alta", "critica"],
    ).astype(str)
    if "indice_pressao_proxy" in snap.columns:
        out["indice_pressao_proxy_atual"] = snap["indice_pressao_proxy"].values
    if "indice_pressao_rede" in snap.columns:
        out["indice_pressao_observado"] = snap["indice_pressao_rede"].values
    for c in ("tat_p90_dias", "pct_liberado_48h", "backlog_estimado", "tests", "tests_ma8"):
        if c in snap.columns:
            out[c] = snap[c].values
    out["drivers"] = drivers
    out["tipo_sinal"] = "Predito"
    out["acao_sugerida"] = np.where(
        out["acima_limiar"],
        "Pressão predita alta: antecipar triagem de backlog, reforçar liberação ≤48h e articular rede municipal.",
        np.where(
            out["prob_pressao_alta_proxima_janela"] >= 0.30,
            "Monitorar volume/TAT na próxima SE e revisar capacidade de liberação.",
            "Manter rotina de desempenho da rede laboratorial.",
        ),
    )
    out["metodo"] = metodo
    out["modelo_versao"] = modelo_versao
    out["rotulo_nota"] = LABEL_NOTE
    return out.sort_values(
        "prob_pressao_alta_proxima_janela", ascending=False
    ).reset_index(drop=True)


def score_pressao_familia(weekly: pd.DataFrame, outdir: Path | str) -> pd.DataFrame:
    panel = build_family_pressao_panel(weekly, outdir)
    if panel.empty:
        return pd.DataFrame()
    snap = panel.sort_values(["municipio", "familia", "epi_year", "epi_week"]).groupby(
        ["municipio", "familia"], sort=False
    ).tail(1).copy()
    rows = []
    for _, row in snap.iterrows():
        fam = str(row.get("familia", "outros"))
        bundle = None
        try:
            bundle = load_bundle("pressao", familia=fam)
            if bundle is None:
                bundle = load_bundle("pressao")
        except Exception:
            bundle = None
        if bundle is not None:
            p = float(predict_proba_bundle(bundle, pd.DataFrame([row]))[0])
            thr = float(bundle.get("threshold", 0.35))
            metodo = "sklearn_gb_pressao_familia_v1"
            try:
                drv = explain_row(bundle, row)
            except Exception:
                drv = ""
        else:
            proxy = float(pd.to_numeric(row.get("indice_pressao_proxy", 0), errors="coerce") or 0) / 100.0
            pct = float(pd.to_numeric(row.get("tests_pct_estadual", 0), errors="coerce") or 0)
            logit = np.clip(-1.8 + 2.5 * proxy + 0.8 * pct, -20, 20)
            p = float(1.0 / (1.0 + np.exp(-logit)))
            thr = 0.40
            metodo = "baseline_logit_pressao_familia_v1"
            drv = f"proxy={proxy*100:.1f}; pct={pct:.2f}"
        rows.append({
            "municipio": row["municipio"],
            "familia": fam,
            "epi_year": row.get("epi_year"),
            "epi_week": row.get("epi_week"),
            "prob_pressao_alta_proxima_janela": round(p, 4),
            "limiar_operacional": thr,
            "acima_limiar": p >= thr,
            "faixa_pressao_predita": (
                "critica" if p >= 0.60 else "alta" if p >= 0.40 else "moderada" if p >= 0.25 else "baixa"
            ),
            "indice_pressao_proxy_atual": row.get("indice_pressao_proxy"),
            "tests": row.get("tests"),
            "drivers": drv,
            "tipo_sinal": "Predito",
            "metodo": metodo,
            "modelo_versao": "pressao_v1" if metodo.startswith("sklearn") else "baseline_v1",
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        "prob_pressao_alta_proxima_janela", ascending=False
    ).reset_index(drop=True)


def run_pressao_pipeline(
    weekly: pd.DataFrame,
    outdir: Path | str,
    store_dir: Path | str = STORE,
) -> dict[str, Path]:
    """Treina, pontua e grava artefatos de pressão predita."""
    outdir = Path(outdir)
    store = Path(store_dir)
    paths: dict[str, Path] = {}

    panel = build_pressao_panel(weekly, outdir=outdir)
    meta = train_pressao_model(panel, store_dir=store)
    try:
        fam_meta = train_pressao_familia(weekly, outdir, store_dir=store)
        meta["familia_models"] = fam_meta
        (store / "pressao_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        meta["familia_models_error"] = str(exc)

    scored = score_pressao_predito(panel)
    # Anexa pressão observada (rede) se disponível
    rede = _read_csv(outdir, "indicadores_rede_laboratorial.csv")
    if not rede.empty and not scored.empty and "municipio" in rede.columns:
        from gerar_indicadores_emergencia import _indice_pressao
        try:
            rp = _indice_pressao(rede)[["municipio", "indice_pressao_rede", "faixa_pressao"]]
            scored = scored.merge(rp, on="municipio", how="left")
            scored["tipo_sinal_observado"] = "Derivado"
        except Exception:
            pass

    out_csv = outdir / "ml_pressao_rede_predito.csv"
    scored.to_csv(out_csv, index=False, encoding="utf-8-sig")
    paths["pressao"] = out_csv
    try:
        scored.to_parquet(outdir / "ml_pressao_rede_predito.parquet", index=False)
    except Exception:
        pass

    fam_scored = score_pressao_familia(weekly, outdir)
    if not fam_scored.empty:
        fam_csv = outdir / "ml_pressao_rede_familia_predito.csv"
        fam_scored.to_csv(fam_csv, index=False, encoding="utf-8-sig")
        paths["pressao_familia"] = fam_csv
        try:
            fam_scored.to_parquet(outdir / "ml_pressao_rede_familia_predito.parquet", index=False)
        except Exception:
            pass

    bt = backtest_pressao(panel)
    bt_path = outdir / "ml_pressao_rede_backtest.csv"
    bt.to_csv(bt_path, index=False, encoding="utf-8-sig")
    paths["backtest"] = bt_path
    try:
        bt.to_parquet(outdir / "ml_pressao_rede_backtest.parquet", index=False)
    except Exception:
        pass

    # Anexa ao resumo de backtest global se existir
    global_bt = outdir / "ml_backtest_summary.csv"
    if global_bt.exists() and not bt.empty:
        try:
            old = pd.read_csv(global_bt)
            old = old[old["modelo"].astype(str) != "pressao"]
            pd.concat([old, bt], ignore_index=True).to_csv(
                global_bt, index=False, encoding="utf-8-sig"
            )
        except Exception:
            pass

    return paths
