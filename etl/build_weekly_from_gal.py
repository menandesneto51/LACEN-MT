# -*- coding: utf-8 -*-
"""Constrói weekly_tests / positivity a partir do staging DW ou CSV GAL local."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from etl.epi_week import date_to_epi, format_se, semana_completa_mais_recente

ROOT = Path(__file__).resolve().parents[1]

_TARGET_RULES = [
    (r"\bdengue\b", "dengue"),
    (r"\bzika\b", "zika"),
    (r"chikung", "chikungunya"),
    (r"oropouche", "oropouche"),
    (r"febre\s*amarela", "febre_amarela"),
    (r"influenza", "influenza"),
    (r"sars\s*cov|covid", "sars_cov_2"),
    (r"hepatite\s*c|\bhcv\b", "hepatite_c_hcv"),
    (r"hepatite\s*b|\bhbv\b|hbsag", "hepatite_b_hbv"),
    (r"hepatite\s*a", "hepatite_a"),
    (r"hepatite", "hepatite"),
    (r"tubercul|\bmtb\b|baciloscopia|rifampicina|lf[\s_-]?lam", "tuberculose"),
    (r"leptosp", "leptospira"),
    (r"hantav", "hantavirus"),
    (r"mening", "meningite"),
    (r"mal[aá]ria", "malaria"),
    (r"\bhiv\b", "hiv"),
    (r"s[ií]filis", "sifilis"),
    (r"hanseni", "hanseniase"),
    (r"leishman", "leishmaniose"),
]


def _log(msg: str) -> None:
    print(msg, flush=True)


def infer_target(agravo: object, exame: object = "") -> str:
    blob = f"{agravo or ''} {exame or ''}".casefold()
    for pat, tgt in _TARGET_RULES:
        if re.search(pat, blob, flags=re.I):
            return tgt
    blob = re.sub(r"[^a-z0-9]+", "_", blob).strip("_")
    return blob[:80] if blob else "nao_classificado"


def weekly_from_dw_agg(agg: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Converte agregação SQL DW → weekly_tests + positivity."""
    if agg is None or agg.empty:
        empty_t = pd.DataFrame(columns=["epi_year", "epi_week", "target", "municipio", "tests"])
        empty_p = pd.DataFrame(columns=[
            "epi_year", "epi_week", "target", "municipio", "tests", "positives", "negatives", "positivity",
        ])
        return empty_t, empty_p

    df = agg.copy()
    df["municipio"] = df["municipio"].astype(str).str.strip().str.upper()
    df["epi_year"] = pd.to_numeric(df["epi_year"], errors="coerce")
    df["epi_week"] = pd.to_numeric(df["epi_week"], errors="coerce")
    df = df.dropna(subset=["epi_year", "epi_week", "municipio"])
    df["epi_year"] = df["epi_year"].astype(int)
    df["epi_week"] = df["epi_week"].astype(int)
    df["target"] = [
        infer_target(a, e)
        for a, e in zip(df.get("agravo_raw", ""), df.get("exame_raw", ""))
    ]
    df["tests"] = pd.to_numeric(df.get("n_registros"), errors="coerce").fillna(0).astype(int)
    df["positives"] = pd.to_numeric(df.get("n_positivos_proxy"), errors="coerce").fillna(0).astype(int)

    tests = (
        df.groupby(["epi_year", "epi_week", "target", "municipio"], as_index=False)
        .agg(tests=("tests", "sum"))
    )
    pos = (
        df.groupby(["epi_year", "epi_week", "target", "municipio"], as_index=False)
        .agg(tests=("tests", "sum"), positives=("positives", "sum"))
    )
    pos["negatives"] = (pos["tests"] - pos["positives"]).clip(lower=0)
    pos["positivity"] = np.where(pos["tests"] > 0, pos["positives"] / pos["tests"], np.nan)
    return tests, pos


def weekly_from_local_gal(
    gal_path: Path | str,
    *,
    year_min: int = 2024,
    chunksize: int = 200_000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agregação leve do CSV GAL local (fallback offline)."""
    gal_path = Path(gal_path)
    header = pd.read_csv(gal_path, nrows=0, encoding="latin1")
    cols = set(header.columns)

    def pick(*cands: str) -> Optional[str]:
        for c in cands:
            if c in cols:
                return c
        return None

    date_col = pick("Data_Liberacao_dt", "Data_Liberacao")
    mun_col = pick("Municipio_Residencia_Paciente", "Municipio_Solicitante")
    agravo_col = pick("Agravo_Requisicao", "Agravo_Gal")
    exame_col = pick("Exame")
    r1 = pick("Campo_Resultado_1")
    if not date_col or not mun_col:
        raise ValueError(f"Colunas insuficientes em {gal_path.name}")

    usecols = [c for c in (date_col, mun_col, agravo_col, exame_col, r1) if c]
    parts = []
    for chunk in pd.read_csv(
        gal_path, usecols=usecols, encoding="latin1",
        chunksize=chunksize, low_memory=False,
    ):
        dt = pd.to_datetime(chunk[date_col], errors="coerce", dayfirst=True)
        mask = dt.dt.year.between(year_min, date_to_epi()[0] + 1)
        chunk = chunk.loc[mask].copy()
        if chunk.empty:
            continue
        dt = dt.loc[mask]
        epi = dt.dt.isocalendar()
        chunk["epi_year"] = epi.year.astype(int)
        chunk["epi_week"] = epi.week.astype(int)
        chunk["municipio"] = chunk[mun_col].astype(str).str.strip().str.upper()
        agr = chunk[agravo_col] if agravo_col else ""
        ex = chunk[exame_col] if exame_col else ""
        chunk["target"] = [infer_target(a, e) for a, e in zip(agr, ex)]
        if r1:
            blob = chunk[r1].astype(str).str.casefold()
            chunk["positives"] = blob.str.contains("positiv", na=False).astype(int)
        else:
            chunk["positives"] = 0
        chunk["tests"] = 1
        g = chunk.groupby(["epi_year", "epi_week", "target", "municipio"], as_index=False).agg(
            tests=("tests", "sum"),
            positives=("positives", "sum"),
        )
        parts.append(g)

    if not parts:
        empty_t = pd.DataFrame(columns=["epi_year", "epi_week", "target", "municipio", "tests"])
        empty_p = pd.DataFrame(columns=[
            "epi_year", "epi_week", "target", "municipio", "tests", "positives", "negatives", "positivity",
        ])
        return empty_t, empty_p

    allp = pd.concat(parts, ignore_index=True)
    pos = (
        allp.groupby(["epi_year", "epi_week", "target", "municipio"], as_index=False)
        .agg(tests=("tests", "sum"), positives=("positives", "sum"))
    )
    pos["negatives"] = (pos["tests"] - pos["positives"]).clip(lower=0)
    pos["positivity"] = np.where(pos["tests"] > 0, pos["positives"] / pos["tests"], np.nan)
    tests = pos[["epi_year", "epi_week", "target", "municipio", "tests"]].copy()
    return tests, pos


def _merge_replace_weeks(old: pd.DataFrame, new: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    if old is None or old.empty:
        return new.copy()
    if new is None or new.empty:
        return old.copy()
    weeks = new[["epi_year", "epi_week"]].drop_duplicates()
    keep = old.merge(weeks, on=["epi_year", "epi_week"], how="left", indicator=True)
    keep = keep[keep["_merge"] == "left_only"].drop(columns=["_merge"])
    # alinhar colunas
    cols = list(dict.fromkeys(list(keep.columns) + list(new.columns)))
    for c in cols:
        if c not in keep.columns:
            keep[c] = np.nan
        if c not in new.columns:
            new = new.copy()
            new[c] = np.nan
    out = pd.concat([keep[cols], new[cols]], ignore_index=True)
    return out.drop_duplicates(subset=key_cols, keep="last")


def publish_weekly_inputs(
    tests: pd.DataFrame,
    pos: pd.DataFrame,
    outdir: Path | str,
    *,
    replace_from_year: int = 2024,
) -> dict:
    """Atualiza CSVs que a integração final consome; preserva histórico antigo."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    wt_path = outdir / "weekly_tests_by_target_municipio.csv"
    pos_path = outdir / "positivity_by_target_epiweek_municipio.csv"

    old_t = pd.read_csv(wt_path, low_memory=False) if wt_path.exists() else pd.DataFrame()
    old_p = pd.read_csv(pos_path, low_memory=False) if pos_path.exists() else pd.DataFrame()

    # só substitui semanas cobertas pelo new (tipicamente janela DW recente)
    new_t = tests.copy()
    new_p = pos.copy()
    if replace_from_year and not new_t.empty:
        new_t = new_t[pd.to_numeric(new_t["epi_year"], errors="coerce") >= replace_from_year]
        new_p = new_p[pd.to_numeric(new_p["epi_year"], errors="coerce") >= replace_from_year]

    merged_t = _merge_replace_weeks(
        old_t, new_t, ["epi_year", "epi_week", "target", "municipio"]
    )
    merged_p = _merge_replace_weeks(
        old_p, new_p, ["epi_year", "epi_week", "target", "municipio"]
    )

    merged_t.to_csv(wt_path, index=False, encoding="utf-8-sig")
    merged_p.to_csv(pos_path, index=False, encoding="utf-8-sig")
    try:
        merged_t.to_parquet(outdir / "weekly_tests_by_target_municipio.parquet", index=False)
        merged_p.to_parquet(outdir / "positivity_by_target_epiweek_municipio.parquet", index=False)
    except Exception:
        pass

    se_max = None
    if not merged_t.empty:
        y = int(pd.to_numeric(merged_t["epi_year"], errors="coerce").max())
        w = int(pd.to_numeric(merged_t.loc[merged_t["epi_year"] == y, "epi_week"], errors="coerce").max())
        se_max = (y, w)

    return {
        "weekly_tests_rows": int(len(merged_t)),
        "positivity_rows": int(len(merged_p)),
        "se_max": format_se(*se_max) if se_max else None,
        "paths": {"tests": str(wt_path.name), "positivity": str(pos_path.name)},
    }


def choose_se_operacional(
    weekly: pd.DataFrame,
    hoje=None,
    *,
    max_atraso_sem_aviso: int = 2,
) -> dict:
    """Define SE usada vs esperada; nunca silencia atraso > limiar."""
    from etl.epi_week import atraso_dias_desde_fim_se, atraso_semanas

    esp = semana_completa_mais_recente(hoje)
    info = {
        "hoje": str(pd.Timestamp(hoje or pd.Timestamp.today()).date()),
        "se_esperada": format_se(*esp),
        "se_esperada_tuple": esp,
        "se_usada": None,
        "se_usada_tuple": None,
        "atraso_se": None,
        "atraso_dias": None,
        "se_fonte": None,
        "aviso": None,
    }
    if weekly is None or weekly.empty:
        info["aviso"] = "Sem dados semanais — impossível fixar SE."
        return info

    w = weekly.copy()
    w["epi_year"] = pd.to_numeric(w["epi_year"], errors="coerce")
    w["epi_week"] = pd.to_numeric(w["epi_week"], errors="coerce")
    weeks = (
        w[["epi_year", "epi_week"]].dropna().drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
    )
    if weeks.empty:
        info["aviso"] = "Sem pares epi_year/epi_week válidos."
        return info

    # Preferir SE esperada se houver linhas; senão última presente no DW/local
    ey, ew = esp
    has_esp = ((weeks["epi_year"] == ey) & (weeks["epi_week"] == ew)).any()
    if has_esp:
        usada = (ey, ew)
        fonte = "se_completa_calendario"
    else:
        usada = (int(weeks.iloc[-1]["epi_year"]), int(weeks.iloc[-1]["epi_week"]))
        fonte = "ultima_se_presente_nos_dados"

    atr = atraso_semanas(esp, usada)
    info.update({
        "se_usada": format_se(*usada),
        "se_usada_tuple": usada,
        "atraso_se": atr,
        "atraso_dias": atraso_dias_desde_fim_se(usada[0], usada[1], hoje),
        "se_fonte": fonte,
    })
    if atr > max_atraso_sem_aviso:
        info["aviso"] = (
            f"ATRASO: SE usada {info['se_usada']} está {atr} semanas atrás da "
            f"esperada {info['se_esperada']} ({info['hoje']}). "
            "Não tratar como semana corrente sem justificativa (DW/VPN/carga)."
        )
        _log(f"[SE] !!! {info['aviso']}")
    else:
        _log(f"[SE] esperada={info['se_esperada']} usada={info['se_usada']} atraso_se={atr}")
    return info
