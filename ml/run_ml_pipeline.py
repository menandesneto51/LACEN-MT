# -*- coding: utf-8 -*-
"""Executa feature store + inferência e grava CSVs em saida_pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.features import build_panel_features, latest_week_snapshot  # noqa: E402
from ml.models import (  # noqa: E402
    detect_anomalias,
    forecast_demanda,
    score_risco_predito,
    score_silencio_predito,
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def run_ml_pipeline(outdir: Path | str = "saida_pipeline") -> dict[str, Path]:
    outdir = Path(outdir)
    weekly_path = outdir / "integrated_weekly_surveillance.csv"
    if not weekly_path.exists():
        raise FileNotFoundError(f"Não encontrado: {weekly_path}")

    _log(f"[ML] Lendo {weekly_path.name}...")
    weekly = pd.read_csv(weekly_path, low_memory=False)
    _log(f"[ML] Linhas semanais: {len(weekly):,}")

    _log("[ML] Construindo features (lags / médias móveis / clima / CNES / vizinhos)...")
    features = build_panel_features(weekly, outdir=outdir)
    snap = latest_week_snapshot(features)

    _log("[ML] Treinando modelos sklearn (se disponível)...")
    try:
        from ml.train import train_and_save
        meta = train_and_save(features)
        _log(f"[ML] Treino: sklearn={meta.get('sklearn')} versao={meta.get('modelo_versao')}")
        if meta.get("models"):
            for k, v in meta["models"].items():
                _log(f"[ML]   {k}: {v}")
    except Exception as exc:
        _log(f"[ML][AVISO] Treino sklearn pulado: {exc}")

    # Snapshot compacto da última observação por município-alvo
    feat_out = outdir / "ml_features_latest.csv"
    snap.to_csv(feat_out, index=False, encoding="utf-8-sig")
    _log(f"[ML] {feat_out.name}: {len(snap):,} linhas")

    _log("[ML] Forecast de demanda...")
    fc = forecast_demanda(weekly, horizon=4)
    fc_out = outdir / "ml_forecast_demanda.csv"
    fc.to_csv(fc_out, index=False, encoding="utf-8-sig")
    _log(f"[ML] {fc_out.name}: {len(fc):,} linhas")

    _log("[ML] Detecção de anomalias...")
    an = detect_anomalias(features)
    an_out = outdir / "ml_anomalias.csv"
    an.to_csv(an_out, index=False, encoding="utf-8-sig")
    _log(f"[ML] {an_out.name}: {len(an):,} linhas")

    _log("[ML] Risco predito...")
    risco = score_risco_predito(features)
    risco_out = outdir / "ml_risco_predito.csv"
    risco.to_csv(risco_out, index=False, encoding="utf-8-sig")
    _log(f"[ML] {risco_out.name}: {len(risco):,} linhas")

    _log("[ML] Silêncio predito...")
    silencio = score_silencio_predito(features)
    silencio_out = outdir / "ml_silencio_predito.csv"
    silencio.to_csv(silencio_out, index=False, encoding="utf-8-sig")
    _log(f"[ML] {silencio_out.name}: {len(silencio):,} linhas")

    pressao_out = outdir / "ml_pressao_rede_predito.csv"
    try:
        _log("[ML] Pressão de rede predita...")
        from ml.pressao_rede import run_pressao_pipeline
        pr_paths = run_pressao_pipeline(weekly, outdir=outdir)
        pressao_out = pr_paths.get("pressao", pressao_out)
        _log(f"[ML] {pressao_out.name} gerado")
        bt_pr = outdir / "ml_pressao_rede_backtest.csv"
        if bt_pr.exists():
            try:
                _btp = pd.read_csv(bt_pr)
                if not _btp.empty and "auc" in _btp.columns:
                    r0 = _btp.iloc[0]
                    _log(
                        f"[ML]   pressao backtest: auc={r0.get('auc')} "
                        f"confirmacao={r0.get('confirmacao')} P@20={r0.get('precision_at_20')}"
                    )
            except Exception:
                pass
    except Exception as exc:
        _log(f"[ML][AVISO] Pressão predita pulada: {exc}")

    _log("[ML] Backtest temporal...")
    bt_out = outdir / "ml_backtest_summary.csv"
    try:
        from ml.backtest import run_backtest
        bt = run_backtest(features)
        bt.to_csv(bt_out, index=False, encoding="utf-8-sig")
        _log(f"[ML] {bt_out.name}: {len(bt):,} linhas")
        if not bt.empty and "auc" in bt.columns:
            for _, r in bt[bt["escopo"].astype(str).eq("global")].iterrows():
                _log(
                    f"[ML]   backtest {r.get('modelo')}: auc={r.get('auc')} "
                    f"confirmacao={r.get('confirmacao')} n={r.get('n')}"
                )
        # Reanexa backtest de pressão se já gerado
        bt_pr = outdir / "ml_pressao_rede_backtest.csv"
        if bt_pr.exists():
            try:
                _btp = pd.read_csv(bt_pr)
                if not _btp.empty:
                    bt2 = pd.concat([bt, _btp], ignore_index=True)
                    bt2.to_csv(bt_out, index=False, encoding="utf-8-sig")
            except Exception:
                pass
    except Exception as exc:
        _log(f"[ML][AVISO] Backtest pulado: {exc}")
        bt_out = outdir / "ml_backtest_summary.csv"

    # Também atualiza forecast estadual legado com método EWMA (compatível)
    if not fc.empty:
        legacy = fc.rename(columns={
            "forecast_tests": "forecast_tests",
            "forecast_positividade": "forecast_positividade",
            "forecast_notificacoes": "forecast_notificacoes",
        })
        legacy_cols = [
            "target", "forecast_step", "forecast_epi_year", "forecast_epi_week",
            "forecast_tests", "forecast_positividade", "forecast_notificacoes",
            "metodo", "modelo_versao",
        ]
        legacy[[c for c in legacy_cols if c in legacy.columns]].to_csv(
            outdir / "forecast_integrated_statewide.csv",
            index=False,
            encoding="utf-8-sig",
        )

    _log("[ML] Pipeline preditivo concluído.")
    try:
        from ml.mirror_dw import append_alerta_historico, atualizar_desfechos, build_executive_summaries, mirror_to_dw
        append_alerta_historico(outdir, risco, silencio)
        atualizar_desfechos(outdir)
        build_executive_summaries(outdir)
        st = mirror_to_dw(outdir)
        _log(f"[ML] Histórico/espelho: dw_ok={st.get('dw_ok')} mirrored={len(st.get('mirrored') or [])}")
    except Exception as exc:
        _log(f"[ML][AVISO] Histórico/DW: {exc}")
    try:
        from gerar_indicadores_rede_lacen import build_indicadores_rede
        build_indicadores_rede(outdir=outdir)
    except Exception as exc:
        _log(f"[ML][AVISO] Indicadores rede: {exc}")
    try:
        from gerar_indicadores_emergencia import build_indicadores_emergencia
        build_indicadores_emergencia(outdir=outdir)
    except Exception as exc:
        _log(f"[ML][AVISO] Indicadores emergência: {exc}")
    try:
        from gerar_confirmacao_emergencia import build_confirmacao_emergencia
        _log("[ML] Confirmação semanal de emergência...")
        build_confirmacao_emergencia(outdir=outdir)
        # Reconsolida cartão executivo com KPIs de confirmação + Predito
        from gerar_indicadores_emergencia import build_indicadores_emergencia
        build_indicadores_emergencia(outdir=outdir)
    except Exception as exc:
        _log(f"[ML][AVISO] Confirmação emergência: {exc}")
    try:
        from exportar_parquet_saida import export_outdir
        _log("[ML] Exportando parquet...")
        export_outdir(outdir)
    except Exception as exc:
        _log(f"[ML][AVISO] Parquet não gerado: {exc}")
    return {
        "features": feat_out,
        "forecast": fc_out,
        "anomalias": an_out,
        "risco": risco_out,
        "silencio": silencio_out,
        "pressao": pressao_out,
        "backtest": bt_out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline ML baseline LACEN MT")
    ap.add_argument("--outdir", default="saida_pipeline")
    args = ap.parse_args()
    run_ml_pipeline(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
