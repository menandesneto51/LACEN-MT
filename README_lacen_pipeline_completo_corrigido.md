# Pipeline completo corrigido do LACEN/GAL

Este script substitui a versão anterior e mantém as análises gerais do banco, além de gerar automaticamente a versão final depurada de arboviroses.

## O que ele gera
- `schema_catalog.csv`
- `backlog_by_status_year.csv`
- `positivity_by_target_year.csv`
- `positivity_by_target_epiweek_municipio.csv`
- `weekly_tests_by_target_municipio.csv`
- `weekly_alerts.csv`
- `forecast_next_weeks_statewide.csv`
- `arboviroses_positivos_todos.csv`
- `arboviroses_positivos_agudos.csv`
- `arboviroses_positivos_final_agudos_casos.csv`
- `arboviroses_positivos_final_agudos_detalhado.csv`
- `arboviroses_positivos_final_todos_casos.csv`
- `arboviroses_positivos_final_todos_detalhado.csv`
- `arboviroses_resumo_anual.csv`
- `arboviroses_resumo_epiweek_municipio.csv`
- `arboviroses_positivos.xlsx`
- `arboviroses_positivos_final.xlsx`

## Substituição
Você pode renomear `lacen_analysis_pipeline_completo_corrigido.py` para `lacen_analysis_pipeline.py` e substituir o arquivo antigo.

## Comando recomendado
```bat
cd /d "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\lacen TATI"
python lacen_analysis_pipeline_completo_corrigido.py --inputs "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\LACEN 2010 a 2026.csv" --outdir "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\lacen TATI\saida_pipeline" --start-year 2010 --chunk-size 10000
```

## Observação
Evite `--write-normalized` em CSV no banco inteiro se o disco estiver apertado. Se precisar da base normalizada completa, prefira `--write-normalized --normalized-format parquet`.
