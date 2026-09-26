# Decisão institucional — ADR-001 Âncora temporal GAL

**Status:** PENDENTE  
**Produto:** LACEN-MT V2.1  
**Decisão automática:** proibida

## Evidências obrigatórias

Preencher a partir de `saida_pipeline/quality/gal_temporal_anchor_summary.json` e `gal_temporal_anchor_weekly_comparison.csv`.

- Cobertura Data de Solicitação:
- Cobertura Data da Coleta:
- Mediana atraso solicitação−coleta:
- P90 atraso solicitação−coleta:
- Registros que mudam de SE:
- Proporção que muda de SE:
- Registros que mudam de ano epidemiológico:
- Semanas com diferenças agregadas:
- Maior diferença absoluta semanal:
- Impacto observado em baseline/anomalia/alerta:

## Finalidade dos produtos

Marcar a regra aprovada por produto.

| Produto | Âncora proposta | Justificativa |
|---|---|---|
| Vigilância epidemiológica | PENDENTE | |
| Fluxo laboratorial/operacional | PENDENTE | |
| Baseline histórico | PENDENTE | |
| Anomalia/alerta | PENDENTE | |
| Dashboard executivo | PENDENTE | |

## Decisão

Escolher explicitamente uma das alternativas:

- [ ] A — Solicitação como âncora única
- [ ] B — Coleta como âncora única
- [ ] C — Âncoras distintas por finalidade
- [ ] D — Manter regra atual temporariamente e coletar mais evidências

### Fundamentação

Preencher.

### Tratamento da série histórica

- [ ] Não reprocessar histórico
- [ ] Reprocessar histórico integralmente
- [ ] Reprocessar apenas período definido
- [ ] Manter duas séries paralelas

Período/justificativa:

## Aprovações

- Clinical/Epidemiological Specialist:
- Chief Architect:
- Data Governance:
- Responsável institucional pelo produto:
- Data da decisão:

## Critério para remover o BLOCK

O parecer Clinical/Epidemiological Specialist só pode sair de `BLOCK` quando esta decisão estiver preenchida, assinada/validada institucionalmente e o comportamento escolhido estiver coberto por teste de regressão.
