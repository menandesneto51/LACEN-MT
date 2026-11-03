# -*- coding: utf-8 -*-
"""Detecção de anomalias por contagem (v2) — série semanal completa no calendário.

Substitui o critério anterior (``(atual − ma8) / ma8 ≥ 0,5``), que tinha três
problemas documentados em ``docs/avaliacao_pipeline_alertas.md``:

1. A média móvel incluía a própria semana avaliada (o sinal "diluía" a base).
2. O painel só tem linhas em semanas com exame (série esparsa): ``ma8`` era a
   média das 8 últimas semanas *observadas*, que podem cobrir meses; semanas sem
   exame (zero) nunca entravam na base.
3. Variação relativa não considera o tamanho da amostra (1 → 2 exames = +100%,
   severidade "alta").

Método v2:

* Para cada município × alvo, monta-se a série em semanas ISO consecutivas,
  preenchendo com **zero** as semanas sem exame.
* Base = média das ``janela_base`` semanas **anteriores** à semana avaliada.
* Volume / notificações: cauda superior de Poisson ``P(X ≥ atual | λ = base)``
  com λ mínimo de 0,5 (evita disparo com base zero) e excesso absoluto mínimo.
* Positividade: cauda superior binomial ``P(K ≥ positivos | n, p_base)``, com
  ``n`` mínimo e aumento mínimo de pontos percentuais.
* Avalia as ``n_semanas_avaliadas`` últimas SE do calendário (não só a última
  linha de cada série), para que a SE analisada do alerta (N−1) seja coberta
  mesmo quando a série já tem linha na SE corrente.

Saída com as mesmas colunas da v1 (``z_proxy`` mantém a variação relativa para
ordenação legada) + ``p_valor``, ``excesso_absoluto`` e ``metodo``.
Severidade continua sendo **estatística**: não é prioridade epidemiológica.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from etl.epi_week import shift_se

METODO = "poisson_binomial_calendario_v2"


def poisson_sf(k: int, lam: float) -> float:
    """P(X ≥ k) para X ~ Poisson(λ) (stdlib, estável em log)."""
    k = int(k)
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    # P(X ≤ k−1) somando termos em log; k típico < alguns milhares.
    log_term = -lam  # i = 0
    cdf = math.exp(log_term)
    for i in range(1, k):
        log_term += math.log(lam) - math.log(i)
        cdf += math.exp(log_term)
    return float(min(1.0, max(0.0, 1.0 - cdf)))


def poisson_cdf(k: int, lam: float) -> float:
    """P(X ≤ k)."""
    return 1.0 - poisson_sf(int(k) + 1, lam)


def binom_sf(k: int, n: int, p: float) -> float:
    """P(K ≥ k) para K ~ Binomial(n, p)."""
    k, n = int(k), int(n)
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    lp, lq = math.log(p), math.log1p(-p)
    tot = 0.0
    for i in range(k, n + 1):
        tot += math.exp(
            math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * lp + (n - i) * lq
        )
    return float(min(1.0, tot))


def _calendar(last: tuple[int, int], n: int) -> list[tuple[int, int]]:
    return [shift_se(last[0], last[1], -i) for i in range(n - 1, -1, -1)]


def _severidade(p: float, p_alta: float, p_moderada: float) -> str | None:
    if p < p_alta:
        return "alta"
    if p < p_moderada:
        return "moderada"
    return None


def detect_anomalias_v2(
    features: pd.DataFrame,
    *,
    n_semanas_avaliadas: int = 4,
    janela_base: int = 8,
    p_alta: float = 0.001,
    p_moderada: float = 0.01,
    min_excesso: int = 3,
    min_n_positividade: int = 5,
    min_delta_pp: float = 0.10,
    lambda_min: float = 0.5,
) -> pd.DataFrame:
    """Anomalias por contagem nas últimas SE do calendário (ver docstring do módulo)."""
    need = {"municipio", "target", "epi_year", "epi_week", "tests"}
    if features is None or features.empty or not need.issubset(features.columns):
        return pd.DataFrame()

    df = features.copy()
    df["epi_year"] = pd.to_numeric(df["epi_year"], errors="coerce")
    df["epi_week"] = pd.to_numeric(df["epi_week"], errors="coerce")
    df = df.dropna(subset=["epi_year", "epi_week"])
    if df.empty:
        return pd.DataFrame()
    df["epi_year"] = df["epi_year"].astype(int)
    df["epi_week"] = df["epi_week"].astype(int)
    last = max(zip(df["epi_year"], df["epi_week"]))
    weeks = _calendar(last, janela_base + n_semanas_avaliadas)
    idx = {yw: i for i, yw in enumerate(weeks)}
    df["_i"] = [idx.get((y, w)) for y, w in zip(df["epi_year"], df["epi_week"])]
    df = df.dropna(subset=["_i"])
    if df.empty:
        return pd.DataFrame()
    df["_i"] = df["_i"].astype(int)

    count_metrics = [m for m in ("tests", "positives", "notificacoes", "den_positividade")
                     if m in df.columns]
    for m in count_metrics:
        df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0.0)
    g = df.groupby(["municipio", "target", "_i"], as_index=False)[count_metrics].sum()
    keys = g[["municipio", "target"]].drop_duplicates().reset_index(drop=True)
    kidx = {k: j for j, k in enumerate(zip(keys["municipio"], keys["target"]))}
    T = len(weeks)
    grids: dict[str, np.ndarray] = {}
    rows_k = np.array([kidx[k] for k in zip(g["municipio"], g["target"])], dtype=int)
    for m in count_metrics:
        arr = np.zeros((len(keys), T), dtype=float)
        arr[rows_k, g["_i"].to_numpy()] = g[m].to_numpy()
        grids[m] = arr

    out: list[dict] = []
    for e in range(janela_base, T):
        ey, ew = weeks[e]
        sl = slice(e - janela_base, e)
        for metric in ("tests", "notificacoes"):
            if metric not in grids:
                continue
            arr = grids[metric]
            cur = arr[:, e]
            base = arr[:, sl].mean(axis=1)
            for j in np.nonzero((cur > 0) | (base >= 5))[0]:
                c, b = float(cur[j]), float(base[j])
                lam = max(b, lambda_min)
                if c - b >= min_excesso:
                    p = poisson_sf(int(round(c)), lam)
                    tipo = "alta_atipica"
                elif b >= 5 and b - c >= min_excesso:
                    p = poisson_cdf(int(round(c)), lam)
                    tipo = "queda_atipica"
                else:
                    continue
                sev = _severidade(p, p_alta, p_moderada)
                if not sev:
                    continue
                out.append({
                    "municipio": keys.at[j, "municipio"],
                    "target": keys.at[j, "target"],
                    "epi_year": ey,
                    "epi_week": ew,
                    "metric": metric,
                    "valor_atual": c,
                    "baseline_ma8": round(b, 3),
                    "z_proxy": round((c - b) / max(b, 1e-6), 4),
                    "p_valor": p,
                    "excesso_absoluto": round(c - b, 2),
                    "tipo_anomalia": tipo,
                    "severidade": sev,
                })
        if "positives" in grids:
            # n = resultados válidos (positivos + negativos) quando disponível
            den = grids.get("den_positividade", grids["tests"])
            n_cur = den[:, e]
            k_cur = grids["positives"][:, e]
            n_b = den[:, sl].sum(axis=1)
            k_b = grids["positives"][:, sl].sum(axis=1)
            for j in np.nonzero((n_cur >= min_n_positividade) & (n_b > 0))[0]:
                n, k = int(n_cur[j]), int(k_cur[j])
                pb = float(k_b[j] / n_b[j])
                pc = k / n if n else 0.0
                if pc - pb < min_delta_pp or k < 2:
                    continue
                p = binom_sf(k, n, max(pb, 0.01))
                sev = _severidade(p, p_alta, p_moderada)
                if not sev:
                    continue
                out.append({
                    "municipio": keys.at[j, "municipio"],
                    "target": keys.at[j, "target"],
                    "epi_year": ey,
                    "epi_week": ew,
                    "metric": "positividade",
                    "valor_atual": round(pc, 4),
                    "baseline_ma8": round(pb, 4),
                    "z_proxy": round((pc - pb) / max(pb, 1e-6), 4),
                    "p_valor": p,
                    "excesso_absoluto": round(k - pb * n, 2),
                    "tipo_anomalia": "alta_atipica",
                    "severidade": sev,
                })

    if not out:
        return pd.DataFrame()
    res = pd.DataFrame(out)
    res["acao_sugerida"] = np.where(
        res["tipo_anomalia"].eq("alta_atipica"),
        "Validar excesso frente à base de 8 SE anteriores (anomalia estatística ≠ surto).",
        "Verificar interrupção de fluxo de coleta/cadastro (queda estatística).",
    )
    res["metodo"] = METODO
    res["modelo_versao"] = "baseline_v2"
    sev_rank = {"alta": 0, "moderada": 1}
    res["_s"] = res["severidade"].map(sev_rank)
    res = res.sort_values(["epi_year", "epi_week", "_s", "p_valor"],
                          ascending=[False, False, True, True]).drop(columns="_s")
    return res.reset_index(drop=True)
