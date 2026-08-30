# Cruzamento de bases — LACEN / CIEVS / VE

Prioridade e valor epidemiológico de cada fonte no DW estadual (leitura somente).  
Extratos opcionais: `etl/dw_extract.py` → `saida_pipeline/staging_dw/`.  
Inventário da SE: `briefing_cruzamento_bases.csv` / seção 7d do parecer VE.

## Ordem de prioridade

| # | Base | Quando agrega valor | Chave típica de join |
|---|------|---------------------|----------------------|
| 1 | **SINAN** | Notificação compulsória; todo exame LACEN de agravo notificável deveria ter ficha. Divergência `gal_sem_sinan` / `sinan_sem_gal` por mun×família. | mun IBGE × agravo/família × SE |
| 2 | **GAL / LACEN** | Demanda laboratorial, positividade, TAT — sinal Observado do CIEVS. | mun × target × SE |
| 3 | **SIH / AIH** | Internações correlatas (gravidade, pressão hospitalar) quando CID/agravo junta. | mun × CID/período |
| 4 | **SIVEP / SRAG** | Respiratório grave (influenza, COVID, SRAG) — complementar a SINAN SRAG e exames moleculares. | mun × SE / classificação |
| 5 | **SIM** | Óbitos — letalidade contextual (não atribuição causal automática). | mun × CID × semana/mês |
| 6 | **CNES** | Capacidade da rede (leitos, UTI, equipes) — interpreta pressão e silêncio. | mun IBGE |
| 7 | **IndicaSUS / pactuação** | Indicadores pactuados e vigilância em saúde — meta vs realizado. | mun / indicador / competência |
| 8 | **SISREG** | Regulação de vagas e filas — atraso de acesso a especialidade/UTI. | mun / procedimento |
| 9 | **SIA** | Produção ambulatorial correlata (quando disponível no DW). | mun × procedimento |

## Regras operacionais

- Preferir **views read-only** (`VW_*`) quando VPN/env permitem; falha de view **não bloqueia** o relatório CIEVS.
- GAL micro atual **não traz bairro/CEP** → geo cai para município (centroid/`codigo_ibge`). SINAN com `BairroResidencia` habilita hotspot bairro quando o extrato estiver no staging.
- Cruzamento SIH/SIA exige chave estável; se ausente, listar fonte como “ausente” e seguir só com GAL×SINAN.
- Documentação MS: ver `conhecimento_ve/fontes.md` e `notificaveis_resumo.md`.

## Artefatos gerados

- `briefing_gal_sinan_divergencia.csv` — flags por mun×família (qualquer agravo)
- `briefing_geo_hotspots.csv` — bairro/CEP ou município
- `briefing_cruzamento_bases.csv` — presença no staging DW
