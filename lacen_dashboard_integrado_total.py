# -*- coding: utf-8 -*-
"""
Painel Integrado de Vigilância — LACEN MT
Versão v5.0 — CSV, análises do período, monitoramento 2026 e alertas para próximos dias.

Estrutura mantida:
- Lê os CSVs já existentes em saida_pipeline.
- Não exige DuckDB/Parquet.
- Mantém compatibilidade com integrated_weekly_surveillance.csv, integrated_alerts.csv,
  integrated_annual_summary.csv e integrated_target_municipio_summary.csv.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from lacen_theme import footer_institucional, hero, inject_theme, meta_bar


VERSAO_DASHBOARD_LACEN = "v5.2-identidade-institucional-ses-cievs"

st.set_page_config(
    page_title="LACEN MT | SES-MT · CIEVS-MT",
    page_icon="assets/logos/brasao_mato_grosso.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_theme()


# =============================================================================
# Arquivos
# =============================================================================

CORE_FILES = {
    "weekly": "integrated_weekly_surveillance.csv",
    "alerts": "integrated_alerts.csv",
    "annual": "integrated_annual_summary.csv",
    "summary_mun": "integrated_target_municipio_summary.csv",
}

OPTIONAL_FILES = {
    "forecast": "forecast_integrated_statewide.csv",
    "municipal_master": "municipal_master.csv",
    "population": "populacao_municipio.csv",
    "climate_weekly": "climate_weekly_municipio.csv",
    "climate_assoc": "climate_association_summary.csv",
    "requests_demo": "requests_by_demo.csv",
    "positivity_demo": "positivity_by_demo.csv",
    "sinan_demo": "sinan_demo.csv",
    "sim_demo": "sim_demo.csv",
    "backlog": "backlog_by_status_year.csv",
    "schema": "schema_catalog.csv",
    "cnes_capacity": "cnes_capacity_municipio.csv",
    "weekly_alerts_raw": "weekly_alerts.csv",
    "weekly_tests_raw": "weekly_tests_by_target_municipio.csv",
    "positivity_weekly_raw": "positivity_by_target_epiweek_municipio.csv",
    "municipios_risco": "municipios_em_risco.csv",
    "municipios_silenciosos": "municipios_silenciosos.csv",
    "taxa_utilizacao": "taxa_utilizacao_lacen.csv",
    "ml_forecast": "ml_forecast_demanda.csv",
    "ml_anomalias": "ml_anomalias.csv",
    "ml_risco": "ml_risco_predito.csv",
    "ml_silencio": "ml_silencio_predito.csv",
    "ml_features": "ml_features_latest.csv",
    "sinan_weekly": "sinan_weekly_municipio.csv",
    "sim_weekly": "sim_weekly_municipio.csv",
}


# =============================================================================
# Utilitários
# =============================================================================

def strip_accents(text: object) -> str:
    if text is None:
        return ""
    try:
        if isinstance(text, float) and math.isnan(text):
            return ""
    except Exception:
        pass
    s = str(text)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def norm_key(text: object) -> str:
    s = strip_accents(text).casefold().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def norm_municipio(text: object) -> str:
    s = strip_accents(text).upper().strip()
    s = re.sub(r"^\d+\s*[-\.]?\s*", "", s)
    s = s.replace("MUNICIPIO DE ", "")
    s = re.sub(r"\s+", " ", s)
    return s


def norm_join_municipio(text: object) -> str:
    s = norm_municipio(text)
    s = s.replace("SANTO ANTONIO DO LESTE", "SANTO ANTONIO DE LESTE")
    s = s.replace("POXOREU", "POXOREO")
    s = s.replace("GLORIA D'OESTE", "GLORIA DOESTE")
    return re.sub(r"[^A-Z0-9]+", "", s)


def read_csv_resilient(path: Path) -> pd.DataFrame:
    last_error = None
    for enc in ("utf-8-sig", "utf-8", "latin1", "cp1252"):
        for sep in (None, ";", ",", "\t", "|"):
            try:
                if sep is None:
                    df = pd.read_csv(path, encoding=enc, low_memory=False)
                else:
                    df = pd.read_csv(path, encoding=enc, sep=sep, low_memory=False)
                if df.shape[1] >= 1:
                    return df
            except Exception as exc:
                last_error = exc
    raise ValueError(f"Não foi possível ler {path}. Último erro: {last_error}")


def read_table_resilient(path: Path) -> pd.DataFrame:
    """Prefere .parquet (mais rápido); cai para CSV resiliente."""
    pq = path if path.suffix.lower() == ".parquet" else path.with_suffix(".parquet")
    csv = path if path.suffix.lower() == ".csv" else path.with_suffix(".csv")
    if pq.exists():
        try:
            return pd.read_parquet(pq)
        except Exception:
            pass
    if csv.exists():
        return read_csv_resilient(csv)
    raise FileNotFoundError(f"Nem parquet nem CSV: {path}")


def first_col(df_or_cols: pd.DataFrame | Iterable[str], candidates: Sequence[str]) -> Optional[str]:
    cols = list(df_or_cols.columns if isinstance(df_or_cols, pd.DataFrame) else df_or_cols)
    normalized = {norm_key(c): c for c in cols}
    literal = {c: c for c in cols}
    for cand in candidates:
        if cand in literal:
            return literal[cand]
        nk = norm_key(cand)
        if nk in normalized:
            return normalized[nk]
    return None


def fuzzy_col(
    df_or_cols: pd.DataFrame | Iterable[str],
    include_any: Sequence[str] = (),
    include_all: Sequence[str] = (),
    exclude_any: Sequence[str] = (),
) -> Optional[str]:
    cols = list(df_or_cols.columns if isinstance(df_or_cols, pd.DataFrame) else df_or_cols)
    any_tokens = [norm_key(x) for x in include_any]
    all_tokens = [norm_key(x) for x in include_all]
    exc_tokens = [norm_key(x) for x in exclude_any]
    scored: list[tuple[float, str]] = []
    for c in cols:
        nc = norm_key(c)
        if exc_tokens and any(tok and tok in nc for tok in exc_tokens):
            continue
        if all_tokens and not all(tok and tok in nc for tok in all_tokens):
            continue
        if any_tokens and not any(tok and tok in nc for tok in any_tokens):
            continue
        score = 0.0
        score += sum(tok in nc for tok in any_tokens) * 2
        score += sum(tok in nc for tok in all_tokens) * 3
        score -= len(nc) / 1000.0
        scored.append((score, c))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def to_num(s: object) -> pd.Series | float:
    if isinstance(s, pd.Series):
        if pd.api.types.is_numeric_dtype(s):
            return pd.to_numeric(s, errors="coerce")
        return pd.to_numeric(
            s.astype(str)
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False)
            .replace({"nan": np.nan, "None": np.nan, "": np.nan}),
            errors="coerce",
        )
    try:
        if s is None or (isinstance(s, float) and math.isnan(s)):
            return np.nan
        if isinstance(s, (int, float, np.number)):
            return float(s)
        return float(str(s).replace(".", "").replace(",", "."))
    except Exception:
        return np.nan


def normalize_prop(s: pd.Series) -> pd.Series:
    x = to_num(s)
    return pd.Series(np.where(x > 1.5, x / 100.0, x), index=s.index)


def safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return np.where(b > 0, a / b, np.nan)


def format_int(x) -> str:
    if pd.isna(x):
        return "0"
    try:
        return f"{int(round(float(x))):,}".replace(",", ".")
    except Exception:
        return str(x)


def format_pct(x) -> str:
    if pd.isna(x):
        return "NA"
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return "NA"


def format_num(x, digits: int = 2) -> str:
    if pd.isna(x):
        return "NA"
    try:
        return f"{float(x):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(x)


def iso_monday(year: int, week: int) -> Optional[date]:
    try:
        return date.fromisocalendar(int(year), int(week), 1)
    except Exception:
        return None


def iso_week_label(year: object, week: object) -> str:
    if pd.isna(year) or pd.isna(week):
        return "NA"
    try:
        return f"{int(year)}-SE{int(week):02d}"
    except Exception:
        return "NA"


def safe_marker_size(df: pd.DataFrame, source_col: str, out_col: str, min_size: float = 7.0, max_size: float = 24.0) -> pd.DataFrame:
    df = df.copy()
    if source_col not in df.columns:
        df[out_col] = float(min_size)
        return df
    s = to_num(df[source_col]).replace([np.inf, -np.inf], np.nan)
    valid = s.dropna()
    if valid.empty:
        df[out_col] = float(min_size)
        return df
    vmin = float(valid.min())
    vmax = float(valid.max())
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax == vmin:
        df[out_col] = float((min_size + max_size) / 2.0)
        return df
    scaled = min_size + ((s - vmin) / (vmax - vmin)) * (max_size - min_size)
    df[out_col] = scaled.fillna(min_size).clip(lower=min_size, upper=max_size)
    return df


def robust_z(s: pd.Series) -> pd.Series:
    s = to_num(s)
    med = s.median()
    mad = (s - med).abs().median()
    if pd.isna(mad) or mad == 0:
        std = s.std(ddof=0)
        if pd.isna(std) or std == 0:
            return pd.Series(np.zeros(len(s)), index=s.index)
        return (s - s.mean()) / std
    return 0.6745 * (s - med) / mad


def require_cols(df: Optional[pd.DataFrame], cols: Sequence[str], context: str) -> bool:
    """Valida colunas antes de plotar; avisa em vez de quebrar o painel."""
    if df is None or df.empty:
        st.warning(f"{context}: sem dados para exibir.")
        return False
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.warning(f"{context}: colunas ausentes ({', '.join(missing)}). Exibindo tabela parcial.")
        show_table(df, context, max_rows=200)
        return False
    return True


def ensure_cols(df: Optional[pd.DataFrame], defaults: dict) -> pd.DataFrame:
    """Garante colunas mínimas para o painel não quebrar (preenche ausentes)."""
    if df is None:
        return pd.DataFrame({k: pd.Series(dtype=type(v) if v is not None else float) for k, v in defaults.items()})
    out = df.copy()
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    return out


def safe_plotly(fig, context: str = "Gráfico") -> None:
    """Renderiza Plotly com fallback — evita crash do Streamlit."""
    if fig is None:
        st.warning(f"{context}: figura vazia.")
        return
    try:
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.warning(f"{context}: falha ao renderizar ({exc}).")


def ensure_alias_columns(df: pd.DataFrame, aliases: dict[str, Sequence[str]]) -> pd.DataFrame:
    """Garante colunas canônicas a partir de aliases (ex.: positividade vs positivity)."""
    out = df.copy()
    for canonical, candidates in aliases.items():
        if canonical in out.columns:
            continue
        found = first_col(out, list(candidates) + [canonical])
        if found and found in out.columns:
            out[canonical] = out[found]
    return out


def show_table(df: pd.DataFrame, title: str, max_rows: int = 500) -> None:
    st.markdown(f"#### {title}")
    if df is None or df.empty:
        st.info("Tabela vazia para o filtro atual.")
        return
    st.dataframe(df.head(max_rows), use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    safe_name = norm_key(title) or "tabela"
    st.download_button(
        f"Baixar {title} em CSV",
        data=csv,
        file_name=f"{safe_name}.csv",
        mime="text/csv",
    )


# =============================================================================
# Carga e harmonização
# =============================================================================

@st.cache_data(show_spinner=False)
def load_data(folder: str):
    base = Path(folder)
    data: dict[str, Optional[pd.DataFrame]] = {}
    missing: list[str] = []

    for key, filename in CORE_FILES.items():
        p = base / filename
        pq = p.with_suffix(".parquet")
        if not p.exists() and not pq.exists():
            data[key] = None
            missing.append(filename)
        else:
            data[key] = read_table_resilient(p)

    for key, filename in OPTIONAL_FILES.items():
        p = base / filename
        pq = p.with_suffix(".parquet")
        if p.exists() or pq.exists():
            try:
                data[key] = read_table_resilient(p)
            except Exception:
                data[key] = None
        else:
            data[key] = None

    return data, missing


def harmonize_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = ensure_alias_columns(
        df,
        {
            "positividade": ["positivity", "positividade_media", "taxa_positividade", "pos_rate"],
            "positives": ["positivos", "detectados", "reagentes", "n_positivos"],
            "tests": ["testes", "solicitacoes", "solicitacoes_lacen", "n_testes", "exames"],
            "notificacoes": ["notificacoes_sinan", "casos_sinan", "casos"],
            "municipio": ["Município", "Municipio", "municipio_residencia", "mun"],
            "latitude": ["lat", "y", "coord_y", "Latitude"],
            "longitude": ["lon", "long", "lng", "x", "coord_x", "Longitude"],
        },
    )

    col_target = first_col(df, ["target", "alvo", "agravo", "agravo_alvo", "doenca"])
    col_mun = first_col(df, ["municipio", "Município", "Municipio", "municipio_residencia"])
    col_year = first_col(df, ["epi_year", "ano", "year", "ano_epidemiologico"])
    col_week = first_col(df, ["epi_week", "semana", "week", "semana_epidemiologica"])

    if col_target and col_target != "target":
        df["target"] = df[col_target].astype(str)
    elif "target" not in df.columns:
        df["target"] = "outros"

    if col_mun and col_mun != "municipio":
        df["municipio"] = df[col_mun].map(norm_municipio)
    elif "municipio" in df.columns:
        df["municipio"] = df["municipio"].map(norm_municipio)
    else:
        df["municipio"] = "IGNORADO"

    if col_year and col_year != "epi_year":
        df["epi_year"] = to_num(df[col_year])
    elif "epi_year" in df.columns:
        df["epi_year"] = to_num(df["epi_year"])
    else:
        df["epi_year"] = np.nan

    if col_week and col_week != "epi_week":
        df["epi_week"] = to_num(df[col_week])
    elif "epi_week" in df.columns:
        df["epi_week"] = to_num(df["epi_week"])
    else:
        df["epi_week"] = np.nan

    col_tests = first_col(df, ["tests", "testes", "solicitacoes", "solicitacoes_lacen", "n_testes", "exames"])
    col_pos = first_col(df, ["positives", "positivos", "detectados", "reagentes", "n_positivos"])
    col_neg = first_col(df, ["negatives", "negativos", "n_negativos"])
    col_notif = first_col(df, ["notificacoes", "notificacoes_sinan", "casos_sinan", "casos"])
    col_deaths = first_col(df, ["obitos_sim", "obitos", "deaths", "mortes"])
    col_pop = first_col(df, ["populacao", "pop", "population"])
    col_posrate = first_col(df, ["positividade", "positivity", "positividade_media", "taxa_positividade"])
    col_inc = first_col(df, ["incidencia_100k", "incidencia", "incidencia_media_100k"])
    col_mort = first_col(df, ["mortalidade_100k", "mortalidade"])
    col_risk = first_col(df, ["risco_composto", "indice_risco_integrado", "risco_integrado", "risk_score"])

    df["tests"] = to_num(df[col_tests]) if col_tests else 0
    df["positives"] = to_num(df[col_pos]) if col_pos else 0
    df["negatives"] = to_num(df[col_neg]) if col_neg else np.nan
    df["notificacoes"] = to_num(df[col_notif]) if col_notif else 0
    df["obitos_sim"] = to_num(df[col_deaths]) if col_deaths else 0
    df["populacao"] = to_num(df[col_pop]) if col_pop else np.nan

    if col_posrate:
        df["positividade"] = normalize_prop(df[col_posrate])
    else:
        df["positividade"] = safe_div(df["positives"], df["tests"])

    if col_inc:
        df["incidencia_100k"] = to_num(df[col_inc])
    else:
        df["incidencia_100k"] = np.where(df["populacao"] > 0, df["notificacoes"] / df["populacao"] * 100000, np.nan)

    if col_mort:
        df["mortalidade_100k"] = to_num(df[col_mort])
    else:
        df["mortalidade_100k"] = np.where(df["populacao"] > 0, df["obitos_sim"] / df["populacao"] * 100000, np.nan)

    if col_risk:
        df["risco_composto"] = to_num(df[col_risk])
    else:
        z_tests = robust_z(df["tests"].fillna(0))
        z_pos = robust_z(df["positividade"].fillna(df["positividade"].median()))
        z_not = robust_z(df["notificacoes"].fillna(0))
        df["risco_composto"] = (z_tests.fillna(0) + z_pos.fillna(0) + z_not.fillna(0)) / 3

    df["epi_year"] = to_num(df["epi_year"])
    df["epi_week"] = to_num(df["epi_week"])
    df["periodo"] = [iso_week_label(y, w) for y, w in zip(df["epi_year"], df["epi_week"])]
    df["periodo_data"] = [iso_monday(y, w) for y, w in zip(df["epi_year"], df["epi_week"])]
    df["target"] = df["target"].astype(str)
    return df


def harmonize_annual(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    target = first_col(df, ["target", "alvo", "agravo"])
    ano = first_col(df, ["ano", "year", "epi_year"])
    tests = first_col(df, ["testes", "tests", "solicitacoes"])
    pos = first_col(df, ["positivos", "positives"])
    notif = first_col(df, ["notificacoes", "notificacoes_sinan"])
    deaths = first_col(df, ["obitos", "obitos_sim"])
    posrate = first_col(df, ["positividade_media", "positividade", "positivity"])
    inc = first_col(df, ["incidencia_100k", "incidencia_media_100k"])
    risk = first_col(df, ["risco_max", "risco_composto", "indice_risco_integrado"])

    if target and target != "target":
        df["target"] = df[target].astype(str)
    elif "target" not in df.columns:
        df["target"] = "outros"
    df["ano"] = to_num(df[ano]) if ano else np.nan
    df["testes"] = to_num(df[tests]) if tests else 0
    df["positivos"] = to_num(df[pos]) if pos else 0
    df["notificacoes"] = to_num(df[notif]) if notif else 0
    df["obitos"] = to_num(df[deaths]) if deaths else 0
    if posrate:
        df["positividade_media"] = normalize_prop(df[posrate])
    else:
        df["positividade_media"] = safe_div(df["positivos"], df["testes"])
    df["incidencia_100k"] = to_num(df[inc]) if inc else np.nan
    df["risco_max"] = to_num(df[risk]) if risk else np.nan
    return df


def detect_group_targets(all_targets: Sequence[str], mode: str) -> list[str]:
    groups = {
        "Arboviroses": ["dengue", "zika", "chik", "oropouche", "febre_amarela", "mayaro"],
        "Respiratórios": ["sars", "cov", "influenza", "vsr", "rsv", "resp", "metapneumo", "rinovirus", "adenovirus"],
        "Tuberculose": ["tuberculose", "mtb", "rifampicina", "baciloscopia"],
        "Hepatites": ["hepatite", "hbv", "hcv", "hbsag"],
        "Meningites": ["mening", "pneumo", "meningoc"],
    }
    if mode == "Todos os agravos/alvos":
        return list(all_targets)
    tokens = groups.get(mode, [])
    return [t for t in all_targets if any(tok in norm_key(t) for tok in tokens)]


# =============================================================================
# Análises do período e alertas
# =============================================================================

def aggregate_period(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=group_cols)
    g = df.groupby(group_cols, as_index=False).agg(
        semanas=("periodo", "nunique"),
        tests=("tests", "sum"),
        positives=("positives", "sum"),
        notificacoes=("notificacoes", "sum"),
        obitos_sim=("obitos_sim", "sum"),
        populacao=("populacao", "max"),
        risco_composto=("risco_composto", "max"),
        semana_min=("epi_week", "min"),
        semana_max=("epi_week", "max"),
    )
    g["positividade"] = safe_div(g["positives"], g["tests"])
    g["incidencia_100k"] = np.where(g["populacao"] > 0, g["notificacoes"] / g["populacao"] * 100000, np.nan)
    g["solicitacoes_100k"] = np.where(g["populacao"] > 0, g["tests"] / g["populacao"] * 100000, np.nan)
    g["media_semanal_tests"] = safe_div(g["tests"], g["semanas"].replace(0, np.nan))
    g["media_semanal_notificacoes"] = safe_div(g["notificacoes"], g["semanas"].replace(0, np.nan))
    return g


def build_period_analysis(
    weekly: pd.DataFrame,
    analysis_year: int,
    week_start: int,
    week_end: int,
    baseline_mode: str,
    baseline_year_start: int,
    baseline_year_end: int,
    selected_targets: list[str],
    selected_muns: list[str],
) -> pd.DataFrame:
    if weekly is None or weekly.empty:
        return pd.DataFrame()

    df = weekly.copy()
    if selected_targets:
        df = df[df["target"].isin(selected_targets)]
    if selected_muns:
        df = df[df["municipio"].isin(selected_muns)]

    current = df[(df["epi_year"].eq(analysis_year)) & (df["epi_week"].between(week_start, week_end))].copy()
    n_weeks = max(1, int(week_end) - int(week_start) + 1)

    if baseline_mode == "Período imediatamente anterior":
        prev_end = int(week_start) - 1
        prev_start = max(1, prev_end - n_weeks + 1)
        baseline = df[(df["epi_year"].eq(analysis_year)) & (df["epi_week"].between(prev_start, prev_end))].copy()
        baseline_label = f"{analysis_year}-SE{prev_start:02d} a SE{prev_end:02d}"
    elif baseline_mode == "Mesmo período do ano anterior":
        baseline = df[(df["epi_year"].eq(analysis_year - 1)) & (df["epi_week"].between(week_start, week_end))].copy()
        baseline_label = f"{analysis_year - 1}-SE{week_start:02d} a SE{week_end:02d}"
    else:
        baseline = df[
            (df["epi_year"].between(baseline_year_start, baseline_year_end))
            & (df["epi_year"].ne(analysis_year))
            & (df["epi_week"].between(week_start, week_end))
        ].copy()
        baseline_label = f"Histórico {baseline_year_start}-{baseline_year_end}, SE{week_start:02d} a SE{week_end:02d}"

    group_cols = ["municipio", "target"]
    cur = aggregate_period(current, group_cols).rename(columns={
        "semanas": "semanas_periodo",
        "tests": "tests_periodo",
        "positives": "positivos_periodo",
        "notificacoes": "notificacoes_periodo",
        "obitos_sim": "obitos_sim_periodo",
        "populacao": "populacao_periodo",
        "risco_composto": "risco_periodo",
        "positividade": "positividade_periodo",
        "incidencia_100k": "incidencia_periodo_100k",
        "solicitacoes_100k": "solicitacoes_periodo_100k",
        "media_semanal_tests": "media_semanal_tests_periodo",
        "media_semanal_notificacoes": "media_semanal_notificacoes_periodo",
    })

    base = aggregate_period(baseline, group_cols).rename(columns={
        "semanas": "semanas_base",
        "tests": "tests_base",
        "positives": "positivos_base",
        "notificacoes": "notificacoes_base",
        "obitos_sim": "obitos_sim_base",
        "populacao": "populacao_base",
        "risco_composto": "risco_base",
        "positividade": "positividade_base",
        "incidencia_100k": "incidencia_base_100k",
        "solicitacoes_100k": "solicitacoes_base_100k",
        "media_semanal_tests": "media_semanal_tests_base",
        "media_semanal_notificacoes": "media_semanal_notificacoes_base",
    })

    out = cur.merge(base, on=group_cols, how="outer")
    for c in [
        "tests_periodo", "positivos_periodo", "notificacoes_periodo", "obitos_sim_periodo",
        "tests_base", "positivos_base", "notificacoes_base", "obitos_sim_base",
        "semanas_periodo", "semanas_base",
    ]:
        if c in out.columns:
            out[c] = out[c].fillna(0)

    # Completa população com qualquer registro conhecido.
    pop = df.groupby(group_cols, as_index=False).agg(populacao=("populacao", "max"))
    out = out.merge(pop, on=group_cols, how="left")
    out["populacao"] = out["populacao"].fillna(out.get("populacao_periodo")).fillna(out.get("populacao_base"))

    out["positividade_periodo"] = safe_div(out["positivos_periodo"], out["tests_periodo"])
    out["positividade_base"] = safe_div(out["positivos_base"], out["tests_base"])

    out["delta_tests_abs"] = out["tests_periodo"].fillna(0) - out["tests_base"].fillna(0)
    out["delta_tests_pct"] = safe_div(out["delta_tests_abs"], out["tests_base"].replace(0, np.nan))
    out["delta_positivos_abs"] = out["positivos_periodo"].fillna(0) - out["positivos_base"].fillna(0)
    out["delta_positividade_pp"] = out["positividade_periodo"].fillna(0) - out["positividade_base"].fillna(0)
    out["delta_notificacoes_abs"] = out["notificacoes_periodo"].fillna(0) - out["notificacoes_base"].fillna(0)
    out["delta_notificacoes_pct"] = safe_div(out["delta_notificacoes_abs"], out["notificacoes_base"].replace(0, np.nan))

    out["incidencia_periodo_100k"] = np.where(out["populacao"] > 0, out["notificacoes_periodo"] / out["populacao"] * 100000, np.nan)
    out["solicitacoes_periodo_100k"] = np.where(out["populacao"] > 0, out["tests_periodo"] / out["populacao"] * 100000, np.nan)

    # Baseline histórico semanal para z-score, sempre que possível.
    hist = df[
        (df["epi_year"].between(baseline_year_start, baseline_year_end))
        & (df["epi_year"].ne(analysis_year))
        & (df["epi_week"].between(week_start, week_end))
    ].copy()
    if not hist.empty:
        h = aggregate_period(hist, group_cols)
        h = h.rename(columns={"media_semanal_tests": "hist_media_semanal_tests"})
        hist_week_stats = h.groupby(group_cols, as_index=False).agg(
            hist_media_semanal_tests=("hist_media_semanal_tests", "mean"),
            hist_dp_semanal_tests=("hist_media_semanal_tests", "std"),
            hist_positividade_media=("positividade", "mean"),
            hist_notificacoes_media=("media_semanal_notificacoes", "mean"),
        )
        out = out.merge(hist_week_stats, on=group_cols, how="left")
    else:
        out["hist_media_semanal_tests"] = np.nan
        out["hist_dp_semanal_tests"] = np.nan
        out["hist_positividade_media"] = np.nan
        out["hist_notificacoes_media"] = np.nan

    out["z_solicitacoes_vs_historico"] = (
        out["media_semanal_tests_periodo"] - out["hist_media_semanal_tests"]
    ) / out["hist_dp_semanal_tests"].replace(0, np.nan)
    out["z_solicitacoes_vs_historico"] = out["z_solicitacoes_vs_historico"].replace([np.inf, -np.inf], np.nan).fillna(0)

    out["silencio_laboratorial"] = (out["tests_periodo"].fillna(0) == 0) & (out["notificacoes_periodo"].fillna(0) > 0)
    out["baixo_uso_lacen"] = (
        (out["notificacoes_periodo"].fillna(0) >= 3)
        & (out["tests_periodo"].fillna(0) < np.maximum(1, out["notificacoes_periodo"].fillna(0) * 0.2))
    )

    def scenario(row: pd.Series) -> str:
        inc_tests = row.get("delta_tests_pct", np.nan)
        inc_pos = row.get("delta_positividade_pp", 0)
        zt = row.get("z_solicitacoes_vs_historico", 0)
        tests = row.get("tests_periodo", 0)
        notif = row.get("notificacoes_periodo", 0)
        if bool(row.get("silencio_laboratorial", False)):
            return "Silêncio laboratorial com notificação SINAN"
        if bool(row.get("baixo_uso_lacen", False)):
            return "Baixa utilização do LACEN diante de notificações"
        if tests > 0 and inc_pos >= 0.15 and (pd.notna(inc_tests) and inc_tests >= 0.30 or zt >= 1.5):
            return "Aumento simultâneo de positividade e solicitações"
        if tests > 0 and inc_pos >= 0.15:
            return "Aumento relevante de positividade"
        if pd.notna(inc_tests) and inc_tests >= 0.50:
            return "Aumento relevante de solicitações"
        if notif > 0 and row.get("delta_notificacoes_abs", 0) > 0:
            return "Aumento de notificações SINAN"
        if tests > 0:
            return "Atividade laboratorial no período"
        return "Sem sinal laboratorial no período"

    def priority(row: pd.Series) -> str:
        pos_period = row.get("positividade_periodo", np.nan)
        delta_pos = row.get("delta_positividade_pp", 0)
        delta_tests_pct = row.get("delta_tests_pct", np.nan)
        zt = row.get("z_solicitacoes_vs_historico", 0)
        deaths = row.get("obitos_sim_periodo", 0)
        if bool(row.get("silencio_laboratorial", False)):
            return "ALTO"
        if deaths and deaths >= 1 and (delta_pos >= 0.10 or zt >= 1.5):
            return "CRÍTICO"
        if pd.notna(pos_period) and pos_period >= 0.30 and (delta_pos >= 0.15 or zt >= 2.0 or (pd.notna(delta_tests_pct) and delta_tests_pct >= 0.50)):
            return "CRÍTICO"
        if delta_pos >= 0.10 or zt >= 1.5 or (pd.notna(delta_tests_pct) and delta_tests_pct >= 0.30) or bool(row.get("baixo_uso_lacen", False)):
            return "ALTO"
        if delta_pos >= 0.05 or zt >= 1.0 or (pd.notna(delta_tests_pct) and delta_tests_pct >= 0.15) or row.get("notificacoes_periodo", 0) > 0:
            return "MODERADO"
        return "MONITORAMENTO"

    out["cenario_operacional"] = out.apply(scenario, axis=1)
    out["prioridade"] = out.apply(priority, axis=1)
    score_map = {"MONITORAMENTO": 1, "MODERADO": 2, "ALTO": 3, "CRÍTICO": 4}
    out["prioridade_score"] = out["prioridade"].map(score_map).fillna(1).astype(int)

    out["ano_analise"] = analysis_year
    out["periodo_analise"] = f"{analysis_year}-SE{week_start:02d} a SE{week_end:02d}"
    out["periodo_base"] = baseline_label
    out["modo_comparacao"] = baseline_mode
    out = out.sort_values(["prioridade_score", "delta_positividade_pp", "delta_tests_abs"], ascending=[False, False, False])
    return out.reset_index(drop=True)


def enrich_period_projection(period_df: pd.DataFrame, horizon_days: int, week_start: int, week_end: int, analysis_year: int) -> pd.DataFrame:
    if period_df is None or period_df.empty:
        return pd.DataFrame()
    out = period_df.copy()
    n_weeks = max(1, int(week_end) - int(week_start) + 1)
    factor = horizon_days / 7.0

    media_tests = out["tests_periodo"].fillna(0) / n_weeks
    tendencia = (out["delta_tests_abs"].fillna(0) / n_weeks).clip(lower=-media_tests)
    out["projecao_solicitacoes_proximos_dias"] = np.maximum(0, (media_tests + tendencia * 0.5) * factor).round(1)

    pos_proj = out["positividade_periodo"].fillna(out["positividade_base"]).fillna(0)
    pos_proj = np.minimum(np.maximum(pos_proj + out["delta_positividade_pp"].fillna(0) / 2.0, 0), 1)
    out["positividade_projetada_proximos_dias"] = pos_proj
    out["projecao_positivos_proximos_dias"] = (out["projecao_solicitacoes_proximos_dias"] * pos_proj).round(1)

    start = iso_monday(analysis_year, week_end)
    if start is not None:
        next_start = start + timedelta(days=7)
        next_end = next_start + timedelta(days=horizon_days - 1)
        out["janela_alerta_proximos_dias"] = f"{next_start:%d/%m/%Y} a {next_end:%d/%m/%Y}"
    else:
        out["janela_alerta_proximos_dias"] = f"próximos {horizon_days} dias"
    out["horizonte_alerta_dias"] = horizon_days
    return out


def build_manager_alert_messages(period_df: pd.DataFrame, folder: str, horizon_days: int) -> pd.DataFrame:
    if period_df is None or period_df.empty:
        return pd.DataFrame()

    df = period_df.copy()
    df = df[df["prioridade"].isin(["CRÍTICO", "ALTO", "MODERADO"])].copy()
    if df.empty:
        return pd.DataFrame()

    df = df.sort_values(["prioridade_score", "delta_positividade_pp", "delta_tests_abs"], ascending=[False, False, False])

    # Cadastro opcional de contatos.
    contacts = None
    for p in [Path(folder) / "gestores_municipais.csv", Path("gestores_municipais.csv")]:
        if p.exists():
            try:
                contacts = read_csv_resilient(p)
                break
            except Exception:
                contacts = None

    if contacts is not None and not contacts.empty:
        cmun = first_col(contacts, ["municipio", "Município", "Municipio"])
        if cmun:
            contacts = contacts.copy()
            contacts["municipio"] = contacts[cmun].map(norm_municipio)
            keep = ["municipio"] + [
                c for c in contacts.columns
                if norm_key(c) in {"gestor", "responsavel", "responsavel_tecnico", "email", "e_mail", "whatsapp", "telefone", "celular"}
            ]
            df = df.merge(contacts[keep].drop_duplicates("municipio"), on="municipio", how="left")

    def action(row: pd.Series) -> str:
        cenario = str(row.get("cenario_operacional", ""))
        if "Silêncio" in cenario:
            return "Acionar vigilância municipal para checar fluxo de coleta/envio ao LACEN e conciliar casos SINAN sem exame."
        if "Baixa utilização" in cenario:
            return "Orientar ampliação/regularização do envio de amostras e revisão do fluxo assistencial-laboratorial."
        if row.get("prioridade") == "CRÍTICO":
            return "Acionar gestor municipal e regional no mesmo dia; verificar coleta, estoque, investigação, assistência e comunicação de risco."
        if row.get("prioridade") == "ALTO":
            return "Emitir alerta técnico ao município e regional; solicitar verificação local e plano de resposta em 24-48h."
        return "Manter monitoramento ativo e solicitar checagem de dados se o padrão persistir."

    def subject(row: pd.Series) -> str:
        return (
            f"[{row.get('prioridade', 'MONITORAMENTO')}] Alerta LACEN-MT — "
            f"{row.get('target', 'agravo')} em {row.get('municipio', 'município')}"
        )

    def message(row: pd.Series) -> str:
        return (
            f"Alerta operacional LACEN-MT ({row.get('prioridade')}) — "
            f"{row.get('municipio')} | Agravo/alvo: {row.get('target')}. "
            f"Período analisado: {row.get('periodo_analise')}; comparação: {row.get('periodo_base')}. "
            f"Cenário: {row.get('cenario_operacional')}. "
            f"Solicitações LACEN no período: {format_int(row.get('tests_periodo'))}; "
            f"positivos: {format_int(row.get('positivos_periodo'))}; "
            f"positividade: {format_pct(row.get('positividade_periodo'))}; "
            f"variação de positividade: {format_num((row.get('delta_positividade_pp', 0) or 0) * 100, 1)} p.p.; "
            f"variação de solicitações: {format_int(row.get('delta_tests_abs'))}. "
            f"Notificações SINAN no período: {format_int(row.get('notificacoes_periodo'))}. "
            f"Projeção operacional para {row.get('janela_alerta_proximos_dias')}: "
            f"{format_num(row.get('projecao_solicitacoes_proximos_dias'), 1)} solicitações e "
            f"{format_num(row.get('projecao_positivos_proximos_dias'), 1)} positivos estimados. "
            f"Ação sugerida: {action(row)}"
        )

    df["assunto_email"] = df.apply(subject, axis=1)
    df["mensagem_gestor"] = df.apply(message, axis=1)
    df["acao_sugerida"] = df.apply(action, axis=1)
    df["canal_sugerido"] = np.where(
        df["prioridade"].eq("CRÍTICO"),
        "WhatsApp + e-mail + ligação",
        np.where(df["prioridade"].eq("ALTO"), "WhatsApp + e-mail", "E-mail/boletim de monitoramento"),
    )
    df["status_envio"] = "pendente_validacao_tecnica"
    df["horizonte_alerta_dias"] = horizon_days

    cols_front = [
        "prioridade", "municipio", "target", "periodo_analise", "periodo_base",
        "cenario_operacional", "janela_alerta_proximos_dias",
        "assunto_email", "mensagem_gestor", "acao_sugerida",
        "canal_sugerido", "status_envio",
    ]
    cols = cols_front + [c for c in df.columns if c not in cols_front]
    return df[cols]


# =============================================================================
# Malha municipal
# =============================================================================

def infer_shape_municipio_col(df: pd.DataFrame) -> Optional[str]:
    candidates = [
        "municipio", "Município", "Municipio", "NM_MUN", "NM_MUNICIP", "NM_MUNICIPIO",
        "NOME", "NOME_MUN", "NOMEMUN", "name", "NAME", "MUN_NOME",
    ]
    c = first_col(df, candidates)
    if c:
        return c
    return fuzzy_col(df, include_any=["mun", "municip", "nome"])


def find_geo_file(user_path: str = "") -> Optional[Path]:
    if user_path:
        p = Path(user_path)
        if p.exists() and p.suffix.lower() in {".shp", ".geojson", ".json"}:
            return p
    for d in [Path("shapefiles"), Path("malhas"), Path("."), Path("geo")]:
        if not d.exists():
            continue
        for ext in ("*.geojson", "*.json", "*.shp"):
            files = sorted(d.glob(ext))
            if files:
                return files[0]
    return None


@st.cache_data(show_spinner=False)
def load_geojson_or_shp(path_str: str):
    if not path_str:
        return None, pd.DataFrame(), "Nenhuma malha informada/encontrada."

    p = Path(path_str)
    if not p.exists():
        return None, pd.DataFrame(), f"Malha não encontrada: {p}"

    try:
        if p.suffix.lower() in {".geojson", ".json"}:
            geojson = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
            rows = []
            for idx, feat in enumerate(geojson.get("features", [])):
                props = dict(feat.get("properties", {}) or {})
                props["__id"] = str(idx)
                feat["properties"] = props
                rows.append(props)
            props_df = pd.DataFrame(rows)
            mc = infer_shape_municipio_col(props_df)
            if mc:
                props_df["municipio_join"] = props_df[mc].map(norm_join_municipio)
                for feat, (_, row) in zip(geojson.get("features", []), props_df.iterrows()):
                    feat["properties"]["municipio_join"] = row["municipio_join"]
            return geojson, props_df, f"Malha GeoJSON carregada: {p}"

        if p.suffix.lower() == ".shp":
            try:
                import shapefile
            except Exception as exc:
                return None, pd.DataFrame(), f"Para ler SHP, instale pyshp: python -m pip install pyshp. Erro: {exc}"

            reader = shapefile.Reader(str(p), encoding="latin1")
            fields = [f[0] for f in reader.fields[1:]]
            features = []
            rows = []
            for idx, sr in enumerate(reader.iterShapeRecords()):
                props = {fields[i]: sr.record[i] for i in range(len(fields))}
                props["__id"] = str(idx)
                try:
                    geom = sr.shape.__geo_interface__
                except Exception:
                    continue
                features.append({"type": "Feature", "properties": props, "geometry": geom})
                rows.append(props)
            props_df = pd.DataFrame(rows)
            mc = infer_shape_municipio_col(props_df)
            if mc:
                props_df["municipio_join"] = props_df[mc].map(norm_join_municipio)
                for feat, (_, row) in zip(features, props_df.iterrows()):
                    feat["properties"]["municipio_join"] = row["municipio_join"]
            return {"type": "FeatureCollection", "features": features}, props_df, f"Shapefile carregado: {p}"
    except Exception as exc:
        return None, pd.DataFrame(), f"Falha ao carregar malha: {exc}"

    return None, pd.DataFrame(), "Formato de malha não suportado."


def join_shape_with_period(props_df: pd.DataFrame, period_df: pd.DataFrame) -> pd.DataFrame:
    if props_df is None or props_df.empty or period_df is None or period_df.empty:
        return pd.DataFrame()
    props = props_df.copy()
    if "municipio_join" not in props.columns:
        mc = infer_shape_municipio_col(props)
        if not mc:
            return pd.DataFrame()
        props["municipio_join"] = props[mc].map(norm_join_municipio)
    risk = period_df.copy()
    risk["municipio_join"] = risk["municipio"].map(norm_join_municipio)
    return props[["__id", "municipio_join"]].merge(risk, on="municipio_join", how="left")


def make_choropleth(geojson: dict, merged: pd.DataFrame, value_col: str, title: str):
    if geojson is None or merged is None or merged.empty or value_col not in merged.columns:
        return None
    plot_df = merged.copy()
    plot_df[value_col] = to_num(plot_df[value_col])
    if plot_df[value_col].notna().sum() == 0:
        return None
    hover_cols = [c for c in [
        "municipio", "target", "prioridade", "cenario_operacional", "tests_periodo",
        "positivos_periodo", "positividade_periodo", "delta_positividade_pp",
        "delta_tests_abs", "notificacoes_periodo", "projecao_solicitacoes_proximos_dias",
        "janela_alerta_proximos_dias",
    ] if c in plot_df.columns]
    fig = px.choropleth_mapbox(
        plot_df,
        geojson=geojson,
        locations="__id",
        featureidkey="properties.__id",
        color=value_col,
        hover_name="municipio" if "municipio" in plot_df.columns else None,
        hover_data={c: True for c in hover_cols if c != "municipio"},
        mapbox_style="open-street-map",
        zoom=4.6,
        center={"lat": -13.2, "lon": -56.1},
        opacity=0.72,
        height=630,
        title=title,
    )
    fig.update_layout(margin={"r": 0, "t": 50, "l": 0, "b": 0})
    return fig


def find_lat_lon_cols(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    if df is None or df.empty:
        return None, None
    lat = first_col(df, ["latitude", "Latitude", "lat", "LATITUDE", "y"])
    lon = first_col(df, ["longitude", "Longitude", "lon", "LONGITUDE", "lng", "x"])
    return lat, lon


# =============================================================================
# Clima
# =============================================================================

def build_runtime_climate_association(wf: pd.DataFrame, climate_weekly: Optional[pd.DataFrame], selected_targets: list[str], selected_muns: list[str], max_lag: int = 4) -> pd.DataFrame:
    if climate_weekly is None or climate_weekly.empty or wf is None or wf.empty:
        return pd.DataFrame()

    cw = climate_weekly.copy()
    mc = first_col(cw, ["municipio", "Município", "Municipio"])
    yc = first_col(cw, ["epi_year", "ano", "year"])
    wc = first_col(cw, ["epi_week", "semana", "week"])
    if not mc or not yc or not wc:
        return pd.DataFrame()

    cw["municipio"] = cw[mc].map(norm_municipio)
    cw["epi_year"] = to_num(cw[yc])
    cw["epi_week"] = to_num(cw[wc])

    if selected_muns:
        cw = cw[cw["municipio"].isin(selected_muns)]
    if cw.empty:
        return pd.DataFrame()

    exclude = {norm_key(x) for x in ["municipio", mc, "epi_year", yc, "epi_week", wc, "ano", "semana", "periodo"]}
    climate_cols = []
    for c in cw.columns:
        if norm_key(c) in exclude:
            continue
        s = to_num(cw[c])
        if s.notna().sum() >= 10:
            cw[c] = s
            climate_cols.append(c)
    if not climate_cols:
        return pd.DataFrame()

    agg = wf.copy()
    if selected_targets:
        agg = agg[agg["target"].isin(selected_targets)]
    if selected_muns:
        agg = agg[agg["municipio"].isin(selected_muns)]
    if agg.empty:
        return pd.DataFrame()

    agg = agg.groupby(["municipio", "epi_year", "epi_week", "target"], as_index=False).agg(
        tests=("tests", "sum"),
        positives=("positives", "sum"),
        notificacoes=("notificacoes", "sum"),
        incidencia_100k=("incidencia_100k", "mean"),
    )
    agg["positividade"] = safe_div(agg["positives"], agg["tests"])

    rows = []
    indicators = ["tests", "positives", "positividade", "notificacoes", "incidencia_100k"]
    for target, dft in agg.groupby("target"):
        base = dft.merge(cw[["municipio", "epi_year", "epi_week"] + climate_cols], on=["municipio", "epi_year", "epi_week"], how="left")
        base = base.sort_values(["municipio", "epi_year", "epi_week"])
        for c in climate_cols[:40]:
            for lag in range(0, max_lag + 1):
                col_lag = f"{c}__lag{lag}"
                base[col_lag] = base.groupby("municipio")[c].shift(lag)
                for ind in indicators:
                    sub = base[[col_lag, ind]].dropna()
                    if len(sub) < 12 or sub[col_lag].nunique() < 2 or sub[ind].nunique() < 2:
                        continue
                    corr = sub[col_lag].corr(sub[ind], method="spearman")
                    if pd.isna(corr):
                        continue
                    rows.append({
                        "target": target,
                        "variavel_climatica": c,
                        "indicador": ind,
                        "lag_semanas": lag,
                        "correlacao_spearman": corr,
                        "abs_correlacao": abs(corr),
                        "n": len(sub),
                    })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["abs_correlacao", "n"], ascending=[False, False])


def sugerir_acao_operacional(row: pd.Series) -> str:
    """Linguagem operacional para gestores (risco / silêncio / utilização)."""
    pri = str(row.get("prioridade", "") or "").upper()
    silencio = bool(row.get("silencio_laboratorial", False))
    baixo = bool(row.get("baixo_uso_lacen", False))
    faixa = str(row.get("faixa_risco", "") or row.get("classificacao_silencio", "") or row.get("tipo_sinal", "")).lower()
    cls = str(row.get("classificacao_uso", "")).lower()

    if silencio or "silencio_critico" in faixa:
        return "Priorizar busca ativa e verificar fluxo de coleta/envio ao LACEN."
    if "silencio_provavel" in faixa or "silencio_moderado" in faixa:
        return "Sensibilizar vigilância municipal e revisar cobertura de testagem."
    if baixo or cls in {"baixo", "silencio"}:
        return "Avaliar subutilização da rede laboratorial e reforçar encaminhamento."
    if pri in {"CRÍTICO", "ALTO"} or faixa in {"alto_alerta", "alerta"}:
        return "Monitorar tendência, validar positivos e articular resposta municipal."
    if cls in {"adequado_ou_alto"}:
        return "Manter monitoramento de rotina."
    return "Acompanhar indicadores e reavaliar na próxima janela epidemiológica."


def with_acao(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["acao_sugerida"] = out.apply(sugerir_acao_operacional, axis=1)
    return out


# =============================================================================
# App
# =============================================================================

hero(
    "Sala de Situação Laboratorial Inteligente",
    "Monitoramento de exames, positividade, risco territorial, municípios silenciosos "
    "e utilização do LACEN, integrado a SINAN, SIM, CNES, clima e vulnerabilidade.",
    brand="SES-MT · CIEVS-MT · LACEN MT",
    org_line="Governo de Mato Grosso · Secretaria de Estado de Saúde",
    system_line="Sistema Inteligente de Monitoramento Laboratorial — LACEN MT",
    right_line="CIEVS / Vigilância Laboratorial",
    versao=VERSAO_DASHBOARD_LACEN,
)

with st.sidebar:
    st.markdown("### SES-MT · CIEVS · LACEN")
    st.caption("Painel institucional de vigilância laboratorial")
    folder = st.text_input("Pasta saida_pipeline", value="saida_pipeline")
    st.caption("Mantém leitura direta dos CSVs já produzidos.")

try:
    data, missing = load_data(folder)
except Exception as exc:
    st.error(f"Falha ao carregar dados de `{folder}`: {exc}")
    st.stop()

if missing:
    st.error("Arquivos obrigatórios ausentes em saida_pipeline: " + ", ".join(missing))
    st.info("Execute `rodar_lacen_sistema_completo_bases.bat` (opção 2 ou 3+4) para gerar as bases.")
    st.stop()

try:
    weekly = harmonize_weekly(data["weekly"])
except Exception as exc:
    st.error(f"Falha ao harmonizar série semanal: {exc}")
    st.stop()

alerts = data["alerts"].copy() if data["alerts"] is not None else pd.DataFrame()
annual = harmonize_annual(data["annual"]) if data["annual"] is not None else pd.DataFrame()
summary_mun = data["summary_mun"].copy() if data["summary_mun"] is not None else pd.DataFrame()
forecast = data["forecast"].copy() if data["forecast"] is not None else pd.DataFrame()
municipal_master = data["municipal_master"].copy() if data["municipal_master"] is not None else pd.DataFrame()
climate_weekly = data["climate_weekly"].copy() if data["climate_weekly"] is not None else pd.DataFrame()
climate_assoc = data["climate_assoc"].copy() if data["climate_assoc"] is not None else pd.DataFrame()
requests_demo = data["requests_demo"]
positivity_demo = data["positivity_demo"]
schema = data["schema"]
backlog = data["backlog"]
cnes_capacity = data["cnes_capacity"]
df_risco = data.get("municipios_risco")
df_silenciosos = data.get("municipios_silenciosos")
df_utilizacao = data.get("taxa_utilizacao")
df_ml_forecast = data.get("ml_forecast")
df_ml_anomalias = data.get("ml_anomalias")
df_ml_risco = data.get("ml_risco")
df_ml_silencio = data.get("ml_silencio")
df_sinan_weekly = data.get("sinan_weekly")
df_sim_weekly = data.get("sim_weekly")
if df_risco is None:
    df_risco = pd.DataFrame()
if df_silenciosos is None:
    df_silenciosos = pd.DataFrame()
if df_utilizacao is None:
    df_utilizacao = pd.DataFrame()
if df_ml_forecast is None:
    df_ml_forecast = pd.DataFrame()
if df_ml_anomalias is None:
    df_ml_anomalias = pd.DataFrame()
if df_ml_risco is None:
    df_ml_risco = pd.DataFrame()
if df_ml_silencio is None:
    df_ml_silencio = pd.DataFrame()
if df_sinan_weekly is None:
    df_sinan_weekly = pd.DataFrame()
if df_sim_weekly is None:
    df_sim_weekly = pd.DataFrame()

all_targets = sorted([str(x) for x in weekly["target"].dropna().unique() if str(x).lower() not in {"nan", "none", ""}])
all_muns = sorted([str(x) for x in weekly["municipio"].dropna().unique() if str(x).upper() not in {"NAN", "NONE", ""}])

valid_years = to_num(weekly["epi_year"]).dropna()
if valid_years.empty:
    min_year, max_year = 2010, 2026
else:
    min_year, max_year = int(valid_years.min()), int(valid_years.max())
years_available = sorted(valid_years.astype(int).unique().tolist()) if not valid_years.empty else [2026]
default_year = 2026 if 2026 in years_available else max_year

with st.sidebar:
    st.header("Análise do período")
    analysis_year = st.selectbox(
        "Ano de análise",
        years_available,
        index=years_available.index(default_year) if default_year in years_available else 0,
    )
    weeks_year = weekly.loc[weekly["epi_year"].eq(analysis_year), "epi_week"].dropna()
    latest_week = int(weeks_year.max()) if not weeks_year.empty else 1
    default_start = max(1, latest_week - 3)
    period_range = st.slider(
        "Período epidemiológico analisado",
        min_value=1,
        max_value=53,
        value=(default_start, latest_week),
        help="Escolha a janela de semanas para análise, comparação e alertas.",
    )
    week_start, week_end = int(period_range[0]), int(period_range[1])
    if week_end < week_start:
        week_start, week_end = week_end, week_start

    baseline_mode = st.selectbox(
        "Comparar com",
        ["Período imediatamente anterior", "Mesmo período do ano anterior", "Média histórica"],
        index=0,
    )
    baseline_year_start = st.number_input("Ano inicial do histórico", min_value=2010, max_value=max_year, value=min_year, step=1)
    baseline_year_end = st.number_input("Ano final do histórico", min_value=2010, max_value=max_year, value=min(max_year, analysis_year - 1) if analysis_year > min_year else min_year, step=1)
    if baseline_year_end < baseline_year_start:
        baseline_year_start, baseline_year_end = baseline_year_end, baseline_year_start

    horizon_days = st.selectbox("Horizonte dos alertas", [7, 14, 21, 28], index=0)

    st.divider()
    st.header("Agravos e municípios")
    mode = st.selectbox(
        "Grupo de agravos/alvos",
        [
            "Todos os agravos/alvos",
            "Seleção manual",
            "Arboviroses",
            "Respiratórios",
            "Tuberculose",
            "Hepatites",
            "Meningites",
        ],
        index=0,
    )
    if mode == "Seleção manual":
        selected_targets = st.multiselect("Selecionar agravos/alvos", all_targets, default=all_targets)
    else:
        selected_targets = detect_group_targets(all_targets, mode)
        if not selected_targets:
            selected_targets = all_targets
        st.caption(f"Agravos/alvos incluídos: {len(selected_targets)}")

    selected_muns = st.multiselect("Municípios", all_muns, default=[])

    st.divider()
    st.header("Mapas")
    user_geo_path = st.text_input("Malha municipal SHP/GeoJSON", value="")
    found_geo = find_geo_file(user_geo_path)
    if found_geo:
        st.caption(f"Malha detectada: {found_geo}")
    else:
        st.caption("Sem malha detectada. O painel usará pontos quando houver latitude/longitude.")

meta_bar(
    atualizado=date.today().isoformat(),
    periodo=f"{analysis_year} · SE{week_start:02d}–SE{week_end:02d}",
    fonte="LACEN/GAL · SINAN · SIM · CNES · clima · território",
    status="OK" if not missing else "ATENÇÃO",
)
wf = weekly[weekly["target"].isin(selected_targets)].copy()
if selected_muns:
    wf = wf[wf["municipio"].isin(selected_muns)]

period_df = build_period_analysis(
    weekly=weekly,
    analysis_year=int(analysis_year),
    week_start=int(week_start),
    week_end=int(week_end),
    baseline_mode=baseline_mode,
    baseline_year_start=int(baseline_year_start),
    baseline_year_end=int(baseline_year_end),
    selected_targets=selected_targets,
    selected_muns=selected_muns,
)
period_df = enrich_period_projection(period_df, int(horizon_days), int(week_start), int(week_end), int(analysis_year))
period_df = ensure_cols(
    period_df,
    {
        "municipio": "",
        "target": "",
        "prioridade": "MONITORAMENTO",
        "prioridade_score": 0.0,
        "cenario_operacional": "",
        "tests_periodo": 0.0,
        "positivos_periodo": 0.0,
        "positividade_periodo": np.nan,
        "notificacoes_periodo": 0.0,
        "obitos_sim_periodo": 0.0,
        "silencio_laboratorial": False,
        "baixo_uso_lacen": False,
        "acao_sugerida": "",
    },
)

manager_alerts = build_manager_alert_messages(period_df, folder, int(horizon_days))

if not manager_alerts.empty:
    outdir = Path(folder)
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        alert_path = outdir / f"alertas_gestores_periodo_{analysis_year}_SE{week_start:02d}_SE{week_end:02d}_proximos_{horizon_days}_dias.csv"
        manager_alerts.to_csv(alert_path, index=False, encoding="utf-8-sig")
    except Exception:
        alert_path = None
else:
    alert_path = None


tabs = st.tabs([
    "Visão executiva",
    "Monitoramento laboratorial",
    "Municípios prioritários",
    "Sinais de silêncio",
    "Utilização laboratorial",
    "Integração SINAN/SIM/CNES",
    "Alertas e recomendações",
    "Sinais preditivos",
    "Análise do período",
    "Alertas próximos dias",
    "Municípios e mapas",
    "Séries e predição",
    "Histórico anual",
    "Clima e ambiente",
    "Tabelas e qualidade",
])


# =============================================================================
# Aba 0: Visão executiva
# =============================================================================
with tabs[0]:
    st.subheader("Visão executiva — Sala de Situação Laboratorial")
    st.caption("Leitura rápida: volume, positividade, municípios ativos, silêncio e alto risco.")
    if period_df.empty:
        st.warning("Sem dados no período/filtros selecionados.")
    else:
        high_df = period_df[period_df["prioridade"].isin(["CRÍTICO", "ALTO"])]
        exames = float(period_df["tests_periodo"].sum()) if "tests_periodo" in period_df.columns else 0.0
        positivos = float(period_df["positivos_periodo"].sum()) if "positivos_periodo" in period_df.columns else 0.0
        pos_global = safe_div(positivos, exames)
        if "tests_periodo" in period_df.columns:
            mun_ativos = int(period_df.loc[period_df["tests_periodo"] > 0, "municipio"].nunique())
        else:
            mun_ativos = int(period_df["municipio"].nunique())

        if not df_silenciosos.empty:
            silencio_n = int(len(df_silenciosos))
        elif "silencio_laboratorial" in period_df.columns:
            silencio_n = int(period_df["silencio_laboratorial"].fillna(False).sum())
        else:
            silencio_n = 0

        if not df_risco.empty and "faixa_risco" in df_risco.columns:
            alto_risco_n = int(df_risco["faixa_risco"].astype(str).isin(["alerta", "alto_alerta", "atencao"]).sum())
        elif not df_risco.empty and "score_risco_territorial" in df_risco.columns:
            q = float(df_risco["score_risco_territorial"].quantile(0.75))
            alto_risco_n = int((df_risco["score_risco_territorial"] >= max(q, 0.5)).sum())
        else:
            alto_risco_n = int(len(high_df))

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Exames", format_int(exames))
        c2.metric("Positivos", format_int(positivos))
        c3.metric("Positividade", format_pct(pos_global))
        c4.metric("Municípios ativos", format_int(mun_ativos))
        c5.metric("Municípios silenciosos", format_int(silencio_n))
        c6.metric("Prioritários (atenção+)", format_int(alto_risco_n))

        st.markdown("##### Cinco principais alertas da janela")
        if "prioridade_score" in high_df.columns:
            top_alertas = with_acao(high_df.sort_values("prioridade_score", ascending=False).head(5))
        else:
            top_alertas = with_acao(high_df.head(5))
        if top_alertas.empty:
            st.info("Nenhum alerta crítico/alto na janela selecionada.")
        else:
            cols_alert = [c for c in [
                "prioridade", "municipio", "target", "cenario_operacional",
                "tests_periodo", "positividade_periodo", "acao_sugerida",
            ] if c in top_alertas.columns]
            show_table(top_alertas[cols_alert], "Cinco principais alertas", max_rows=5)

        if not df_risco.empty and "score_risco_territorial" in df_risco.columns:
            top_risco = with_acao(df_risco.head(10))
            if require_cols(top_risco, ["municipio", "score_risco_territorial"], "Municípios prioritários"):
                fig = px.bar(
                    top_risco.sort_values("score_risco_territorial"),
                    x="score_risco_territorial",
                    y="municipio",
                    color="faixa_risco" if "faixa_risco" in top_risco.columns else None,
                    orientation="h",
                    title="Top 10 municípios prioritários (risco territorial)",
                    labels={"score_risco_territorial": "Score de risco", "municipio": "Município"},
                )
                safe_plotly(fig, "Top risco territorial")
            with st.expander("Ver tabela dos municípios prioritários"):
                show_table(
                    top_risco[[c for c in [
                        "municipio", "faixa_risco", "score_risco_territorial",
                        "tests_8sem", "positives_8sem", "acao_sugerida",
                    ] if c in top_risco.columns]],
                    "Municípios prioritários",
                    max_rows=10,
                )
        else:
            st.info(
                "Arquivo `municipios_em_risco.csv` ainda não gerado. "
                "Rode `python lacen_integracao_final_only.py` para atualizar a inteligência territorial."
            )


# =============================================================================
# Aba 1: Monitoramento laboratorial
# =============================================================================
with tabs[1]:
    st.subheader("Monitoramento laboratorial")
    st.caption("Exames, positivos, positividade e ranking por agravo na janela selecionada.")
    if period_df.empty:
        st.warning("Sem dados no período/filtros selecionados.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Exames na janela", format_int(period_df["tests_periodo"].sum()) if "tests_periodo" in period_df.columns else "—")
        m2.metric("Positivos", format_int(period_df["positivos_periodo"].sum()) if "positivos_periodo" in period_df.columns else "—")
        if {"positivos_periodo", "tests_periodo"}.issubset(period_df.columns):
            m3.metric("Positividade", format_pct(safe_div(period_df["positivos_periodo"].sum(), period_df["tests_periodo"].sum())))
        else:
            m3.metric("Positividade", "—")
        m4.metric("Agravos monitorados", format_int(period_df["target"].nunique()) if "target" in period_df.columns else "—")

        by_tgt = period_df.groupby("target", as_index=False).agg(
            exames=("tests_periodo", "sum"),
            positivos=("positivos_periodo", "sum"),
        ).sort_values("exames", ascending=False).head(20)
        by_tgt["positividade"] = safe_div(by_tgt["positivos"], by_tgt["exames"])
        if require_cols(by_tgt, ["target", "exames"], "Exames por agravo"):
            fig = px.bar(
                by_tgt.sort_values("exames"),
                x="exames",
                y="target",
                orientation="h",
                title="Top 20 agravos/alvos por volume de exames",
                labels={"exames": "Exames", "target": "Agravo/alvo"},
            )
            safe_plotly(fig, "Exames por agravo")
        with st.expander("Tabela detalhada por agravo (top 20)"):
            show_table(by_tgt, "Monitoramento por agravo", max_rows=20)


# =============================================================================
# Aba 2: Municípios prioritários
# =============================================================================
with tabs[2]:
    st.subheader("Municípios prioritários — risco composto")
    if df_risco.empty:
        st.info("Sem `municipios_em_risco.csv`. Execute a integração final para gerar.")
        if not period_df.empty and require_cols(period_df, ["municipio", "prioridade_score"], "Risco derivado do período"):
            proxy = with_acao(period_df.groupby("municipio", as_index=False).agg(
                prioridade_score=("prioridade_score", "max"),
                tests_periodo=("tests_periodo", "sum"),
                positivos_periodo=("positivos_periodo", "sum"),
                notificacoes_periodo=("notificacoes_periodo", "sum"),
            ).sort_values("prioridade_score", ascending=False).head(50))
            show_table(proxy, "Proxy de risco a partir do período selecionado", max_rows=50)
    else:
        faixa = sorted([str(x) for x in df_risco.get("faixa_risco", pd.Series(dtype=str)).dropna().unique()])
        sel_faixa = st.multiselect("Faixa de risco", faixa, default=faixa, key="faixa_risco_tab")
        view = with_acao(df_risco.copy())
        if sel_faixa and "faixa_risco" in view.columns:
            view = view[view["faixa_risco"].astype(str).isin(sel_faixa)]
        m1, m2, m3 = st.columns(3)
        m1.metric("Municípios listados", format_int(len(view)))
        m2.metric("Score médio", format_num(view["score_risco_territorial"].mean()) if "score_risco_territorial" in view.columns else "—")
        m3.metric("Em alerta/alto", format_int(view["faixa_risco"].astype(str).isin(["alerta", "alto_alerta"]).sum()) if "faixa_risco" in view.columns else 0)
        topn = view.head(20)
        if require_cols(topn, ["municipio", "score_risco_territorial"], "Ranking de risco"):
            fig = px.bar(
                topn.sort_values("score_risco_territorial"),
                x="score_risco_territorial",
                y="municipio",
                color="faixa_risco" if "faixa_risco" in topn.columns else None,
                orientation="h",
                title="Ranking municipal de risco territorial (top 20)",
                labels={"score_risco_territorial": "Score de risco", "municipio": "Município"},
            )
            safe_plotly(fig, "Ranking de risco")
        with st.expander("Tabela de risco (limitada)"):
            show_table(
                view[[c for c in [
                    "municipio", "faixa_risco", "score_risco_territorial",
                    "tests_8sem", "positives_8sem", "notificacoes_8sem", "acao_sugerida",
                ] if c in view.columns]],
                "municipios_em_risco",
                max_rows=100,
            )


# =============================================================================
# Aba 3: Sinais de silêncio
# =============================================================================
with tabs[3]:
    st.subheader("Sinais de silêncio laboratorial")
    st.caption("Ausência de exame não significa ausência de risco — pode indicar falha de captação.")
    if df_silenciosos.empty:
        st.info("Sem `municipios_silenciosos.csv`. Usando sinais do período selecionado.")
        if not period_df.empty:
            mask = pd.Series(False, index=period_df.index)
            if "silencio_laboratorial" in period_df.columns:
                mask = mask | period_df["silencio_laboratorial"].fillna(False).astype(bool)
            if "baixo_uso_lacen" in period_df.columns:
                mask = mask | period_df["baixo_uso_lacen"].fillna(False).astype(bool)
            show_table(with_acao(period_df.loc[mask]).head(100), "Silêncio/baixo uso no período", max_rows=100)
    else:
        tipo_col = "classificacao_silencio" if "classificacao_silencio" in df_silenciosos.columns else "tipo_sinal"
        tipo = sorted([str(x) for x in df_silenciosos.get(tipo_col, pd.Series(dtype=str)).dropna().unique()])
        sel_tipo = st.multiselect("Classificação de silêncio", tipo, default=tipo, key="tipo_silencio_tab")
        view = with_acao(df_silenciosos.copy())
        if sel_tipo and tipo_col in view.columns:
            view = view[view[tipo_col].astype(str).isin(sel_tipo)]
        # Só filtra por agravo se a base de silêncio tiver target preenchido
        if selected_targets and "target" in view.columns:
            tgt_ok = view["target"].notna() & view["target"].astype(str).str.strip().ne("") & ~view["target"].astype(str).str.lower().isin(["nan", "none"])
            if bool(tgt_ok.any()):
                view = view[~tgt_ok | view["target"].isin(selected_targets)]
        s1, s2, s3 = st.columns(3)
        s1.metric("Municípios silenciosos", format_int(view["municipio"].nunique() if "municipio" in view.columns else len(view)))
        notif_col = "notif_recent" if "notif_recent" in view.columns else ("notificacoes" if "notificacoes" in view.columns else None)
        s2.metric("Notificações recentes", format_int(view[notif_col].fillna(0).sum()) if notif_col else "—")
        s3.metric(
            "Críticos",
            format_int((view.get(tipo_col, pd.Series(dtype=str)).astype(str) == "silencio_critico").sum())
            if tipo_col in view.columns else 0,
        )
        cols_show = [c for c in [
            "municipio", "classificacao_silencio", "tipo_sinal", "score_silencio",
            "tests_recent", "notif_recent", "tests_hist", "notif_hist",
            "populacao", "indice_vulnerabilidade", "acao_sugerida",
        ] if c in view.columns]
        with st.expander("Tabela de municípios silenciosos (limitada)"):
            show_table(view[cols_show].head(100) if cols_show else view.head(100), "municipios_silenciosos", max_rows=100)


# =============================================================================
# Aba 4: Utilização laboratorial
# =============================================================================
with tabs[4]:
    st.subheader("Utilização laboratorial do LACEN")
    st.caption("Exames/notificação e exames por 100 mil habitantes.")
    if df_utilizacao.empty:
        st.info("Sem `taxa_utilizacao_lacen.csv`. Execute a integração final.")
        if not period_df.empty:
            u = with_acao(period_df.copy())
            u["taxa_utilizacao_periodo"] = safe_div(u["tests_periodo"], u["notificacoes_periodo"].replace(0, np.nan))
            show_table(
                u[[c for c in [
                    "municipio", "target", "tests_periodo", "notificacoes_periodo",
                    "taxa_utilizacao_periodo", "baixo_uso_lacen", "acao_sugerida",
                ] if c in u.columns]].head(100),
                "Utilização no período (proxy)",
                max_rows=100,
            )
    else:
        view = with_acao(df_utilizacao.copy())
        if selected_targets and "target" in view.columns:
            view = view[view["target"].isin(selected_targets)]
        classes = sorted([str(x) for x in view.get("classificacao_uso", pd.Series(dtype=str)).dropna().unique()])
        sel_cls = st.multiselect("Classificação de uso", classes, default=classes, key="cls_uso_tab")
        if sel_cls and "classificacao_uso" in view.columns:
            view = view[view["classificacao_uso"].astype(str).isin(sel_cls)]
        u1, u2, u3 = st.columns(3)
        u1.metric("Pares município-alvo", format_int(len(view)))
        u2.metric("Mediana exames/100 mil", format_num(view["exames_por_100k"].median()) if "exames_por_100k" in view.columns else "—")
        u3.metric(
            "Baixo uso / silêncio",
            format_int(view["classificacao_uso"].astype(str).isin(["baixo", "silencio"]).sum())
            if "classificacao_uso" in view.columns else 0,
        )
        if "classificacao_uso" in view.columns:
            dist = view["classificacao_uso"].astype(str).value_counts().reset_index()
            dist.columns = ["classificacao_uso", "registros"]
            fig = px.bar(
                dist,
                x="registros",
                y="classificacao_uso",
                orientation="h",
                title="Distribuição da classificação de uso do LACEN",
                labels={"registros": "Registros", "classificacao_uso": "Classificação"},
            )
            safe_plotly(fig, "Classificação de uso")
        with st.expander("Tabela de utilização (top 100)"):
            show_table(
                view.head(100)[[c for c in [
                    "municipio", "target", "tests", "notificacoes", "taxa_utilizacao",
                    "exames_por_100k", "classificacao_uso", "acao_sugerida",
                ] if c in view.columns]],
                "taxa_utilizacao_lacen",
                max_rows=100,
            )


# =============================================================================
# Aba 5: Integração SINAN / SIM / CNES
# =============================================================================
with tabs[5]:
    st.subheader("Integração LACEN × SINAN × SIM × CNES")
    st.caption("Compara exames, notificações, óbitos e capacidade instalada no território.")
    if period_df.empty:
        st.warning("Sem dados no período/filtros selecionados.")
    else:
        exames = float(period_df["tests_periodo"].sum()) if "tests_periodo" in period_df.columns else 0.0
        notif = float(period_df["notificacoes_periodo"].sum()) if "notificacoes_periodo" in period_df.columns else 0.0
        obitos = float(period_df["obitos_sim_periodo"].sum()) if "obitos_sim_periodo" in period_df.columns else 0.0

        # Fonte direta SINAN (não depende do join por alvo laboratorial)
        sinan_periodo = 0.0
        if not df_sinan_weekly.empty:
            sw = df_sinan_weekly.copy()
            sw["epi_year"] = to_num(sw.get("epi_year", pd.Series(dtype=float)))
            sw["epi_week"] = to_num(sw.get("epi_week", pd.Series(dtype=float)))
            ncol = first_col(sw, ["notificacoes_sinan", "notificacoes"])
            if ncol:
                sw[ncol] = to_num(sw[ncol])
                mask = sw["epi_year"].eq(analysis_year) & sw["epi_week"].between(week_start, week_end)
                sinan_periodo = float(sw.loc[mask, ncol].fillna(0).sum())
                if sinan_periodo > notif:
                    notif = sinan_periodo

        sim_ok = False
        if not df_sim_weekly.empty:
            sy = to_num(df_sim_weekly.get("epi_year", pd.Series(dtype=float)))
            sim_ok = bool((sy.fillna(0) > 1900).any())
            if sim_ok:
                sm = df_sim_weekly.copy()
                sm["epi_year"] = to_num(sm["epi_year"])
                sm["epi_week"] = to_num(sm["epi_week"])
                ocol = first_col(sm, ["obitos_sim", "obitos"])
                if ocol:
                    mask = sm["epi_year"].eq(analysis_year) & sm["epi_week"].between(week_start, week_end)
                    obitos = float(to_num(sm.loc[mask, ocol]).fillna(0).sum())

        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Exames LACEN", format_int(exames))
        i2.metric("Notificações SINAN", format_int(notif))
        i3.metric("Óbitos SIM", format_int(obitos) if sim_ok else "—")
        i4.metric("Exames / notificação", format_num(safe_div(exames, notif)) if notif else "—")
        if not sim_ok:
            st.caption("SIM: arquivo sem anos epidemiológicos válidos — reconstruir `sim_weekly_municipio.csv` no pipeline.")

        integ = period_df.groupby("municipio", as_index=False).agg(
            exames=("tests_periodo", "sum") if "tests_periodo" in period_df.columns else ("municipio", "size"),
            positivos=("positivos_periodo", "sum") if "positivos_periodo" in period_df.columns else ("municipio", "size"),
            notificacoes=("notificacoes_periodo", "sum") if "notificacoes_periodo" in period_df.columns else ("municipio", "size"),
            obitos_sim=("obitos_sim_periodo", "sum") if "obitos_sim_periodo" in period_df.columns else ("municipio", "size"),
        )

        # Complementa notificações por município a partir do SINAN semanal
        if not df_sinan_weekly.empty:
            sw = df_sinan_weekly.copy()
            sw["epi_year"] = to_num(sw.get("epi_year", pd.Series(dtype=float)))
            sw["epi_week"] = to_num(sw.get("epi_week", pd.Series(dtype=float)))
            mun_s = first_col(sw, ["municipio", "Município"])
            ncol = first_col(sw, ["notificacoes_sinan", "notificacoes"])
            if mun_s and ncol:
                sw = sw[sw["epi_year"].eq(analysis_year) & sw["epi_week"].between(week_start, week_end)].copy()
                sw["municipio"] = sw[mun_s].map(norm_municipio)
                sw[ncol] = to_num(sw[ncol])
                by_mun = sw.groupby("municipio", as_index=False).agg(notificacoes_sinan=(ncol, "sum"))
                integ = integ.merge(by_mun, on="municipio", how="outer")
                integ["exames"] = integ["exames"].fillna(0)
                integ["positivos"] = integ["positivos"].fillna(0)
                integ["notificacoes"] = integ["notificacoes"].fillna(0)
                integ["notificacoes"] = np.maximum(integ["notificacoes"], integ["notificacoes_sinan"].fillna(0))
                integ["obitos_sim"] = integ["obitos_sim"].fillna(0)

        integ["exames_por_notif"] = safe_div(integ["exames"], integ["notificacoes"].replace(0, np.nan))
        integ["gap_sinan_sem_exame"] = (integ["notificacoes"].fillna(0) > 0) & (integ["exames"].fillna(0) == 0)

        cnes_df = cnes_capacity.copy() if cnes_capacity is not None and not getattr(cnes_capacity, "empty", True) else pd.DataFrame()
        if not cnes_df.empty:
            mun_c = first_col(cnes_df, ["municipio", "Município", "Municipio"])
            if mun_c:
                cnes_df = cnes_df.copy()
                cnes_df["municipio"] = cnes_df[mun_c].map(norm_municipio)
                keep_cnes = [c for c in [
                    "municipio", "cnes_estabelecimentos", "cnes_leitos_total", "cnes_leitos_sus",
                    "cnes_leitos_uti", "cnes_equipes_esf", "cnes_equipamentos_criticos",
                ] if c in cnes_df.columns]
                integ = integ.merge(cnes_df[keep_cnes], on="municipio", how="left")

        c1, c2, c3 = st.columns(3)
        c1.metric("Municípios com gap SINAN (sem exame)", format_int(integ["gap_sinan_sem_exame"].sum()))
        if not cnes_df.empty and "cnes_estabelecimentos" in cnes_df.columns:
            c2.metric("Municípios com CNES", format_int(cnes_df["municipio"].nunique() if "municipio" in cnes_df.columns else len(cnes_df)))
            c3.metric(
                "Mediana estabelecimentos CNES",
                format_num(pd.to_numeric(cnes_df["cnes_estabelecimentos"], errors="coerce").median()),
            )
            st.caption("Nota: valores absolutos de CNES dependem da qualidade do cadastro consolidado; use mediana e ranking, não a soma bruta.")
        else:
            c2.metric("CNES", "não carregado")
            c3.metric("Estabelecimentos", "—")

        if float(notif) == 0 and float(obitos) == 0:
            st.info(
                "SINAN/SIM zerados nesta janela epidemiológica (SE selecionada). "
                "Amplie o período na barra lateral ou atualize a integração com bases mais recentes."
            )

        top_gap = integ[integ["gap_sinan_sem_exame"]].sort_values("notificacoes", ascending=False).head(20)
        if not top_gap.empty and require_cols(top_gap, ["municipio", "notificacoes"], "Gap SINAN"):
            fig = px.bar(
                top_gap.sort_values("notificacoes"),
                x="notificacoes",
                y="municipio",
                orientation="h",
                title="Top 20 — notificações SINAN sem exame LACEN no período",
                labels={"notificacoes": "Notificações", "municipio": "Município"},
            )
            safe_plotly(fig, "Gap SINAN sem exame")

        if {"exames", "notificacoes"}.issubset(integ.columns):
            scatter = integ[(integ["exames"] > 0) | (integ["notificacoes"] > 0)].copy()
            scatter = scatter.head(200)
            if not scatter.empty:
                size_col = None
                if "obitos_sim" in scatter.columns and float(scatter["obitos_sim"].fillna(0).sum()) > 0:
                    scatter["_size"] = scatter["obitos_sim"].fillna(0).clip(lower=0) + 1
                    size_col = "_size"
                fig = px.scatter(
                    scatter,
                    x="notificacoes",
                    y="exames",
                    size=size_col,
                    hover_name="municipio",
                    title="Exames LACEN vs notificações SINAN"
                    + (" (tamanho ≈ óbitos SIM)" if size_col else ""),
                    labels={"notificacoes": "Notificações SINAN", "exames": "Exames LACEN"},
                )
                safe_plotly(fig, "LACEN vs SINAN")

        integ_view = with_acao(integ.sort_values(["gap_sinan_sem_exame", "notificacoes"], ascending=[False, False]))
        with st.expander("Tabela integrada municipal (top 100)"):
            show_table(
                integ_view.head(100)[[c for c in [
                    "municipio", "exames", "positivos", "notificacoes", "obitos_sim",
                    "exames_por_notif", "gap_sinan_sem_exame",
                    "cnes_estabelecimentos", "cnes_leitos_sus", "cnes_equipes_esf", "acao_sugerida",
                ] if c in integ_view.columns]],
                "integracao_sinan_sim_cnes",
                max_rows=100,
            )


# =============================================================================
# Aba 6: Alertas e recomendações
# =============================================================================
with tabs[6]:
    st.subheader("Alertas e recomendações operacionais")
    if manager_alerts.empty and (alerts is None or alerts.empty):
        st.info("Nenhum alerta disponível para os filtros atuais.")
    else:
        if not manager_alerts.empty:
            st.markdown("#### Fila operacional do período")
            a1, a2, a3 = st.columns(3)
            a1.metric("Alertas gestores", format_int(len(manager_alerts)))
            a2.metric("Críticos", format_int((manager_alerts["prioridade"] == "CRÍTICO").sum()) if "prioridade" in manager_alerts.columns else 0)
            a3.metric("Municípios", format_int(manager_alerts["municipio"].nunique()) if "municipio" in manager_alerts.columns else 0)
            with st.expander("Tabela de alertas gestores"):
                show_table(with_acao(manager_alerts).head(100), "Alertas gestores (período)", max_rows=100)
        if alerts is not None and not alerts.empty:
            st.markdown("#### Alertas integrados semanais (pipeline)")
            al = alerts.copy()
            tgt = first_col(al, ["target", "alvo", "agravo"])
            mun = first_col(al, ["municipio", "Município", "Municipio"])
            if tgt and selected_targets:
                al = al[al[tgt].astype(str).isin(selected_targets)]
            if mun and selected_muns:
                al = al[al[mun].map(norm_municipio).isin(selected_muns)]
            level = first_col(al, ["alert_level", "nivel_risco", "nivel_alerta"])
            if level:
                fig = px.histogram(al, x=level, title="Distribuição de níveis de alerta integrado")
                safe_plotly(fig, "Níveis de alerta")
            with st.expander("Tabela de alertas do pipeline (amostra)"):
                show_table(al.head(100), "integrated_alerts (filtrado)", max_rows=100)


# =============================================================================
# Aba 7: Sinais preditivos (ML)
# =============================================================================
with tabs[7]:
    st.subheader("Sinais preditivos — módulo ML baseline")
    st.caption(
        "Modelos: forecast EWMA + anomalias; risco/silêncio usam sklearn (Gradient Boosting) "
        "quando `ml/models_store` estiver disponível, senão baseline logística. "
        "Resultados em `saida_pipeline` — não treinam no DW."
    )
    ml_missing = all(df.empty for df in (df_ml_forecast, df_ml_anomalias, df_ml_risco, df_ml_silencio))
    if ml_missing:
        st.info(
            "Arquivos ML ainda não gerados. Rode: "
            "`python -m ml.run_ml_pipeline --outdir saida_pipeline`"
        )
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Séries forecast", format_int(len(df_ml_forecast)))
        k2.metric("Anomalias", format_int(len(df_ml_anomalias)))
        alto_r = int(df_ml_risco["faixa_predita"].astype(str).isin(["alto", "muito_alto"]).sum()) if not df_ml_risco.empty and "faixa_predita" in df_ml_risco.columns else 0
        k3.metric("Risco alto/muito alto", format_int(alto_r))
        crit_s = int((df_ml_silencio.get("faixa_silencio_predita", pd.Series(dtype=str)).astype(str) == "silencio_critico").sum()) if not df_ml_silencio.empty else 0
        k4.metric("Silêncio crítico predito", format_int(crit_s))

        st.markdown("##### Previsão de demanda (estadual por agravo)")
        if df_ml_forecast.empty:
            st.caption("Sem `ml_forecast_demanda.csv`.")
        else:
            fc = df_ml_forecast.copy()
            if selected_targets and "target" in fc.columns:
                fc = fc[fc["target"].isin(selected_targets)]
            # Limita legenda: top N agravos por volume previsto
            top_n_fc = st.slider("Agravos no gráfico de forecast", 5, 20, 8, key="top_n_forecast")
            top_targets: list[str] = []
            if {"target", "forecast_tests"}.issubset(fc.columns):
                rank = (
                    fc.groupby("target", as_index=False)["forecast_tests"]
                    .max()
                    .sort_values("forecast_tests", ascending=False)
                )
                top_targets = rank["target"].head(int(top_n_fc)).tolist()
                fc_plot = fc[fc["target"].isin(top_targets)].copy()
            else:
                fc_plot = fc
            if require_cols(fc_plot, ["target", "forecast_step", "forecast_tests"], "Forecast ML"):
                fig = px.line(
                    fc_plot.sort_values(["target", "forecast_step"]),
                    x="forecast_step",
                    y="forecast_tests",
                    color="target",
                    markers=True,
                    title=f"Exames previstos — top {max(len(top_targets), 1)} agravos (EWMA)",
                    labels={"forecast_step": "Semanas à frente", "forecast_tests": "Exames previstos", "target": "Agravo"},
                )
                safe_plotly(fig, "Forecast demanda")
            with st.expander("Tabela de forecast (completa filtrada)"):
                show_table(fc.head(100), "ml_forecast_demanda", max_rows=100)

        st.markdown("##### Anomalias detectadas")
        if df_ml_anomalias.empty:
            st.caption("Nenhuma anomalia na última semana / arquivo ausente.")
        else:
            an = df_ml_anomalias.copy()
            if selected_targets and "target" in an.columns:
                an = an[an["target"].isin(selected_targets)]
            if selected_muns and "municipio" in an.columns:
                an = an[an["municipio"].map(norm_municipio).isin(selected_muns)]
            show_table(an.head(50), "Top anomalias", max_rows=50)

        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown("##### Risco predito (top 20)")
            if df_ml_risco.empty:
                st.caption("Sem `ml_risco_predito.csv`.")
            else:
                rr = df_ml_risco.copy()
                if selected_targets and "target" in rr.columns:
                    rr = rr[rr["target"].isin(selected_targets)]
                top_rr = rr.head(20)
                if require_cols(top_rr, ["municipio", "prob_alerta_proxima_janela"], "Risco predito"):
                    fig = px.bar(
                        top_rr.sort_values("prob_alerta_proxima_janela"),
                        x="prob_alerta_proxima_janela",
                        y="municipio",
                        color="faixa_predita" if "faixa_predita" in top_rr.columns else None,
                        orientation="h",
                        title="Probabilidade de alerta — próxima janela",
                        labels={"prob_alerta_proxima_janela": "Probabilidade", "municipio": "Município"},
                    )
                    safe_plotly(fig, "Risco predito")
                with st.expander("Tabela risco predito"):
                    show_table(
                        rr.head(50)[[c for c in ["municipio", "target", "prob_alerta_proxima_janela", "faixa_predita", "acao_sugerida"] if c in rr.columns]],
                        "ml_risco_predito",
                        max_rows=50,
                    )
        with c_b:
            st.markdown("##### Silêncio predito (top 20)")
            if df_ml_silencio.empty:
                st.caption("Sem `ml_silencio_predito.csv`.")
            else:
                ss = df_ml_silencio.copy()
                if selected_targets and "target" in ss.columns:
                    ss = ss[ss["target"].isin(selected_targets)]
                top_ss = ss.head(20)
                if require_cols(top_ss, ["municipio", "prob_silencio_proxima_janela"], "Silêncio predito"):
                    fig = px.bar(
                        top_ss.sort_values("prob_silencio_proxima_janela"),
                        x="prob_silencio_proxima_janela",
                        y="municipio",
                        color="faixa_silencio_predita" if "faixa_silencio_predita" in top_ss.columns else None,
                        orientation="h",
                        title="Probabilidade de silêncio — próxima janela",
                        labels={"prob_silencio_proxima_janela": "Probabilidade", "municipio": "Município"},
                    )
                    safe_plotly(fig, "Silêncio predito")
                with st.expander("Tabela silêncio predito"):
                    show_table(
                        ss.head(50)[[c for c in ["municipio", "target", "prob_silencio_proxima_janela", "faixa_silencio_predita", "acao_sugerida"] if c in ss.columns]],
                        "ml_silencio_predito",
                        max_rows=50,
                    )


# =============================================================================
# Aba 8: período (detalhada)
# =============================================================================
with tabs[8]:
    st.subheader("Análise do período selecionado")
    st.markdown(
        f"**Período:** {analysis_year}-SE{week_start:02d} a SE{week_end:02d}  \n"
        f"**Comparação:** {baseline_mode}  \n"
        f"**Horizonte prospectivo dos alertas:** próximos {horizon_days} dias"
    )

    if period_df.empty:
        st.warning("Sem dados para o período/filtros selecionados.")
    else:
        high_df = period_df[period_df["prioridade"].isin(["CRÍTICO", "ALTO"])]
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Agravos no período", format_int(period_df["target"].nunique()))
        c2.metric("Municípios no período", format_int(period_df["municipio"].nunique()))
        c3.metric("Solicitações LACEN", format_int(period_df["tests_periodo"].sum()))
        c4.metric("Positivos", format_int(period_df["positivos_periodo"].sum()))
        pos_global = period_df["positivos_periodo"].sum() / period_df["tests_periodo"].sum() if period_df["tests_periodo"].sum() else np.nan
        c5.metric("Positividade global", format_pct(pos_global))
        c6.metric("Alertas crítico/alto", format_int(len(high_df)))

        resumo = period_df.groupby("prioridade", as_index=False).agg(
            registros=("target", "size"),
            municipios=("municipio", "nunique"),
            agravos=("target", "nunique"),
            tests_periodo=("tests_periodo", "sum"),
            positivos_periodo=("positivos_periodo", "sum"),
            notificacoes_periodo=("notificacoes_periodo", "sum"),
            projecao_solicitacoes=("projecao_solicitacoes_proximos_dias", "sum"),
            projecao_positivos=("projecao_positivos_proximos_dias", "sum"),
        )
        order = pd.CategoricalDtype(["CRÍTICO", "ALTO", "MODERADO", "MONITORAMENTO"], ordered=True)
        resumo["prioridade"] = resumo["prioridade"].astype(order)
        resumo = resumo.sort_values("prioridade")
        st.dataframe(resumo, use_container_width=True)

        top = period_df.head(40).copy()
        fig = px.bar(
            top.sort_values("prioridade_score"),
            x="prioridade_score",
            y="municipio",
            color="prioridade",
            orientation="h",
            hover_data=[
                "target", "cenario_operacional", "tests_periodo", "positivos_periodo",
                "positividade_periodo", "delta_positividade_pp", "delta_tests_abs",
                "notificacoes_periodo", "projecao_solicitacoes_proximos_dias",
            ],
            title="Top sinais operacionais do período",
            labels={"prioridade_score": "Prioridade", "municipio": "Município"},
        )
        st.plotly_chart(fig, use_container_width=True)

        scenario = period_df.groupby("cenario_operacional", as_index=False).agg(
            registros=("target", "size"),
            municipios=("municipio", "nunique"),
            agravos=("target", "nunique"),
            tests_periodo=("tests_periodo", "sum"),
            positivos_periodo=("positivos_periodo", "sum"),
        ).sort_values("registros", ascending=False)
        fig2 = px.bar(
            scenario,
            x="registros",
            y="cenario_operacional",
            orientation="h",
            title="Distribuição dos cenários operacionais",
            labels={"registros": "Registros", "cenario_operacional": "Cenário"},
        )
        fig2.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig2, use_container_width=True)

        cols = [
            "prioridade", "municipio", "target", "periodo_analise", "periodo_base", "cenario_operacional",
            "tests_periodo", "tests_base", "delta_tests_abs", "delta_tests_pct",
            "positivos_periodo", "positivos_base", "positividade_periodo", "positividade_base", "delta_positividade_pp",
            "notificacoes_periodo", "notificacoes_base", "delta_notificacoes_abs",
            "silencio_laboratorial", "baixo_uso_lacen", "projecao_solicitacoes_proximos_dias",
            "projecao_positivos_proximos_dias", "janela_alerta_proximos_dias",
        ]
        show_table(period_df[[c for c in cols if c in period_df.columns]], "Tabela analítica do período", max_rows=1000)


# =============================================================================
# Aba 9: alertas próximos dias
# =============================================================================
with tabs[9]:
    st.subheader("Alertas para os próximos dias")

    if manager_alerts.empty:
        st.info("Nenhum alerta crítico/alto/moderado no período/filtros atuais.")
    else:
        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("Alertas para validação", format_int(len(manager_alerts)))
        a2.metric("Municípios", format_int(manager_alerts["municipio"].nunique()))
        a3.metric("Agravos/alvos", format_int(manager_alerts["target"].nunique()))
        a4.metric("Críticos", format_int((manager_alerts["prioridade"] == "CRÍTICO").sum()))
        a5.metric("Horizonte", f"{horizon_days} dias")

        if alert_path:
            st.success(f"Arquivo operacional gerado: {alert_path}")

        priority_filter = st.multiselect(
            "Prioridade",
            ["CRÍTICO", "ALTO", "MODERADO"],
            default=["CRÍTICO", "ALTO", "MODERADO"],
        )
        target_filter_alert = st.multiselect(
            "Filtrar agravos dos alertas",
            sorted(manager_alerts["target"].dropna().astype(str).unique().tolist()),
            default=[],
        )

        msg_df = manager_alerts[manager_alerts["prioridade"].isin(priority_filter)].copy()
        if target_filter_alert:
            msg_df = msg_df[msg_df["target"].isin(target_filter_alert)]

        st.markdown("#### Mensagens prontas para validação técnica")
        for _, row in msg_df.head(20).iterrows():
            with st.expander(f"{row['prioridade']} — {row['municipio']} — {row['target']}"):
                st.markdown(f"**Assunto:** {row['assunto_email']}")
                st.write(row["mensagem_gestor"])
                st.markdown(f"**Ação sugerida:** {row['acao_sugerida']}")
                st.markdown(f"**Canal sugerido:** {row['canal_sugerido']}")

        show_table(msg_df, "Fila de alertas para gestores", max_rows=2000)


# =============================================================================
# Aba 10: municípios e mapas
# =============================================================================
with tabs[10]:
    st.subheader("Municípios e mapas por agravo/alvo")
    st.caption("Mapas só são renderizados após selecionar o agravo e confirmar abaixo (reduz carga inicial).")

    if period_df.empty:
        st.warning("Sem dados para mapa no período/filtro atual.")
    else:
        map_targets = sorted(period_df["target"].dropna().astype(str).unique().tolist())
        map_target = st.selectbox("Agravo/alvo para o mapa", map_targets, index=0)
        map_metric = st.selectbox(
            "Indicador do mapa",
            [
                "prioridade_score",
                "positividade_periodo",
                "delta_positividade_pp",
                "tests_periodo",
                "delta_tests_abs",
                "notificacoes_periodo",
                "projecao_solicitacoes_proximos_dias",
                "projecao_positivos_proximos_dias",
                "solicitacoes_periodo_100k",
            ],
            index=0,
        )
        render_map = st.checkbox("Renderizar mapa agora", value=False, key="render_map_now")
        map_df = period_df[period_df["target"].astype(str).eq(map_target)].copy()
        if not render_map:
            st.info("Selecione o agravo/indicador e marque **Renderizar mapa agora** para carregar a malha.")
            with st.expander("Prévia tabular do agravo (sem mapa)"):
                show_table(map_df.head(50), "Prévia municipal", max_rows=50)
        else:
            geojson = None
            props_df = pd.DataFrame()
            if found_geo:
                geojson, props_df, geo_msg = load_geojson_or_shp(str(found_geo))
                st.caption(geo_msg)

            if geojson is not None and not props_df.empty:
                merged = join_shape_with_period(props_df, map_df)
                fig = make_choropleth(
                    geojson,
                    merged,
                    map_metric,
                    f"Mapa municipal — {map_target} | {map_metric} | {analysis_year}-SE{week_start:02d} a SE{week_end:02d}",
                )
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("A malha foi carregada, mas não foi possível cruzar os municípios com os dados do dashboard.")
                    show_table(map_df, "Tabela usada no mapa")
            else:
                if municipal_master is None or municipal_master.empty:
                    st.info("Sem shapefile/GeoJSON e sem municipal_master.csv para mapa de pontos.")
                    show_table(map_df, "Tabela municipal filtrada")
                else:
                    mm = municipal_master.copy()
                    mc = first_col(mm, ["municipio", "Município", "Municipio"])
                    if mc and mc != "municipio":
                        mm["municipio"] = mm[mc].map(norm_municipio)
                    elif "municipio" in mm.columns:
                        mm["municipio"] = mm["municipio"].map(norm_municipio)
                    lat_col, lon_col = find_lat_lon_cols(mm)
                    if not lat_col or not lon_col:
                        st.info("Sem shapefile/GeoJSON e sem latitude/longitude em municipal_master.csv.")
                        show_table(map_df, "Tabela municipal filtrada")
                    else:
                        mm[lat_col] = to_num(mm[lat_col])
                        mm[lon_col] = to_num(mm[lon_col])
                        plot = map_df.merge(mm[["municipio", lat_col, lon_col]], on="municipio", how="left")
                        plot = plot.dropna(subset=[lat_col, lon_col])
                        plot = safe_marker_size(plot, map_metric, "marker_size", 7, 24)
                        fig = px.scatter_mapbox(
                            plot,
                            lat=lat_col,
                            lon=lon_col,
                            color=map_metric,
                            size="marker_size",
                            hover_name="municipio",
                            hover_data={
                                "target": True,
                                "prioridade": True,
                                "cenario_operacional": True,
                                "tests_periodo": True,
                                "positividade_periodo": ":.1%",
                                "delta_positividade_pp": ":.2f",
                                "projecao_solicitacoes_proximos_dias": ":.1f",
                                "marker_size": False,
                                lat_col: False,
                                lon_col: False,
                            },
                            mapbox_style="open-street-map",
                            zoom=4.6,
                            center={"lat": -13.2, "lon": -56.1},
                            height=630,
                            title=f"Mapa de pontos — {map_target} | {map_metric}",
                        )
                        st.plotly_chart(fig, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                show_table(
                    map_df.sort_values(["prioridade_score", map_metric], ascending=[False, False]).head(50),
                    "Municípios do agravo selecionado",
                    max_rows=50,
                )
            with col_b:
                silent = map_df[(map_df["silencio_laboratorial"]) | (map_df["baixo_uso_lacen"])]
                show_table(silent.head(50), "Silêncio laboratorial ou baixo uso do LACEN", max_rows=50)


# =============================================================================
# Aba 11: séries e predição
# =============================================================================
with tabs[11]:
    st.subheader("Séries históricas e predição operacional curta")

    hist_targets = sorted(wf["target"].dropna().astype(str).unique().tolist())
    chosen_hist_targets = st.multiselect(
        "Agravos/alvos para série histórica",
        hist_targets,
        default=hist_targets[: min(6, len(hist_targets))],
    )
    metric = st.selectbox(
        "Indicador da série",
        ["tests", "positives", "positividade", "notificacoes", "obitos_sim", "incidencia_100k"],
        index=2,
    )
    hist_year_range = st.slider("Intervalo de anos da série", min_year, max_year, (min_year, max_year))

    hist = wf.copy()
    if chosen_hist_targets:
        hist = hist[hist["target"].isin(chosen_hist_targets)]
    hist = hist[hist["epi_year"].between(hist_year_range[0], hist_year_range[1])]

    if hist.empty:
        st.info("Sem série histórica para o filtro atual.")
    else:
        agg_hist = hist.groupby(["epi_year", "epi_week", "periodo", "target"], as_index=False).agg(
            tests=("tests", "sum"),
            positives=("positives", "sum"),
            notificacoes=("notificacoes", "sum"),
            obitos_sim=("obitos_sim", "sum"),
            incidencia_100k=("incidencia_100k", "mean"),
        )
        agg_hist["positividade"] = safe_div(agg_hist["positives"], agg_hist["tests"])
        agg_hist["periodo_data"] = [iso_monday(y, w) for y, w in zip(agg_hist["epi_year"], agg_hist["epi_week"])]

        fig = px.line(
            agg_hist.sort_values(["target", "periodo_data"]),
            x="periodo_data",
            y=metric,
            color="target",
            markers=False,
            title=f"Série histórica semanal — {metric}",
            labels={"periodo_data": "Semana epidemiológica", metric: metric, "target": "Agravo/alvo"},
        )
        if metric == "positividade":
            fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

        pred = period_df[period_df["target"].isin(chosen_hist_targets)] if chosen_hist_targets else period_df
        pred_cols = [
            "prioridade", "municipio", "target", "periodo_analise", "cenario_operacional",
            "projecao_solicitacoes_proximos_dias", "projecao_positivos_proximos_dias",
            "positividade_projetada_proximos_dias", "janela_alerta_proximos_dias",
        ]
        show_table(pred[[c for c in pred_cols if c in pred.columns]].head(500), "Projeção operacional para próximos dias", max_rows=500)

    if forecast is not None and not forecast.empty:
        st.markdown("#### Forecast integrado existente")
        fc = forecast.copy()
        ft = first_col(fc, ["target", "alvo", "agravo"])
        fy = first_col(fc, ["epi_year", "ano", "year"])
        fw = first_col(fc, ["epi_week", "semana", "week"])
        if ft and ft != "target":
            fc["target"] = fc[ft]
        if fy and fy != "epi_year":
            fc["epi_year"] = to_num(fc[fy])
        if fw and fw != "epi_week":
            fc["epi_week"] = to_num(fc[fw])
        value_candidates = [
            "predicted_tests", "forecast_tests", "tests_pred", "testes_previstos",
            "predicted", "forecast", "valor_previsto", "yhat", "previsao"
        ]
        numeric_cols = [c for c in fc.columns if pd.api.types.is_numeric_dtype(fc[c])]
        fc_value_options = [c for c in value_candidates if c in fc.columns] or numeric_cols
        if fc_value_options:
            fc_value = st.selectbox("Coluna do forecast", fc_value_options, index=0)
            fc["valor_previsto"] = to_num(fc[fc_value])
            if "target" in fc.columns and chosen_hist_targets:
                fc = fc[fc["target"].isin(chosen_hist_targets)]
            if {"epi_year", "epi_week"}.issubset(fc.columns):
                fc["periodo"] = [iso_week_label(y, w) for y, w in zip(fc["epi_year"], fc["epi_week"])]
            else:
                fc["periodo"] = np.arange(len(fc)).astype(str)
            fig = px.line(
                fc.sort_values(["target", "periodo"]) if "target" in fc.columns else fc,
                x="periodo",
                y="valor_previsto",
                color="target" if "target" in fc.columns else None,
                markers=True,
                title=f"Forecast integrado — {fc_value}",
            )
            st.plotly_chart(fig, use_container_width=True)
            show_table(fc, "Tabela forecast integrada", max_rows=1000)
        else:
            st.info("Forecast encontrado, mas não foi possível identificar uma coluna numérica de previsão.")
    else:
        st.info("forecast_integrated_statewide.csv não encontrado. O painel usa projeção operacional curta baseada no período selecionado.")


# =============================================================================
# Aba 12: histórico anual
# =============================================================================
with tabs[12]:
    st.subheader("Histórico anual por agravo/alvo")

    if annual.empty:
        st.info("integrated_annual_summary.csv vazio ou ausente.")
    else:
        af = annual[annual["target"].isin(selected_targets)].copy()
        if af.empty:
            st.info("Sem dados anuais para o filtro atual.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                fig = px.line(
                    af.sort_values(["target", "ano"]),
                    x="ano",
                    y="positividade_media",
                    color="target",
                    markers=True,
                    title="Positividade anual por agravo/alvo",
                )
                fig.update_yaxes(tickformat=".0%")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                fig = px.line(
                    af.sort_values(["target", "ano"]),
                    x="ano",
                    y="testes",
                    color="target",
                    markers=True,
                    title="Solicitações/testes anuais por agravo/alvo",
                )
                st.plotly_chart(fig, use_container_width=True)

            c3, c4 = st.columns(2)
            with c3:
                fig = px.line(
                    af.sort_values(["target", "ano"]),
                    x="ano",
                    y="notificacoes",
                    color="target",
                    markers=True,
                    title="Notificações anuais por agravo/alvo",
                )
                st.plotly_chart(fig, use_container_width=True)
            with c4:
                fig = px.line(
                    af.sort_values(["target", "ano"]),
                    x="ano",
                    y="incidencia_100k",
                    color="target",
                    markers=True,
                    title="Incidência anual por 100 mil",
                )
                st.plotly_chart(fig, use_container_width=True)

            show_table(af, "Resumo anual integrado", max_rows=1000)


# =============================================================================
# Aba 13: clima e ambiente
# =============================================================================
with tabs[13]:
    st.subheader("Clima, ambiente e vulnerabilidade")

    if climate_assoc is not None and not climate_assoc.empty:
        ca = climate_assoc.copy()
        tgt = first_col(ca, ["target", "alvo", "agravo"])
        if tgt and selected_targets:
            ca = ca[ca[tgt].isin(selected_targets)]
        show_table(ca, "Associação clima-doença pré-calculada", max_rows=1000)
    else:
        st.info(
            "climate_association_summary.csv não encontrado ou vazio. "
            "Gerando associação exploratória em tempo de execução com climate_weekly_municipio.csv."
        )
        wf_period_year = wf[wf["epi_year"].eq(analysis_year)].copy()
        runtime_ca = build_runtime_climate_association(wf_period_year, climate_weekly, selected_targets, selected_muns)
        if runtime_ca.empty:
            st.warning(
                "Não foi possível calcular associação clima-indicador. Verifique se climate_weekly_municipio.csv "
                "tem município, ano/semana e variáveis climáticas numéricas."
            )
        else:
            show_table(runtime_ca, "Associação exploratória clima x indicadores", max_rows=1000)
            top_ca = runtime_ca.head(40)
            fig = px.bar(
                top_ca,
                x="correlacao_spearman",
                y="variavel_climatica",
                color="target",
                orientation="h",
                hover_data=["indicador", "lag_semanas", "n"],
                title="Maiores correlações exploratórias clima x indicadores",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

    if climate_weekly is not None and not climate_weekly.empty:
        cw = climate_weekly.copy()
        mc = first_col(cw, ["municipio", "Município", "Municipio"])
        yc = first_col(cw, ["epi_year", "ano", "year"])
        wc = first_col(cw, ["epi_week", "semana", "week"])
        if mc:
            cw["municipio"] = cw[mc].map(norm_municipio)
            if selected_muns:
                cw = cw[cw["municipio"].isin(selected_muns)]
        if yc:
            cw["epi_year"] = to_num(cw[yc])
        if wc:
            cw["epi_week"] = to_num(cw[wc])
        if yc and wc:
            cw["periodo"] = [iso_week_label(y, w) for y, w in zip(cw["epi_year"], cw["epi_week"])]
        numeric_climate_cols = []
        for c in cw.columns:
            if norm_key(c) in {"municipio", "epi_year", "epi_week", "ano", "semana", "periodo"}:
                continue
            s = to_num(cw[c])
            if s.notna().sum() >= 5:
                cw[c] = s
                numeric_climate_cols.append(c)
        if numeric_climate_cols and "periodo" in cw.columns:
            clim_var = st.selectbox("Variável climática para série", numeric_climate_cols, index=0)
            plot = cw.groupby(["epi_year", "epi_week", "periodo"], as_index=False)[clim_var].mean()
            fig = px.line(plot.sort_values(["epi_year", "epi_week"]), x="periodo", y=clim_var, markers=True, title=f"Série climática — {clim_var}")
            st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# Aba 14: tabelas e qualidade
# =============================================================================
with tabs[14]:
    st.subheader("Tabelas, qualidade e exportações")

    export_tables = {
        "analise_periodo": period_df,
        "alertas_gestores_proximos_dias": manager_alerts,
        "municipios_em_risco": df_risco,
        "municipios_silenciosos": df_silenciosos,
        "taxa_utilizacao_lacen": df_utilizacao,
        "ml_forecast_demanda": df_ml_forecast,
        "ml_anomalias": df_ml_anomalias,
        "ml_risco_predito": df_ml_risco,
        "ml_silencio_predito": df_ml_silencio,
        "weekly_filtrado": wf,
        "annual": annual,
        "summary_municipio": summary_mun,
        "integrated_alerts": alerts,
    }
    if schema is not None and not schema.empty:
        export_tables["schema_catalog"] = schema
    if backlog is not None and not backlog.empty:
        export_tables["backlog"] = backlog
    if cnes_capacity is not None and not cnes_capacity.empty:
        export_tables["cnes_capacity"] = cnes_capacity

    table_choice = st.selectbox("Tabela para visualizar", list(export_tables.keys()))
    show_table(export_tables[table_choice], table_choice, max_rows=2000)

    diag = pd.DataFrame([
        {"item": "Linhas weekly", "valor": len(weekly)},
        {"item": "Agravos/alvos weekly", "valor": weekly["target"].nunique()},
        {"item": "Municípios weekly", "valor": weekly["municipio"].nunique()},
        {"item": "Ano mínimo", "valor": min_year},
        {"item": "Ano máximo", "valor": max_year},
        {"item": "Ano analisado", "valor": analysis_year},
        {"item": "Período analisado", "valor": f"SE{week_start:02d}-SE{week_end:02d}"},
        {"item": "Alertas gestores", "valor": len(manager_alerts)},
        {"item": "Climate association existe", "valor": bool(climate_assoc is not None and not climate_assoc.empty)},
        {"item": "Climate weekly existe", "valor": bool(climate_weekly is not None and not climate_weekly.empty)},
    ])
    st.dataframe(diag, use_container_width=True)

footer_institucional()
