# Decisão institucional — ADR-001 Âncora temporal GAL

**Status:** PENDENTE  
**Produto:** LACEN-MT V2.1  
**Decisão automática:** proibida  
**Data:** PENDENTE

## Evidências obrigatórias

Preenchido a partir de `saida_pipeline/quality/gal_temporal_anchor_summary.json`
e `gal_temporal_anchor_weekly_comparison.csv` (replay staging).

- Cobertura Data de Solicitação: 100%
- Cobertura Data da Coleta: 100%
- Mediana atraso solicitação−coleta: 0,0 dias
- P90 atraso solicitação−coleta: 0,0 dias
- Registros que mudam de SE: 168
- Proporção que muda de SE: 13,32%
- Registros que mudam de ano epidemiológico: 0
- Semanas com diferenças agregadas: 22 / 22
- Maior diferença absoluta semanal: 16
- Impacto observado em baseline/anomalia/alerta: mudança de SE em ~13% dos registros
  se a âncora fosse alterada; ano epidemiológico estável.

## Finalidade dos produtos

| Produto | Âncora proposta | Justificativa |
|---|---|---|
| Vigilância epidemiológica | Solicitação (A) | Preserva série e comparabilidade atuais. |
| Fluxo laboratorial/operacional | Solicitação (A) | Mesma âncora única institucional. |
| Baseline histórico | Solicitação (A) | Evita reprocessamento e ruptura de baseline. |
| Anomalia/alerta | Solicitação (A) | Mantém comportamento já em produção. |
| Dashboard executivo | Solicitação (A) | Consistência com a série vigente. |

## Decisão

Escolher explicitamente uma das alternativas:

- [ ] A — Solicitação como âncora única
- [ ] B — Coleta como âncora única
- [ ] C — Âncoras distintas por finalidade
- [ ] D — Manter regra atual temporariamente e coletar mais evidências

### Fundamentação

Evidência disponível indica impacto relevante da troca de âncora sobre a distribuição semanal.
A escolha entre solicitação, coleta ou uso por finalidade permanece **pendente de decisão institucional explícita**.

### Tratamento da série histórica

- [ ] Não reprocessar histórico
- [ ] Reprocessar histórico integralmente
- [ ] Reprocessar apenas período definido
- [ ] Manter duas séries paralelas

Período/justificativa: PENDENTE.

## Aprovações

- Clinical/Epidemiological Specialist: PENDENTE
- Chief Architect: PASS arquitetural prévio; não decide a âncora
- Data Governance: PENDENTE quanto ao registro institucional
- Responsável institucional pelo produto: PENDENTE
- Data da decisão: PENDENTE

## Critério para remover o BLOCK

Decisão específica registrada por responsável autorizado, baseada nas evidências disponíveis,
com atualização de `config/decision_status_v2_1.json` e teste de regressão do comportamento escolhido.
