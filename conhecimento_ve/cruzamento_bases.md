# Cruzamento de bases — LACEN / CIEVS / VE

Prioridade e valor epidemiológico de cada fonte no DW estadual (leitura somente).  
Extratos opcionais: `etl/dw_extract.py` → `saida_pipeline/staging_dw/`.  
Inventário da SE: `briefing_cruzamento_bases.csv` / seção 7d do parecer VE.

## Ordem de prioridade

| # | Base | Quando agrega valor | Chave típica de join |
|---|------|---------------------|----------------------|
| 1 | **SINAN** | Notificação compulsória; todo exame LACEN de agravo notificável deveria ter ficha. Divergência `gal_sem_sinan` / `sinan_sem_gal` por mun×família. | mun IBGE × agravo/família × SE |
| 2 | **GAL / LACEN** | Demanda laboratorial, positividade, TAT — sinal Observado do CIEVS. | mun × target × SE |
| 3 | **SIH / AIH** (proxy **`dbo.VW_INTERNACAO`**) | Internações correlatas (gravidade, pressão hospitalar) quando CID junta. **Não há view `*SIH*`/`*AIH*` no DW SES-MT** — usar `SIH_DW_TABLE=VW_INTERNACAO`. | mun × CID família × SE |
| 4 | **SIVEP / SRAG** | Respiratório grave (influenza, COVID, SRAG) — complementar a SINAN SRAG e exames moleculares. | mun × SE / classificação |
| 5 | **SIM** | Óbitos — letalidade contextual (não atribuição causal automática). | mun × CID × semana/mês |
| 6 | **CNES** | Capacidade da rede (leitos, UTI, equipes) — interpreta pressão e silêncio. | mun IBGE |
| 7 | **IndicaSUS / pactuação** | Indicadores pactuados — no DW: `INDICADORES*` / `INDICADORESPACTUACAO` (proxy). Host IndicaSUS → `staging_dw/indicasus_*`. | mun / indicador / competência |
| 8 | **SISREG** | Regulação de vagas e filas — **fora do DW**. Host `SISREG_*` → `staging_dw/sisreg_*` (aggs mun×status; falha **não bloqueia**). | mun / procedimento |
| 9 | **SIA** (`dbo.SIA`, `dbo.SIA_APAC`) | Produção ambulatorial / APAC correlata (CID×mun; extrato `TOP N` / janela recente). | mun × CID / procedimento |
| 10 | **SINASC** (`dbo.VW_SINASC`) | Nascidos — contexto perinatal (amostra `TOP N`). | mun × SE/mês |

## Fontes adicionais (IndicaSUS / SISREG / leftovers)

- Extrator: `etl/external_extract.py` (chamado por `dw_extract.run_extract`).
- Artefatos: `indicasus_inventory.csv`, `indicasus_indicador.*`, `sisreg_inventory.csv`, `sisreg_amb_mun_status_agg.*`, `sisreg_hosp_mun_status_agg.*`, `sisreg_samu_fila.*`, `vw_sinasc.*`.
- Log da última busca: `staging_dw/fontes_busca_ultimo.txt` (hosts, objetos, linhas, falhas — sem senhas).
- Caveat: metas IndicaSUS (`MetaIndicadorValor`) podem estar vazias no BdSES; catálogo `ind.Indicador` + ocupação amostral ainda úteis. SISREG: nunca full-scan das views de 10–40M linhas.

## SIH via VW_INTERNACAO

- Staging amostra: `vw_internacao_recent.parquet|csv` (janela ~90–180d, não full dump).
- Agregados: `sih_mun_cid_familia_agg.*` (mun × SE × família CID: hepatite B15–B19, TB A15–A19, dengue/arbov A90–A92/A95), `sih_mun_semana_agg.*`.
- Resumo: `cruzamento_sih_sia_resumo.json` + `cruzamento_sih_sia_top_mun.*` → seção **Cruzamento SIH/SIA** no Bloco E (CIEVS) e 7e (parecer VE).
- Colunas-chave: `MunicipioResidencia`, `CodigoDiagnosticoPrincipal` / `DiagnosticoPrincipal`, `AnoInternacao`/`MesInternacao`/`DiaInternacao` (fallback competência).

## SIA

- Staging: `sia_recent.*`, `sia_apac_recent.*`; agg `sia_mun_cid_familia_agg.*` (mun × mês × família CID) quando `CodigoCidPrincipal`/`CidPrincipal` existem.
- Caveat: correlato ambulatorial — não substitui notificação SINAN nem confirma surto.

## Regras operacionais

- Preferir **views read-only** (`VW_*`) quando VPN/env permitem; falha de view **não bloqueia** o relatório CIEVS.
- GAL micro atual **não traz bairro/CEP** → geo cai para município (centroid/`codigo_ibge`). SINAN com `BairroResidencia` habilita hotspot bairro quando o extrato estiver no staging.
- Cruzamento SIH/SIA exige chave estável (mun + CID); se ausente, listar fonte como “ausente” e seguir só com GAL×SINAN.
- **SISREG**: host separado — opcional `check_sisreg_tcp()` no extract; ausência/falha **não bloqueia**.
- Documentação MS: ver `conhecimento_ve/fontes.md` e `notificaveis_resumo.md`.

## Artefatos gerados

- `briefing_gal_sinan_divergencia.csv` — flags por mun×família (qualquer agravo)
- `briefing_geo_hotspots.csv` — bairro/CEP ou município
- `briefing_cruzamento_bases.csv` — presença no staging DW
- `staging_dw/cruzamento_sih_sia_resumo.json` — top mun internacoes/SIA + caveat
- `briefing_cruzamento_sih_sia.csv` — eco do top mun no outdir do briefing
