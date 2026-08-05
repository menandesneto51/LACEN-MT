# -*- coding: utf-8 -*-
"""Inferência baseline (sem sklearn): forecast, anomalia, risco e silêncio preditos."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .features import latest_week_snapshot, prepare_weekly


def _sigmoid(x: np.ndarray | pd.Series) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    x = np.clip(x, -20, 20)
    return 1.0 / (1.0 + np.exp(-x))


def _advance_epiweek(year: int, week: int, steps: int = 1) -> tuple[int, int]:
    y, w = int(year), int(week)
    for _ in range(steps):
        w += 1
        if w > 53:
            w = 1
            y += 1
    return y, w


def forecast_demanda(weekly: pd.DataFrame, horizon: int = 4) -> pd.DataFrame:
    """Previsão estadual por alvo: média móvel exponencial das últimas 8 semanas."""
    df = prepare_weekly(weekly)
    state = (
        df.groupby(["epi_year", "epi_week", "target"], as_index=False)
        .agg(
            tests=("tests", "sum"),
            positives=("positives", "sum"),
            notificacoes=("notificacoes", "sum") if "notificacoes" in df.columns else ("tests", "sum"),
            populacao=("populacao", "sum") if "populacao" in df.columns else ("tests", "size"),
        )
        .sort_values(["target", "epi_year", "epi_week"])
    )
    if "positividade" not in state.columns:
        state["positividade"] = np.where(state["tests"] > 0, state["positives"] / state["tests"], np.nan)

    rows = []
    for target, sub in state.groupby("target"):
        sub = sub.reset_index(drop=True)
        if len(sub) < 6:
            continue
        tail = sub.tail(8)
        # EWMA simples
        ewma_tests = float(tail["tests"].ewm(span=4, adjust=False).mean().iloc[-1])
        ewma_pos = float(tail["positividade"].ewm(span=4, adjust=False).mean().iloc[-1])
        ewma_notif = float(tail["notificacoes"].ewm(span=4, adjust=False).mean().iloc[-1])
        hist_std = float(tail["tests"].std(ddof=0) or 0.0)
        last_y, last_w = int(sub.iloc[-1]["epi_year"]), int(sub.iloc[-1]["epi_week"])
        for step in range(1, horizon + 1):
            fy, fw = _advance_epiweek(last_y, last_w, step)
            # intervalo empírico ±1 desvio
            rows.append({
                "target": target,
                "forecast_step": step,
                "forecast_epi_year": fy,
                "forecast_epi_week": fw,
                "forecast_tests": round(ewma_tests, 2),
                "forecast_tests_low": round(max(0.0, ewma_tests - hist_std), 2),
                "forecast_tests_high": round(ewma_tests + hist_std, 2),
                "forecast_positividade": round(float(np.nan_to_num(ewma_pos, nan=0.0)), 4),
                "forecast_notificacoes": round(ewma_notif, 2),
                "metodo": "ewma_span4_tail8",
                "modelo_versao": "baseline_v1",
            })
    return pd.DataFrame(rows)


def detect_anomalias(features: pd.DataFrame, z_threshold: float = 2.5) -> pd.DataFrame:
    """Anomalias na última semana: desvio vs média móvel 8 semanas."""
    snap = latest_week_snapshot(features)
    if snap.empty:
        return pd.DataFrame()

    rows = []
    for metric in ("tests", "positividade", "incidencia_100k", "notificacoes"):
        ma = f"{metric}_ma8"
        if metric not in snap.columns or ma not in snap.columns:
            continue
        cur = pd.to_numeric(snap[metric], errors="coerce")
        base = pd.to_numeric(snap[ma], errors="coerce")
        # desvio relativo robusto
        denom = base.abs().clip(lower=1e-6)
        z_proxy = (cur - base) / denom
        # também usa z histórico se existir na série completa
        tmp = snap.copy()
        tmp["z_proxy"] = z_proxy
        tmp["metric"] = metric
        tmp["valor_atual"] = cur
        tmp["baseline_ma8"] = base
        flag = tmp["z_proxy"].abs() >= (z_threshold / 5.0)  # limiar relativo ~0.5
        # reforço: se tests atual >> ma8
        if metric == "tests":
            flag = flag | ((cur >= 5) & (cur >= base * 2.0))
        if metric == "positividade":
            flag = flag | ((cur >= 0.35) & (cur - base >= 0.15))
        hit = tmp.loc[flag].copy()
        if hit.empty:
            continue
        hit["tipo_anomalia"] = np.where(hit["z_proxy"] >= 0, "alta_atipica", "queda_atipica")
        hit["severidade"] = np.where(hit["z_proxy"].abs() >= 1.0, "alta", np.where(hit["z_proxy"].abs() >= 0.5, "moderada", "baixa"))
        hit["acao_sugerida"] = np.where(
            hit["tipo_anomalia"].eq("alta_atipica"),
            "Investigar pico atípico e validar capacidade laboratorial/vigilância.",
            "Verificar possível interrupção de fluxo de coleta ou subnotificação.",
        )
        cols = [
            "municipio", "target", "epi_year", "epi_week", "metric",
            "valor_atual", "baseline_ma8", "z_proxy", "tipo_anomalia", "severidade",
            "acao_sugerida",
        ]
        rows.append(hit[[c for c in cols if c in hit.columns]])

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["modelo_versao"] = "baseline_v1"
    sev_rank = {"alta": 0, "moderada": 1, "baixa": 2}
    out["_sev"] = out["severidade"].map(sev_rank).fillna(9)
    out = out.sort_values(["_sev", "z_proxy"], ascending=[True, False]).drop(columns=["_sev"])
    return out.reset_index(drop=True)


# Bandas institucionais (absoluto ∩ percentil estadual)
BANDAS_RISCO = ("Baixo", "Moderado", "Alto", "Crítico")
BAND_RANK = {b: i for i, b in enumerate(BANDAS_RISCO)}
LEGENDA_BANDAS_RISCO = (
    "Bandas combinam severidade absoluta (risco composto / positividade / limiar ML) "
    "e percentil estadual da probabilidade predita na família do agravo. "
    "A banda final é o maior entre absoluto e percentil."
)


def _banda_absoluta_row(
    risco_composto: float,
    positividade: float,
    tests: float,
    acima_limiar: bool,
    nivel_risco: str = "",
) -> str:
    """Severidade operacional absoluta (não relativa à distribuição)."""
    nivel = str(nivel_risco or "").strip().lower()
    r = float(risco_composto or 0.0)
    pos = float(positividade or 0.0)
    t = float(tests or 0.0)
    # Alinha aos cortes de nivel_risco do weekly (1 / 2 / 3)
    if nivel == "alto_alerta" or r >= 3.0 or (acima_limiar and r >= 2.0 and pos >= 0.35 and t >= 3):
        return "Crítico"
    if nivel == "alerta" or r >= 2.0 or acima_limiar or (pos >= 0.50 and t >= 2):
        return "Alto"
    if nivel == "atencao" or r >= 1.0 or (pos >= 0.25 and t >= 1):
        return "Moderado"
    return "Baixo"


def _banda_from_percentil(pct: float) -> str:
    """Posição relativa estadual (0–100)."""
    p = float(pct if pd.notna(pct) else 0.0)
    if p >= 90:
        return "Crítico"
    if p >= 75:
        return "Alto"
    if p >= 50:
        return "Moderado"
    return "Baixo"


def _max_banda(a: str, b: str) -> str:
    return a if BAND_RANK.get(a, 0) >= BAND_RANK.get(b, 0) else b


def aplicar_bandas_risco(out: pd.DataFrame, snap: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Enriquece ml_risco_predito com bandas absoluta + percentil + combinada.
    Preferencialmente usa colunas do snapshot de features (risco_composto, etc.).
    """
    if out is None or out.empty:
        return out if out is not None else pd.DataFrame()

    df = out.copy()
    if snap is not None and not snap.empty:
        keys = [c for c in ("municipio", "target", "epi_year", "epi_week") if c in df.columns and c in snap.columns]
        extras = [c for c in ("risco_composto", "positividade", "tests", "nivel_risco") if c in snap.columns]
        if keys and extras:
            meta = snap[keys + extras].drop_duplicates(subset=keys, keep="last")
            df = df.merge(meta, on=keys, how="left", suffixes=("", "_snap"))

    risco = pd.to_numeric(df.get("risco_composto", 0), errors="coerce").fillna(0)
    pos = pd.to_numeric(df.get("positividade", 0), errors="coerce").fillna(0)
    tests = pd.to_numeric(df.get("tests", 0), errors="coerce").fillna(0)
    acima = df.get("acima_limiar", False)
    if not isinstance(acima, pd.Series):
        acima = pd.Series(False, index=df.index)
    else:
        acima = acima.fillna(False).astype(bool)
    nivel = df["nivel_risco"].astype(str) if "nivel_risco" in df.columns else pd.Series("", index=df.index)

    df["risco_composto"] = np.round(risco, 4)
    df["banda_absoluta"] = [
        _banda_absoluta_row(r, p, t, bool(a), n)
        for r, p, t, a, n in zip(risco, pos, tests, acima, nivel)
    ]

    # Percentil estadual da probabilidade predita (por família; fallback global)
    prob = pd.to_numeric(df.get("prob_alerta_proxima_janela", 0), errors="coerce")
    pct = pd.Series(np.nan, index=df.index, dtype=float)
    if "familia" in df.columns:
        for _, idx in df.groupby("familia", dropna=False).groups.items():
            sub = prob.loc[idx]
            if sub.notna().sum() >= 2:
                pct.loc[idx] = sub.rank(method="average", pct=True) * 100.0
            elif sub.notna().sum() == 1:
                pct.loc[idx] = 50.0
    if pct.isna().all() and prob.notna().any():
        pct = prob.rank(method="average", pct=True) * 100.0
    df["percentil_estadual"] = np.round(pct.fillna(0), 1)
    df["banda_percentil"] = df["percentil_estadual"].map(_banda_from_percentil)
    df["banda_risco"] = [
        _max_banda(a, p) for a, p in zip(df["banda_absoluta"], df["banda_percentil"])
    ]
    df["criterio_banda"] = np.where(
        df["banda_absoluta"].map(BAND_RANK) > df["banda_percentil"].map(BAND_RANK),
        "absoluto",
        np.where(
            df["banda_percentil"].map(BAND_RANK) > df["banda_absoluta"].map(BAND_RANK),
            "percentil",
            "ambos",
        ),
    )
    df["legenda_banda"] = LEGENDA_BANDAS_RISCO
    return df


def score_risco_predito(features: pd.DataFrame) -> pd.DataFrame:
    """Probabilidade operacional de município-alvo estar em alerta na próxima janela."""
    snap = latest_week_snapshot(features)
    if snap.empty:
        return pd.DataFrame()

    from ml.train import familia_agravo, explain_row, load_bundle, predict_proba_bundle

    snap = snap.copy()
    snap["familia"] = snap["target"].map(familia_agravo)

    probs = np.zeros(len(snap), dtype=float)
    metodos = []
    thresholds = []
    drivers_ml = []
    for i, (_, row) in enumerate(snap.iterrows()):
        fam = row.get("familia", "outros")
        bundle = None
        try:
            bundle = load_bundle("risco", familia=str(fam))
            if bundle is None:
                bundle = load_bundle("risco")
        except Exception:
            bundle = None
        if bundle is not None:
            p = float(predict_proba_bundle(bundle, pd.DataFrame([row]))[0])
            probs[i] = p
            thr = float(bundle.get("threshold", 0.25))
            thresholds.append(thr)
            metodos.append("sklearn_gb_v2_familia" if bundle.get("familia") not in (None, "global") else "sklearn_gb_v2")
            try:
                drivers_ml.append(explain_row(bundle, row))
            except Exception:
                drivers_ml.append("")
        else:
            pos = float(pd.to_numeric(row.get("positividade", 0), errors="coerce") or 0)
            pos_t = float(pd.to_numeric(row.get("positividade_trend", 0), errors="coerce") or 0)
            risco = float(pd.to_numeric(row.get("risco_composto", 0), errors="coerce") or 0)
            tests = float(pd.to_numeric(row.get("tests", 0), errors="coerce") or 0)
            notif = float(pd.to_numeric(row.get("notificacoes", 0), errors="coerce") or 0)
            vuln = float(pd.to_numeric(row.get("indice_vulnerabilidade", 0), errors="coerce") or 0)
            tests_t = float(pd.to_numeric(row.get("tests_trend", 0), errors="coerce") or 0)
            logit = (
                -2.2 + 2.8 * pos + 1.5 * np.tanh(pos_t * 5) + 0.35 * min(risco, 10)
                + 0.15 * np.log1p(tests) + 0.12 * np.log1p(notif)
                + 0.25 * np.clip(vuln, -3, 3) + 0.4 * np.tanh(tests_t / 5.0)
            )
            probs[i] = float(_sigmoid(np.array([logit]))[0])
            thresholds.append(0.25)
            metodos.append("baseline_logit_v1")
            drivers_ml.append("")

    pos = pd.to_numeric(snap.get("positividade", 0), errors="coerce").fillna(0)
    pos_t = pd.to_numeric(snap.get("positividade_trend", 0), errors="coerce").fillna(0)
    risco = pd.to_numeric(snap.get("risco_composto", 0), errors="coerce").fillna(0)

    out = snap[["municipio", "target", "epi_year", "epi_week"]].copy()
    out["familia"] = snap["familia"].values
    out["prob_alerta_proxima_janela"] = np.round(probs, 4)
    out["limiar_operacional"] = thresholds
    out["acima_limiar"] = out["prob_alerta_proxima_janela"] >= out["limiar_operacional"]
    out["faixa_predita"] = pd.cut(
        out["prob_alerta_proxima_janela"],
        bins=[-0.01, 0.15, 0.30, 0.50, 1.01],
        labels=["baixo", "moderado", "alto", "muito_alto"],
    ).astype(str)
    out["drivers"] = [
        (d if d else f"positividade={p:.2f}; tendencia_pos={t:.3f}; risco={r:.2f}")
        for d, p, t, r in zip(drivers_ml, pos, pos_t, risco)
    ]
    out["tipo_sinal"] = "predito"
    out["acao_sugerida"] = np.where(
        out["acima_limiar"],
        "Priorizar monitoramento ativo e articulação com vigilância municipal.",
        np.where(
            out["prob_alerta_proxima_janela"] >= 0.20,
            "Acompanhar tendência semanal e reforçar coleta se houver sintoma clínico.",
            "Manter rotina de vigilância laboratorial.",
        ),
    )
    out["metodo"] = metodos
    out["modelo_versao"] = np.where(
        pd.Series(metodos).astype(str).str.startswith("sklearn"), "sklearn_v2", "baseline_v1"
    )
    out = aplicar_bandas_risco(out, snap)
    return out.sort_values("prob_alerta_proxima_janela", ascending=False).reset_index(drop=True)


def score_silencio_predito(features: pd.DataFrame) -> pd.DataFrame:
    """Probabilidade de silêncio laboratorial (sem exames) na próxima janela."""
    snap = latest_week_snapshot(features)
    if snap.empty:
        return pd.DataFrame()

    try:
        from ml.train import load_bundle, predict_proba_bundle
        bundle = load_bundle("silencio")
    except Exception:
        bundle = None

    tests = pd.to_numeric(snap.get("tests", 0), errors="coerce").fillna(0)
    tests_ma8 = pd.to_numeric(snap.get("tests_ma8", 0), errors="coerce").fillna(0)
    notif = pd.to_numeric(snap.get("notificacoes", 0), errors="coerce").fillna(0)
    weeks_zero = pd.to_numeric(snap.get("semanas_sem_exame", 0), errors="coerce").fillna(0)
    vuln = pd.to_numeric(snap.get("indice_vulnerabilidade", 0), errors="coerce").fillna(0)
    uso = pd.to_numeric(snap.get("solicitacoes_100k", 0), errors="coerce").fillna(0)

    if bundle is not None:
        prob = predict_proba_bundle(bundle, snap)
        metodo = "sklearn_gb_v2"
        thr = float(bundle.get("threshold", 0.5))
    else:
        logit = (
            -1.0
            + 0.55 * weeks_zero.clip(0, 12)
            + 0.8 * (tests <= 0).astype(float)
            + 0.35 * (tests_ma8 < 1).astype(float)
            + 0.25 * np.log1p(notif)
            + 0.2 * vuln.clip(-3, 3)
            - 0.15 * np.log1p(uso.clip(lower=0))
        )
        if "vizinhos_em_alerta" in snap.columns:
            logit = logit + 0.35 * pd.to_numeric(snap["vizinhos_em_alerta"], errors="coerce").fillna(0).clip(0, 6)
        prob = _sigmoid(logit)
        metodo = "baseline_logit_v1"
        thr = 0.55

    out = snap[["municipio", "target", "epi_year", "epi_week"]].copy()
    out["prob_silencio_proxima_janela"] = np.round(prob, 4)
    out["limiar_operacional"] = thr
    out["acima_limiar"] = out["prob_silencio_proxima_janela"] >= thr
    out["tests_ultima_semana"] = tests
    out["tests_ma8"] = tests_ma8
    out["notificacoes_ultima_semana"] = notif
    out["semanas_sem_exame"] = weeks_zero
    out["faixa_silencio_predita"] = pd.cut(
        out["prob_silencio_proxima_janela"],
        bins=[-0.01, 0.35, 0.55, 0.75, 1.01],
        labels=["sem_silencio_aparente", "silencio_moderado", "silencio_provavel", "silencio_critico"],
    ).astype(str)
    out["tipo_sinal"] = "predito"
    out["acao_sugerida"] = np.where(
        out["acima_limiar"],
        "Busca ativa: verificar fluxo de coleta/envio e sensibilizar vigilância municipal.",
        np.where(
            out["prob_silencio_proxima_janela"] >= 0.45,
            "Revisar cobertura de testagem e histórico de utilização do LACEN.",
            "Manter acompanhamento de rotina.",
        ),
    )
    out["metodo"] = metodo
    out["modelo_versao"] = "sklearn_v2" if metodo.startswith("sklearn") else "baseline_v1"
    return out.sort_values("prob_silencio_proxima_janela", ascending=False).reset_index(drop=True)
