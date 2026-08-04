# -*- coding: utf-8 -*-
"""Indicadores de desempenho da rede laboratorial (TAT, backlog, rejeição)."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def _find_gal_paths() -> list[Path]:
    candidates = []
    for pattern in ("gal*.csv", "GAL*.csv", "*gal*201*.csv", "*GAL*201*.csv"):
        candidates.extend(ROOT.glob(pattern))
        candidates.extend((ROOT / "dados").glob(pattern) if (ROOT / "dados").exists() else [])
    # dedupe
    seen = set()
    out = []
    for p in candidates:
        if p.resolve() not in seen and p.is_file() and p.stat().st_size > 1000:
            seen.add(p.resolve())
            out.append(p)
    return out


def _norm_status(s: object) -> str:
    t = str(s or "").casefold()
    if any(x in t for x in ("rejeit", "inadequad", "recusad")):
        return "rejeitado"
    if any(x in t for x in ("pendente", "aguard", "em analise", "em análise", "recebid")):
        return "pendente"
    if any(x in t for x in ("liberad", "conclu", "finaliz", "resultad")):
        return "liberado"
    if any(x in t for x in ("inconclusive", "inconclus")):
        return "inconclusivo"
    return "outro"


def build_indicadores_rede(
    gal_paths: Optional[list[Path]] = None,
    outdir: Path | str = "saida_pipeline",
    chunksize: int = 80_000,
) -> pd.DataFrame:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = gal_paths or _find_gal_paths()
    if not paths:
        # Fallback: deriva proxies a partir do weekly (sem microdados GAL)
        weekly_path = outdir / "integrated_weekly_surveillance.csv"
        if not weekly_path.exists():
            empty = pd.DataFrame(columns=[
                "municipio", "exames", "tat_mediano_dias", "pct_liberado_7d",
                "pct_rejeitado", "backlog_estimado", "fonte",
            ])
            empty.to_csv(outdir / "indicadores_rede_laboratorial.csv", index=False, encoding="utf-8-sig")
            return empty
        w = pd.read_csv(weekly_path, low_memory=False)
        w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
        w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0)
        # últimas 8 SE
        weeks = w[["epi_year", "epi_week"]].drop_duplicates().sort_values(["epi_year", "epi_week"]).tail(8)
        recent = w.merge(weeks, on=["epi_year", "epi_week"], how="inner")
        g = recent.groupby("municipio", as_index=False).agg(exames=("tests", "sum"))
        g["tat_mediano_dias"] = np.nan
        g["pct_liberado_7d"] = np.nan
        g["pct_rejeitado"] = np.nan
        g["backlog_estimado"] = np.nan
        g["fonte"] = "proxy_weekly_sem_gal"
        g["interpretacao"] = "Sem microdados GAL locais — indicadores TAT/rejeição indisponíveis; use exames como proxy de volume."
        g.to_csv(outdir / "indicadores_rede_laboratorial.csv", index=False, encoding="utf-8-sig")
        print(f"[REDE] Proxy sem GAL: {len(g)} municípios", flush=True)
        return g

    rows = []
    for path in paths[:6]:
        print(f"[REDE] Lendo {path.name}...", flush=True)
        try:
            chunks = pd.read_csv(path, chunksize=chunksize, low_memory=False, encoding="latin1")
        except Exception:
            try:
                chunks = pd.read_csv(path, chunksize=chunksize, low_memory=False, encoding="utf-8-sig")
            except Exception as exc:
                print(f"[AVISO] Falha {path.name}: {exc}", flush=True)
                continue
        for chunk in chunks:
            mun_col = next((c for c in chunk.columns if "municipio" in str(c).casefold() and "resid" in str(c).casefold()), None)
            if mun_col is None:
                mun_col = next((c for c in chunk.columns if "municipio" in str(c).casefold()), None)
            col_coleta = next((c for c in chunk.columns if "coleta" in str(c).casefold()), None)
            col_lib = next((c for c in chunk.columns if "liberac" in str(c).casefold()), None)
            col_status = next((c for c in chunk.columns if "status" in str(c).casefold()), None)
            if mun_col is None:
                continue
            tmp = pd.DataFrame({"municipio": chunk[mun_col].astype(str).str.strip().str.upper()})
            if col_coleta:
                tmp["dt_coleta"] = pd.to_datetime(chunk[col_coleta], errors="coerce", dayfirst=True)
            else:
                tmp["dt_coleta"] = pd.NaT
            if col_lib:
                tmp["dt_lib"] = pd.to_datetime(chunk[col_lib], errors="coerce", dayfirst=True)
            else:
                tmp["dt_lib"] = pd.NaT
            if col_status:
                tmp["status"] = chunk[col_status].map(_norm_status)
            else:
                tmp["status"] = np.where(tmp["dt_lib"].notna(), "liberado", "pendente")
            tmp["tat_dias"] = (tmp["dt_lib"] - tmp["dt_coleta"]).dt.total_seconds() / 86400.0
            tmp.loc[tmp["tat_dias"] < 0, "tat_dias"] = np.nan
            tmp.loc[tmp["tat_dias"] > 365, "tat_dias"] = np.nan
            rows.append(tmp)

    if not rows:
        return build_indicadores_rede(gal_paths=[], outdir=outdir)

    all_df = pd.concat(rows, ignore_index=True)
    all_df = all_df[all_df["municipio"].ne("") & all_df["municipio"].ne("NAN")]
    g = all_df.groupby("municipio", as_index=False).agg(
        exames=("municipio", "size"),
        tat_mediano_dias=("tat_dias", "median"),
        tat_p90_dias=("tat_dias", lambda s: s.quantile(0.9)),
        pct_liberado_7d=("tat_dias", lambda s: float((s.dropna() <= 7).mean()) if s.notna().any() else np.nan),
        pct_rejeitado=("status", lambda s: float((s == "rejeitado").mean())),
        backlog_estimado=("status", lambda s: int((s == "pendente").sum())),
        pct_inconclusivo=("status", lambda s: float((s == "inconclusivo").mean())),
    )
    g["fonte"] = "gal_microdados"
    g["interpretacao"] = np.where(
        g["tat_mediano_dias"].fillna(99) > 14,
        "TAT mediano elevado — revisar fluxo coleta→liberação",
        np.where(
            g["pct_rejeitado"].fillna(0) > 0.05,
            "Rejeição elevada — capacitar coleta/envio",
            "Desempenho dentro do esperado (proxy)",
        ),
    )
    g = g.sort_values(["backlog_estimado", "tat_mediano_dias"], ascending=[False, False])
    g.to_csv(outdir / "indicadores_rede_laboratorial.csv", index=False, encoding="utf-8-sig")
    print(f"[REDE] {len(g)} municípios | fonte=gal", flush=True)
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="saida_pipeline")
    ap.add_argument("--gal", nargs="*", default=None)
    args = ap.parse_args()
    paths = [Path(p) for p in args.gal] if args.gal else None
    build_indicadores_rede(paths, args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
