# AGENTS — Regra Global de Engenharia

Este projeto adota obrigatoriamente o framework multiagente SISA/SISAE.

## Fluxo
CTO Virtual → Product Owner → Chief Architect → especialistas aplicáveis → Security → QA → Observability/DevOps → revisão final do Chief Architect.

## Especialistas
Clinical Specialist; Data Architect; Data Governance; API Architect; Backend Engineer; AI Engineer; GIS Specialist; UX Research; Frontend Engineer; Performance Engineer; Security Engineer; QA Engineer; Observability/DevOps.

O CTO seleciona os agentes aplicáveis a cada slice. GIS é obrigatório em lógica territorial/geoespacial. Clinical Specialist é obrigatório quando houver regra sanitária, clínica ou epidemiológica.

## Vetos
- Clinical Specialist: regra sanitária/epidemiológica sem fundamento verificável.
- Data Governance: indicador sem fonte, temporalidade, lineage ou definição reproduzível.
- Security Engineer: secrets expostos, acesso indevido ou despacho inseguro.
- Chief Architect: arquitetura paralela, acoplamento indevido ou quebra das decisões arquiteturais vigentes.

## Regras permanentes
- Preservar decisões e arquitetura válidas do projeto; não impor stack de outro sistema.
- Regras oficiais e cálculos devem ser determinísticos, versionados, testáveis e auditáveis.
- IA pode explicar, sintetizar, priorizar e sugerir; não pode inventar nem alterar silenciosamente regra oficial.
- Toda proxy deve ser identificada como proxy.
- Fontes, referência temporal, transformação e saída devem ter lineage.
- Mudanças arquiteturais relevantes exigem ADR.
- Entregas devem possuir critérios de aceite, testes, revisão de segurança, observabilidade e documentação.
- Não substituir saída operacional vigente sem equivalência validada.
- Implementações devem considerar a transição desenvolvimento local → infraestrutura institucional quando aplicável.

## Definition of Done
Uma mudança só está concluída quando os critérios de aceite foram atendidos, fontes e regras estão documentadas, testes aplicáveis passaram, segurança e observabilidade foram consideradas, documentação foi atualizada e o Chief Architect realizou a revisão final.
