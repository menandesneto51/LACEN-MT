# Prompt de continuidade — Cursor / LACEN-MT V2.1

Você está trabalhando na branch `feat/v2-data-quality-agent`.

## Objetivo
Completar o Data Quality Agent e integrar o gate ao pipeline sem regressão.

## Já implementado
- `quality/data_quality_agent.py`;
- PASS/WARN/BLOCK;
- checks básicos de SE, contagens, população e TAT;
- testes em `tests/test_data_quality_agent.py`;
- CI em `.github/workflows/quality-gate.yml`;
- gate chamado em `etl/run_etl_dw.py` antes de rede/ML/mirror/CIEVS;
- freshness auditável sem limiar inventado, completude, duplicidade, encoding e validação de código IBGE;
- lineage mínimo no artefato de qualidade;
- utilitário de maturação corrigido para anos ISO com SE 53.

## Execute agora
1. Rode `pytest`.
2. Faça smoke test de imports do `etl.run_etl_dw`.
3. Adicione testes de integração provando que `BLOCK` impede chamadas de rede/ML/mirror/CIEVS e que `WARN` não interrompe o pipeline.
4. Localize as fontes populacionais de staging e faça o gate de população atuar apenas nos produtos que realmente calculam taxas/incidência.
5. Evolua `municipio_ibge` para chave canônica propagada pela dimensão territorial; não introduza novas correções hardcoded de nomes.
6. Defina contratos de freshness por fonte em configuração versionada; até validação institucional, ausência de SLA permanece `WARN`, nunca limiar inventado.
7. Registre lineage por produto com fonte, tabela/arquivo lógico, data de corte, check_id e versão do pipeline, sem path absoluto local.
8. Adicione testes de regressão para encoding e códigos IBGE.
9. Preserve a correção ISO/SE53 e não altere a âncora solicitação/coleta sem decisão documentada.
10. Mantenha artefatos em `saida_pipeline/quality/` e não faça merge.

## Critérios de aceite
- BLOCK impede inferência/ML/mirror/CIEVS;
- WARN permanece visível;
- testes demonstram os dois comportamentos;
- anos ISO com SE53 são cobertos;
- população incompatível temporalmente bloqueia taxa dependente;
- nenhuma credencial/PII/path local é adicionada;
- `pytest` verde;
- mudanças pequenas, revisáveis e documentadas.

Não faça merge. Prepare commits para revisão no PR #7.
