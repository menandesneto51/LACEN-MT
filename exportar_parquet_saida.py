# -*- coding: utf-8 -*-
"""Gera .parquet ao lado dos CSVs essenciais (mais rápido no Streamlit Cloud)."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ESSENTIAL = [
    "integrated_weekly_surveillance.csv",
    "integrated_alerts.csv",
    "integrated_annual_summary.csv",
    "integrated_target_municipio_summary.csv",
    "forecast_integrated_statewide.csv",
    "municipios_em_risco.csv",
    "municipios_silenciosos.csv",
    "taxa_utilizacao_lacen.csv",
    "ml_forecast_demanda.csv",
    "ml_anomalias.csv",
    "ml_risco_predito.csv",
    "ml_silencio_predito.csv",
    "ml_features_latest.csv",
    "municipal_master.csv",
    "populacao_municipio.csv",
    "cnes_capacity_municipio.csv",
    "qualidade_dado_municipal.csv",
    "municipio_vizinhos.csv",
    "fila_operacional.csv",
    "ml_backtest_summary.csv",
    "indicadores_rede_laboratorial.csv",
    "indicadores_rede_resumo.csv",
    "indicadores_rede_por_familia.csv",
    "indicadores_emergencia.csv",
    "indicadores_emergencia_resumo.csv",
    "indicadores_emergencia_familia.csv",
    "indicadores_emergencia_acoes.csv",
    "ml_pressao_rede_predito.csv",
    "ml_pressao_rede_familia_predito.csv",
    "ml_pressao_rede_backtest.csv",
    "emergencia_confirmacao_resumo.csv",
    "emergencia_confirmacao_detalhe.csv",
    "alerta_historico.csv",
    "executive_state_summary.csv",
    "executive_rede_summary.csv",
    "sim_qualidade.csv",
]


def csv_to_parquet(csv_path: Path) -> Path | None:
    pq = csv_path.with_suffix(".parquet")
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        df.to_parquet(pq, index=False)
        return pq
    except Exception as exc:
        print(f"[AVISO] {csv_path.name}: {exc}", flush=True)
        return None


def export_outdir(outdir: Path | str = "saida_pipeline") -> list[Path]:
    outdir = Path(outdir)
    done: list[Path] = []
    for name in ESSENTIAL:
        src = outdir / name
        if not src.exists():
            continue
        pq = csv_to_parquet(src)
        if pq is not None:
            mb = pq.stat().st_size / (1024 * 1024)
            print(f"[OK] {pq.name} ({mb:.2f} MB)", flush=True)
            done.append(pq)
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="saida_pipeline")
    args = ap.parse_args()
    done = export_outdir(args.outdir)
    print(f"[FINAL] {len(done)} arquivos parquet gerados.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
