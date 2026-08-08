# -*- coding: utf-8 -*-
"""Loop semanal de confirmação de alertas de emergência.

Para cada SE nas últimas N semanas, reconstrói flags (sla_crise proxy, silêncio GAL,
divergência GAL×notif, pressão alta) e verifica se se confirmaram nas 1–2 SE seguintes
com desfechos de volume/rede/weekly.

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
    # exclui a última SE (sem horizonte futuro completo) — usa até penúltima
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
    """Flags de emergência na SE de referência."""
    cur = vol[(vol["epi_year"] == year) & (vol["epi_week"] == week)].copy()
    if cur.empty:
        return pd.DataFrame()

    # Histórico 8 SE anteriores
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

    # Pressão alta: volume no top quartil da semana OU rede estrutural alta
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
        }])
        empty.to_csv(outdir / "emergencia_confirmacao_resumo.csv", index=False, encoding="utf-8-sig")
        return empty

    rede = _read(outdir, "indicadores_emergencia.csv")
    if rede.empty:
        rede = _read(outdir, "indicadores_rede_laboratorial.csv")

    vol = _mun_week_vol(weekly)
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

            # Confirmação por tipo
            for tipo in tipos:
                if tipo == "silencio_gal":
                    # confirma se permanece baixo vs hist ou zero exames no horizonte
                    med = float(r.get("exames_mediana_8se") or 0)
                    conf = (
                        outc["exames_futuro"] <= 0.5 * max(med, 1) * outc["semanas_futuro"]
                        or outc["exames_max_futuro"] <= 0
                    )
                elif tipo == "divergencia":
                    conf = (outc["notif_futuro"] >= 2) and (
                        outc["exames_futuro"] < 0.5 * outc["notif_futuro"]
                    )
                elif tipo == "pressao_alta":
                    # confirma se volume futuro permanece elevado (top metade da SE futura)
                    conf = outc["exames_max_futuro"] >= max(
                        5.0, 0.75 * float(r.get("exames") or 0)
                    )
                else:  # sla_crise
                    # confirma se volume/backlog pressure persiste (proxy operacional)
                    conf = outc["exames_futuro"] >= max(3.0, 0.5 * float(r.get("exames") or 0))

                detail_rows.append({
                    "municipio": r["municipio"],
                    "epi_year_ref": y,
                    "epi_week_ref": w,
                    "tipo_alerta": tipo,
                    "confirmado": int(bool(conf)),
                    "exames_ref": float(r.get("exames") or 0),
                    "exames_futuro": outc["exames_futuro"],
                    "tipo_sinal": "Derivado",
                })

    detail = pd.DataFrame(detail_rows)
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

    # Última semana de flags (para cartão)
    last_n_alertas = 0
    if not ref_weeks.empty:
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
        "janela_semanas": int(len(ref_weeks)),
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
        "tipo_sinal": "Derivado",
        "fonte": "weekly_retro_flags_x_desfecho",
        "interpretacao": "",
        "nota": (
            "Flags reconstruídos retrospectivamente a partir do weekly + rede; "
            "não dependem de histórico persistido de indicadores_emergencia."
        ),
    }])
    if taxa_geral is None:
        resumo.loc[0, "interpretacao"] = (
            f"Confirmação emergência: sem pares alerta×desfecho (janela={len(ref_weeks)})."
        )
    else:
        def _pct(v):
            return f"{v:.0%}" if v is not None else "n/d"

        resumo.loc[0, "interpretacao"] = (
            f"Confirmação emergência (últimas {len(ref_weeks)} SE, horizonte {horizon}): "
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
        f"[CONF] alertas={n_g} confirmados={conf_g} taxa={taxa_geral} "
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
