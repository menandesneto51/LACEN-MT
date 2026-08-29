# -*- coding: utf-8 -*-
"""Loop semanal de confirmação de alertas de emergência.

Preferência:
1) Flags carimbados em alerta_emergencia_historico.csv (≥2 SE distintas) →
   confirmação prospectiva Observado (alerta stampado × desfecho futuro).
2) Se histórico vazio/curto → reconstrução retrospectiva Derivado
   (weekly + rede), como fallback.

Saída: emergencia_confirmacao_resumo.csv (+ detalhe opcional).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def _read(outdir: Path, name: str) -> pd.DataFrame:
    for ext in (".parquet", ".csv"):
        path = outdir / f"{Path(name).stem}{ext}"
        if not path.exists():
            continue
        try:
            if path.suffix == ".parquet":
                return pd.read_parquet(path)
            return pd.read_csv(path, low_memory=False)
        except Exception:
            continue
    return pd.DataFrame()


def _week_list(weekly: pd.DataFrame, n_weeks: int = 12) -> pd.DataFrame:
    weeks = (
        weekly[["epi_year", "epi_week"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["epi_year", "epi_week"])
        .reset_index(drop=True)
    )
    if len(weeks) <= 2:
        return weeks
    return weeks.iloc[max(0, len(weeks) - n_weeks - 1) : -1].reset_index(drop=True)


def _mun_week_vol(weekly: pd.DataFrame) -> pd.DataFrame:
    w = weekly.copy()
    w["municipio"] = w["municipio"].astype(str).str.strip().str.upper()
    w["tests"] = pd.to_numeric(w.get("tests"), errors="coerce").fillna(0)
    w["notificacoes"] = pd.to_numeric(w.get("notificacoes"), errors="coerce").fillna(0)
    return (
        w.groupby(["municipio", "epi_year", "epi_week"], as_index=False)
        .agg(exames=("tests", "sum"), notificacoes=("notificacoes", "sum"))
    )


def _flags_for_week(
    vol: pd.DataFrame,
    year: int,
    week: int,
    rede: pd.DataFrame,
    hist_weeks: pd.DataFrame,
) -> pd.DataFrame:
    """Flags de emergência na SE de referência (reconstrução retrospectiva)."""
    cur = vol[(vol["epi_year"] == year) & (vol["epi_week"] == week)].copy()
    if cur.empty:
        return pd.DataFrame()

    hist_keys = hist_weeks[
        (hist_weeks["epi_year"] < year)
        | ((hist_weeks["epi_year"] == year) & (hist_weeks["epi_week"] < week))
    ].tail(8)
    if not hist_keys.empty:
        hist = vol.merge(hist_keys, on=["epi_year", "epi_week"], how="inner")
        base = hist.groupby("municipio", as_index=False).agg(
            exames_mediana_8se=("exames", "median"),
            exames_media_8se=("exames", "mean"),
        )
        cur = cur.merge(base, on="municipio", how="left")
    else:
        cur["exames_mediana_8se"] = np.nan
        cur["exames_media_8se"] = np.nan

    med = cur["exames_mediana_8se"].fillna(0).clip(lower=0)
    cur["silencio_gal"] = ((med >= 5) & (cur["exames"] <= 0.25 * med)) | (
        (med >= 3) & (cur["exames"] <= 0)
    )
    cur["divergencia"] = (cur["notificacoes"] >= 3) & (cur["exames"] <= 0)

    cur["pct_vol"] = cur["exames"].rank(pct=True)
    pressao_vol = cur["pct_vol"] >= 0.75

    if rede is not None and not rede.empty:
        r = rede.copy()
        r["municipio"] = r["municipio"].astype(str).str.strip().str.upper()
        keep = [c for c in (
            "municipio", "indice_pressao_rede", "faixa_pressao", "sla_crise",
            "pct_liberado_48h", "tat_p90_dias", "backlog_estimado",
        ) if c in r.columns]
        if "indice_pressao_rede" not in r.columns and "exames" in r.columns:
            try:
                from gerar_indicadores_emergencia import _indice_pressao
                r = _indice_pressao(r)
                keep = [c for c in (
                    "municipio", "indice_pressao_rede", "faixa_pressao",
                    "pct_liberado_48h", "tat_p90_dias", "backlog_estimado",
                ) if c in r.columns]
            except Exception:
                pass
        cur = cur.merge(r[keep], on="municipio", how="left")
        faixa = cur.get("faixa_pressao", pd.Series("", index=cur.index)).astype(str)
        pressao_rede = faixa.isin(["alta", "critica"]) | (
            pd.to_numeric(cur.get("indice_pressao_rede"), errors="coerce").fillna(0) >= 55
        )
        if "sla_crise" in cur.columns:
            sla = cur["sla_crise"].fillna(False).astype(bool)
        else:
            pct48 = pd.to_numeric(cur.get("pct_liberado_48h"), errors="coerce")
            tat = pd.to_numeric(cur.get("tat_p90_dias"), errors="coerce")
            sla = False
            if pct48.notna().any():
                sla = pct48 <= float(pct48.quantile(0.25))
            if tat.notna().any():
                sla = sla | (tat >= float(tat.quantile(0.75)))
            cur["sla_crise"] = sla
    else:
        pressao_rede = pd.Series(False, index=cur.index)
        cur["sla_crise"] = False
        cur["indice_pressao_rede"] = np.nan

    cur["pressao_alta"] = pressao_vol | pressao_rede.fillna(False)
    cur["epi_year_ref"] = year
    cur["epi_week_ref"] = week
    return cur


def _future_outcomes(
    vol: pd.DataFrame,
    municipio: str,
    year: int,
    week: int,
    horizon: int = 2,
) -> dict:
    rows = []
    y, w = int(year), int(week)
    for _ in range(horizon):
        w += 1
        if w > 53:
            w = 1
            y += 1
        sub = vol[(vol["municipio"] == municipio) & (vol["epi_year"] == y) & (vol["epi_week"] == w)]
        if not sub.empty:
            rows.append(sub.iloc[0])
    if not rows:
        return {"tem_futuro": False}
    fut = pd.DataFrame(rows)
    exames = pd.to_numeric(fut["exames"], errors="coerce").fillna(0)
    notif = pd.to_numeric(fut["notificacoes"], errors="coerce").fillna(0)
    return {
        "tem_futuro": True,
        "exames_futuro": float(exames.sum()),
        "exames_max_futuro": float(exames.max()),
        "notif_futuro": float(notif.sum()),
        "semanas_futuro": int(len(fut)),
    }


def _confirm_tipo(tipo: str, r: pd.Series, outc: dict) -> bool:
    if tipo == "silencio_gal":
        med = float(r.get("exames_mediana_8se") or r.get("exames_ref") or 0)
        return (
            outc["exames_futuro"] <= 0.5 * max(med, 1) * outc["semanas_futuro"]
            or outc["exames_max_futuro"] <= 0
        )
    if tipo == "divergencia":
        return (outc["notif_futuro"] >= 2) and (
            outc["exames_futuro"] < 0.5 * outc["notif_futuro"]
        )
    if tipo == "pressao_alta":
        return outc["exames_max_futuro"] >= max(
            5.0, 0.75 * float(r.get("exames") or r.get("exames_ref") or 0)
        )
    # sla_crise
    return outc["exames_futuro"] >= max(3.0, 0.5 * float(r.get("exames") or r.get("exames_ref") or 0))


def _detail_from_stamped(
    hist: pd.DataFrame,
    vol: pd.DataFrame,
    horizon: int = 2,
) -> pd.DataFrame:
    """Confirmação prospectiva a partir de flags carimbados (Observado)."""
    h = hist.copy()
    h["municipio"] = h["municipio"].astype(str).str.strip().str.upper()
    h["ano_se"] = pd.to_numeric(h.get("ano_se"), errors="coerce")
    h["semana_epidemiologica"] = pd.to_numeric(h.get("semana_epidemiologica"), errors="coerce")
    h = h.dropna(subset=["ano_se", "semana_epidemiologica", "municipio"])

    weeks = (
        h[["ano_se", "semana_epidemiologica"]]
        .drop_duplicates()
        .sort_values(["ano_se", "semana_epidemiologica"])
        .reset_index(drop=True)
    )
    # Exclui a última SE carimbada se ainda não há horizonte futuro completo no vol
    if len(weeks) >= 2:
        eval_weeks = weeks.iloc[:-1]
    else:
        eval_weeks = weeks

    detail_rows = []
    for _, wk in eval_weeks.iterrows():
        y, w = int(wk["ano_se"]), int(wk["semana_epidemiologica"])
        snap = h[(h["ano_se"] == y) & (h["semana_epidemiologica"] == w)]
        if snap.empty:
            continue

        # mediana hist 8 SE para silêncio (a partir do volume, não do stamp)
        hist_keys = (
            vol[["epi_year", "epi_week"]].drop_duplicates()
            .sort_values(["epi_year", "epi_week"])
        )
        hist_keys = hist_keys[
            (hist_keys["epi_year"] < y)
            | ((hist_keys["epi_year"] == y) & (hist_keys["epi_week"] < w))
        ].tail(8)
        med_map = {}
        if not hist_keys.empty:
            hv = vol.merge(hist_keys, on=["epi_year", "epi_week"], how="inner")
            med_map = (
                hv.groupby("municipio")["exames"].median().to_dict()
            )
        cur_vol = vol[(vol["epi_year"] == y) & (vol["epi_week"] == w)].set_index("municipio")

        for _, r in snap.iterrows():
            tipos = []
            if bool(r.get("silencio_gal_alerta")):
                tipos.append("silencio_gal")
            if bool(r.get("divergencia_gal_notif")):
                tipos.append("divergencia")
            if bool(r.get("pressao_alta")) or str(r.get("faixa_pressao", "")).lower() in (
                "alta", "critica",
            ):
                tipos.append("pressao_alta")
            if bool(r.get("sla_crise")):
                tipos.append("sla_crise")
            if not tipos:
                continue

            mun = r["municipio"]
            outc = _future_outcomes(vol, mun, y, w, horizon=horizon)
            if not outc.get("tem_futuro"):
                continue

            exames_ref = float(cur_vol.loc[mun, "exames"]) if mun in cur_vol.index else 0.0
            row_ctx = pd.Series({
                "exames": exames_ref,
                "exames_ref": exames_ref,
                "exames_mediana_8se": float(med_map.get(mun, 0) or 0),
            })
            for tipo in tipos:
                conf = _confirm_tipo(tipo, row_ctx, outc)
                detail_rows.append({
                    "municipio": mun,
                    "codigo_ibge": r.get("codigo_ibge"),
                    "epi_year_ref": y,
                    "epi_week_ref": w,
                    "tipo_alerta": tipo,
                    "confirmado": int(bool(conf)),
                    "exames_ref": exames_ref,
                    "exames_futuro": outc["exames_futuro"],
                    "tipo_sinal": "Observado",
                    "fonte_flag": "alerta_emergencia_historico",
                })
    return pd.DataFrame(detail_rows)


def _detail_from_retro(
    vol: pd.DataFrame,
    rede: pd.DataFrame,
    n_weeks: int,
    horizon: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fallback: reconstrói flags retrospectivamente (Derivado)."""
    all_weeks = (
        vol[["epi_year", "epi_week"]].drop_duplicates()
        .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    )
    ref_weeks = _week_list(vol, n_weeks=n_weeks)
    detail_rows = []
    for _, wk in ref_weeks.iterrows():
        y, w = int(wk["epi_year"]), int(wk["epi_week"])
        flags = _flags_for_week(vol, y, w, rede, all_weeks)
        if flags.empty:
            continue
        alerted = flags[
            flags["silencio_gal"].fillna(False)
            | flags["divergencia"].fillna(False)
            | flags["pressao_alta"].fillna(False)
            | flags["sla_crise"].fillna(False)
        ]
        for _, r in alerted.iterrows():
            outc = _future_outcomes(vol, r["municipio"], y, w, horizon=horizon)
            if not outc.get("tem_futuro"):
                continue
            tipos = []
            if bool(r.get("silencio_gal")):
                tipos.append("silencio_gal")
            if bool(r.get("divergencia")):
                tipos.append("divergencia")
            if bool(r.get("pressao_alta")):
                tipos.append("pressao_alta")
            if bool(r.get("sla_crise")):
                tipos.append("sla_crise")
            for tipo in tipos:
                conf = _confirm_tipo(tipo, r, outc)
                detail_rows.append({
                    "municipio": r["municipio"],
                    "epi_year_ref": y,
                    "epi_week_ref": w,
                    "tipo_alerta": tipo,
                    "confirmado": int(bool(conf)),
                    "exames_ref": float(r.get("exames") or 0),
                    "exames_futuro": outc["exames_futuro"],
                    "tipo_sinal": "Derivado",
                    "fonte_flag": "weekly_retro_flags",
                })
    return pd.DataFrame(detail_rows), ref_weeks


def build_confirmacao_emergencia(
    outdir: Path | str = "saida_pipeline",
    n_weeks: int = 12,
    horizon: int = 2,
) -> pd.DataFrame:
    outdir = Path(outdir)
    weekly = _read(outdir, "integrated_weekly_surveillance.csv")
    if weekly.empty:
        empty = pd.DataFrame([{
            "status": "skipped",
            "motivo": "weekly ausente",
            "taxa_confirmacao_geral": np.nan,
            "tipo_sinal": "Derivado",
        }])
        empty.to_csv(outdir / "emergencia_confirmacao_resumo.csv", index=False, encoding="utf-8-sig")
        return empty

    rede = _read(outdir, "indicadores_emergencia.csv")
    if rede.empty:
        rede = _read(outdir, "indicadores_rede_laboratorial.csv")

    vol = _mun_week_vol(weekly)
    hist = _read(outdir, "alerta_emergencia_historico.csv")

    n_se_hist = 0
    if not hist.empty and "semana_epidemiologica" in hist.columns:
        n_se_hist = int(
            hist[["ano_se", "semana_epidemiologica"]].dropna().drop_duplicates().shape[0]
        )

    use_stamped = n_se_hist >= 2
    detail = pd.DataFrame()
    ref_weeks = pd.DataFrame()
    fonte = "weekly_retro_flags_x_desfecho"
    tipo_sinal = "Derivado"
    modo = "retrospectivo"

    if use_stamped:
        detail = _detail_from_stamped(hist, vol, horizon=horizon)
        if not detail.empty:
            fonte = "alerta_emergencia_historico_x_desfecho"
            tipo_sinal = "Observado"
            modo = "prospectivo_carimbado"
            ref_weeks = (
                detail[["epi_year_ref", "epi_week_ref"]]
                .drop_duplicates()
                .rename(columns={"epi_year_ref": "epi_year", "epi_week_ref": "epi_week"})
            )
        else:
            # Histórico existe mas ainda sem pares com futuro — fallback
            use_stamped = False

    if not use_stamped or detail.empty:
        detail, ref_weeks = _detail_from_retro(vol, rede, n_weeks=n_weeks, horizon=horizon)
        fonte = "weekly_retro_flags_x_desfecho"
        tipo_sinal = "Derivado"
        modo = "retrospectivo"
        if n_se_hist >= 1:
            fonte = "weekly_retro_flags_x_desfecho_fallback"
            # Histórico curto: ainda Derivado, mas anota que carimbo está em construção

    detail_path = outdir / "emergencia_confirmacao_detalhe.csv"
    if not detail.empty:
        detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
        try:
            detail.to_parquet(outdir / "emergencia_confirmacao_detalhe.parquet", index=False)
        except Exception:
            pass

    def _rate(tipo: str | None = None) -> tuple[float | None, int, int]:
        if detail.empty:
            return None, 0, 0
        sub = detail if tipo is None else detail[detail["tipo_alerta"] == tipo]
        if sub.empty:
            return None, 0, 0
        n = int(len(sub))
        c = int(sub["confirmado"].sum())
        return (c / n if n else None), c, n

    taxa_geral, conf_g, n_g = _rate()
    taxa_sil, conf_s, n_s = _rate("silencio_gal")
    taxa_div, conf_d, n_d = _rate("divergencia")
    taxa_pr, conf_p, n_p = _rate("pressao_alta")
    taxa_sla, conf_sl, n_sl = _rate("sla_crise")

    last_n_alertas = 0
    if not hist.empty and n_se_hist >= 1:
        last = (
            hist[["ano_se", "semana_epidemiologica"]].dropna()
            .drop_duplicates()
            .sort_values(["ano_se", "semana_epidemiologica"])
            .iloc[-1]
        )
        snap = hist[
            (hist["ano_se"] == last["ano_se"])
            & (hist["semana_epidemiologica"] == last["semana_epidemiologica"])
        ]
        last_n_alertas = int(
            (
                snap.get("silencio_gal_alerta", False).fillna(False).astype(bool)
                | snap.get("divergencia_gal_notif", False).fillna(False).astype(bool)
                | snap.get("pressao_alta", False).fillna(False).astype(bool)
                | snap.get("sla_crise", False).fillna(False).astype(bool)
            ).sum()
        )
    elif not ref_weeks.empty:
        all_weeks = (
            vol[["epi_year", "epi_week"]].drop_duplicates()
            .sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
        )
        ly, lw = int(ref_weeks.iloc[-1]["epi_year"]), int(ref_weeks.iloc[-1]["epi_week"])
        last_flags = _flags_for_week(vol, ly, lw, rede, all_weeks)
        if not last_flags.empty:
            last_n_alertas = int(
                (
                    last_flags["silencio_gal"].fillna(False)
                    | last_flags["divergencia"].fillna(False)
                    | last_flags["pressao_alta"].fillna(False)
                    | last_flags["sla_crise"].fillna(False)
                ).sum()
            )

    resumo = pd.DataFrame([{
        "janela_semanas": int(len(ref_weeks)) if not ref_weeks.empty else 0,
        "horizon_semanas": int(horizon),
        "n_alertas_avaliados": n_g,
        "n_confirmados": conf_g,
        "taxa_confirmacao_geral": taxa_geral,
        "taxa_confirmacao_silencio_gal": taxa_sil,
        "n_silencio_gal": n_s,
        "taxa_confirmacao_divergencia": taxa_div,
        "n_divergencia": n_d,
        "taxa_confirmacao_pressao_alta": taxa_pr,
        "n_pressao_alta": n_p,
        "taxa_confirmacao_sla_crise": taxa_sla,
        "n_sla_crise": n_sl,
        "n_municipios_alerta_ultima_se_avaliada": last_n_alertas,
        "n_se_historico_carimbado": n_se_hist,
        "modo_confirmacao": modo,
        "tipo_sinal": tipo_sinal,
        "fonte": fonte,
        "interpretacao": "",
        "nota": (
            "Confirmação Observado a partir de flags carimbados por SE "
            "(alerta_emergencia_historico) × desfecho nas 1–2 SE seguintes."
            if tipo_sinal == "Observado"
            else (
                "Flags reconstruídos retrospectivamente (Derivado); histórico carimbado "
                f"ainda com {n_se_hist} SE — use Observado quando ≥2 SE forem persistidas."
            )
        ),
    }])
    if taxa_geral is None:
        resumo.loc[0, "interpretacao"] = (
            f"Confirmação emergência ({tipo_sinal}): sem pares alerta×desfecho "
            f"(janela={len(ref_weeks)}, SE carimbadas={n_se_hist})."
        )
    else:
        def _pct(v):
            return f"{v:.0%}" if v is not None else "n/d"

        resumo.loc[0, "interpretacao"] = (
            f"Confirmação emergência [{tipo_sinal} · {modo}] "
            f"(janela {len(ref_weeks)} SE, horizonte {horizon}): "
            f"geral={_pct(taxa_geral)} ({conf_g}/{n_g}); "
            f"silêncio={_pct(taxa_sil)}; pressão={_pct(taxa_pr)}; "
            f"divergência={_pct(taxa_div)}; SLA={_pct(taxa_sla)}."
        )

    out = outdir / "emergencia_confirmacao_resumo.csv"
    resumo.to_csv(out, index=False, encoding="utf-8-sig")
    try:
        resumo.to_parquet(outdir / "emergencia_confirmacao_resumo.parquet", index=False)
    except Exception:
        pass
    print(
        f"[CONF] modo={modo} tipo={tipo_sinal} se_hist={n_se_hist} "
        f"alertas={n_g} confirmados={conf_g} taxa={taxa_geral} "
        f"| silêncio={taxa_sil} pressão={taxa_pr}",
        flush=True,
    )
    return resumo


def main() -> int:
    ap = argparse.ArgumentParser(description="Confirmação semanal de alertas de emergência")
    ap.add_argument("--outdir", default="saida_pipeline")
    ap.add_argument("--weeks", type=int, default=12)
    ap.add_argument("--horizon", type=int, default=2)
    args = ap.parse_args()
    build_confirmacao_emergencia(args.outdir, n_weeks=args.weeks, horizon=args.horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
