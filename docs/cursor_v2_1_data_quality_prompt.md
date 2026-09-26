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
- gate chamado em `etl/run_etl_dw.py` antes de rede/ML/mirror/CIEVS.

## Execute agora
1. Rode `pytest`.
2. Faça smoke test de imports do `etl.run_etl_dw`.
3. Adicione testes do comportamento do pipeline quando o gate retorna BLOCK, garantindo que ML/CIEVS não sejam chamados.
4. Implemente freshness por fonte e completude sem inventar limiares clínicos.
5. Detecte duplicidades com chaves configuráveis; não presuma uma chave nominal de paciente.
6. Crie validação territorial baseada em código IBGE quando a fonte o disponibilizar.
7. Adicione detecção de encoding quebrado como WARN, sem “corrigir” silenciosamente o dado original.
8. Registre lineage mínimo: fonte, arquivo/tabela, data de corte, versão/check_id.
9. Corrija qualquer lógica local de SE que assuma sempre 52 semanas usando utilitário ISO central; não altere a âncora solicitação/coleta sem decisão documentada.
10. Mantenha artefatos em `saida_pipeline/quality/`.

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
