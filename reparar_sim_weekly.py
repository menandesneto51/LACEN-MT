# -*- coding: utf-8 -*-
"""Reconstrói sim_weekly_municipio.csv a partir do SIM bruto (DataObito/AnoObito)."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def _infer_target(causa: object) -> str:
    t = str(causa or "").casefold()
    rules = (
        ("dengue", "dengue"),
        ("zika", "zika"),
        ("chikungunya", "chikungunya"),
        ("tubercul", "tuberculose"),
        ("hepatite", "hepatite"),
        ("influenza", "influenza"),
        ("covid", "covid"),
        ("sars", "covid"),
        ("mening", "meningite"),
        ("leishman", "leishmaniose"),
        ("malária", "malaria"),
        ("malaria", "malaria"),
        ("hantavir", "hantavirus"),
        ("leptosp", "leptospirose"),
    )
    for key, tgt in rules:
        if key in t:
            return tgt
    return "outros"


def rebuild_sim_weekly(
    sim_path: Path | str,
    outdir: Path | str = "saida_pipeline",
) -> pd.DataFrame:
    sim_path = Path(sim_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(sim_path, encoding="latin1", low_memory=False)
    # Normaliza nomes
    cols = {c: str(c).strip() for c in df.columns}
    df = df.rename(columns=cols)

    date_col = next((c for c in df.columns if c.lower() in {"dataobito", "dt_obito", "dtobito"}), None)
    ano_col = next((c for c in df.columns if c.lower() in {"anoobito", "ano"}), None)
    mun_col = next(
        (c for c in df.columns if c.lower() in {
            "municipioresidencia", "municipio_residencia", "mun_res", "municipio",
        }),
        None,
    )
    causa_col = next(
        (c for c in df.columns if c.lower() in {
            "causabasica", "causa_basica", "causabas", "cid10",
        }),
        None,
    )
    if mun_col is None:
        raise ValueError(f"Coluna de município não encontrada em {sim_path.name}")

    work = pd.DataFrame({
        "municipio": df[mun_col].astype(str).str.strip().str.upper(),
        "causa": df[causa_col].astype(str) if causa_col else "",
    })
    if date_col:
        work["event_date"] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    else:
        work["event_date"] = pd.NaT
    if ano_col and work["event_date"].isna().mean() > 0.5:
        # fallback AnoObito + 1º de julho
        ano = pd.to_numeric(df[ano_col], errors="coerce")
        work["event_date"] = pd.to_datetime(
            ano.astype("Int64").astype(str) + "-07-01", errors="coerce"
        )

    work = work.dropna(subset=["event_date"]).copy()
    years_ok = work["event_date"].dt.year.between(1990, 2100)
    work = work.loc[years_ok].copy()
    if work.empty:
        raise ValueError("Nenhuma data de óbito válida (1990–2100) após parse.")

    iso = work["event_date"].dt.isocalendar()
    work["ano"] = work["event_date"].dt.year.astype(int)
    work["epi_year"] = iso["year"].astype(int)
    work["epi_week"] = iso["week"].astype(int)
    work = work[work["epi_year"].between(1990, 2100)].copy()
    work["target"] = work["causa"].map(_infer_target)
    work["obitos"] = 1

    weekly = (
        work.groupby(["epi_year", "epi_week", "ano", "target", "municipio"], dropna=False)
        .agg(obitos_sim=("obitos", "sum"))
        .reset_index()
    )
    weekly.to_csv(outdir / "sim_weekly_municipio.csv", index=False, encoding="utf-8-sig")

    demo = (
        work.groupby(["ano", "target", "municipio"], dropna=False)
        .agg(obitos_sim=("obitos", "sum"))
        .reset_index()
    )
    demo.to_csv(outdir / "sim_demo.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame([{
        "fonte": sim_path.name,
        "status": "ok",
        "pct_ano_invalido": 0.0,
        "n_linhas": int(len(weekly)),
        "ano_min": int(weekly["epi_year"].min()),
        "ano_max": int(weekly["epi_year"].max()),
        "acao": "reconstruido",
    }]).to_csv(outdir / "sim_qualidade.csv", index=False, encoding="utf-8-sig")

    print(
        f"[SIM] OK weekly={len(weekly):,} anos={weekly['epi_year'].min()}-{weekly['epi_year'].max()}",
        flush=True,
    )
    return weekly


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", default=str(ROOT / "SIM 2010 a 2025.csv"))
    ap.add_argument("--outdir", default=str(ROOT / "saida_pipeline"))
    args = ap.parse_args()
    path = Path(args.sim)
    if not path.exists():
        # tenta sibling Sentinela
        alt = ROOT.parent / "Sentinela" / "SIM 2010 a 2025.csv"
        path = alt if alt.exists() else path
    if not path.exists():
        print(f"[ERRO] SIM bruto não encontrado: {args.sim}", flush=True)
        return 1
    rebuild_sim_weekly(path, args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
