#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline analítica para bases históricas do LACEN-MT / GAL (2010+).

Funcionalidades principais
--------------------------
1. Leitura de CSV/XLSX/XLS/Parquet em lote.
2. Normalização dos 6 campos de resultado (Campo_Resultado_1..6) em formato longo.
3. Limpeza de HTML, espaços, rótulos vazios e problemas comuns de codificação.
4. Classificação automática de alvo, papel da medida e classe do resultado.
5. Geração de indicadores:
   - cobertura / esquemas de preenchimento
   - backlog por status
   - positividade por alvo, ano, semana epidemiológica e município
   - alertas precoces por volume e positividade
   - previsão simples para 4 semanas (baseline sazonal + tendência recente)
   - saídas finais corrigidas de arboviroses em nível de caso

Uso básico
----------
python lacen_analysis_pipeline.py \
  --inputs "D:/LACEN/gal_2010.csv" "D:/LACEN/gal_2011.csv" "D:/LACEN/gal_2025.csv" \
  --outdir "D:/LACEN/saida_pipeline" \
  --start-year 2010

Dependências
------------
pandas, numpy, openpyxl, pyarrow (opcional, recomendado)
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# -----------------------------------------------------------------------------
# Configuração geral
# -----------------------------------------------------------------------------
RESULT_COLS = [f"Campo_Resultado_{i}" for i in range(1, 7)]
DATE_CANDIDATES = [
    "Data_Solicitacao_dt",
    "Data_Coleta_dt",
    "Data_Liberacao_dt",
    "Data_Cadastro_dt",
    "DT_Atualizacao",
]
TEXT_COLS_BASE = [
    "Agravo_Requisicao",
    "Municipio_Residencia_Paciente",
    "Municipio_Solicitante",
    "Municipio_Notificacao_Sinan",
    "Municipio_Notificacao_Gal",
    "Exame",
    "Metodologia",
    "Status_Exame",
    "Observacao_Resultado",
    *RESULT_COLS,
]
ID_CANDIDATES = ["Sequencial", "Codigo_Amostra", "Requisicao", "Num_Interno"]

POSITIVE_TERMS = [
    r"\bdetect[aá]vel\b",
    r"\breagente\b",
    r"\bpositivo\b",
    r"\bpresente\b",
    r"\bmtb detectado\b",
    r"\bdetected\b",
    r"\bresistente\b",
    r"\bpositiva\b",
]
NEGATIVE_TERMS = [
    r"n[aã]o\s+detect[aá]vel",
    r"n[aã]o\s+reagente",
    r"\bnegativo\b",
    r"\bausente\b",
    r"\bnot detected\b",
    r"\bnegativa\b",
    r"\bsens[ií]vel\b",  # útil para resistência antimicrobiana
]
TRACE_TERMS = [r"\btra[cç]o?s\b", r"trace"]
INCONCLUSIVE_TERMS = [
    r"inconclus",
    r"indeterm",
    r"insatisfat",
    r"insuficient",
    r"inv[aá]lid",
    r"contamin",
    r"repetir",
]
PENDING_TERMS = [
    r"em\s+process",
    r"aguardando",
    r"pendente",
    r"sem\s+resultado",
    r"n[aã]o\s+realizado",
]

TARGET_RULES = [
    (r"\bdengue\b", "dengue"),
    (r"\bzika\b", "zika"),
    (r"chikung", "chikungunya"),
    (r"influenza\s*a", "influenza_a"),
    (r"influenza\s*b", "influenza_b"),
    (r"sars\s*cov\s*[- ]?2|covid", "sars_cov_2"),
    (r"v[íi]rus\s+sincicial|vsr|rsv", "vsr"),
    (r"adenov[ií]rus", "adenovirus"),
    (r"metapneumov[ií]rus", "metapneumovirus"),
    (r"parainfluenza", "parainfluenza"),
    (r"rinov[ií]rus|enterov[ií]rus", "rinovirus_enterovirus"),
    (r"leptospir", "leptospira"),
    (r"hantav", "hantavirus"),
    (r"hepatite\s*a", "hepatite_a"),
    (r"hepatite\s*b|hbsag|anti-hbc|anti-hbs|hbv", "hepatite_b_hbv"),
    (r"hepatite\s*c|hcv", "hepatite_c_hcv"),
    (r"hepatite\s*d|hdv", "hepatite_d_hdv"),
    (r"hepatite\s*e|hev", "hepatite_e_hev"),
    (r"micobacterium\s+tuberculosis|\bmtb\b", "mtb"),
    (r"rifampicina", "rifampicina"),
    (r"baciloscopia|ziehl|auramina", "baciloscopia"),
    (r"chlamydia", "chlamydia_trachomatis"),
    (r"gonorr|neisseria", "neisseria_gonorrhoeae"),
    (r"hiv|carga\s+viral\s+hiv", "hiv"),
    (r"dengue\s*igm", "dengue_igm"),
    (r"chikungunya\s*igm", "chikungunya_igm"),
    (r"zika\s*igm", "zika_igm"),
]

SITE_LABEL_TERMS = [
    "lóbulo auricular direito",
    "lóbulo auricular esquerdo",
    "cotovelo direito",
    "cotovelo esquerdo",
    "lesão",
]

ARB_TARGETS = {"dengue", "zika", "chikungunya"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline analítica histórica do LACEN/GAL (2010+)."
    )
    parser.add_argument("--inputs", nargs="+", required=True, help="Arquivos de entrada CSV/XLSX/XLS/Parquet.")
    parser.add_argument("--outdir", required=True, help="Diretório de saída.")
    parser.add_argument("--start-year", type=int, default=2010, help="Ano mínimo a considerar.")
    parser.add_argument("--chunk-size", type=int, default=50000, help="Tamanho do chunk para CSVs grandes.")
    parser.add_argument("--sep", default=None, help="Separador do CSV. Se omitido, tenta detectar.")
    parser.add_argument("--encoding", default=None, help="Encoding do CSV. Se omitido, tenta utf-8-sig e latin1.")
    parser.add_argument("--write-normalized", action="store_true", help="Gravar base normalizada detalhada em CSV/parquet.")
    parser.add_argument("--normalized-format", choices=["csv", "parquet"], default="csv")
    parser.add_argument("--municipality-source", choices=["residencia", "solicitante", "notificacao"], default="residencia")
    parser.add_argument("--min-alert-count", type=int, default=5, help="Contagem mínima para sinalizar alerta.")
    parser.add_argument("--forecast-horizon", type=int, default=4, help="Semanas para previsão simples.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


# -----------------------------------------------------------------------------
# Utilitários de limpeza e parsing
# -----------------------------------------------------------------------------
def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def maybe_fix_mojibake(text: str) -> str:
    if not isinstance(text, str):
        return text
    if any(token in text for token in ["Ã", "Â", "ð", "�"]):
        try:
            fixed = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            if fixed:
                return fixed
        except Exception:
            pass
    return text


def strip_html_and_normalize(text: object) -> str:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return ""
    s = str(text)
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = maybe_fix_mojibake(s)
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_key(text: str) -> str:
    s = strip_html_and_normalize(text).casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip(" :;-_")


def detect_csv_sep(file_path: Path) -> str:
    try:
        sample = file_path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;	|")
        return dialect.delimiter
    except Exception:
        return ","


def choose_encoding(file_path: Path, forced: Optional[str] = None) -> str:
    if forced:
        return forced
    for enc in ("utf-8-sig", "latin1"):
        try:
            with file_path.open("r", encoding=enc, errors="strict") as fh:
                fh.read(2048)
            return enc
        except Exception:
            continue
    return "latin1"


def safe_to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def ensure_columns(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def pick_event_date(df: pd.DataFrame) -> pd.Series:
    event = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for col in DATE_CANDIDATES:
        if col in df.columns:
            converted = safe_to_datetime(df[col])
            event = event.fillna(converted)
    return event


def pick_municipality(df: pd.DataFrame, source: str) -> pd.Series:
    if source == "residencia":
        candidates = [
            "Municipio_Residencia_Paciente",
            "Municipio_Solicitante",
            "Municipio_Notificacao_Sinan",
            "Municipio_Notificacao_Gal",
        ]
    elif source == "solicitante":
        candidates = [
            "Municipio_Solicitante",
            "Municipio_Residencia_Paciente",
            "Municipio_Notificacao_Sinan",
            "Municipio_Notificacao_Gal",
        ]
    else:
        candidates = [
            "Municipio_Notificacao_Sinan",
            "Municipio_Notificacao_Gal",
            "Municipio_Residencia_Paciente",
            "Municipio_Solicitante",
        ]
    out = pd.Series("IGNORADO", index=df.index, dtype="object")
    for col in candidates:
        if col in df.columns:
            values = df[col].map(strip_html_and_normalize)
            out = np.where((pd.Series(out) == "IGNORADO") & (values != ""), values, out)
            out = pd.Series(out, index=df.index)
    out = out.map(lambda x: normalize_key(x).upper() if x else "IGNORADO")
    out = out.replace({"": "IGNORADO", "NAN": "IGNORADO"})
    return out


def extract_label_and_value(raw: str) -> Tuple[str, str]:
    s = strip_html_and_normalize(raw)
    if not s:
        return "", ""
    m = re.match(r"^([^:]{1,120}):\s*(.*)$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s.strip(), ""


def schema_signature(row: pd.Series) -> str:
    labels = []
    for col in RESULT_COLS:
        label, _ = extract_label_and_value(row.get(col, ""))
        labels.append(normalize_key(label) or "vazio")
    return " | ".join(labels)


def has_real_value(raw: str) -> bool:
    label, value = extract_label_and_value(raw)
    if not label and not value:
        return False
    value_norm = normalize_key(value)
    if value_norm in {"", "-", "na", "n/a"}:
        return False
    return True


def match_target_in_text(text: str) -> Optional[str]:
    text_norm = normalize_key(text)
    if not text_norm:
        return None
    for pattern, target in TARGET_RULES:
        if re.search(pattern, text_norm, flags=re.I):
            return target
    return None


def infer_target(label: str, exam: str, methodology: str, agravo: str, previous_target: Optional[str] = None) -> str:
    label_norm = normalize_key(label)
    exam_norm = normalize_key(exam)
    meth_norm = normalize_key(methodology)
    agravo_norm = normalize_key(agravo)

    if any(token in label_norm for token in ["ct", "cut-off", "cut off", "do/co", "d.o/c.o", "d.o./c.o.", "valor"]):
        if previous_target:
            return previous_target

    for context in (label_norm, exam_norm, meth_norm, agravo_norm):
        matched = match_target_in_text(context)
        if matched:
            return matched

    if label_norm in SITE_LABEL_TERMS:
        return label_norm.replace(" ", "_")

    fallback = exam_norm or meth_norm or agravo_norm or label_norm or "nao_classificado"
    fallback = re.sub(r"[^a-z0-9_]+", "_", fallback).strip("_")
    return fallback[:80] or "nao_classificado"


def infer_measure_role(label: str, value: str, target: str) -> str:
    label_norm = normalize_key(label)
    value_norm = normalize_key(value)

    if label_norm in SITE_LABEL_TERMS:
        return "site_result"
    if any(token in label_norm for token in ["ct", "cut-off", "cut off", "do/co", "d.o/c.o", "d.o./c.o."]):
        return "analytic_metric"
    if label_norm == "valor":
        if re.fullmatch(r"[-+]?\d+[\d,\.]*", value_norm):
            return "analytic_metric"
    if any(tok in label_norm for tok in ["copias", "carga viral", "log"]):
        return "quantitative_result"
    if value_norm == "":
        return "empty_field"
    return "qualitative_result"


def classify_outcome(value: str, target: str) -> str:
    value_norm = normalize_key(value)
    if value_norm == "":
        return "empty"
    if any(re.search(p, value_norm, flags=re.I) for p in PENDING_TERMS):
        return "pending"
    if any(re.search(p, value_norm, flags=re.I) for p in TRACE_TERMS):
        return "trace"
    if target == "rifampicina" and re.search(r"sensivel", value_norm, flags=re.I):
        return "susceptible"
    if target == "rifampicina" and re.search(r"resistente", value_norm, flags=re.I):
        return "resistant"
    if any(re.search(p, value_norm, flags=re.I) for p in INCONCLUSIVE_TERMS):
        return "inconclusive"
    if any(re.search(p, value_norm, flags=re.I) for p in NEGATIVE_TERMS):
        return "negative"
    if any(re.search(p, value_norm, flags=re.I) for p in POSITIVE_TERMS):
        return "positive"
    if re.fullmatch(r"[-+]?\d+[\d,\.]*", value_norm):
        return "numeric"
    return "other_text"


def normalize_status(value: str) -> str:
    s = normalize_key(value)
    if s == "":
        return "status_ausente"
    mapping = {
        "exame liberado": "liberado",
        "aguardando triagem": "aguardando_triagem",
        "aguardando processamento": "aguardando_processamento",
        "em analise": "em_analise",
        "cancelado": "cancelado",
        "exame nao realizado": "nao_realizado",
    }
    return mapping.get(s, re.sub(r"[^a-z0-9_]+", "_", s).strip("_"))


def make_record_id(row: pd.Series) -> str:
    parts = []
    for col in ID_CANDIDATES:
        val = strip_html_and_normalize(row.get(col, ""))
        if val:
            parts.append(val)
    if parts:
        return "|".join(parts)
    # fallback determinístico
    fallback_fields = [
        strip_html_and_normalize(row.get("Exame", "")),
        strip_html_and_normalize(row.get("Metodologia", "")),
        strip_html_and_normalize(row.get("Data_Cadastro_dt", "")),
    ]
    return "anon|" + "|".join(fallback_fields)


def normalize_chunk(df: pd.DataFrame, municipality_source: str) -> pd.DataFrame:
    df = ensure_columns(df.copy(), TEXT_COLS_BASE + DATE_CANDIDATES + ID_CANDIDATES)
    for col in TEXT_COLS_BASE:
        df[col] = df[col].map(strip_html_and_normalize)

    df["event_date"] = pick_event_date(df)
    df = df[df["event_date"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["year"] = df["event_date"].dt.year.astype(int)
    iso = df["event_date"].dt.isocalendar()
    df["epi_year"] = iso["year"].astype(int)
    df["epi_week"] = iso["week"].astype(int)
    df["municipio_analitico"] = pick_municipality(df, municipality_source)
    df["status_exame_norm"] = df["Status_Exame"].map(normalize_status)
    df["record_id"] = df.apply(make_record_id, axis=1)

    records: List[Dict[str, object]] = []

    for row in df.itertuples(index=False):
        row_dict = row._asdict()
        prev_target: Optional[str] = None
        for idx, result_col in enumerate(RESULT_COLS, start=1):
            raw = row_dict.get(result_col, "") or ""
            label, value = extract_label_and_value(raw)
            target = infer_target(
                label=label,
                exam=row_dict.get("Exame", ""),
                methodology=row_dict.get("Metodologia", ""),
                agravo=row_dict.get("Agravo_Requisicao", ""),
                previous_target=prev_target,
            )
            role = infer_measure_role(label, value, target)
            outcome = classify_outcome(value, target)
            records.append(
                {
                    "record_id": row_dict["record_id"],
                    "sequencial": row_dict.get("Sequencial", ""),
                    "requisicao": row_dict.get("Requisicao", ""),
                    "codigo_amostra": row_dict.get("Codigo_Amostra", ""),
                    "event_date": row_dict["event_date"],
                    "year": row_dict["year"],
                    "epi_year": row_dict["epi_year"],
                    "epi_week": row_dict["epi_week"],
                    "municipio": row_dict["municipio_analitico"],
                    "agravo": normalize_key(row_dict.get("Agravo_Requisicao", "")) or "ignorado",
                    "exame": strip_html_and_normalize(row_dict.get("Exame", "")),
                    "metodologia": strip_html_and_normalize(row_dict.get("Metodologia", "")),
                    "status_exame": row_dict["status_exame_norm"],
                    "field_index": idx,
                    "field_label": label,
                    "field_value": value,
                    "field_has_real_value": bool(has_real_value(raw)),
                    "schema_signature": schema_signature(pd.Series({c: row_dict.get(c, "") for c in RESULT_COLS})),
                    "target": target,
                    "measure_role": role,
                    "outcome_class": outcome,
                    "observacao_resultado": strip_html_and_normalize(row_dict.get("Observacao_Resultado", "")),
                    "is_released": row_dict["status_exame_norm"] == "liberado",
                }
            )
            if target and role in {"qualitative_result", "quantitative_result", "site_result"}:
                prev_target = target

        # Observação também pode carregar informação útil
        obs = strip_html_and_normalize(row_dict.get("Observacao_Resultado", ""))
        if obs:
            records.append(
                {
                    "record_id": row_dict["record_id"],
                    "sequencial": row_dict.get("Sequencial", ""),
                    "requisicao": row_dict.get("Requisicao", ""),
                    "codigo_amostra": row_dict.get("Codigo_Amostra", ""),
                    "event_date": row_dict["event_date"],
                    "year": row_dict["year"],
                    "epi_year": row_dict["epi_year"],
                    "epi_week": row_dict["epi_week"],
                    "municipio": row_dict["municipio_analitico"],
                    "agravo": normalize_key(row_dict.get("Agravo_Requisicao", "")) or "ignorado",
                    "exame": strip_html_and_normalize(row_dict.get("Exame", "")),
                    "metodologia": strip_html_and_normalize(row_dict.get("Metodologia", "")),
                    "status_exame": row_dict["status_exame_norm"],
                    "field_index": 7,
                    "field_label": "observacao_resultado",
                    "field_value": obs,
                    "field_has_real_value": True,
                    "schema_signature": schema_signature(pd.Series({c: row_dict.get(c, "") for c in RESULT_COLS})),
                    "target": infer_target("observacao_resultado", row_dict.get("Exame", ""), row_dict.get("Metodologia", ""), row_dict.get("Agravo_Requisicao", "")),
                    "measure_role": "observation",
                    "outcome_class": classify_outcome(obs, infer_target("observacao_resultado", row_dict.get("Exame", ""), row_dict.get("Metodologia", ""), row_dict.get("Agravo_Requisicao", ""))),
                    "observacao_resultado": obs,
                    "is_released": row_dict["status_exame_norm"] == "liberado",
                }
            )

    out = pd.DataFrame.from_records(records)
    out["is_interpretable_result"] = (
        out["measure_role"].eq("qualitative_result")
        & out["field_has_real_value"]
        & out["outcome_class"].isin(["positive", "negative", "trace", "inconclusive", "susceptible", "resistant"])
    )
    out["is_positive_like"] = out["outcome_class"].isin(["positive", "trace", "resistant"])
    out["is_negative_like"] = out["outcome_class"].isin(["negative", "susceptible"])
    return out


def classify_arbovirosis_positivity(exame: str, metodologia: str) -> str:
    context = normalize_key(f"{exame} | {metodologia}")
    if any(token in context for token in ["rt-pcr", "rt pcr", "pcr", "biologia molecular", "ns1", "isolamento viral", "antigeno ns1", "antígeno ns1"]):
        return "aguda_confirmatoria"
    if "igm" in context or "mac-elisa" in context or "mac elisa" in context:
        return "aguda_provavel"
    if "igg" in context:
        return "exposicao_previa"
    return "positivo_sem_classificacao"


def extract_arboviroses_positives(norm: pd.DataFrame) -> pd.DataFrame:
    if norm.empty:
        return pd.DataFrame()

    arb = norm[
        norm["target"].isin(ARB_TARGETS)
        & norm["is_released"]
        & norm["field_has_real_value"]
        & norm["is_positive_like"]
        & norm["measure_role"].isin(["qualitative_result", "site_result"])
    ].copy()

    if arb.empty:
        return arb

    arb["classe_resultado"] = arb["outcome_class"]
    arb["classe_positividade"] = [
        classify_arbovirosis_positivity(exame, metodologia)
        for exame, metodologia in zip(arb["exame"], arb["metodologia"])
    ]

    arb = arb.drop_duplicates(
        subset=[
            "record_id",
            "target",
            "exame",
            "metodologia",
            "field_label",
            "field_value",
            "classe_positividade",
        ]
    )

    preferred = [
        "record_id",
        "sequencial",
        "requisicao",
        "codigo_amostra",
        "event_date",
        "year",
        "epi_year",
        "epi_week",
        "municipio",
        "agravo",
        "exame",
        "metodologia",
        "status_exame",
        "target",
        "field_index",
        "field_label",
        "field_value",
        "classe_resultado",
        "classe_positividade",
        "observacao_resultado",
        "schema_signature",
    ]
    existing = [c for c in preferred if c in arb.columns]
    return arb[existing].sort_values(["event_date", "municipio", "target", "exame"]).reset_index(drop=True)




# -----------------------------------------------------------------------------
# Pós-processamento corrigido de arboviroses
# -----------------------------------------------------------------------------
ARB_PATTERN = re.compile(r"DENGUE|ZIKA|CHIK|ARBOV|MAYARO|OROPOUCHE|FEBRE AMARELA", re.I)


def filter_arboviral_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    for col in ["exame", "agravo", "target"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)

    mask = (
        out["exame"].str.contains(ARB_PATTERN, na=False)
        | out["agravo"].str.contains(ARB_PATTERN, na=False)
        | out["target"].str.contains(ARB_PATTERN, na=False)
        | out["target"].isin(["dengue", "zika", "chikungunya"])
    )
    out = out.loc[mask].copy()
    if "event_date" in out.columns:
        out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce")
    out["target"] = (
        out["target"]
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"chikungunia": "chikungunya", "chikungunya ": "chikungunya"})
    )
    return out


def _join_unique(vals: Iterable[object]) -> str:
    uniq: List[str] = []
    for v in vals:
        if pd.isna(v):
            continue
        s = str(v).strip()
        if s and s not in uniq:
            uniq.append(s)
    return " | ".join(uniq)


def _mode_text(vals: Iterable[object]) -> str:
    items = [str(v).strip() for v in vals if not pd.isna(v) and str(v).strip()]
    if not items:
        return ""
    return pd.Series(items).value_counts(dropna=False).index[0]


def build_arb_case_level(df: pd.DataFrame, agudos_only: bool = True) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    detailed: mantém evidências laboratoriais distintas, sem duplicação operacional óbvia.
    cases: consolida para uma linha por requisição/amostra/data/município/alvo.
    """
    if df.empty:
        return df.copy(), df.copy()

    work = filter_arboviral_frame(df)

    if agudos_only:
        work = work[work["classe_positividade"].isin(["aguda_confirmatoria", "aguda_provavel"])].copy()

    # Mantém somente universo arboviral verdadeiro
    work = work[
        work["target"].isin(["dengue", "zika", "chikungunya"])
        | work["exame"].str.contains(ARB_PATTERN, na=False)
        | work["agravo"].str.contains(ARB_PATTERN, na=False)
    ].copy()

    if work.empty:
        return work.copy(), work.copy()

    dedup_subset = [
        "requisicao",
        "codigo_amostra",
        "event_date",
        "municipio",
        "target",
        "exame",
        "metodologia",
        "classe_positividade",
        "field_value",
    ]
    dedup_subset = [c for c in dedup_subset if c in work.columns]
    detailed = work.drop_duplicates(subset=dedup_subset).copy()

    grp_cols = ["requisicao", "codigo_amostra", "event_date", "municipio", "target"]
    grp_cols = [c for c in grp_cols if c in detailed.columns]

    agg_map = {
        "agravo": ("agravo", _mode_text),
        "exames": ("exame", _join_unique),
        "metodologias": ("metodologia", _join_unique),
        "status_exame": ("status_exame", _join_unique),
        "classes_positividade": ("classe_positividade", _join_unique),
        "evidencias": ("field_value", _join_unique),
        "observacoes": ("observacao_resultado", _join_unique),
        "n_evidencias": ("field_value", "count"),
    }
    agg_map = {k: v for k, v in agg_map.items() if v[0] in detailed.columns}

    cases = detailed.groupby(grp_cols, dropna=False).agg(**agg_map).reset_index()

    if "classes_positividade" in cases.columns:
        cases["tipo_caso"] = cases["classes_positividade"].apply(
            lambda x: "confirmatorio_agudo"
            if "aguda_confirmatoria" in str(x)
            else ("provavel_agudo" if "aguda_provavel" in str(x) else "exposicao_previa")
        )
    else:
        cases["tipo_caso"] = ""

    if "event_date" in cases.columns:
        cases["ano"] = pd.to_datetime(cases["event_date"], errors="coerce").dt.year
        cases["mes"] = pd.to_datetime(cases["event_date"], errors="coerce").dt.month
        epi = pd.to_datetime(cases["event_date"], errors="coerce").dt.isocalendar()
        cases["epi_year"] = epi.year.astype("Int64")
        cases["epi_week"] = epi.week.astype("Int64")

    sort_cols_cases = [c for c in ["ano", "mes", "municipio", "target", "event_date", "requisicao"] if c in cases.columns]
    if sort_cols_cases:
        cases = cases.sort_values(sort_cols_cases)

    sort_cols_det = [c for c in ["event_date", "municipio", "target", "requisicao"] if c in detailed.columns]
    if sort_cols_det:
        detailed = detailed.sort_values(sort_cols_det)

    return detailed.reset_index(drop=True), cases.reset_index(drop=True)


def write_arboviroses_corrected_outputs(outdir: Path, arb_pos: pd.DataFrame, arb_agudos: pd.DataFrame) -> None:
    """
    Gera saídas finais corrigidas para uso epidemiológico.
    """
    if arb_pos.empty and arb_agudos.empty:
        return

    todos_detalhado, todos_casos = build_arb_case_level(arb_pos, agudos_only=False)
    agudos_detalhado, agudos_casos = build_arb_case_level(arb_agudos, agudos_only=True)

    # Resumos
    if not agudos_casos.empty and "ano" in agudos_casos.columns:
        resumo_anual = (
            agudos_casos.groupby(["ano", "target"], dropna=False)
            .size()
            .reset_index(name="casos_positivos")
            .sort_values(["ano", "target"])
        )
    else:
        resumo_anual = pd.DataFrame(columns=["ano", "target", "casos_positivos"])

    if not agudos_casos.empty and {"epi_year", "epi_week", "municipio", "target"}.issubset(agudos_casos.columns):
        resumo_se_mun = (
            agudos_casos.groupby(["epi_year", "epi_week", "municipio", "target"], dropna=False)
            .size()
            .reset_index(name="casos_positivos")
            .sort_values(["epi_year", "epi_week", "municipio", "target"])
        )
    else:
        resumo_se_mun = pd.DataFrame(columns=["epi_year", "epi_week", "municipio", "target", "casos_positivos"])

    controle = pd.DataFrame(
        {
            "dataset": ["todos_filtrado", "todos_casos", "agudos_filtrado", "agudos_casos"],
            "linhas": [len(todos_detalhado), len(todos_casos), len(agudos_detalhado), len(agudos_casos)],
        }
    )

    # CSVs principais
    write_dataframe(agudos_casos, outdir / "arboviroses_positivos_final_agudos_casos.csv")
    write_dataframe(agudos_detalhado, outdir / "arboviroses_positivos_final_agudos_detalhado.csv")
    write_dataframe(todos_casos, outdir / "arboviroses_positivos_final_todos_casos.csv")
    write_dataframe(todos_detalhado, outdir / "arboviroses_positivos_final_todos_detalhado.csv")
    write_dataframe(resumo_anual, outdir / "arboviroses_resumo_anual.csv")
    write_dataframe(resumo_se_mun, outdir / "arboviroses_resumo_epiweek_municipio.csv")

    # Excel enxuto, para evitar timeout e arquivos gigantes
    workbook_path = outdir / "arboviroses_positivos_final.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        agudos_casos.to_excel(writer, sheet_name="CASOS_AGUDOS_FINAL", index=False)
        resumo_anual.to_excel(writer, sheet_name="RESUMO_ANUAL", index=False)
        resumo_se_mun.to_excel(writer, sheet_name="RESUMO_SE_MUNICIPIO", index=False)
        controle.to_excel(writer, sheet_name="CONTROLE", index=False)


# -----------------------------------------------------------------------------
# Leitura de arquivos
# -----------------------------------------------------------------------------
def read_file_chunks(file_path: Path, args: argparse.Namespace) -> Iterator[pd.DataFrame]:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        sep = args.sep or detect_csv_sep(file_path)
        encoding = choose_encoding(file_path, args.encoding)
        logging.info("Lendo CSV %s | sep=%s | encoding=%s", file_path.name, sep, encoding)
        reader = pd.read_csv(
            file_path,
            sep=sep,
            encoding=encoding,
            low_memory=False,
            chunksize=args.chunk_size,
            dtype=str,
        )
        yield from reader
    elif suffix in {".xlsx", ".xls"}:
        logging.info("Lendo planilha %s", file_path.name)
        xls = pd.ExcelFile(file_path)
        sheet = xls.sheet_names[0]
        df = pd.read_excel(file_path, sheet_name=sheet, dtype=str)
        yield df
    elif suffix == ".parquet":
        logging.info("Lendo parquet %s", file_path.name)
        df = pd.read_parquet(file_path)
        yield df.astype(str)
    else:
        raise ValueError(f"Formato não suportado: {file_path}")


# -----------------------------------------------------------------------------
# Agregações
# -----------------------------------------------------------------------------
def append_grouped_store(store: Dict[str, List[pd.DataFrame]], key: str, frame: pd.DataFrame) -> None:
    if not frame.empty:
        store[key].append(frame)


def finalize_store(store: Dict[str, List[pd.DataFrame]]) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    metric_cols = {"n", "tests", "positives", "negatives"}
    for key, frames in store.items():
        if not frames:
            out[key] = pd.DataFrame()
            continue
        merged = pd.concat(frames, ignore_index=True)
        numeric_metrics = [c for c in merged.columns if c in metric_cols]
        group_cols = [c for c in merged.columns if c not in numeric_metrics]
        if not numeric_metrics:
            out[key] = merged.drop_duplicates().reset_index(drop=True)
        else:
            out[key] = merged.groupby(group_cols, dropna=False, as_index=False)[numeric_metrics].sum()
    return out


def create_alerts(weekly_tests: pd.DataFrame, weekly_pos: pd.DataFrame, min_alert_count: int) -> pd.DataFrame:
    if weekly_tests.empty:
        return pd.DataFrame()

    tests = weekly_tests.copy()
    tests["series_key"] = tests["target"] + "|" + tests["municipio"]
    tests = tests.sort_values(["series_key", "epi_year", "epi_week"]).reset_index(drop=True)

    pos = weekly_pos.copy() if not weekly_pos.empty else pd.DataFrame(columns=["epi_year", "epi_week", "target", "municipio", "positivity"])
    if not pos.empty and "positivity" not in pos.columns:
        pos["positivity"] = np.where(pos["tests"] > 0, pos["positives"] / pos["tests"], np.nan)

    alerts: List[Dict[str, object]] = []
    for (target, municipio), sub in tests.groupby(["target", "municipio"], dropna=False):
        sub = sub.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
        pos_sub = pos[(pos["target"] == target) & (pos["municipio"] == municipio)].copy()
        pos_map = {(r.epi_year, r.epi_week): r.positivity for r in pos_sub.itertuples(index=False)}

        hist_by_week: Dict[int, List[float]] = defaultdict(list)
        hist_pos_by_week: Dict[int, List[float]] = defaultdict(list)
        recent_counts: List[float] = []
        recent_pos: List[float] = []

        for r in sub.itertuples(index=False):
            cnt = float(r.tests)
            pw = pos_map.get((r.epi_year, r.epi_week), np.nan)
            hist_cnt = hist_by_week[r.epi_week]
            hist_pos = hist_pos_by_week[r.epi_week]
            seasonal_mean = float(np.mean(hist_cnt)) if hist_cnt else np.nan
            seasonal_std = float(np.std(hist_cnt, ddof=1)) if len(hist_cnt) > 1 else 0.0
            recent_mean = float(np.mean(recent_counts[-8:])) if recent_counts else np.nan
            recent_std = float(np.std(recent_counts[-8:], ddof=1)) if len(recent_counts[-8:]) > 1 else 0.0
            volume_candidates = [
                seasonal_mean + 2 * seasonal_std if not np.isnan(seasonal_mean) else np.nan,
                recent_mean + 2 * recent_std if not np.isnan(recent_mean) else np.nan,
            ]
            volume_candidates = [x for x in volume_candidates if not np.isnan(x)]
            threshold_volume = float(max(volume_candidates)) if volume_candidates else np.nan
            volume_alert = bool(cnt >= max(min_alert_count, threshold_volume if not np.isnan(threshold_volume) else min_alert_count))

            pos_seasonal_mean = float(np.mean(hist_pos)) if hist_pos else np.nan
            pos_seasonal_std = float(np.std(hist_pos, ddof=1)) if len(hist_pos) > 1 else 0.0
            pos_recent_mean = float(np.mean(recent_pos[-8:])) if recent_pos else np.nan
            pos_recent_std = float(np.std(recent_pos[-8:], ddof=1)) if len(recent_pos[-8:]) > 1 else 0.0
            pos_candidates = [
                pos_seasonal_mean + 2 * pos_seasonal_std if not np.isnan(pos_seasonal_mean) else np.nan,
                pos_recent_mean + 2 * pos_recent_std if not np.isnan(pos_recent_mean) else np.nan,
            ]
            pos_candidates = [x for x in pos_candidates if not np.isnan(x)]
            threshold_pos = float(max(pos_candidates)) if pos_candidates else np.nan
            positivity_alert = bool((not np.isnan(pw)) and (not np.isnan(threshold_pos)) and pw >= threshold_pos and cnt >= min_alert_count)

            score = 0.0
            if volume_alert:
                base = threshold_volume if not np.isnan(threshold_volume) and threshold_volume > 0 else max(1.0, seasonal_mean if not np.isnan(seasonal_mean) else recent_mean if not np.isnan(recent_mean) else 1.0)
                score += cnt / base
            if positivity_alert:
                basep = threshold_pos if not np.isnan(threshold_pos) and threshold_pos > 0 else max(0.01, pos_seasonal_mean if not np.isnan(pos_seasonal_mean) else pos_recent_mean if not np.isnan(pos_recent_mean) else 0.01)
                score += (pw or 0.0) / basep

            alerts.append(
                {
                    "target": target,
                    "municipio": municipio,
                    "epi_year": int(r.epi_year),
                    "epi_week": int(r.epi_week),
                    "tests": int(r.tests),
                    "seasonal_mean_tests": seasonal_mean,
                    "seasonal_std_tests": seasonal_std,
                    "recent_mean_tests": recent_mean,
                    "recent_std_tests": recent_std,
                    "volume_threshold": threshold_volume,
                    "volume_alert": volume_alert,
                    "positivity": pw,
                    "seasonal_mean_positivity": pos_seasonal_mean,
                    "recent_mean_positivity": pos_recent_mean,
                    "positivity_threshold": threshold_pos,
                    "positivity_alert": positivity_alert,
                    "alert_score": score,
                }
            )

            hist_by_week[r.epi_week].append(cnt)
            recent_counts.append(cnt)
            if not np.isnan(pw):
                hist_pos_by_week[r.epi_week].append(float(pw))
                recent_pos.append(float(pw))

    out = pd.DataFrame(alerts)
    if not out.empty:
        out["alert_level"] = np.select(
            [out["alert_score"] >= 3.0, out["alert_score"] >= 2.0, out["alert_score"] > 0],
            ["alto", "moderado", "baixo"],
            default="sem_sinal",
        )
    return out


def create_forecast(weekly_tests: pd.DataFrame, horizon: int) -> pd.DataFrame:
    if weekly_tests.empty:
        return pd.DataFrame()
    forecasts: List[Dict[str, object]] = []
    grouped = weekly_tests.sort_values(["target", "epi_year", "epi_week"]).groupby("target", dropna=False)
    for target, sub in grouped:
        sub = sub.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
        last_year = int(sub.iloc[-1]["epi_year"])
        last_week = int(sub.iloc[-1]["epi_week"])
        recent = sub["tests"].tail(4).astype(float).tolist()
        hist_by_week: Dict[int, List[float]] = defaultdict(list)
        for r in sub.itertuples(index=False):
            hist_by_week[int(r.epi_week)].append(float(r.tests))
        year, week = last_year, last_week
        for step in range(1, horizon + 1):
            week += 1
            if week > 53:
                week = 1
                year += 1
            seasonal = hist_by_week.get(week, [])
            seasonal_median = float(np.median(seasonal)) if seasonal else np.nan
            recent_median = float(np.median(recent[-4:])) if recent else np.nan
            if np.isnan(seasonal_median) and np.isnan(recent_median):
                pred = np.nan
            elif np.isnan(seasonal_median):
                pred = recent_median
            elif np.isnan(recent_median):
                pred = seasonal_median
            else:
                pred = 0.6 * recent_median + 0.4 * seasonal_median
            pred = max(0.0, float(pred)) if not np.isnan(pred) else np.nan
            forecasts.append(
                {
                    "target": target,
                    "forecast_step": step,
                    "forecast_epi_year": year,
                    "forecast_epi_week": week,
                    "forecast_tests": pred,
                    "seasonal_median_same_week": seasonal_median,
                    "recent_median_last4": recent_median,
                }
            )
            if not np.isnan(pred):
                recent.append(pred)
                hist_by_week[week].append(pred)
    return pd.DataFrame(forecasts)


# -----------------------------------------------------------------------------
# Escrita de saídas
# -----------------------------------------------------------------------------
def write_dataframe(df: pd.DataFrame, path: Path) -> None:
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False, encoding="utf-8-sig")


def build_readme(outdir: Path, args: argparse.Namespace, processed_files: List[str], summary: Dict[str, int]) -> None:
    content = f"""# Pipeline histórica LACEN/GAL

## Execução
- Arquivos processados: {len(processed_files)}
- Ano inicial: {args.start_year}
- Chunk size: {args.chunk_size}
- Município analítico: {args.municipality_source}
- Saída detalhada normalizada: {'sim' if args.write_normalized else 'não'}

## Resumo operacional
- Linhas brutas lidas: {summary.get('rows_input', 0):,}
- Linhas dentro do período: {summary.get('rows_in_period', 0):,}
- Linhas normalizadas geradas: {summary.get('normalized_rows', 0):,}

## Principais arquivos
- `schema_catalog.csv`: catálogo de esquemas dos 6 campos
- `backlog_by_status_year.csv`: distribuição anual por status do exame
- `positivity_by_target_year.csv`: positividade anual por alvo
- `positivity_by_target_epiweek_municipio.csv`: positividade semanal e municipal
- `weekly_tests_by_target_municipio.csv`: séries semanais de volume
- `weekly_alerts.csv`: alertas precoces por alvo/município/semana
- `forecast_next_weeks_statewide.csv`: previsão simples das próximas semanas por alvo
- `arboviroses_positivos_todos.csv`: todos os positivos laboratoriais para dengue, zika e chikungunya
- `arboviroses_positivos_agudos.csv`: positivos compatíveis com infecção aguda (PCR/NS1/IgM)
- `arboviroses_positivos.xlsx`: workbook com abas prontas para uso operacional
- `normalized_results.*`: base longa dos resultados normalizados (opcional)

## Observações metodológicas
1. Os campos `Campo_Resultado_1..6` são tratados como estrutura semi-estruturada e convertidos para formato longo.
2. A positividade considera apenas linhas com `measure_role = qualitative_result` e `outcome_class` positivo/negativo equivalente.
3. Alvos multi-painel, como arboviroses e respiratórios, são separados em linhas específicas por alvo.
4. A extração de arboviroses positivas prioriza o alvo identificado no rótulo do campo e no nome do exame, evitando que o agravo da requisição sobrescreva o alvo verdadeiro do laudo.
5. O módulo de alerta combina baseline sazonal (mesma semana epidemiológica em anos anteriores) e baseline recente (últimas 8 semanas observadas).
6. A previsão é propositalmente conservadora: mediana sazonal + tendência recente. Ela serve como baseline operacional, não como modelo final de pesquisa.
"""
    (outdir / "README.md").write_text(content, encoding="utf-8")


# -----------------------------------------------------------------------------
# Pipeline principal
# -----------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    processed_files: List[str] = []
    summary = defaultdict(int)
    store: Dict[str, List[pd.DataFrame]] = defaultdict(list)

    normalized_output_path = outdir / f"normalized_results.{args.normalized_format}"
    if args.write_normalized and normalized_output_path.exists():
        normalized_output_path.unlink()

    first_write = True

    for input_arg in args.inputs:
        file_path = Path(input_arg)
        if not file_path.exists():
            logging.error("Arquivo não encontrado: %s", file_path)
            continue
        processed_files.append(file_path.name)
        for chunk_idx, chunk in enumerate(read_file_chunks(file_path, args), start=1):
            summary["rows_input"] += len(chunk)
            chunk = ensure_columns(chunk, TEXT_COLS_BASE + DATE_CANDIDATES + ID_CANDIDATES)
            event_dates = pick_event_date(chunk)
            chunk = chunk.loc[event_dates.dt.year.fillna(0).astype(int) >= args.start_year].copy()
            summary["rows_in_period"] += len(chunk)
            if chunk.empty:
                continue

            norm = normalize_chunk(chunk, municipality_source=args.municipality_source)
            summary["normalized_rows"] += len(norm)
            if norm.empty:
                continue

            # Esquemas
            schema = (
                norm[["exame", "metodologia", "schema_signature", "is_released", "field_has_real_value"]]
                .drop_duplicates()
                .groupby(["exame", "metodologia", "schema_signature", "is_released", "field_has_real_value"], dropna=False)
                .size()
                .reset_index(name="n")
            )
            append_grouped_store(store, "schema_catalog", schema)

            # Backlog / status
            status = (
                norm[["year", "status_exame", "exame", "record_id"]]
                .drop_duplicates()
                .groupby(["year", "status_exame", "exame"], dropna=False)["record_id"]
                .nunique()
                .reset_index(name="n")
            )
            append_grouped_store(store, "backlog", status)

            # Positividade anual por alvo
            pos_base = norm[norm["is_interpretable_result"]].copy()
            if not pos_base.empty:
                annual = (
                    pos_base.assign(
                        tests=1,
                        positives=pos_base["is_positive_like"].astype(int),
                        negatives=pos_base["is_negative_like"].astype(int),
                    )
                    .groupby(["year", "target"], dropna=False)[["tests", "positives", "negatives"]]
                    .sum()
                    .reset_index()
                )
                append_grouped_store(store, "positivity_annual", annual)

                weekly_pos = (
                    pos_base.assign(
                        tests=1,
                        positives=pos_base["is_positive_like"].astype(int),
                        negatives=pos_base["is_negative_like"].astype(int),
                    )
                    .groupby(["epi_year", "epi_week", "target", "municipio"], dropna=False)[["tests", "positives", "negatives"]]
                    .sum()
                    .reset_index()
                )
                append_grouped_store(store, "positivity_weekly", weekly_pos)

            # Volume semanal por alvo/município (somente papel qualitativo)
            vol_base = norm[norm["measure_role"].isin(["qualitative_result", "quantitative_result", "site_result"])].copy()
            if not vol_base.empty:
                weekly_tests = (
                    vol_base[["epi_year", "epi_week", "target", "municipio", "record_id"]]
                    .drop_duplicates()
                    .groupby(["epi_year", "epi_week", "target", "municipio"], dropna=False)["record_id"]
                    .nunique()
                    .reset_index(name="n")
                )
                append_grouped_store(store, "weekly_tests", weekly_tests.rename(columns={"n": "tests"}))

            arb_pos = extract_arboviroses_positives(norm)
            if not arb_pos.empty:
                append_grouped_store(store, "arboviroses_positivos", arb_pos)
                arb_agudos = arb_pos[arb_pos["classe_positividade"].isin(["aguda_confirmatoria", "aguda_provavel"])].copy()
                if not arb_agudos.empty:
                    append_grouped_store(store, "arboviroses_positivos_agudos", arb_agudos)

            # Base normalizada detalhada opcional
            if args.write_normalized:
                if args.normalized_format == "csv":
                    norm.to_csv(normalized_output_path, index=False, mode="w" if first_write else "a", header=first_write, encoding="utf-8-sig")
                else:
                    # append incremental em parquet é mais complexo; fallback simples concatena por lote em arquivos particionados
                    part_path = outdir / f"normalized_results_part_{file_path.stem}_{chunk_idx:04d}.parquet"
                    norm.to_parquet(part_path, index=False)
                first_write = False

            logging.info(
                "Processado %s | chunk %s | linhas=%s | normalizadas=%s",
                file_path.name,
                chunk_idx,
                len(chunk),
                len(norm),
            )

    finalized = finalize_store(store)

    # Escreve agregações principais
    schema_catalog = finalized.get("schema_catalog", pd.DataFrame())
    if not schema_catalog.empty:
        schema_catalog = schema_catalog.sort_values("n", ascending=False)
        write_dataframe(schema_catalog, outdir / "schema_catalog.csv")

    backlog = finalized.get("backlog", pd.DataFrame())
    if not backlog.empty:
        backlog = backlog.sort_values(["year", "status_exame", "exame"])
        write_dataframe(backlog.rename(columns={"n": "records"}), outdir / "backlog_by_status_year.csv")

    positivity_annual = finalized.get("positivity_annual", pd.DataFrame())
    if not positivity_annual.empty:
        positivity_annual = positivity_annual.copy()
        positivity_annual["positivity"] = np.where(positivity_annual["tests"] > 0, positivity_annual["positives"] / positivity_annual["tests"], np.nan)
        positivity_annual = positivity_annual.sort_values(["year", "positivity"], ascending=[True, False])
        write_dataframe(positivity_annual[["year", "target", "tests", "positives", "negatives", "positivity"]], outdir / "positivity_by_target_year.csv")

    positivity_weekly = finalized.get("positivity_weekly", pd.DataFrame())
    if not positivity_weekly.empty:
        positivity_weekly = positivity_weekly.copy()
        positivity_weekly["positivity"] = np.where(positivity_weekly["tests"] > 0, positivity_weekly["positives"] / positivity_weekly["tests"], np.nan)
        positivity_weekly = positivity_weekly.sort_values(["epi_year", "epi_week", "target", "municipio"])
        write_dataframe(
            positivity_weekly[["epi_year", "epi_week", "target", "municipio", "tests", "positives", "negatives", "positivity"]],
            outdir / "positivity_by_target_epiweek_municipio.csv",
        )

    weekly_tests = finalized.get("weekly_tests", pd.DataFrame())
    if not weekly_tests.empty:
        weekly_tests = weekly_tests.copy()
        weekly_tests = weekly_tests.sort_values(["epi_year", "epi_week", "target", "municipio"])
        write_dataframe(weekly_tests[["epi_year", "epi_week", "target", "municipio", "tests"]], outdir / "weekly_tests_by_target_municipio.csv")

        pos_for_alert = positivity_weekly[["epi_year", "epi_week", "target", "municipio", "tests", "positives", "positivity"]] if not positivity_weekly.empty else pd.DataFrame()
        alerts = create_alerts(weekly_tests[["epi_year", "epi_week", "target", "municipio", "tests"]], pos_for_alert, args.min_alert_count)
        if not alerts.empty:
            alerts = alerts.sort_values(["alert_score", "epi_year", "epi_week"], ascending=[False, False, False])
            write_dataframe(alerts, outdir / "weekly_alerts.csv")

        statewide = (
            weekly_tests.groupby(["epi_year", "epi_week", "target"], dropna=False)["tests"]
            .sum()
            .reset_index()
        )
        forecast = create_forecast(statewide, args.forecast_horizon)
        if not forecast.empty:
            write_dataframe(forecast, outdir / "forecast_next_weeks_statewide.csv")

    arb_pos = finalized.get("arboviroses_positivos", pd.DataFrame())
    arb_agudos = finalized.get("arboviroses_positivos_agudos", pd.DataFrame())

    if not arb_pos.empty:
        arb_pos = arb_pos.sort_values(["event_date", "municipio", "target", "exame"]).drop_duplicates()
        write_dataframe(arb_pos, outdir / "arboviroses_positivos_todos.csv")

    if not arb_agudos.empty:
        arb_agudos = arb_agudos.sort_values(["event_date", "municipio", "target", "exame"]).drop_duplicates()
        write_dataframe(arb_agudos, outdir / "arboviroses_positivos_agudos.csv")

    if not arb_pos.empty or not arb_agudos.empty:
        workbook_path = outdir / "arboviroses_positivos.xlsx"
        with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
            if not arb_pos.empty:
                arb_pos.to_excel(writer, sheet_name="ARBOVIROSES_POSITIVOS", index=False)
            if not arb_agudos.empty:
                arb_agudos.to_excel(writer, sheet_name="ARBOVIROSES_POSITIVOS_AGUDOS", index=False)
        # versão final corrigida para uso epidemiológico
        write_arboviroses_corrected_outputs(outdir, arb_pos, arb_agudos)

    metadata = {
        "processed_files": processed_files,
        "summary": dict(summary),
        "parameters": vars(args),
    }
    (outdir / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    build_readme(outdir, args, processed_files, dict(summary))

    logging.info("Execução concluída. Saídas em: %s", outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
