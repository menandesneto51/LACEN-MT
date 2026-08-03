# Sistema Inteligente de Monitoramento Laboratorial — LACEN MT

Fluxo oficial na raiz (cópias antigas em `antigos/`).

## Pipeline
1. `lacen_analysis_pipeline_completo_corrigido.py` — LACEN/GAL
2. `lacen_builder_integrado_total.py` — SINAN + SIM + CNES + clima + população
3. `lacen_integracao_final_only.py` — risco composto + inteligência territorial
4. `lacen_dashboard_integrado_total.py` — Streamlit v5.1 (12 abas)

Orquestração: `rodar_lacen_sistema_completo_bases.bat`

## Saídas territoriais (novas)
Em `saida_pipeline/`, após a integração final (ou `gerar_inteligencia_territorial_stdlib.py`):
- `municipios_em_risco.csv`
- `municipios_silenciosos.csv`
- `taxa_utilizacao_lacen.csv`

## Dashboard
```bat
python -m streamlit run lacen_dashboard_integrado_total.py
```

Abas novas: Visão executiva, Municípios em risco, Municípios silenciosos, Utilização do LACEN, Alertas territoriais.

## Segredos / integrações
Use `.env.example` como modelo. Não grave senhas no código.
Padrão alinhado a TITAN_V40_DEV / Sentinela / SISREG (`DW_*`, Telegram, e-mail).
