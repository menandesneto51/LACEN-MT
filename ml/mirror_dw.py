# -*- coding: utf-8 -*-
"""Espelho local/DW de escores ML + histórico alerta×desfecho + bulk SQL."""
from __future__ import annotations

import argparse
import json
import socket
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

MIRROR_TABLES = {
    "ml_risco_predito.csv": "lacen_ml_risco_predito",
    "ml_silencio_predito.csv": "lacen_ml_silencio_predito",
    "ml_backtest_summary.csv": "lacen_ml_backtest_summary",
    "alerta_historico.csv": "lacen_alerta_historico",
    "alerta_emergencia_historico.csv": "lacen_alerta_emergencia_historico",
    "fila_operacional.csv": "lacen_fila_operacional",
    "indicadores_rede_laboratorial.csv": "lacen_indicadores_rede",
    "qualidade_dado_municipal.csv": "lacen_qualidade_dado",
}


def dw_reachable(host: str = "10.15.1.50", port: int = 1433, timeout: float = 2.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _load_dw_env() -> dict:
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        # fallback institucional (sem imprimir segredos)
        sis = ROOT.parent / "SISREG" / ".env"
        if sis.exists():
            load_dotenv(sis, override=False)
        titan = ROOT.parent / "AESOP COMPLETO" / "aesop_titan_complete_system" / ".env"
        if titan.exists():
            load_dotenv(titan, override=False)
    except Exception:
        pass
    return {
        "server": os.getenv("DW_SERVER") or os.getenv("DW_HOST") or os.getenv("DATAWAREHOUSE_HOST") or "10.15.1.50",
        "database": os.getenv("DW_DATABASE") or os.getenv("DATAWAREHOUSE_DATABASE"),
        "user": os.getenv("DW_USER") or os.getenv("DATAWAREHOUSE_USER"),
        "password": os.getenv("DW_PASSWORD") or os.getenv("DATAWAREHOUSE_PASSWORD"),
        "driver": os.getenv("DW_ODBC_DRIVER", "ODBC Driver 17 for SQL Server"),
        "schema": os.getenv("DW_SCHEMA", "dbo"),
    }


def append_alerta_emergencia_historico(
    outdir: Path | str,
    emergencia: Optional[pd.DataFrame] = None,
) -> Path:
    """Persiste snapshot semanal de flags de emergência (append/upsert por SE+IBGE).

    Chave: ano_se + semana_epidemiologica + codigo_ibge (fallback municipio).
    Não apaga histórico de outras semanas.
    """
    outdir = Path(outdir)
    hist_path = outdir / "alerta_emergencia_historico.csv"
    if emergencia is None:
        emerg_path = outdir / "indicadores_emergencia.csv"
        if not emerg_path.exists():
            return hist_path
        emergencia = pd.read_csv(emerg_path, low_memory=False)
    if emergencia is None or emergencia.empty:
        return hist_path

    df = emergencia.copy()
    df["municipio"] = df["municipio"].astype(str).str.strip().str.upper()

    # SE de referência (silêncio GAL / weekly); fallback = última SE do weekly
    if "epi_year_ref" in df.columns and df["epi_year_ref"].notna().any():
        ano = int(pd.to_numeric(df["epi_year_ref"], errors="coerce").dropna().iloc[0])
        se = int(pd.to_numeric(df["epi_week_ref"], errors="coerce").dropna().iloc[0])
    else:
        weekly_path = outdir / "integrated_weekly_surveillance.csv"
        if weekly_path.exists():
            w = pd.read_csv(
                weekly_path,
                usecols=lambda c: c in {"epi_year", "epi_week"},
                low_memory=False,
            )
            wk = (
                w[["epi_year", "epi_week"]].dropna()
                .drop_duplicates()
                .sort_values(["epi_year", "epi_week"])
            )
            if wk.empty:
                return hist_path
            ano, se = int(wk.iloc[-1]["epi_year"]), int(wk.iloc[-1]["epi_week"])
        else:
            return hist_path

    # IBGE
    mun_path = outdir / "municipal_master.csv"
    ibge_map = {}
    if mun_path.exists():
        try:
            mm = pd.read_csv(mun_path, usecols=["municipio", "codigo_ibge"], low_memory=False)
            mm["municipio"] = mm["municipio"].astype(str).str.strip().str.upper()
            ibge_map = dict(zip(mm["municipio"], mm["codigo_ibge"]))
        except Exception:
            ibge_map = {}

    faixa = df.get("faixa_pressao", pd.Series("", index=df.index)).astype(str)
    pressao_alta = faixa.isin(["alta", "critica"])
    if "indice_pressao_rede" in df.columns:
        pressao_alta = pressao_alta | (
            pd.to_numeric(df["indice_pressao_rede"], errors="coerce").fillna(0) >= 55
        )

    ts = datetime.now().isoformat(timespec="seconds")
    rows = []
    for _, r in df.iterrows():
        mun = r["municipio"]
        rows.append({
            "ano_se": ano,
            "semana_epidemiologica": se,
            "codigo_ibge": ibge_map.get(mun, r.get("codigo_ibge", "")),
            "municipio": mun,
            "sla_crise": bool(r.get("sla_crise", False)),
            "silencio_gal_alerta": bool(r.get("silencio_gal_alerta", False)),
            "divergencia_gal_notif": bool(r.get("divergencia_gal_notif", False)),
            "faixa_pressao": str(r.get("faixa_pressao", "") or ""),
            "pressao_alta": bool(pressao_alta.loc[r.name] if r.name in pressao_alta.index else False),
            "indice_pressao_rede": r.get("indice_pressao_rede"),
            "prob_pressao_alta_proxima_janela": r.get("prob_pressao_alta_proxima_janela"),
            "faixa_pressao_predita": r.get("faixa_pressao_predita"),
            "pressao_predita_acima_limiar": r.get("pressao_predita_acima_limiar"),
            "prioridade_emergencia": r.get("prioridade_emergencia"),
            "ts_geracao": ts,
            "tipo_sinal": "Observado",
        })

    novo = pd.DataFrame(rows)
    novo["fonte_stamp"] = "indicadores_emergencia"
    # Upsert: mesma SE+mun substitui; outras SE permanecem
    key = ["ano_se", "semana_epidemiologica", "municipio"]
    if hist_path.exists():
        try:
            old = pd.read_csv(hist_path, low_memory=False)
        except Exception:
            old = pd.DataFrame()
        if not old.empty:
            comb = pd.concat([old, novo], ignore_index=True)
            comb = comb.drop_duplicates(subset=[c for c in key if c in comb.columns], keep="last")
        else:
            comb = novo
    else:
        comb = novo

    comb.to_csv(hist_path, index=False, encoding="utf-8-sig")
    try:
        comb.to_parquet(outdir / "alerta_emergencia_historico.parquet", index=False)
    except Exception:
        pass

    # Se histórico ainda curto (<2 SE), faz seed retroativo das SE anteriores
    # para habilitar confirmação prospectiva Observado sem esperar semanas.
    try:
        n_se = int(
            comb[["ano_se", "semana_epidemiologica"]].dropna().drop_duplicates().shape[0]
        )
        if n_se < 2:
            comb = _seed_emergencia_historico_retro(outdir, comb, n_weeks=8)
            comb.to_csv(hist_path, index=False, encoding="utf-8-sig")
            try:
                comb.to_parquet(outdir / "alerta_emergencia_historico.parquet", index=False)
            except Exception:
                pass
    except Exception:
        pass
    return hist_path


def _seed_emergencia_historico_retro(
    outdir: Path,
    existing: pd.DataFrame,
    n_weeks: int = 8,
) -> pd.DataFrame:
    """Carimba SE anteriores via flags retrospectivos (uma vez, se histórico curto)."""
    import numpy as np
    from gerar_confirmacao_emergencia import _flags_for_week, _mun_week_vol, _read

    weekly = _read(outdir, "integrated_weekly_surveillance.csv")
    if weekly.empty:
        return existing
    rede = _read(outdir, "indicadores_emergencia.csv")
    if rede.empty:
        rede = _read(outdir, "indicadores_rede_laboratorial.csv")
    vol = _mun_week_vol(weekly)
    all_weeks = (
        vol[["epi_year", "epi_week"]].drop_duplicates()
        .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    )
    if len(all_weeks) < 3:
        return existing

    seed_weeks = all_weeks.iloc[max(0, len(all_weeks) - n_weeks - 1) : -1]
    mun_path = outdir / "municipal_master.csv"
    ibge_map = {}
    if mun_path.exists():
        try:
            mm = pd.read_csv(mun_path, usecols=["municipio", "codigo_ibge"], low_memory=False)
            mm["municipio"] = mm["municipio"].astype(str).str.strip().str.upper()
            ibge_map = dict(zip(mm["municipio"], mm["codigo_ibge"]))
        except Exception:
            pass

    ts = datetime.now().isoformat(timespec="seconds")
    rows = []
    for _, wk in seed_weeks.iterrows():
        y, w = int(wk["epi_year"]), int(wk["epi_week"])
        flags = _flags_for_week(vol, y, w, rede, all_weeks)
        if flags.empty:
            continue
        for _, r in flags.iterrows():
            mun = str(r["municipio"]).strip().upper()
            rows.append({
                "ano_se": y,
                "semana_epidemiologica": w,
                "codigo_ibge": ibge_map.get(mun, ""),
                "municipio": mun,
                "sla_crise": bool(r.get("sla_crise", False)),
                "silencio_gal_alerta": bool(r.get("silencio_gal", False)),
                "divergencia_gal_notif": bool(r.get("divergencia", False)),
                "faixa_pressao": str(r.get("faixa_pressao", "") or ""),
                "pressao_alta": bool(r.get("pressao_alta", False)),
                "indice_pressao_rede": r.get("indice_pressao_rede"),
                "prob_pressao_alta_proxima_janela": np.nan,
                "faixa_pressao_predita": "",
                "pressao_predita_acima_limiar": "",
                "prioridade_emergencia": "",
                "ts_geracao": ts,
                "tipo_sinal": "Observado",
                "fonte_stamp": "seed_retro_inicial",
            })
    if not rows:
        return existing
    novo = pd.DataFrame(rows)
    if "fonte_stamp" not in existing.columns:
        existing = existing.copy()
        existing["fonte_stamp"] = "indicadores_emergencia"
    comb = pd.concat([existing, novo], ignore_index=True)
    key = ["ano_se", "semana_epidemiologica", "municipio"]
    return comb.drop_duplicates(subset=[c for c in key if c in comb.columns], keep="first")


def append_alerta_historico(
    outdir: Path | str,
    ml_risco: Optional[pd.DataFrame] = None,
    ml_silencio: Optional[pd.DataFrame] = None,
    horizon_weeks: int = 2,
) -> Path:
    outdir = Path(outdir)
    hist_path = outdir / "alerta_historico.csv"
    today = date.today().isoformat()
    rows = []

    if ml_risco is not None and not ml_risco.empty:
        rr = ml_risco.copy()
        if "acima_limiar" in rr.columns:
            rr = rr[rr["acima_limiar"].fillna(False)]
        elif "prob_alerta_proxima_janela" in rr.columns:
            thr = float(rr["limiar_operacional"].median()) if "limiar_operacional" in rr.columns else 0.25
            rr = rr[rr["prob_alerta_proxima_janela"] >= thr]
        for _, r in rr.head(200).iterrows():
            rows.append({
                "data_emissao": today,
                "tipo": "risco",
                "municipio": r.get("municipio"),
                "agravo_alvo": r.get("target"),
                "epi_year": r.get("epi_year"),
                "epi_week": r.get("epi_week"),
                "prob": r.get("prob_alerta_proxima_janela"),
                "horizon_weeks": horizon_weeks,
                "desfecho": "",
                "confirmado": "",
            })

    if ml_silencio is not None and not ml_silencio.empty:
        ss = ml_silencio.copy()
        if "acima_limiar" in ss.columns:
            ss = ss[ss["acima_limiar"].fillna(False)]
        for _, r in ss.head(200).iterrows():
            rows.append({
                "data_emissao": today,
                "tipo": "silencio",
                "municipio": r.get("municipio"),
                "agravo_alvo": r.get("target"),
                "epi_year": r.get("epi_year"),
                "epi_week": r.get("epi_week"),
                "prob": r.get("prob_silencio_proxima_janela"),
                "horizon_weeks": horizon_weeks,
                "desfecho": "",
                "confirmado": "",
            })

    novo = pd.DataFrame(rows)
    if hist_path.exists() and not novo.empty:
        old = pd.read_csv(hist_path, low_memory=False)
        key = ["data_emissao", "tipo", "municipio", "agravo_alvo", "epi_year", "epi_week"]
        comb = pd.concat([old, novo], ignore_index=True)
        comb = comb.drop_duplicates(subset=[c for c in key if c in comb.columns], keep="last")
    else:
        comb = novo if not novo.empty else (pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame())

    comb.to_csv(hist_path, index=False, encoding="utf-8-sig")
    return hist_path


def _epi_add(year: int, week: int, delta: int) -> tuple[int, int]:
    """Avança semanas epidemiológicas (aprox. ISO 1..52)."""
    y, w = int(year), int(week) + int(delta)
    while w > 52:
        w -= 52
        y += 1
    while w < 1:
        w += 52
        y -= 1
    return y, w


def _epi_le(y1: int, w1: int, y2: int, w2: int) -> bool:
    return (int(y1), int(w1)) <= (int(y2), int(w2))


def seed_alertas_retrospectivos(
    outdir: Path | str,
    max_risco: int = 150,
    max_silencio: int = 150,
    horizon_weeks: int = 2,
) -> Path:
    """Carimba alertas em semanas com horizonte já observável (não só a fronteira).

    Necessário para o loop alerta×desfecho ter pares de risco avaliáveis: o stamp
    operacional só pega a última SE de cada série (ainda sem futuro).
    """
    outdir = Path(outdir)
    hist_path = outdir / "alerta_historico.csv"
    weekly_path = outdir / "integrated_weekly_surveillance.csv"
    if not weekly_path.exists():
        return hist_path

    w = pd.read_csv(
        weekly_path,
        usecols=lambda c: c in {
            "municipio", "target", "epi_year", "epi_week", "tests", "positives",
            "positividade", "risco_composto", "notificacoes",
        },
        low_memory=False,
    )
    if w.empty:
        return hist_path

    w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
    for c in ("tests", "positives", "positividade", "risco_composto", "notificacoes", "epi_year", "epi_week"):
        if c in w.columns:
            w[c] = pd.to_numeric(w[c], errors="coerce")
    w["tests"] = w["tests"].fillna(0)
    w["positives"] = w["positives"].fillna(0)
    w["risco_composto"] = w["risco_composto"].fillna(0)
    w["positividade"] = w["positividade"].fillna(0)
    if "notificacoes" not in w.columns:
        w["notificacoes"] = 0.0
    w["notificacoes"] = pd.to_numeric(w["notificacoes"], errors="coerce").fillna(0)

    max_y = int(w["epi_year"].max())
    max_w = int(w.loc[w["epi_year"] == max_y, "epi_week"].max())

    rows_risco: list[dict] = []
    rows_sil: list[dict] = []
    w = w.sort_values(["municipio", "target", "epi_year", "epi_week"])
    for (mun, tgt), g in w.groupby(["municipio", "target"], sort=False):
        g = g.reset_index(drop=True)
        if len(g) < horizon_weeks + 1:
            continue
        for i in range(0, len(g) - horizon_weeks):
            r = g.iloc[i]
            y, wk = int(r["epi_year"]), int(r["epi_week"])
            hy, hw = _epi_add(y, wk, horizon_weeks)
            if not _epi_le(hy, hw, max_y, max_w):
                continue
            alerta = (
                (r["risco_composto"] >= 1.2)
                or ((r["positividade"] >= 0.25) and (r["tests"] >= 2))
                or (r["positives"] >= 2)
            )
            silencio = float(r["tests"]) <= 0
            if alerta and len(rows_risco) < max_risco:
                rows_risco.append({
                    "data_emissao": "retrospectivo",
                    "tipo": "risco",
                    "municipio": mun,
                    "agravo_alvo": tgt,
                    "epi_year": y,
                    "epi_week": wk,
                    "prob": float(min(0.99, 0.5 + 0.1 * float(r["risco_composto"]))),
                    "horizon_weeks": horizon_weeks,
                    "desfecho": "",
                    "confirmado": "",
                })
            if silencio and len(rows_sil) < max_silencio:
                rows_sil.append({
                    "data_emissao": "retrospectivo",
                    "tipo": "silencio",
                    "municipio": mun,
                    "agravo_alvo": tgt,
                    "epi_year": y,
                    "epi_week": wk,
                    "prob": 0.7,
                    "horizon_weeks": horizon_weeks,
                    "desfecho": "",
                    "confirmado": "",
                })
        if len(rows_risco) >= max_risco and len(rows_sil) >= max_silencio:
            break

    rows = rows_risco + rows_sil
    if not rows:
        return hist_path

    novo = pd.DataFrame(rows)
    if hist_path.exists():
        old = pd.read_csv(hist_path, low_memory=False)
        comb = pd.concat([old, novo], ignore_index=True)
    else:
        comb = novo
    key = ["data_emissao", "tipo", "municipio", "agravo_alvo", "epi_year", "epi_week"]
    comb = comb.drop_duplicates(subset=[c for c in key if c in comb.columns], keep="last")
    comb.to_csv(hist_path, index=False, encoding="utf-8-sig")
    return hist_path


def atualizar_desfechos(outdir: Path | str) -> Path:
    """Fecha alerta×desfecho após horizonte SE.

    Séries laboratoriais são esparsas: ausência de linha em SE+1..SE+2, depois que a
    semana estadual já passou do horizonte, conta como zero exames (risco não
    confirmado / silêncio confirmado). Enquanto o horizonte ainda não venceu,
    mantém desfecho em aberto.
    """
    outdir = Path(outdir)
    hist_path = outdir / "alerta_historico.csv"
    weekly_csv = outdir / "integrated_weekly_surveillance.csv"
    weekly_pq = outdir / "integrated_weekly_surveillance.parquet"
    if not hist_path.exists() or not (weekly_csv.exists() or weekly_pq.exists()):
        return hist_path

    hist = pd.read_csv(hist_path, low_memory=False)
    if hist.empty or "municipio" not in hist.columns:
        return hist_path

    usecols = {
        "municipio", "target", "epi_year", "epi_week", "tests", "positives", "positividade",
        "notificacoes", "risco_composto",
    }
    if weekly_csv.exists():
        w = pd.read_csv(weekly_csv, usecols=lambda c: c in usecols, low_memory=False)
    else:
        w = pd.read_parquet(weekly_pq)
        w = w[[c for c in w.columns if c in usecols]]

    w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
    hist["municipio"] = hist["municipio"].astype(str).str.strip().str.upper()
    w["positividade"] = pd.to_numeric(w.get("positividade"), errors="coerce")
    w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0)
    w["positives"] = pd.to_numeric(w.get("positives"), errors="coerce").fillna(0)
    w["risco_composto"] = pd.to_numeric(w.get("risco_composto"), errors="coerce").fillna(0)

    # Fronteira estadual: só fecha desfecho quando a SE de referência já avançou.
    max_y = int(pd.to_numeric(w["epi_year"], errors="coerce").max())
    max_w = int(
        pd.to_numeric(w.loc[w["epi_year"] == max_y, "epi_week"], errors="coerce").max()
    )

    def _horizon_elapsed(y, wk, horizon: int) -> bool:
        hy, hw = _epi_add(int(y), int(wk), int(horizon))
        return _epi_le(hy, hw, max_y, max_w)

    def _future_window(r, horizon: int) -> pd.DataFrame:
        y, wk = r.get("epi_year"), r.get("epi_week")
        if pd.isna(y) or pd.isna(wk):
            return w.iloc[0:0]
        y, wk = int(y), int(wk)
        weeks = [_epi_add(y, wk, d) for d in range(1, horizon + 1)]
        mask = False
        for fy, fw in weeks:
            mask = mask | ((w["epi_year"] == fy) & (w["epi_week"] == fw))
        return w[
            (w["municipio"] == r["municipio"])
            & (w["target"].astype(str) == str(r.get("agravo_alvo", "")))
            & mask
        ]

    def _confirm_risco(r) -> str:
        y, wk = r.get("epi_year"), r.get("epi_week")
        if pd.isna(y) or pd.isna(wk):
            return ""
        horizon = int(pd.to_numeric(r.get("horizon_weeks"), errors="coerce") or 2)
        if not _horizon_elapsed(y, wk, horizon):
            return ""
        fut = _future_window(r, horizon)
        if fut.empty:
            return "0"
        hit = (
            (fut["risco_composto"] >= 1.2).any()
            | ((fut["positividade"].fillna(0) >= 0.25) & (fut["tests"] >= 2)).any()
            | (fut["positives"] >= 2).any()
        )
        return "1" if hit else "0"

    def _confirm_sil(r) -> str:
        y, wk = r.get("epi_year"), r.get("epi_week")
        if pd.isna(y) or pd.isna(wk):
            return ""
        if not _horizon_elapsed(y, wk, 1):
            return ""
        fut = _future_window(r, 1)
        if fut.empty:
            return "1"
        return "1" if float(fut["tests"].sum()) <= 0 else "0"

    hist["confirmado"] = hist["confirmado"].astype(object)
    hist["desfecho"] = hist["desfecho"].astype(object)
    conf = hist["confirmado"]
    mask_open = conf.isna() | conf.astype(str).str.strip().str.lower().isin(
        ["", "nan", "none", "<na>", "nat"]
    )
    for idx in hist.loc[mask_open].index:
        tipo = str(hist.at[idx, "tipo"])
        if tipo == "risco":
            c = _confirm_risco(hist.loc[idx])
            hist.at[idx, "confirmado"] = c
            hist.at[idx, "desfecho"] = (
                "alerta_lab" if c == "1" else ("sem_confirmacao" if c == "0" else "")
            )
        elif tipo == "silencio":
            c = _confirm_sil(hist.loc[idx])
            hist.at[idx, "confirmado"] = c
            hist.at[idx, "desfecho"] = (
                "silencio" if c == "1" else ("com_exame" if c == "0" else "")
            )

    def _norm_flag(v) -> str:
        if pd.isna(v):
            return ""
        s = str(v).strip().lower()
        if s in {"", "nan", "none", "<na>", "nat"}:
            return ""
        if s in {"0", "0.0", "false"}:
            return "0"
        if s in {"1", "1.0", "true"}:
            return "1"
        try:
            return str(int(float(s)))
        except Exception:
            return ""

    hist["confirmado"] = hist["confirmado"].map(_norm_flag)
    hist["desfecho"] = hist["desfecho"].map(
        lambda v: "" if pd.isna(v) or str(v).strip().lower() in {"", "nan", "none"} else str(v)
    )

    hist.to_csv(hist_path, index=False, encoding="utf-8-sig")
    try:
        hist.to_parquet(outdir / "alerta_historico.parquet", index=False)
    except Exception:
        pass
    return hist_path


def _sql_type(series: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "FLOAT"
    if pd.api.types.is_bool_dtype(series):
        return "BIT"
    return "NVARCHAR(500)"


def _pick_odbc_driver(preferred: str | None = None) -> str:
    import pyodbc
    installed = list(pyodbc.drivers())
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend([
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ])
    for d in candidates:
        if d in installed:
            return d
    raise RuntimeError(
        "Nenhum driver ODBC SQL Server encontrado. Instalados: "
        + (", ".join(installed) if installed else "(nenhum)")
    )


def _ensure_table(cursor, schema: str, table: str, df: pd.DataFrame) -> str:
    """Garante tabela. Retorna 'created'|'exists'|'denied'."""
    cols_sql = ", ".join(f"[{c}] {_sql_type(df[c])}" for c in df.columns)
    cursor.execute(
        f"""
        SELECT CASE WHEN OBJECT_ID(N'[{schema}].[{table}]', N'U') IS NULL THEN 0 ELSE 1 END
        """
    )
    exists = int(cursor.fetchone()[0]) == 1
    if exists:
        return "exists"
    try:
        cursor.execute(
            f"""
            CREATE TABLE [{schema}].[{table}] (
                {cols_sql},
                [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            );
            """
        )
        return "created"
    except Exception as exc:
        if "permission denied" in str(exc).casefold() or "262" in str(exc):
            return "denied"
        raise


def _replace_table_rows(cursor, schema: str, table: str, df: pd.DataFrame) -> int:
    cursor.execute(f"DELETE FROM [{schema}].[{table}]")
    if df.empty:
        return 0
    cols = list(df.columns)
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(f"[{c}]" for c in cols)
    sql = f"INSERT INTO [{schema}].[{table}] ({col_list}) VALUES ({placeholders})"
    records = []
    for row in df.itertuples(index=False, name=None):
        records.append(tuple(None if pd.isna(v) else v for v in row))
    cursor.fast_executemany = True
    cursor.executemany(sql, records)
    return len(records)


def write_ddl_script(outdir: Path, schema: str = "dbo") -> Path:
    """Gera script SQL para o DBA criar as tabelas lacen_*."""
    sql_dir = Path(outdir) / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    path = sql_dir / "create_lacen_ml_tables.sql"
    lines = [
        "-- LACEN MT — DDL para espelho ML no Datawarehouse",
        "-- Executar com usuário que tenha CREATE TABLE no schema alvo.",
        f"-- Schema sugerido: {schema}",
        "",
    ]
    for fname, table in MIRROR_TABLES.items():
        csv_path = Path(outdir) / fname
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path, nrows=5, low_memory=False)
        cols_sql = ",\n    ".join(f"[{c}] {_sql_type(df[c])}" for c in df.columns)
        lines.append(
            f"""
IF OBJECT_ID(N'[{schema}].[{table}]', N'U') IS NULL
BEGIN
    CREATE TABLE [{schema}].[{table}] (
    {cols_sql},
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO
""".strip()
        )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def mirror_to_dw(outdir: Path | str, do_bulk: bool = True) -> dict:
    """Espelha CSVs ML no SQL Server (CREATE+REPLACE) quando VPN/.env OK."""
    outdir = Path(outdir)
    status = {
        "dw_ok": dw_reachable(),
        "mirrored": [],
        "rows": {},
        "skipped_create_denied": [],
        "error": None,
        "ts": datetime.now().isoformat() + "Z",
    }
    status_path = outdir / "ml_dw_mirror_status.json"
    ddl_path = write_ddl_script(outdir)
    status["ddl_script"] = str(ddl_path.name)

    if not status["dw_ok"]:
        status["error"] = "DW inacessível (VPN/rede). Escores permanecem em saida_pipeline."
        status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        return status

    try:
        import pyodbc
        cfg = _load_dw_env()
        if not all([cfg["database"], cfg["user"], cfg["password"]]):
            status["error"] = "Variáveis DW_* / DATAWAREHOUSE_* ausentes no .env"
            status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
            return status

        driver = _pick_odbc_driver(cfg.get("driver"))
        status["driver"] = driver
        conn_str = (
            f"DRIVER={{{driver}}};SERVER={cfg['server']};"
            f"DATABASE={cfg['database']};UID={cfg['user']};PWD={cfg['password']};"
            f"TrustServerCertificate=yes;"
        )
        conn = pyodbc.connect(conn_str, timeout=8)
        cursor = conn.cursor()
        schema = cfg["schema"]

        for fname, table in MIRROR_TABLES.items():
            path = outdir / fname
            if not path.exists():
                continue
            df = pd.read_csv(path, low_memory=False)
            if len(df) > 20000:
                df = df.head(20000)
            status["mirrored"].append(fname)
            if not do_bulk:
                continue
            state = _ensure_table(cursor, schema, table, df)
            if state == "denied":
                status["skipped_create_denied"].append(table)
                continue
            n = _replace_table_rows(cursor, schema, table, df)
            status["rows"][table] = n
        conn.commit()
        cursor.close()
        conn.close()
        if status["skipped_create_denied"] and not status["rows"]:
            status["error"] = (
                "Conectado ao DW, mas sem permissão CREATE TABLE. "
                f"Peça ao DBA para rodar saida_pipeline/sql/{ddl_path.name} "
                "e depois reexecute: python -m ml.mirror_dw"
            )
        else:
            status["note"] = f"Bulk parcial/OK no schema {schema}. Tabelas atualizadas: {list(status['rows'])}"
    except Exception as exc:
        status["error"] = str(exc)

    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def build_executive_summaries(outdir: Path | str) -> list[Path]:
    outdir = Path(outdir)
    done = []
    weekly = outdir / "integrated_weekly_surveillance.csv"
    if weekly.exists():
        w = pd.read_csv(weekly, low_memory=False)
        w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0)
        w["positives"] = pd.to_numeric(w.get("positives"), errors="coerce").fillna(0)
        weeks = w[["epi_year", "epi_week"]].drop_duplicates().sort_values(["epi_year", "epi_week"]).tail(8)
        recent = w.merge(weeks, on=["epi_year", "epi_week"], how="inner")
        state = pd.DataFrame([{
            "epi_year_max": int(weeks["epi_year"].max()),
            "epi_week_max": int(weeks["epi_week"].max()),
            "exames_8sem": float(recent["tests"].sum()),
            "positivos_8sem": float(recent["positives"].sum()),
            "positividade_8sem": float(recent["positives"].sum() / recent["tests"].sum()) if recent["tests"].sum() else None,
            "municipios": int(recent["municipio"].nunique()),
            "agravos": int(recent["target"].nunique()),
        }])
        p = outdir / "executive_state_summary.csv"
        state.to_csv(p, index=False, encoding="utf-8-sig")
        done.append(p)
        try:
            state.to_parquet(outdir / "executive_state_summary.parquet", index=False)
        except Exception:
            pass

    for src, dst in (
        ("municipios_em_risco.csv", "executive_municipality_summary.csv"),
        ("ml_risco_predito.csv", "executive_alerts.csv"),
        ("indicadores_rede_laboratorial.csv", "executive_rede_summary.csv"),
    ):
        sp = outdir / src
        if sp.exists():
            df = pd.read_csv(sp, low_memory=False).head(200)
            dp = outdir / dst
            df.to_csv(dp, index=False, encoding="utf-8-sig")
            done.append(dp)
            try:
                df.to_parquet(dp.with_suffix(".parquet"), index=False)
            except Exception:
                pass
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="saida_pipeline")
    ap.add_argument("--no-bulk", action="store_true")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    risco = pd.read_csv(outdir / "ml_risco_predito.csv") if (outdir / "ml_risco_predito.csv").exists() else None
    sil = pd.read_csv(outdir / "ml_silencio_predito.csv") if (outdir / "ml_silencio_predito.csv").exists() else None
    append_alerta_historico(outdir, risco, sil)
    seed_alertas_retrospectivos(outdir)
    atualizar_desfechos(outdir)
    build_executive_summaries(outdir)
    st = mirror_to_dw(outdir, do_bulk=not args.no_bulk)
    print("[MIRROR]", {k: st.get(k) for k in ("dw_ok", "mirrored", "rows", "error", "note")}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
