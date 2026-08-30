# -*- coding: utf-8 -*-
"""
Extração leve de hosts externos ao DW estadual: IndicaSUS e SISREG.

Falha soft por fonte (nunca bloqueia ETL/CIEVS). Amostras TOP N / janela recente —
sem dump completo de produção.
"""
from __future__ import annotations

import json
import os
import re
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _log(msg: str) -> None:
    print(msg, flush=True)


def _safe_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name or ""):
        raise ValueError(f"Identificador SQL inválido: {name!r}")
    return name


def _load_env() -> None:
    try:
        from lacen_dw import _load_dotenv_files

        _load_dotenv_files()
    except Exception:
        try:
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env", override=False)
        except Exception:
            pass


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = str(os.getenv(n, "") or "").strip()
        if v:
            return v
    return default


def _truthy(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on")


def check_tcp(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def build_odbc(
    *,
    host: str,
    port: str,
    database: str,
    user: str,
    password: str,
    trust: str = "yes",
    encrypt: str = "no",
) -> str:
    driver = _env(
        "DW_DRIVER",
        "DW_ODBC_DRIVER",
        "SQLSERVER_DRIVER",
        default="ODBC Driver 18 for SQL Server",
    )
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
    )


def connect_odbc(odbc: str) -> tuple[str, Any]:
    try:
        from sqlalchemy import create_engine

        url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc)
        engine = create_engine(url, pool_pre_ping=True, future=True)
        return "sqlalchemy", engine
    except Exception:
        import pyodbc

        return "pyodbc", pyodbc.connect(odbc, timeout=15)


def read_sql(mode: str, queryable: Any, sql: str) -> pd.DataFrame:
    if mode == "sqlalchemy":
        from sqlalchemy import text

        return pd.read_sql_query(text(sql), queryable)
    return pd.read_sql_query(sql, queryable)


def close_conn(mode: str, queryable: Any) -> None:
    if mode == "pyodbc" and queryable is not None:
        try:
            queryable.close()
        except Exception:
            pass


def _save_df(stage: Path, stem: str, df: pd.DataFrame) -> dict[str, str]:
    files: dict[str, str] = {}
    pq = stage / f"{stem}.parquet"
    csv = stage / f"{stem}.csv"
    df.to_parquet(pq, index=False)
    df.to_csv(csv, index=False, encoding="utf-8-sig")
    files[stem] = pq.name
    files[f"{stem}_csv"] = csv.name
    return files


# ---------------------------------------------------------------------------
# IndicaSUS
# ---------------------------------------------------------------------------


def connect_indicasus() -> tuple[Optional[str], Any, dict[str, Any]]:
    """
    Conecta IndicaSUS. Credenciais nativas INDICASUS_* têm prioridade;
    se INDICASUS_USE_DW_CREDENTIALS=true, tenta DW_* depois (costuma falhar).
    """
    _load_env()
    host = _env("INDICASUS_HOST", "INDICASUS_SERVER")
    port = _env("INDICASUS_PORT", default="1433")
    database = _env("INDICASUS_DATABASE", "INDICASUS_DB")
    user = _env("INDICASUS_USER")
    password = _env("INDICASUS_PASSWORD")
    trust = _env("INDICASUS_TRUST_CERT", "INDICASUS_TRUST_SERVER_CERTIFICATE", default="yes")
    encrypt = _env("INDICASUS_ENCRYPT", default="no")
    meta: dict[str, Any] = {
        "host": host or None,
        "port": int(port) if port else None,
        "database": database or None,
        "user": user or None,
        "ok": False,
    }
    if not host or not database or not user or not password:
        meta["error"] = "INDICASUS_* incompleto (host/db/user/password)"
        return None, None, meta
    if not check_tcp(host, int(port)):
        meta["error"] = f"TCP falhou {host}:{port}"
        return None, None, meta

    attempts: list[tuple[str, str, str]] = [("native", user, password)]
    if _truthy("INDICASUS_USE_DW_CREDENTIALS", False):
        dw_user = _env("DW_USER", "DATAWAREHOUSE_USER")
        dw_pwd = _env("DW_PASSWORD", "DATAWAREHOUSE_PASSWORD")
        if dw_user and dw_pwd:
            attempts.append(("dw_creds", dw_user, dw_pwd))

    errors: list[str] = []
    for label, u, p in attempts:
        try:
            odbc = build_odbc(
                host=host,
                port=port,
                database=database,
                user=u,
                password=p,
                trust=trust,
                encrypt=encrypt,
            )
            mode, q = connect_odbc(odbc)
            meta["ok"] = True
            meta["auth"] = label
            meta["user"] = u
            return mode, q, meta
        except Exception as exc:
            errors.append(f"{label}:{type(exc).__name__}")
    meta["error"] = "; ".join(errors) or "login failed"
    return None, None, meta


def inventory_tables(mode: str, queryable: Any) -> pd.DataFrame:
    return read_sql(
        mode,
        queryable,
        """
        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """,
    )


def extract_indicasus(stage: Path) -> dict[str, Any]:
    """Extrai catálogo/indicadores leves + inventário IndicaSUS → indicasus_*."""
    out: dict[str, Any] = {
        "source": "INDICASUS",
        "ok": False,
        "objects_listed": 0,
        "files": {},
        "extracted": [],
        "failures": [],
        "connect": {},
    }
    mode, q, cmeta = connect_indicasus()
    out["connect"] = {k: v for k, v in cmeta.items() if k != "password"}
    if not mode or q is None:
        out["failures"].append(cmeta.get("error") or "connect failed")
        _log(f"[INDICASUS] falhou: {out['failures'][-1]}")
        return out

    try:
        inv = inventory_tables(mode, q)
        out["objects_listed"] = int(len(inv))
        inv.to_csv(stage / "indicasus_inventory.csv", index=False, encoding="utf-8-sig")
        out["files"]["indicasus_inventory"] = "indicasus_inventory.csv"
        _log(f"[INDICASUS] inventário: {len(inv)} objetos")

        # Catálogo de indicadores (leve)
        targets: list[tuple[str, str, str, int]] = [
            ("ind", "Indicador", "indicasus_indicador", 5_000),
            ("form", "V_MunicipioRegiao", "indicasus_municipio_regiao", 500),
            ("ind", "Tema", "indicasus_tema", 2_000),
            ("ind", "Periodicidade", "indicasus_periodicidade", 500),
            ("ind", "ImportacaoCalculado", "indicasus_importacao_calculado", 30_000),
            ("ind", "EntradaDados", "indicasus_entrada_dados", 30_000),
            ("ind", "MetaIndicadorValor", "indicasus_meta_indicador_valor", 30_000),
            ("form", "HistoricoOcupacao", "indicasus_historico_ocupacao_sample", 20_000),
        ]
        for schema, table, stem, top in targets:
            try:
                schema_s, table_s = _safe_ident(schema), _safe_ident(table)
                df = read_sql(
                    mode,
                    q,
                    f"SELECT TOP ({int(top)}) * FROM [{schema_s}].[{table_s}]",
                )
                if df is None or df.empty:
                    out["failures"].append(f"{schema}.{table}: vazio")
                    continue
                out["files"].update(_save_df(stage, stem, df))
                out["extracted"].append(
                    {"object": f"{schema}.{table}", "rows": int(len(df)), "stem": stem}
                )
                _log(f"[INDICASUS] {stem} ← {len(df)} linhas ({schema}.{table})")
            except Exception as exc:
                out["failures"].append(f"{schema}.{table}: {type(exc).__name__}")
                _log(f"[INDICASUS] skip {schema}.{table}: {type(exc).__name__}")

        # Agregado leve ocupação por tipo de leito (sample window via TOP already done;
        # if HistoricoOcupacao has DataAcompanhamento, try mun-less summary)
        try:
            df_occ = read_sql(
                mode,
                q,
                """
                SELECT TOP (50000)
                  TipoDeLeitoQueOcupa AS tipo_leito,
                  SituacaoCovid AS situacao_covid,
                  CAST(DataAcompanhamento AS date) AS data_ref,
                  COUNT_BIG(*) AS n
                FROM [form].[HistoricoOcupacao]
                WHERE DataAcompanhamento >= DATEADD(month, -6, GETDATE())
                GROUP BY TipoDeLeitoQueOcupa, SituacaoCovid, CAST(DataAcompanhamento AS date)
                ORDER BY data_ref DESC
                """,
            )
            if df_occ is not None and not df_occ.empty:
                out["files"].update(_save_df(stage, "indicasus_ocupacao_agg", df_occ))
                out["extracted"].append(
                    {
                        "object": "form.HistoricoOcupacao/agg",
                        "rows": int(len(df_occ)),
                        "stem": "indicasus_ocupacao_agg",
                    }
                )
        except Exception as exc:
            out["failures"].append(f"ocupacao_agg: {type(exc).__name__}")

        out["ok"] = True
    finally:
        close_conn(mode, q)
    return out


# ---------------------------------------------------------------------------
# SISREG
# ---------------------------------------------------------------------------


def connect_sisreg() -> tuple[Optional[str], Any, dict[str, Any]]:
    _load_env()
    host = _env("SISREG_HOST")
    port = _env("SISREG_PORT", default="1433")
    database = _env("SISREG_DATABASE", "SISREG_DB")
    # SISREG_DB may be a duckdb path — prefer SISREG_DATABASE for SQL Server
    if database and (database.lower().endswith(".duckdb") or "\\" in database or "/" in database):
        database = _env("SISREG_DATABASE") or ""
    user = _env("SISREG_USER")
    password = _env("SISREG_PASSWORD")
    trust = _env("SISREG_TRUST_CERT", default="yes")
    encrypt = _env("SISREG_ENCRYPT", default="no")
    meta: dict[str, Any] = {
        "host": host or None,
        "port": int(port) if port else None,
        "database": database or None,
        "user": user or None,
        "ok": False,
    }
    if not host or not database or not user or not password:
        meta["error"] = "SISREG_* incompleto (host/database/user/password)"
        return None, None, meta
    if not check_tcp(host, int(port)):
        meta["error"] = f"TCP falhou {host}:{port}"
        return None, None, meta
    try:
        odbc = build_odbc(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            trust=trust,
            encrypt=encrypt,
        )
        mode, q = connect_odbc(odbc)
        meta["ok"] = True
        return mode, q, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}"
        return None, None, meta


def extract_sisreg(stage: Path, *, months_back: int = 6) -> dict[str, Any]:
    """Inventário + agregados leves de fila/regulação por município."""
    out: dict[str, Any] = {
        "source": "SISREG",
        "ok": False,
        "objects_listed": 0,
        "files": {},
        "extracted": [],
        "failures": [],
        "connect": {},
    }
    mode, q, cmeta = connect_sisreg()
    out["connect"] = cmeta
    if not mode or q is None:
        out["failures"].append(cmeta.get("error") or "connect failed")
        _log(f"[SISREG] falhou: {out['failures'][-1]}")
        return out

    try:
        inv = inventory_tables(mode, q)
        out["objects_listed"] = int(len(inv))
        inv.to_csv(stage / "sisreg_inventory.csv", index=False, encoding="utf-8-sig")
        out["files"]["sisreg_inventory"] = "sisreg_inventory.csv"
        _log(f"[SISREG] inventário: {len(inv)} objetos")

        # Fila SAMU (pequena) — amostra completa leve
        try:
            df_fila = read_sql(
                mode,
                q,
                "SELECT TOP (50000) * FROM [dbo].[VW_SAMU_FILA_HOSPITALAR]",
            )
            if df_fila is not None and not df_fila.empty:
                out["files"].update(_save_df(stage, "sisreg_samu_fila", df_fila))
                out["extracted"].append(
                    {
                        "object": "dbo.VW_SAMU_FILA_HOSPITALAR",
                        "rows": int(len(df_fila)),
                        "stem": "sisreg_samu_fila",
                    }
                )
                _log(f"[SISREG] sisreg_samu_fila ← {len(df_fila)} linhas")
        except Exception as exc:
            out["failures"].append(f"VW_SAMU_FILA_HOSPITALAR: {type(exc).__name__}")

        # Agregado ambulatorial por mun × status (janela recente) — SEM dump
        months = max(1, int(months_back))
        try:
            df_amb = read_sql(
                mode,
                q,
                f"""
                SELECT TOP (80000)
                  UPPER(LTRIM(RTRIM(municipio_paciente_residencia))) AS municipio,
                  status_solicitacao,
                  nome_grupo_procedimento,
                  COUNT_BIG(*) AS n_solicitacoes
                FROM [dbo].[VW_AMBULATORIAL_SOLICITACAO]
                WHERE TRY_CONVERT(date, data_solicitacao) >= DATEADD(month, -{months}, CAST(GETDATE() AS date))
                GROUP BY
                  UPPER(LTRIM(RTRIM(municipio_paciente_residencia))),
                  status_solicitacao,
                  nome_grupo_procedimento
                ORDER BY n_solicitacoes DESC
                """,
            )
            if df_amb is not None and not df_amb.empty:
                out["files"].update(_save_df(stage, "sisreg_amb_mun_status_agg", df_amb))
                out["extracted"].append(
                    {
                        "object": "dbo.VW_AMBULATORIAL_SOLICITACAO/agg",
                        "rows": int(len(df_amb)),
                        "stem": "sisreg_amb_mun_status_agg",
                    }
                )
                _log(f"[SISREG] sisreg_amb_mun_status_agg ← {len(df_amb)} linhas")
        except Exception as exc:
            out["failures"].append(f"amb_agg: {type(exc).__name__}")
            _log(f"[SISREG] amb_agg skip: {type(exc).__name__}")

        # Hospitalar sintético — agg mun × status (janela)
        try:
            df_hosp = read_sql(
                mode,
                q,
                f"""
                SELECT TOP (80000)
                  UPPER(LTRIM(RTRIM(municipio_paciente_residencia))) AS municipio,
                  status,
                  COUNT_BIG(*) AS n_solicitacoes
                FROM [dbo].[VW_HOSPITALAR_SINTETICO]
                WHERE TRY_CONVERT(date, data_solicitacao) >= DATEADD(month, -{months}, CAST(GETDATE() AS date))
                GROUP BY
                  UPPER(LTRIM(RTRIM(municipio_paciente_residencia))),
                  status
                ORDER BY n_solicitacoes DESC
                """,
            )
            if df_hosp is not None and not df_hosp.empty:
                out["files"].update(_save_df(stage, "sisreg_hosp_mun_status_agg", df_hosp))
                out["extracted"].append(
                    {
                        "object": "dbo.VW_HOSPITALAR_SINTETICO/agg",
                        "rows": int(len(df_hosp)),
                        "stem": "sisreg_hosp_mun_status_agg",
                    }
                )
                _log(f"[SISREG] sisreg_hosp_mun_status_agg ← {len(df_hosp)} linhas")
        except Exception as exc:
            out["failures"].append(f"hosp_agg: {type(exc).__name__}")
            _log(f"[SISREG] hosp_agg skip: {type(exc).__name__}")

        # Amostra recente hospitalar (TOP N colunas-chave) — não full dump
        try:
            df_hs = read_sql(
                mode,
                q,
                f"""
                SELECT TOP (25000)
                  municipio_paciente_residencia,
                  status,
                  data_solicitacao,
                  data_internacao,
                  data_alta,
                  codigo_cid,
                  Codigo_Procedimento,
                  Descricao_procedimento,
                  nome_central_reguladora,
                  nome_unidade_executante,
                  codigo_classificacao_risco
                FROM [dbo].[VW_HOSPITALAR_SINTETICO]
                WHERE TRY_CONVERT(date, data_solicitacao) >= DATEADD(month, -{months}, CAST(GETDATE() AS date))
                ORDER BY data_solicitacao DESC
                """,
            )
            if df_hs is not None and not df_hs.empty:
                out["files"].update(_save_df(stage, "sisreg_hosp_recent", df_hs))
                out["extracted"].append(
                    {
                        "object": "dbo.VW_HOSPITALAR_SINTETICO/sample",
                        "rows": int(len(df_hs)),
                        "stem": "sisreg_hosp_recent",
                    }
                )
        except Exception as exc:
            out["failures"].append(f"hosp_recent: {type(exc).__name__}")

        out["ok"] = True
    finally:
        close_conn(mode, q)
    return out


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def run_external_extract(outdir: Path | str = "saida_pipeline") -> dict[str, Any]:
    stage = Path(outdir) / "staging_dw"
    stage.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "indicasus": {},
        "sisreg": {},
    }
    try:
        report["indicasus"] = extract_indicasus(stage)
    except Exception as exc:
        report["indicasus"] = {
            "ok": False,
            "failures": [f"fatal:{type(exc).__name__}"],
        }
        _log(f"[INDICASUS] fatal: {type(exc).__name__}")
    try:
        report["sisreg"] = extract_sisreg(stage)
    except Exception as exc:
        report["sisreg"] = {
            "ok": False,
            "failures": [f"fatal:{type(exc).__name__}"],
        }
        _log(f"[SISREG] fatal: {type(exc).__name__}")
    return report


def write_fontes_busca_report(
    stage: Path,
    *,
    dw_meta: Optional[dict[str, Any]] = None,
    external: Optional[dict[str, Any]] = None,
) -> Path:
    """Grava saida_pipeline/staging_dw/fontes_busca_ultimo.txt (sem segredos)."""
    lines: list[str] = [
        "LACEN MT — busca de fontes adicionais (IndicaSUS / SISREG / DW leftovers)",
        f"gerado_em: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    dw_meta = dw_meta or {}
    external = external or {}

    # DW
    lines.append("=== DW estadual ===")
    lines.append(
        f"tcp/connect: ok={bool(dw_meta.get('gal_view') or dw_meta.get('sources_extracted'))}"
    )
    lines.append(f"objects_inventory: {len(dw_meta.get('objects') or [])}")
    extracted = dw_meta.get("sources_extracted") or []
    lines.append(f"sources_extracted ({len(extracted)}): {', '.join(extracted[:40])}")
    if dw_meta.get("error"):
        lines.append(f"failure: {dw_meta.get('error')}")
    leftovers = dw_meta.get("dw_leftovers") or {}
    if leftovers:
        lines.append(
            f"leftovers_attempted: {leftovers.get('attempted')} | "
            f"extracted: {leftovers.get('extracted_count')} | "
            f"failures: {leftovers.get('failures')}"
        )
    lines.append("")

    for key, title in (("indicasus", "IndicaSUS"), ("sisreg", "SISREG")):
        block = external.get(key) or {}
        conn = block.get("connect") or {}
        lines.append(f"=== {title} ===")
        lines.append(
            f"connected: {block.get('ok')} | host={conn.get('host')} | "
            f"db={conn.get('database')} | user={conn.get('user')} | "
            f"auth={conn.get('auth')}"
        )
        lines.append(f"objects_listed: {block.get('objects_listed', 0)}")
        for row in block.get("extracted") or []:
            lines.append(
                f"  extracted: {row.get('object')} → {row.get('stem')} ({row.get('rows')} rows)"
            )
        for fail in block.get("failures") or []:
            lines.append(f"  failure: {fail}")
        if conn.get("error") and not block.get("ok"):
            lines.append(f"  connect_error: {conn.get('error')}")
        lines.append("")

    path = stage / "fontes_busca_ultimo.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"[OK] {path}")
    return path


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("saida_pipeline")
    rep = run_external_extract(out)
    stage = out / "staging_dw"
    write_fontes_busca_report(stage, external=rep)
    print(json.dumps({k: {"ok": v.get("ok"), "n": v.get("objects_listed"), "ext": len(v.get("extracted") or []), "fail": v.get("failures")} for k, v in (("indicasus", rep.get("indicasus") or {}), ("sisreg", rep.get("sisreg") or {}))}, indent=2, ensure_ascii=False))
