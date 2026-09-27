# Decisão institucional — prioridade de fontes populacionais

**Status:** PENDENTE  
**Configuração alvo:** `config/population_governance_v2_1.json`  
**Decisão automática:** proibida  
**Data:** PENDENTE

## Evidências obrigatórias

- `population_source_comparison_summary.json`
- `population_source_coverage_detail.csv`
- `population_source_pairwise_comparison.csv`
- `population_governance_v2_1.json`

### Resumo

- Ano de análise: 2021 (staging)
- Fontes disponíveis: `DW:POPULACAO_TOTAL`
- Cobertura territorial por fonte: 141 municípios
- Territórios com múltiplas fontes: 0
- Territórios com divergência: 0
- Maior diferença absoluta: n/a
- Maior diferença relativa: n/a
- Conflitos internos na mesma fonte: nenhum observado no staging

## Critérios de decisão

Única fonte com cobertura anual no staging avaliado; sem concorrência multi-fonte.

## Prioridade candidata observada (não aprovada)

1. `DW:POPULACAO_TOTAL` — única fonte observada no staging avaliado; decisão institucional ainda pendente
2. _(vazio — demais candidatas sem evidência de cobertura no ano analisado)_
3.
4.

## Fallback temporal

- [ ] Proibido
- [ ] Permitido sob regra explícita

Regra: exigir ano de análise exato (`require_exact_analysis_year=true`).

## Fontes não listadas

- [ ] Bloquear uso automático
- [ ] Permitir sob condição explícita

Condição: `allow_unlisted_sources=false`.

## Aprovações

- Security/Data Governance: PENDENTE
- Data Architect: evidência técnica disponível; não constitui aprovação
- Epidemiologia: PENDENTE
- Responsável institucional pelo produto: PENDENTE
- Data da decisão: PENDENTE

## Alteração da configuração

Até decisão institucional, `config/population_governance_v2_1.json` permanece:
- `status = "PENDING_APPROVAL"`
- `source_priority = []`
- `allow_previous_year = false`

## Critério para remover o WARN

Política populacional aprovada explicitamente por responsável autorizado, após revisão da comparação real de fontes
e confirmação de ausência de conflitos internos não resolvidos no staging utilizado.
