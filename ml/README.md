# Módulo de machine learning / sinais preditivos — LACEN MT

## Ideia

O ML **não treina dentro do SQL Server**. Ele roda em Python sobre `saida_pipeline`,
grava escores em CSV (e depois pode espelhar no DW).

```
integrated_weekly_surveillance.csv
        ↓
ml/features.py          → ml_features_latest.csv
ml/models.py            → forecast / anomalias / risco / silêncio
        ↓
dashboard (aba Sinais preditivos)
```

## Saídas

| Arquivo | Conteúdo |
|---------|----------|
| `ml_features_latest.csv` | Features da última semana epidemiológica |
| `ml_forecast_demanda.csv` | Previsão de exames/positividade (4 semanas) |
| `ml_anomalias.csv` | Picos/quedas atípicas |
| `ml_risco_predito.csv` | Probabilidade de alerta na próxima janela |
| `ml_silencio_predito.csv` | Probabilidade de silêncio laboratorial |

## Como rodar

```bat
.venv\Scripts\python.exe -m ml.run_ml_pipeline --outdir saida_pipeline
```

Também é chamado automaticamente por `lacen_integracao_final_only.py` e `atualizar_sistema_lacen.py`.

## Modelos atuais (baseline_v1)

- **Forecast:** EWMA (span=4) sobre as últimas 8 semanas estaduais por alvo
- **Anomalia:** desvio vs média móvel 8 semanas
- **Risco / silêncio:** escore logístico interpretável (pesos fixos)

Próximo passo opcional: treinar sklearn/XGBoost com validação temporal e versionar em `ml/models_store/`.
