# SES_DATA_CATALOG — Preflight obrigatório para o LACEN-MT

## Objetivo

Evitar duplicação de fontes, coletores, ETLs, tabelas e indicadores já cobertos pelo ecossistema de dados da SES-MT. O preflight deve ocorrer **antes** de qualquer implementação que dependa de nova origem de dados ou nova interpretação de uma origem existente.

## Quando executar

Execute o `SES_DATA_CATALOG` antes de:
- criar nova fonte, coletor, scraper ou integração por API;
- criar ou alterar ETL/ELT;
- criar tabela intermediária, dimensão ou fato;
- criar indicador novo ou mudar sua origem;
- introduzir linkage entre sistemas;
- propor substituição de fonte oficial;
- criar fallback de dados.

Não é necessário reexecutar o preflight para mudanças puramente visuais, correções ortográficas, refactors sem alteração de contrato de dados ou testes que não criem dependência nova.

## Fontes prioritárias já inventariadas

O catálogo mestre institucional deve ser consultado antes de buscar fonte externa. No contexto SES-MT, a busca deve começar pelos inventários já disponíveis, incluindo:
- DW SES/Datawarehouse;
- SISREG;
- e-SUS APS;
- IndicaSUS;
- SI-PNI;
- GAL/LACEN quando aplicável;
- demais objetos institucionais já documentados no Catálogo Mestre SES-MT.

Este repositório não deve copiar credenciais, microdados ou caminhos locais usados para acessar esses inventários.

## CatalogEvidencePack

Toda mudança de dados deve deixar uma evidência mínima auditável com a seguinte estrutura lógica:

```json
{
  "agent": "SES_DATA_CATALOG",
  "checked_at": "ISO-8601",
  "request": {
    "need": "descrição objetiva da necessidade de dados",
    "project": "LACEN-MT",
    "branch": "feat/v2-data-quality-agent"
  },
  "catalog_matches": [
    {
      "system": "DW|SISREG|eSUS_APS|IndicaSUS|SI_PNI|GAL|outro",
      "object": "objeto/tabela/view/end-point conhecido",
      "coverage": "o que a fonte cobre",
      "evidence": "referência de catálogo"
    }
  ],
  "gap": {
    "exists": false,
    "description": "lacuna comprovada ou null"
  },
  "decision": "REUSE|EXTEND_EXISTING|NEW_SOURCE_REQUIRED|BLOCK",
  "recommendation": "ação recomendada",
  "constraints": [
    "sem credenciais no código",
    "sem microdados identificáveis no repositório"
  ]
}
```

## Regras de decisão

### REUSE
Use quando o catálogo já contém fonte/objeto suficiente. Não crie coletor paralelo.

### EXTEND_EXISTING
Use quando a fonte já existe, mas falta transformação, agregação, view ou coluna derivada. A extensão deve preservar lineage.

### NEW_SOURCE_REQUIRED
Só use quando a lacuna estiver demonstrada e nenhuma fonte catalogada cobrir o requisito. Deve haver justificativa técnica e de governança.

### BLOCK
Use quando não foi possível comprovar a origem, o acesso, a definição do dado ou quando a proposta violaria segurança/governança.

## Integração com Cursor

Antes de implementar mudança de dados no Cursor:
1. ler esta regra e `.cursor/rules/lacen-v2.mdc`;
2. registrar o `CatalogEvidencePack` no contexto da tarefa;
3. reutilizar o objeto catalogado sempre que possível;
4. somente então editar código;
5. executar testes e Quality Gate;
6. atualizar lineage e documentação correspondente.

## Critério de aceite

Uma PR que introduza nova dependência de dados sem evidência de preflight deve permanecer bloqueada para revisão até que o `CatalogEvidencePack` seja produzido e revisado.

O preflight não autoriza automaticamente uso de dados, release ou promoção. Ele apenas demonstra que a arquitetura consultou primeiro o catálogo institucional e evitou duplicação desnecessária.
