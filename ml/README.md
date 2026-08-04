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
| `ml_backtest_summary.csv` | AUC / confirmação temporal (treino 80% semanas → teste 20%) |

## Como rodar

```bat
.venv\Scripts\python.exe -m ml.run_ml_pipeline --outdir saida_pipeline
```

Também é chamado automaticamente por `lacen_integracao_final_only.py` e `atualizar_sistema_lacen.py`.

## Modelos atuais

### baseline_v1 (sempre disponível)
- **Forecast:** EWMA (span=4) sobre as últimas 8 semanas estaduais por alvo
- **Anomalia:** desvio vs média móvel 8 semanas
- **Risco / silêncio:** escore logístico interpretável (pesos fixos)

### sklearn_v1 (se `scikit-learn` instalado)
- Gradient Boosting com validação temporal (80/20 por semana epidemiológica)
- Artefatos em `ml/models_store/` (`risco_gb.joblib`, `silencio_gb.joblib`, `meta.json`)
- Inferência usa sklearn se o artefato existir; senão cai na baseline

```bat
.venv\Scripts\python.exe -m pip install scikit-learn joblib
.venv\Scripts\python.exe -m ml.run_ml_pipeline --outdir saida_pipeline
```

## Streamlit Cloud — tornar público

1. https://share.streamlit.io/ → login GitHub
2. App do repositório `menandesneto51/LACEN-MT`
3. Manage app → **Reboot** (para puxar o commit novo)
4. Settings → **Sharing** → *This app is public and searchable*
5. Testar em aba anônima e enviar o link `https://….streamlit.app`

Detalhes: `STREAMLIT_PUBLICO.md`
