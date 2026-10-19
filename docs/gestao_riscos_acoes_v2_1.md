# Gestão de Riscos e Ações — LACEN-MT V2.1

## Objetivo

Transformar sinais do Radar LACEN em um ciclo operacional rastreável de decisão e resposta:

```
SINAL → RISCO → PRIORIZAÇÃO → RESPONSÁVEL → AÇÃO → PRAZO
      → EVIDÊNCIA → RISCO RESIDUAL → VALIDAÇÃO → ENCERRAMENTO
```

A camada não declara surto, epidemia ou emergência automaticamente.

## 1. Registro de riscos

Fonte primária: `saida_pipeline/radar_eventos_risco.csv`.

Cada agravo × território recebe `risk_id` estável entre semanas. O registro mantém:

- primeira e última semana de detecção;
- evento, agravo, família e município;
- tipo do sinal;
- probabilidade e impacto;
- score e prioridade inerentes;
- confiança e evidências;
- veredito operacional;
- responsável;
- estratégia de tratamento;
- decisão e evidência da decisão;
- risco residual;
- estado e datas do ciclo de vida.

## 2. Matriz de risco

Escalas:
- baixo = 1;
- médio = 2;
- alto = 3.

`score = probabilidade × impacto`

| Score | Prioridade |
|---:|---|
| 1–2 | BAIXA |
| 3–5 | MODERADA |
| 6–8 | ALTA |
| 9 | CRÍTICA |

A matriz prioriza resposta; não substitui avaliação epidemiológica.

## 3. Ciclo de vida do risco

`ABERTO → EM_ANALISE → EM_MITIGACAO → MONITORAMENTO → CONTROLADO → FECHADO`

Nenhum risco fecha automaticamente.

`CONTROLADO` e `FECHADO` exigem:
- decisão explícita;
- evidência da decisão;
- probabilidade residual;
- impacto residual;
- justificativa do risco residual.

`FECHADO` exige ainda todas as ações relacionadas em `VALIDADA` ou `CANCELADA`.

Se um risco fechado reaparecer em nova semana, ele volta automaticamente para `EM_ANALISE`.

## 4. Plano de ações

As ações atualmente produzidas pelo Radar são convertidas em registros individuais para:
- CIEVS-MT;
- Vigilância Epidemiológica municipal;
- área técnica;
- municípios vizinhos/regional;
- LACEN-MT.

Estados:
`PLANEJADA → EM_ANDAMENTO → CONCLUIDA → VALIDADA`

Estados alternativos:
- `BLOQUEADA`;
- `CANCELADA`.

`CONCLUIDA` exige evidência de execução e resultado.
`VALIDADA` exige também validação explícita.

## 5. Prazos padrão iniciais

- CRÍTICA: 1 dia;
- ALTA: 2 dias;
- MODERADA: 7 dias;
- BAIXA: 14 dias.

Esses prazos são operacionais e podem ser ajustados explicitamente por ação.

## 6. Risco residual

Após intervenção, registrar novamente probabilidade × impacto.

Nunca assumir que uma ação concluída eliminou o risco. O risco residual precisa ser analisado e justificado.

## 7. Resumo operacional

Artefato: `saida_pipeline/quality/risk_action_summary_v2_1.json`.

Status:
- `BLOCK`: risco crítico aberto ou risco crítico/alto com ação atrasada;
- `WARN`: risco alto, ação bloqueada ou ação ainda aberta;
- `PASS`: sem pendências operacionais relevantes na camada.

Esse status é **operacional** e não substitui o Promotion Gate técnico da V2.1.

## 8. Agentes

### RISK_REGISTER_STEWARD
Responsável por:
- integridade do registro;
- aging;
- ações atrasadas;
- risco residual;
- reabertura de riscos recorrentes;
- consistência dos estados;
- evidência de encerramento.

### EMERGENCY_RESPONSE_COORDINATOR
Atua quando risco CRÍTICO/ALTO exige coordenação:
- consolida ações;
- propõe responsáveis;
- identifica dependências e bloqueios;
- organiza escalonamento;
- prepara pauta para decisão humana.

Não ativa COES, não declara emergência e não substitui autoridade competente.

## 9. Definition of Done

A gestão de um risco só é considerada encerrada quando:
1. risco está `FECHADO`;
2. decisão e evidência estão registradas;
3. risco residual está documentado;
4. ações estão `VALIDADA` ou `CANCELADA`;
5. não há reaparecimento do sinal no ciclo mais recente;
6. o encerramento é auditável.

## 10. Integração com Cursor

O Cursor deve consultar:
- `quality/risk_action_management.py`;
- `docs/gestao_riscos_acoes_v2_1.md`;
- `quality/agent_reviews.py`;
- `config/agent_orchestration_v2_1.json`.

Qualquer melhoria futura deve preservar IDs estáveis, histórico humano e proibição de encerramento automático.
