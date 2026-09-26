# ADR-001 — Âncora temporal do GAL para semana epidemiológica

**Status:** PENDENTE DE DECISÃO  
**Escopo:** LACEN-MT V2.1  
**Decisão automática:** proibida

## Contexto

O pipeline atual usa preferencialmente a data de solicitação do GAL para derivar ano/semana epidemiológica, com fallback para outras datas quando a solicitação não está disponível.

A revisão Clinical/Epidemiological Specialist bloqueou a promoção da V2 enquanto a regra institucional da âncora temporal GAL — especialmente solicitação versus coleta — não estiver formalmente decidida.

A documentação operacional do GAL evidencia que o sistema acompanha o fluxo desde a solicitação até a liberação do resultado e que a data de coleta é informação laboratorial/epidemiológica relevante. Isso, porém, não é suficiente por si só para substituir a âncora atual sem avaliar o objetivo analítico do produto e o impacto sobre a série histórica.

## Evidência documental oficial

A documentação consultada do GAL trata **Data de Solicitação** e **Data da Coleta** como campos distintos do fluxo laboratorial. Isso sustenta a necessidade de preservar ambas as semânticas no modelo e de não converter uma na outra por conveniência técnica.

Até esta revisão, não foi identificada norma oficial que estabeleça uma dessas duas datas como âncora universal obrigatória para a semana epidemiológica de todos os produtos analíticos derivados do GAL.

Referências consultadas:
- Ministério da Saúde/BVS — formulários e instruções do GAL, com campos separados para solicitação e coleta;
- LACEN/SES-MT — manual operacional do GAL, mantendo as duas datas como eventos distintos do fluxo.

Conclusão documental: a escolha da âncora deve ser definida pela **finalidade epidemiológica/operacional do produto**, validada institucionalmente e acompanhada de análise de impacto sobre a série.

## Evidência quantitativa exigida

A V2.1 passa a gerar:
- cobertura de Data de Solicitação;
- cobertura de Data da Coleta;
- atraso solicitação−coleta;
- proporção de registros que mudam de SE;
- proporção que muda de ano epidemiológico;
- comparação semanal das contagens sob cada âncora;
- número/proporção de semanas com diferença;
- maior diferença absoluta semanal;
- soma das diferenças absolutas semanais.

Artefatos:
- `gal_temporal_anchor_detail.csv`;
- `gal_temporal_anchor_weekly_comparison.csv`;
- `gal_temporal_anchor_summary.json`;
- `gal_temporal_anchor_summary.txt`.

## Alternativas

### A. Data de solicitação
Vantagens:
- preserva o comportamento atual;
- menor risco de quebra retroativa;
- representa entrada da demanda no fluxo laboratorial.

Riscos:
- pode deslocar temporalmente o evento em relação à coleta biológica;
- pode refletir atraso administrativo.

### B. Data de coleta
Vantagens:
- aproxima o evento do momento de obtenção da amostra;
- pode ser mais aderente à interpretação epidemiológica de circulação laboratorial.

Riscos:
- pode estar ausente/inconsistente em parte da série;
- mudança retroativa altera SE, baseline e alertas;
- não deve ser aplicada sem validação institucional.

### C. Duas âncoras por finalidade
- coleta para produtos epidemiológicos;
- solicitação para produtos operacionais/laboratoriais.

Vantagens:
- separa finalidade epidemiológica de fluxo assistencial/laboratorial.

Riscos:
- maior complexidade;
- exige nomenclatura e governança explícitas para evitar comparação indevida.

## Evidência necessária antes da decisão

1. cobertura e completude das duas datas;
2. distribuição do atraso solicitação−coleta;
3. proporção de registros que mudam de SE;
4. proporção que muda de ano epidemiológico;
5. efeito sobre contagens por SE/município/agravo;
6. efeito sobre baselines, anomalias e alertas;
7. validação epidemiológica/institucional da finalidade de cada produto.

## Regra temporária

Até decisão formal:
- manter comportamento atual;
- não promover a V2;
- não reprocessar série histórica com nova âncora;
- executar análise de sensibilidade;
- registrar qualquer decisão final neste ADR.

## Decisão

**PENDENTE**

## Aprovações necessárias

- Clinical/Epidemiological Specialist
- Chief Architect
- Data Governance
- responsável institucional pelo produto
