# -*- coding: utf-8 -*-
"""Indicadores de desempenho da rede laboratorial (TAT, backlog, rejeição) a partir do GAL/LACEN."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent

try:
    from lacen_inteligencia import familia_agravo
except Exception:  # pragma: no cover
    def familia_agravo(target: object) -> str:  # type: ignore
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

# Colunas mínimas do export GAL LACEN MT
GAL_USECOLS = [
    "Municipio_Residencia_Paciente",
    "Municipio_Solicitante",
    "Data_Coleta_dt",
    "Data_Coleta",
    "Data_Recebimento_dt",
    "Data_Recebimento",
    "Data_Liberacao_dt",
    "Data_Liberacao",
    "Status_Exame",
    "Agravo_Requisicao",
    "Unidade_Solicitante",
]


def _find_gal_paths() -> list[Path]:
    preferred = [
        ROOT / "LACEN 2010 a 2026.csv",
        ROOT / "LACEN_2010_a_2026.csv",
    ]
    out = [p for p in preferred if p.exists()]
    for pattern in ("gal*.csv", "GAL*.csv", "*gal*.csv", "*GAL*.csv", "LACEN*.csv"):
        for p in ROOT.glob(pattern):
            if p.resolve() not in {x.resolve() for x in out} and p.stat().st_size > 1000:
                # evita CSVs territoriais pequenos / não-GAL
                name = p.name.casefold()
                if any(x in name for x in ("cnes", "sinan", "sim ", "clima", "municip")):
                    continue
                out.append(p)
    return out


def _norm_status(s: object) -> str:
    t = str(s or "").casefold()
    if any(x in t for x in ("rejeit", "inadequad", "recusad", "cancelad")):
        return "rejeitado"
    if any(x in t for x in ("pendente", "aguard", "em analise", "em análise", "recebid", "triagem")):
        return "pendente"
    if any(x in t for x in ("liberad", "conclu", "finaliz", "resultad", "entregue")):
        return "liberado"
    if any(x in t for x in ("inconclusive", "inconclus")):
        return "inconclusivo"
    return "outro"


def _pick_col(columns, *candidates) -> Optional[str]:
    lower = {str(c).casefold(): c for c in columns}
    for cand in candidates:
        if cand.casefold() in lower:
            return lower[cand.casefold()]
    for c in columns:
        cl = str(c).casefold()
        for cand in candidates:
            if cand.casefold() in cl:
                return c
    return None


def _parse_dt(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", dayfirst=True)
    # também tenta ISO
    if dt.notna().mean() < 0.2:
        dt = pd.to_datetime(series, errors="coerce")
    return dt


def build_indicadores_rede(
    gal_paths: Optional[list[Path]] = None,
    outdir: Path | str = "saida_pipeline",
    chunksize: int = 100_000,
    recent_years: int = 3,
) -> pd.DataFrame:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = gal_paths or _find_gal_paths()

    if not paths:
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
        weeks = w[["epi_year", "epi_week"]].drop_duplicates().sort_values(["epi_year", "epi_week"]).tail(8)
        recent = w.merge(weeks, on=["epi_year", "epi_week"], how="inner")
        g = recent.groupby("municipio", as_index=False).agg(exames=("tests", "sum"))
        g["tat_mediano_dias"] = np.nan
        g["tat_p90_dias"] = np.nan
        g["pct_liberado_48h"] = np.nan
        g["pct_liberado_7d"] = np.nan
        g["pct_rejeitado"] = np.nan
        g["backlog_estimado"] = np.nan
        g["fonte"] = "proxy_weekly_sem_gal"
        g["interpretacao"] = "Sem microdados GAL — indicadores TAT/rejeição indisponíveis."
        g.to_csv(outdir / "indicadores_rede_laboratorial.csv", index=False, encoding="utf-8-sig")
        print(f"[REDE] Proxy sem GAL: {len(g)} municípios", flush=True)
        return g

    year_min = pd.Timestamp.today().year - max(1, recent_years) + 1
    parts = []
    for path in paths[:3]:
        print(f"[REDE] Lendo {path.name} (anos>={year_min})...", flush=True)
        # descobrir colunas existentes
        header = pd.read_csv(path, nrows=0, encoding="latin1")
        usecols = [c for c in GAL_USECOLS if c in header.columns]
        if not usecols:
            # fallback fuzzy
            mun = _pick_col(header.columns, "Municipio_Residencia_Paciente", "Municipio_Solicitante")
            coleta = _pick_col(header.columns, "Data_Coleta_dt", "Data_Coleta")
            receb = _pick_col(header.columns, "Data_Recebimento_dt", "Data_Recebimento")
            liber = _pick_col(header.columns, "Data_Liberacao_dt", "Data_Liberacao")
            status = _pick_col(header.columns, "Status_Exame")
            agravo = _pick_col(header.columns, "Agravo_Requisicao")
            usecols = [c for c in (mun, coleta, receb, liber, status, agravo) if c]
        if len(usecols) < 3:
            print(f"[AVISO] Colunas insuficientes em {path.name}", flush=True)
            continue

        try:
            reader = pd.read_csv(
                path, usecols=usecols, chunksize=chunksize,
                encoding="latin1", low_memory=False,
            )
        except Exception as exc:
            print(f"[AVISO] Falha ao abrir {path.name}: {exc}", flush=True)
            continue

        n_rows = 0
        for chunk in reader:
            mun_col = _pick_col(chunk.columns, "Municipio_Residencia_Paciente", "Municipio_Solicitante", "municipio")
            col_coleta = _pick_col(chunk.columns, "Data_Coleta_dt", "Data_Coleta")
            col_receb = _pick_col(chunk.columns, "Data_Recebimento_dt", "Data_Recebimento")
            col_lib = _pick_col(chunk.columns, "Data_Liberacao_dt", "Data_Liberacao")
            col_status = _pick_col(chunk.columns, "Status_Exame", "status")
            col_agravo = _pick_col(chunk.columns, "Agravo_Requisicao", "agravo", "target")
            if mun_col is None:
                continue

            tmp = pd.DataFrame({
                "municipio": chunk[mun_col].astype(str).str.strip().str.upper(),
            })
            dt_coleta = _parse_dt(chunk[col_coleta]) if col_coleta else pd.Series(pd.NaT, index=chunk.index)
            dt_receb = _parse_dt(chunk[col_receb]) if col_receb else pd.Series(pd.NaT, index=chunk.index)
            dt_lib = _parse_dt(chunk[col_lib]) if col_lib else pd.Series(pd.NaT, index=chunk.index)

            # filtra anos recentes pela melhor data disponível
            ref = dt_lib.fillna(dt_receb).fillna(dt_coleta)
            mask_year = ref.dt.year.fillna(0).ge(year_min)
            tmp = tmp.loc[mask_year].copy()
            if tmp.empty:
                continue
            dt_coleta = dt_coleta.loc[tmp.index]
            dt_receb = dt_receb.loc[tmp.index]
            dt_lib = dt_lib.loc[tmp.index]

            tmp["status"] = chunk.loc[tmp.index, col_status].map(_norm_status) if col_status else np.where(
                dt_lib.notna(), "liberado", "pendente"
            )
            if col_agravo:
                tmp["agravo_raw"] = chunk.loc[tmp.index, col_agravo].astype(str)
                tmp["familia"] = tmp["agravo_raw"].map(familia_agravo).replace("", "outros")
            else:
                tmp["agravo_raw"] = ""
                tmp["familia"] = "outros"
            # TAT coleta→liberação e recebimento→liberação
            tat_cl = (dt_lib - dt_coleta).dt.total_seconds() / 86400.0
            tat_rl = (dt_lib - dt_receb).dt.total_seconds() / 86400.0
            tmp["tat_coleta_liberacao_dias"] = tat_cl.where((tat_cl >= 0) & (tat_cl <= 365))
            tmp["tat_receb_liberacao_dias"] = tat_rl.where((tat_rl >= 0) & (tat_rl <= 365))
            tmp["tat_dias"] = tmp["tat_coleta_liberacao_dias"].fillna(tmp["tat_receb_liberacao_dias"])
            tmp["logistica_dias"] = ((dt_receb - dt_coleta).dt.total_seconds() / 86400.0).where(
                lambda s: (s >= 0) & (s <= 120)
            )
            parts.append(tmp)
            n_rows += len(tmp)
        print(f"[REDE] {path.name}: {n_rows:,} linhas recentes", flush=True)

    if not parts:
        return build_indicadores_rede(gal_paths=[], outdir=outdir)

    all_df = pd.concat(parts, ignore_index=True)
    all_df = all_df[all_df["municipio"].ne("") & ~all_df["municipio"].isin({"NAN", "NONE", "IGNORADO"})]

    # Restringe ao universo MT quando municipal_master existir
    mm_path = outdir / "municipal_master.csv"
    if mm_path.exists():
        try:
            mm = pd.read_csv(mm_path, usecols=lambda c: c in {"municipio", "Municipio"}, low_memory=False)
            col = "municipio" if "municipio" in mm.columns else mm.columns[0]
            mt = set(mm[col].astype(str).str.strip().str.upper())
            before = len(all_df)
            all_df = all_df[all_df["municipio"].isin(mt)]
            print(f"[REDE] Filtro MT: {before:,} → {len(all_df):,} linhas | {all_df['municipio'].nunique()} municípios", flush=True)
        except Exception as exc:
            print(f"[AVISO] Filtro MT não aplicado: {exc}", flush=True)

    def _pct_le(s: pd.Series, dias: float) -> float:
        v = s.dropna()
        return float((v <= dias).mean()) if len(v) else np.nan

    if "familia" not in all_df.columns:
        all_df["familia"] = "outros"

    g = all_df.groupby("municipio", as_index=False).agg(
        exames=("municipio", "size"),
        tat_mediano_dias=("tat_dias", "median"),
        tat_p90_dias=("tat_dias", lambda s: s.quantile(0.9)),
        tat_lab_mediano_dias=("tat_receb_liberacao_dias", "median"),
        logistica_mediana_dias=("logistica_dias", "median"),
        pct_liberado_48h=("tat_receb_liberacao_dias", lambda s: _pct_le(s, 2.0)),
        pct_liberado_48h_coleta=("tat_dias", lambda s: _pct_le(s, 2.0)),
        pct_liberado_7d=("tat_dias", lambda s: _pct_le(s, 7.0)),
        pct_liberado_14d=("tat_dias", lambda s: _pct_le(s, 14.0)),
        pct_rejeitado=("status", lambda s: float((s == "rejeitado").mean())),
        backlog_estimado=("status", lambda s: int((s == "pendente").sum())),
        pct_inconclusivo=("status", lambda s: float((s == "inconclusivo").mean())),
        pct_liberado=("status", lambda s: float((s == "liberado").mean())),
    )
    g["fonte"] = "gal_lacen_microdados"
    g["anos_referencia"] = f">={year_min}"
    # Se TAT laboratorial (receb→lib) estiver vazio, usa coleta→lib como fallback
    g["pct_liberado_48h"] = g["pct_liberado_48h"].fillna(g["pct_liberado_48h_coleta"])
    g["interpretacao"] = np.select(
        [
            g["pct_liberado_48h"].fillna(1) < 0.40,
            g["tat_mediano_dias"].fillna(99) > 14,
            g["pct_rejeitado"].fillna(0) > 0.05,
            g["logistica_mediana_dias"].fillna(0) > 5,
            g["backlog_estimado"].fillna(0) > 50,
        ],
        [
            "SLA crise: baixa liberação ≤48h — priorizar liberação/triagem",
            "TAT mediano elevado — revisar fluxo coleta→liberação",
            "Rejeição elevada — capacitar coleta/envio de amostras",
            "Atraso logístico coleta→recebimento — revisar transporte",
            "Backlog pendente relevante — priorizar liberação",
        ],
        default="Desempenho dentro do esperado (janela recente)",
    )
    g = g.sort_values(["backlog_estimado", "tat_mediano_dias"], ascending=[False, False])
    out_csv = outdir / "indicadores_rede_laboratorial.csv"
    g.to_csv(out_csv, index=False, encoding="utf-8-sig")
    try:
        g.to_parquet(outdir / "indicadores_rede_laboratorial.parquet", index=False)
    except Exception:
        pass

    # SLA por família de agravo (+ rollup municipal×família com volume mínimo)
    fam = all_df.groupby(["familia"], as_index=False).agg(
        exames=("municipio", "size"),
        n_municipios=("municipio", "nunique"),
        tat_mediano_dias=("tat_dias", "median"),
        tat_p90_dias=("tat_dias", lambda s: s.quantile(0.9)),
        pct_liberado_48h=("tat_receb_liberacao_dias", lambda s: _pct_le(s, 2.0)),
        pct_liberado_48h_coleta=("tat_dias", lambda s: _pct_le(s, 2.0)),
        pct_liberado_7d=("tat_dias", lambda s: _pct_le(s, 7.0)),
        pct_rejeitado=("status", lambda s: float((s == "rejeitado").mean())),
        backlog_estimado=("status", lambda s: int((s == "pendente").sum())),
    )
    fam["granularidade"] = "familia"
    fam["municipio"] = "ESTADO_MT"
    fam["pct_liberado_48h"] = fam["pct_liberado_48h"].fillna(fam["pct_liberado_48h_coleta"])
    fam_mun = all_df.groupby(["municipio", "familia"], as_index=False).agg(
        exames=("municipio", "size"),
        tat_mediano_dias=("tat_dias", "median"),
        tat_p90_dias=("tat_dias", lambda s: s.quantile(0.9)),
        pct_liberado_48h=("tat_receb_liberacao_dias", lambda s: _pct_le(s, 2.0)),
        pct_liberado_48h_coleta=("tat_dias", lambda s: _pct_le(s, 2.0)),
        pct_liberado_7d=("tat_dias", lambda s: _pct_le(s, 7.0)),
        pct_rejeitado=("status", lambda s: float((s == "rejeitado").mean())),
        backlog_estimado=("status", lambda s: int((s == "pendente").sum())),
    )
    fam_mun["granularidade"] = "municipio_familia"
    fam_mun["n_municipios"] = 1
    fam_mun["pct_liberado_48h"] = fam_mun["pct_liberado_48h"].fillna(fam_mun["pct_liberado_48h_coleta"])
    fam_mun = fam_mun[fam_mun["exames"] >= 20]
    por_fam = pd.concat([fam, fam_mun], ignore_index=True, sort=False)
    por_fam["fonte"] = "gal_lacen_microdados"
    por_fam["anos_referencia"] = f">={year_min}"
    por_fam = por_fam.sort_values(["granularidade", "exames"], ascending=[True, False])
    por_fam.to_csv(outdir / "indicadores_rede_por_familia.csv", index=False, encoding="utf-8-sig")
    try:
        por_fam.to_parquet(outdir / "indicadores_rede_por_familia.parquet", index=False)
    except Exception:
        pass

    resumo = pd.DataFrame([{
        "n_municipios": int(len(g)),
        "exames_total": int(g["exames"].sum()),
        "tat_mediano_estadual": float(g["tat_mediano_dias"].median()) if g["tat_mediano_dias"].notna().any() else None,
        "tat_p90_estadual": float(g["tat_p90_dias"].median()) if g["tat_p90_dias"].notna().any() else None,
        "pct_liberado_48h_mediano": float(g["pct_liberado_48h"].median()) if g["pct_liberado_48h"].notna().any() else None,
        "pct_liberado_7d_mediano": float(g["pct_liberado_7d"].median()) if g["pct_liberado_7d"].notna().any() else None,
        "pct_rejeitado_mediano": float(g["pct_rejeitado"].median()) if g["pct_rejeitado"].notna().any() else None,
        "backlog_total": int(g["backlog_estimado"].sum()),
        "fonte": "gal_lacen_microdados",
        "anos_referencia": f">={year_min}",
    }])
    resumo.to_csv(outdir / "indicadores_rede_resumo.csv", index=False, encoding="utf-8-sig")
    try:
        resumo.to_parquet(outdir / "indicadores_rede_resumo.parquet", index=False)
    except Exception:
        pass
    print(
        f"[REDE] {len(g)} municípios | exames={int(g['exames'].sum()):,} | "
        f"TAT mediano estadual={resumo['tat_mediano_estadual'].iloc[0]} | "
        f"%≤48h mediano={resumo['pct_liberado_48h_mediano'].iloc[0]} | "
        f"famílias={fam['familia'].nunique()}",
        flush=True,
    )
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="saida_pipeline")
    ap.add_argument("--gal", nargs="*", default=None)
    ap.add_argument("--years", type=int, default=3, help="Anos recentes a considerar")
    ap.add_argument("--chunksize", type=int, default=100000)
    args = ap.parse_args()
    paths = [Path(p) for p in args.gal] if args.gal else None
    build_indicadores_rede(paths, args.outdir, chunksize=args.chunksize, recent_years=args.years)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
