# LACEN-MT V2 — Data Quality Agent

## Papel
Gate determinístico de confiabilidade executado **antes** de análise epidemiológica, ML, alerta e relatório. Não diagnostica, não classifica surto e não altera regra clínica/epidemiológica.

## Contrato
- **PASS** — checks executados sem achado impeditivo.
- **WARN** — análise pode prosseguir, mas o achado deve permanecer visível e auditável.
- **BLOCK** — o produto dependente do dado não pode ser publicado como consolidado.

## Checks iniciais
- domínio de ano/SE;
- contagens negativas;
- positivos > exames;
- ano e validade do denominador populacional;
- compatibilidade temporal da população com a análise;
- TAT negativo;
- TAT extremo como warning.

## Próxima expansão
Freshness por fonte, completude por agravo/marcador, duplicidade, município/código IBGE, chaves de linkage, encoding, datas impossíveis, lineage, contratos SINAN/SIM/SIH/SIA/CNES/SISREG/IndicaSUS e gates específicos por produto.

## Saída
`data_quality_gate_ultimo.json` para automação e `data_quality_gate_ultimo.txt` para auditoria humana.

## Princípio
`DADO → QUALIDADE → REGRA → ANÁLISE → SINAL → INTERPRETAÇÃO → AÇÃO`.

Nunca permitir `dado não validado → inferência automatizada → alerta institucional`.
