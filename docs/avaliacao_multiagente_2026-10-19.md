# Avaliação Multiagente — LACEN-MT

**Data:** 19/10/2026  
**Branch:** `feat/v2-data-quality-agent`  
**PR:** #7  
**HEAD avaliado:** `6f12a829641ec8095778f1dc1dce142e5cf1faed`  
**Status global:** **CONDITIONAL**  
**Promoção automática:** proibida

## Síntese executiva

O projeto apresenta boa maturidade arquitetural e epidemiológica. O núcleo de qualidade de dados, governança territorial, população, linkage, risco e ação, inteligência laboratorial e estatística está consistente e coberto por testes. O PR encontra-se tecnicamente mergeável e o HEAD avaliado possui CI verde com 169 testes aprovados.

A avaliação multiagente, entretanto, identifica lacunas operacionais que justificam manter o projeto em **CONDITIONAL** antes de uma promoção institucional ampla. As principais são:

1. Vigilância Genômica obrigatória, porém ainda sem ingestão operacional validada.
2. Modelos ML com desempenho heterogêneo por família.
3. Quality Gate sem lint/SAST, dependency audit e secret scan dedicados.
4. Ausência de observabilidade operacional robusta do pipeline.
5. Supply Chain ainda fora da camada operacional de risco.
6. Revisão técnica/ABNT final dos produtos publicados ainda pendente.

## Parecer por agente

| Agente | Status | Avaliação |
|---|---|---|
| SES_DATA_CATALOG | PASS | Preflight institucional definido e obrigatório. |
| CTO Virtual | PASS | Arquitetura incremental, V2 paralela ao legado e gates independentes. |
| Product Owner | PASS | Produto orientado a decisão, risco e resposta. |
| Chief Architect | PASS | Arquitetura coerente, determinística e auditável. |
| Clinical/Epidemiological Specialist | PASS | Separação correta entre sinal, caso, surto e decisão. |
| Emergency Response Coordinator | PASS | Fluxo de risco→ação→evidência→residual implementado. |
| Risk Register Steward | PASS | Persistência, lifecycle e reabertura testados. |
| Data Architect | PASS | Chaves, denominadores, lineage e território bem governados. |
| Data Governance | PASS | Decisões e evidências versionadas. |
| Backend/API | WARN | Forte dependência de scripts/CSV; camada de serviço ainda limitada. |
| AI/GIS | WARN | Inteligência territorial existe, mas QA geoespacial formal pode avançar. |
| ML Specialist | WARN | Globalmente útil, porém famílias específicas apresentam desempenho insuficiente. |
| Statistics Specialist | PASS | Método reproduzível e linguagem estatística saneada. |
| Laboratory Intelligence Specialist | PASS | Métricas laboratoriais bem separadas de interpretação epidemiológica. |
| Genomic Intelligence Specialist | WARN | Obrigatório, porém sem ingestão genômica operacional validada. |
| Supply Chain Specialist | WARN | Estoques/reagentes ainda não participam do risco operacional. |
| Technical Writing/ABNT | WARN | Falta auditoria final sistemática dos produtos publicados. |
| UX | WARN | Dashboard funcional, porém monolítico e sem testes de usabilidade formais. |
| Performance | WARN | CSV/dashboard monolítico podem limitar escalabilidade. |
| Security | WARN | CI atual não inclui SAST, dependency audit ou secret scan dedicados. |
| QA | PASS | CI verde; 169 testes aprovados no HEAD avaliado. |
| Observability/DevOps | WARN | Falta healthcheck/telemetria operacional estruturada. |
| Chief Architect Final | CONDITIONAL | Sem BLOCK estrutural, mas P1 ainda precisa saneamento. |

## Prioridades P1

### 1. Segurança do CI
Adicionar ao Quality Gate:
- lint;
- análise estática de segurança;
- auditoria de dependências;
- secret scan;
- smoke test de imports e dashboard.

### 2. Vigilância Genômica
Executar `SES_DATA_CATALOG` para localizar fonte institucional de:
- sequenciamento;
- linhagem;
- variante;
- metadados de amostra.

Depois implementar a camada governada amostra → sequência → linhagem/variante → linkage epidemiológico.

### 3. ML por família
Não promover alertas autônomos por família sem critério mínimo versionado. Recalibrar ou suprimir recortes com desempenho inadequado, especialmente respiratório, hepatite e “outros”.

### 4. Gestão de riscos e ações
Adicionar:
- aging;
- SLA por prioridade/tipologia;
- tempo até mitigação;
- recorrência;
- efetividade das ações;
- matriz RACI.

## Prioridades P2

- Integrar Supply Chain ao risco laboratorial.
- Implementar observabilidade e health status.
- Auditar os produtos finais sob critérios técnicos/ABNT.
- Criar contratos mais explícitos de serviço para risco, ações e consultas.

## Prioridades P3

- Modularizar o dashboard.
- Validar UX com usuários CIEVS/LACEN.
- Medir performance e reduzir dependência de CSV quando houver benefício comprovado.
- Formalizar QA geoespacial.

## Continuidade P1 — implementação em 19/10/2026

### Segurança do CI
Implementado no Quality Gate:
- `ruff` para erros críticos de lint;
- secret scan do repositório;
- `bandit` para análise estática de segurança;
- `pip-audit` para dependências;
- pytest permanece obrigatório.

O status de Segurança só deve migrar de WARN após o novo workflow concluir sem bloqueios ou após os achados serem saneados.

### Gestão de riscos e ações
Implementados:
- `age_days`;
- `sla_days`;
- `sla_status`;
- `time_to_close_days`;
- `recurrence_count`;
- `reopened_at`;
- aging de ações;
- dias até o prazo;
- indicadores de riscos fora do SLA e recorrentes no dashboard.

### Vigilância Genômica
O preflight `SES_DATA_CATALOG` foi concluído:
- `dbo.VW_GAL` fornece a âncora institucional de amostra, incluindo `Amostra` e `Codigo_Amostra`;
- não foram encontrados no catálogo campos explícitos de `linhagem`, `variante`, `sequenciamento` ou `genoma`;
- decisão do preflight: `NEW_SOURCE_REQUIRED`;
- isso significa identificar/catalogar a fonte oficial já usada pelo LACEN para resultados genômicos, e não inventar um novo sistema.

Artefato: `config/catalog_evidence_genomics_v2_1.json`.

### Supply Chain
O preflight identificou `dbo.SUINS_INSUMOS_ENTRADAS_SAIDAS` como fonte institucional potencial para movimentação de insumos, com entradas, saídas, lote, fornecedor, destino e quantidades.

Decisão: `EXTEND_EXISTING`. Ainda é necessário validar completude, saldo/base histórica e recorte específico do LACEN antes de calcular estoque ou risco de ruptura.

Artefato: `config/catalog_evidence_supply_chain_v2_1.json`.

### ML
Foi implementado `quality/ml_backtest_gate.py`.

Regra técnica mínima:
- `AUC < 0,5` → `BLOCK` para interpretação operacional daquele escopo;
- AUC ausente → `WARN`;
- o gate não define limiar epidemiológico nem declara evento.

O ETL gera `quality/ml_model_gate_v2_1.json` e registra os escopos bloqueados/avisados.

---

## Conclusão dos agentes

**Não há BLOCK estrutural no projeto neste momento.**  
O LACEN-MT está tecnicamente consistente e com boa governança, mas a recomendação conjunta dos agentes é manter o estado **CONDITIONAL** até o fechamento dos itens P1.

O merge técnico do PR não deve ser interpretado como promoção institucional automática.
