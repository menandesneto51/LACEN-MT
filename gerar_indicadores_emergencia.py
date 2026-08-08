# -*- coding: utf-8 -*-
"""Indicadores de emergência em saúde pública para LACEN-MT.

Consolida SLA de crise (≤48h / TAT p90), índice de pressão da rede,
alerta de silêncio GAL, divergência GAL×notificação e cartão executivo.

Prefere artefatos já publicados em saida_pipeline. Não lê o GAL bruto:
para %≤48h / SLA por família use gerar_indicadores_rede_lacen.py (--years).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent

FORMULA_PRESSAO = (
    "indice_pressao_rede = 100 × clip( "
    "0,30·volume_norm + 0,30·backlog_norm + 0,25·tat_p90_norm + 0,15·rejeicao_norm ; 0–1 ). "
    "volume_norm = exames/p95(exames); backlog_norm = backlog/max(exames,1) limitado a 1; "
    "tat_p90_norm = min(tat_p90/14, 2)/2; rejeicao_norm = min(pct_rejeitado/0,05, 2)/2."
)


def _read(outdir: Path, name: str, usecols: Optional[list[str]] = None) -> pd.DataFrame:
    for ext in (".parquet", ".csv"):
        path = outdir / f"{Path(name).stem}{ext}"
        if not path.exists():
            continue
        try:
            if path.suffix == ".parquet":
                df = pd.read_parquet(path)
            else:
                df = pd.read_csv(path, low_memory=False, usecols=usecols if usecols else None)
            return df
        except Exception:
            try:
                return pd.read_csv(path if path.suffix == ".csv" else outdir / f"{Path(name).stem}.csv",
                                   low_memory=False)
            except Exception:
                continue
    return pd.DataFrame()


def _norm01(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s, errors="coerce")
    return v.clip(lower=0, upper=1).fillna(0.0)


def _indice_pressao(rede: pd.DataFrame) -> pd.DataFrame:
    out = rede.copy()
    out["municipio"] = out["municipio"].astype(str).str.strip().str.upper()
    exames = pd.to_numeric(out.get("exames"), errors="coerce").fillna(0.0)
    backlog = pd.to_numeric(out.get("backlog_estimado"), errors="coerce").fillna(0.0)
    tat_p90 = pd.to_numeric(out.get("tat_p90_dias"), errors="coerce")
    reje = pd.to_numeric(out.get("pct_rejeitado"), errors="coerce").fillna(0.0)

    p95 = float(exames.quantile(0.95)) if len(exames) else 1.0
    p95 = max(p95, 1.0)
    volume_norm = (exames / p95).clip(0, 1)
    backlog_norm = (backlog / exames.clip(lower=1)).clip(0, 1)
    tat_norm = (tat_p90.fillna(14) / 14.0).clip(0, 2) / 2.0
    rej_norm = (reje / 0.05).clip(0, 2) / 2.0

    out["volume_norm"] = volume_norm.round(4)
    out["backlog_norm"] = backlog_norm.round(4)
    out["tat_p90_norm"] = tat_norm.round(4)
    out["rejeicao_norm"] = rej_norm.round(4)
    out["indice_pressao_rede"] = (
        100.0 * (0.30 * volume_norm + 0.30 * backlog_norm + 0.25 * tat_norm + 0.15 * rej_norm)
    ).clip(0, 100).round(2)
    out["faixa_pressao"] = pd.cut(
        out["indice_pressao_rede"],
        bins=[-0.01, 35, 55, 75, 100.01],
        labels=["baixa", "moderada", "alta", "critica"],
    ).astype(str)
    out["formula_pressao"] = FORMULA_PRESSAO
    return out


def _silencio_gal(weekly: pd.DataFrame, vizinhos: pd.DataFrame) -> pd.DataFrame:
    """Queda abrupta de exames vs histórico (8 SE) e vs vizinhos — distinto do silêncio SINAN."""
    if weekly is None or weekly.empty:
        return pd.DataFrame()

    w = weekly.copy()
    w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
    w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0.0)
    w["epi_year"] = pd.to_numeric(w.get("epi_year"), errors="coerce")
    w["epi_week"] = pd.to_numeric(w.get("epi_week"), errors="coerce")
    weeks = (
        w[["epi_year", "epi_week"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
    )
    if weeks.empty:
        return pd.DataFrame()
    last = weeks.tail(1)
    hist = weeks.tail(9).head(8)  # 8 SE anteriores à última
    last_y, last_w = int(last.iloc[0]["epi_year"]), int(last.iloc[0]["epi_week"])

    cur = (
        w.merge(last, on=["epi_year", "epi_week"], how="inner")
        .groupby("municipio", as_index=False)
        .agg(exames_ultima_se=("tests", "sum"))
    )
    base = (
        w.merge(hist, on=["epi_year", "epi_week"], how="inner")
        .groupby("municipio", as_index=False)
        .agg(
            exames_mediana_8se=("tests", "median"),
            exames_media_8se=("tests", "mean"),
            semanas_hist=("epi_week", "nunique"),
        )
    )
    out = base.merge(cur, on="municipio", how="outer").fillna(0)
    med = out["exames_mediana_8se"].clip(lower=0)
    # Queda abrupta: última SE ≤25% da mediana histórica, com histórico relevante
    queda = (med >= 5) & (out["exames_ultima_se"] <= 0.25 * med)
    silencio_absoluto = (med >= 3) & (out["exames_ultima_se"] <= 0)
    out["razao_exames_vs_hist"] = np.where(
        med > 0, (out["exames_ultima_se"] / med).round(3), np.nan
    )
    out["silencio_gal_alerta"] = queda | silencio_absoluto
    out["tipo_silencio_gal"] = np.select(
        [silencio_absoluto, queda],
        ["queda_absoluta", "queda_abrupta"],
        default="estavel",
    )
    out["epi_year_ref"] = last_y
    out["epi_week_ref"] = last_w
    out["fonte_silencio"] = "gal_weekly_vs_historico"
    out["nota_silencio"] = (
        "Alerta de silêncio GAL (exames) — distinto do silêncio SINAN/territorial em municipios_silenciosos."
    )

    # Comparação com vizinhos
    if vizinhos is not None and not vizinhos.empty and "vizinho" in vizinhos.columns:
        v = vizinhos.copy()
        v["municipio"] = v["municipio"].astype(str).str.strip().str.upper()
        v["vizinho"] = v["vizinho"].astype(str).str.strip().str.upper()
        vol = out.set_index("municipio")["exames_ultima_se"]
        v["exames_vizinho"] = v["vizinho"].map(vol).fillna(0)
        agg = v.groupby("municipio", as_index=False).agg(
            exames_mediana_vizinhos=("exames_vizinho", "median"),
            n_vizinhos_vol=("vizinho", "count"),
        )
        out = out.merge(agg, on="municipio", how="left")
        out["exames_mediana_vizinhos"] = out["exames_mediana_vizinhos"].fillna(0)
        out["silencio_gal_vs_vizinhos"] = (
            out["silencio_gal_alerta"]
            & (out["exames_mediana_vizinhos"] >= 5)
            & (out["exames_ultima_se"] < 0.5 * out["exames_mediana_vizinhos"])
        )
    else:
        out["exames_mediana_vizinhos"] = np.nan
        out["silencio_gal_vs_vizinhos"] = False
        out["n_vizinhos_vol"] = 0

    return out.sort_values(
        ["silencio_gal_alerta", "silencio_gal_vs_vizinhos", "exames_mediana_8se"],
        ascending=[False, False, False],
    )


def _divergencia_gal_notif(
    weekly: pd.DataFrame,
    qualidade: pd.DataFrame,
) -> pd.DataFrame:
    """Divergência exames GAL × notificações na mesma janela/município."""
    rows = []
    if qualidade is not None and not qualidade.empty:
        q = qualidade.copy()
        q["municipio"] = q["municipio"].astype(str).str.strip().str.upper()
        gap = q.get("gap_sinan_sem_exame")
        if gap is not None:
            mask = gap.fillna(False).astype(bool) | (
                (pd.to_numeric(q.get("notif_sinan"), errors="coerce").fillna(0) > 0)
                & (pd.to_numeric(q.get("exames"), errors="coerce").fillna(0) <= 0)
            )
            for _, r in q.loc[mask].iterrows():
                rows.append({
                    "municipio": r["municipio"],
                    "exames_janela": float(r.get("exames") or 0),
                    "notificacoes_janela": float(r.get("notif_sinan") or r.get("notif_join") or 0),
                    "divergencia_gal_notif": True,
                    "tipo_divergencia": "sinan_sem_exame",
                    "fonte_divergencia": "qualidade_dado_municipal",
                    "tipo_sinal": "Derivado",
                })

    if weekly is not None and not weekly.empty:
        w = weekly.copy()
        w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
        w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0)
        w["notificacoes"] = pd.to_numeric(w.get("notificacoes"), errors="coerce").fillna(0)
        weeks = (
            w[["epi_year", "epi_week"]]
            .dropna()
            .drop_duplicates()
            .sort_values(["epi_year", "epi_week"])
            .tail(1)
        )
        if not weeks.empty:
            cur = w.merge(weeks, on=["epi_year", "epi_week"], how="inner")
            g = cur.groupby("municipio", as_index=False).agg(
                exames_janela=("tests", "sum"),
                notificacoes_janela=("notificacoes", "sum"),
            )
            # Notificação sem exame OU exame sem notificação com volume extremo
            div = (
                ((g["notificacoes_janela"] >= 3) & (g["exames_janela"] <= 0))
                | ((g["exames_janela"] >= 20) & (g["notificacoes_janela"] <= 0))
            )
            already = {r["municipio"] for r in rows}
            for _, r in g.loc[div].iterrows():
                mun = r["municipio"]
                if mun in already:
                    continue
                tipo = (
                    "notif_sem_exame_semana"
                    if r["notificacoes_janela"] > 0 and r["exames_janela"] <= 0
                    else "exame_sem_notif_semana"
                )
                rows.append({
                    "municipio": mun,
                    "exames_janela": float(r["exames_janela"]),
                    "notificacoes_janela": float(r["notificacoes_janela"]),
                    "divergencia_gal_notif": True,
                    "tipo_divergencia": tipo,
                    "fonte_divergencia": "integrated_weekly_surveillance",
                    "tipo_sinal": "Derivado",
                    "epi_year_ref": int(weeks.iloc[0]["epi_year"]),
                    "epi_week_ref": int(weeks.iloc[0]["epi_week"]),
                })

    if not rows:
        return pd.DataFrame(columns=[
            "municipio", "exames_janela", "notificacoes_janela",
            "divergencia_gal_notif", "tipo_divergencia", "fonte_divergencia", "tipo_sinal",
        ])
    return pd.DataFrame(rows).drop_duplicates("municipio")


def _acoes_emergencia(df: pd.DataFrame) -> pd.DataFrame:
    try:
        from lacen_inteligencia import PROTOCOLOS, enriquecer_acoes
    except Exception:
        return df

    out = df.copy()
    # Sinal para protocolo
    def _sinal(row) -> str:
        if bool(row.get("sla_crise")):
            return "risco"
        if bool(row.get("silencio_gal_alerta")):
            return "silencio"
        if bool(row.get("divergencia_gal_notif")):
            return "utilizacao"
        if str(row.get("faixa_pressao", "")).lower() in {"alta", "critica"}:
            return "risco"
        return "padrao"

    out["sinal"] = out.apply(_sinal, axis=1)
    out = enriquecer_acoes(out)
    # Sobrescreve textos específicos de emergência quando aplicável
    crise = PROTOCOLOS.get("risco", {})
    sil = PROTOCOLOS.get("silencio", {})
    mask_sla = out.get("sla_crise", pd.Series(False, index=out.index)).fillna(False).astype(bool)
    if mask_sla.any():
        out.loc[mask_sla, "acao_sugerida"] = (
            "SLA de crise: reforçar liberação ≤48h, triagem de backlog e comunicação CIEVS/LACEN."
        )
        out.loc[mask_sla, "responsavel"] = crise.get("responsavel", "CIEVS / LACEN")
        out.loc[mask_sla, "prazo_acao"] = "24–48h"
        out.loc[mask_sla, "checklist_operacional"] = (
            "1) Conferir % liberado ≤48h e TAT p90; 2) Priorizar backlog; "
            "3) Articular rede municipal; 4) Reavaliar em 48h"
        )
    mask_sil = out.get("silencio_gal_alerta", pd.Series(False, index=out.index)).fillna(False).astype(bool)
    if mask_sil.any():
        out.loc[mask_sil, "acao_sugerida"] = (
            "Silêncio GAL: verificar fluxo de coleta/envio e queda abrupta de exames vs histórico/vizinhos."
        )
        out.loc[mask_sil, "responsavel"] = sil.get("responsavel", "Vigilância municipal + LACEN")
        out.loc[mask_sil, "prazo_acao"] = sil.get("prazo", "7 dias")
    return out


def build_indicadores_emergencia(outdir: Path | str = "saida_pipeline") -> dict[str, pd.DataFrame]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rede = _read(outdir, "indicadores_rede_laboratorial.csv")
    weekly = _read(outdir, "integrated_weekly_surveillance.csv")
    qualidade = _read(outdir, "qualidade_dado_municipal.csv")
    vizinhos = _read(outdir, "municipio_vizinhos.csv")
    familia = _read(outdir, "indicadores_rede_por_familia.csv")
    fila = _read(outdir, "fila_operacional.csv")
    silenciosos = _read(outdir, "municipios_silenciosos.csv")

    if rede.empty and weekly.empty:
        empty = pd.DataFrame()
        empty.to_csv(outdir / "indicadores_emergencia.csv", index=False, encoding="utf-8-sig")
        empty.to_csv(outdir / "indicadores_emergencia_resumo.csv", index=False, encoding="utf-8-sig")
        print("[EMERG] Sem base rede/weekly — arquivos vazios gerados.", flush=True)
        return {"emergencia": empty, "resumo": empty}

    # --- Pressão + SLA municipal ---
    if not rede.empty:
        base = _indice_pressao(rede)
        has_48h = "pct_liberado_48h" in base.columns and base["pct_liberado_48h"].notna().any()
        if not has_48h:
            base["pct_liberado_48h"] = np.nan
            base["sla_48h_fonte"] = "indisponivel_requer_regen_gal"
        else:
            base["sla_48h_fonte"] = "gal_lacen_microdados"
        # Crise SLA relativa: pior quartil de %≤48h (lab) OU pior quartil de TAT p90
        pct48 = pd.to_numeric(base["pct_liberado_48h"], errors="coerce")
        tat_p90 = pd.to_numeric(base.get("tat_p90_dias"), errors="coerce")
        pct7 = pd.to_numeric(base.get("pct_liberado_7d"), errors="coerce")
        tat_p75 = float(tat_p90.quantile(0.75)) if tat_p90.notna().any() else 90.0
        if has_48h:
            q25_48 = float(pct48.quantile(0.25)) if pct48.notna().any() else 0.50
            base["sla_crise"] = (pct48 <= q25_48) | (tat_p90 >= tat_p75)
            base["tipo_sinal_sla"] = "Observado"
            base["pct_liberado_48h_limiar_crise"] = q25_48
        else:
            q25_7 = float(pct7.quantile(0.25)) if pct7.notna().any() else 0.35
            base["sla_crise"] = (pct7 <= q25_7) | (tat_p90 >= tat_p75)
            base["tipo_sinal_sla"] = "Derivado"
            base["nota_sla"] = (
                "pct_liberado_48h ausente — proxy Derivado via %≤7d e TAT p90 (quartis). "
                "Regenere com gerar_indicadores_rede_lacen.py --years 3."
            )
            base["pct_liberado_48h_limiar_crise"] = np.nan
        base["tat_p90_limiar_crise"] = tat_p75
    else:
        # Fallback mínimo a partir do weekly (sem TAT)
        mun = (
            weekly.assign(municipio=weekly["municipio"].astype(str).str.strip().str.upper())
            .groupby("municipio", as_index=False)
            .agg(exames=("tests", "sum"))
        )
        base = mun
        base["indice_pressao_rede"] = np.nan
        base["faixa_pressao"] = ""
        base["pct_liberado_48h"] = np.nan
        base["tat_p90_dias"] = np.nan
        base["sla_crise"] = False
        base["tipo_sinal_sla"] = "Derivado"
        base["formula_pressao"] = FORMULA_PRESSAO
        base["sla_48h_fonte"] = "indisponivel"

    # --- Silêncio GAL ---
    sil_gal = _silencio_gal(weekly, vizinhos)
    if not sil_gal.empty:
        keep_sil = [
            c for c in [
                "municipio", "exames_ultima_se", "exames_mediana_8se", "razao_exames_vs_hist",
                "silencio_gal_alerta", "tipo_silencio_gal", "silencio_gal_vs_vizinhos",
                "exames_mediana_vizinhos", "epi_year_ref", "epi_week_ref",
                "fonte_silencio", "nota_silencio",
            ] if c in sil_gal.columns
        ]
        base = base.merge(sil_gal[keep_sil], on="municipio", how="outer")
    else:
        base["silencio_gal_alerta"] = False
        base["tipo_silencio_gal"] = ""

    # Distinção explícita do silêncio SINAN/territorial
    if not silenciosos.empty and "municipio" in silenciosos.columns:
        sinan_sil = set(
            silenciosos["municipio"].astype(str).str.strip().str.upper()
        )
        base["silencio_sinan_territorial"] = base["municipio"].isin(sinan_sil)
    else:
        base["silencio_sinan_territorial"] = False
    base["silencio_gal_distinto_sinan"] = (
        base.get("silencio_gal_alerta", False).fillna(False).astype(bool)
        & ~base["silencio_sinan_territorial"].fillna(False).astype(bool)
    )

    # --- Divergência ---
    div = _divergencia_gal_notif(weekly, qualidade)
    if not div.empty:
        keep_div = [
            c for c in [
                "municipio", "divergencia_gal_notif", "tipo_divergencia",
                "fonte_divergencia", "exames_janela", "notificacoes_janela",
            ] if c in div.columns
        ]
        base = base.merge(div[keep_div], on="municipio", how="left")
    base["divergencia_gal_notif"] = base.get("divergencia_gal_notif", False)
    base["divergencia_gal_notif"] = base["divergencia_gal_notif"].fillna(False).astype(bool)

    base["silencio_gal_alerta"] = base.get("silencio_gal_alerta", False)
    base["silencio_gal_alerta"] = base["silencio_gal_alerta"].fillna(False).astype(bool)
    base["sla_crise"] = base.get("sla_crise", False)
    base["sla_crise"] = base["sla_crise"].fillna(False).astype(bool)

    # Prioridade operacional
    vs_viz = (
        base["silencio_gal_vs_vizinhos"].fillna(False).astype(bool)
        if "silencio_gal_vs_vizinhos" in base.columns
        else pd.Series(False, index=base.index)
    )
    faixa = base.get("faixa_pressao", pd.Series("", index=base.index)).astype(str)
    base["prioridade_emergencia"] = np.select(
        [
            base["sla_crise"] & faixa.eq("critica"),
            base["sla_crise"] | vs_viz,
            base["silencio_gal_alerta"] | base["divergencia_gal_notif"],
            faixa.isin(["alta", "critica"]),
        ],
        ["CRÍTICO", "ALTO", "ALTO", "MODERADO"],
        default="MONITORAMENTO",
    )

    base = _acoes_emergencia(base)
    base["formula_pressao"] = FORMULA_PRESSAO
    base["tipo_sinal_pressao"] = "Derivado"

    # Enriquece com pressão Predito (ML), se já gerada
    pressao_ml = _read(outdir, "ml_pressao_rede_predito.csv")
    if not pressao_ml.empty and "municipio" in pressao_ml.columns:
        pressao_ml = pressao_ml.copy()
        pressao_ml["municipio"] = pressao_ml["municipio"].astype(str).str.strip().str.upper()
        keep_p = [
            c for c in (
                "municipio", "prob_pressao_alta_proxima_janela", "limiar_operacional",
                "acima_limiar", "faixa_pressao_predita", "drivers", "acao_sugerida",
            ) if c in pressao_ml.columns
        ]
        pm = pressao_ml[keep_p].drop_duplicates("municipio")
        rename = {
            "acima_limiar": "pressao_predita_acima_limiar",
            "drivers": "drivers_pressao_predita",
            "acao_sugerida": "acao_pressao_predita",
            "limiar_operacional": "limiar_pressao_predita",
        }
        pm = pm.rename(columns={k: v for k, v in rename.items() if k in pm.columns})
        base = base.merge(pm, on="municipio", how="left")
        base["tipo_sinal_pressao_predita"] = "Predito"
        # Eleva prioridade se Predito alta e ainda só monitoramento
        pred_alta = (
            base.get("pressao_predita_acima_limiar", pd.Series(False, index=base.index))
            .fillna(False).astype(bool)
        )
        faixa_cur = base.get("faixa_pressao", pd.Series("", index=base.index)).astype(str)
        mon = base["prioridade_emergencia"].astype(str).eq("MONITORAMENTO")
        base.loc[pred_alta & mon, "prioridade_emergencia"] = "MODERADO"
        base.loc[
            pred_alta
            & base["prioridade_emergencia"].astype(str).eq("MODERADO")
            & faixa_cur.isin(["alta", "critica"]),
            "prioridade_emergencia",
        ] = "ALTO"

    pri = {"CRÍTICO": 0, "ALTO": 1, "MODERADO": 2, "MONITORAMENTO": 3}
    base["_pr"] = base["prioridade_emergencia"].map(pri).fillna(9)
    base = base.sort_values(["_pr", "indice_pressao_rede"], ascending=[True, False]).drop(columns=["_pr"])

    out_csv = outdir / "indicadores_emergencia.csv"
    base.to_csv(out_csv, index=False, encoding="utf-8-sig")
    try:
        base.to_parquet(outdir / "indicadores_emergencia.parquet", index=False)
    except Exception:
        pass

    # --- Por família (SLA crise) ---
    if not familia.empty:
        fam = familia.copy()
        if "granularidade" in fam.columns:
            fam_state = fam[fam["granularidade"].astype(str) == "familia"].copy()
        else:
            fam_state = fam.copy()
        if "pct_liberado_48h" in fam_state.columns:
            p48 = pd.to_numeric(fam_state["pct_liberado_48h"], errors="coerce")
            p90 = pd.to_numeric(fam_state.get("tat_p90_dias"), errors="coerce")
            lim48 = float(p48.quantile(0.25)) if p48.notna().any() else 0.50
            lim90 = float(p90.quantile(0.75)) if p90.notna().any() else 90.0
            fam_state["sla_crise"] = (p48 <= lim48) | (p90.fillna(0) >= lim90)
        fam_state.to_csv(outdir / "indicadores_emergencia_familia.csv", index=False, encoding="utf-8-sig")
        try:
            fam_state.to_parquet(outdir / "indicadores_emergencia_familia.parquet", index=False)
        except Exception:
            pass
    else:
        fam_state = pd.DataFrame()

    # --- Resumo estadual / cartão executivo ---
    pct48_med = (
        float(pd.to_numeric(base["pct_liberado_48h"], errors="coerce").median())
        if "pct_liberado_48h" in base.columns and base["pct_liberado_48h"].notna().any()
        else None
    )
    tat_p90_med = (
        float(pd.to_numeric(base["tat_p90_dias"], errors="coerce").median())
        if "tat_p90_dias" in base.columns and base["tat_p90_dias"].notna().any()
        else None
    )
    pressao_med = (
        float(pd.to_numeric(base["indice_pressao_rede"], errors="coerce").median())
        if "indice_pressao_rede" in base.columns and base["indice_pressao_rede"].notna().any()
        else None
    )
    n_sil = int(base["silencio_gal_alerta"].sum())
    n_div = int(base["divergencia_gal_notif"].sum())
    n_sla = int(base["sla_crise"].sum())
    n_pressao = int(
        base.get("faixa_pressao", pd.Series(dtype=str)).astype(str).isin(["alta", "critica"]).sum()
    ) if "faixa_pressao" in base.columns else 0
    n_pressao_pred = int(
        base.get("pressao_predita_acima_limiar", pd.Series(False, index=base.index))
        .fillna(False).astype(bool).sum()
    ) if "pressao_predita_acima_limiar" in base.columns else 0
    prob_press_med = (
        float(pd.to_numeric(base["prob_pressao_alta_proxima_janela"], errors="coerce").median())
        if "prob_pressao_alta_proxima_janela" in base.columns
        and base["prob_pressao_alta_proxima_janela"].notna().any()
        else None
    )

    # Confirmação semanal (se já gerada nesta rodada ou anterior)
    conf = _read(outdir, "emergencia_confirmacao_resumo.csv")
    taxa_conf = None
    taxa_conf_sil = None
    if not conf.empty:
        taxa_conf = conf.iloc[0].get("taxa_confirmacao_geral")
        taxa_conf_sil = conf.iloc[0].get("taxa_confirmacao_silencio_gal")
        try:
            taxa_conf = float(taxa_conf) if pd.notna(taxa_conf) else None
        except Exception:
            taxa_conf = None
        try:
            taxa_conf_sil = float(taxa_conf_sil) if pd.notna(taxa_conf_sil) else None
        except Exception:
            taxa_conf_sil = None

    # Top ações (fila + emergência)
    top_acoes = base[base["prioridade_emergencia"].isin(["CRÍTICO", "ALTO"])].head(8).copy()
    if not fila.empty:
        f2 = fila.copy()
        f2["municipio"] = f2["municipio"].astype(str).str.strip().str.upper()
        # prioriza fila existente no texto do resumo
        top_fila_n = min(5, len(f2))
    else:
        top_fila_n = 0

    resumo = pd.DataFrame([{
        "kpi_pct_liberado_48h": pct48_med,
        "kpi_tat_p90_dias": tat_p90_med,
        "kpi_indice_pressao_rede": pressao_med,
        "kpi_n_silencio_gal": n_sil,
        "kpi_n_divergencia_gal_notif": n_div,
        "kpi_n_pressao_predita_alta": n_pressao_pred,
        "kpi_prob_pressao_predita_mediana": prob_press_med,
        "kpi_taxa_confirmacao_emergencia": taxa_conf,
        "kpi_taxa_confirmacao_silencio_gal": taxa_conf_sil,
        "n_municipios_sla_crise": n_sla,
        "n_municipios_pressao_alta_critica": n_pressao,
        "n_municipios": int(base["municipio"].nunique()),
        "n_acoes_prioritarias": int(len(top_acoes)),
        "n_itens_fila_operacional": top_fila_n if fila.empty else int(len(fila)),
        "formula_pressao": FORMULA_PRESSAO,
        "sla_48h_disponivel": bool(pct48_med is not None),
        "fonte": "saida_pipeline_consolidado",
        "tipo_sinal": "Observado/Derivado/Predito",
        "interpretacao": (
            f"Cartão emergência: %≤48h={pct48_med if pct48_med is not None else 'n/d'}; "
            f"TAT p90={tat_p90_med if tat_p90_med is not None else 'n/d'}d; "
            f"pressão obs={pressao_med if pressao_med is not None else 'n/d'}; "
            f"pressão predita alta={n_pressao_pred} mun; "
            f"silêncio GAL={n_sil}; divergência GAL×notif={n_div}; SLA crise={n_sla} mun"
            + (
                f"; confirmação alertas={taxa_conf:.0%}."
                if taxa_conf is not None else "."
            )
        ),
    }])
    resumo.to_csv(outdir / "indicadores_emergencia_resumo.csv", index=False, encoding="utf-8-sig")
    try:
        resumo.to_parquet(outdir / "indicadores_emergencia_resumo.parquet", index=False)
    except Exception:
        pass

    # Ações top para o cartão (artefato leve)
    acoes_cols = [
        c for c in [
            "municipio", "prioridade_emergencia", "sla_crise", "indice_pressao_rede",
            "faixa_pressao", "prob_pressao_alta_proxima_janela", "faixa_pressao_predita",
            "pct_liberado_48h", "tat_p90_dias",
            "silencio_gal_alerta", "divergencia_gal_notif",
            "acao_sugerida", "responsavel", "prazo_acao", "checklist_operacional",
        ] if c in top_acoes.columns
    ]
    top_acoes[acoes_cols].to_csv(
        outdir / "indicadores_emergencia_acoes.csv", index=False, encoding="utf-8-sig"
    )
    try:
        top_acoes[acoes_cols].to_parquet(
            outdir / "indicadores_emergencia_acoes.parquet", index=False
        )
    except Exception:
        pass

    print(
        f"[EMERG] mun={len(base)} | SLA crise={n_sla} | silêncio GAL={n_sil} | "
        f"divergência={n_div} | pressão med={pressao_med} | %≤48h={pct48_med}",
        flush=True,
    )
    return {
        "emergencia": base,
        "resumo": resumo,
        "familia": fam_state,
        "acoes": top_acoes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Indicadores de emergência LACEN-MT")
    ap.add_argument("--outdir", default="saida_pipeline")
    args = ap.parse_args()
    build_indicadores_emergencia(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
