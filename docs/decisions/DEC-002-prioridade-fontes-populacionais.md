# Decisão institucional — prioridade de fontes populacionais

**Status:** PENDENTE  
**Configuração alvo:** `config/population_governance_v2_1.json`  
**Decisão automática:** proibida

## Evidências obrigatórias

Preencher com os artefatos:
- `population_source_comparison_summary.json`
- `population_source_coverage_detail.csv`
- `population_source_pairwise_comparison.csv`
- `population_governance_v2_1.json`

### Resumo

- Ano de análise:
- Fontes disponíveis:
- Cobertura territorial por fonte:
- Territórios com múltiplas fontes:
- Territórios com divergência:
- Maior diferença absoluta:
- Maior diferença relativa:
- Conflitos internos na mesma fonte:

## Critérios de decisão

Avaliar cada fonte quanto a:
1. cobertura territorial;
2. ano de referência;
3. consistência interna;
4. rastreabilidade/versionamento;
5. aderência ao uso epidemiológico;
6. disponibilidade futura;
7. governança institucional.

## Prioridade aprovada

Preencher somente após validação institucional:

1.
2.
3.
4.

## Fallback temporal

- [ ] Proibido
- [ ] Permitido sob regra explícita

Regra:

## Fontes não listadas

- [ ] Bloquear uso automático
- [ ] Permitir sob condição explícita

Condição:

## Aprovações

- Security/Data Governance:
- Data Architect:
- Epidemiologia:
- Responsável institucional pelo produto:
- Data da decisão:

## Alteração da configuração

Somente após aprovação, atualizar `config/population_governance_v2_1.json`:
- `status = "APPROVED"`
- `approved_by`
- `approved_at`
- `source_priority`
- `allow_previous_year`
- demais regras aprovadas.

## Critério para remover o WARN

O parecer Security/Data Governance só pode sair de `WARN` após:
- política aprovada;
- comparação real das fontes revisada;
- ausência de conflitos internos não resolvidos;
- Artifact Hygiene e Product Lineage revisados nos artefatos reais.
