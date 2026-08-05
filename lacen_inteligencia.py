# -*- coding: utf-8 -*-
"""Inteligência operacional LACEN MT: vizinhos, protocolos de ação e confiança do dado."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Bounding box aproximado de Mato Grosso (filtra lat/lon corrompidos)
MT_LAT = (-18.5, -7.0)
MT_LON = (-62.5, -50.0)

# Protocolos por família de agravo / sinal
PROTOCOLOS = {
    "tuberculose": {
        "responsavel": "Vigilância municipal de TB + LACEN",
        "prazo": "48h",
        "checklist": "1) Confirmar amostra no GAL; 2) Articular busca de sintomáticos; 3) Verificar baciloscopia/LF-LAM pendentes",
        "acao": "Ativar busca ativa de TB e validar fluxo de coleta/envio ao LACEN em até 48h.",
    },
    "hepatite": {
        "responsavel": "Vigilância de hepatites + LACEN",
        "prazo": "7 dias",
        "checklist": "1) Revisar positivos HBV/HCV; 2) Checar encaminhamento clínico; 3) Avaliar cobertura de testagem",
        "acao": "Validar positivos de hepatite, revisar tendência e reforçar testagem/encaminhamento em 7 dias.",
    },
    "arbovirose": {
        "responsavel": "Vigilância de arboviroses + CIEVS",
        "prazo": "24–72h",
        "checklist": "1) Conferir positividade dengue/zika/chik/oropouche; 2) Cruzar com SINAN; 3) Avaliar municípios vizinhos",
        "acao": "Investigar pico de arbovirose, cruzar com notificações e monitorar cluster territorial em 24–72h.",
    },
    "respiratorio": {
        "responsavel": "Vigilância de influenza/COVID + LACEN",
        "prazo": "48h",
        "checklist": "1) Validar positivos respiratórios; 2) Verificar capacidade laboratorial; 3) Comunicar CIEVS se tendência ascendente",
        "acao": "Monitorar tendência respiratória, validar positivos e articular resposta em 48h.",
    },
    "silencio": {
        "responsavel": "Vigilância municipal + referência LACEN",
        "prazo": "7 dias",
        "checklist": "1) Verificar fluxo GAL/coleta; 2) Conferir casos SINAN sem exame; 3) Sensibilizar SMS; 4) Checar vizinhos em alerta",
        "acao": "Priorizar busca ativa: verificar fluxo de coleta/envio e sensibilizar vigilância municipal em 7 dias.",
    },
    "risco": {
        "responsavel": "CIEVS / Sala de Situação + vigilância municipal",
        "prazo": "48–72h",
        "checklist": "1) Revisar score de risco; 2) Validar exames/positivos; 3) Articular resposta municipal; 4) Reavaliar na próxima SE",
        "acao": "Monitorar tendência, validar positivos e articular resposta municipal em 48–72h.",
    },
    "utilizacao": {
        "responsavel": "Vigilância municipal + LACEN",
        "prazo": "15 dias",
        "checklist": "1) Comparar exames×notificações; 2) Identificar subutilização; 3) Reforçar encaminhamento laboratorial",
        "acao": "Avaliar subutilização da rede e reforçar encaminhamento de amostras em 15 dias.",
    },
    "padrao": {
        "responsavel": "Vigilância municipal",
        "prazo": "próxima SE",
        "checklist": "1) Acompanhar indicadores; 2) Reavaliar na próxima janela epidemiológica",
        "acao": "Acompanhar indicadores e reavaliar na próxima janela epidemiológica.",
    },
}


def familia_agravo(target: object) -> str:
    t = str(target or "").casefold()
    if any(x in t for x in ("tuberculose", "baciloscopia", "rifampicina", "lf_lam")):
        return "tuberculose"
    if "hepatite" in t:
        return "hepatite"
    if any(x in t for x in ("dengue", "zika", "chikungunya", "oropouche", "mayaro", "febre_amarela")):
        return "arbovirose"
    if any(x in t for x in ("influenza", "sars_cov", "covid", "respirat", "virus_respiratorio")):
        return "respiratorio"
    return ""


def protocolo_para_linha(row: pd.Series) -> dict:
    sinal = str(row.get("sinal", "") or "").casefold()
    faixa = str(
        row.get("faixa_risco", "")
        or row.get("classificacao_silencio", "")
        or row.get("tipo_sinal", "")
        or ""
    ).casefold()
    cls = str(row.get("classificacao_uso", "") or "").casefold()
    fam = familia_agravo(row.get("agravo_alvo") or row.get("target") or "")

    if "silencio" in sinal or "silencio" in faixa or bool(row.get("silencio_laboratorial", False)):
        key = "silencio"
    elif "risco" in sinal or faixa in {"alerta", "alto_alerta", "atencao"}:
        key = fam if fam in PROTOCOLOS else "risco"
    elif "utiliz" in sinal or cls in {"baixo", "silencio"} or bool(row.get("baixo_uso_lacen", False)):
        key = "utilizacao"
    elif fam:
        key = fam
    else:
        key = "padrao"
    return PROTOCOLOS[key].copy()


def enriquecer_acoes(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    out = df.copy()
    proto = out.apply(protocolo_para_linha, axis=1, result_type="expand")
    out["acao_sugerida"] = proto["acao"]
    out["responsavel"] = proto["responsavel"]
    out["prazo_acao"] = proto["prazo"]
    out["checklist_operacional"] = proto["checklist"]
    return out


def _haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def coords_validas(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["latitude"] = pd.to_numeric(out.get("latitude"), errors="coerce")
    out["longitude"] = pd.to_numeric(out.get("longitude"), errors="coerce")
    out["municipio"] = out["municipio"].astype(str).str.strip().str.upper()
    mask = (
        out["latitude"].between(*MT_LAT)
        & out["longitude"].between(*MT_LON)
        & out["municipio"].ne("")
    )
    return out.loc[mask, ["municipio", "latitude", "longitude"]].drop_duplicates("municipio")


def build_vizinhos(
    municipal_master: pd.DataFrame,
    k: int = 6,
    max_km: float = 120.0,
) -> pd.DataFrame:
    """Grafo k-vizinhos mais próximos (Haversine), filtrando coordenadas inválidas."""
    geo = coords_validas(municipal_master)
    if len(geo) < 3:
        return pd.DataFrame(columns=["municipio", "vizinho", "dist_km", "rank_vizinho"])

    munis = geo["municipio"].tolist()
    lats = geo["latitude"].to_numpy(dtype=float)
    lons = geo["longitude"].to_numpy(dtype=float)
    rows = []
    for i, m in enumerate(munis):
        d = _haversine_km(lats[i], lons[i], lats, lons)
        d[i] = np.inf
        order = np.argsort(d)
        rank = 0
        for j in order:
            if not np.isfinite(d[j]) or d[j] > max_km:
                continue
            rank += 1
            rows.append({
                "municipio": m,
                "vizinho": munis[j],
                "dist_km": round(float(d[j]), 2),
                "rank_vizinho": rank,
            })
            if rank >= k:
                break
    return pd.DataFrame(rows)


def enriquecer_silencio_com_vizinhos(
    silenciosos: pd.DataFrame,
    risco: pd.DataFrame,
    vizinhos: pd.DataFrame,
) -> pd.DataFrame:
    """Eleva silêncio quando vizinhos estão em alerta/alto alerta."""
    if silenciosos is None or silenciosos.empty or vizinhos is None or vizinhos.empty:
        return silenciosos if silenciosos is not None else pd.DataFrame()

    out = silenciosos.copy()
    alert_muns: set[str] = set()
    if risco is not None and not risco.empty and "faixa_risco" in risco.columns:
        alert_muns = set(
            risco.loc[
                risco["faixa_risco"].astype(str).isin(["alerta", "alto_alerta"]),
                "municipio",
            ]
            .astype(str)
            .str.upper()
        )

    if not alert_muns:
        out["vizinhos_em_alerta"] = 0
        out["silencio_com_vizinho_alerta"] = False
        return out

    v = vizinhos.copy()
    v["municipio"] = v["municipio"].astype(str).str.upper()
    v["vizinho"] = v["vizinho"].astype(str).str.upper()
    v["vizinho_alerta"] = v["vizinho"].isin(alert_muns)
    agg = v.groupby("municipio", as_index=False).agg(
        vizinhos_em_alerta=("vizinho_alerta", "sum"),
        n_vizinhos=("vizinho", "count"),
    )
    out["municipio"] = out["municipio"].astype(str).str.upper()
    out = out.merge(agg, on="municipio", how="left")
    out["vizinhos_em_alerta"] = out["vizinhos_em_alerta"].fillna(0).astype(int)
    out["silencio_com_vizinho_alerta"] = out["vizinhos_em_alerta"] > 0

    # Upgrade de classificação e score
    if "score_silencio" in out.columns:
        out["score_silencio"] = pd.to_numeric(out["score_silencio"], errors="coerce").fillna(0)
        out.loc[out["silencio_com_vizinho_alerta"], "score_silencio"] = (
            out.loc[out["silencio_com_vizinho_alerta"], "score_silencio"] + 1.5
        )
    if "classificacao_silencio" in out.columns:
        up = out["silencio_com_vizinho_alerta"] & out["classificacao_silencio"].astype(str).isin(
            ["silencio_moderado", "silencio_provavel", "baixo_uso_lacen"]
        )
        out.loc[up, "classificacao_silencio"] = "silencio_critico"
        out.loc[up, "tipo_sinal"] = "silencio_critico"
        out.loc[out["silencio_com_vizinho_alerta"], "motivo_territorial"] = (
            "Silêncio com vizinho(s) em alerta — possível falha de captação no cluster"
        )
    return out


def enriquecer_fila_com_ml(
    fila: pd.DataFrame,
    ml_risco: Optional[pd.DataFrame] = None,
    ml_silencio: Optional[pd.DataFrame] = None,
    limiar_ml: float = 0.55,
) -> pd.DataFrame:
    """
    Cruza fila operacional com ML: alerta híbrido = regra operacional + ML alto.
    """
    if fila is None or fila.empty:
        return fila if fila is not None else pd.DataFrame()

    out = fila.copy()
    out["municipio"] = out["municipio"].astype(str).str.strip().str.upper()
    out["prob_ml"] = np.nan
    out["faixa_ml"] = ""
    out["alerta_hibrido"] = False

    risco_map = pd.DataFrame()
    if ml_risco is not None and not ml_risco.empty and "municipio" in ml_risco.columns:
        rr = ml_risco.copy()
        rr["municipio"] = rr["municipio"].astype(str).str.strip().str.upper()
        pcol = "prob_alerta_proxima_janela"
        if pcol in rr.columns:
            idx = rr.groupby("municipio")[pcol].idxmax()
            keep = ["municipio", pcol]
            rename = {pcol: "prob_ml_risco"}
            for src, dst in (
                ("faixa_predita", "faixa_ml_risco"),
                ("banda_risco", "banda_risco"),
                ("banda_absoluta", "banda_absoluta"),
                ("banda_percentil", "banda_percentil"),
                ("percentil_estadual", "percentil_estadual"),
                ("criterio_banda", "criterio_banda"),
            ):
                if src in rr.columns:
                    keep.append(src)
                    rename[src] = dst
            risco_map = rr.loc[idx, keep].rename(columns=rename)
            if "faixa_ml_risco" not in risco_map.columns:
                risco_map["faixa_ml_risco"] = ""


    sil_map = pd.DataFrame()
    if ml_silencio is not None and not ml_silencio.empty and "municipio" in ml_silencio.columns:
        ss = ml_silencio.copy()
        ss["municipio"] = ss["municipio"].astype(str).str.strip().str.upper()
        pcol = "prob_silencio_proxima_janela"
        if pcol in ss.columns:
            sil_map = (
                ss.groupby("municipio", as_index=False)
                .agg(prob_ml_silencio=(pcol, "max"))
            )

    if not risco_map.empty:
        out = out.merge(risco_map, on="municipio", how="left")
    else:
        out["prob_ml_risco"] = np.nan
        out["faixa_ml_risco"] = ""
        out["banda_risco"] = ""

    if not sil_map.empty:
        out = out.merge(sil_map, on="municipio", how="left")
    else:
        out["prob_ml_silencio"] = np.nan

    # Probabilidade relevante conforme o tipo de sinal
    sil_mask = out["sinal"].astype(str).str.contains("silencio", case=False, na=False)
    out.loc[sil_mask, "prob_ml"] = out.loc[sil_mask, "prob_ml_silencio"]
    out.loc[~sil_mask, "prob_ml"] = out.loc[~sil_mask, "prob_ml_risco"]
    if "faixa_ml_risco" in out.columns:
        out.loc[~sil_mask, "faixa_ml"] = out.loc[~sil_mask, "faixa_ml_risco"].fillna("").astype(str)
    if "banda_risco" in out.columns:
        out["banda_risco"] = out["banda_risco"].fillna("").astype(str)

    out["alerta_hibrido"] = (
        out["prioridade"].astype(str).isin(["CRÍTICO", "ALTO"])
        & out["prob_ml"].fillna(0).ge(limiar_ml)
    )
    # Eleva prioridade quando banda combinada é Crítico
    if "banda_risco" in out.columns:
        out.loc[
            out["banda_risco"].astype(str).eq("Crítico") & out["prioridade"].astype(str).eq("ALTO"),
            "prioridade",
        ] = "CRÍTICO"
    # Reforça prioridade quando híbrido
    out.loc[out["alerta_hibrido"] & out["prioridade"].astype(str).eq("ALTO"), "prioridade"] = "CRÍTICO"
    out.loc[out["alerta_hibrido"], "motivo"] = (
        out.loc[out["alerta_hibrido"], "motivo"].astype(str)
        + " | ML confirma (prob="
        + out.loc[out["alerta_hibrido"], "prob_ml"].round(2).astype(str)
        + ")"
    )
    return out


def qualidade_dado_semanal(weekly: pd.DataFrame, sinan: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Indicadores de confiança/qualidade por município na janela recente."""
    if weekly is None or weekly.empty:
        return pd.DataFrame()

    df = weekly.copy()
    df["municipio"] = df["municipio"].astype(str).str.strip().str.upper()
    for c in ("tests", "positives", "notificacoes", "obitos_sim", "populacao"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    weeks = (
        df[["epi_year", "epi_week"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
    )
    keep = weeks.tail(8)
    recent = df.merge(keep, on=["epi_year", "epi_week"], how="inner")

    g = recent.groupby("municipio", as_index=False).agg(
        exames=("tests", "sum"),
        positivos=("positives", "sum"),
        notif_join=("notificacoes", "sum"),
        semanas_com_dado=("epi_week", "nunique"),
        populacao=("populacao", "max"),
    )

    # SINAN direto (mais confiável que o join por alvo)
    if sinan is not None and not sinan.empty:
        sw = sinan.copy()
        sw["municipio"] = sw["municipio"].astype(str).str.strip().str.upper()
        sw["epi_year"] = pd.to_numeric(sw.get("epi_year"), errors="coerce")
        sw["epi_week"] = pd.to_numeric(sw.get("epi_week"), errors="coerce")
        ncol = "notificacoes_sinan" if "notificacoes_sinan" in sw.columns else "notificacoes"
        if ncol in sw.columns:
            sw[ncol] = pd.to_numeric(sw[ncol], errors="coerce").fillna(0)
            sw = sw.merge(keep, on=["epi_year", "epi_week"], how="inner")
            sagg = sw.groupby("municipio", as_index=False).agg(notif_sinan=(ncol, "sum"))
            g = g.merge(sagg, on="municipio", how="outer")
    if "notif_sinan" not in g.columns:
        g["notif_sinan"] = np.nan

    g["exames"] = g["exames"].fillna(0)
    g["notif_join"] = g["notif_join"].fillna(0)
    g["notif_sinan"] = g["notif_sinan"].fillna(0)
    g["semanas_com_dado"] = g["semanas_com_dado"].fillna(0)

    gap_sinan = (g["notif_sinan"] > 0) & (g["exames"] <= 0)
    join_fraco = (g["notif_sinan"] > 0) & (g["notif_join"] <= 0)
    cobertura_semanas = (g["semanas_com_dado"] / 8.0).clip(0, 1)

    # Confiança 0–1
    conf = (
        0.35 * cobertura_semanas
        + 0.25 * (g["exames"] > 0).astype(float)
        + 0.20 * (~gap_sinan).astype(float)
        + 0.20 * (~join_fraco).astype(float)
    )
    g["confianca_dado"] = conf.round(3)
    g["faixa_confianca"] = pd.cut(
        g["confianca_dado"],
        bins=[-0.01, 0.35, 0.60, 0.80, 1.01],
        labels=["baixa", "moderada", "boa", "alta"],
    ).astype(str)
    g["gap_sinan_sem_exame"] = gap_sinan
    g["join_sinan_fraco"] = join_fraco
    g["interpretacao"] = np.select(
        [
            gap_sinan,
            join_fraco,
            g["confianca_dado"] < 0.35,
            g["confianca_dado"] >= 0.8,
        ],
        [
            "SINAN com notificação e ausência de exame LACEN — possível silêncio de captação",
            "SINAN existe mas pouco cruzou no join por alvo — revisar mapeamento agravo×exame",
            "Poucas semanas com dado — interpretar indicadores com cautela",
            "Boa cobertura recente de exames/notificações",
        ],
        default="Cobertura intermediária — monitorar",
    )
    return g.sort_values(["confianca_dado", "exames"], ascending=[True, True]).reset_index(drop=True)
