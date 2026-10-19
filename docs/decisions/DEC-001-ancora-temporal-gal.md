# Decisão institucional — ADR-001 Âncora temporal GAL

**Status:** APROVADA  
**Produto:** LACEN-MT V2.1  
**Decisão automática:** proibida  
**Data:** 2026-09-27  
**Endosso:** `config/institutional_endorsement_v2_1.json`

## Evidências obrigatórias

Consultar `saida_pipeline/quality/gal_temporal_anchor_summary.json` e pacotes DEC-001.

## Decisão

- [x] A — Solicitação como âncora única
- [ ] B — Coleta como âncora única
- [ ] C — Âncoras distintas por finalidade
- [ ] D — Manter regra atual temporariamente e coletar mais evidências

### Fundamentação

Preservar a âncora atual em data de solicitação, mantendo comparabilidade histórica e evitando reprocessamento. Evidência de sensibilidade solicitação×coleta arquivada; escolha institucional do Responsável CIEVS-MT.

### Tratamento da série histórica

- [x] Não reprocessar histórico
- [ ] Reprocessar histórico integralmente
- [ ] Reprocessar apenas período definido
- [ ] Manter duas séries paralelas

## Aprovações

- Clinical/Epidemiological Specialist: Menandes Neto (Responsável CIEVS-MT (vigilância epidemiológica)) — 2026-09-27
- Data Governance: Menandes Neto (Responsável CIEVS-MT (governança dos produtos de vigilância)) — 2026-09-27
- Responsável institucional pelo produto: Menandes Neto (Responsável CIEVS-MT / produto LACEN-MT V2.1) — 2026-09-27
- Data da decisão: 2026-09-27
