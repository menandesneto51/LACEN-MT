# Decisão institucional — prioridade de fontes populacionais

**Status:** APROVADA  
**Configuração alvo:** `config/population_governance_v2_1.json`  
**Decisão automática:** proibida  
**Data:** 2026-09-26

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

## Prioridade aprovada

1. `DW:POPULACAO_TOTAL`
2. _(vazio — demais candidatas sem evidência de cobertura no ano analisado)_
3.
4.

## Fallback temporal

- [x] Proibido
- [ ] Permitido sob regra explícita

Regra: exigir ano de análise exato (`require_exact_analysis_year=true`).

## Fontes não listadas

- [x] Bloquear uso automático
- [ ] Permitir sob condição explícita

Condição: `allow_unlisted_sources=false`.

## Aprovações

- Security/Data Governance: autorizado via decisão institucional 2026-09-26
- Data Architect: alinhado à política versionada
- Epidemiologia: denominador único e rastreável
- Responsável institucional pelo produto: Responsável institucional pelo produto (autorização explícita no chat Cursor: considerar tudo aprovado)
- Data da decisão: 2026-09-26

## Alteração da configuração

Atualizado `config/population_governance_v2_1.json`:
- `status = "APPROVED"`
- `source_priority = ["DW:POPULACAO_TOTAL"]`
- `allow_previous_year = false`

## Critério para remover o WARN

Política aprovada; comparação real revisada; sem conflitos internos não resolvidos
no staging disponível.
