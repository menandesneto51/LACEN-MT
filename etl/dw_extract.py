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
    "Data_Solicitacao_dt",
    "Data_Solicitacao",
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
        from lacen_dw import _load_dotenv_files
        _load_dotenv_files()
    except Exception:
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
    except OSError:
        return False, host, port


# Objetos opcionais a extrair (TOP N) quando presentes no inventário
OPTIONAL_EXTRACT_CANDIDATES: tuple[str, ...] = (
    "VW_SINAN",
    "VW_SINAN_DENGUE",
    "VW_SINAN_TUBERCULOSE",
    "VW_SINAN_HEPATITE",
    "VW_SINAN_MENINGITE",
    "VW_SINAN_SINDROMERESPIRATORIAAGUDAGRAVE",
    "VW_SINAN_CHIKUNGUNYA",
    "VW_SINAN_NOTIFICACAOINDIVIDUAL",
    "VW_SIM",
    "SIM",
    "VW_LACEN",
    "VW_CNES",
    "CNES_ESTABELECIMENTOS",
    "CNES_LEITOS",
    "VW_INDICASUS",
    "INDICADORES",
    "INDICADORESPACTUACAO",
    "INDICADORESVIGILANCIASAUDE",
    "VW_SISREG",
    "VW_SIH",
    "VW_SIA",
    "VW_AIH",
    "VW_INTERNACAO",  # proxy SIH no DW SES-MT (sem view *SIH*)
    "SIH",
    "SIA",
    "SIA_APAC",
    "VW_SINASC",
    "SIVEP_MALARIA",
    "VW_POPULACAO",
    "POPULACAO",
    "POPULACAO_TOTAL",
    "VW_MUNICIPIO",
)

# SINAN prioritários (qualquer agravo) — extrair vários, não só o 1º alfabético
SINAN_PRIORITY_VIEWS: tuple[str, ...] = (
    "VW_SINAN_DENGUE",
    "VW_SINAN_TUBERCULOSE",
    "VW_SINAN_HEPATITE",
    "VW_SINAN_MENINGITE",
    "VW_SINAN_SINDROMERESPIRATORIAAGUDAGRAVE",
    "VW_SINAN_CHIKUNGUNYA",
    "VW_SINAN_NOTIFICACAOINDIVIDUAL",
    "VW_SINAN_LEISHMANIOSEVISCERAL",
    "VW_SINAN_HANSENIASE",
    "VW_SINAN_HANTAVIROSE",
    # leftovers nice-to-have (TOP N)
    "VW_SINAN_LEISHMANIOSETEGUMENTAR",
    "VW_SINAN_SIFILISGESTANTE",
    "VW_SINAN_SIFILISCONGENITA",
    "VW_SINAN_AIDSADULTO",
    "VW_SINAN_AIDSCRIANCA",
    "VW_SINAN_ESQUISTOSSOMOSE",
    "VW_SINAN_FEBREMACULOSA",
    "VW_SINAN_INTOXICACAOEXOGENA",
    "VW_SINAN_ANIMAISPECONHENTOS",
    "VW_SINAN_ACIDENTETRABALHOGRAVE",
    "VW_SINAN_ACIDENTETRABALHOEXPOSICAOMATERIALBIOLOGICO",
    "VW_SINAN_DOENCARELACIONADATRABALHOLERDORT",
    "VW_SINAN_VIOLENCIADOMESTICASEXUALEOUOUTRAS",
)

# Leftovers explícitos pós-SIH/SIA (amostra TOP N)
DW_LEFTOVER_MUST: tuple[str, ...] = (
    "VW_SINASC",
    "SIVEP_MALARIA",
)


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


def discover_table_columns(
    mode: str,
    queryable: Any,
    schema: str = "dbo",
    table: str = "VW_GAL",
) -> list[str]:
    from lacen_dw import read_sql

    schema, table = _safe_ident(schema), _safe_ident(table)
    df = read_sql(
        mode,
        queryable,
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'
        ORDER BY ORDINAL_POSITION
        """,
    )
    return [str(x) for x in df["COLUMN_NAME"].tolist()]


def discover_gal_columns(
    mode: str, queryable: Any, schema: str = "dbo", view: str = "VW_GAL"
) -> list[str]:
    return discover_table_columns(mode, queryable, schema=schema, table=view)


# Famílias CID10 correlatas aos agravos prioritários LACEN/CIEVS
CID_FAMILIA_SQL_CASES: tuple[tuple[str, str], ...] = (
    (
        "hepatite",
        "({cid} LIKE 'B15%' OR {cid} LIKE 'B16%' OR {cid} LIKE 'B17%' "
        "OR {cid} LIKE 'B18%' OR {cid} LIKE 'B19%')",
    ),
    (
        "tuberculose",
        "({cid} LIKE 'A15%' OR {cid} LIKE 'A16%' OR {cid} LIKE 'A17%' "
        "OR {cid} LIKE 'A18%' OR {cid} LIKE 'A19%')",
    ),
    (
        "dengue_arbovirose",
        "({cid} LIKE 'A90%' OR {cid} LIKE 'A91%' OR {cid} LIKE 'A92%' "
        "OR {cid} LIKE 'A95%')",
    ),
)

CID_FAMILIA_PREFIXES: dict[str, tuple[str, ...]] = {
    "hepatite": ("B15", "B16", "B17", "B18", "B19"),
    "tuberculose": ("A15", "A16", "A17", "A18", "A19"),
    "dengue_arbovirose": ("A90", "A91", "A92", "A95"),
}

# Colunas preferidas no sample recente (quando existirem)
INTERNACAO_SAMPLE_COLS: tuple[str, ...] = (
    "AnoInternacao",
    "MesInternacao",
    "DiaInternacao",
    "AnoCompetencia",
    "MesCompetencia",
    "MunicipioResidencia",
    "CodigoMunicipioResidencia",
    "MunicipioOcorrencia",
    "CodigoMunicipioOcorrencia",
    "DiagnosticoPrincipal",
    "CodigoDiagnosticoPrincipal",
    "DiagnosticoPrincipalCid10Capitulo",
    "DiagnosticoSecundario",
    "HospitalNome",
    "CaraterInternacao",
    "NumeroAIH",
    "FoiAObito",
    "PermanenciaDias",
    "TeveDiariasUTI",
    "NumeroInternacoes",
)

SIA_SAMPLE_COLS: tuple[str, ...] = (
    "AnoAtendimento",
    "MesAtendimento",
    "AnoApresentacao",
    "MesApresentacao",
    "MunicipioResidencia",
    "CodigoMunicipioResidencia",
    "MunicipioAtendimento",
    "CidPrincipal",
    "CodigoCidPrincipal",
    "CidPrincipalCid10Capitulo",
    "ProcedimentoNome",
    "ProcedimentoCodigo",
    "QuantidadeAprovada",
    "ValorAprovado",
)

SIA_APAC_SAMPLE_COLS: tuple[str, ...] = (
    "AnoCompetencia",
    "MesCompetencia",
    "AnoInicioApac",
    "MesInicioApac",
    "DiaInicioApac",
    "MunicipioResidencia",
    "CodigoMunicipioResidencia",
    "CausaBasica",
    "CausaCid10Capitulo",
    "ProcedimentoNome",
    "ProcedimentoCodigo",
    "QuantidadeAprovada",
    "ValorAprovado",
    "TipoApac",
)


def _cid_familia_case_sql(cid_expr: str) -> str:
    parts = [
        f"WHEN {cond.format(cid=cid_expr)} THEN N'{fam}'"
        for fam, cond in CID_FAMILIA_SQL_CASES
    ]
    return "CASE " + " ".join(parts) + " ELSE NULL END"


def _normalize_cid_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
        .str.strip()
    )


def cid_to_familia(cid: Any) -> str | None:
    code = str(cid or "").upper().replace(".", "").replace(" ", "")
    if len(code) < 3:
        return None
    head = code[:3]
    for fam, prefixes in CID_FAMILIA_PREFIXES.items():
        if any(code.startswith(p) or head == p for p in prefixes):
            return fam
    return None


def check_sisreg_tcp(timeout: float = 2.0) -> dict[str, Any]:
    """Ping opcional do host SISREG (fora do DW). Nunca bloqueia o ETL."""
    import os
    import socket

    try:
        from lacen_dw import _load_dotenv_files

        _load_dotenv_files()
    except Exception:
        pass

    host = (os.getenv("SISREG_HOST") or "").strip()
    if not host:
        return {
            "ok": None,
            "host": None,
            "port": None,
            "note": "SISREG_HOST ausente — regulação fora do DW (não bloqueia)",
        }
    port = int(os.getenv("SISREG_PORT") or "1433")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "ok": True,
                "host": host,
                "port": port,
                "note": "SISREG TCP OK (host separado; sem view no DW)",
            }
    except OSError as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "note": f"SISREG TCP falhou (não bloqueia ETL): {type(exc).__name__}",
        }


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

    from etl.epi_week import gal_se_date_is_solicitacao, pick_gal_se_date_col

    schema, view = _safe_ident(schema), _safe_ident(view)
    cols = set(discover_gal_columns(mode, queryable, schema, view))
    # SE = data da solicitação (não liberação). Janela do agg usa a mesma âncora.
    date_col = pick_gal_se_date_col(cols)
    if not date_col:
        raise RuntimeError(
            f"{schema}.{view} sem coluna de data para SE "
            "(esperado Data_Solicitacao* / fallback coleta ou liberação)."
        )
    if not gal_se_date_is_solicitacao(date_col):
        _log(
            f"[DW][AVISO] SE sem Data_Solicitacao na view — usando fallback {date_col}"
        )
    else:
        _log(f"[DW] SE ancorada em {date_col} (solicitação)")

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

    # isoyear exige SQL Server 2022+; fórmula YEAR(DATEADD(day, 26-iso_week, d))
    # é compatível com versões anteriores e alinha ao isocalendar() Python.
    d = f"CAST([{date_col}] AS date)"
    epi_year_expr = f"YEAR(DATEADD(day, 26 - DATEPART(iso_week, {d}), {d}))"
    epi_week_expr = f"DATEPART(iso_week, {d})"

    sql = f"""
    SELECT
      {epi_year_expr} AS epi_year,
      {epi_week_expr} AS epi_week,
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
      {epi_year_expr},
      {epi_week_expr},
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
    from etl.epi_week import pick_gal_se_date_col

    want = [c for c in GAL_SELECT_COLS if c in cols]
    if "Data_Liberacao_dt" not in want and "Data_Liberacao" in cols:
        want.append("Data_Liberacao")
    se_col = pick_gal_se_date_col(cols)
    if se_col and se_col not in want:
        want.append(se_col)
    if not want:
        raise RuntimeError("Nenhuma coluna GAL conhecida na view.")
    # Janela do micro = liberação (TAT/rede/frescor). SE usa solicitação à parte.
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


def _year_int_sql(col: str) -> str:
    return f"TRY_CONVERT(int, [{col}])"


def _month_int_sql(col: str) -> str:
    """Mes no DW SES costuma ser '02.Fev' / '12.Dez' — pega os 2 dígitos iniciais."""
    return (
        f"COALESCE("
        f"TRY_CONVERT(int, [{col}]), "
        f"TRY_CONVERT(int, LEFT(LTRIM(RTRIM(CAST([{col}] AS NVARCHAR(20)))), 2))"
        f")"
    )


def _day_int_sql(col: str) -> str:
    return (
        f"COALESCE("
        f"TRY_CONVERT(int, [{col}]), "
        f"TRY_CONVERT(int, LEFT(LTRIM(RTRIM(CAST([{col}] AS NVARCHAR(20)))), 2)), "
        f"1)"
    )


def _sih_date_expr(cols: set[str]) -> Optional[str]:
    """Expressão date a partir de Ano/Mes/DiaInternacao ou competência (mês PT-BR)."""
    if {"AnoInternacao", "MesInternacao", "DiaInternacao"} <= cols:
        y, m, d = (
            _year_int_sql("AnoInternacao"),
            _month_int_sql("MesInternacao"),
            _day_int_sql("DiaInternacao"),
        )
        inter = (
            f"CASE WHEN {y} IS NOT NULL AND {m} BETWEEN 1 AND 12 "
            f"THEN TRY_CONVERT(date, DATEFROMPARTS({y}, {m}, "
            f"CASE WHEN {d} BETWEEN 1 AND 31 THEN {d} ELSE 1 END)) "
            f"ELSE NULL END"
        )
        if {"AnoCompetencia", "MesCompetencia"} <= cols:
            yc, mc = _year_int_sql("AnoCompetencia"), _month_int_sql("MesCompetencia")
            return (
                f"COALESCE({inter}, "
                f"CASE WHEN {yc} IS NOT NULL AND {mc} BETWEEN 1 AND 12 "
                f"THEN TRY_CONVERT(date, DATEFROMPARTS({yc}, {mc}, 1)) ELSE NULL END)"
            )
        return inter
    if {"AnoCompetencia", "MesCompetencia"} <= cols:
        yc, mc = _year_int_sql("AnoCompetencia"), _month_int_sql("MesCompetencia")
        return (
            f"CASE WHEN {yc} IS NOT NULL AND {mc} BETWEEN 1 AND 12 "
            f"THEN TRY_CONVERT(date, DATEFROMPARTS({yc}, {mc}, 1)) ELSE NULL END"
        )
    return None


def _sia_date_expr(cols: set[str]) -> Optional[str]:
    pairs = (
        ("AnoAtendimento", "MesAtendimento"),
        ("AnoApresentacao", "MesApresentacao"),
        ("AnoCompetencia", "MesCompetencia"),
    )
    for ycol, mcol in pairs:
        if ycol in cols and mcol in cols:
            y, m = _year_int_sql(ycol), _month_int_sql(mcol)
            return (
                f"CASE WHEN {y} IS NOT NULL AND {m} BETWEEN 1 AND 12 "
                f"THEN TRY_CONVERT(date, DATEFROMPARTS({y}, {m}, 1)) ELSE NULL END"
            )
    return None


def _parse_month_pt(val: Any) -> Optional[int]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        n = int(val)
        if 1 <= n <= 12:
            return n
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if len(s) >= 2 and s[:2].isdigit():
        n = int(s[:2])
        if 1 <= n <= 12:
            return n
    return None


def _parse_year(val: Any) -> Optional[int]:
    try:
        n = int(float(str(val).strip()[:4]))
        return n if n >= 2000 else None
    except (TypeError, ValueError):
        return None


def _pick_cols(available: set[str], preferred: tuple[str, ...]) -> list[str]:
    return [c for c in preferred if c in available]


def extract_vw_internacao_recent(
    mode: str,
    queryable: Any,
    *,
    schema: str = "dbo",
    view: str | None = None,
    days_back: int = 180,
    top: int = 80_000,
) -> tuple[Optional[pd.DataFrame], list[str]]:
    """Amostra recente de VW_INTERNACAO (proxy SIH) → staging."""
    import os

    from lacen_dw import read_sql

    schema = _safe_ident(schema or os.getenv("SIH_DW_SCHEMA") or "dbo")
    view = _safe_ident(
        view or os.getenv("SIH_DW_TABLE") or "VW_INTERNACAO"
    )
    cols = set(discover_table_columns(mode, queryable, schema, view))
    if not cols:
        _log(f"[DW] {schema}.{view} sem colunas")
        return None, []
    want = _pick_cols(cols, INTERNACAO_SAMPLE_COLS) or sorted(cols)[:40]
    date_expr = _sih_date_expr(cols)
    col_list = ", ".join(f"[{c}]" for c in want)
    if date_expr:
        sql = f"""
        SELECT TOP ({int(top)}) {col_list}
        FROM [{schema}].[{view}]
        WHERE {date_expr} IS NOT NULL
          AND {date_expr} >= DATEADD(day, -{int(days_back)}, CAST(GETDATE() AS date))
          AND {date_expr} <= CAST(GETDATE() AS date)
        ORDER BY {date_expr} DESC
        """
    else:
        sql = f"SELECT TOP ({int(top)}) {col_list} FROM [{schema}].[{view}]"
    _log(f"[DW] Micro {schema}.{view} TOP {top} / ~{days_back}d…")
    try:
        return read_sql(mode, queryable, sql), sorted(cols)
    except Exception as exc:
        _log(f"[DW] Extrato {view} falhou: {type(exc).__name__}: {exc}")
        return None, sorted(cols)


def extract_sia_recent(
    mode: str,
    queryable: Any,
    table_name: str,
    *,
    schema: str = "dbo",
    days_back: int = 180,
    top: int = 60_000,
    preferred_cols: tuple[str, ...] = SIA_SAMPLE_COLS,
) -> tuple[Optional[pd.DataFrame], list[str]]:
    """Amostra recente SIA / SIA_APAC com filtro de competência/atendimento."""
    from lacen_dw import read_sql

    schema, table_name = _safe_ident(schema), _safe_ident(table_name)
    cols = set(discover_table_columns(mode, queryable, schema, table_name))
    if not cols:
        return None, []
    want = _pick_cols(cols, preferred_cols) or sorted(cols)[:40]
    date_expr = _sia_date_expr(cols)
    col_list = ", ".join(f"[{c}]" for c in want)
    if date_expr:
        sql = f"""
        SELECT TOP ({int(top)}) {col_list}
        FROM [{schema}].[{table_name}]
        WHERE {date_expr} IS NOT NULL
          AND {date_expr} >= DATEADD(day, -{int(days_back)}, CAST(GETDATE() AS date))
          AND {date_expr} <= CAST(GETDATE() AS date)
        ORDER BY {date_expr} DESC
        """
    else:
        sql = f"SELECT TOP ({int(top)}) {col_list} FROM [{schema}].[{table_name}]"
    _log(f"[DW] Micro {schema}.{table_name} TOP {top} / ~{days_back}d…")
    try:
        return read_sql(mode, queryable, sql), sorted(cols)
    except Exception as exc:
        _log(f"[DW] Extrato {table_name} falhou: {type(exc).__name__}: {exc}")
        return None, sorted(cols)


def extract_sih_mun_cid_agg(
    mode: str,
    queryable: Any,
    *,
    schema: str = "dbo",
    view: str | None = None,
    days_back: int = 180,
) -> Optional[pd.DataFrame]:
    """Agrega mun × SE × família CID (hepatite/TB/arbov) no próprio DW."""
    import os

    from lacen_dw import read_sql

    schema = _safe_ident(schema or os.getenv("SIH_DW_SCHEMA") or "dbo")
    view = _safe_ident(view or os.getenv("SIH_DW_TABLE") or "VW_INTERNACAO")
    cols = set(discover_table_columns(mode, queryable, schema, view))
    date_expr = _sih_date_expr(cols)
    mun_col = next(
        (
            c
            for c in (
                "MunicipioResidencia",
                "MunicipioOcorrencia",
                "CodigoMunicipioResidencia",
            )
            if c in cols
        ),
        None,
    )
    cid_col = next(
        (
            c
            for c in (
                "CodigoDiagnosticoPrincipal",
                "DiagnosticoPrincipal",
                "CodigoDiagnosticoPrincipalCid10Capitulo",
            )
            if c in cols
        ),
        None,
    )
    if not date_expr or not mun_col or not cid_col:
        _log("[DW] Agg SIH: faltam data/mun/CID — skip SQL agg")
        return None

    cid_norm = (
        f"UPPER(REPLACE(REPLACE(LTRIM(RTRIM(CAST([{cid_col}] AS NVARCHAR(20)))), '.', ''), ' ', ''))"
    )
    fam_expr = _cid_familia_case_sql(cid_norm)
    d = f"({date_expr})"
    epi_year = f"YEAR(DATEADD(day, 26 - DATEPART(iso_week, {d}), {d}))"
    epi_week = f"DATEPART(iso_week, {d})"
    sql = f"""
    SELECT
      {epi_year} AS epi_year,
      {epi_week} AS epi_week,
      UPPER(LTRIM(RTRIM(CAST([{mun_col}] AS NVARCHAR(200))))) AS municipio,
      {fam_expr} AS cid_familia,
      COUNT_BIG(*) AS n_internacoes,
      MIN({d}) AS dt_min,
      MAX({d}) AS dt_max
    FROM [{schema}].[{view}]
    WHERE {d} IS NOT NULL
      AND {d} >= DATEADD(day, -{int(days_back)}, CAST(GETDATE() AS date))
      AND {d} <= CAST(GETDATE() AS date)
      AND {fam_expr} IS NOT NULL
      AND LTRIM(RTRIM(CAST([{mun_col}] AS NVARCHAR(200)))) <> ''
    GROUP BY
      {epi_year},
      {epi_week},
      UPPER(LTRIM(RTRIM(CAST([{mun_col}] AS NVARCHAR(200))))),
      {fam_expr}
    """
    _log(f"[DW] Agg SIH mun×SE×CID família (~{days_back}d)…")
    try:
        return read_sql(mode, queryable, sql)
    except Exception as exc:
        _log(f"[DW] Agg SIH falhou: {type(exc).__name__}: {exc}")
        return None


def extract_sia_mun_cid_agg(
    mode: str,
    queryable: Any,
    table_name: str = "SIA",
    *,
    schema: str = "dbo",
    days_back: int = 180,
) -> Optional[pd.DataFrame]:
    """Agrega SIA mun × competência-mês × família CID (leve)."""
    from lacen_dw import read_sql

    schema, table_name = _safe_ident(schema), _safe_ident(table_name)
    cols = set(discover_table_columns(mode, queryable, schema, table_name))
    date_expr = _sia_date_expr(cols)
    mun_col = next(
        (
            c
            for c in (
                "MunicipioResidencia",
                "MunicipioAtendimento",
                "CodigoMunicipioResidencia",
            )
            if c in cols
        ),
        None,
    )
    cid_col = next(
        (
            c
            for c in (
                "CodigoCidPrincipal",
                "CidPrincipal",
                "CausaBasica",
                "CodigoCidPrincipalCid10Capitulo",
            )
            if c in cols
        ),
        None,
    )
    if not date_expr or not mun_col or not cid_col:
        _log(f"[DW] Agg {table_name}: faltam data/mun/CID — skip")
        return None

    cid_norm = (
        f"UPPER(REPLACE(REPLACE(LTRIM(RTRIM(CAST([{cid_col}] AS NVARCHAR(20)))), '.', ''), ' ', ''))"
    )
    fam_expr = _cid_familia_case_sql(cid_norm)
    d = f"({date_expr})"
    qty = (
        "SUM(ISNULL([QuantidadeAprovada], 1))"
        if "QuantidadeAprovada" in cols
        else "COUNT_BIG(*)"
    )
    sql = f"""
    SELECT
      YEAR({d}) AS ano,
      MONTH({d}) AS mes,
      UPPER(LTRIM(RTRIM(CAST([{mun_col}] AS NVARCHAR(200))))) AS municipio,
      {fam_expr} AS cid_familia,
      COUNT_BIG(*) AS n_registros,
      {qty} AS n_procedimentos
    FROM [{schema}].[{table_name}]
    WHERE {d} IS NOT NULL
      AND {d} >= DATEADD(day, -{int(days_back)}, CAST(GETDATE() AS date))
      AND {d} <= CAST(GETDATE() AS date)
      AND {fam_expr} IS NOT NULL
      AND LTRIM(RTRIM(CAST([{mun_col}] AS NVARCHAR(200)))) <> ''
    GROUP BY
      YEAR({d}),
      MONTH({d}),
      UPPER(LTRIM(RTRIM(CAST([{mun_col}] AS NVARCHAR(200))))),
      {fam_expr}
    """
    _log(f"[DW] Agg {table_name} mun×mês×CID família (~{days_back}d)…")
    try:
        return read_sql(mode, queryable, sql)
    except Exception as exc:
        _log(f"[DW] Agg {table_name} falhou: {type(exc).__name__}: {exc}")
        return None


def aggregate_internacao_from_sample(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback local: mun × semana × família CID a partir do sample."""
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    mun_col = next(
        (
            c
            for c in (
                "MunicipioResidencia",
                "MunicipioOcorrencia",
                "CodigoMunicipioResidencia",
            )
            if c in work.columns
        ),
        None,
    )
    cid_col = next(
        (
            c
            for c in ("CodigoDiagnosticoPrincipal", "DiagnosticoPrincipal")
            if c in work.columns
        ),
        None,
    )
    if not mun_col or not cid_col:
        return pd.DataFrame()

    def _row_date(r: pd.Series) -> Optional[date]:
        y = _parse_year(r.get("AnoInternacao") or r.get("AnoCompetencia"))
        m = _parse_month_pt(r.get("MesInternacao") or r.get("MesCompetencia"))
        d = _parse_month_pt(r.get("DiaInternacao")) or 1
        if not y or not m:
            return None
        try:
            d = min(max(int(d), 1), 28)
            return date(y, m, d)
        except (TypeError, ValueError):
            return None

    work["_dt"] = work.apply(_row_date, axis=1)
    work = work.dropna(subset=["_dt"])
    if work.empty:
        return pd.DataFrame()
    iso = work["_dt"].apply(lambda d: d.isocalendar())
    work["epi_year"] = [x[0] for x in iso]
    work["epi_week"] = [x[1] for x in iso]
    work["municipio"] = work[mun_col].astype(str).str.upper().str.strip()
    work["cid_familia"] = work[cid_col].map(cid_to_familia)
    work = work.dropna(subset=["cid_familia"])
    if work.empty:
        return pd.DataFrame()
    g = (
        work.groupby(["epi_year", "epi_week", "municipio", "cid_familia"], as_index=False)
        .size()
        .rename(columns={"size": "n_internacoes"})
    )
    return g


def build_cruzamento_sih_resumo(
    sih_agg: Optional[pd.DataFrame],
    sia_agg: Optional[pd.DataFrame],
    *,
    top_n: int = 12,
) -> dict[str, Any]:
    """Resumo leve para briefing/VE/CIEVS (top mun por família)."""
    caveat = (
        "Cruzamento SIH/SIA é correlato por CID×município (proxy VW_INTERNACAO / SIA); "
        "não atribui causalidade nem confirma surto. SISREG permanece em host separado."
    )
    top_mun: list[dict[str, Any]] = []
    if sih_agg is not None and not sih_agg.empty:
        g = sih_agg.copy()
        g["n"] = pd.to_numeric(g.get("n_internacoes"), errors="coerce").fillna(0)
        by = (
            g.groupby(["municipio", "cid_familia"], as_index=False)["n"]
            .sum()
            .sort_values("n", ascending=False)
        )
        for _, r in by.head(top_n).iterrows():
            top_mun.append(
                {
                    "fonte": "SIH/VW_INTERNACAO",
                    "municipio": str(r["municipio"]),
                    "cid_familia": str(r["cid_familia"]),
                    "n": int(r["n"]),
                }
            )
    if sia_agg is not None and not sia_agg.empty and len(top_mun) < top_n:
        g = sia_agg.copy()
        ncol = "n_procedimentos" if "n_procedimentos" in g.columns else "n_registros"
        g["n"] = pd.to_numeric(g.get(ncol), errors="coerce").fillna(0)
        by = (
            g.groupby(["municipio", "cid_familia"], as_index=False)["n"]
            .sum()
            .sort_values("n", ascending=False)
        )
        for _, r in by.head(max(0, top_n - len(top_mun))).iterrows():
            top_mun.append(
                {
                    "fonte": "SIA",
                    "municipio": str(r["municipio"]),
                    "cid_familia": str(r["cid_familia"]),
                    "n": int(r["n"]),
                }
            )
    return {
        "caveat": caveat,
        "top_mun": top_mun,
        "sih_rows": int(len(sih_agg)) if sih_agg is not None else 0,
        "sia_rows": int(len(sia_agg)) if sia_agg is not None else 0,
        "familias": sorted(
            {
                str(x.get("cid_familia"))
                for x in top_mun
                if x.get("cid_familia")
            }
        ),
    }


def _save_df(stage: Path, stem: str, df: pd.DataFrame) -> dict[str, str]:
    files: dict[str, str] = {}
    pq = stage / f"{stem}.parquet"
    csv = stage / f"{stem}.csv"
    df.to_parquet(pq, index=False)
    df.to_csv(csv, index=False, encoding="utf-8-sig")
    files[stem] = pq.name
    files[f"{stem}_csv"] = csv.name
    return files


def extract_sih_sia_bundle(
    mode: str,
    queryable: Any,
    stage: Path,
    *,
    days_back: int = 180,
    names: set[str] | None = None,
) -> dict[str, Any]:
    """
    Extrai VW_INTERNACAO / SIA / SIA_APAC / INDICADORES* (amostra + aggs leves).
    Grava `vw_internacao_recent.*`, `sia_recent.*`, aggs e resumo de cruzamento.
    """
    import os

    names = {n.upper() for n in (names or set())}
    meta: dict[str, Any] = {
        "files": {},
        "columns": {},
        "sources": [],
        "aggregates": {},
    }
    schema_sih = (os.getenv("SIH_DW_SCHEMA") or "dbo").strip() or "dbo"
    view_sih = (os.getenv("SIH_DW_TABLE") or "VW_INTERNACAO").strip() or "VW_INTERNACAO"

    # --- SIH proxy ---
    if (not names) or view_sih.upper() in names or "VW_INTERNACAO" in names:
        df_i, cols_i = extract_vw_internacao_recent(
            mode, queryable, schema=schema_sih, view=view_sih, days_back=days_back
        )
        meta["columns"]["VW_INTERNACAO"] = cols_i
        if df_i is not None and not df_i.empty:
            meta["files"].update(_save_df(stage, "vw_internacao_recent", df_i))
            meta["sources"].append(f"{schema_sih}.{view_sih}")
            _log(f"[DW] vw_internacao_recent ← {len(df_i)} linhas")

        agg_sih = extract_sih_mun_cid_agg(
            mode, queryable, schema=schema_sih, view=view_sih, days_back=days_back
        )
        if (agg_sih is None or agg_sih.empty) and df_i is not None:
            agg_sih = aggregate_internacao_from_sample(df_i)
        if agg_sih is not None and not agg_sih.empty:
            meta["files"].update(_save_df(stage, "sih_mun_cid_familia_agg", agg_sih))
            # mun × week (soma famílias)
            if {"epi_year", "epi_week", "municipio"} <= set(agg_sih.columns):
                mun_week = (
                    agg_sih.groupby(["epi_year", "epi_week", "municipio"], as_index=False)[
                        "n_internacoes"
                    ].sum()
                    if "n_internacoes" in agg_sih.columns
                    else agg_sih
                )
                meta["files"].update(_save_df(stage, "sih_mun_semana_agg", mun_week))
            meta["aggregates"]["sih_mun_cid"] = int(len(agg_sih))
        else:
            agg_sih = None
    else:
        agg_sih = None

    # --- SIA ---
    agg_sia = None
    if (not names) or "SIA" in names:
        df_s, cols_s = extract_sia_recent(
            mode,
            queryable,
            "SIA",
            days_back=days_back,
            preferred_cols=SIA_SAMPLE_COLS,
        )
        meta["columns"]["SIA"] = cols_s
        if df_s is not None and not df_s.empty:
            meta["files"].update(_save_df(stage, "sia_recent", df_s))
            meta["sources"].append("dbo.SIA")
            _log(f"[DW] sia_recent ← {len(df_s)} linhas")
        agg_sia = extract_sia_mun_cid_agg(
            mode, queryable, "SIA", days_back=days_back
        )
        if agg_sia is not None and not agg_sia.empty:
            meta["files"].update(_save_df(stage, "sia_mun_cid_familia_agg", agg_sia))
            meta["aggregates"]["sia_mun_cid"] = int(len(agg_sia))

    # --- SIA_APAC (sample only; APAC CID menos útil para agravos agudos) ---
    if (not names) or "SIA_APAC" in names:
        df_a, cols_a = extract_sia_recent(
            mode,
            queryable,
            "SIA_APAC",
            days_back=days_back,
            top=30_000,
            preferred_cols=SIA_APAC_SAMPLE_COLS,
        )
        meta["columns"]["SIA_APAC"] = cols_a
        if df_a is not None and not df_a.empty:
            meta["files"].update(_save_df(stage, "sia_apac_recent", df_a))
            meta["sources"].append("dbo.SIA_APAC")
            _log(f"[DW] sia_apac_recent ← {len(df_a)} linhas")

    # --- INDICADORES* ---
    for ind in ("INDICADORES", "INDICADORESPACTUACAO", "INDICADORESVIGILANCIASAUDE"):
        if names and ind not in names:
            continue
        top = 20_000 if ind == "INDICADORES" else 50_000
        df_ind = extract_optional_view(mode, queryable, ind, top=top)
        if df_ind is not None and not df_ind.empty:
            safe = ind.lower()
            meta["files"].update(_save_df(stage, safe, df_ind))
            meta["sources"].append(f"dbo.{ind}")
            meta["columns"][ind] = list(df_ind.columns.astype(str))
            _log(f"[DW] {safe} ← {len(df_ind)} linhas")

    resumo = build_cruzamento_sih_resumo(agg_sih, agg_sia)
    resumo_path = stage / "cruzamento_sih_sia_resumo.json"
    resumo_path.write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    meta["files"]["cruzamento_sih_sia_resumo"] = resumo_path.name
    meta["resumo"] = resumo

    # CSV tabular do top mun para briefing
    top_rows = resumo.get("top_mun") or []
    if top_rows:
        top_df = pd.DataFrame(top_rows)
        meta["files"].update(_save_df(stage, "cruzamento_sih_sia_top_mun", top_df))

    return meta


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

        extracted_sources: list[str] = [gal_view]

        # Bundle SIH/SIA/INDICADORES (amostra + aggs) — antes do loop genérico
        sih_sia = extract_sih_sia_bundle(
            mode, queryable, stage, days_back=max(90, int(micro_days)), names=names
        )
        meta["files"].update(sih_sia.get("files") or {})
        meta["sih_sia_columns"] = sih_sia.get("columns") or {}
        meta["sih_sia_aggregates"] = sih_sia.get("aggregates") or {}
        meta["cruzamento_sih_sia"] = sih_sia.get("resumo") or {}
        for src in sih_sia.get("sources") or []:
            if src not in extracted_sources:
                extracted_sources.append(src)

        # Ping SISREG (host separado) — nunca bloqueia
        sisreg_ping = check_sisreg_tcp()
        meta["sisreg_ping"] = sisreg_ping
        _log(f"[SISREG] {sisreg_ping.get('note')}")

        # Candidatos explícitos + fuzzy (SINAN/SIM/IndicaSUS/SISREG/SIH/SIA/CNES/pop)
        fuzzy_groups: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("SINAN", ("VW_SINAN", "SINAN")),
            ("SIM", ("VW_SIM", "SIM")),
            ("INDICASUS", ("INDICA", "PACTUAC")),
            ("SISREG", ("SISREG",)),
            ("SIH", ("SIH", "AIH", "INTERNAC")),
            ("SIA", ("SIA", "AMBULATOR")),
            ("SIVEP", ("SIVEP", "SRAG")),
            ("CNES", ("VW_CNES", "CNES")),
            ("POPULACAO", ("POPULAC",)),
        )
        # Já cobertos pelo bundle SIH/SIA/INDICADORES*
        already = {
            gal_view,
            "VW_INTERNACAO",
            "SIA",
            "SIA_APAC",
            "INDICADORES",
            "INDICADORESPACTUACAO",
            "INDICADORESVIGILANCIASAUDE",
            "VW_SIH",
            "VW_SIA",
            "VW_AIH",
            "SIH",
        }
        extra_names: list[str] = []
        # 1) SINAN prioritários (vários agravos)
        for cand in SINAN_PRIORITY_VIEWS:
            if cand in names and cand not in already:
                extra_names.append(cand)
                already.add(cand)
        # 2) Candidatos explícitos
        for cand in OPTIONAL_EXTRACT_CANDIDATES:
            if cand in names and cand not in already:
                extra_names.append(cand)
                already.add(cand)
        # 3) Leftovers must (SINASC / SIVEP)
        for cand in DW_LEFTOVER_MUST:
            if cand in names and cand not in already:
                extra_names.append(cand)
                already.add(cand)
        # 4) Fuzzy — até 2 por grupo (exceto SINAN: já coberto)
        for label, needles in fuzzy_groups:
            matches = sorted(
                n for n in names
                if n not in already and any(nd in n for nd in needles)
            )
            if label == "SINAN":
                # Complementa com TODAS as views SINAN restantes (TOP N cada)
                for pick in matches:
                    if pick not in already:
                        extra_names.append(pick)
                        already.add(pick)
                continue
            if label in ("SIH", "SIA", "INDICASUS"):
                # Bundle dedicado já extraiu
                continue
            vw_first = [n for n in matches if n.startswith("VW_")] or matches[:2]
            for pick in vw_first[:2]:
                if pick not in extra_names:
                    extra_names.append(pick)
                    already.add(pick)

        meta["sources_attempted"] = extra_names
        leftover_fail: list[str] = []
        leftover_ok: list[str] = []
        # Limite alto o bastante para cobrir ~23 VW_SINAN + SINASC + extras
        for cand in extra_names[:40]:
            schema = "dbo"
            if not inv.empty and "TABLE_NAME" in inv.columns:
                hit = inv[inv["TABLE_NAME"].astype(str).str.upper() == cand]
                if not hit.empty and "TABLE_SCHEMA" in hit.columns:
                    schema = str(hit.iloc[0]["TABLE_SCHEMA"])
            top = 30_000 if cand.startswith("VW_SINAN") or cand == "VW_SINASC" else 50_000
            df = extract_optional_view(mode, queryable, cand, schema=schema, top=top)
            if df is not None and not df.empty:
                safe = re.sub(r"[^a-z0-9_]+", "_", cand.lower())
                p = stage / f"{safe}.parquet"
                df.to_parquet(p, index=False)
                df.to_csv(stage / f"{safe}.csv", index=False, encoding="utf-8-sig")
                meta["files"][safe] = str(p.name)
                extracted_sources.append(f"{schema}.{cand}")
                leftover_ok.append(cand)
                _log(f"[DW] Extraído {schema}.{cand} → {p.name} ({len(df)} linhas)")
            else:
                leftover_fail.append(cand)
        meta["sources_extracted"] = extracted_sources
        meta["dw_leftovers"] = {
            "attempted": list(extra_names[:40]),
            "extracted_count": len(leftover_ok),
            "extracted": leftover_ok,
            "failures": leftover_fail,
        }
    finally:
        if mode == "pyodbc" and queryable is not None:
            try:
                queryable.close()
            except Exception:
                pass

    # Hosts externos (IndicaSUS / SISREG) — fail soft
    external: dict[str, Any] = {}
    try:
        from etl.external_extract import run_external_extract, write_fontes_busca_report

        external = run_external_extract(outdir)
        meta["external"] = {
            "indicasus_ok": bool((external.get("indicasus") or {}).get("ok")),
            "sisreg_ok": bool((external.get("sisreg") or {}).get("ok")),
            "indicasus_objects": (external.get("indicasus") or {}).get("objects_listed"),
            "sisreg_objects": (external.get("sisreg") or {}).get("objects_listed"),
            "indicasus_extracted": [
                e.get("stem") for e in ((external.get("indicasus") or {}).get("extracted") or [])
            ],
            "sisreg_extracted": [
                e.get("stem") for e in ((external.get("sisreg") or {}).get("extracted") or [])
            ],
        }
        # Propagar files dos externos no meta
        for key in ("indicasus", "sisreg"):
            for stem, fname in ((external.get(key) or {}).get("files") or {}).items():
                meta["files"][stem] = fname
        write_fontes_busca_report(stage, dw_meta=meta, external=external)
    except Exception as exc:
        meta["external"] = {"error": type(exc).__name__}
        _log(f"[EXTERNAL] skip: {type(exc).__name__}")
        try:
            from etl.external_extract import write_fontes_busca_report

            write_fontes_busca_report(stage, dw_meta=meta, external=external)
        except Exception:
            pass

    meta_path = stage / "extract_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    meta["files"]["extract_meta"] = str(meta_path.name)
    _log(f"[DW] Staging OK → {stage}")
    return meta
