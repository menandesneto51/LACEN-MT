# Módulo de machine learning / sinais preditivos — LACEN MT

## Ideia

O ML **não treina dentro do SQL Server**. Ele roda em Python sobre `saida_pipeline`,
grava escores em CSV (e pode espelhar no DW quando a VPN estiver disponível).

```
integrated_weekly_surveillance.csv
        ↓
ml/features.py          → features_v2 (clima, CNES, vizinhos, confiança)
ml/train.py             → sklearn_v2 (calibrado + por família)
ml/models.py            → forecast / anomalias / risco / silêncio + drivers
ml/backtest.py          → AUC + precisão@K + limiar calibrado
ml/mirror_dw.py         → alerta_historico + executive_* + status DW
        ↓
dashboard (Predição e alertas + assistente)
```

## Saídas

| Arquivo | Conteúdo |
|---------|----------|
| `ml_features_latest.csv` | Features da última semana |
| `ml_forecast_demanda.csv` | Previsão EWMA (4 semanas) |
| `ml_anomalias.csv` | Picos/quedas atípicas |
| `ml_risco_predito.csv` | Prob. alerta + limiar + drivers |
| `ml_silencio_predito.csv` | Prob. silêncio + limiar |
| `ml_backtest_summary.csv` | AUC / confirmação / P@20 / P@50 |
| `alerta_historico.csv` | Alertas emitidos × desfecho |
| `indicadores_rede_laboratorial.csv` | TAT / backlog / rejeição |
| `executive_state_summary.csv` | Resumo executivo leve |

## Como rodar

```bat
.venv\Scripts\python.exe -m ml.run_ml_pipeline --outdir saida_pipeline
```

Também: `rodar_ml_lacen.bat`, `lacen_integracao_final_only.py`, `atualizar_sistema_lacen.py`.

### SIM (mortalidade)

```bat
.venv\Scripts\python.exe reparar_sim_weekly.py --sim "SIM 2010 a 2025.csv" --outdir saida_pipeline
```

### Rede laboratorial

```bat
.venv\Scripts\python.exe gerar_indicadores_rede_lacen.py --outdir saida_pipeline
```

## Modelos

### baseline_v1
EWMA + logit interpretável (fallback).

### sklearn_v2
- Gradient Boosting + calibração isotônica quando possível
- Limiar operacional por F1 no holdout temporal
- Modelos por família (arbovirose, TB, hepatite, respiratório)
- Drivers (importância × valor) no CSV de risco

## Assistente

`lacen_assistente.py` responde só com CSVs agregados (citações obrigatórias).
Rewrite opcional via `LACEN_LLM_API_KEY` / `OPENAI_API_KEY` — sem inventar número.
