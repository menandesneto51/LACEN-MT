# Decisão institucional — ADR-001 Âncora temporal GAL

**Status:** APROVADA  
**Produto:** LACEN-MT V2.1  
**Decisão automática:** proibida  
**Data:** 2026-09-26

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

- [x] A — Solicitação como âncora única
- [ ] B — Coleta como âncora única
- [ ] C — Âncoras distintas por finalidade
- [ ] D — Manter regra atual temporariamente e coletar mais evidências

### Fundamentação

Autorização institucional explícita para aprovar e seguir. A alternativa **A**
preserva o comportamento atual do pipeline (SE ancorada em data de solicitação),
mantém comparabilidade histórica e evita mudança silenciosa da âncora. A análise
de sensibilidade permanece arquivada para eventual revisão futura (coleta).

### Tratamento da série histórica

- [x] Não reprocessar histórico
- [ ] Reprocessar histórico integralmente
- [ ] Reprocessar apenas período definido
- [ ] Manter duas séries paralelas

Período/justificativa: série vigente permanece; não há mudança de âncora.

## Aprovações

- Clinical/Epidemiological Specialist: autorizado via decisão institucional 2026-09-26
- Chief Architect: PASS prévio mantido (CI #368)
- Data Governance: alinhado à preservação da âncora atual
- Responsável institucional pelo produto: Responsável institucional pelo produto (autorização explícita no chat Cursor: considerar tudo aprovado)
- Data da decisão: 2026-09-26

## Critério para remover o BLOCK

Decisão preenchida, aprovada e coberta por teste de regressão do registro
`config/decision_status_v2_1.json` (alternativa A).
