# -*- coding: utf-8 -*-
"""Extração somente-leitura do DW estadual (VW_GAL e views afins) → staging."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Colunas típicas de dbo.VW_GAL (espelho do export GAL LACEN MT)
GAL_SELECT_COLS = [
    "Municipio_Residencia_Paciente",
    "Municipio_Solicitante",
    "IBGE_Municipio_Residencia_Paciente",
    "IBGE_Municipio_Solicitante",
    "Agravo_Requisicao",
    "Agravo_Gal",
    "Exame",
    "Metodologia",
    "Status_Exame",
    "Data_Coleta_dt",
    "Data_Recebimento_dt",
    "Data_Liberacao_dt",
    "Campo_Resultado_1",
    "Campo_Resultado_2",
    "Campo_Resultado_3",
    "Campo_Resultado_4",
    "Campo_Resultado_5",
    "Campo_Resultado_6",
    "Observacao_Resultado",
    "Laboratorio_Cadastro",
]


def _log(msg: str) -> None:
    print(msg, flush=True)


def staging_dir(outdir: Path | str) -> Path:
    p = Path(outdir) / "staging_dw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def check_dw_tcp(timeout: float = 3.0) -> tuple[bool, str, int]:
    """Ping TCP rápido antes do ODBC (evita espera longa sem VPN)."""
    import os
    import socket

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        sis = ROOT.parent / "SISREG" / ".env"
        if sis.exists():
            load_dotenv(sis, override=False)
    except Exception:
        pass

    host = (
        os.getenv("DW_HOST")
        or os.getenv("DW_SERVER")
        or os.getenv("DATAWAREHOUSE_HOST")
        or "10.15.1.50"
    )
    port = int(os.getenv("DW_PORT") or os.getenv("DATAWAREHOUSE_PORT") or "1433")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, host, port
    except OSError as exc:
        return False, host, port


def connect_or_raise():
    ok, host, port = check_dw_tcp()
    if not ok:
        raise ConnectionError(
            f"DW inacessível em {host}:{port} (timeout TCP). "
            "Conecte a VPN SES-MT / rede institucional e tente de novo. "
            "Offline: use --allow-local-fallback (SE pode ficar atrasada)."
        )
    from lacen_dw import connect_dw
    return connect_dw()


def list_relevant_objects(mode: str, queryable: Any) -> pd.DataFrame:
    from lacen_dw import inventariar_fontes_lacen
    return inventariar_fontes_lacen(mode, queryable)


def _safe_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name or ""):
        raise ValueError(f"Identificador SQL inválido: {name!r}")
    return name


def discover_gal_columns(mode: str, queryable: Any, schema: str = "dbo", view: str = "VW_GAL") -> list[str]:
    from lacen_dw import read_sql
    schema, view = _safe_ident(schema), _safe_ident(view)
    df = read_sql(
        mode,
        queryable,
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{view}'
        ORDER BY ORDINAL_POSITION
        """,
    )
    return [str(x) for x in df["COLUMN_NAME"].tolist()]


def extract_vw_gal_weekly_agg(
    mode: str,
    queryable: Any,
    *,
    weeks_back: int = 60,
    schema: str = "dbo",
    view: str = "VW_GAL",
) -> pd.DataFrame:
    """Agrega volume/positivos por SE×município×agravo no próprio DW (leve)."""
    from lacen_dw import read_sql

    schema, view = _safe_ident(schema), _safe_ident(view)
    cols = set(discover_gal_columns(mode, queryable, schema, view))
    date_col = "Data_Liberacao_dt" if "Data_Liberacao_dt" in cols else (
        "Data_Liberacao" if "Data_Liberacao" in cols else None
    )
    if not date_col:
        raise RuntimeError(f"{schema}.{view} sem coluna de liberação.")

    mun_col = next(
        (c for c in (
            "Municipio_Residencia_Paciente",
            "Municipio_Solicitante",
            "Municipio_Notificacao_Gal",
        ) if c in cols),
        None,
    )
    if not mun_col:
        raise RuntimeError(f"{schema}.{view} sem coluna de município.")

    agravo_col = next(
        (c for c in ("Agravo_Requisicao", "Agravo_Gal", "Exame") if c in cols),
        None,
    )
    exame_expr = "Exame" if "Exame" in cols else "NULL"
    status_expr = "Status_Exame" if "Status_Exame" in cols else "NULL"

    result_bits = []
    for c in (
        "Campo_Resultado_1", "Campo_Resultado_2", "Campo_Resultado_3",
        "Campo_Resultado_4", "Campo_Resultado_5", "Campo_Resultado_6",
        "Observacao_Resultado",
    ):
        if c in cols:
            result_bits.append(f"ISNULL(CAST([{c}] AS NVARCHAR(4000)), '')")
    concat_expr = " + ' ' + ".join(result_bits) if result_bits else "''"

    agravo_sql = f"[{agravo_col}]" if agravo_col else "N''"
    days = max(7, int(weeks_back) * 7 + 14)

    sql = f"""
    SELECT
      DATEPART(isoyear, CAST([{date_col}] AS date)) AS epi_year,
      DATEPART(iso_week, CAST([{date_col}] AS date)) AS epi_week,
      UPPER(LTRIM(RTRIM([{mun_col}]))) AS municipio,
      LOWER(LTRIM(RTRIM(CAST({agravo_sql} AS NVARCHAR(400))))) AS agravo_raw,
      LOWER(LTRIM(RTRIM(CAST({exame_expr} AS NVARCHAR(400))))) AS exame_raw,
      COUNT_BIG(*) AS n_registros,
      SUM(CASE
            WHEN {concat_expr} LIKE N'%positiv%' THEN 1
            WHEN {concat_expr} LIKE N'%reagent%' AND {concat_expr} NOT LIKE N'%nao reagent%'
                 AND {concat_expr} NOT LIKE N'%não reagent%' THEN 1
            ELSE 0
          END) AS n_positivos_proxy,
      SUM(CASE
            WHEN LOWER(ISNULL(CAST({status_expr} AS NVARCHAR(200)), '')) LIKE N'%liberad%' THEN 1
            ELSE 0
          END) AS n_liberados,
      MIN(CAST([{date_col}] AS date)) AS dt_min,
      MAX(CAST([{date_col}] AS date)) AS dt_max
    FROM [{schema}].[{view}]
    WHERE [{date_col}] IS NOT NULL
      AND CAST([{date_col}] AS date) >= DATEADD(day, -{days}, CAST(GETDATE() AS date))
      AND CAST([{date_col}] AS date) <= CAST(GETDATE() AS date)
      AND LTRIM(RTRIM([{mun_col}])) <> ''
    GROUP BY
      DATEPART(isoyear, CAST([{date_col}] AS date)),
      DATEPART(iso_week, CAST([{date_col}] AS date)),
      UPPER(LTRIM(RTRIM([{mun_col}]))),
      LOWER(LTRIM(RTRIM(CAST({agravo_sql} AS NVARCHAR(400))))),
      LOWER(LTRIM(RTRIM(CAST({exame_expr} AS NVARCHAR(400)))))
    """
    _log(f"[DW] Agregando {schema}.{view} (últimos ~{weeks_back} SE)…")
    return read_sql(mode, queryable, sql)


def extract_vw_gal_micro_sample(
    mode: str,
    queryable: Any,
    *,
    days_back: int = 120,
    top: int = 250_000,
    schema: str = "dbo",
    view: str = "VW_GAL",
) -> pd.DataFrame:
    """Amostra recente de microdados GAL para TAT/rede (staging)."""
    from lacen_dw import read_sql

    schema, view = _safe_ident(schema), _safe_ident(view)
    cols = set(discover_gal_columns(mode, queryable, schema, view))
    want = [c for c in GAL_SELECT_COLS if c in cols]
    if "Data_Liberacao_dt" not in want and "Data_Liberacao" in cols:
        want.append("Data_Liberacao")
    if not want:
        raise RuntimeError("Nenhuma coluna GAL conhecida na view.")
    date_col = "Data_Liberacao_dt" if "Data_Liberacao_dt" in cols else "Data_Liberacao"
    col_list = ", ".join(f"[{c}]" for c in want)
    sql = f"""
    SELECT TOP ({int(top)}) {col_list}
    FROM [{schema}].[{view}]
    WHERE [{date_col}] IS NOT NULL
      AND CAST([{date_col}] AS date) >= DATEADD(day, -{int(days_back)}, CAST(GETDATE() AS date))
      AND CAST([{date_col}] AS date) <= CAST(GETDATE() AS date)
    ORDER BY [{date_col}] DESC
    """
    _log(f"[DW] Microdados {schema}.{view} TOP {top} / {days_back}d…")
    return read_sql(mode, queryable, sql)


def extract_optional_view(
    mode: str,
    queryable: Any,
    table_name: str,
    *,
    schema: str = "dbo",
    top: int = 50_000,
) -> Optional[pd.DataFrame]:
    from lacen_dw import read_sql
    schema, table_name = _safe_ident(schema), _safe_ident(table_name)
    try:
        return read_sql(
            mode,
            queryable,
            f"SELECT TOP ({int(top)}) * FROM [{schema}].[{table_name}]",
        )
    except Exception as exc:
        _log(f"[DW] View {schema}.{table_name} indisponível: {type(exc).__name__}")
        return None


def run_extract(
    outdir: Path | str = "saida_pipeline",
    *,
    weeks_back: int = 60,
    micro_days: int = 120,
) -> dict[str, Any]:
    """Extrai DW → `saida_pipeline/staging_dw/` e grava inventário."""
    outdir = Path(outdir)
    stage = staging_dir(outdir)
    meta: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "objects": [],
        "files": {},
        "error": None,
    }

    mode, queryable = connect_or_raise()
    try:
        inv = list_relevant_objects(mode, queryable)
        inv_path = stage / "dw_inventory.csv"
        inv.to_csv(inv_path, index=False, encoding="utf-8-sig")
        meta["objects"] = inv.to_dict(orient="records")
        meta["files"]["inventory"] = str(inv_path.name)

        names = set(inv["TABLE_NAME"].astype(str).str.upper())
        gal_view = "VW_GAL" if "VW_GAL" in names else None
        if gal_view is None:
            # fallback fuzzy
            for n in names:
                if "GAL" in n and n.startswith("VW_"):
                    gal_view = n
                    break
        if not gal_view:
            raise RuntimeError(
                "Nenhuma view GAL encontrada (esperado dbo.VW_GAL). "
                f"Objetos: {sorted(names)[:40]}"
            )

        weekly = extract_vw_gal_weekly_agg(
            mode, queryable, weeks_back=weeks_back, view=gal_view
        )
        wpath = stage / "vw_gal_weekly_agg.parquet"
        cpath = stage / "vw_gal_weekly_agg.csv"
        weekly.to_parquet(wpath, index=False)
        weekly.to_csv(cpath, index=False, encoding="utf-8-sig")
        meta["files"]["vw_gal_weekly_agg"] = str(wpath.name)
        meta["gal_view"] = gal_view
        meta["weekly_rows"] = int(len(weekly))
        if not weekly.empty:
            meta["se_max_dw"] = (
                f"{int(weekly['epi_year'].max())}-SE"
                f"{int(weekly.loc[weekly['epi_year'] == weekly['epi_year'].max(), 'epi_week'].max()):02d}"
            )
            meta["exames_proxy"] = int(pd.to_numeric(weekly["n_registros"], errors="coerce").fillna(0).sum())
            meta["positivos_proxy"] = int(pd.to_numeric(weekly["n_positivos_proxy"], errors="coerce").fillna(0).sum())

        micro = extract_vw_gal_micro_sample(
            mode, queryable, days_back=micro_days, view=gal_view
        )
        mpath = stage / "vw_gal_micro_recent.parquet"
        micro.to_parquet(mpath, index=False)
        micro.to_csv(stage / "vw_gal_micro_recent.csv", index=False, encoding="utf-8-sig")
        meta["files"]["vw_gal_micro_recent"] = str(mpath.name)
        meta["micro_rows"] = int(len(micro))

        for cand in ("VW_SINAN", "VW_SIM", "VW_LACEN"):
            if cand in names:
                df = extract_optional_view(mode, queryable, cand)
                if df is not None and not df.empty:
                    p = stage / f"{cand.lower()}.parquet"
                    df.to_parquet(p, index=False)
                    meta["files"][cand.lower()] = str(p.name)
    finally:
        if mode == "pyodbc" and queryable is not None:
            try:
                queryable.close()
            except Exception:
                pass

    meta_path = stage / "extract_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    meta["files"]["extract_meta"] = str(meta_path.name)
    _log(f"[DW] Staging OK → {stage}")
    return meta
