# Formulário de aprovação institucional — LACEN-MT V2.1

**Decisão automática:** proibida  
**Aprovação via chat/agente:** inválida para gravar `APPROVED` em config

Este formulário é o caminho oficial para sair do estado `PENDING` de DEC-001/DEC-002.
Após preenchimento humano, gerar `config/institutional_endorsement_v2_1.json` e validar:

```powershell
python scripts/aplicar_aprovacao_institucional_v2_1.py --dry-run
```

## Evidências a consultar

- `saida_pipeline/quality/dossier_sala_decisao_v2_1.md`
- `DEC-001_evidence_packet.md` / `decision_brief_DEC-001.md`
- `DEC-002_evidence_packet.md` / `decision_brief_DEC-002.md`
- `gal_temporal_anchor_summary.json`
- `population_source_comparison_summary.json`

## DEC-001 — Âncora temporal GAL

Marque exatamente uma:

- [ ] A — Solicitação como âncora única
- [ ] B — Coleta como âncora única
- [ ] C — Âncoras distintas por finalidade
- [ ] D — Manter regra atual temporariamente

Série histórica:

- [ ] Não reprocessar
- [ ] Reprocessar integralmente
- [ ] Reprocessar período definido: ________
- [ ] Duas séries paralelas

Fundamentação (obrigatória):

> 

## DEC-002 — Fontes populacionais

Ordem de prioridade aprovada (1 = maior):

1. _______________
2. _______________
3. _______________

Fallback de ano anterior: [ ] Proibido  [ ] Permitido (regra: ________)  
Fontes não listadas: [ ] Bloquear  [ ] Permitir sob condição: ________

## Assinaturas (nome completo + cargo + data YYYY-MM-DD)

| Papel | Nome | Cargo | Data |
|---|---|---|---|
| Responsável institucional pelo produto |  |  |  |
| Clinical/Epidemiological Specialist |  |  |  |
| Security/Data Governance |  |  |  |

## Schema do JSON de endosso

Arquivo: `config/institutional_endorsement_v2_1.json`

```json
{
  "schema_version": "v2.1-endorsement-1",
  "automatic_decision_allowed": false,
  "DEC-001": {
    "alternative": "A",
    "historical_series": "nao_reprocessar",
    "rationale": "..."
  },
  "DEC-002": {
    "source_priority": ["DW:POPULACAO_TOTAL"],
    "allow_previous_year": false,
    "allow_unlisted_sources": false,
    "rationale": "..."
  },
  "signers": {
    "responsavel_institucional": {
      "name": "Nome Completo",
      "role_title": "Cargo institucional",
      "signed_at": "2026-09-27",
      "note": ""
    },
    "clinical_epidemiological": {
      "name": "Nome Completo",
      "role_title": "Cargo",
      "signed_at": "2026-09-27",
      "note": ""
    },
    "data_governance": {
      "name": "Nome Completo",
      "role_title": "Cargo",
      "signed_at": "2026-09-27",
      "note": ""
    }
  }
}
```
