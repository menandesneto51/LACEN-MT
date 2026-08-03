
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


def log(msg: str) -> None:
    print(msg, flush=True)


def read_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception:
            continue
    raise ValueError(f"Não foi possível ler {path}")


def robust_z(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    med = s.median()
    mad = (s - med).abs().median()
    if pd.isna(mad) or mad == 0:
        std = s.std(ddof=0)
        if pd.isna(std) or std == 0:
            return pd.Series(np.zeros(len(s)), index=s.index)
        return (s - s.mean()) / std
    return 0.6745 * (s - med) / mad


def wilson_interval(pos, n, z=1.96):
    if pd.isna(n):
        return np.nan, np.nan
    try:
        n = float(n)
    except Exception:
        return np.nan, np.nan
    if n <= 0:
        return np.nan, np.nan

    pos = 0.0 if pd.isna(pos) else float(pos)
    if pos < 0:
        pos = 0.0
    if pos > n:
        pos = n

    phat = pos / n
    inner = (phat * (1 - phat) + z * z / (4 * n)) / n
    if inner < 0:
        inner = 0.0

    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(inner) / denom
    return max(0.0, center - half), min(1.0, center + half)


def poisson_ci(count, pop, z=1.96):
    if pd.isna(pop):
        return np.nan, np.nan
    try:
        count = 0.0 if pd.isna(count) else float(count)
        pop = float(pop)
    except Exception:
        return np.nan, np.nan
    if pop <= 0 or count < 0:
        return np.nan, np.nan
    rate = count / pop
    se = (math.sqrt(count) / pop) if count > 0 else (1.0 / pop)
    low = max(0.0, rate - z * se)
    high = rate + z * se
    return low * 100000, high * 100000


def ensure_vulnerability(mm: pd.DataFrame) -> pd.DataFrame:
    mm = mm.copy()
    if "indice_vulnerabilidade" in mm.columns:
        return mm
    cols = []
    if "idh" in mm.columns:
        mm["idh_inv"] = 1 - pd.to_numeric(mm["idh"], errors="coerce")
        cols.append("idh_inv")
    if "gini" in mm.columns:
        cols.append("gini")
    if "extrema_pobreza_pct" in mm.columns:
        cols.append("extrema_pobreza_pct")
    if "pea_2010" in mm.columns:
        rank = pd.to_numeric(mm["pea_2010"], errors="coerce").rank(pct=True)
        mm["pea_inv_rank"] = 1 - rank
        cols.append("pea_inv_rank")

    zcols = []
    for c in cols:
        mm[c + "_z"] = robust_z(mm[c])
        zcols.append(c + "_z")
    if zcols:
        mm["indice_vulnerabilidade"] = mm[zcols].mean(axis=1)
    else:
        mm["indice_vulnerabilidade"] = np.nan
    return mm


def main():
    ap = argparse.ArgumentParser(description="Roda somente a integração final do ecossistema LACEN integrado.")
    ap.add_argument("--outdir", default="saida_pipeline", help="Pasta saida_pipeline já preenchida pelas etapas pesadas.")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    log("[A] Lendo arquivos já prontos do saida_pipeline")

    positivity_weekly = read_csv(outdir / "positivity_by_target_epiweek_municipio.csv")
    weekly_tests = read_csv(outdir / "weekly_tests_by_target_municipio.csv")
    weekly_alerts = read_csv(outdir / "weekly_alerts.csv")
    municipal_master = ensure_vulnerability(read_csv(outdir / "municipal_master.csv"))
    pop = read_csv(outdir / "populacao_municipio.csv")
    climate = read_csv(outdir / "climate_weekly_municipio.csv")
    sinan = read_csv(outdir / "sinan_weekly_municipio.csv")
    sim = read_csv(outdir / "sim_weekly_municipio.csv")
    cnes = read_csv(outdir / "cnes_capacity_municipio.csv")

    log("[B] Harmonizando colunas")

    weekly = positivity_weekly.copy()
    if "tests" not in weekly.columns and "tests" in weekly_tests.columns:
        weekly = weekly.merge(
            weekly_tests[["epi_year", "epi_week", "target", "municipio", "tests"]],
            on=["epi_year", "epi_week", "target", "municipio"],
            how="left"
        )
    if "tests" not in weekly.columns:
        raise ValueError("Arquivo de positividade semanal não contém 'tests' e weekly_tests também não pôde suprir.")

    for col in ("positives", "negatives", "tests"):
        if col not in weekly.columns:
            weekly[col] = np.nan

    if "ano" not in weekly.columns:
        weekly["ano"] = pd.to_numeric(weekly["epi_year"], errors="coerce")

    if "ano" not in pop.columns:
        raise ValueError("populacao_municipio.csv sem coluna 'ano'.")
    pop["ano"] = pd.to_numeric(pop["ano"], errors="coerce")
    weekly = weekly.merge(pop[["municipio", "ano", "populacao"]], on=["municipio", "ano"], how="left")

    if "notificacoes_sinan" in sinan.columns and "notificacoes" not in sinan.columns:
        sinan = sinan.rename(columns={"notificacoes_sinan": "notificacoes"})
    if "notificacoes" not in sinan.columns:
        sinan["notificacoes"] = 0
    if "obitos_sinan" not in sinan.columns:
        sinan["obitos_sinan"] = 0
    if "encerrados_sinan" not in sinan.columns:
        sinan["encerrados_sinan"] = 0

    if "obitos_sim" not in sim.columns:
        sim["obitos_sim"] = 0

    weekly = weekly.merge(
        sinan[["epi_year", "epi_week", "target", "municipio", "notificacoes", "obitos_sinan", "encerrados_sinan"]],
        on=["epi_year", "epi_week", "target", "municipio"],
        how="left",
    )
    weekly = weekly.merge(
        sim[["epi_year", "epi_week", "target", "municipio", "obitos_sim"]],
        on=["epi_year", "epi_week", "target", "municipio"],
        how="left",
    )
    weekly = weekly.merge(climate, on=["municipio", "epi_year", "epi_week"], how="left")
    weekly = weekly.merge(municipal_master, on="municipio", how="left")
    weekly = weekly.merge(cnes, on="municipio", how="left")

    log("[C] Calculando taxas, IC e score de risco")

    for col in ["tests", "positives", "negatives", "notificacoes", "obitos_sinan", "encerrados_sinan", "obitos_sim", "populacao"]:
        if col in weekly.columns:
            weekly[col] = pd.to_numeric(weekly[col], errors="coerce")

    weekly["tests"] = weekly["tests"].fillna(0).clip(lower=0)
    weekly["positives"] = weekly["positives"].fillna(0).clip(lower=0)
    weekly["positives"] = np.where(weekly["positives"] > weekly["tests"], weekly["tests"], weekly["positives"])
    weekly["negatives"] = weekly["negatives"].fillna(0).clip(lower=0)
    weekly["notificacoes"] = weekly["notificacoes"].fillna(0).clip(lower=0)
    weekly["obitos_sinan"] = weekly["obitos_sinan"].fillna(0).clip(lower=0)
    weekly["encerrados_sinan"] = weekly["encerrados_sinan"].fillna(0).clip(lower=0)
    weekly["obitos_sim"] = weekly["obitos_sim"].fillna(0).clip(lower=0)

    weekly["positividade"] = np.where(weekly["tests"] > 0, weekly["positives"] / weekly["tests"], np.nan)
    weekly["solicitacoes_100k"] = np.where(weekly["populacao"] > 0, weekly["tests"] / weekly["populacao"] * 100000, np.nan)
    weekly["incidencia_100k"] = np.where(weekly["populacao"] > 0, weekly["positives"] / weekly["populacao"] * 100000, np.nan)
    weekly["notificacoes_100k"] = np.where(weekly["populacao"] > 0, weekly["notificacoes"] / weekly["populacao"] * 100000, np.nan)
    weekly["mortalidade_100k"] = np.where(weekly["populacao"] > 0, weekly["obitos_sim"] / weekly["populacao"] * 100000, np.nan)
    weekly["letalidade_proxy"] = np.where(weekly["notificacoes"] > 0, weekly["obitos_sim"] / weekly["notificacoes"], np.nan)

    pos_ci = weekly.apply(lambda r: wilson_interval(r["positives"], r["tests"]), axis=1)
    weekly["positivity_ci_low"] = [x[0] for x in pos_ci]
    weekly["positivity_ci_high"] = [x[1] for x in pos_ci]

    inc_ci = weekly.apply(lambda r: poisson_ci(r["positives"], r["populacao"]), axis=1)
    weekly["incidencia_ci_low"] = [x[0] for x in inc_ci]
    weekly["incidencia_ci_high"] = [x[1] for x in inc_ci]

    mort_ci = weekly.apply(lambda r: poisson_ci(r["obitos_sim"], r["populacao"]), axis=1)
    weekly["mortalidade_ci_low"] = [x[0] for x in mort_ci]
    weekly["mortalidade_ci_high"] = [x[1] for x in mort_ci]

    weekly["z_tests"] = weekly.groupby(["target", "municipio"], dropna=False)["tests"].transform(robust_z)
    weekly["z_pos"] = weekly.groupby(["target", "municipio"], dropna=False)["positividade"].transform(robust_z)
    weekly["z_inc"] = weekly.groupby(["target", "municipio"], dropna=False)["incidencia_100k"].transform(robust_z)
    weekly["z_notif"] = weekly.groupby(["target", "municipio"], dropna=False)["notificacoes_100k"].transform(robust_z)
    weekly["z_mort"] = weekly.groupby(["target", "municipio"], dropna=False)["mortalidade_100k"].transform(robust_z)

    for col in ["z_tests", "z_pos", "z_inc", "z_notif", "z_mort", "indice_vulnerabilidade"]:
        weekly[col] = pd.to_numeric(weekly[col], errors="coerce").fillna(0)

    # Cap z-scores to avoid extreme outliers dominating territorial ranks
    for col in ["z_tests", "z_pos", "z_inc", "z_notif", "z_mort"]:
        weekly[col] = weekly[col].clip(lower=0, upper=5)

    weekly["risco_composto"] = (
        weekly["z_tests"] * 0.25
        + weekly["z_pos"] * 0.20
        + weekly["z_inc"] * 0.20
        + weekly["z_notif"] * 0.15
        + weekly["z_mort"] * 0.10
        + weekly["indice_vulnerabilidade"].clip(lower=0, upper=5) * 0.10
    ).clip(lower=0, upper=10)
    weekly["nivel_risco"] = pd.cut(
        weekly["risco_composto"],
        bins=[-np.inf, 1, 2, 3, np.inf],
        labels=["habitual", "atencao", "alerta", "alto_alerta"]
    )

    log("[D] Gravando saídas finais")

    weekly.to_csv(outdir / "integrated_weekly_surveillance.csv", index=False, encoding="utf-8-sig")

    alerts = weekly_alerts.merge(
        weekly[[
            "epi_year", "epi_week", "target", "municipio",
            "notificacoes", "obitos_sim", "incidencia_100k", "mortalidade_100k",
            "solicitacoes_100k", "risco_composto", "nivel_risco"
        ]],
        on=["epi_year", "epi_week", "target", "municipio"],
        how="left",
    )
    alerts.to_csv(outdir / "integrated_alerts.csv", index=False, encoding="utf-8-sig")

    annual = weekly.groupby(["ano", "target"], dropna=False).agg(
        testes=("tests", "sum"),
        positivos=("positives", "sum"),
        notificacoes=("notificacoes", "sum"),
        obitos=("obitos_sim", "sum"),
        populacao=("populacao", "sum"),
        positividade_media=("positividade", "mean"),
        risco_max=("risco_composto", "max"),
    ).reset_index()
    annual["incidencia_100k"] = np.where(annual["populacao"] > 0, annual["positivos"] / annual["populacao"] * 100000, np.nan)
    annual["mortalidade_100k"] = np.where(annual["populacao"] > 0, annual["obitos"] / annual["populacao"] * 100000, np.nan)
    annual.to_csv(outdir / "integrated_annual_summary.csv", index=False, encoding="utf-8-sig")

    target_mun = weekly.groupby(["target", "municipio"], dropna=False).agg(
        semanas=("epi_week", "count"),
        testes=("tests", "sum"),
        positivos=("positives", "sum"),
        notificacoes=("notificacoes", "sum"),
        obitos=("obitos_sim", "sum"),
        positividade_media=("positividade", "mean"),
        incidencia_media_100k=("incidencia_100k", "mean"),
        risco_max=("risco_composto", "max"),
    ).reset_index()
    target_mun.to_csv(outdir / "integrated_target_municipio_summary.csv", index=False, encoding="utf-8-sig")

    state = weekly.groupby(["epi_year", "epi_week", "target"], dropna=False).agg(
        tests=("tests", "sum"),
        positives=("positives", "sum"),
        notificacoes=("notificacoes", "sum"),
        obitos=("obitos_sim", "sum"),
        populacao=("populacao", "sum")
    ).reset_index()
    state["positividade"] = np.where(state["tests"] > 0, state["positives"] / state["tests"], np.nan)
    state["incidencia_100k"] = np.where(state["populacao"] > 0, state["positives"] / state["populacao"] * 100000, np.nan)

    forecasts = []
    for target, sub in state.groupby("target"):
        sub = sub.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
        if len(sub) < 8:
            continue
        last_year = int(sub.iloc[-1]["epi_year"])
        last_week = int(sub.iloc[-1]["epi_week"])
        med_tests = sub["tests"].tail(8).median()
        med_pos = sub["positividade"].tail(8).median()
        med_inc = sub["incidencia_100k"].tail(8).median()
        med_notif = sub["notificacoes"].tail(8).median()
        med_obitos = sub["obitos"].tail(8).median()
        y, w = last_year, last_week
        for step in range(1, 5):
            w += 1
            if w > 53:
                w = 1
                y += 1
            forecasts.append({
                "target": target,
                "forecast_step": step,
                "forecast_epi_year": y,
                "forecast_epi_week": w,
                "forecast_tests": med_tests,
                "forecast_positividade": med_pos,
                "forecast_incidencia_100k": med_inc,
                "forecast_notificacoes": med_notif,
                "forecast_obitos": med_obitos,
            })
    pd.DataFrame(forecasts).to_csv(outdir / "forecast_integrated_statewide.csv", index=False, encoding="utf-8-sig")

    log("[E] Indicadores territoriais: risco, silêncio e utilização do LACEN")
    write_territorial_intelligence(weekly, outdir)

    log("[F] Sinais preditivos (módulo ML baseline)")
    try:
        from ml.run_ml_pipeline import run_ml_pipeline
        run_ml_pipeline(outdir)
    except Exception as exc:
        log(f"[AVISO] Módulo ML não executado: {exc}")

    log("[FINAL] Integração final concluída com sucesso.")


def write_territorial_intelligence(weekly: pd.DataFrame, outdir: Path) -> None:
    """Gera CSVs de municípios em risco, silenciosos e taxa de utilização do LACEN."""
    df = weekly.copy()
    for c in ("tests", "positives", "notificacoes", "populacao", "risco_composto", "positividade", "solicitacoes_100k"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "risco_composto" in df.columns:
        df["risco_composto"] = df["risco_composto"].clip(lower=0, upper=10)

    # Janela recente estadual: últimas 8 semanas epidemiológicas distintas
    weeks = (
        df[["epi_year", "epi_week"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
    )
    recent_weeks = set(map(tuple, weeks.tail(8).to_numpy()))
    df["_recent"] = df.apply(lambda r: (r["epi_year"], r["epi_week"]) in recent_weeks, axis=1)
    recent = df[df["_recent"]].copy()

    mun_target = recent.groupby(["municipio", "target"], dropna=False).agg(
        semanas=("epi_week", "count"),
        tests=("tests", "sum"),
        positives=("positives", "sum"),
        notificacoes=("notificacoes", "sum"),
        populacao=("populacao", "max"),
        risco_medio=("risco_composto", "mean"),
        risco_max=("risco_composto", "max"),
        positividade_media=("positividade", "mean"),
        solicitacoes_100k_media=("solicitacoes_100k", "mean"),
        nivel_risco_max=("nivel_risco", lambda s: s.astype(str).max() if len(s) else ""),
    ).reset_index()

    mun_target["positividade_media"] = np.where(
        mun_target["tests"] > 0,
        mun_target["positives"] / mun_target["tests"],
        mun_target["positividade_media"],
    )
    mun_target["taxa_utilizacao"] = np.where(
        mun_target["notificacoes"] > 0,
        mun_target["tests"] / mun_target["notificacoes"],
        np.where(mun_target["tests"] > 0, np.nan, 0.0),
    )
    mun_target["silencio_laboratorial"] = (
        (mun_target["tests"].fillna(0) == 0) & (mun_target["notificacoes"].fillna(0) > 0)
    )
    mun_target["baixo_uso_lacen"] = (
        (mun_target["notificacoes"].fillna(0) >= 3)
        & (mun_target["tests"].fillna(0) < np.maximum(1, mun_target["notificacoes"].fillna(0) * 0.2))
    )

    # Municípios em risco: agrega por município (máximo risco + volume)
    risco = mun_target.groupby("municipio", dropna=False).agg(
        alvos_monitorados=("target", "nunique"),
        tests_8sem=("tests", "sum"),
        positives_8sem=("positives", "sum"),
        notificacoes_8sem=("notificacoes", "sum"),
        populacao=("populacao", "max"),
        risco_medio=("risco_medio", "mean"),
        risco_max=("risco_max", "max"),
        positividade_media=("positividade_media", "mean"),
        alvos_alto_alerta=("nivel_risco_max", lambda s: int((s.astype(str) == "alto_alerta").sum())),
        alvos_alerta=("nivel_risco_max", lambda s: int(s.astype(str).isin(["alerta", "alto_alerta"]).sum())),
    ).reset_index()
    risco["score_risco_territorial"] = (
        risco["risco_max"].fillna(0).clip(0, 10) * 0.55
        + risco["risco_medio"].fillna(0).clip(0, 10) * 0.25
        + (risco["alvos_alerta"].fillna(0) / risco["alvos_monitorados"].replace(0, np.nan)).fillna(0) * 0.20
    )
    risco["faixa_risco"] = pd.cut(
        risco["score_risco_territorial"],
        bins=[-np.inf, 1.0, 2.0, 3.0, np.inf],
        labels=["habitual", "atencao", "alerta", "alto_alerta"],
    )
    risco = risco.sort_values(["score_risco_territorial", "risco_max"], ascending=False)
    risco.to_csv(outdir / "municipios_em_risco.csv", index=False, encoding="utf-8-sig")

    # Silêncio territorial: weekly costuma ser sparse (só linhas com exames).
    # Compara universo municipal com atividade recente + histórico.
    mm_path = outdir / "municipal_master.csv"
    pop_path = outdir / "populacao_municipio.csv"
    if mm_path.exists():
        mm = read_csv(mm_path)
        mm["municipio"] = mm["municipio"].astype(str).str.strip().str.upper()
        if "indice_vulnerabilidade" in mm.columns:
            mm["indice_vulnerabilidade"] = pd.to_numeric(mm["indice_vulnerabilidade"], errors="coerce")
        else:
            mm["indice_vulnerabilidade"] = 0.0
    else:
        mm = pd.DataFrame({"municipio": sorted(df["municipio"].dropna().astype(str).str.upper().unique())})
        mm["indice_vulnerabilidade"] = 0.0

    if pop_path.exists():
        pop = read_csv(pop_path)
        pop["municipio"] = pop["municipio"].astype(str).str.strip().str.upper()
        pop["ano"] = pd.to_numeric(pop.get("ano"), errors="coerce")
        pop["populacao"] = pd.to_numeric(pop.get("populacao"), errors="coerce")
        pop = pop.sort_values(["municipio", "ano"]).groupby("municipio", as_index=False).tail(1)
        mm = mm.merge(pop[["municipio", "populacao"]], on="municipio", how="left", suffixes=("", "_pop"))
        if "populacao_pop" in mm.columns:
            mm["populacao"] = mm["populacao"].fillna(mm["populacao_pop"])
            mm = mm.drop(columns=["populacao_pop"])
    if "populacao" not in mm.columns:
        mm["populacao"] = np.nan

    recent = recent.assign(municipio=recent["municipio"].astype(str).str.strip().str.upper())
    df = df.assign(municipio=df["municipio"].astype(str).str.strip().str.upper())
    act_recent = recent.groupby("municipio", dropna=False).agg(
        tests_recent=("tests", "sum"),
        notif_recent=("notificacoes", "sum"),
        positives_recent=("positives", "sum"),
        alvos_recent=("target", "nunique"),
    ).reset_index()

    act_hist = df.groupby("municipio", dropna=False).agg(
        tests_hist=("tests", "sum"),
        notif_hist=("notificacoes", "sum"),
        semanas_hist=("epi_week", "count"),
    ).reset_index()

    silencio_mun = mm.merge(act_recent, on="municipio", how="left").merge(act_hist, on="municipio", how="left")
    for c in ("tests_recent", "notif_recent", "positives_recent", "alvos_recent", "tests_hist", "notif_hist", "semanas_hist"):
        silencio_mun[c] = pd.to_numeric(silencio_mun.get(c), errors="coerce").fillna(0)
    silencio_mun["populacao"] = pd.to_numeric(silencio_mun["populacao"], errors="coerce")
    silencio_mun["indice_vulnerabilidade"] = pd.to_numeric(
        silencio_mun.get("indice_vulnerabilidade"), errors="coerce"
    ).fillna(0)

    sem_envio_recente = silencio_mun["tests_recent"] <= 0
    teve_historico = silencio_mun["tests_hist"] > 0
    notif_sem_exame = silencio_mun["notif_recent"] > 0
    pop = silencio_mun["populacao"].fillna(0)
    vuln = silencio_mun["indice_vulnerabilidade"]

    silencio_mun["classificacao_silencio"] = np.select(
        [
            sem_envio_recente & (notif_sem_exame | (teve_historico & (pop >= 5000) & (vuln >= 0.5))),
            sem_envio_recente & ((pop >= 10000) | (teve_historico & (pop >= 3000))),
            sem_envio_recente & (pop >= 3000),
            (silencio_mun["notif_recent"] >= 3)
            & (silencio_mun["tests_recent"] < np.maximum(1, silencio_mun["notif_recent"] * 0.2)),
        ],
        ["silencio_critico", "silencio_provavel", "silencio_moderado", "baixo_uso_lacen"],
        default="",
    )
    silencio_mun["tipo_sinal"] = silencio_mun["classificacao_silencio"]
    silencio_mun["score_silencio"] = (
        sem_envio_recente.astype(float) * 2.0
        + (~teve_historico & sem_envio_recente).astype(float) * 0.5
        + notif_sem_exame.astype(float) * 2.0
        + (pop >= 10000).astype(float) * 1.0
        + (pop >= 5000).astype(float) * 0.5
        + (vuln >= 0.5).astype(float) * 1.0
        + (vuln >= 1.0).astype(float) * 0.5
    )
    silenciosos = silencio_mun[silencio_mun["classificacao_silencio"] != ""].copy()

    # Complementa com sinais mun×alvo (baixo uso / silêncio com notificação)
    alvo_sinais = mun_target[mun_target["silencio_laboratorial"] | mun_target["baixo_uso_lacen"]].copy()
    if not alvo_sinais.empty:
        alvo_sinais["tipo_sinal"] = np.where(
            alvo_sinais["silencio_laboratorial"], "silencio_laboratorial", "baixo_uso_lacen"
        )
        alvo_sinais["classificacao_silencio"] = alvo_sinais["tipo_sinal"]
        alvo_sinais["score_silencio"] = np.where(alvo_sinais["silencio_laboratorial"], 3.0, 2.0)
        alvo_sinais = alvo_sinais.rename(columns={
            "tests": "tests_recent",
            "notificacoes": "notif_recent",
            "positives": "positives_recent",
        })
        keep = [
            "municipio", "target", "tests_recent", "notif_recent", "positives_recent",
            "populacao", "tipo_sinal", "classificacao_silencio", "score_silencio",
        ]
        alvo_sinais["municipio"] = alvo_sinais["municipio"].astype(str).str.strip().str.upper()
        silenciosos = pd.concat([silenciosos, alvo_sinais[keep]], ignore_index=True, sort=False)

    if "target" not in silenciosos.columns:
        silenciosos["target"] = ""
    silenciosos = silenciosos.sort_values(
        ["score_silencio", "notif_recent", "tests_recent", "municipio"],
        ascending=[False, False, True, True],
    )
    silenciosos.to_csv(outdir / "municipios_silenciosos.csv", index=False, encoding="utf-8-sig")

    util = mun_target.copy()
    util["exames_por_100_notificacoes"] = np.where(
        util["notificacoes"] > 0,
        util["tests"] / util["notificacoes"] * 100.0,
        np.nan,
    )
    # Taxa por 100 mil hab. (utilização do LACEN)
    util["exames_por_100k"] = np.where(
        util["populacao"].fillna(0) > 0,
        util["tests"] / util["populacao"] * 100000.0,
        np.nan,
    )
    util["classificacao_uso"] = np.where(
        util["silencio_laboratorial"],
        "silencio",
        np.where(
            util["baixo_uso_lacen"],
            "baixo",
            np.where(util["taxa_utilizacao"].fillna(0) >= 1.0, "adequado_ou_alto", "intermediario"),
        ),
    )
    util = util.sort_values(["taxa_utilizacao", "notificacoes"], ascending=[True, False], na_position="first")
    util.to_csv(outdir / "taxa_utilizacao_lacen.csv", index=False, encoding="utf-8-sig")

    log(
        f"[E] Gravados: municipios_em_risco.csv ({len(risco)}), "
        f"municipios_silenciosos.csv ({len(silenciosos)}), "
        f"taxa_utilizacao_lacen.csv ({len(util)})"
    )


if __name__ == "__main__":
    main()
