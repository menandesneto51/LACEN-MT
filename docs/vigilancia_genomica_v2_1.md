# Vigilância Genômica — contrato de integração LACEN-MT V2.1

## Papel no produto

A Vigilância Genômica é componente obrigatório do desenho do LACEN-MT. Na V2.1, o componente entra inicialmente como **contrato governado de dados e análise**, sem inventar fonte, API ou coletor ainda não validado.

A ausência de dados genômicos no ciclo operacional não significa `NOT_APPLICABLE`. Significa que o eixo está **aplicável, porém ainda não operacionalizado**, devendo permanecer visível no readiness e no Promotion Gate.

## Preflight obrigatório

Antes de qualquer ingestão genômica, executar `SES_DATA_CATALOG` e produzir um `CatalogEvidencePack` que responda:

1. existe no DW SES, GAL/LACEN ou outra fonte institucional objeto com sequenciamento, linhagem, variante ou metadados da amostra?
2. qual é a granularidade: exame, amostra, sequenciamento, consenso, linhagem, variante ou caso?
3. há identificador técnico estável de amostra que permita linkage sem expor PII?
4. quais datas existem: coleta, recebimento, sequenciamento, liberação, submissão?
5. há cobertura histórica e atualização regular?
6. quais campos são laboratoriais observados e quais são interpretações derivadas?
7. existe fonte externa oficialmente autorizada que precise ser vinculada?

Sem esse preflight, nova ingestão genômica permanece bloqueada.

## Contrato mínimo de dados

Quando a fonte estiver validada, a camada normalizada deve preferir os seguintes campos lógicos:

- `sample_key`: identificador técnico pseudonimizado/estável;
- `municipio_ibge`;
- `data_coleta`;
- `data_sequenciamento`;
- `data_liberacao`;
- `agente`;
- `metodo_sequenciamento`;
- `plataforma`;
- `linhagem`;
- `variante`;
- `subvariante`;
- `qc_status`;
- `coverage_pct`;
- `depth_mean`;
- `source_system`;
- `source_version`;
- `extracted_at`.

Campos ausentes devem permanecer nulos; não inferir linhagem ou variante a partir do nome do exame.

## Regras analíticas

- resultado molecular ≠ genoma sequenciado;
- genoma sequenciado ≠ linhagem atribuída;
- linhagem/variante ≠ maior gravidade;
- frequência observada de variante ≠ prevalência populacional sem desenho amostral adequado;
- ausência de sequenciamento ≠ ausência de circulação;
- mudança de proporção pode refletir mudança na estratégia de amostragem;
- risco clínico, transmissibilidade ou escape imune só podem ser atribuídos com evidência externa explícita e versionada;
- análise genômica deve informar denominador: amostras elegíveis, sequenciadas e com classificação válida;
- série temporal deve manter coleta e sequenciamento separadamente;
- linkage com vigilância epidemiológica deve preservar a distinção entre amostra, pessoa, caso e notificação.

## Indicadores mínimos previstos

Somente após validação da fonte:
- número de amostras elegíveis;
- número e proporção sequenciada;
- sucesso de sequenciamento;
- TAT coleta → sequenciamento;
- TAT coleta → liberação;
- distribuição de linhagens/variantes entre sequências válidas;
- diversidade de linhagens;
- cobertura territorial das sequências;
- completude de metadados;
- proporção de amostras sem classificação;
- mudanças temporais de composição, sempre com denominador explícito.

## Genomic Intelligence Specialist

O agente deve revisar:
- integridade do contrato amostra→sequência→linhagem;
- qualidade e cobertura;
- viés de seleção;
- completude temporal e territorial;
- versionamento do classificador/linhagem;
- interpretação de variantes;
- afirmações de risco biológico;
- linkage com GAL/SINAN/SIVEP/SIM quando aplicável.

Saída esperada: `GenomicIntelligenceReviewPack`.

## Estado V2.1

- eixo genômico: **APLICÁVEL**;
- ingestão operacional versionada: **a validar**;
- fonte oficial: **não presumida**;
- `SES_DATA_CATALOG`: obrigatório antes da implementação;
- parecer do Genomic Intelligence Specialist: deve permanecer `WARN` ou `BLOCK` enquanto a fonte e o contrato operacional não forem validados;
- promoção automática: proibida.
