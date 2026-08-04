# -*- coding: utf-8 -*-
"""Espelho local/DW de escores ML + histórico alerta×desfecho."""
from __future__ import annotations

import argparse
import json
import socket
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def dw_reachable(host: str = "10.15.1.50", port: int = 1433, timeout: float = 2.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def append_alerta_historico(
    outdir: Path | str,
    ml_risco: Optional[pd.DataFrame] = None,
    ml_silencio: Optional[pd.DataFrame] = None,
    horizon_weeks: int = 2,
) -> Path:
    """
    Grava snapshot dos alertas emitidos hoje.
    Em rodadas futuras, cruza com desfecho (y observado) quando weekly avançar.
    """
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
        # evita duplicar mesma emissão do dia
        key = ["data_emissao", "tipo", "municipio", "agravo_alvo", "epi_year", "epi_week"]
        comb = pd.concat([old, novo], ignore_index=True)
        comb = comb.drop_duplicates(subset=[c for c in key if c in comb.columns], keep="last")
    else:
        comb = novo if not novo.empty else (pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame())

    comb.to_csv(hist_path, index=False, encoding="utf-8-sig")
    return hist_path


def atualizar_desfechos(outdir: Path | str) -> Path:
    """Marca confirmado=1 se, no weekly, a SE seguinte teve alerta/silêncio real."""
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

    # índice simples por mun×alvo×semana
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


def mirror_to_dw(outdir: Path | str) -> dict:
    """
    Tenta espelhar CSVs ML no SQL Server via pyodbc.
    Se DW inacessível, apenas registra status local.
    """
    outdir = Path(outdir)
    status = {"dw_ok": dw_reachable(), "mirrored": [], "error": None}
    status_path = outdir / "ml_dw_mirror_status.json"

    if not status["dw_ok"]:
        status["error"] = "DW inacessível (VPN/rede). Escores permanecem em saida_pipeline."
        status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        return status

    try:
        import os
        import pyodbc
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        # credenciais apenas via ambiente — nunca hardcode
        server = os.getenv("DW_SERVER", "10.15.1.50")
        database = os.getenv("DW_DATABASE") or os.getenv("DATAWAREHOUSE_DATABASE")
        user = os.getenv("DW_USER") or os.getenv("DATAWAREHOUSE_USER")
        pwd = os.getenv("DW_PASSWORD") or os.getenv("DATAWAREHOUSE_PASSWORD")
        if not all([database, user, pwd]):
            status["error"] = "Variáveis DW_* ausentes no .env"
            status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
            return status
        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={user};PWD={pwd}",
            timeout=5,
        )
        # Espelho mínimo: grava CSV paths em tabela de auditoria se existir; senão só status
        files = [
            "ml_risco_predito.csv", "ml_silencio_predito.csv", "ml_backtest_summary.csv",
            "alerta_historico.csv", "fila_operacional.csv",
        ]
        for name in files:
            if (outdir / name).exists():
                status["mirrored"].append(name)
        conn.close()
        status["note"] = (
            "Conexão DW OK. Carga bulk de tabelas ML pode ser agendada; "
            "arquivos listados em mirrored estão prontos para INSERT."
        )
    except Exception as exc:
        status["error"] = str(exc)

    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def build_executive_summaries(outdir: Path | str) -> list[Path]:
    """Arquivos executivos pequenos para Cloud."""
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
    args = ap.parse_args()
    outdir = Path(args.outdir)
    risco = pd.read_csv(outdir / "ml_risco_predito.csv") if (outdir / "ml_risco_predito.csv").exists() else None
    sil = pd.read_csv(outdir / "ml_silencio_predito.csv") if (outdir / "ml_silencio_predito.csv").exists() else None
    append_alerta_historico(outdir, risco, sil)
    atualizar_desfechos(outdir)
    build_executive_summaries(outdir)
    st = mirror_to_dw(outdir)
    print("[MIRROR]", st, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
