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


def atualizar_desfechos(outdir: Path | str) -> Path:
    outdir = Path(outdir)
    hist_path = outdir / "alerta_historico.csv"
    weekly_path = outdir / "integrated_weekly_surveillance.csv"
    if not hist_path.exists() or not weekly_path.exists():
        return hist_path

    hist = pd.read_csv(hist_path, low_memory=False)
    if hist.empty or "municipio" not in hist.columns:
        return hist_path

    w = pd.read_csv(weekly_path, usecols=lambda c: c in {
        "municipio", "target", "epi_year", "epi_week", "tests", "positives", "positividade",
        "notificacoes", "risco_composto",
    }, low_memory=False)
    w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
    hist["municipio"] = hist["municipio"].astype(str).str.strip().str.upper()
    w["positividade"] = pd.to_numeric(w.get("positividade"), errors="coerce")
    w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0)
    w["positives"] = pd.to_numeric(w.get("positives"), errors="coerce").fillna(0)
    w["risco_composto"] = pd.to_numeric(w.get("risco_composto"), errors="coerce").fillna(0)

    def _confirm_risco(r) -> str:
        y, wk = r.get("epi_year"), r.get("epi_week")
        if pd.isna(y) or pd.isna(wk):
            return ""
        fut = w[
            (w["municipio"] == r["municipio"])
            & (w["target"].astype(str) == str(r.get("agravo_alvo", "")))
            & (
                ((w["epi_year"] == y) & (w["epi_week"] > wk) & (w["epi_week"] <= wk + 2))
                | ((w["epi_year"] == y + 1) & (wk >= 51) & (w["epi_week"] <= 2))
            )
        ]
        if fut.empty:
            return ""
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
        fut = w[
            (w["municipio"] == r["municipio"])
            & (w["target"].astype(str) == str(r.get("agravo_alvo", "")))
            & (w["epi_year"] == y)
            & (w["epi_week"] == wk + 1)
        ]
        if fut.empty:
            return ""
        return "1" if float(fut["tests"].sum()) <= 0 else "0"

    mask_open = hist["confirmado"].astype(str).isin(["", "nan", "None"])
    for idx in hist.loc[mask_open].index:
        tipo = str(hist.at[idx, "tipo"])
        if tipo == "risco":
            hist.at[idx, "confirmado"] = _confirm_risco(hist.loc[idx])
            hist.at[idx, "desfecho"] = "alerta_lab" if hist.at[idx, "confirmado"] == "1" else (
                "sem_confirmacao" if hist.at[idx, "confirmado"] == "0" else ""
            )
        elif tipo == "silencio":
            hist.at[idx, "confirmado"] = _confirm_sil(hist.loc[idx])
            hist.at[idx, "desfecho"] = "silencio" if hist.at[idx, "confirmado"] == "1" else (
                "com_exame" if hist.at[idx, "confirmado"] == "0" else ""
            )

    hist.to_csv(hist_path, index=False, encoding="utf-8-sig")
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
    atualizar_desfechos(outdir)
    build_executive_summaries(outdir)
    st = mirror_to_dw(outdir, do_bulk=not args.no_bulk)
    print("[MIRROR]", {k: st.get(k) for k in ("dw_ok", "mirrored", "rows", "error", "note")}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
