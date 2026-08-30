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
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from lacen_auth import auth_sidebar_status, require_auth
from lacen_theme import footer_institucional, hero, inject_theme, meta_bar


VERSAO_DASHBOARD_LACEN = "v5.4-auth-institucional"

# Pasta padrão pública (Cloud / uso normal). Override só em admin ou diagnóstico.
DATA_DIR = Path("saida_pipeline")


def _modo_admin() -> bool:
    env = str(os.environ.get("MODO_ADMIN", "")).strip().lower()
    if env in {"1", "true", "yes", "sim", "on"}:
        return True
    try:
        sec = st.secrets.get("MODO_ADMIN", False)
        if isinstance(sec, bool):
            return sec
        return str(sec).strip().lower() in {"1", "true", "yes", "sim", "on"}
    except Exception:
        return False

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

# Carregados no start (visão executiva / fila operacional)
STARTUP_OPTIONAL_FILES = {
    "municipios_risco": "municipios_em_risco.csv",
    "municipios_silenciosos": "municipios_silenciosos.csv",
    "taxa_utilizacao": "taxa_utilizacao_lacen.csv",
    "qualidade_dado": "qualidade_dado_municipal.csv",
    "municipio_vizinhos": "municipio_vizinhos.csv",
    "ml_risco": "ml_risco_predito.csv",
    "ml_silencio": "ml_silencio_predito.csv",
    "ml_pressao": "ml_pressao_rede_predito.csv",
    "indicadores_emergencia": "indicadores_emergencia.csv",
    "indicadores_emergencia_resumo": "indicadores_emergencia_resumo.csv",
    "indicadores_emergencia_acoes": "indicadores_emergencia_acoes.csv",
    "emergencia_confirmacao": "emergencia_confirmacao_resumo.csv",
    "briefing_epi": "briefing_epi_se.csv",
}

# Carregados sob demanda pelo módulo aberto (não no startup)
DEFERRED_OPTIONAL_FILES = {
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
    "ml_forecast": "ml_forecast_demanda.csv",
    "ml_anomalias": "ml_anomalias.csv",
    "ml_features": "ml_features_latest.csv",
    "ml_backtest": "ml_backtest_summary.csv",
    "ml_pressao_familia": "ml_pressao_rede_familia_predito.csv",
    "ml_pressao_backtest": "ml_pressao_rede_backtest.csv",
    "sinan_weekly": "sinan_weekly_municipio.csv",
    "sim_weekly": "sim_weekly_municipio.csv",
    "indicadores_rede": "indicadores_rede_laboratorial.csv",
    "indicadores_rede_familia": "indicadores_rede_por_familia.csv",
    "indicadores_emergencia_familia": "indicadores_emergencia_familia.csv",
    "alerta_historico": "alerta_historico.csv",
    "alerta_emergencia_historico": "alerta_emergencia_historico.csv",
    "executive_state": "executive_state_summary.csv",
}

OPTIONAL_FILES = {**STARTUP_OPTIONAL_FILES, **DEFERRED_OPTIONAL_FILES}


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
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        try:
            st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.warning(f"{context}: falha ao renderizar ({exc}).")
    except Exception as exc:
        st.warning(f"{context}: falha ao renderizar ({exc}).")


def safe_dataframe(df: pd.DataFrame, **kwargs) -> None:
    """dataframe com width='stretch' e fallback para Streamlit antigo."""
    try:
        st.dataframe(df, width="stretch", **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kwargs)


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


def show_table(df: pd.DataFrame, title: str, max_rows: int = 500, key: Optional[str] = None) -> None:
    st.markdown(f"#### {title}")
    if df is None or df.empty:
        st.info("Tabela vazia para o filtro atual.")
        return
    safe_dataframe(df.head(max_rows))
    csv = df.to_csv(index=False).encode("utf-8-sig")
    safe_name = norm_key(title) or "tabela"
    btn_key = key or f"dl_{safe_name}_{len(df)}_{max_rows}"
    st.download_button(
        f"Baixar {title} em CSV",
        data=csv,
        file_name=f"{safe_name}.csv",
        mime="text/csv",
        key=btn_key,
    )


def top_targets_by_volume(
    df: pd.DataFrame,
    candidates: Sequence[str],
    n: int = 5,
    target_col: str = "target",
    volume_col: str = "tests",
) -> list[str]:
    """Seleciona os N agravos com maior volume entre os candidatos (para gráficos de linha)."""
    if df is None or df.empty or not candidates:
        return list(candidates)[:n]
    work = df[df[target_col].isin(list(candidates))].copy() if target_col in df.columns else df.copy()
    if work.empty or target_col not in work.columns:
        return list(candidates)[:n]
    vol = volume_col if volume_col in work.columns else None
    if vol is None:
        for alt in ("tests", "tests_periodo", "exames", "forecast_tests"):
            if alt in work.columns:
                vol = alt
                break
    if vol is None:
        return list(candidates)[:n]
    rank = (
        work.groupby(target_col, as_index=False)[vol]
        .sum()
        .sort_values(vol, ascending=False)
    )
    top = [str(x) for x in rank[target_col].head(int(n)).tolist()]
    return top or list(candidates)[:n]


# =============================================================================
# Carga e harmonização
# =============================================================================

@st.cache_data(show_spinner=False)
def _load_one_table(folder: str, filename: str) -> Optional[pd.DataFrame]:
    base = Path(folder)
    p = base / filename
    pq = p.with_suffix(".parquet")
    if not p.exists() and not pq.exists():
        return None
    try:
        return read_table_resilient(p)
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_data(folder: str, include_deferred: bool = False):
    """Carrega core + optionals leves. Arquivos pesados só se include_deferred=True."""
    data: dict[str, Optional[pd.DataFrame]] = {}
    missing: list[str] = []

    for key, filename in CORE_FILES.items():
        df = _load_one_table(folder, filename)
        if df is None:
            data[key] = None
            missing.append(filename)
        else:
            data[key] = df

    for key, filename in STARTUP_OPTIONAL_FILES.items():
        data[key] = _load_one_table(folder, filename)

    if include_deferred:
        for key, filename in DEFERRED_OPTIONAL_FILES.items():
            data[key] = _load_one_table(folder, filename)
    else:
        for key in DEFERRED_OPTIONAL_FILES:
            data[key] = None

    return data, missing


def get_optional(folder: str, key: str) -> pd.DataFrame:
    """Carga sob demanda de arquivo opcional (com cache)."""
    filename = OPTIONAL_FILES.get(key)
    if not filename:
        return pd.DataFrame()
    df = _load_one_table(folder, filename)
    return df if df is not None else pd.DataFrame()


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
        **({"codigo_ibge": ("codigo_ibge", "max")} if "codigo_ibge" in df.columns else {}),
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
    preferred = [
        Path("geo") / "mt_municipios.geojson",
        Path("assets") / "mt_municipios.geojson",
        Path("malhas") / "mt_municipios.geojson",
    ]
    for p in preferred:
        if p.exists():
            return p
    for d in [Path("geo"), Path("shapefiles"), Path("malhas"), Path("assets"), Path(".")]:
        if not d.exists():
            continue
        for ext in ("*.geojson", "*.json", "*.shp"):
            files = sorted(d.glob(ext))
            # Evita JSON de config genérico na raiz
            files = [f for f in files if "municip" in f.name.lower() or f.suffix.lower() in {".geojson", ".shp"} or d.name in {"geo", "malhas", "shapefiles"}]
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
                # Normaliza código IBGE (tbrugz/geodata-br usa "id")
                ibge_raw = props.get("id") or props.get("CD_MUN") or props.get("codigo_ibge") or props.get("codarea")
                if ibge_raw is not None and str(ibge_raw).strip():
                    try:
                        props["codigo_ibge"] = str(int(float(str(ibge_raw).strip())))
                    except Exception:
                        props["codigo_ibge"] = str(ibge_raw).strip()
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
                ibge_raw = props.get("CD_MUN") or props.get("codigo_ibge") or props.get("GEOCODIGO")
                if ibge_raw is not None and str(ibge_raw).strip():
                    try:
                        props["codigo_ibge"] = str(int(float(str(ibge_raw).strip())))
                    except Exception:
                        props["codigo_ibge"] = str(ibge_raw).strip()
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


def _norm_ibge(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    return out.apply(lambda x: str(int(x)) if pd.notna(x) else "")


def join_shape_with_period(props_df: pd.DataFrame, period_df: pd.DataFrame) -> pd.DataFrame:
    if props_df is None or props_df.empty or period_df is None or period_df.empty:
        return pd.DataFrame()
    props = props_df.copy()
    risk = period_df.copy()

    # Preferência: join por código IBGE (mais estável que nome)
    if "codigo_ibge" in props.columns and "codigo_ibge" in risk.columns:
        props["codigo_ibge_join"] = _norm_ibge(props["codigo_ibge"])
        risk["codigo_ibge_join"] = _norm_ibge(risk["codigo_ibge"])
        merged = props[["__id", "codigo_ibge_join"]].merge(
            risk, on="codigo_ibge_join", how="left"
        )
        if merged["codigo_ibge_join"].ne("").any() and merged.drop(columns=["__id", "codigo_ibge_join"], errors="ignore").notna().any().any():
            hit = int(merged.drop(columns=["__id"], errors="ignore").notna().any(axis=1).sum()) if len(merged) else 0
            # Se poucos matches, cai no nome
            if hit >= max(5, int(0.1 * len(props))):
                return merged

    if "municipio_join" not in props.columns:
        mc = infer_shape_municipio_col(props)
        if not mc:
            return pd.DataFrame()
        props["municipio_join"] = props[mc].map(norm_join_municipio)
    if "municipio" not in risk.columns:
        return pd.DataFrame()
    risk["municipio_join"] = risk["municipio"].map(norm_join_municipio)
    keep_props = ["__id", "municipio_join"] + (["codigo_ibge"] if "codigo_ibge" in props.columns else [])
    return props[keep_props].merge(risk, on="municipio_join", how="left")


def make_choropleth(geojson: dict, merged: pd.DataFrame, value_col: str, title: str):
    if geojson is None or merged is None or merged.empty or value_col not in merged.columns:
        return None
    plot_df = merged.copy()
    # Categorical risk bands (object ou pandas StringDtype)
    cat_cols = {"banda_risco", "faixa_risco", "prioridade", "banda_absoluta", "banda_percentil"}
    is_categorical = value_col in cat_cols or not pd.api.types.is_numeric_dtype(plot_df[value_col])
    if is_categorical and value_col in cat_cols:
        plot_df[value_col] = plot_df[value_col].astype(str).replace({"nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})
        if plot_df[value_col].notna().sum() == 0:
            return None
        color_kw = {
            "color": value_col,
            "category_orders": {value_col: [k for k in [
                "Baixo", "Moderado", "Alto", "Crítico",
                "habitual", "atencao", "alerta", "alto_alerta",
                "MODERADO", "ALTO", "CRÍTICO",
            ] if k in set(plot_df[value_col].dropna().astype(str))]},
        }
    else:
        plot_df[value_col] = to_num(plot_df[value_col])
        if plot_df[value_col].notna().sum() == 0:
            return None
        color_kw = {"color": value_col}
    hover_cols = [c for c in [
        "municipio", "target", "prioridade", "banda_risco", "faixa_risco",
        "cenario_operacional", "tests_periodo",
        "positivos_periodo", "positividade_periodo", "delta_positividade_pp",
        "delta_tests_abs", "notificacoes_periodo", "projecao_solicitacoes_proximos_dias",
        "janela_alerta_proximos_dias", "percentil_estadual", "codigo_ibge",
    ] if c in plot_df.columns]
    fig = px.choropleth_mapbox(
        plot_df,
        geojson=geojson,
        locations="__id",
        featureidkey="properties.__id",
        hover_name="municipio" if "municipio" in plot_df.columns else None,
        hover_data={c: True for c in hover_cols if c != "municipio"},
        mapbox_style="open-street-map",
        zoom=4.8,
        center={"lat": -12.8, "lon": -56.0},
        opacity=0.72,
        height=630,
        title=title,
        **color_kw,
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


def with_acao(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica protocolo operacional (ação, responsável, prazo, checklist)."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    try:
        from lacen_inteligencia import enriquecer_acoes
        out = df.copy()
        if "sinal" not in out.columns:
            if "faixa_risco" in out.columns:
                out["sinal"] = "risco_territorial"
            elif "classificacao_silencio" in out.columns or "silencio_laboratorial" in out.columns:
                out["sinal"] = "silencio_laboratorial"
            elif "classificacao_uso" in out.columns:
                out["sinal"] = "utilizacao_lacen"
            elif "prioridade" in out.columns:
                out["sinal"] = "alerta_laboratorial"
        return enriquecer_acoes(out)
    except Exception:
        out = df.copy()
        if "acao_sugerida" not in out.columns:
            out["acao_sugerida"] = "Acompanhar indicadores e reavaliar na próxima janela epidemiológica."
        return out


def build_fila_operacional(
    period_df: pd.DataFrame,
    df_risco: pd.DataFrame,
    df_silenciosos: pd.DataFrame,
    top_n: int = 20,
    df_ml_risco: Optional[pd.DataFrame] = None,
    df_ml_silencio: Optional[pd.DataFrame] = None,
    df_ml_pressao: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Fila gerencial: município | sinal | motivo | prioridade | ação | prazo | responsável."""
    rows: list[dict] = []

    if period_df is not None and not period_df.empty:
        high = period_df[period_df.get("prioridade", pd.Series(dtype=str)).isin(["CRÍTICO", "ALTO"])].copy()
        if "prioridade_score" in high.columns:
            high = high.sort_values("prioridade_score", ascending=False)
        for _, r in high.head(top_n).iterrows():
            rows.append({
                "municipio": r.get("municipio"),
                "agravo_alvo": r.get("target"),
                "sinal": "alerta_laboratorial",
                "motivo": r.get("cenario_operacional") or f"Prioridade {r.get('prioridade')}",
                "prioridade": r.get("prioridade"),
                "score": r.get("prioridade_score", np.nan),
                "exames": r.get("tests_periodo", np.nan),
                "positividade": r.get("positividade_periodo", np.nan),
            })

    if df_risco is not None and not df_risco.empty:
        risco = df_risco.copy()
        if "faixa_risco" in risco.columns:
            risco = risco[risco["faixa_risco"].astype(str).isin(["alerta", "alto_alerta", "atencao"])]
        if "score_risco_territorial" in risco.columns:
            risco = risco.sort_values("score_risco_territorial", ascending=False)
        for _, r in risco.head(min(10, top_n)).iterrows():
            rows.append({
                "municipio": r.get("municipio"),
                "agravo_alvo": "",
                "sinal": "risco_territorial",
                "motivo": f"Faixa {r.get('faixa_risco')} | score {float(r.get('score_risco_territorial', 0) or 0):.2f}",
                "prioridade": "ALTO" if str(r.get("faixa_risco")) in {"alerta", "alto_alerta"} else "MODERADO",
                "score": r.get("score_risco_territorial", np.nan),
                "exames": r.get("tests_8sem", np.nan),
                "positividade": r.get("positividade_media", np.nan),
            })

    if df_silenciosos is not None and not df_silenciosos.empty:
        sil = df_silenciosos.copy()
        tipo_col = "classificacao_silencio" if "classificacao_silencio" in sil.columns else "tipo_sinal"
        if tipo_col in sil.columns:
            sil = sil[sil[tipo_col].astype(str).isin(["silencio_critico", "silencio_provavel"])]
        if "silencio_com_vizinho_alerta" in sil.columns and "score_silencio" in sil.columns:
            sil = sil.sort_values(["silencio_com_vizinho_alerta", "score_silencio"], ascending=[False, False])
        elif "silencio_com_vizinho_alerta" in sil.columns:
            sil = sil.sort_values("silencio_com_vizinho_alerta", ascending=False)
        elif "score_silencio" in sil.columns:
            sil = sil.sort_values("score_silencio", ascending=False)
        for _, r in sil.head(min(10, top_n)).iterrows():
            motivo = (
                f"{r.get(tipo_col, 'silencio')} | exames recentes={r.get('tests_recent', 0)} "
                f"| notif={r.get('notif_recent', r.get('notificacoes', 0))}"
            )
            if bool(r.get("silencio_com_vizinho_alerta", False)):
                motivo += f" | vizinhos em alerta={r.get('vizinhos_em_alerta', 0)}"
            rows.append({
                "municipio": r.get("municipio"),
                "agravo_alvo": r.get("target", ""),
                "sinal": "silencio_laboratorial",
                "motivo": motivo,
                "prioridade": "CRÍTICO" if (
                    str(r.get(tipo_col, "")).endswith("critico")
                    or bool(r.get("silencio_com_vizinho_alerta", False))
                ) else "ALTO",
                "score": r.get("score_silencio", np.nan),
                "exames": r.get("tests_recent", np.nan),
                "positividade": np.nan,
            })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    pri_rank = {"CRÍTICO": 0, "ALTO": 1, "MODERADO": 2, "MONITORAMENTO": 3}
    out["_pr"] = out["prioridade"].astype(str).map(pri_rank).fillna(9)
    out = out.sort_values(["_pr", "score"], ascending=[True, False]).drop(columns=["_pr"])
    out = out.drop_duplicates(subset=["municipio", "sinal", "agravo_alvo"], keep="first")
    out = with_acao(out.head(top_n))
    try:
        from lacen_inteligencia import enriquecer_fila_com_ml
        out = enriquecer_fila_com_ml(
            out, df_ml_risco, df_ml_silencio, ml_pressao=df_ml_pressao
        )
        # Reordena após reforço híbrido
        pri_rank = {"CRÍTICO": 0, "ALTO": 1, "MODERADO": 2, "MONITORAMENTO": 3}
        out["_pr"] = out["prioridade"].astype(str).map(pri_rank).fillna(9)
        out = out.sort_values(
            ["alerta_hibrido", "_pr", "prob_ml", "score"],
            ascending=[False, True, False, False],
        ).drop(columns=["_pr"], errors="ignore")
    except Exception:
        pass
    cols = [
        "municipio", "sinal", "motivo", "prioridade",
        "acao_sugerida", "responsavel", "prazo_acao", "checklist_operacional",
        "alerta_hibrido", "prob_ml", "faixa_ml",
        "prob_pressao_predita", "faixa_pressao_predita",
        "agravo_alvo", "exames", "positividade", "score",
    ]
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)

# =============================================================================
# App
# =============================================================================

require_auth()

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

MODO_ADMIN = _modo_admin()
folder = str(DATA_DIR)

with st.sidebar:
    st.markdown("### SES-MT · CIEVS · LACEN")
    st.caption("Painel institucional de vigilância laboratorial")
    auth_sidebar_status()
    if MODO_ADMIN:
        folder = st.text_input("Pasta saida_pipeline (admin)", value=str(DATA_DIR))
        st.caption("MODO_ADMIN ativo — override de pasta permitido.")
    else:
        st.caption(f"Dados: `{DATA_DIR}`")
        with st.expander("Diagnóstico técnico"):
            folder = st.text_input("Override de pasta (avançado)", value=str(DATA_DIR), key="diag_folder")
            st.caption("Em uso público a pasta padrão é `saida_pipeline`. Alterar só para diagnóstico local.")

try:
    data, missing = load_data(folder, include_deferred=False)
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

# Optionals leves (startup)
df_risco = data.get("municipios_risco")
df_silenciosos = data.get("municipios_silenciosos")
df_utilizacao = data.get("taxa_utilizacao")
df_qualidade = data.get("qualidade_dado")
df_vizinhos = data.get("municipio_vizinhos")
df_ml_risco = data.get("ml_risco")
df_ml_silencio = data.get("ml_silencio")
df_ml_pressao = data.get("ml_pressao")
df_emergencia = data.get("indicadores_emergencia")
df_emergencia_resumo = data.get("indicadores_emergencia_resumo")
df_emergencia_acoes = data.get("indicadores_emergencia_acoes")
df_emergencia_confirmacao = data.get("emergencia_confirmacao")
if df_risco is None:
    df_risco = pd.DataFrame()
if df_silenciosos is None:
    df_silenciosos = pd.DataFrame()
if df_utilizacao is None:
    df_utilizacao = pd.DataFrame()
if df_qualidade is None:
    df_qualidade = pd.DataFrame()
if df_vizinhos is None:
    df_vizinhos = pd.DataFrame()
if df_ml_risco is None:
    df_ml_risco = pd.DataFrame()
if df_ml_silencio is None:
    df_ml_silencio = pd.DataFrame()
if df_ml_pressao is None:
    df_ml_pressao = pd.DataFrame()
if df_emergencia is None:
    df_emergencia = pd.DataFrame()
if df_emergencia_resumo is None:
    df_emergencia_resumo = pd.DataFrame()
if df_emergencia_acoes is None:
    df_emergencia_acoes = pd.DataFrame()
if df_emergencia_confirmacao is None:
    df_emergencia_confirmacao = pd.DataFrame()

# Placeholders — carregados sob demanda pelo módulo
forecast = pd.DataFrame()
municipal_master = pd.DataFrame()
climate_weekly = pd.DataFrame()
climate_assoc = pd.DataFrame()
requests_demo = None
positivity_demo = None
schema = None
backlog = None
cnes_capacity = None
df_ml_forecast = pd.DataFrame()
df_ml_anomalias = pd.DataFrame()
df_ml_backtest = pd.DataFrame()
df_sinan_weekly = pd.DataFrame()
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
fila_operacional = build_fila_operacional(
    period_df, df_risco, df_silenciosos, top_n=20,
    df_ml_risco=df_ml_risco, df_ml_silencio=df_ml_silencio,
    df_ml_pressao=df_ml_pressao,
)

# Default de agravos para gráficos de linha (top 5 por volume); "Todos" permanece nos filtros/tabelas
default_chart_targets = top_targets_by_volume(
    period_df if not period_df.empty else wf,
    selected_targets,
    n=5,
    volume_col="tests_periodo" if (not period_df.empty and "tests_periodo" in period_df.columns) else "tests",
)

MODULOS = [
    "Visão executiva",
    "Vigilância laboratorial",
    "Territórios prioritários",
    "Integração epidemiológica",
    "Predição e alertas",
    "Dados e qualidade",
]
modulo = st.radio("Módulo", MODULOS, horizontal=True, label_visibility="collapsed", key="modulo_principal")


# =============================================================================
# Módulo: Visão executiva
# =============================================================================
if modulo == "Visão executiva":
    st.subheader("Visão executiva — Sala de Situação Laboratorial")
    st.caption(
        "Leitura rápida: **o quê** (volume/positividade), **onde** (municípios prioritários/silêncio) "
        "e **o que fazer** (fila com ação, prazo e responsável). "
        "Indicadores: Observado · Derivado · Predito."
    )
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

        n_crit = int((period_df["prioridade"] == "CRÍTICO").sum()) if "prioridade" in period_df.columns else 0
        n_alto = int((period_df["prioridade"] == "ALTO").sum()) if "prioridade" in period_df.columns else 0
        n_hibrido = int(fila_operacional["alerta_hibrido"].fillna(False).sum()) if (
            not fila_operacional.empty and "alerta_hibrido" in fila_operacional.columns
        ) else 0

        # Resumo automático da janela
        top_mun = ""
        if "prioridade_score" in period_df.columns and "municipio" in period_df.columns:
            tm = period_df.sort_values("prioridade_score", ascending=False)
            if not tm.empty:
                top_mun = str(tm.iloc[0]["municipio"])
        top_agravo = default_chart_targets[0] if default_chart_targets else "—"
        st.info(
            f"**Resumo da janela** {analysis_year}-SE{week_start:02d}–SE{week_end:02d}: "
            f"{format_int(exames)} exames (Observado), positividade {format_pct(pos_global)} (Derivado), "
            f"{format_int(n_crit + n_alto)} sinais crítico/alto (Derivado). "
            f"Prioritário: {top_mun or '—'}; agravo de maior volume: {top_agravo}. "
            f"Fila operacional: {len(fila_operacional)} itens"
            + (f" ({n_hibrido} com reforço híbrido ML/Predito)." if n_hibrido else ".")
        )

        st.markdown("##### Indicadores-chave")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Exames (Observado)", format_int(exames))
        c2.metric("Positivos (Observado)", format_int(positivos))
        c3.metric("Positividade (Derivado)", format_pct(pos_global))
        c4.metric("Municípios ativos (Observado)", format_int(mun_ativos))
        c5.metric("Silenciosos (Derivado)", format_int(silencio_n))
        c6.metric("Prioritários atenção+ (Derivado)", format_int(alto_risco_n))

        # --- Briefing SE — 5 perguntas CIEVS ---
        st.markdown("##### Briefing SE — 5 perguntas CIEVS")
        df_briefing = get_optional(folder, "briefing_epi")
        if df_briefing.empty:
            try:
                from lacen_briefing_epi import gerar_briefing_epi

                _b = gerar_briefing_epi(folder, persistir=False)
                if _b.rows_flat:
                    df_briefing = pd.DataFrame(_b.rows_flat)
            except Exception:
                df_briefing = pd.DataFrame()
        if df_briefing.empty:
            st.caption(
                "Briefing indisponível — gere com `python lacen_briefing_epi.py` "
                "ou rode o relatório CIEVS."
            )
        else:
            se_brief = (
                str(df_briefing["se"].iloc[0])
                if "se" in df_briefing.columns and len(df_briefing)
                else "—"
            )
            with st.expander(
                f"Briefing SE — 5 perguntas CIEVS ({se_brief})",
                expanded=False,
            ):
                st.caption(
                    "Observado (lab integrated_weekly) · Predito (ML se presente). "
                    "Positividade IgG/sorologia elevada ≠ surto agudo."
                )
                pergunta_col = "pergunta" if "pergunta" in df_briefing.columns else None
                if pergunta_col:
                    labels = {
                        "mais_solicitados": "1) Mais solicitados",
                        "maior_positividade": "2) Maior positividade",
                        "localidades": "3) Localidades",
                        "vizinhos_mesma_situacao": "4) Vizinhos na mesma situação",
                        "risco_dispersao": "5) Risco de dispersão",
                    }
                    for key, title in labels.items():
                        sub = df_briefing[df_briefing[pergunta_col].astype(str) == key]
                        if sub.empty:
                            continue
                        st.markdown(f"**{title}**")
                        cols_show = [
                            c
                            for c in [
                                "rank",
                                "target",
                                "municipio",
                                "exames",
                                "positivos",
                                "positividade",
                                "detalhe",
                                "tipo_sinal",
                                "flag",
                            ]
                            if c in sub.columns
                        ]
                        show_table(
                            sub[cols_show].head(12),
                            title,
                            max_rows=12,
                            key=f"briefing_{key}",
                        )
                else:
                    show_table(
                        df_briefing.head(40),
                        "Briefing epi",
                        max_rows=40,
                        key="briefing_raw",
                    )

        # --- Cartão executivo de emergência (5 KPIs + ações) ---
        st.markdown("##### Emergência em saúde pública — cartão executivo")
        st.caption(
            "SLA de crise, pressão da rede (Observado/Derivado/Predito), silêncio GAL e divergência GAL×notificação."
        )
        if df_emergencia_resumo.empty and df_emergencia.empty:
            st.info(
                "Arquivos `indicadores_emergencia*.csv` ainda não gerados. "
                "Execute `python gerar_indicadores_emergencia.py` "
                "(e, para %≤48h, `python gerar_indicadores_rede_lacen.py --years 3`)."
            )
        else:
            rs = df_emergencia_resumo.iloc[0] if not df_emergencia_resumo.empty else None
            if rs is not None:
                e1, e2, e3, e4, e5 = st.columns(5)
                pct48 = rs.get("kpi_pct_liberado_48h")
                tat90 = rs.get("kpi_tat_p90_dias")
                press = rs.get("kpi_indice_pressao_rede")
                n_sil_g = rs.get("kpi_n_silencio_gal")
                n_div_g = rs.get("kpi_n_divergencia_gal_notif")
                e1.metric(
                    "% liberado ≤48h (Observado)",
                    format_pct(pct48) if pd.notna(pct48) else "n/d",
                )
                e2.metric(
                    "TAT p90 dias (Observado)",
                    format_num(tat90) if pd.notna(tat90) else "n/d",
                )
                e3.metric(
                    "Pressão rede 0–100 (Derivado)",
                    format_num(press) if pd.notna(press) else "n/d",
                )
                e4.metric("Silêncio GAL (Derivado)", format_int(n_sil_g or 0))
                e5.metric("Divergência GAL×notif (Derivado)", format_int(n_div_g or 0))

                n_pred = rs.get("kpi_n_pressao_predita_alta")
                taxa_conf = rs.get("kpi_taxa_confirmacao_emergencia")
                if pd.isna(taxa_conf) and not df_emergencia_confirmacao.empty:
                    taxa_conf = df_emergencia_confirmacao.iloc[0].get("taxa_confirmacao_geral")
                tipo_conf = rs.get("kpi_tipo_sinal_confirmacao")
                if (pd.isna(tipo_conf) or not tipo_conf) and not df_emergencia_confirmacao.empty:
                    tipo_conf = df_emergencia_confirmacao.iloc[0].get("tipo_sinal")
                tipo_conf = str(tipo_conf) if pd.notna(tipo_conf) and tipo_conf else "Derivado"
                taxa_sil_conf = rs.get("kpi_taxa_confirmacao_silencio_gal")
                if pd.isna(taxa_sil_conf) and not df_emergencia_confirmacao.empty:
                    taxa_sil_conf = df_emergencia_confirmacao.iloc[0].get(
                        "taxa_confirmacao_silencio_gal"
                    )
                p1, p2, p3, p4 = st.columns(4)
                p1.metric(
                    "Pressão predita alta (Predito)",
                    format_int(n_pred or 0),
                )
                if not df_ml_pressao.empty and "prob_pressao_alta_proxima_janela" in df_ml_pressao.columns:
                    p2.metric(
                        "Prob. pressão mediana (Predito)",
                        format_num(df_ml_pressao["prob_pressao_alta_proxima_janela"].median()),
                    )
                else:
                    prob_med = rs.get("kpi_prob_pressao_predita_mediana")
                    p2.metric(
                        "Prob. pressão mediana (Predito)",
                        format_num(prob_med) if pd.notna(prob_med) else "n/d",
                    )
                p3.metric(
                    f"Confirmação alertas ({tipo_conf})",
                    format_pct(taxa_conf) if pd.notna(taxa_conf) else "n/d",
                )
                p4.metric(
                    f"Confirmação silêncio GAL ({tipo_conf})",
                    format_pct(taxa_sil_conf) if pd.notna(taxa_sil_conf) else "n/d",
                )

                if "formula_pressao" in rs.index and pd.notna(rs.get("formula_pressao")):
                    with st.expander("Legenda — fórmula do índice de pressão da rede"):
                        st.caption(str(rs.get("formula_pressao")))
                if rs.get("sla_48h_disponivel") is False or (
                    pd.isna(pct48) and not df_emergencia.empty
                    and "sla_48h_fonte" in df_emergencia.columns
                    and str(df_emergencia["sla_48h_fonte"].iloc[0]).startswith("indisponivel")
                ):
                    st.caption(
                        "Nota: %≤48h ainda não disponível no artefato de rede — "
                        "use proxy Derivado (%≤7d/TAT p90) até regenerar GAL."
                    )
                if "interpretacao" in rs.index and pd.notna(rs.get("interpretacao")):
                    st.info(str(rs.get("interpretacao")))

            if not df_ml_pressao.empty:
                st.caption("Top municípios — pressão de rede predita (Predito · próxima SE)")
                show_table(
                    df_ml_pressao.head(12)[[c for c in [
                        "municipio", "prob_pressao_alta_proxima_janela", "faixa_pressao_predita",
                        "indice_pressao_rede", "faixa_pressao", "acima_limiar",
                        "drivers", "acao_sugerida",
                    ] if c in df_ml_pressao.columns]],
                    "Pressão predita",
                    max_rows=12,
                    key="exec_pressao_pred",
                )

            # SLA por família (se existir)
            df_fam_em = get_optional(folder, "indicadores_emergencia_familia")
            if not df_fam_em.empty and "familia" in df_fam_em.columns:
                st.caption("SLA de crise por família de agravo (Observado · GAL)")
                show_table(
                    df_fam_em.head(12)[[c for c in [
                        "familia", "exames", "pct_liberado_48h", "tat_p90_dias",
                        "pct_liberado_7d", "pct_rejeitado", "backlog_estimado", "sla_crise",
                    ] if c in df_fam_em.columns]],
                    "SLA por família",
                    max_rows=12,
                    key="exec_sla_fam",
                )

            if not df_emergencia_acoes.empty:
                acoes_src = df_emergencia_acoes
            elif not df_emergencia.empty and "prioridade_emergencia" in df_emergencia.columns:
                acoes_src = df_emergencia[
                    df_emergencia["prioridade_emergencia"].astype(str).isin(["CRÍTICO", "ALTO"])
                ].head(8)
            else:
                acoes_src = pd.DataFrame()
            if not acoes_src.empty:
                st.markdown("###### Ações prioritárias de emergência (prazo · responsável)")
                show_table(
                    acoes_src.head(8)[[c for c in [
                        "municipio", "prioridade_emergencia", "sla_crise",
                        "indice_pressao_rede", "prob_pressao_alta_proxima_janela",
                        "faixa_pressao_predita",
                        "silencio_gal_alerta", "divergencia_gal_notif",
                        "acao_sugerida", "responsavel", "prazo_acao",
                    ] if c in acoes_src.columns]],
                    "Ações emergência",
                    max_rows=8,
                    key="exec_emerg_acoes",
                )

        # Bandas absoluto + percentil (ML e/ou territorial)
        banda_src = df_ml_risco if not df_ml_risco.empty and "banda_risco" in df_ml_risco.columns else (
            df_risco if not df_risco.empty and "banda_risco" in df_risco.columns else pd.DataFrame()
        )
        if not banda_src.empty:
            st.caption(
                "Bandas de risco (Baixo / Moderado / Alto / Crítico): combinam severidade **absoluta** "
                "(risco composto, positividade, limiar ML) e **percentil** estadual da probabilidade/score. "
                "A banda final é o maior entre os dois critérios."
            )
            bc1, bc2, bc3, bc4 = st.columns(4)
            counts = banda_src["banda_risco"].astype(str).value_counts()
            bc1.metric("Banda Crítico", format_int(int(counts.get("Crítico", 0))))
            bc2.metric("Banda Alto", format_int(int(counts.get("Alto", 0))))
            bc3.metric("Banda Moderado", format_int(int(counts.get("Moderado", 0))))
            bc4.metric("Banda Baixo", format_int(int(counts.get("Baixo", 0))))

        st.markdown("##### O que fazer — fila operacional (ação · prazo · responsável)")
        if fila_operacional.empty:
            st.info("Sem fila operacional para a janela atual.")
        else:
            show_table(
                fila_operacional.head(15)[[c for c in [
                    "municipio", "sinal", "motivo", "prioridade",
                    "alerta_hibrido", "prob_ml", "faixa_ml", "banda_risco",
                    "prob_pressao_predita", "faixa_pressao_predita",
                    "acao_sugerida", "responsavel", "prazo_acao", "agravo_alvo",
                ] if c in fila_operacional.columns]],
                "Fila operacional (top 15)",
                max_rows=15,
                key="exec_fila",
            )
            with st.expander("Checklist operacional da fila"):
                show_table(
                    fila_operacional.head(15)[[c for c in [
                        "municipio", "sinal", "checklist_operacional", "prazo_acao", "responsavel",
                    ] if c in fila_operacional.columns]],
                    "Checklist",
                    max_rows=15,
                    key="exec_checklist",
                )
            # Download in-memory (sem gravar CSV no disco durante navegação)
            st.download_button(
                "Baixar fila operacional (CSV)",
                data=fila_operacional.to_csv(index=False).encode("utf-8-sig"),
                file_name="fila_operacional.csv",
                mime="text/csv",
                key="dl_fila_exec",
            )

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
                "responsavel", "prazo_acao",
            ] if c in top_alertas.columns]
            show_table(top_alertas[cols_alert], "Cinco principais alertas", max_rows=5, key="exec_top5")

        if not df_risco.empty and "score_risco_territorial" in df_risco.columns:
            top_risco = with_acao(df_risco.head(10))
            if require_cols(top_risco, ["municipio", "score_risco_territorial"], "Municípios prioritários"):
                fig = px.bar(
                    top_risco.sort_values("score_risco_territorial"),
                    x="score_risco_territorial",
                    y="municipio",
                    color="faixa_risco" if "faixa_risco" in top_risco.columns else None,
                    orientation="h",
                    title="Top 10 municípios prioritários (risco territorial · Derivado)",
                    labels={"score_risco_territorial": "Score de risco", "municipio": "Município"},
                )
                safe_plotly(fig, "Top risco territorial")
            with st.expander("Ver tabela dos municípios prioritários"):
                show_table(
                    top_risco[[c for c in [
                        "municipio", "faixa_risco", "score_risco_territorial",
                        "tests_8sem", "positives_8sem", "acao_sugerida",
                        "responsavel", "prazo_acao",
                    ] if c in top_risco.columns]],
                    "Municípios prioritários",
                    max_rows=10,
                    key="exec_risco",
                )
        else:
            st.info(
                "Arquivo `municipios_em_risco.csv` ainda não gerado. "
                "Rode `python lacen_integracao_final_only.py` para atualizar a inteligência territorial."
            )


# =============================================================================
# Módulo: Vigilância laboratorial (Monitoramento + Análise do período)
# =============================================================================
elif modulo == "Vigilância laboratorial":
    sub_vig = st.radio(
        "Subvisão",
        ["Monitoramento", "Análise do período"],
        horizontal=True,
        key="sub_vigilancia",
    )

    if sub_vig == "Monitoramento":
        st.subheader("Monitoramento laboratorial")
        st.caption("Exames, positivos, positividade e ranking por agravo na janela selecionada.")
        if period_df.empty:
            st.warning("Sem dados no período/filtros selecionados.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Exames na janela (Observado)", format_int(period_df["tests_periodo"].sum()) if "tests_periodo" in period_df.columns else "—")
            m2.metric("Positivos (Observado)", format_int(period_df["positivos_periodo"].sum()) if "positivos_periodo" in period_df.columns else "—")
            if {"positivos_periodo", "tests_periodo"}.issubset(period_df.columns):
                m3.metric("Positividade (Derivado)", format_pct(safe_div(period_df["positivos_periodo"].sum(), period_df["tests_periodo"].sum())))
            else:
                m3.metric("Positividade (Derivado)", "—")
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
                show_table(by_tgt, "Monitoramento por agravo", max_rows=20, key="vig_by_tgt")

    else:
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
            c3.metric("Solicitações LACEN (Observado)", format_int(period_df["tests_periodo"].sum()))
            c4.metric("Positivos (Observado)", format_int(period_df["positivos_periodo"].sum()))
            pos_global = period_df["positivos_periodo"].sum() / period_df["tests_periodo"].sum() if period_df["tests_periodo"].sum() else np.nan
            c5.metric("Positividade global (Derivado)", format_pct(pos_global))
            c6.metric("Alertas crítico/alto (Derivado)", format_int(len(high_df)))

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
            safe_dataframe(resumo)

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
            safe_plotly(fig, "Sinais do período")

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
            safe_plotly(fig2, "Cenários operacionais")

            cols = [
                "prioridade", "municipio", "target", "periodo_analise", "periodo_base", "cenario_operacional",
                "tests_periodo", "tests_base", "delta_tests_abs", "delta_tests_pct",
                "positivos_periodo", "positivos_base", "positividade_periodo", "positividade_base", "delta_positividade_pp",
                "notificacoes_periodo", "notificacoes_base", "delta_notificacoes_abs",
                "silencio_laboratorial", "baixo_uso_lacen", "projecao_solicitacoes_proximos_dias",
                "projecao_positivos_proximos_dias", "janela_alerta_proximos_dias",
            ]
            show_table(period_df[[c for c in cols if c in period_df.columns]], "Tabela analítica do período", max_rows=1000, key="vig_periodo")


# =============================================================================
# Módulo: Territórios prioritários
# =============================================================================
elif modulo == "Territórios prioritários":
    sub_terr = st.radio(
        "Subvisão",
        ["Risco territorial", "Sinais de silêncio", "Utilização", "Municípios e mapas"],
        horizontal=True,
        key="sub_territorios",
    )

    if sub_terr == "Risco territorial":
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
                show_table(proxy, "Proxy de risco a partir do período selecionado", max_rows=50, key="terr_proxy")
        else:
            faixa = sorted([str(x) for x in df_risco.get("faixa_risco", pd.Series(dtype=str)).dropna().unique()])
            sel_faixa = st.multiselect("Faixa de risco", faixa, default=faixa, key="faixa_risco_tab")
            view = with_acao(df_risco.copy())
            if sel_faixa and "faixa_risco" in view.columns:
                view = view[view["faixa_risco"].astype(str).isin(sel_faixa)]
            m1, m2, m3 = st.columns(3)
            m1.metric("Municípios listados", format_int(len(view)))
            m2.metric("Score médio (Derivado)", format_num(view["score_risco_territorial"].mean()) if "score_risco_territorial" in view.columns else "—")
            m3.metric("Em alerta/alto", format_int(view["faixa_risco"].astype(str).isin(["alerta", "alto_alerta"]).sum()) if "faixa_risco" in view.columns else 0)
            if "banda_risco" in view.columns:
                st.caption(
                    "Legenda: **banda absoluta** usa risco composto (cortes 1/2/3); "
                    "**banda percentil** usa ranking estadual do score; "
                    "**banda final** = max(absoluto, percentil)."
                )
                b1, b2, b3, b4 = st.columns(4)
                vc = view["banda_risco"].astype(str).value_counts()
                b1.metric("Crítico", format_int(int(vc.get("Crítico", 0))))
                b2.metric("Alto", format_int(int(vc.get("Alto", 0))))
                b3.metric("Moderado", format_int(int(vc.get("Moderado", 0))))
                b4.metric("Baixo", format_int(int(vc.get("Baixo", 0))))
            topn = view.head(20)
            if require_cols(topn, ["municipio", "score_risco_territorial"], "Ranking de risco"):
                fig = px.bar(
                    topn.sort_values("score_risco_territorial"),
                    x="score_risco_territorial",
                    y="municipio",
                    color="banda_risco" if "banda_risco" in topn.columns else (
                        "faixa_risco" if "faixa_risco" in topn.columns else None
                    ),
                    orientation="h",
                    title="Ranking municipal de risco territorial (top 20)",
                    labels={"score_risco_territorial": "Score de risco", "municipio": "Município"},
                )
                safe_plotly(fig, "Ranking de risco")
            with st.expander("Tabela de risco (limitada)"):
                show_table(
                    view[[c for c in [
                        "municipio", "banda_risco", "banda_absoluta", "banda_percentil",
                        "percentil_estadual", "criterio_banda", "faixa_risco",
                        "score_risco_territorial",
                        "tests_8sem", "positives_8sem", "notificacoes_8sem",
                        "acao_sugerida", "responsavel", "prazo_acao", "checklist_operacional",
                    ] if c in view.columns]],
                    "municipios_em_risco",
                    max_rows=100,
                    key="terr_risco",
                )
            if not df_ml_pressao.empty:
                st.markdown("##### Pressão de rede predita (Predito)")
                st.caption(
                    "Probabilidade de alta pressão laboratorial na próxima SE "
                    "(volume + TAT/backlog estrutural)."
                )
                show_table(
                    df_ml_pressao.head(30)[[c for c in [
                        "municipio", "prob_pressao_alta_proxima_janela", "faixa_pressao_predita",
                        "indice_pressao_rede", "faixa_pressao", "acima_limiar",
                        "acao_sugerida",
                    ] if c in df_ml_pressao.columns]],
                    "Pressão predita por município",
                    max_rows=30,
                    key="terr_pressao_pred",
                )

    elif sub_terr == "Sinais de silêncio":
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
                show_table(with_acao(period_df.loc[mask]).head(100), "Silêncio/baixo uso no período", max_rows=100, key="terr_sil_period")
        else:
            tipo_col = "classificacao_silencio" if "classificacao_silencio" in df_silenciosos.columns else "tipo_sinal"
            tipo = sorted([str(x) for x in df_silenciosos.get(tipo_col, pd.Series(dtype=str)).dropna().unique()])
            sel_tipo = st.multiselect("Classificação de silêncio", tipo, default=tipo, key="tipo_silencio_tab")
            view = with_acao(df_silenciosos.copy())
            if sel_tipo and tipo_col in view.columns:
                view = view[view[tipo_col].astype(str).isin(sel_tipo)]
            if selected_targets and "target" in view.columns:
                tgt_ok = view["target"].notna() & view["target"].astype(str).str.strip().ne("") & ~view["target"].astype(str).str.lower().isin(["nan", "none"])
                if bool(tgt_ok.any()):
                    view = view[~tgt_ok | view["target"].isin(selected_targets)]
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Municípios silenciosos", format_int(view["municipio"].nunique() if "municipio" in view.columns else len(view)))
            notif_col = "notif_recent" if "notif_recent" in view.columns else ("notificacoes" if "notificacoes" in view.columns else None)
            s2.metric("Notificações recentes", format_int(view[notif_col].fillna(0).sum()) if notif_col else "—")
            s3.metric(
                "Críticos",
                format_int((view.get(tipo_col, pd.Series(dtype=str)).astype(str) == "silencio_critico").sum())
                if tipo_col in view.columns else 0,
            )
            if "silencio_com_vizinho_alerta" in view.columns:
                s4.metric("Com vizinho em alerta", format_int(view["silencio_com_vizinho_alerta"].fillna(False).sum()))
            else:
                s4.metric("Com vizinho em alerta", "—")
            cols_show = [c for c in [
                "municipio", "classificacao_silencio", "tipo_sinal", "score_silencio",
                "tests_recent", "notif_recent", "tests_hist", "notif_hist",
                "populacao", "indice_vulnerabilidade",
                "vizinhos_em_alerta", "silencio_com_vizinho_alerta", "motivo_territorial",
                "acao_sugerida", "responsavel", "prazo_acao", "checklist_operacional",
            ] if c in view.columns]
            with st.expander("Tabela de municípios silenciosos (limitada)"):
                show_table(view[cols_show].head(100) if cols_show else view.head(100), "municipios_silenciosos", max_rows=100, key="terr_sil")
            if not df_vizinhos.empty and "municipio" in view.columns:
                with st.expander("Vizinhos territoriais dos silenciosos (amostra)"):
                    muns = set(view["municipio"].astype(str).str.upper().head(30))
                    vz = df_vizinhos.copy()
                    vz["municipio"] = vz["municipio"].astype(str).str.upper()
                    show_table(
                        vz[vz["municipio"].isin(muns)].head(100),
                        "municipio_vizinhos (silenciosos)",
                        max_rows=100,
                        key="terr_viz",
                    )

    elif sub_terr == "Utilização":
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
                    key="terr_uso_proxy",
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
                        "exames_por_100k", "classificacao_uso",
                        "acao_sugerida", "responsavel", "prazo_acao", "checklist_operacional",
                    ] if c in view.columns]],
                    "taxa_utilizacao_lacen",
                    max_rows=100,
                    key="terr_uso",
                )

    else:  # Municípios e mapas
        st.subheader("Municípios e mapas por agravo/alvo")
        st.caption("Mapas só são renderizados após selecionar o agravo e confirmar abaixo (reduz carga inicial).")
        municipal_master = get_optional(folder, "municipal_master")

        if period_df.empty:
            st.warning("Sem dados para mapa no período/filtro atual.")
        else:
            map_targets = sorted(period_df["target"].dropna().astype(str).unique().tolist())
            map_default_idx = 0
            if default_chart_targets and default_chart_targets[0] in map_targets:
                map_default_idx = map_targets.index(default_chart_targets[0])
            map_target = st.selectbox("Agravo/alvo para o mapa", map_targets, index=map_default_idx)
            map_metric = st.selectbox(
                "Indicador do mapa",
                [
                    "banda_risco",
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
            # Anexa IBGE + banda territorial/ML para coroplético
            if "codigo_ibge" not in map_df.columns:
                mm_ibge = get_optional(folder, "municipal_master")
                if mm_ibge is not None and not mm_ibge.empty and {"municipio", "codigo_ibge"}.issubset(mm_ibge.columns):
                    mmj = mm_ibge[["municipio", "codigo_ibge"]].copy()
                    mmj["municipio"] = mmj["municipio"].map(norm_municipio)
                    map_df["municipio"] = map_df["municipio"].map(norm_municipio)
                    map_df = map_df.merge(mmj, on="municipio", how="left")
            if "banda_risco" not in map_df.columns:
                if not df_risco.empty and "banda_risco" in df_risco.columns:
                    br = df_risco[["municipio", "banda_risco"] + (
                        ["percentil_estadual"] if "percentil_estadual" in df_risco.columns else []
                    )].copy()
                    br["municipio"] = br["municipio"].map(norm_municipio)
                    map_df["municipio"] = map_df["municipio"].map(norm_municipio)
                    map_df = map_df.merge(br, on="municipio", how="left")
                elif not df_ml_risco.empty and "banda_risco" in df_ml_risco.columns:
                    br = df_ml_risco.copy()
                    if "target" in br.columns:
                        br = br[br["target"].astype(str).eq(map_target)]
                    if "prob_alerta_proxima_janela" in br.columns:
                        br = br.sort_values("prob_alerta_proxima_janela", ascending=False)
                    keep = ["municipio", "banda_risco"] + [
                        c for c in ("percentil_estadual", "banda_absoluta", "banda_percentil") if c in br.columns
                    ]
                    br = br.drop_duplicates("municipio", keep="first")[keep]
                    br["municipio"] = br["municipio"].map(norm_municipio)
                    map_df["municipio"] = map_df["municipio"].map(norm_municipio)
                    map_df = map_df.merge(br, on="municipio", how="left")
            if map_metric == "banda_risco" and "banda_risco" not in map_df.columns:
                st.warning("Coluna `banda_risco` ainda não disponível — rode o ML/integração ou escolha outro indicador.")
            if not render_map:
                st.info("Selecione o agravo/indicador e marque **Renderizar mapa agora** para carregar a malha.")
                with st.expander("Prévia tabular do agravo (sem mapa)"):
                    show_table(map_df.head(50), "Prévia municipal", max_rows=50, key="map_prev")
            else:
                geojson = None
                props_df = pd.DataFrame()
                if found_geo:
                    geojson, props_df, geo_msg = load_geojson_or_shp(str(found_geo))
                    st.caption(geo_msg)
                else:
                    st.caption(
                        "Malha ausente: coloque `geo/mt_municipios.geojson` (municípios de MT com código IBGE) "
                        "para ativar o coroplético."
                    )

                if geojson is not None and not props_df.empty:
                    merged = join_shape_with_period(props_df, map_df)
                    fig = make_choropleth(
                        geojson,
                        merged,
                        map_metric,
                        f"Mapa municipal — {map_target} | {map_metric} | {analysis_year}-SE{week_start:02d} a SE{week_end:02d}",
                    )
                    if fig is not None:
                        safe_plotly(fig, "Mapa coroplético")
                    else:
                        st.warning("A malha foi carregada, mas não foi possível cruzar os municípios com os dados do dashboard.")
                        show_table(map_df, "Tabela usada no mapa", key="map_fail")
                else:
                    if municipal_master is None or municipal_master.empty:
                        st.info("Sem shapefile/GeoJSON e sem municipal_master.csv para mapa de pontos.")
                        show_table(map_df, "Tabela municipal filtrada", key="map_nomm")
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
                            show_table(map_df, "Tabela municipal filtrada", key="map_noll")
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
                            safe_plotly(fig, "Mapa de pontos")

                col_a, col_b = st.columns(2)
                with col_a:
                    show_table(
                        map_df.sort_values(["prioridade_score", map_metric], ascending=[False, False]).head(50),
                        "Municípios do agravo selecionado",
                        max_rows=50,
                        key="map_muns",
                    )
                with col_b:
                    silent = map_df[(map_df["silencio_laboratorial"]) | (map_df["baixo_uso_lacen"])]
                    show_table(silent.head(50), "Silêncio laboratorial ou baixo uso do LACEN", max_rows=50, key="map_sil")


# =============================================================================
# Módulo: Integração epidemiológica (SINAN/SIM/CNES + Clima)
# =============================================================================
elif modulo == "Integração epidemiológica":
    sub_int = st.radio(
        "Subvisão",
        ["SINAN / SIM / CNES", "Clima e ambiente"],
        horizontal=True,
        key="sub_integracao",
    )
    df_sinan_weekly = get_optional(folder, "sinan_weekly")
    df_sim_weekly = get_optional(folder, "sim_weekly")
    cnes_capacity = get_optional(folder, "cnes_capacity")
    climate_weekly = get_optional(folder, "climate_weekly")
    climate_assoc = get_optional(folder, "climate_assoc")

    if sub_int == "SINAN / SIM / CNES":
        st.subheader("Integração LACEN × SINAN × SIM × CNES")
        st.caption("Compara exames, notificações, óbitos e capacidade instalada no território.")
        if period_df.empty:
            st.warning("Sem dados no período/filtros selecionados.")
        else:
            exames = float(period_df["tests_periodo"].sum()) if "tests_periodo" in period_df.columns else 0.0
            notif = float(period_df["notificacoes_periodo"].sum()) if "notificacoes_periodo" in period_df.columns else 0.0
            obitos = float(period_df["obitos_sim_periodo"].sum()) if "obitos_sim_periodo" in period_df.columns else 0.0

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
            i1.metric("Exames LACEN (Observado)", format_int(exames))
            i2.metric("Notificações SINAN (Observado)", format_int(notif))
            i3.metric("Óbitos SIM (Observado)", format_int(obitos) if sim_ok else "—")
            i4.metric("Exames / notificação (Derivado)", format_num(safe_div(exames, notif)) if notif else "—")
            if not sim_ok:
                st.caption("SIM: arquivo sem anos epidemiológicos válidos — reconstruir `sim_weekly_municipio.csv` no pipeline.")

            integ = period_df.groupby("municipio", as_index=False).agg(
                exames=("tests_periodo", "sum") if "tests_periodo" in period_df.columns else ("municipio", "size"),
                positivos=("positivos_periodo", "sum") if "positivos_periodo" in period_df.columns else ("municipio", "size"),
                notificacoes=("notificacoes_periodo", "sum") if "notificacoes_periodo" in period_df.columns else ("municipio", "size"),
                obitos_sim=("obitos_sim_periodo", "sum") if "obitos_sim_periodo" in period_df.columns else ("municipio", "size"),
            )

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
                    key="int_sinan",
                )

    else:  # Clima
        st.subheader("Clima, ambiente e vulnerabilidade")

        if climate_assoc is not None and not climate_assoc.empty:
            ca = climate_assoc.copy()
            tgt = first_col(ca, ["target", "alvo", "agravo"])
            if tgt and selected_targets:
                ca = ca[ca[tgt].isin(selected_targets)]
            show_table(ca, "Associação clima-doença pré-calculada", max_rows=1000, key="clim_assoc")
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
                show_table(runtime_ca, "Associação exploratória clima x indicadores", max_rows=1000, key="clim_runtime")
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
                safe_plotly(fig, "Clima correlações")

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
                safe_plotly(fig, "Série climática")


# =============================================================================
# Módulo: Predição e alertas
# =============================================================================
elif modulo == "Predição e alertas":
    sub_pred = st.radio(
        "Subvisão",
        ["Alertas e recomendações", "Alertas próximos dias", "Sinais preditivos", "Séries e predição"],
        horizontal=True,
        key="sub_predicao",
    )
    df_ml_forecast = get_optional(folder, "ml_forecast")
    df_ml_anomalias = get_optional(folder, "ml_anomalias")
    df_ml_backtest = get_optional(folder, "ml_backtest")
    forecast = get_optional(folder, "forecast")
    _bf = get_optional(folder, "briefing_epi")
    if not _bf.empty and "se" in _bf.columns:
        st.caption(
            f"Cruzar Predito abaixo com **Observado** do briefing CIEVS "
            f"(SE {_bf['se'].iloc[0]}) na Visão executiva — 5 perguntas."
        )

    if sub_pred == "Alertas e recomendações":
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
                    show_table(with_acao(manager_alerts).head(100), "Alertas gestores (período)", max_rows=100, key="pred_alertas")
                st.download_button(
                    "Baixar alertas gestores (CSV)",
                    data=manager_alerts.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"alertas_gestores_periodo_{analysis_year}_SE{week_start:02d}_SE{week_end:02d}_proximos_{horizon_days}_dias.csv",
                    mime="text/csv",
                    key="dl_alertas_gestores",
                )
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
                    show_table(al.head(100), "integrated_alerts (filtrado)", max_rows=100, key="pred_integ_al")

    elif sub_pred == "Alertas próximos dias":
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

            st.download_button(
                "Baixar alertas gestores (CSV em memória)",
                data=manager_alerts.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"alertas_gestores_periodo_{analysis_year}_SE{week_start:02d}_SE{week_end:02d}_proximos_{horizon_days}_dias.csv",
                mime="text/csv",
                key="dl_alertas_prox",
            )

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

            show_table(msg_df, "Fila de alertas para gestores", max_rows=2000, key="pred_msg")

    elif sub_pred == "Sinais preditivos":
        st.subheader("Sinais preditivos — ML sklearn_v2 (Predito)")
        st.caption(
            "Forecast EWMA + anomalias; risco/silêncio com Gradient Boosting calibrado por família. "
            "Drivers explicam por que o município aparece. Não treina no DW."
        )
        with st.expander("Assistente de sala de situação (somente agregados)", expanded=False):
            pergunta = st.text_input(
                "Pergunta",
                value="Quais 5 municípios priorizar esta semana e por quê?",
                key="assistente_pergunta",
            )
            if st.button("Responder com evidência", key="assistente_btn"):
                try:
                    from lacen_assistente import responder_sala_situacao, talvez_enriquecer_com_llm
                    resp = responder_sala_situacao(pergunta, folder)
                    resp = talvez_enriquecer_com_llm(resp, pergunta)
                    st.markdown(resp.get("resposta", ""))
                    st.caption(f"Fonte: {resp.get('fonte', '')}")
                    if resp.get("citacoes"):
                        with st.expander("Citações (linhas dos CSVs)"):
                            for c in resp["citacoes"][:10]:
                                st.code(c)
                except Exception as exc:
                    st.warning(f"Assistente indisponível: {exc}")

        ml_missing = all(df.empty for df in (df_ml_forecast, df_ml_anomalias, df_ml_risco, df_ml_silencio))
        if ml_missing:
            st.info(
                "Arquivos ML ainda não gerados. Rode: "
                "`python -m ml.run_ml_pipeline --outdir saida_pipeline`"
            )
        else:
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Séries forecast (Predito)", format_int(len(df_ml_forecast)))
            k2.metric("Anomalias (Derivado)", format_int(len(df_ml_anomalias)))
            alto_r = int(df_ml_risco["faixa_predita"].astype(str).isin(["alto", "muito_alto"]).sum()) if not df_ml_risco.empty and "faixa_predita" in df_ml_risco.columns else 0
            k3.metric("Risco alto/muito alto (Predito)", format_int(alto_r))
            crit_s = int((df_ml_silencio.get("faixa_silencio_predita", pd.Series(dtype=str)).astype(str) == "silencio_critico").sum()) if not df_ml_silencio.empty else 0
            k4.metric("Silêncio crítico predito", format_int(crit_s))

            if not df_ml_backtest.empty:
                st.markdown("##### Backtest temporal (alerta SE t → confirmação SE t+1)")
                bt = df_ml_backtest.copy()
                show_table(
                    bt[[c for c in [
                        "modelo", "escopo", "status", "metodo", "threshold", "auc", "confirmacao",
                        "precision_at_20", "precision_at_50", "precision", "recall", "brier",
                        "n", "n_alerta_emitido", "n_confirmado", "n_train_weeks", "n_test_weeks",
                    ] if c in bt.columns]],
                    "ml_backtest_summary",
                    max_rows=50,
                    key="pred_bt",
                )
                glob = bt[bt["escopo"].astype(str).eq("global")] if "escopo" in bt.columns else bt
                if not glob.empty and "auc" in glob.columns:
                    cal = glob[glob["metodo"].astype(str).str.contains("calibrado", na=False)] if "metodo" in glob.columns else glob
                    use = cal if not cal.empty else glob
                    auc_risco = use.loc[use["modelo"].astype(str).eq("risco"), "auc"]
                    auc_sil = use.loc[use["modelo"].astype(str).eq("silencio"), "auc"]
                    p20 = use.loc[use["modelo"].astype(str).eq("risco"), "precision_at_20"] if "precision_at_20" in use.columns else pd.Series(dtype=float)
                    cbt1, cbt2, cbt3 = st.columns(3)
                    cbt1.metric("AUC risco (teste)", format_num(float(auc_risco.iloc[0])) if len(auc_risco) and pd.notna(auc_risco.iloc[0]) else "—")
                    cbt2.metric("AUC silêncio (teste)", format_num(float(auc_sil.iloc[0])) if len(auc_sil) and pd.notna(auc_sil.iloc[0]) else "—")
                    cbt3.metric("Precisão@20 risco", format_num(float(p20.iloc[0])) if len(p20) and pd.notna(p20.iloc[0]) else "—")

            st.markdown("##### Previsão de demanda (estadual por agravo)")
            if df_ml_forecast.empty:
                st.caption("Sem `ml_forecast_demanda.csv`.")
            else:
                fc = df_ml_forecast.copy()
                if selected_targets and "target" in fc.columns:
                    fc = fc[fc["target"].isin(selected_targets)]
                top_n_fc = st.slider("Agravos no gráfico de forecast", 5, 20, 5, key="top_n_forecast")
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
                        title=f"Exames previstos — top {max(len(top_targets), 1)} agravos (EWMA · Predito)",
                        labels={"forecast_step": "Semanas à frente", "forecast_tests": "Exames previstos", "target": "Agravo"},
                    )
                    safe_plotly(fig, "Forecast demanda")
                with st.expander("Tabela de forecast (completa filtrada)"):
                    show_table(fc.head(100), "ml_forecast_demanda", max_rows=100, key="pred_fc")

            st.markdown("##### Anomalias detectadas")
            if df_ml_anomalias.empty:
                st.caption("Nenhuma anomalia na última semana / arquivo ausente.")
            else:
                an = df_ml_anomalias.copy()
                if selected_targets and "target" in an.columns:
                    an = an[an["target"].isin(selected_targets)]
                if selected_muns and "municipio" in an.columns:
                    an = an[an["municipio"].map(norm_municipio).isin(selected_muns)]
                show_table(an.head(50), "Top anomalias", max_rows=50, key="pred_an")

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
                            color="banda_risco" if "banda_risco" in top_rr.columns else (
                                "faixa_predita" if "faixa_predita" in top_rr.columns else None
                            ),
                            orientation="h",
                            title="Probabilidade de alerta — próxima janela (Predito)",
                            labels={"prob_alerta_proxima_janela": "Probabilidade", "municipio": "Município"},
                        )
                        safe_plotly(fig, "Risco predito")
                    if "banda_risco" in rr.columns:
                        st.caption(
                            "Bandas: absoluto (risco/positividade/limiar) × percentil estadual da prob. ML; "
                            "final = max dos dois."
                        )
                    with st.expander("Tabela risco predito + drivers"):
                        show_table(
                            rr.head(50)[[c for c in [
                                "municipio", "target", "familia", "prob_alerta_proxima_janela",
                                "limiar_operacional", "acima_limiar", "faixa_predita",
                                "banda_risco", "banda_absoluta", "banda_percentil",
                                "percentil_estadual", "criterio_banda", "risco_composto",
                                "drivers", "acao_sugerida", "metodo",
                            ] if c in rr.columns]],
                            "ml_risco_predito",
                            max_rows=50,
                            key="pred_rr",
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
                            title="Probabilidade de silêncio — próxima janela (Predito)",
                            labels={"prob_silencio_proxima_janela": "Probabilidade", "municipio": "Município"},
                        )
                        safe_plotly(fig, "Silêncio predito")
                    with st.expander("Tabela silêncio predito"):
                        show_table(
                            ss.head(50)[[c for c in ["municipio", "target", "prob_silencio_proxima_janela", "faixa_silencio_predita", "acao_sugerida"] if c in ss.columns]],
                            "ml_silencio_predito",
                            max_rows=50,
                            key="pred_ss",
                        )

    else:  # Séries e predição
        st.subheader("Séries históricas e predição operacional curta")

        hist_targets = sorted(wf["target"].dropna().astype(str).unique().tolist())
        chart_default = [t for t in default_chart_targets if t in hist_targets] or hist_targets[: min(5, len(hist_targets))]
        chosen_hist_targets = st.multiselect(
            "Agravos/alvos para série histórica (padrão: top 5 por volume)",
            hist_targets,
            default=chart_default,
            key="hist_targets_sel",
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
                title=f"Série histórica semanal — {metric} (Observado/Derivado)",
                labels={"periodo_data": "Semana epidemiológica", metric: metric, "target": "Agravo/alvo"},
            )
            if metric == "positividade":
                fig.update_yaxes(tickformat=".0%")
            safe_plotly(fig, "Série histórica")

            pred = period_df[period_df["target"].isin(chosen_hist_targets)] if chosen_hist_targets else period_df
            pred_cols = [
                "prioridade", "municipio", "target", "periodo_analise", "cenario_operacional",
                "projecao_solicitacoes_proximos_dias", "projecao_positivos_proximos_dias",
                "positividade_projetada_proximos_dias", "janela_alerta_proximos_dias",
            ]
            show_table(pred[[c for c in pred_cols if c in pred.columns]].head(500), "Projeção operacional para próximos dias (Predito)", max_rows=500, key="series_pred")

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
                    title=f"Forecast integrado — {fc_value} (Predito)",
                )
                safe_plotly(fig, "Forecast integrado")
                show_table(fc, "Tabela forecast integrada", max_rows=1000, key="series_fc")
            else:
                st.info("Forecast encontrado, mas não foi possível identificar uma coluna numérica de previsão.")
        else:
            st.info("forecast_integrated_statewide.csv não encontrado. O painel usa projeção operacional curta baseada no período selecionado.")


# =============================================================================
# Módulo: Dados e qualidade
# =============================================================================
elif modulo == "Dados e qualidade":
    sub_dados = st.radio(
        "Subvisão",
        ["Tabelas e qualidade", "Histórico anual"],
        horizontal=True,
        key="sub_dados",
    )
    schema = get_optional(folder, "schema")
    backlog = get_optional(folder, "backlog")
    cnes_capacity = get_optional(folder, "cnes_capacity")

    if sub_dados == "Tabelas e qualidade":
        st.subheader("Tabelas, qualidade e exportações")

        df_rede = get_optional(folder, "indicadores_rede")
        if not df_rede.empty:
            st.markdown("##### Desempenho da rede laboratorial (TAT / backlog / rejeição)")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Municípios MT", format_int(len(df_rede)))
            r2.metric(
                "TAT mediano (dias)",
                format_num(df_rede["tat_mediano_dias"].median()) if "tat_mediano_dias" in df_rede.columns else "—",
            )
            r3.metric(
                "% liberado ≤7d (mediana)",
                format_pct(df_rede["pct_liberado_7d"].median()) if "pct_liberado_7d" in df_rede.columns else "—",
            )
            r4.metric(
                "Backlog pendente",
                format_int(df_rede["backlog_estimado"].sum()) if "backlog_estimado" in df_rede.columns else "—",
            )
            resumo_path = Path(folder) / "indicadores_rede_resumo.csv"
            if resumo_path.exists():
                try:
                    rs = pd.read_csv(resumo_path, nrows=1)
                    if not rs.empty and "tat_mediano_estadual" in rs.columns:
                        st.caption(
                            f"Resumo estadual GAL: TAT mediano {format_num(rs['tat_mediano_estadual'].iloc[0])} dias "
                            f"· {format_int(rs['n_municipios'].iloc[0]) if 'n_municipios' in rs.columns else '—'} municípios "
                            f"· fonte `{rs['fonte'].iloc[0] if 'fonte' in rs.columns else 'gal'}`"
                        )
                except Exception:
                    pass
            if "pct_liberado_48h" in df_rede.columns and df_rede["pct_liberado_48h"].notna().any():
                st.caption(
                    f"% liberado ≤48h (mediana municipal · Observado): "
                    f"{format_pct(df_rede['pct_liberado_48h'].median())} · "
                    f"TAT p90 mediano: {format_num(df_rede['tat_p90_dias'].median()) if 'tat_p90_dias' in df_rede.columns else '—'} dias"
                )
            show_table(
                df_rede.head(50)[[c for c in [
                    "municipio", "exames", "tat_mediano_dias", "tat_p90_dias",
                    "tat_lab_mediano_dias", "logistica_mediana_dias",
                    "pct_liberado_48h", "pct_liberado_7d", "pct_liberado_14d", "pct_rejeitado",
                    "backlog_estimado", "fonte", "interpretacao",
                ] if c in df_rede.columns]],
                "indicadores_rede_laboratorial",
                max_rows=50,
                key="dados_rede",
            )
            df_rede_fam = get_optional(folder, "indicadores_rede_familia")
            if not df_rede_fam.empty:
                st.markdown("##### SLA por família de agravo (Observado · GAL)")
                show_table(
                    df_rede_fam.head(40)[[c for c in [
                        "granularidade", "familia", "municipio", "exames",
                        "pct_liberado_48h", "tat_p90_dias", "pct_liberado_7d",
                        "pct_rejeitado", "backlog_estimado",
                    ] if c in df_rede_fam.columns]],
                    "indicadores_rede_por_familia",
                    max_rows=40,
                    key="dados_rede_fam",
                )
            if not df_emergencia.empty:
                st.markdown("##### Indicadores de emergência (Observado · Derivado · Predito)")
                show_table(
                    df_emergencia.head(40)[[c for c in [
                        "municipio", "indice_pressao_rede", "faixa_pressao",
                        "prob_pressao_alta_proxima_janela", "faixa_pressao_predita",
                        "pct_liberado_48h", "tat_p90_dias", "sla_crise",
                        "silencio_gal_alerta", "divergencia_gal_notif",
                        "prioridade_emergencia", "acao_sugerida", "prazo_acao",
                    ] if c in df_emergencia.columns]],
                    "indicadores_emergencia",
                    max_rows=40,
                    key="dados_emerg",
                )
            if not df_emergencia_confirmacao.empty:
                rc = df_emergencia_confirmacao.iloc[0]
                tipo_c = str(rc.get("tipo_sinal") or "Derivado")
                st.markdown(
                    f"##### Confirmação semanal de alertas de emergência ({tipo_c})"
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric(
                    f"Taxa confirmação geral ({tipo_c})",
                    format_pct(rc.get("taxa_confirmacao_geral"))
                    if pd.notna(rc.get("taxa_confirmacao_geral")) else "n/d",
                )
                c2.metric(
                    f"Confirmação silêncio GAL ({tipo_c})",
                    format_pct(rc.get("taxa_confirmacao_silencio_gal"))
                    if pd.notna(rc.get("taxa_confirmacao_silencio_gal")) else "n/d",
                )
                c3.metric(
                    "Alertas avaliados",
                    format_int(rc.get("n_alertas_avaliados") or 0),
                )
                c4.metric(
                    "SE carimbadas (histórico)",
                    format_int(rc.get("n_se_historico_carimbado") or 0),
                )
                if pd.notna(rc.get("interpretacao")):
                    st.caption(str(rc.get("interpretacao")))
                if pd.notna(rc.get("nota")):
                    st.caption(str(rc.get("nota")))
                if pd.notna(rc.get("modo_confirmacao")):
                    st.caption(f"Modo: {rc.get('modo_confirmacao')} · fonte={rc.get('fonte')}")
            if not df_ml_pressao.empty:
                st.markdown("##### Pressão de rede predita (Predito)")
                show_table(
                    df_ml_pressao.head(40)[[c for c in [
                        "municipio", "prob_pressao_alta_proxima_janela", "faixa_pressao_predita",
                        "indice_pressao_rede", "acima_limiar", "drivers", "metodo",
                    ] if c in df_ml_pressao.columns]],
                    "ml_pressao_rede_predito",
                    max_rows=40,
                    key="dados_pressao_ml",
                )

        if not df_qualidade.empty:
            st.markdown("##### Confiança / qualidade do dado (últimas 8 SE)")
            q1, q2, q3 = st.columns(3)
            q1.metric("Municípios avaliados", format_int(len(df_qualidade)))
            if "faixa_confianca" in df_qualidade.columns:
                q2.metric(
                    "Confiança baixa",
                    format_int((df_qualidade["faixa_confianca"].astype(str) == "baixa").sum()),
                )
            else:
                q2.metric("Confiança baixa", "—")
            if "gap_sinan_sem_exame" in df_qualidade.columns:
                q3.metric(
                    "Gap SINAN sem exame",
                    format_int(df_qualidade["gap_sinan_sem_exame"].fillna(False).sum()),
                )
            else:
                q3.metric("Gap SINAN sem exame", "—")
            show_table(
                df_qualidade.head(50)[[c for c in [
                    "municipio", "confianca_dado", "faixa_confianca", "exames", "notif_sinan",
                    "notif_join", "semanas_com_dado", "gap_sinan_sem_exame", "join_sinan_fraco",
                    "interpretacao",
                ] if c in df_qualidade.columns]],
                "qualidade_dado_municipal (pior confiança primeiro)",
                max_rows=50,
                key="dados_qual",
            )
        else:
            st.info("Sem `qualidade_dado_municipal.csv`. Rode a integração final para gerar.")

        export_tables = {
            "analise_periodo": period_df,
            "alertas_gestores_proximos_dias": manager_alerts,
            "municipios_em_risco": df_risco,
            "municipios_silenciosos": df_silenciosos,
            "taxa_utilizacao_lacen": df_utilizacao,
            "fila_operacional": fila_operacional,
            "qualidade_dado_municipal": df_qualidade,
            "municipio_vizinhos": df_vizinhos,
            "ml_risco_predito": df_ml_risco,
            "ml_silencio_predito": df_ml_silencio,
            "weekly_filtrado": wf,
            "annual": annual,
            "summary_municipio": summary_mun,
            "integrated_alerts": alerts,
        }
        table_choice = st.selectbox("Tabela para visualizar", list(export_tables.keys()) + [
            "ml_forecast_demanda", "ml_anomalias", "ml_backtest_summary",
            "schema_catalog", "backlog", "cnes_capacity",
        ])
        if table_choice in export_tables:
            show_table(export_tables[table_choice], table_choice, max_rows=2000, key=f"dados_{table_choice}")
        elif table_choice == "ml_forecast_demanda":
            show_table(get_optional(folder, "ml_forecast"), table_choice, max_rows=2000, key="dados_ml_fc")
        elif table_choice == "ml_anomalias":
            show_table(get_optional(folder, "ml_anomalias"), table_choice, max_rows=2000, key="dados_ml_an")
        elif table_choice == "ml_backtest_summary":
            show_table(get_optional(folder, "ml_backtest"), table_choice, max_rows=2000, key="dados_ml_bt")
        elif table_choice == "schema_catalog":
            show_table(schema if schema is not None else pd.DataFrame(), table_choice, max_rows=2000, key="dados_schema")
        elif table_choice == "backlog":
            show_table(backlog if backlog is not None else pd.DataFrame(), table_choice, max_rows=2000, key="dados_backlog")
        elif table_choice == "cnes_capacity":
            show_table(cnes_capacity if cnes_capacity is not None else pd.DataFrame(), table_choice, max_rows=2000, key="dados_cnes")

        diag = pd.DataFrame([
            {"item": "Linhas weekly", "valor": str(len(weekly))},
            {"item": "Agravos/alvos weekly", "valor": str(weekly["target"].nunique())},
            {"item": "Municípios weekly", "valor": str(weekly["municipio"].nunique())},
            {"item": "Ano mínimo", "valor": str(min_year)},
            {"item": "Ano máximo", "valor": str(max_year)},
            {"item": "Ano analisado", "valor": str(analysis_year)},
            {"item": "Período analisado", "valor": f"SE{week_start:02d}-SE{week_end:02d}"},
            {"item": "Alertas gestores", "valor": str(len(manager_alerts))},
            {"item": "Qualidade do dado", "valor": str(len(df_qualidade))},
            {"item": "Arestas de vizinhos", "valor": str(len(df_vizinhos))},
            {"item": "Pasta de dados", "valor": str(folder)},
            {"item": "MODO_ADMIN", "valor": str(MODO_ADMIN)},
        ])
        safe_dataframe(diag)

    else:  # Histórico anual
        st.subheader("Histórico anual por agravo/alvo")

        if annual.empty:
            st.info("integrated_annual_summary.csv vazio ou ausente.")
        else:
            af = annual[annual["target"].isin(selected_targets)].copy()
            if af.empty:
                st.info("Sem dados anuais para o filtro atual.")
            else:
                chart_tgts = top_targets_by_volume(af, selected_targets, n=5, volume_col="testes")
                af_chart = af[af["target"].isin(chart_tgts)].copy()
                st.caption(f"Gráficos: top {len(chart_tgts)} agravos por volume ({', '.join(chart_tgts)}). Tabela abaixo mantém o filtro completo.")
                c1, c2 = st.columns(2)
                with c1:
                    fig = px.line(
                        af_chart.sort_values(["target", "ano"]),
                        x="ano",
                        y="positividade_media",
                        color="target",
                        markers=True,
                        title="Positividade anual por agravo/alvo",
                    )
                    fig.update_yaxes(tickformat=".0%")
                    safe_plotly(fig, "Positividade anual")
                with c2:
                    fig = px.line(
                        af_chart.sort_values(["target", "ano"]),
                        x="ano",
                        y="testes",
                        color="target",
                        markers=True,
                        title="Solicitações/testes anuais por agravo/alvo",
                    )
                    safe_plotly(fig, "Testes anuais")

                c3, c4 = st.columns(2)
                with c3:
                    fig = px.line(
                        af_chart.sort_values(["target", "ano"]),
                        x="ano",
                        y="notificacoes",
                        color="target",
                        markers=True,
                        title="Notificações anuais por agravo/alvo",
                    )
                    safe_plotly(fig, "Notificações anuais")
                with c4:
                    fig = px.line(
                        af_chart.sort_values(["target", "ano"]),
                        x="ano",
                        y="incidencia_100k",
                        color="target",
                        markers=True,
                        title="Incidência anual por 100 mil",
                    )
                    safe_plotly(fig, "Incidência anual")

                show_table(af, "Resumo anual integrado", max_rows=1000, key="dados_anual")


footer_institucional()
