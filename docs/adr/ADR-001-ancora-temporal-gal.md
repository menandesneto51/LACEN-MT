# ADR-001 — Âncora temporal do GAL para semana epidemiológica

**Status:** PENDENTE DE DECISÃO  
**Escopo:** LACEN-MT V2.1  
**Decisão automática:** proibida

## Contexto

O pipeline atual usa preferencialmente a data de solicitação do GAL para derivar ano/semana epidemiológica, com fallback para outras datas quando a solicitação não está disponível.

A revisão Clinical/Epidemiological Specialist bloqueou a promoção da V2 enquanto a regra institucional da âncora temporal GAL — especialmente solicitação versus coleta — não estiver formalmente decidida.

A documentação operacional do GAL evidencia que o sistema acompanha o fluxo desde a solicitação até a liberação do resultado e que a data de coleta é informação laboratorial/epidemiológica relevante. Isso, porém, não é suficiente por si só para substituir a âncora atual sem avaliar o objetivo analítico do produto e o impacto sobre a série histórica.

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
