
import argparse
import importlib.util
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

def log_step(msg):
    print(msg, flush=True)

# ----------------------------
# General utilities
# ----------------------------
def norm_text(x):
    if pd.isna(x):
        return ""
    x = str(x).strip().upper()
    x = unicodedata.normalize("NFKD", x)
    x = "".join(ch for ch in x if not unicodedata.combining(ch))
    x = re.sub(r"\s+", " ", x)
    return x

def norm_municipio(x):
    x = norm_text(x)
    x = re.sub(r"^\d+\s*[-\.]?\s*", "", x)
    x = x.replace("MUNICIPIO DE ", "")
    return x

def parse_decimal_br(x):
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.number)):
        v = float(x)
    else:
        s = str(x).strip()
        s = s.replace(".", "").replace(",", ".")
        try:
            v = float(s)
        except Exception:
            return np.nan
    if abs(v) > 1000:
        # likely encoded coordinate or scaled metric
        v = v / 10000.0
    return v

def parse_prop(x):
    v = parse_decimal_br(x)
    if pd.isna(v):
        return np.nan
    if v > 100:
        return v / 100.0
    return v

def parse_index_01(x):
    v = parse_decimal_br(x)
    if pd.isna(v):
        return np.nan
    if v > 1:
        if v > 100:
            return v / 1000.0
        return v / 100.0
    return v

def wilson_interval(pos, n, z=1.96):
    if pd.isna(n) or n <= 0:
        return np.nan, np.nan
    pos = 0.0 if pd.isna(pos) else float(pos)
    n = float(n)
    phat = pos / n
    denom = 1 + z*z/n
    center = (phat + z*z/(2*n)) / denom
    half = z * math.sqrt((phat*(1-phat) + z*z/(4*n))/n) / denom
    return max(0.0, center-half), min(1.0, center+half)

def poisson_ci(count, pop, z=1.96):
    if pd.isna(pop) or pop <= 0 or pd.isna(count) or count < 0:
        return np.nan, np.nan
    count = float(count)
    pop = float(pop)
    rate = count / pop
    se = (math.sqrt(count) / pop) if count > 0 else (1.0 / pop)
    low = max(0.0, rate - z * se)
    high = rate + z * se
    return low * 100000, high * 100000

def first_existing(columns, candidates):
    cols = list(columns)
    norm_map = {norm_text(c): c for c in cols}
    for cand in candidates:
        if cand in cols:
            return cand
        if norm_text(cand) in norm_map:
            return norm_map[norm_text(cand)]
    return None

def fuzzy_find_column(columns, include_any=None, include_all=None, exclude_any=None):
    include_any = [norm_text(x) for x in (include_any or [])]
    include_all = [norm_text(x) for x in (include_all or [])]
    exclude_any = [norm_text(x) for x in (exclude_any or [])]
    cols = list(columns)
    scored = []
    for c in cols:
        nc = norm_text(c)
        if exclude_any and any(tok in nc for tok in exclude_any):
            continue
        if include_all and not all(tok in nc for tok in include_all):
            continue
        if include_any and not any(tok in nc for tok in include_any):
            continue
        score = 0
        score += sum(tok in nc for tok in include_any) * 2
        score += sum(tok in nc for tok in include_all) * 3
        # prefer shorter/more specific names
        score -= len(nc) / 1000.0
        scored.append((score, c))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]

def _slug_name(s: str) -> str:
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def resolve_existing_path(pathlike) -> Path:
    p = Path(pathlike)
    if p.exists():
        return p
    parent = p.parent if str(p.parent) not in ("", ".") else Path(".")
    if not parent.exists():
        parent = Path(".")
    target_slug = _slug_name(p.name)
    target_stem_slug = _slug_name(p.stem)
    candidates = []
    for cand in parent.iterdir():
        if not cand.is_file():
            continue
        slug = _slug_name(cand.name)
        stem_slug = _slug_name(cand.stem)
        if slug == target_slug or stem_slug == target_stem_slug:
            return cand
        if target_stem_slug and (target_stem_slug in stem_slug or stem_slug in target_stem_slug):
            candidates.append(cand)
    if candidates:
        candidates = sorted(candidates, key=lambda c: len(c.name))
        return candidates[0]
    return p

def try_read_table(path: Path) -> pd.DataFrame:
    path = resolve_existing_path(path)
    if not path.exists():
        raise ValueError(f"Arquivo não encontrado: {path}")
    if path.suffix.lower() in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    encodings = ["utf-8-sig", "utf-8", "latin1"]
    for enc in encodings:
        for sep in [";", ",", "\t", "|"]:
            for engine in ["c", "python"]:
                try:
                    kwargs = dict(sep=sep, low_memory=False, encoding=enc)
                    if engine == "python":
                        kwargs["engine"] = "python"
                        kwargs["on_bad_lines"] = "skip"
                    df = pd.read_csv(path, **kwargs)
                    if df.shape[1] > 1:
                        return df
                except Exception:
                    continue
    raise ValueError(f"Não foi possível ler {path}")


def read_csv_chunks_resilient(path: Path, chunksize: int = 50000):
    path = resolve_existing_path(path)
    if not path.exists():
        raise ValueError(f"Arquivo não encontrado: {path}")
    encodings = ["utf-8-sig", "utf-8", "latin1"]
    seps = [";", ",", "\t", "|"]
    last_err = None
    for enc in encodings:
        for sep in seps:
            for engine in ["c", "python"]:
                try:
                    kwargs = dict(sep=sep, encoding=enc, chunksize=chunksize, dtype=str, low_memory=False)
                    if engine == "python":
                        kwargs["engine"] = "python"
                        kwargs["on_bad_lines"] = "skip"
                    reader = pd.read_csv(path, **kwargs)
                    first = next(reader)
                    if first.shape[1] <= 1:
                        continue
                    yield first
                    for chunk in reader:
                        yield chunk
                    return
                except StopIteration:
                    return
                except Exception as e:
                    last_err = e
                    continue
    raise ValueError(f"Não foi possível ler {path}: {last_err}")

def safe_to_datetime(s):
    """Parse robusto de datas SIM/SINAN; rejeita anos absurdos (<1990)."""
    raw = s
    # Formato compacto YYYYMMDD (comum no SIM)
    try:
        as_str = pd.Series(raw).astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        compact = as_str.str.fullmatch(r"\d{8}")
        if compact is not None and compact.any():
            dt_c = pd.to_datetime(as_str.where(compact), format="%Y%m%d", errors="coerce")
            if dt_c.notna().sum() > max(1, int(0.3 * len(as_str))):
                out = dt_c
                # preenche restantes
                rest = ~compact | dt_c.isna()
                if rest.any():
                    out = out.fillna(pd.to_datetime(as_str.where(rest), errors="coerce", dayfirst=True))
                years = out.dt.year
                out = out.where(years.between(1990, 2100))
                return out
    except Exception:
        pass
    try:
        dt = pd.to_datetime(raw, errors="coerce", format="%Y-%m-%d")
        if hasattr(dt, "notna") and dt.notna().sum() > 0:
            years = dt.dt.year
            dt = dt.where(years.between(1990, 2100))
            if dt.notna().sum() > 0:
                return dt
    except Exception:
        pass
    dt = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    if hasattr(dt, "dt"):
        years = dt.dt.year
        dt = dt.where(years.between(1990, 2100))
    return dt

def robust_z(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    med = s.median()
    mad = (s - med).abs().median()
    if pd.isna(mad) or mad == 0:
        std = s.std(ddof=0)
        if pd.isna(std) or std == 0:
            return pd.Series(np.zeros(len(s)), index=s.index)
        return (s - s.mean()) / std
    return 0.6745 * (s - med) / mad

def load_pipeline_module(path: str):
    path = str(resolve_existing_path(path))
    spec = importlib.util.spec_from_file_location("lacen_pipeline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ----------------------------
# Common candidates
# ----------------------------
SEX_CANDIDATES = ["Sexo", "Sexo_Paciente", "SexoPaciente", "CS_SEXO", "SEXO"]
AGE_CANDIDATES = ["Idade", "Idade_Anos", "NU_IDADE_N", "Idade_Num", "IDADE"]
BIRTH_CANDIDATES = ["Data_Nascimento", "Data_Nascimento_dt", "DT_NASCIMENTO", "DT_NASC", "DT_NASCIM"]
RACE_CANDIDATES = ["Raca_Cor", "RacaCor", "Raca_Cor_Paciente", "CS_RACA", "RACA_COR", "COR_RACA"]
SCHOOL_CANDIDATES = ["Escolaridade", "Escolaridade_Paciente", "CS_ESCOL_N", "ESCOLARI"]
MUN_CANDIDATES = ["Municipio_Residencia_Paciente", "Municipio_Solicitante", "Municipio_Notificacao_Sinan", "Municipio_Notificacao_Gal",
                  "MUNICIPIO_RESIDENCIA", "MUNICIPIO", "MUNIC_RES", "MUN_RES", "MUN_NOT", "MUNICIPIO_NOTIFICACAO", "Município"]
DATE_CANDIDATES = ["Data_Solicitacao_dt", "Data_Coleta_dt", "Data_Liberacao_dt", "Data_Cadastro_dt",
                   "DT_NOTIFIC", "DT_SIN_PRI", "DT_NOTIFICACAO", "DTOBITO", "DT_OBITO", "DATA_OBITO", "Data Consulta", "DATA"]

SINAN_AGRAVO_CANDIDATES = ["Agravo", "Agravo_Requisicao", "AGRAVO", "ID_AGRAVO", "DOENCA", "DIAGNOSTICO", "CLASSI_FIN", "Nome_Agravo"]
SIM_CAUSE_CANDIDATES = ["CAUSABAS", "CAUSA_BAS", "Causa_Basica", "CID10", "CAUSA_MORTE"]
CNES_MUN_CANDIDATES = ["EstabelecimentoMunicipioNome", "EstabelecimentoMunicipioCodigo", "MUNICIPIO", "Município", "Municipio", "MUNICIPIO_NOME", "MunicipioNome", "Nome_Municipio", "MUNNOME"]

TARGET_PATTERNS = [
    (r"DENGUE", "dengue"),
    (r"ZIKA", "zika"),
    (r"CHIK", "chikungunya"),
    (r"SARS[\s_-]*COV[\s_-]*2|COVID", "sars_cov_2"),
    (r"INFLUENZA A", "influenza_a"),
    (r"INFLUENZA B", "influenza_b"),
    (r"VSR|VIRUS SINCICIAL|RSV", "vsr"),
    (r"TUBERC|MTB|RIFAMPICINA|BACILOSCOPIA", "tuberculose"),
    (r"HEPATITE B|HBV|HBSAG|ANTI-HBC|ANTI-HBS", "hepatite_b_hbv"),
    (r"HEPATITE C|HCV", "hepatite_c_hcv"),
    (r"HEPATITE A", "hepatite_a"),
    (r"LEPTOSPIR", "leptospirose"),
    (r"HANTAV", "hantavirus"),
    (r"MENING", "meningite"),
    (r"SARAMPO", "sarampo"),
    (r"RUBEOLA", "rubeola"),
    (r"FEBRE AMARELA", "febre_amarela"),
    (r"OROPOUCHE", "oropouche"),
]

def infer_target_from_text(*texts):
    ctx = " | ".join([norm_text(x) for x in texts if x is not None])
    for pat, tgt in TARGET_PATTERNS:
        if re.search(pat, ctx):
            return tgt
    return "outros"

def normalize_sex(x):
    x = norm_text(x)
    if x.startswith("F"):
        return "FEMININO"
    if x.startswith("M"):
        return "MASCULINO"
    return "IGNORADO"

def normalize_race(x):
    x = norm_text(x)
    for k in ["BRANCA", "PRETA", "PARDA", "AMARELA", "INDIGENA"]:
        if k in x:
            return k
    return "IGNORADO"

def normalize_schooling(x):
    x = norm_text(x)
    return x if x else "IGNORADO"

def age_to_group(age):
    if pd.isna(age):
        return "IGNORADO"
    try:
        a = float(age)
    except Exception:
        return "IGNORADO"
    if a < 1: return "<1"
    if a <= 4: return "1-4"
    if a <= 9: return "5-9"
    if a <= 14: return "10-14"
    if a <= 19: return "15-19"
    if a <= 29: return "20-29"
    if a <= 39: return "30-39"
    if a <= 49: return "40-49"
    if a <= 59: return "50-59"
    if a <= 69: return "60-69"
    if a <= 79: return "70-79"
    return "80+"

# ----------------------------
# External datasets builders
# ----------------------------
def build_municipal_master(geo_path, mun_path, pea_path, outdir):
    geo = try_read_table(Path(geo_path))
    mun = try_read_table(Path(mun_path))
    pea = try_read_table(Path(pea_path))

    geo_mun_col = first_existing(geo.columns, ["Município", "Municipio"])
    geo_code_col = first_existing(geo.columns, ["Código IBGE", "Codigo IBGE", "IBGE"])
    gini_col = first_existing(geo.columns, ["Índice de Gini", "Indice de Gini", "Gini"])
    ep_col = first_existing(geo.columns, ["Proporção de Extrema Pobreza (%)", "Prop. Extrema Pobreza", "Extrema Pobreza (%)"])

    mun_mun_col = first_existing(mun.columns, ["Município", "Municipio"])
    mun_code_col = first_existing(mun.columns, ["Código IBGE", "Codigo IBGE", "IBGE"])
    lat_col = first_existing(mun.columns, ["Latitude", "Latitude (Fonte XLSX)"])
    lon_col = first_existing(mun.columns, ["Longitude", "Longitude (Fonte XLSX)"])
    idh_col = first_existing(mun.columns, ["IDH", "IDHM"])
    gini2_col = first_existing(mun.columns, ["Índice de Gini (Fonte CSV)", "Indice de Gini"])
    ep2_col = first_existing(mun.columns, ["Proporção de Extrema Pobreza (%) (Fonte XLSX)", "Prop. Extrema Pobreza"])

    pea_mun_col = first_existing(pea.columns, ["Município", "Municipio"])
    pea_col = first_existing(pea.columns, ["PEAO 2010 TAB. 3584 IBGE", "PEA", "PEA_2010"])

    g = pd.DataFrame({
        "municipio": geo[geo_mun_col].map(norm_municipio) if geo_mun_col else None,
        "codigo_ibge": geo[geo_code_col] if geo_code_col else np.nan,
        "gini": geo[gini_col].map(parse_index_01) if gini_col else np.nan,
        "extrema_pobreza_pct": geo[ep_col].map(parse_prop) if ep_col else np.nan,
    }).dropna(subset=["municipio"]).drop_duplicates("municipio")

    m = pd.DataFrame({
        "municipio": mun[mun_mun_col].map(norm_municipio) if mun_mun_col else None,
        "codigo_ibge": mun[mun_code_col] if mun_code_col else np.nan,
        "latitude": mun[lat_col].map(parse_decimal_br) if lat_col else np.nan,
        "longitude": mun[lon_col].map(parse_decimal_br) if lon_col else np.nan,
        "idh": mun[idh_col].map(parse_index_01) if idh_col else np.nan,
        "gini_mun": mun[gini2_col].map(parse_index_01) if gini2_col else np.nan,
        "extrema_pobreza_pct_mun": mun[ep2_col].map(parse_prop) if ep2_col else np.nan,
    }).dropna(subset=["municipio"]).drop_duplicates("municipio")

    p = pd.DataFrame({
        "municipio": pea[pea_mun_col].map(norm_municipio) if pea_mun_col else None,
        "pea_2010": pd.to_numeric(pea[pea_col], errors="coerce") if pea_col else np.nan,
    }).dropna(subset=["municipio"]).drop_duplicates("municipio")

    pop_cols = [c for c in mun.columns if str(c).startswith("Pop_")]
    pop_rows = []
    for c in pop_cols:
        try:
            year = int(str(c).split("_")[1])
        except Exception:
            continue
        tmp = pd.DataFrame({"municipio": mun[mun_mun_col].map(norm_municipio), "ano": year, "populacao": pd.to_numeric(mun[c], errors="coerce")})
        pop_rows.append(tmp)
    pop_long = pd.concat(pop_rows, ignore_index=True) if pop_rows else pd.DataFrame(columns=["municipio","ano","populacao"])

    mm = m.merge(g, on=["municipio"], how="outer", suffixes=("","_g"))
    mm["codigo_ibge"] = mm["codigo_ibge"].fillna(mm.get("codigo_ibge_g"))
    if "gini" not in mm.columns:
        mm["gini"] = np.nan
    mm["gini"] = mm["gini"].fillna(mm.get("gini_mun"))
    mm["extrema_pobreza_pct"] = mm["extrema_pobreza_pct"].fillna(mm.get("extrema_pobreza_pct_mun"))
    mm = mm.drop(columns=[c for c in ["codigo_ibge_g","gini_mun","extrema_pobreza_pct_mun"] if c in mm.columns])
    mm = mm.merge(p, on="municipio", how="left")

    # vulnerability
    components = []
    if "idh" in mm.columns:
        mm["idh_inv"] = 1 - mm["idh"]
        components.append("idh_inv")
    if "gini" in mm.columns:
        components.append("gini")
    if "extrema_pobreza_pct" in mm.columns:
        components.append("extrema_pobreza_pct")
    if "pea_2010" in mm.columns:
        mm["pea_inv"] = 1 - mm["pea_2010"].rank(pct=True)
        components.append("pea_inv")
    zcols = []
    for c in components:
        mm[c + "_z"] = robust_z(pd.to_numeric(mm[c], errors="coerce").fillna(pd.to_numeric(mm[c], errors="coerce").median()))
        zcols.append(c + "_z")
    mm["indice_vulnerabilidade"] = mm[zcols].mean(axis=1) if zcols else np.nan

    mm.to_csv(Path(outdir) / "municipal_master.csv", index=False, encoding="utf-8-sig")
    pop_long.to_csv(Path(outdir) / "populacao_municipio.csv", index=False, encoding="utf-8-sig")
    return mm, pop_long

def build_climate_weekly(climate_path, outdir):
    clim = try_read_table(Path(climate_path))
    mun_col = first_existing(clim.columns, ["Municípios", "Municipio", "Município"])
    date_col = first_existing(clim.columns, ["Data Consulta", "Data", "DATA"])
    rain_col = first_existing(clim.columns, ["precipitation_sum", "Precipitação", "PRECIPITATION_SUM"])
    wind_col = first_existing(clim.columns, ["wind_speed_10m_max", "VENTO_MAX", "VENTO"])
    temp_col = first_existing(clim.columns, ["temperature_2m_max", "TEMPERATURA_MAX", "TEMPERATURA"])
    hum_col = first_existing(clim.columns, ["relative_humidity_2m_min", "UMIDADE_MIN", "UMIDADE"])
    event_col = first_existing(clim.columns, ["Evento", "EVENTO"])
    sev_col = first_existing(clim.columns, ["Severidade", "SEVERIDADE"])
    oid_col = first_existing(clim.columns, ["OID", "ID", "CODIGO"])

    df = pd.DataFrame({
        "municipio": clim[mun_col].map(norm_municipio) if mun_col else None,
        "event_date": safe_to_datetime(clim[date_col]) if date_col else pd.NaT,
        "precipitation_sum_mm": clim[rain_col].map(parse_decimal_br) if rain_col else np.nan,
        "wind_speed_10m_max": clim[wind_col].map(parse_decimal_br) if wind_col else np.nan,
        "temperature_2m_max": clim[temp_col].map(parse_decimal_br) if temp_col else np.nan,
        "relative_humidity_2m_min": clim[hum_col].map(parse_decimal_br) if hum_col else np.nan,
        "evento": clim[event_col].map(norm_text) if event_col else "",
        "severidade": clim[sev_col].map(norm_text) if sev_col else "",
        "oid": clim[oid_col] if oid_col else np.arange(len(clim))
    }).dropna(subset=["municipio","event_date"])

    iso = df["event_date"].dt.isocalendar()
    df["epi_year"] = iso["year"].astype(int)
    df["epi_week"] = iso["week"].astype(int)
    sev_map = {"SEVERO": 3, "PERIGO": 2, "PERIGO POTENCIAL": 1}
    df["sev_score"] = df["severidade"].map(lambda x: sev_map.get(x, 0))

    weekly = df.groupby(["municipio","epi_year","epi_week"], dropna=False).agg(
        precipitation_sum_mm=("precipitation_sum_mm","mean"),
        wind_speed_10m_max=("wind_speed_10m_max","mean"),
        temperature_2m_max=("temperature_2m_max","mean"),
        relative_humidity_2m_min=("relative_humidity_2m_min","mean"),
        n_eventos_climaticos=("oid","nunique"),
        severidade_media=("sev_score","mean"),
        severidade_max=("sev_score","max"),
    ).reset_index()

    weekly.to_csv(Path(outdir) / "climate_weekly_municipio.csv", index=False, encoding="utf-8-sig")
    return weekly

def build_sinan_weekly(sinan_path, outdir):
    path = resolve_existing_path(Path(sinan_path))
    log_step(f"[SINAN] Iniciando leitura: {path}")
    weekly_parts = []
    demo_parts = []

    try:
        chunks = read_csv_chunks_resilient(path, chunksize=50000)
    except Exception:
        df = try_read_table(path)
        chunks = [df]

    total_rows = 0
    used_chunks = 0
    for i, df in enumerate(chunks, start=1):
        total_rows += len(df)
        mun_col = first_existing(df.columns, MUN_CANDIDATES) or fuzzy_find_column(df.columns, include_any=["municip", "mun"], exclude_any=["uf"])
        date_col = (
            first_existing(df.columns, ["DT_NOTIFIC", "DT_SIN_PRI", "DT_NOTIFICACAO", "DATA_NOTIFICACAO", "Data_Notificacao"])
            or fuzzy_find_column(df.columns, include_all=["dt"], include_any=["not", "notif", "sin", "pri"])
            or fuzzy_find_column(df.columns, include_all=["data","not"])
            or fuzzy_find_column(df.columns, include_any=["dtnot", "datanot"])
        )
        agravo_col = (
            first_existing(df.columns, SINAN_AGRAVO_CANDIDATES)
            or fuzzy_find_column(df.columns, include_any=["agrav", "doenc", "diag", "classi", "cid"])
        )
        sex_col = first_existing(df.columns, SEX_CANDIDATES)
        race_col = first_existing(df.columns, RACE_CANDIDATES)
        school_col = first_existing(df.columns, SCHOOL_CANDIDATES)
        age_col = first_existing(df.columns, AGE_CANDIDATES)
        birth_col = first_existing(df.columns, BIRTH_CANDIDATES)
        evol_col = first_existing(df.columns, ["EVOLUCAO", "Evolucao", "DT_ENCERRA", "CRITERIO"])

        if mun_col is None or date_col is None:
            cols_preview = ", ".join(list(map(str, df.columns[:12])))
            log_step(f"[SINAN] chunk {i}: sem colunas-chave, ignorado | colunas: {cols_preview}")
            continue

        work = pd.DataFrame({
            "municipio": df[mun_col].map(norm_municipio),
            "event_date": safe_to_datetime(df[date_col]),
            "agravo_texto": df[agravo_col].map(norm_text) if agravo_col else "",
            "sexo": df[sex_col].map(normalize_sex) if sex_col else "IGNORADO",
            "raca_cor": df[race_col].map(normalize_race) if race_col else "IGNORADO",
            "escolaridade": df[school_col].map(normalize_schooling) if school_col else "IGNORADO",
            "evolucao": df[evol_col].map(norm_text) if evol_col else "",
        })
        if age_col:
            age_series = pd.to_numeric(df[age_col], errors="coerce")
        elif birth_col:
            birth = safe_to_datetime(df[birth_col])
            age_series = ((work["event_date"] - birth).dt.days / 365.25).round(1)
        else:
            age_series = pd.Series(np.nan, index=df.index)
        work["faixa_etaria"] = age_series.map(age_to_group)
        work = work.dropna(subset=["municipio","event_date"]).copy()
        if work.empty:
            log_step(f"[SINAN] chunk {i}: sem linhas válidas após limpeza")
            continue
        used_chunks += 1
        work["target"] = work["agravo_texto"].map(lambda x: infer_target_from_text(x) if str(x).strip() else "nao_classificado_sinan")
        iso = work["event_date"].dt.isocalendar()
        work["ano"] = work["event_date"].dt.year
        work["epi_year"] = iso["year"].astype(int)
        work["epi_week"] = iso["week"].astype(int)
        work["notificacoes"] = 1
        work["encerrados"] = work["evolucao"].map(lambda x: 0 if x == "" else 1)

        weekly_parts.append(
            work.groupby(["epi_year","epi_week","ano","target","municipio"], dropna=False)
            .agg(notificacoes_sinan=("notificacoes","sum"), encerrados_sinan=("encerrados","sum")).reset_index()
        )
        demo_parts.append(
            work.groupby(["ano","target","municipio","sexo","faixa_etaria","raca_cor","escolaridade"], dropna=False)
            .agg(notificacoes_sinan=("notificacoes","sum")).reset_index()
        )
        log_step(f"[SINAN] chunk {i}: linhas={len(df)} válidas={len(work)} acumulado={total_rows}")

    weekly = pd.concat(weekly_parts, ignore_index=True) if weekly_parts else pd.DataFrame()
    demo = pd.concat(demo_parts, ignore_index=True) if demo_parts else pd.DataFrame()
    if not weekly.empty:
        weekly = weekly.groupby(["epi_year","epi_week","ano","target","municipio"], dropna=False).sum(numeric_only=True).reset_index()
        weekly.to_csv(Path(outdir) / "sinan_weekly_municipio.csv", index=False, encoding="utf-8-sig")
    if not demo.empty:
        demo = demo.groupby(["ano","target","municipio","sexo","faixa_etaria","raca_cor","escolaridade"], dropna=False).sum(numeric_only=True).reset_index()
        demo.to_csv(Path(outdir) / "sinan_demo.csv", index=False, encoding="utf-8-sig")
    log_step(f"[SINAN] Concluído. chunks úteis={used_chunks} linhas_lidas={total_rows}")
    return weekly, demo

def build_sim_weekly(sim_path, outdir):
    path = resolve_existing_path(Path(sim_path))
    log_step(f"[SIM] Iniciando leitura: {path}")
    weekly_parts = []
    demo_parts = []

    try:
        chunks = read_csv_chunks_resilient(path, chunksize=50000)
    except Exception:
        df = try_read_table(path)
        chunks = [df]

    total_rows = 0
    used_chunks = 0
    for i, df in enumerate(chunks, start=1):
        total_rows += len(df)
        mun_col = first_existing(df.columns, ["MUNICIPIO", "Município residência", "Município", "MUN_RES", "MUNNOME"]) or fuzzy_find_column(df.columns, include_any=["municip", "mun"], exclude_any=["uf"])
        date_col = (
            first_existing(df.columns, ["DTOBITO", "DT_OBITO", "DATA_OBITO", "Data_Obito"])
            or fuzzy_find_column(df.columns, include_any=["obito"])
            or fuzzy_find_column(df.columns, include_all=["data","obit"])
        )
        cause_col = first_existing(df.columns, SIM_CAUSE_CANDIDATES) or fuzzy_find_column(df.columns, include_any=["causa", "cid"])
        sex_col = first_existing(df.columns, SEX_CANDIDATES)
        race_col = first_existing(df.columns, RACE_CANDIDATES)
        school_col = first_existing(df.columns, SCHOOL_CANDIDATES)
        age_col = first_existing(df.columns, AGE_CANDIDATES)
        birth_col = first_existing(df.columns, BIRTH_CANDIDATES)

        if mun_col is None or date_col is None:
            cols_preview = ", ".join(list(map(str, df.columns[:12])))
            log_step(f"[SIM] chunk {i}: sem colunas-chave, ignorado | colunas: {cols_preview}")
            continue

        work = pd.DataFrame({
            "municipio": df[mun_col].map(norm_municipio),
            "event_date": safe_to_datetime(df[date_col]),
            "causa_texto": df[cause_col].map(norm_text) if cause_col else "",
            "sexo": df[sex_col].map(normalize_sex) if sex_col else "IGNORADO",
            "raca_cor": df[race_col].map(normalize_race) if race_col else "IGNORADO",
            "escolaridade": df[school_col].map(normalize_schooling) if school_col else "IGNORADO",
        })
        if age_col:
            age_series = pd.to_numeric(df[age_col], errors="coerce")
        elif birth_col:
            birth = safe_to_datetime(df[birth_col])
            age_series = ((work["event_date"] - birth).dt.days / 365.25).round(1)
        else:
            age_series = pd.Series(np.nan, index=df.index)
        work["faixa_etaria"] = age_series.map(age_to_group)
        work = work.dropna(subset=["municipio","event_date"]).copy()
        # Descarta anos inválidos (parsing quebrado → ano 1)
        years_ok = work["event_date"].dt.year.between(1990, 2100)
        n_bad = int((~years_ok).sum())
        if n_bad:
            log_step(f"[SIM] chunk {i}: descartadas {n_bad} linhas com data/ano inválido")
        work = work.loc[years_ok].copy()
        if work.empty:
            log_step(f"[SIM] chunk {i}: sem linhas válidas após limpeza")
            continue
        used_chunks += 1
        work["target"] = work["causa_texto"].map(lambda x: infer_target_from_text(x) if str(x).strip() else "nao_classificado_sim")
        iso = work["event_date"].dt.isocalendar()
        work["ano"] = work["event_date"].dt.year.astype(int)
        work["epi_year"] = iso["year"].astype(int)
        work["epi_week"] = iso["week"].astype(int)
        # Dupla checagem pós-isocalendar
        work = work[work["epi_year"].between(1990, 2100)].copy()
        if work.empty:
            continue
        work["obitos"] = 1

        weekly_parts.append(
            work.groupby(["epi_year","epi_week","ano","target","municipio"], dropna=False)
            .agg(obitos_sim=("obitos","sum")).reset_index()
        )
        demo_parts.append(
            work.groupby(["ano","target","municipio","sexo","faixa_etaria","raca_cor","escolaridade"], dropna=False)
            .agg(obitos_sim=("obitos","sum")).reset_index()
        )
        log_step(f"[SIM] chunk {i}: linhas={len(df)} válidas={len(work)} acumulado={total_rows}")

    weekly = pd.concat(weekly_parts, ignore_index=True) if weekly_parts else pd.DataFrame()
    demo = pd.concat(demo_parts, ignore_index=True) if demo_parts else pd.DataFrame()
    if not weekly.empty:
        weekly = weekly.groupby(["epi_year","epi_week","ano","target","municipio"], dropna=False).sum(numeric_only=True).reset_index()
        weekly.to_csv(Path(outdir) / "sim_weekly_municipio.csv", index=False, encoding="utf-8-sig")
    if not demo.empty:
        demo = demo.groupby(["ano","target","municipio","sexo","faixa_etaria","raca_cor","escolaridade"], dropna=False).sum(numeric_only=True).reset_index()
        demo.to_csv(Path(outdir) / "sim_demo.csv", index=False, encoding="utf-8-sig")
    log_step(f"[SIM] Concluído. chunks úteis={used_chunks} linhas_lidas={total_rows}")
    return weekly, demo

def build_cnes_capacity(estab_path, leitos_path, equip_path, equipes_path, outdir):
    log_step("[CNES] Iniciando processamento de estabelecimentos, leitos, equipamentos e equipes")

    def get_mun(df):
        col = first_existing(df.columns, CNES_MUN_CANDIDATES)
        if col is None:
            return pd.Series(["IGNORADO"] * len(df))
        return df[col].map(norm_municipio)

    def aggregate_file_chunks(path, kind):
        path = resolve_existing_path(Path(path))
        log_step(f"[CNES-{kind}] Lendo: {path}")
        parts = []
        rows = 0
        try:
            chunks = read_csv_chunks_resilient(path, chunksize=50000)
        except Exception as e:
            log_step(f"[CNES-{kind}] leitura em chunks falhou, tentando leitura única: {e}")
            chunks = [try_read_table(path)]

        for i, df in enumerate(chunks, start=1):
            rows += len(df)
            mun = get_mun(df)

            if kind == "ESTAB":
                agg = (
                    pd.DataFrame({"municipio": mun, "cnes_estabelecimentos": 1})
                    .groupby("municipio", dropna=False)["cnes_estabelecimentos"]
                    .sum().reset_index()
                )

            elif kind == "LEITOS":
                out = pd.DataFrame({"municipio": mun})
                qtd_exist = first_existing(df.columns, ["QtdExistente", "QTDEXISTENTE", "QTD_EXISTENTE"])
                qtd_sus = first_existing(df.columns, ["QtdSUS", "QTDSUS", "QTD_SUS"])
                tipo = first_existing(df.columns, ["TipoLeito", "TIPOLEITO"])
                esp = first_existing(df.columns, ["Especialidade", "Especialidade2", "ESPECIALIDADE"])
                out["cnes_leitos_total"] = pd.to_numeric(df[qtd_exist], errors="coerce") if qtd_exist else np.nan
                out["cnes_leitos_sus"] = pd.to_numeric(df[qtd_sus], errors="coerce") if qtd_sus else np.nan
                if tipo or esp:
                    tipo_txt = (df[tipo].map(norm_text) if tipo else "") + " " + (df[esp].map(norm_text) if esp else "")
                    out["cnes_leitos_uti"] = np.where(tipo_txt.str.contains("UTI|INTENSIVA", na=False), out["cnes_leitos_total"], 0)
                else:
                    out["cnes_leitos_uti"] = np.nan
                agg = out.groupby("municipio", dropna=False).agg(
                    cnes_leitos_total=("cnes_leitos_total", "sum"),
                    cnes_leitos_sus=("cnes_leitos_sus", "sum"),
                    cnes_leitos_uti=("cnes_leitos_uti", "sum"),
                ).reset_index()

            elif kind == "EQUIP":
                out = pd.DataFrame({"municipio": mun})
                qtd_exist = first_existing(df.columns, ["QtdExistente", "QTDEXISTENTE", "QTD_EXISTENTE"])
                qtd_uso = first_existing(df.columns, ["QtdUso", "QTDUSO", "QTD_USO"])
                tipo = first_existing(df.columns, ["EquipamentoTipo", "EQUIPAMENTOTIPO"])
                grupo = first_existing(df.columns, ["EquipamentoGrupo", "EQUIPAMENTOGRUPO"])
                out["cnes_equipamentos_total"] = pd.to_numeric(df[qtd_exist], errors="coerce") if qtd_exist else np.nan
                out["cnes_equipamentos_uso"] = pd.to_numeric(df[qtd_uso], errors="coerce") if qtd_uso else np.nan
                if tipo or grupo:
                    txt = (df[grupo].map(norm_text) if grupo else "") + " " + (df[tipo].map(norm_text) if tipo else "")
                    crit = txt.str.contains("VENTIL|RESPIR|RX|RAIO X|TOMOG|PCR|ULTRASSOM|DESFIB|MONITOR", na=False)
                    out["cnes_equipamentos_criticos"] = np.where(crit, out["cnes_equipamentos_total"], 0)
                else:
                    out["cnes_equipamentos_criticos"] = np.nan
                agg = out.groupby("municipio", dropna=False).agg(
                    cnes_equipamentos_total=("cnes_equipamentos_total", "sum"),
                    cnes_equipamentos_uso=("cnes_equipamentos_uso", "sum"),
                    cnes_equipamentos_criticos=("cnes_equipamentos_criticos", "sum"),
                ).reset_index()

            elif kind == "EQUIPES":
                out = pd.DataFrame({"municipio": mun})
                qtd_eq = first_existing(df.columns, ["QtdEquipes", "QTDEQUIPES", "QTD_EQUIPES"])
                tipo_eq = first_existing(df.columns, ["EquipeTipo", "EQUIPETIPO"])
                out["cnes_equipes_total"] = pd.to_numeric(df[qtd_eq], errors="coerce") if qtd_eq else 1
                if tipo_eq:
                    txt = df[tipo_eq].map(norm_text)
                    out["cnes_equipes_esf"] = np.where(txt.str.contains("SAUDE DA FAMILIA|ESF", na=False), out["cnes_equipes_total"], 0)
                else:
                    out["cnes_equipes_esf"] = np.nan
                agg = out.groupby("municipio", dropna=False).agg(
                    cnes_equipes_total=("cnes_equipes_total", "sum"),
                    cnes_equipes_esf=("cnes_equipes_esf", "sum"),
                ).reset_index()
            else:
                raise ValueError(f"Tipo CNES desconhecido: {kind}")

            parts.append(agg)
            log_step(f"[CNES-{kind}] chunk {i}: linhas={len(df)} acumulado={rows}")

        if not parts:
            return pd.DataFrame(columns=["municipio"])

        merged = pd.concat(parts, ignore_index=True)
        metric_cols = [c for c in merged.columns if c != "municipio"]
        merged = merged.groupby("municipio", dropna=False)[metric_cols].sum(numeric_only=True).reset_index()
        log_step(f"[CNES-{kind}] Concluído. linhas_lidas={rows}")
        return merged

    est_agg = aggregate_file_chunks(estab_path, "ESTAB")
    leitos_agg = aggregate_file_chunks(leitos_path, "LEITOS")
    eq_agg = aggregate_file_chunks(equip_path, "EQUIP")
    team_agg = aggregate_file_chunks(equipes_path, "EQUIPES")

    cap = est_agg.merge(leitos_agg, on="municipio", how="outer") \
                 .merge(eq_agg, on="municipio", how="outer") \
                 .merge(team_agg, on="municipio", how="outer")

    cap.to_csv(Path(outdir) / "cnes_capacity_municipio.csv", index=False, encoding="utf-8-sig")
    log_step("[CNES] Concluído e salvo cnes_capacity_municipio.csv")
    return cap

# ----------------------------
# LACEN demo + enrich
# ----------------------------
def build_lacen_demo(raw_path, pipeline_script, outdir, municipality_source="residencia", chunk_size=10000):
    mod = load_pipeline_module(pipeline_script)
    raw_path = resolve_existing_path(raw_path)
    req_frames = []
    pos_frames = []

    read_ok = False
    for enc in ["utf-8-sig", "utf-8", "latin1"]:
        try:
            log_step(f"[LACEN-DEMO] Tentando leitura do bruto com encoding={enc}")
            reader = pd.read_csv(raw_path, sep=",", encoding=enc, low_memory=False, chunksize=chunk_size, dtype=str)
            total_rows = 0
            total_norm = 0
            for i, chunk in enumerate(reader, start=1):
                total_rows += len(chunk)
                cols = set(chunk.columns)
                sex_col = first_existing(cols, SEX_CANDIDATES)
                race_col = first_existing(cols, RACE_CANDIDATES)
                school_col = first_existing(cols, SCHOOL_CANDIDATES)
                age_col = first_existing(cols, AGE_CANDIDATES)
                birth_col = first_existing(cols, BIRTH_CANDIDATES)

                event_date = mod.pick_event_date(chunk)
                municipio = mod.pick_municipality(chunk, municipality_source).map(norm_municipio)
                record_id = chunk.apply(mod.make_record_id, axis=1)

                if age_col:
                    ages = pd.to_numeric(chunk[age_col], errors="coerce")
                elif birth_col:
                    birth = safe_to_datetime(chunk[birth_col])
                    ages = ((safe_to_datetime(event_date) - birth).dt.days / 365.25).round(1)
                else:
                    ages = pd.Series(np.nan, index=chunk.index)

                demo = pd.DataFrame({
                    "record_id": record_id,
                    "event_date": safe_to_datetime(event_date),
                    "ano": safe_to_datetime(event_date).dt.year,
                    "municipio": municipio,
                    "sexo": chunk[sex_col].map(normalize_sex) if sex_col else "IGNORADO",
                    "faixa_etaria": ages.map(age_to_group),
                    "raca_cor": chunk[race_col].map(normalize_race) if race_col else "IGNORADO",
                    "escolaridade": chunk[school_col].map(normalize_schooling) if school_col else "IGNORADO",
                }).dropna(subset=["event_date"])

                req = demo.assign(solicitacoes=1).groupby(
                    ["ano", "municipio", "sexo", "faixa_etaria", "raca_cor", "escolaridade"],
                    dropna=False
                )["solicitacoes"].sum().reset_index()
                req_frames.append(req)

                norm = mod.normalize_chunk(chunk, municipality_source=municipality_source)
                if norm.empty:
                    if i % 10 == 0:
                        log_step(f"[LACEN-DEMO] chunk {i}: linhas={len(chunk)} acumulado={total_rows} normalizadas=0")
                    continue
                total_norm += len(norm)

                q = norm[norm["is_interpretable_result"]][
                    ["record_id", "target", "is_positive_like", "is_negative_like", "event_date"]
                ].copy()
                q["ano"] = pd.to_datetime(q["event_date"], errors="coerce").dt.year
                q = q.merge(demo.drop(columns=["event_date", "ano", "municipio"]), on="record_id", how="left")
                q["municipio"] = norm.drop_duplicates("record_id").set_index("record_id")["municipio"].reindex(q["record_id"]).values

                pos = q.groupby(
                    ["ano", "target", "municipio", "sexo", "faixa_etaria", "raca_cor", "escolaridade"],
                    dropna=False
                ).agg(
                    testes=("record_id", "count"),
                    positivos=("is_positive_like", "sum"),
                    negativos=("is_negative_like", "sum")
                ).reset_index()
                pos_frames.append(pos)

                if i % 10 == 0:
                    log_step(f"[LACEN-DEMO] chunk {i}: linhas={len(chunk)} acumulado={total_rows} normalizadas_acum={total_norm}")

            log_step(f"[LACEN-DEMO] Concluído com encoding={enc}. linhas_lidas={total_rows} normalizadas={total_norm}")
            read_ok = True
            break
        except Exception:
            continue

    if not read_ok:
        raise ValueError(f"Não foi possível ler o bruto do LACEN: {raw_path}")

    requests_demo = pd.concat(req_frames, ignore_index=True) if req_frames else pd.DataFrame()
    positivity_demo = pd.concat(pos_frames, ignore_index=True) if pos_frames else pd.DataFrame()

    if not requests_demo.empty:
        requests_demo.to_csv(Path(outdir) / "requests_by_demo.csv", index=False, encoding="utf-8-sig")

    if not positivity_demo.empty:
        positivity_demo["positividade"] = np.where(
            positivity_demo["testes"] > 0,
            positivity_demo["positivos"] / positivity_demo["testes"],
            np.nan
        )
        cis = positivity_demo.apply(lambda r: wilson_interval(r["positivos"], r["testes"]), axis=1)
        positivity_demo["ci_low"] = [x[0] for x in cis]
        positivity_demo["ci_high"] = [x[1] for x in cis]
        positivity_demo.to_csv(Path(outdir) / "positivity_by_demo.csv", index=False, encoding="utf-8-sig")

    return requests_demo, positivity_demo

def add_rates_and_ci(df):
    df = df.copy()
    if "populacao" in df.columns:
        df["solicitacoes_100k"] = np.where(df["populacao"]>0, df["tests"] / df["populacao"] * 100000, np.nan)
        df["incidencia_100k"] = np.where(df["populacao"]>0, df["positives"].fillna(0) / df["populacao"] * 100000, np.nan)
        df["notificacoes_100k"] = np.where(df["populacao"]>0, df["notificacoes"].fillna(0) / df["populacao"] * 100000, np.nan)
        df["mortalidade_100k"] = np.where(df["populacao"]>0, df["obitos_sim"].fillna(0) / df["populacao"] * 100000, np.nan)
    df["positividade"] = np.where(df["tests"] > 0, df["positives"] / df["tests"], np.nan)
    df["letalidade_proxy"] = np.where(df["notificacoes"] > 0, df["obitos_sim"].fillna(0) / df["notificacoes"], np.nan)
    pos_ci = df.apply(lambda r: wilson_interval(r["positives"], r["tests"]), axis=1)
    df["positivity_ci_low"] = [x[0] for x in pos_ci]
    df["positivity_ci_high"] = [x[1] for x in pos_ci]
    inc_ci = df.apply(lambda r: poisson_ci(r["positives"], r["populacao"]), axis=1)
    df["incidencia_ci_low"] = [x[0] for x in inc_ci]
    df["incidencia_ci_high"] = [x[1] for x in inc_ci]
    mort_ci = df.apply(lambda r: poisson_ci(r["obitos_sim"], r["populacao"]), axis=1)
    df["mortalidade_ci_low"] = [x[0] for x in mort_ci]
    df["mortalidade_ci_high"] = [x[1] for x in mort_ci]
    return df

def forecast_statewide(df, outdir):
    forecasts = []
    state = df.groupby(["epi_year","epi_week","target"], dropna=False).agg(
        tests=("tests","sum"),
        positives=("positives","sum"),
        notificacoes=("notificacoes","sum"),
        obitos_sim=("obitos_sim","sum"),
        populacao=("populacao","sum"),
    ).reset_index()
    state["positividade"] = np.where(state["tests"]>0, state["positives"]/state["tests"], np.nan)
    state["incidencia_100k"] = np.where(state["populacao"]>0, state["positives"]/state["populacao"]*100000, np.nan)
    state["notificacoes_100k"] = np.where(state["populacao"]>0, state["notificacoes"]/state["populacao"]*100000, np.nan)
    state["mortalidade_100k"] = np.where(state["populacao"]>0, state["obitos_sim"]/state["populacao"]*100000, np.nan)

    for target, sub in state.groupby("target"):
        sub = sub.sort_values(["epi_year","epi_week"]).reset_index(drop=True)
        if len(sub) < 12:
            continue
        hist = defaultdict(list)
        hist_pos = defaultdict(list)
        hist_inc = defaultdict(list)
        hist_not = defaultdict(list)
        hist_mort = defaultdict(list)
        for r in sub.itertuples(index=False):
            hist[int(r.epi_week)].append(float(r.tests))
            hist_pos[int(r.epi_week)].append(float(r.positividade) if pd.notna(r.positividade) else np.nan)
            hist_inc[int(r.epi_week)].append(float(r.incidencia_100k) if pd.notna(r.incidencia_100k) else np.nan)
            hist_not[int(r.epi_week)].append(float(r.notificacoes_100k) if pd.notna(r.notificacoes_100k) else np.nan)
            hist_mort[int(r.epi_week)].append(float(r.mortalidade_100k) if pd.notna(r.mortalidade_100k) else np.nan)

        y = int(sub.iloc[-1]["epi_year"]); w = int(sub.iloc[-1]["epi_week"])
        recent_t = sub["tests"].tail(8).astype(float).tolist()
        recent_p = sub["positividade"].tail(8).astype(float).tolist()
        recent_i = sub["incidencia_100k"].tail(8).astype(float).tolist()
        recent_n = sub["notificacoes_100k"].tail(8).astype(float).tolist()
        recent_m = sub["mortalidade_100k"].tail(8).astype(float).tolist()

        def mix(seasonal, recent):
            seasonal = pd.Series(seasonal).dropna()
            recent = pd.Series(recent).dropna()
            a = seasonal.median() if not seasonal.empty else np.nan
            b = recent.median() if not recent.empty else np.nan
            if pd.isna(a) and pd.isna(b): return np.nan
            if pd.isna(a): return b
            if pd.isna(b): return a
            return 0.4 * a + 0.6 * b

        for step in range(1, 5):
            w += 1
            if w > 53:
                w = 1; y += 1
            ft = mix(hist[w], recent_t)
            fp = mix(hist_pos[w], recent_p)
            fi = mix(hist_inc[w], recent_i)
            fn = mix(hist_not[w], recent_n)
            fm = mix(hist_mort[w], recent_m)
            forecasts.append({
                "target": target,
                "forecast_step": step,
                "forecast_epi_year": y,
                "forecast_epi_week": w,
                "forecast_tests": ft,
                "forecast_positividade": fp,
                "forecast_incidencia_100k": fi,
                "forecast_notificacoes_100k": fn,
                "forecast_mortalidade_100k": fm,
            })
            recent_t.append(ft); recent_p.append(fp); recent_i.append(fi); recent_n.append(fn); recent_m.append(fm)
            hist[w].append(ft); hist_pos[w].append(fp); hist_inc[w].append(fi); hist_not[w].append(fn); hist_mort[w].append(fm)

    out = pd.DataFrame(forecasts)
    out.to_csv(Path(outdir) / "forecast_integrated_statewide.csv", index=False, encoding="utf-8-sig")
    return out

def climate_association_summary(df, outdir):
    rows = []
    for target, sub in df.groupby("target"):
        for var in ["precipitation_sum_mm","temperature_2m_max","relative_humidity_2m_min","wind_speed_10m_max","n_eventos_climaticos","severidade_media"]:
            if var not in sub.columns:
                continue
            d = sub[[var,"positividade","tests","incidencia_100k","notificacoes_100k","mortalidade_100k"]].dropna(subset=[var])
            if len(d) < 20:
                continue
            rows.append({
                "target": target,
                "climate_var": var,
                "n_obs": len(d),
                "spearman_positividade": d[var].corr(d["positividade"], method="spearman") if d["positividade"].notna().sum() > 10 else np.nan,
                "spearman_testes": d[var].corr(d["tests"], method="spearman") if d["tests"].notna().sum() > 10 else np.nan,
                "spearman_incidencia": d[var].corr(d["incidencia_100k"], method="spearman") if d["incidencia_100k"].notna().sum() > 10 else np.nan,
                "spearman_notificacoes": d[var].corr(d["notificacoes_100k"], method="spearman") if d["notificacoes_100k"].notna().sum() > 10 else np.nan,
                "spearman_mortalidade": d[var].corr(d["mortalidade_100k"], method="spearman") if d["mortalidade_100k"].notna().sum() > 10 else np.nan,
            })
    out = pd.DataFrame(rows)
    out.to_csv(Path(outdir) / "climate_association_summary.csv", index=False, encoding="utf-8-sig")
    return out

def main():
    ap = argparse.ArgumentParser(description="Builder completo integrado LACEN + SIM + SINAN + CNES")
    ap.add_argument("--raw", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--pipeline-script", required=True)
    ap.add_argument("--geo-social", required=True)
    ap.add_argument("--climate", required=True)
    ap.add_argument("--municipios", required=True)
    ap.add_argument("--pea", required=True)
    ap.add_argument("--sim", required=True)
    ap.add_argument("--sinan", required=True)
    ap.add_argument("--cnes-estab", required=True)
    ap.add_argument("--cnes-leitos", required=True)
    ap.add_argument("--cnes-equip", required=True)
    ap.add_argument("--cnes-equipes", required=True)
    ap.add_argument("--chunk-size", type=int, default=10000)
    ap.add_argument("--municipality-source", choices=["residencia","solicitante","notificacao"], default="residencia")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    args.raw = str(resolve_existing_path(args.raw))
    args.pipeline_script = str(resolve_existing_path(args.pipeline_script))
    args.geo_social = str(resolve_existing_path(args.geo_social))
    args.climate = str(resolve_existing_path(args.climate))
    args.municipios = str(resolve_existing_path(args.municipios))
    args.pea = str(resolve_existing_path(args.pea))
    args.sim = str(resolve_existing_path(args.sim))
    args.sinan = str(resolve_existing_path(args.sinan))
    args.cnes_estab = str(resolve_existing_path(args.cnes_estab))
    args.cnes_leitos = str(resolve_existing_path(args.cnes_leitos))
    args.cnes_equip = str(resolve_existing_path(args.cnes_equip))
    args.cnes_equipes = str(resolve_existing_path(args.cnes_equipes))

    log_step("[1/7] Construindo base municipal")
    mm, pop = build_municipal_master(args.geo_social, args.municipios, args.pea, outdir)
    log_step("[2/7] Agregando clima semanal")
    climate = build_climate_weekly(args.climate, outdir)
    log_step("[3/7] Processando SINAN")
    sinan_weekly, sinan_demo = build_sinan_weekly(args.sinan, outdir)
    log_step("[4/7] Processando SIM")
    sim_weekly, sim_demo = build_sim_weekly(args.sim, outdir)
    log_step("[5/7] Processando CNES")
    cnes = build_cnes_capacity(args.cnes_estab, args.cnes_leitos, args.cnes_equip, args.cnes_equipes, outdir)

    log_step("[6/7] Lendo saídas do pipeline geral do LACEN")
    # LACEN base outputs
    py = pd.read_csv(outdir / "positivity_by_target_year.csv")
    pw = pd.read_csv(outdir / "positivity_by_target_epiweek_municipio.csv")
    wt = pd.read_csv(outdir / "weekly_tests_by_target_municipio.csv")
    alerts = pd.read_csv(outdir / "weekly_alerts.csv") if (outdir / "weekly_alerts.csv").exists() else pd.DataFrame()

    log_step("[7/7] Processando sociodemografia do LACEN bruto")
    build_lacen_demo(args.raw, args.pipeline_script, outdir, args.municipality_source, args.chunk_size)
    log_step("[7/7] Sociodemografia do LACEN concluída; iniciando integração final")

    weekly = wt.merge(
        pw[["epi_year","epi_week","target","municipio","tests","positives","negatives","positivity"]],
        on=["epi_year","epi_week","target","municipio"],
        how="left",
        suffixes=("", "_pw"),
    )
    if "tests_pw" in weekly.columns:
        weekly["tests"] = weekly["tests"].fillna(weekly["tests_pw"])
        weekly = weekly.drop(columns=["tests_pw"])
    weekly["ano"] = weekly["epi_year"]
    weekly = weekly.merge(pop, left_on=["municipio","ano"], right_on=["municipio","ano"], how="left")
    weekly = weekly.merge(mm, on="municipio", how="left")
    weekly = weekly.merge(climate, on=["municipio","epi_year","epi_week"], how="left")
    # Harmoniza nomes reais vindos do SINAN/SIM antes da integração
    sinan_merge = sinan_weekly.copy()
    if "notificacoes_sinan" in sinan_merge.columns and "notificacoes" not in sinan_merge.columns:
        sinan_merge = sinan_merge.rename(columns={"notificacoes_sinan": "notificacoes"})
    if "obitos_sinan" not in sinan_merge.columns:
        # SINAN aqui não produz óbitos; mantém coluna para compatibilidade do restante do fluxo
        sinan_merge["obitos_sinan"] = 0
    if "encerrados_sinan" not in sinan_merge.columns:
        sinan_merge["encerrados_sinan"] = 0

    sim_merge = sim_weekly.copy()
    if "obitos_sim" not in sim_merge.columns:
        sim_merge["obitos_sim"] = 0

    weekly = weekly.merge(
        sinan_merge[["epi_year","epi_week","target","municipio","notificacoes","obitos_sinan","encerrados_sinan"]],
        on=["epi_year","epi_week","target","municipio"],
        how="left"
    )
    weekly = weekly.merge(
        sim_merge[["epi_year","epi_week","target","municipio","obitos_sim"]],
        on=["epi_year","epi_week","target","municipio"],
        how="left"
    )
    weekly = weekly.merge(cnes, on="municipio", how="left")

    for c in ["notificacoes","obitos_sinan","encerrados_sinan","obitos_sim","cnes_estabelecimentos","cnes_leitos_total","cnes_leitos_uti","cnes_equipamentos_total","cnes_equipamentos_criticos","cnes_equipes_total"]:
        if c in weekly.columns:
            weekly[c] = pd.to_numeric(weekly[c], errors="coerce").fillna(0)

    if "populacao" in weekly.columns:
        weekly["leitos_100k"] = np.where(weekly["populacao"]>0, weekly["cnes_leitos_total"]/weekly["populacao"]*100000, np.nan)
        weekly["uti_100k"] = np.where(weekly["populacao"]>0, weekly["cnes_leitos_uti"]/weekly["populacao"]*100000, np.nan)
        weekly["equip_100k"] = np.where(weekly["populacao"]>0, weekly["cnes_equipamentos_criticos"]/weekly["populacao"]*100000, np.nan)

    weekly = add_rates_and_ci(weekly)

    weekly["lac_sinan_ratio"] = np.where(weekly["notificacoes"] > 0, weekly["positives"].fillna(0) / weekly["notificacoes"], np.nan)
    weekly["lac_request_notif_ratio"] = np.where(weekly["notificacoes"] > 0, weekly["tests"].fillna(0) / weekly["notificacoes"], np.nan)

    # anomaly scores by series
    weekly = weekly.sort_values(["target","municipio","epi_year","epi_week"]).reset_index(drop=True)
    for col in ["tests","positividade","incidencia_100k","notificacoes_100k","mortalidade_100k","precipitation_sum_mm","severidade_media"]:
        if col in weekly.columns:
            weekly[col + "_robust_z"] = weekly.groupby(["target","municipio"], dropna=False)[col].transform(lambda s: robust_z(s.fillna(s.median())))
    # capacity inverse
    if "leitos_100k" in weekly.columns:
        weekly["capacidade_inv_z"] = -robust_z(weekly["leitos_100k"].fillna(weekly["leitos_100k"].median()))
    else:
        weekly["capacidade_inv_z"] = 0.0

    weekly["risco_composto"] = (
        weekly.get("tests_robust_z", 0).clip(lower=0) * 0.20 +
        weekly.get("positividade_robust_z", 0).clip(lower=0) * 0.20 +
        weekly.get("incidencia_100k_robust_z", 0).clip(lower=0) * 0.15 +
        weekly.get("notificacoes_100k_robust_z", 0).clip(lower=0) * 0.10 +
        weekly.get("mortalidade_100k_robust_z", 0).clip(lower=0) * 0.15 +
        pd.to_numeric(weekly.get("indice_vulnerabilidade", 0), errors="coerce").fillna(0).clip(lower=0) * 0.10 +
        pd.to_numeric(weekly.get("capacidade_inv_z", 0), errors="coerce").fillna(0).clip(lower=0) * 0.05 +
        pd.to_numeric(weekly.get("severidade_media_robust_z", 0), errors="coerce").fillna(0).clip(lower=0) * 0.05
    )
    weekly["nivel_risco"] = pd.cut(weekly["risco_composto"], bins=[-np.inf,1,2,3,np.inf], labels=["habitual","atencao","alerta","alto_alerta"])

    # lag features
    for lag in [1,2,3,4]:
        for col in ["tests","positividade","incidencia_100k","notificacoes_100k","mortalidade_100k","precipitation_sum_mm","temperature_2m_max","relative_humidity_2m_min","n_eventos_climaticos","risco_composto"]:
            if col in weekly.columns:
                weekly[f"{col}_lag{lag}"] = weekly.groupby(["target","municipio"], dropna=False)[col].shift(lag)

    weekly.to_csv(outdir / "integrated_weekly_surveillance.csv", index=False, encoding="utf-8-sig")

    # enrich alerts
    if not alerts.empty:
        alerts2 = alerts.merge(
            weekly[["epi_year","epi_week","target","municipio","incidencia_100k","incidencia_ci_low","incidencia_ci_high","mortalidade_100k","notificacoes_100k","indice_vulnerabilidade","leitos_100k","precipitation_sum_mm","n_eventos_climaticos","risco_composto","nivel_risco","lac_sinan_ratio","lac_request_notif_ratio"]],
            on=["epi_year","epi_week","target","municipio"], how="left"
        )
        alerts2.to_csv(outdir / "integrated_alerts.csv", index=False, encoding="utf-8-sig")

    # summary tables
    summary = weekly.groupby(["target","municipio"], dropna=False).agg(
        semanas=("tests","count"),
        testes_total=("tests","sum"),
        positivos_total=("positives","sum"),
        notificacoes_total=("notificacoes","sum"),
        obitos_total=("obitos_sim","sum"),
        positividade_media=("positividade","mean"),
        incidencia_media_100k=("incidencia_100k","mean"),
        mortalidade_media_100k=("mortalidade_100k","mean"),
        risco_max=("risco_composto","max"),
        vulnerabilidade=("indice_vulnerabilidade","mean"),
        leitos_100k=("leitos_100k","mean"),
        chuva_media=("precipitation_sum_mm","mean"),
    ).reset_index()
    summary.to_csv(outdir / "integrated_target_municipio_summary.csv", index=False, encoding="utf-8-sig")

    # annual integrated summary
    annual = weekly.groupby(["ano","target"], dropna=False).agg(
        testes=("tests","sum"),
        positivos=("positives","sum"),
        notificacoes=("notificacoes","sum"),
        obitos=("obitos_sim","sum"),
        populacao=("populacao","sum"),
    ).reset_index()
    annual = add_rates_and_ci(annual.rename(columns={"ano":"ano_tmp"})).rename(columns={"ano_tmp":"ano"})
    annual.to_csv(outdir / "integrated_annual_summary.csv", index=False, encoding="utf-8-sig")

    climate_association_summary(weekly, outdir)
    forecast_statewide(weekly, outdir)

    # integrated demo
    pos_demo = pd.read_csv(outdir / "positivity_by_demo.csv") if (outdir / "positivity_by_demo.csv").exists() else pd.DataFrame()
    req_demo = pd.read_csv(outdir / "requests_by_demo.csv") if (outdir / "requests_by_demo.csv").exists() else pd.DataFrame()
    if not sinan_demo.empty:
        sinan_demo.to_csv(outdir / "sinan_demo.csv", index=False, encoding="utf-8-sig")
    if not sim_demo.empty:
        sim_demo.to_csv(outdir / "sim_demo.csv", index=False, encoding="utf-8-sig")

    print(f"Builder completo concluído. Arquivos gerados em: {outdir}")

if __name__ == "__main__":
    main()
