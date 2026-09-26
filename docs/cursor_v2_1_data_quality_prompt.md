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
- utilitário de maturação corrigido para anos ISO com SE 53;
- `quality/territorial_dimension.py` com dimensão populacional versionada e seleção explícita por ano/fonte;
- staging ampliado para considerar `POPULACAO_TCU`;
- contrato documentado em `docs/dimensao_territorial_populacao_v2.md`;
- GAL/DW e fallback local propagam `municipio_ibge` para os agregados semanais;
- integração epidemiológica usa `territory_key`: `IBGE:<7 dígitos>` quando disponível e `NAME:<nome normalizado>` apenas como fallback legado;
- testes em `tests/test_territory_key_integration.py` cobrem propagação, joins determinísticos e paridade de totais;
- SIH/SIA agregados propagam `municipio_ibge` quando a origem disponibiliza código confiável;
- `lacen_analise_avancada.py` prefere IBGE no linkage SIH e mantém fallback nominal legado;
- integração final gera denominadores paralelos `populacao_v2` + fonte/ano e taxas `*_100k_v2`, sem substituir os indicadores legados;
- `quality/parity_report.py` gera relatório legado × V2 com detalhe municipal e resumo PASS/WARN/BLOCK;
- `quality/linkage_parity.py` audita GAL×SINAN, GAL×SIM, GAL×SIH e GAL×SIA comparando nome × IBGE;
- `quality/territorial_reconciliation.py` transforma divergências em fila acionável com prioridade, hipótese técnica, ação recomendada, responsável sugerido e estado de reconciliação;
- cada item de reconciliação recebe `issue_id` estável e ciclo de vida `ABERTO → EM_ANALISE → CORRECAO_APLICADA → VALIDADO → FECHADO`, preservando decisão/evidência/correção entre execuções;
- `FECHADO` exige decisão, evidência, correção aplicada e validação pós-correção; o resumo calcula `promotion_ready` somente com itens críticos/altos resolvidos e sem fechamentos inválidos;
- classificações de linkage: `IGUAL`, `RECUPERADO_POR_IBGE`, `PERDIDO_COM_IBGE`, `CONFLITO`, `SEM_MATCH`;
- `BLOCK` de paridade/linkage impede promoção da camada V2, mas não interrompe a vigilância legada em produção;
- `quality/promotion_gate.py` consolida Data Quality, paridade, linkage, reconciliação, CI e revisões arquitetural/epidemiológica em `NOT_READY`, `CONDITIONAL` ou `READY_FOR_REVIEW`; nunca promove automaticamente;
- `quality/review_package.py` gera o pacote único de revisão humana em JSON/Markdown com evidências, bloqueios, condições e checklists específicos para Chief Architect e especialista epidemiológico;
- `quality/agent_reviews.py` define contratos auditáveis para Chief Architect, Clinical/Epidemiological Specialist, QA e Security/Data Governance, com status `PENDING/PASS/WARN/BLOCK`, achados, bloqueios, recomendações e decisão;
- `quality/reviews/v2_1_initial_reviews.json` contém os pareceres efetivos iniciais: Chief Architect=WARN, Clinical/Epidemiological Specialist=BLOCK, QA=WARN, Security/Data Governance=WARN. O BLOCK epidemiológico decorre da âncora temporal GAL solicitação×coleta ainda não formalmente decidida;
- `docs/adr/ADR-001-ancora-temporal-gal.md` registra a decisão como PENDENTE e proíbe mudança silenciosa;
- `quality/gal_temporal_anchor_analysis.py` mede cobertura das datas, atraso solicitação−coleta e impacto em SE/ano epidemiológico sem alterar o comportamento atual;
- `quality/artifact_hygiene.py` bloqueia possíveis segredos/credenciais e sinaliza PII/path local em artefatos antes do downstream;
- `quality/product_lineage.py` registra lineage por produto com fontes lógicas, corte temporal, versão do pipeline e dependências, sem path absoluto local;
- `quality/population_governance.py` + `config/population_governance_v2_1.json` controlam aprovação, prioridade de fontes e conflitos internos de denominadores. A política inicia `PENDING_APPROVAL` e não escolhe fonte vencedora automaticamente.

## Execute agora
1. Rode `pytest`.
2. Faça smoke test de imports do `etl.run_etl_dw`.
3. Os testes de integração em `tests/test_run_etl_dw_quality_gate_integration.py` já devem provar que `BLOCK` impede rede/ML/mirror/CIEVS e que `WARN` permite a continuidade inclusive de ML e CIEVS; preserve essa cobertura contra regressões.
4. Use `quality/parity_report.py` como gate de promoção: `BLOCK` significa não substituir legado pela V2; não usar esse status para interromper a publicação legada.
5. Use `quality/linkage_parity.py` para revisar diferenças de join por fonte; trate `RECUPERADO_POR_IBGE` como melhoria auditável, `SEM_MATCH` como investigação e `PERDIDO_COM_IBGE`/`CONFLITO` como bloqueio de promoção.
6. Use `quality/territorial_reconciliation.py` como backlog de saneamento: conflitos são CRÍTICOS, perdas por IBGE são ALTAS e sem-match é MODERADO. Não resolver por fuzzy match em produção; corrigir origem/dimensão e registrar a decisão.
7. Preserve `issue_id` e histórico humano entre execuções. Nunca fechar automaticamente: `FECHADO` exige decisão explícita, evidência, correção aplicada e validação pós-correção registradas.
8. Trate `territorial_promotion_ready=true` como requisito necessário, mas não suficiente, para substituir joins/denominadores legados; mantenha CI, paridade e revisão arquitetural/epidemiológica como gates adicionais.
9. Gere/consulte `promotion_gate_v2_1.json`; `READY_FOR_REVIEW` exige CI confirmado e revisões arquitetural/epidemiológica aprovadas. Use `LACEN_PROMOTION_CI_STATUS`, `LACEN_ARCHITECTURE_REVIEW` e `LACEN_EPIDEMIOLOGY_REVIEW` apenas quando essas evidências tiverem sido realmente verificadas. Ausência de evidência = `CONDITIONAL`.
10. Gere/consulte `review_package_v2_1.md`; Chief Architect e especialista epidemiológico devem revisar checklists independentes antes da decisão de release. O pacote é evidência de revisão, não autorização automática.
11. Use os pareceres versionados em `quality/reviews/v2_1_initial_reviews.json` como estado atual da revisão. Não sobrescreva um `BLOCK/WARN` com `PASS` sem evidência objetiva e registro da correção/decisão que resolveu o achado. Todos os quatro devem estar `PASS` antes de qualquer decisão favorável de release.
12. Resolver prioritariamente o BLOCK epidemiológico usando `ADR-001` e os artefatos `gal_temporal_anchor_*`. Avaliar cobertura, atraso, mudança de SE/ano e impacto nas séries/baselines antes da decisão. Até aprovação formal do ADR, não alterar a âncora nem promover a V2.
13. Não substitua ainda `populacao`/taxas legadas: compare com `populacao_v2` e `*_100k_v2` até decisão formal de governança.
14. A prioridade populacional deve vir exclusivamente de `config/population_governance_v2_1.json`. Enquanto `status != APPROVED`, territórios com múltiplas fontes concorrentes permanecem sem denominador V2. Não usar variável de ambiente para contornar essa governança.
15. Defina contratos de freshness por fonte em configuração versionada; até validação institucional, ausência de SLA permanece `WARN`, nunca limiar inventado.
16. Preserve e amplie `product_lineage_v2_1.json`; nenhuma fonte deve ser registrada como path local absoluto.
17. Preserve o Artifact Hygiene Gate; segredo/credencial = `BLOCK`, PII/path local = `WARN` e investigação.
18. Preserve a correção ISO/SE53 e não altere a âncora solicitação/coleta sem decisão documentada.
19. Rode `pytest`, mantenha artefatos em `saida_pipeline/quality/` e não faça merge.

## Critérios de aceite
- BLOCK impede inferência/ML/mirror/CIEVS;
- WARN permanece visível;
- testes demonstram os dois comportamentos;
- anos ISO com SE53 são cobertos;
- população incompatível temporalmente bloqueia taxa dependente;
- nenhuma credencial/PII/path local é adicionada;
- `pytest` verde, incluindo integração BLOCK/WARN e regressão de zero-padding IBGE;
- mudanças pequenas, revisáveis e documentadas.

Não faça merge. Prepare commits para revisão no PR #7.
