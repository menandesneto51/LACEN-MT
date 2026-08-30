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

## ETL DW + SE real
A base semanal (`integrated_weekly_surveillance`) e os alertas devem refletir a **semana epidemiológica do calendário** (última SE ISO completa vs `hoje`), não um recorte antigo preso em SE20/SE21.

```bat
rodar_etl_dw.bat
.\.venv\Scripts\python.exe -m etl.run_etl_dw
.\.venv\Scripts\python.exe -m etl.run_etl_dw --allow-local-fallback
```

Fluxo: extrai `dbo.VW_GAL` (e inventaria VW_SINAN/LACEN/SIM/IndicaSUS/SISREG/SIH/SIA se existirem) → staging em `saida_pipeline/staging_dw/` → atualiza weekly → rede/emergência/ML → `ml.mirror_dw` → CIEVS dry-run → `saida_pipeline/validacao_etl_dw_ultimo.txt` (`hoje`, `se_esperada`, `se_usada`, `atraso_se`).

Cruzamento de bases (prioridade SINAN → GAL → SIH → SIVEP → SIM → CNES → IndicaSUS → SISREG → SIA): ver `conhecimento_ve/cruzamento_bases.md`. Briefing Top 10 inclui `n_se`, `n_se_ant`, `delta`, `delta_pct`, `tendencia`; GAL×SINAN cobre **qualquer** agravo (mun×família).

Sem VPN SES (`DW_HOST:1433`) o ETL **falha com instrução**; `--allow-local-fallback` usa o CSV GAL local e **avisa** se a SE estiver atrasada. Espelho DW: se `CREATE TABLE` for negado, o DBA deve rodar `saida_pipeline/sql/create_lacen_ml_tables.sql` e reexecutar `python -m ml.mirror_dw`.

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

### Relatório CIEVS 2×/semana
Payload institucional (blocos A–D) via `lacen_relatorio_cievs.py` — Telegram curto + e-mail completo:

```bat
enviar_relatorio_cievs.bat
.\.venv\Scripts\python.exe scripts\enviar_relatorio_cievs.py --dry-run
.\.venv\Scripts\python.exe scripts\enviar_relatorio_cievs.py --telegram --email --to menandesneto@gmail.com
```

Agenda: **terça e sexta** (Agendador de Tarefas Windows apontando para `enviar_relatorio_cievs.bat` com args de envio, ou cron equivalente). Prévia em `saida_pipeline/relatorio_cievs_ultimo.txt`.

Requer no `.env`: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` e/ou SMTP (`EMAIL_USER`/`EMAIL_SENHA` ou `SMTP_*`). Ver `.env.example`.

### Auth do dashboard (SES/CIEVS)
Sem secrets → painel **público**. Com `[auth]` em Streamlit Secrets (ou `LACEN_DASHBOARD_PASSWORD` / `LACEN_REQUIRE_AUTH=1`) → login institucional.
Modelo: `.streamlit/secrets.toml.example`. Cloud: `STREAMLIT_CLOUD.md`. Servidor SES: `scripts/deploy_ses.md`.
