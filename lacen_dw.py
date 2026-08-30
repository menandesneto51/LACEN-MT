# -*- coding: utf-8 -*-
"""
Conexão DW (SQL Server SES-MT) para o LACEN.

Credenciais via ambiente — NÃO hardcode.
Carrega .env local e, se ausente, o .env do SISREG (mesmo DW institucional).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

import pandas as pd

BASE = Path(__file__).resolve().parent
DESKTOP = BASE.parent
SISREG_ENV = DESKTOP / "SISREG" / ".env"
# Fallbacks só se LACEN/.env faltar chaves (override=False)
_SIBLING_ENV_CANDIDATES = (
    SISREG_ENV,
    DESKTOP / "AESOP COMPLETO" / "aesop_titan_complete_system" / ".env",
    DESKTOP / "TITAN_V40_DEV" / ".env",
    DESKTOP / "Sentinela" / ".env",
    DESKTOP.parent / "CIEVS MT" / "SIS-Monitoramento-Clima-Saude-GITHUB-LIMPO" / ".env",
    DESKTOP.parent / "CIEVS MT" / "Monitoramento ondas de calor" / ".env",
)


def _load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # LACEN primeiro; irmãos só preenchem chaves ausentes
    if (BASE / ".env").exists():
        load_dotenv(BASE / ".env", override=False)
    for p in _SIBLING_ENV_CANDIDATES:
        if p.exists():
            load_dotenv(p, override=False)


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
    return default


def build_odbc_conn_str() -> str:
    _load_dotenv_files()
    driver = env_first("SQLSERVER_DRIVER", "ODBC_DRIVER", default="ODBC Driver 18 for SQL Server")
    host = env_first("DATAWAREHOUSE_HOST", "DATAWAREHOUSE_SERVER", "DW_HOST", "DW_SERVER")
    port = env_first("DATAWAREHOUSE_PORT", "DW_PORT", default="1433")
    database = env_first("DATAWAREHOUSE_DATABASE", "DW_DATABASE", "DATAWAREHOUSE_DB", "DW_DB")
    user = env_first("DATAWAREHOUSE_USER", "DW_USER", "DATAWAREHOUSE_USERNAME", "DW_USERNAME")
    password = env_first("DATAWAREHOUSE_PASSWORD", "DW_PASSWORD")
    trust = env_first("DATAWAREHOUSE_TRUST_CERT", "DW_TRUST_CERT", default="yes")
    encrypt = env_first("DATAWAREHOUSE_ENCRYPT", "DW_ENCRYPT", default="no")

    missing = [n for n, v in [
        ("DW_HOST", host), ("DW_DATABASE", database), ("DW_USER", user), ("DW_PASSWORD", password)
    ] if not v]
    if missing:
        raise ValueError(
            "Variáveis ausentes para DW: " + ", ".join(missing)
            + f". Crie LACEN/.env ou mantenha SISREG/.env em {SISREG_ENV}"
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


def connect_dw():
    odbc = build_odbc_conn_str()
    try:
        from sqlalchemy import create_engine
        url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc)
        engine = create_engine(url, pool_pre_ping=True, future=True)
        return "sqlalchemy", engine
    except Exception:
        import pyodbc
        return "pyodbc", pyodbc.connect(odbc)


def read_sql(mode: str, queryable: Any, sql: str, params=None) -> pd.DataFrame:
    if mode == "sqlalchemy":
        from sqlalchemy import text
        return pd.read_sql_query(text(sql), queryable, params=params)
    return pd.read_sql_query(sql, queryable, params=params)


def inventariar_fontes_lacen(mode: str, queryable: Any) -> pd.DataFrame:
    """Inventário INFORMATION_SCHEMA: GAL, SINAN, SIM, CNES, SIH/internação, SIA, IndicaSUS, SISREG, pop."""
    sql = """
    SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
    FROM INFORMATION_SCHEMA.TABLES
    WHERE (
           TABLE_NAME LIKE '%SINAN%'
        OR TABLE_NAME LIKE '%SIM%'
        OR TABLE_NAME LIKE '%SINASC%'
        OR TABLE_NAME LIKE '%CNES%'
        OR TABLE_NAME LIKE '%GAL%'
        OR TABLE_NAME LIKE '%LACEN%'
        OR TABLE_NAME LIKE '%LABORAT%'
        OR TABLE_NAME LIKE '%POPULAC%'
        OR TABLE_NAME LIKE '%MUNICIP%'
        OR TABLE_NAME LIKE '%INDICA%'
        OR TABLE_NAME LIKE '%SISREG%'
        OR TABLE_NAME LIKE '%REGULA%'
        OR TABLE_NAME LIKE '%OCUPA%'
        OR TABLE_NAME LIKE '%SIVEP%'
        OR TABLE_NAME LIKE '%CLIMA%'
        OR TABLE_NAME LIKE '%SIH%'
        OR TABLE_NAME LIKE '%SIA%'
        OR TABLE_NAME LIKE '%AIH%'
        OR TABLE_NAME LIKE '%INTERN%'
        OR TABLE_NAME LIKE '%PACTU%'
    )
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    return read_sql(mode, queryable, sql)


def contar_linhas(mode: str, queryable: Any, schema: str, table: str) -> int:
    sql = f"SELECT COUNT_BIG(*) AS n FROM [{schema}].[{table}]"
    df = read_sql(mode, queryable, sql)
    return int(df.iloc[0]["n"])
