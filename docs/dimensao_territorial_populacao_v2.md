# LACEN-MT V2.1 — Dimensão territorial e população versionada

## Objetivo
Criar uma camada territorial auditável que permita substituir progressivamente joins frágeis por nome de município e eliminar denominadores populacionais silenciosamente incompatíveis com o período analisado.

## Contrato da dimensão
Arquivo lógico: `dim_populacao_versionada`.

Campos:
- `municipio_ibge`: código IBGE de 7 dígitos quando fornecido pela origem;
- `municipio`: nome original/normalizado para exibição e fallback técnico;
- `ano_referencia`: ano explícito do denominador;
- `populacao`: valor populacional;
- `fonte`: origem lógica, por exemplo `DW:POPULACAO`;
- `versao_fonte`: identificação da fonte/staging;
- `extraido_em`: timestamp de extração;
- `is_fallback`: indica uso explícito de ano anterior.

## Regras
1. Código IBGE é a chave territorial preferencial.
2. O sistema não inventa código IBGE a partir de nome.
3. Múltiplas fontes podem coexistir no staging.
4. Nenhuma fonte é escolhida como vencedora sem prioridade configurada.
5. Fallback para ano anterior é proibido por padrão.
6. Produto de contagem não é bloqueado por ausência de população.
7. Produto de taxa/incidência deve declarar `population_required=True` e só prossegue com denominador compatível.
8. Dados populacionais antigos/incompletos permanecem WARN em produtos que não dependem deles e viram BLOCK quando o denominador é requisito do produto.
9. Não usar mapeamentos hardcoded de nomes para criar identidade territorial oficial.
10. Todo uso de denominador deve expor fonte e ano de referência.

## Fontes de staging atualmente consideradas
- `VW_POPULACAO`;
- `POPULACAO`;
- `POPULACAO_TOTAL`;
- `POPULACAO_TCU`.

A presença no staging não implica validação institucional da fonte.

## Artefatos
Gerados em `saida_pipeline/quality/`:
- `dim_populacao_versionada.csv`;
- `dim_populacao_versionada.parquet`;
- `data_quality_gate_ultimo.json`;
- `data_quality_gate_ultimo.txt`.

## Próximo estágio
- propagar `municipio_ibge` para agregados GAL/SINAN/SIM/SIH/SIA;
- criar dimensão territorial municipal separada de população;
- definir prioridade de fontes populacionais por decisão de governança;
- conectar produtos de taxa/incidência ao seletor explícito de denominador;
- remover gradualmente joins por nome depois de testes de paridade.
