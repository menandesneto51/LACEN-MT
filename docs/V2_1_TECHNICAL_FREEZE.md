# LACEN-MT V2.1 — Technical Freeze

**Status:** ATIVO  
**Branch:** `feat/v2-data-quality-agent`  
**Motivo:** arquitetura V2.1 estabilizada e CI verde; trabalho passa a focar DEC-001 e DEC-002.

## Evidência de congelamento

- GitHub Actions: `LACEN-MT Quality Gate`
- Run: #355
- HEAD validado: `91d10a2f7ebbe40b01e0b6e71602cc2ab3c64128`
- Conclusão: `SUCCESS`

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

Executar o ETL com dados reais e produzir:
- `gal_temporal_anchor_summary.json`;
- `gal_temporal_anchor_weekly_comparison.csv`;
- `population_source_comparison_summary.json`;
- `population_source_coverage_detail.csv`;
- `population_source_pairwise_comparison.csv`;
- `decision_brief_DEC-001.md`;
- `decision_brief_DEC-002.md`;
- `decision_readiness_v2_1.json`.


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
