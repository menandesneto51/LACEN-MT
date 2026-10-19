# LACEN-MT V2.1 — Technical Freeze

**Status:** ATIVO  
**Branch:** `feat/v2-data-quality-agent`  
**Motivo:** arquitetura V2.1 estabilizada e CI verde; trabalho passa a focar DEC-001 e DEC-002.

## Evidência de congelamento

- GitHub Actions: `LACEN-MT Quality Gate`
- Run: #36286264892 (PR checks verdes no HEAD atual)
- HEAD validado: `bd84615cfa46a2145f87c799e04b0b0a6a8dfbaf`
- Conclusão: `SUCCESS`
- Nota: aprovações gravadas só via chat foram revertidas por guards de governança;
  DEC-001/DEC-002 permanecem `PENDING` até endosso formal com nome/cargo/data.

## Escopo congelado

Estão congeladas novas funcionalidades de:
- Data Quality Gate;
- paridade legado × V2;
- linkage territorial;
- reconciliação territorial;
- Promotion Gate;
- pareceres multiagente;
- Artifact Hygiene;
- Product Lineage;
- governança populacional;
- decision briefs;
- Decision Registry;
- Decision Readiness.

## Alterações permitidas durante o freeze

Somente:
1. correção de bug/regressão;
2. teste de regressão;
3. geração/coleta de evidências para DEC-001 ou DEC-002;
4. documentação factual das decisões;
5. correções de segurança/governança;
6. ajustes estritamente necessários para executar o pipeline real.

## Alterações não permitidas

- novas features sem relação direta com DEC-001/DEC-002;
- mudança silenciosa da âncora temporal GAL;
- escolha automática de fonte populacional;
- alteração de thresholds sem governança;
- promoção automática da V2;
- merge enquanto houver BLOCK/WARN institucional pendente.

## Critérios para sair do freeze

O freeze só pode ser encerrado após:
- DEC-001 validada institucionalmente;
- DEC-002 validada institucionalmente;
- parecer Clinical/Epidemiological Specialist revisado;
- parecer Security/Data Governance revisado;
- Promotion Gate reexecutado;
- CI verde no HEAD final;
- decisão explícita de release.

## Próximo foco

**Endosso formal:** `config/institutional_endorsement_v2_1.json`  
Responsável: **Menandes Neto — Responsável CIEVS-MT**.  
DEC-001: alternativa **A** (solicitação). DEC-002: `DW:POPULACAO_TOTAL`.  
Promoção automática continua **proibida**.

Próximos passos:
1. Conferir CI verde no HEAD com o endosso
2. Revisar `promotion_gate_v2_1.json` / `review_package_v2_1.md`
3. Só então decidir saída do technical freeze / release humano

Comandos:
- `python scripts/coletar_evidencias_from_staging.py --outdir saida_pipeline`
- `python scripts/gerar_dossier_sala_decisao_v2_1.py --quality-dir saida_pipeline/quality`

Artefatos esperados em `saida_pipeline/quality/`:
- `gal_temporal_anchor_summary.json` / `gal_temporal_anchor_weekly_comparison.csv`
- `population_source_comparison_summary.json` (+ coverage/pairwise)
- `data_quality_gate_ultimo.json` / `paridade_legado_v2_resumo.json`
- `paridade_linkage_resumo.json` / `reconciliacao_territorial_resumo.json`
- `decision_brief_DEC-001.md` / `decision_brief_DEC-002.md`
- `DEC-001_evidence_packet.md` / `DEC-002_evidence_packet.md`
- `decision_readiness_v2_1.json` / `decision_status_registry_v2_1.json`
- `agent_reviews_v2_1.json` / `promotion_gate_v2_1.json`
- `dossier_sala_decisao_v2_1.md`


## Execução de evidências

Usar o modo seguro:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/coletar_evidencias_decisoes_v2_1.ps1
```

Ou diretamente:

```powershell
python -m etl.run_etl_dw --evidence-only --skip-ml --skip-cievs --no-bulk
```

O modo `--evidence-only` deve:
- executar extração, qualidade, paridade, governança, decision briefs, readiness e registry;
- retornar antes de indicadores de rede/emergência, ML, mirror e CIEVS;
- gerar `validacao_etl_dw_ultimo.json` com `evidence_only=true`.
