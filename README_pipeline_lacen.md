# Código para análise histórica do banco LACEN/GAL (2010+)

Este pacote contém um script Python pronto para processar a base completa do LACEN a partir de 2010, respeitando a estrutura real do banco GAL que você enviou.

## O que o código faz

- lê arquivos anuais em **CSV, XLSX/XLS ou Parquet**
- filtra automaticamente a partir do ano definido
- normaliza os **6 campos de resultado** em formato longo
- trata painéis **multi-alvo** como arboviroses, respiratórios, tuberculose molecular e outros blocos semi-estruturados
- limpa HTML, espaços e erros comuns de codificação
- calcula:
  - backlog por status
  - catálogo dos esquemas de preenchimento
  - positividade por alvo e por ano
  - positividade por semana epidemiológica e município
  - alertas precoces por desvio do padrão histórico
  - previsão simples das próximas semanas por alvo

## Arquivos incluídos

- `lacen_analysis_pipeline.py`
- `executar_pipeline_lacen.bat`
- `requirements_lacen_pipeline.txt`

## Dependências

Instale com:

```bash
pip install -r requirements_lacen_pipeline.txt
```

## Exemplo de execução

```bash
python lacen_analysis_pipeline.py ^
  --inputs "D:\LACEN\gal_2010.csv" "D:\LACEN\gal_2011.csv" "D:\LACEN\gal_2012.csv" ^
           "D:\LACEN\gal_2013.csv" "D:\LACEN\gal_2014.csv" "D:\LACEN\gal_2015.csv" ^
           "D:\LACEN\gal_2016.csv" "D:\LACEN\gal_2017.csv" "D:\LACEN\gal_2018.csv" ^
           "D:\LACEN\gal_2019.csv" "D:\LACEN\gal_2020.csv" "D:\LACEN\gal_2021.csv" ^
           "D:\LACEN\gal_2022.csv" "D:\LACEN\gal_2023.csv" "D:\LACEN\gal_2024.csv" ^
           "D:\LACEN\gal_2025.csv" "D:\LACEN\gal_2026.csv" ^
  --outdir "D:\LACEN\saida_pipeline" ^
  --start-year 2010 ^
  --chunk-size 50000 ^
  --write-normalized
```

## Saídas principais

- `schema_catalog.csv`
- `backlog_by_status_year.csv`
- `positivity_by_target_year.csv`
- `positivity_by_target_epiweek_municipio.csv`
- `weekly_tests_by_target_municipio.csv`
- `weekly_alerts.csv`
- `forecast_next_weeks_statewide.csv`
- `normalized_results.csv` ou partições parquet
- `run_metadata.json`
- `README.md` automático com resumo da execução

## Observações importantes

1. A **positividade** é calculada sobre resultados interpretáveis, e não sobre qualquer campo apenas “preenchido”.
2. Para painéis como **Dengue/Zika/Chikungunya**, uma única requisição pode gerar várias linhas analíticas separadas.
3. O módulo de previsão foi desenhado como **baseline operacional**, não como modelo final de pesquisa.
4. Se você quiser, na próxima etapa eu recomendaria acoplar esse pipeline a um **banco SQLite/DuckDB** para facilitar consultas históricas grandes.
