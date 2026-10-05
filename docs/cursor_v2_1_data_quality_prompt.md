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
- os joins de produção SINAN/SIM usam IBGE primeiro; fallback por nome exato só ocorre quando pelo menos um lado não possui código válido. Códigos IBGE válidos conflitantes nunca caem para nome e fuzzy matching permanece proibido;
- `quality/territorial_reconciliation.py` transforma divergências em fila acionável com prioridade, hipótese técnica, ação recomendada, responsável sugerido e estado de reconciliação;
- cada item de reconciliação recebe `issue_id` estável e ciclo de vida `ABERTO → EM_ANALISE → CORRECAO_APLICADA → VALIDADO → FECHADO`, preservando decisão/evidência/correção entre execuções;
- `FECHADO` exige decisão, evidência, correção aplicada e validação pós-correção; o resumo calcula `promotion_ready` somente com itens críticos/altos resolvidos e sem fechamentos inválidos;
- classificações de linkage: `IGUAL`, `RECUPERADO_POR_IBGE`, `PERDIDO_COM_IBGE`, `CONFLITO`, `SEM_MATCH`;
- `BLOCK` de paridade/linkage impede promoção da camada V2, mas não interrompe a vigilância legada em produção;
- testes de integração BLOCK/WARN cobertos em `tests/test_run_etl_dw_quality_gate_integration.py`;
- contratos versionados de freshness em `quality/freshness_contracts.json` (SLA null até validação institucional);
- `quality/promotion_gate.py` consolida Data Quality, paridade, linkage, reconciliação, CI e revisões arquitetural/epidemiológica em `NOT_READY`, `CONDITIONAL` ou `READY_FOR_REVIEW`; nunca promove automaticamente;
- `quality/review_package.py` gera o pacote único de revisão humana em JSON/Markdown com evidências, bloqueios, condições e checklists específicos para Chief Architect e especialista epidemiológico;
- `quality/agent_reviews.py` define contratos auditáveis para Chief Architect, Clinical/Epidemiological Specialist, QA e Security/Data Governance, com status `PENDING/PASS/WARN/BLOCK`, achados, bloqueios, recomendações e decisão;
- `quality/reviews/v2_1_initial_reviews.json` contém os pareceres efetivos atuais: Chief Architect=PASS, Clinical/Epidemiological Specialist=PASS, QA=PASS, Security/Data Governance=PASS, após aprovação formal de DEC-001 e DEC-002;
- DEC-001 está formalmente aprovada com âncora GAL em `solicitacao`; qualquer mudança futura exige nova decisão/ADR e evidência;
- `quality/gal_temporal_anchor_analysis.py` mede cobertura das datas, atraso solicitação−coleta, impacto em SE/ano epidemiológico e diferença agregada por semana sem alterar o comportamento atual;
- `quality/artifact_hygiene.py` bloqueia possíveis segredos/credenciais e sinaliza PII/path local em artefatos antes do downstream;
- `quality/product_lineage.py` registra lineage por produto com fontes lógicas, corte temporal, versão do pipeline e dependências, sem path absoluto local;
- `quality/population_governance.py` + `config/population_governance_v2_1.json` controlam aprovação, prioridade de fontes e conflitos internos de denominadores. DEC-002 está aprovada com prioridade `DW:POPULACAO_TOTAL` e sem fallback silencioso para fonte não listada;
- `quality/population_source_comparison.py` produz cobertura territorial e diferenças par-a-par entre fontes populacionais para sustentar a decisão institucional;
- `quality/decision_briefs.py` gera `decision_brief_DEC-001` e `decision_brief_DEC-002` em JSON/Markdown a partir dos artefatos reais do ETL, resumindo fatos, riscos e opções sem tomar decisão automaticamente;
- `quality/decision_registry.py` + `config/decision_status_v2_1.json` consolidam DEC-001/DEC-002 em `PENDING/APPROVED/REJECTED`, exigindo responsável, data, evidência e conteúdo para decisões concluídas; o Promotion Gate consome esse estado. Para decisões concluídas, as evidências referenciadas também precisam existir em `saida_pipeline/quality/`;
- `quality/decision_readiness.py` verifica se DEC-001/DEC-002 estão tecnicamente prontas para submissão humana: `READY_FOR_HUMAN_DECISION`, `NEEDS_EVIDENCE` ou `DATA_QUALITY_BLOCK`. Essa camada nunca escolhe a decisão.
- `quality/decision_evidence_packets.py` gera `DEC-001_evidence_packet.md` e `DEC-002_evidence_packet.md` preenchendo evidencias quantitativas sem marcar alternativa nem aprovar decisao;

## Execute agora
1. Rode `pytest`.
2. Faça smoke test de imports do `etl.run_etl_dw`.
3. Os testes de integração em `tests/test_run_etl_dw_quality_gate_integration.py` já devem provar que `BLOCK` impede rede/ML/mirror/CIEVS e que `WARN` permite a continuidade inclusive de ML e CIEVS; preserve essa cobertura contra regressões.
4. Use `quality/parity_report.py` como gate de promoção: `BLOCK` significa não substituir legado pela V2; não usar esse status para interromper a publicação legada.
5. Preserve a mesma semântica entre auditoria e produção: IBGE primeiro; fallback por nome exato apenas se algum lado não tiver código; conflito entre códigos válidos = sem match/diagnóstico, nunca fallback. Fuzzy matching em produção é proibido.
6. Use `quality/territorial_reconciliation.py` como backlog de saneamento: conflitos são CRÍTICOS, perdas por IBGE são ALTAS e sem-match é MODERADO. Não resolver por fuzzy match em produção; corrigir origem/dimensão e registrar a decisão.
7. Preserve `issue_id` e histórico humano entre execuções. Nunca fechar automaticamente: `FECHADO` exige decisão explícita, evidência, correção aplicada e validação pós-correção registradas.
8. Trate `territorial_promotion_ready=true` como requisito necessário, mas não suficiente, para substituir joins/denominadores legados; mantenha CI, paridade e revisão arquitetural/epidemiológica como gates adicionais.
9. Gere/consulte `promotion_gate_v2_1.json`; `READY_FOR_REVIEW` exige CI confirmado, revisões arquitetural/epidemiológica aprovadas, governança populacional aprovada, Decision Registry com DEC-001/DEC-002 em `APPROVED` e `decision_readiness_v2_1.json` em `READY_FOR_HUMAN_DECISION`. `NEEDS_EVIDENCE` mantém condição; `DATA_QUALITY_BLOCK` gera bloqueio.
10. Gere/consulte `review_package_v2_1.md`; Chief Architect e especialista epidemiológico devem revisar checklists independentes antes da decisão de release. O pacote é evidência de revisão, não autorização automática.
11. Use os pareceres versionados em `quality/reviews/v2_1_initial_reviews.json` como estado atual da revisão. Chief Architect, Clinical/Epidemiological Specialist, QA, Security/Data Governance, Laboratory Intelligence Specialist e Statistics Specialist estão em `PASS`; ML Specialist, Genomic Intelligence Specialist e Technical Writing/ABNT permanecem em `WARN`; Supply Chain Specialist está `NOT_APPLICABLE` no escopo atual. Não alterar esses estados sem evidência objetiva e registro da decisão/correção.
12. Preservar a decisão aprovada DEC-001: âncora temporal GAL em `solicitacao`. Não reabrir ou alterar essa regra sem nova evidência, ADR e decisão institucional explícita.
13. Não substitua ainda `populacao`/taxas legadas: compare com `populacao_v2` e `*_100k_v2` até decisão formal de governança.
14. A prioridade populacional deve vir exclusivamente de `config/population_governance_v2_1.json`. DEC-002 está aprovada com `source_priority=['DW:POPULACAO_TOTAL']` e `allow_unlisted_sources=false`; fontes fora da prioridade não podem ser usadas como fallback silencioso.
15. Contratos de freshness versionados em `quality/freshness_contracts.json`; até validação institucional, ausência de SLA permanece `WARN`, nunca limiar inventado.
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


## Technical Freeze V2.1

A partir do HEAD validado pelo CI #355 (`91d10a2f7ebbe40b01e0b6e71602cc2ab3c64128`), a arquitetura V2.1 está congelada conforme `docs/V2_1_TECHNICAL_FREEZE.md`.

Após resolução formal de DEC-001 e DEC-002:
- não adicionar novas features;
- aceitar somente bugfix, testes, segurança/governança e geração de evidências necessárias às decisões;
- não alterar silenciosamente âncora temporal GAL, prioridade populacional, thresholds ou regras de promoção;
- manter PR em draft e sem merge;
- foco operacional: validar pipeline real, agentes, evidências, Promotion Gate e pacote final de revisão humana.


## Preflight institucional obrigatório

Antes de criar ou alterar fonte, coletor, scraper, API, ETL, tabela de integração, dimensão, indicador ou fallback de dados:
1. consultar o agente `SES_DATA_CATALOG`;
2. ler `docs/SES_DATA_CATALOG_PREFLIGHT.md`;
3. produzir um `CatalogEvidencePack`;
4. reutilizar fonte/objeto institucional já catalogado quando houver cobertura;
5. somente criar nova ingestão quando a lacuna estiver demonstrada;
6. manter credenciais, PII e caminhos locais fora do repositório.

A ausência desse preflight para nova dependência de dados deve ser tratada como BLOCK de engenharia no Cursor.

## Estado de continuidade

- Branch: `feat/v2-data-quality-agent`;
- PR: #7;
- último Quality Gate confirmado: SUCCESS no commit `5c73a2159ab5fd606f4d558902bf76483e3d6bd6`;
- DEC-001: APPROVED — GAL ancorado em solicitação;
- DEC-002: APPROVED — prioridade populacional `DW:POPULACAO_TOTAL`;
- próximo foco: validar preflight do catálogo, especialistas aplicáveis e Promotion Gate;
- não fazer merge automaticamente.


## Pareceres especialistas — estado atual (2026-09-28)

- Laboratory Intelligence Specialist: PASS.
- ML Specialist: WARN — backtest real revisado; desempenho global é aceitável como sinal auxiliar, mas há desempenho insuficiente em famílias específicas (especialmente respiratório), exigindo recalibração/supressão antes de promoção dessas saídas.
- Statistics Specialist: PASS — método e backtest revisados; apresentação do canal endêmico corrigida para `acima do P75 (sinal estatístico)`, sem inferência automática de epidemia.
- Technical Writing/ABNT: WARN — caminho local absoluto já foi saneado; falta revisão final sistemática dos relatórios/artefatos efetivamente destinados à publicação.
- Genomic Intelligence Specialist: WARN — Genômica é eixo obrigatório do LACEN-MT; contrato em `docs/vigilancia_genomica_v2_1.md`; executar `SES_DATA_CATALOG` e manter readiness visível até validar fonte e ingestão operacional.
- Supply Chain Specialist: NOT_APPLICABLE no HEAD atual; ativar quando houver estoque/reagentes/consumíveis/risco de desabastecimento.

Enquanto houver WARN aplicável, `agent_reviews_status` deve permanecer `PENDING`, fazendo o Promotion Gate permanecer no máximo `CONDITIONAL` na ausência de outros bloqueios. Não converter WARN em PASS sem evidência objetiva.


### Regra específica — Vigilância Genômica

No LACEN-MT, Genômica nunca deve ser classificada como `NOT_APPLICABLE`.
Enquanto a fonte/ingestão ainda não estiver operacionalmente validada:
- manter `Genomic Intelligence Specialist = WARN` ou `BLOCK` conforme gravidade;
- consultar `docs/vigilancia_genomica_v2_1.md`;
- executar `SES_DATA_CATALOG` antes de criar coletor/API/ETL;
- produzir `CatalogEvidencePack`;
- não inferir variante/linhagem a partir de exame molecular;
- preservar amostra → sequência → linhagem/variante → linkage epidemiológico como entidades distintas.


## Gestão de riscos e ações — implementação V2.1

Implementado:
- `quality/risk_action_management.py`;
- registro persistente `risk_register_v2_1.csv`;
- plano persistente `action_register_v2_1.csv`;
- resumo `risk_action_summary_v2_1.json`;
- matriz probabilidade × impacto;
- prioridades BAIXA/MODERADA/ALTA/CRITICA;
- estados do risco `ABERTO → EM_ANALISE → EM_MITIGACAO → MONITORAMENTO → CONTROLADO → FECHADO`;
- estados das ações `PLANEJADA → EM_ANDAMENTO → CONCLUIDA → VALIDADA`, com BLOQUEADA/CANCELADA;
- prazos padrão por prioridade;
- risco residual obrigatório para CONTROLADO/FECHADO;
- reabertura automática para EM_ANALISE quando risco controlado/fechado reaparece;
- persistência de trabalho humano em ciclos sem novos sinais;
- módulo de dashboard `Gestão de riscos e ações`;
- `RISK_REGISTER_STEWARD` e `EMERGENCY_RESPONSE_COORDINATOR` no manifesto de agentes;
- integração no ETL e no lineage.

Regras:
1. risco epidemiológico operacional não é Promotion Gate técnico;
2. nenhum risco fecha automaticamente;
3. `FECHADO` exige todas as ações VALIDADA ou CANCELADA;
4. CONCLUIDA/VALIDADA exige evidência de execução + resultado;
5. risco residual exige probabilidade, impacto e justificativa;
6. risco CRÍTICO aberto gera `risk_action_status=BLOCK`;
7. ALTA/ação bloqueada/ação aberta gera `WARN`;
8. agente não declara emergência nem ativa COES automaticamente;
9. preservar `risk_id`/`action_id` estáveis;
10. consultar `docs/gestao_riscos_acoes_v2_1.md`.

Próximas evoluções permitidas:
- histórico longitudinal de risco;
- SLA configurável por tipologia;
- matriz de responsáveis por agravo;
- integração com comunicação/agenda após autorização;
- indicadores de aging, tempo até mitigação e efetividade das ações;
- vínculo com Genômica, rede laboratorial e capacidade quando as fontes estiverem validadas.
