# Aprovação da Política de Denominadores Populacionais — LACEN-MT V2.1

**Status:** PENDENTE  
**Arquivo de política:** `config/population_governance_v2_1.json`

Este documento formaliza a decisão institucional sobre qual fonte populacional pode ser utilizada pela camada V2 para cálculo de taxas. A existência técnica de uma fonte no DW não equivale à sua aprovação como denominador institucional.

## 1. Escopo da decisão

- Unidade territorial: município
- Unidade temporal: município × ano de referência
- Fallback para ano anterior: **não permitido por padrão**
- Fonte não listada em `source_priority`: **não permitida por padrão**
- Conflito interno na mesma fonte/território/ano: **bloqueia o denominador**

## 2. Fontes candidatas atualmente reconhecidas

- `DW:VW_POPULACAO`
- `DW:POPULACAO`
- `DW:POPULACAO_TOTAL`
- `DW:POPULACAO_TCU`

A relação acima é catálogo técnico, não ordenação de preferência.

## 3. Evidência mínima para aprovação

Para cada fonte candidata, registrar:

| Campo | Fonte 1 | Fonte 2 | Fonte 3 | Fonte 4 |
|---|---|---|---|---|
| Nome lógico |  |  |  |  |
| Órgão/origem primária |  |  |  |  |
| Ano mais recente disponível |  |  |  |  |
| Cobertura municipal |  |  |  |  |
| Código IBGE disponível |  |  |  |  |
| Atualização/frequência |  |  |  |  |
| Regra de revisão retroativa |  |  |  |  |
| Limitação conhecida |  |  |  |  |
| Uso institucional atual |  |  |  |  |

## 4. Comparação obrigatória

Antes da aprovação, anexar o resultado de:

1. cobertura territorial por fonte;
2. municípios ausentes;
3. conflitos de valores dentro da mesma fonte;
4. diferença absoluta e relativa entre fontes no mesmo município/ano;
5. efeito das diferenças nas taxas V2;
6. paridade legado × V2;
7. eventual mudança de classificação operacional causada exclusivamente pelo denominador.

## 5. Decisão institucional

### Prioridade aprovada

`source_priority`:

1. ______________________________
2. ______________________________
3. ______________________________
4. ______________________________

### Regras adicionais

- `allow_previous_year`: [ ] true  [ ] false
- `allow_unlisted_sources`: [ ] true  [ ] false

**Justificativa técnica/institucional:**

____________________________________________________________

____________________________________________________________

## 6. Aprovações

- Data Governance: __________________ / data: __________
- Epidemiologia/Inteligência em Saúde: __________________ / data: __________
- Responsável institucional pelo produto: __________________ / data: __________
- STI/custódia técnica, quando aplicável: __________________ / data: __________

## 7. Regra de efetivação

A política só poderá mudar para `status: APPROVED` após:
- preenchimento desta decisão;
- cobertura territorial validada;
- conflitos internos resolvidos ou explicitamente bloqueados;
- paridade avaliada;
- registro dos aprovadores;
- PR revisado.

Até lá, a V2 deve continuar sem selecionar automaticamente fonte vencedora em territórios ambíguos.
