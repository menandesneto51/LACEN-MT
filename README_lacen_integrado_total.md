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

### Teste de alerta (Telegram + e-mail)
Os alertas (fila operacional, emergência, banda de risco, silêncio, pressão predita) são **gerados em CSV** e exibidos no dashboard — **não há disparo automático** em produção ainda.

Envio manual de teste (uma mensagem, marcada como TESTE), a partir dos top alertas em `saida_pipeline/`:

```bat
python scripts/enviar_alerta_teste.py
python scripts/enviar_alerta_teste.py --dry-run
```

Requer no `.env`: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` e/ou SMTP (`EMAIL_USER`/`EMAIL_SENHA` ou `SMTP_*`). Ver `.env.example`.

### Auth do dashboard (SES/CIEVS)
Sem secrets → painel **público**. Com `[auth]` em Streamlit Secrets (ou `LACEN_DASHBOARD_PASSWORD` / `LACEN_REQUIRE_AUTH=1`) → login institucional.
Modelo: `.streamlit/secrets.toml.example`. Cloud: `STREAMLIT_CLOUD.md`. Servidor SES: `scripts/deploy_ses.md`.
