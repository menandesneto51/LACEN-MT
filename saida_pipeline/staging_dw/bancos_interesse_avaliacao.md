# Avaliação de bancos de interesse — LACEN / CIEVS

Data: **2026-08-30**. Segredos mascarados. Fontes: inventário DW (`dw_inventory` / `dw_views_inventory` / `dw_objects_uteis_pattern`), `.env` / `.env.example` de LACEN + irmãos (Sentinela, TITAN, SISREG, AESOP), docs `dw_fontes_uteis_lacen.md` e `conhecimento_ve/cruzamento_bases.md`.

## Já integrados

| Banco / objeto | Host / origem | Staging / uso no relatório | Status |
|----------------|---------------|----------------------------|--------|
| **DW · VW_GAL** | SES DW `Datawarehouse` (~10.15.1.50) | `vw_gal_*` → weekly, Top10 Δ%, SE operacional | Integrado |
| **DW · VW_SINAN_*** (23 views) | idem | `vw_sinan_*` → GAL×SINAN, geo | Integrado |
| **DW · VW_INTERNACAO** (proxy SIH) | idem | `vw_internacao_recent`, `sih_mun_*`, cruzamento SIH/SIA | Integrado |
| **DW · SIA / SIA_APAC** | idem | `sia_recent`, `sia_mun_cid_familia_agg` (`sia_apac` opcional) | Integrado (SIA); APAC amostra pode faltar |
| **DW · SIM** | idem | `sim.*` | Integrado |
| **DW · CNES_ESTABELECIMENTOS / EQUIPAMENTOS** | idem | `cnes_*` | Integrado (parcial) |
| **DW · POPULACAO*** | idem | `populacao.*` | Integrado |
| **DW · INDICADORES*** | idem | `indicadores*` (proxy pactuação) | Integrado |
| **DW · SIVEP_MALARIA** | idem | `sivep_malaria.*` | Integrado (só malaria) |
| **DW · VW_SINASC** | idem | `vw_sinasc.*` | Integrado (amostra) |
| **IndicaSUS · BdSES** | host próprio (~10.15.0.222) | `indicasus_*` + sinais ocupação no briefing/CIEVS | Integrado |
| **SISREG · SES** | host próprio (~10.15.1.71) | `sisreg_*` aggs (hosp/amb/SAMU) no briefing/CIEVS | Integrado |
| **OpenWeather** | API key nos `.env` LACEN/TITAN/AESOP/SCRAPER | Clima — **não** no pipeline LACEN atual | Chave presente; não ligado ao relatório |

SE operacional de validação: **`se_usada=2026-SE30`** (`se_esperada=2026-SE34`, atraso 4 SE).

---

## Interessantes ainda não ligados

| Fonte | Prioridade | Motivo CIEVS | Como acessar | Nota |
|-------|------------|--------------|--------------|------|
| **DW · CNES_LEITOS** | **Alta** | Capacidade de leitos / pressão rede vs SIH+IndicaSUS | Já no inventário DW; `OPTIONAL_EXTRACT` em `etl/dw_extract.py` | Extrato leve TOP N → `cnes_leitos.*` (tentar nesta remessa) |
| **SIVEP-Gripe / SRAG** (fora malaria) | **Alta** | Influenza/COVID/SRAG complementar a `VW_SINAN_…SRAG` e GAL molecular | TITAN: `SIVEP_LOCAL_*` / pasta update; OpenDataSUS SRAG; AESOP bronze `sivep_gripe` | **Não** há tabela SIVEP influenza no DW SES; só `SIVEP_MALARIA` |
| **e-SUS Notifica** (SG) | **Média** | Síndrome gripal leve; NT MS cita painéis SG × SIVEP | Portal e-SUS Notifica / exports municipais — **sem** credencial no LACEN `.env` | Fora do DW; depende de export institucional |
| **GAL API** (além de VW_GAL) | **Média** | Micro/TAT/status em tempo quase real | `GAL_BASE_URL` / user no `.env.example` (placeholders) | Preferir VW_GAL no DW enquanto estável |
| **DW · SIA_APAC** (amostra dedicada) | **Média** | Alta complexidade / APAC correlata | `USE_DW_SIA` + extract `sia_apac_recent` | Soft-fail se pesado |
| **DW · CNES_EQUIPES* / PROFISSIONAIS** | **Baixa** | Rede AB / ESF — contexto, não alerta lab | DW opcional TOP N | Nice-to-have |
| **RNPI / SIPNI** (imunização) | **Baixa** | Cobertura vacinal (contexto, não surto lab) | Não encontrado nos `.env` LACEN/irmãos | Sem conexão pronta |
| **e-SUS APS** (PEC/CDS) | **Baixa** | Atenção básica — baixa prioridade alerta CIEVS lab | Sem host no LACEN | SIAB* no DW = legado → skip |
| **PCA / Farmácia hospitalar** | **Baixa** | AESOP menciona `farmacia_hospitalar` em rules | Sem DB dedicado no LACEN | Fora de escopo lab-epi agora |
| **OpenWeather no relatório** | **Baixa** | Clima × arbovírus / calor (ondas de calor / SIS-Monitoramento) | `OPENWEATHER_API_KEY` já nos `.env` | Ligar só se houver seção climática CIEVS |

---

## Fora de escopo / risco LGPD

| Item | Motivo |
|------|--------|
| Microdados nominais GAL/SINAN/SISREG (nome, CNS, endereço completo) | LGPD — relatório usa **só agregados** mun×SE×agravo |
| Full dump `SIA` / `VW_INTERNACAO` / views SISREG 10–40M linhas | Risco operacional + LGPD; só TOP N / aggs |
| `SIAB*` (cadastro familiar, moradia) | Legado AB; baixa relevância alerta; sensível |
| Credenciais DW em host IndicaSUS (`INDICASUS_USE_DW_CREDENTIALS`) | Costuma falhar login; preferir `INDICASUS_*` nativos |
| Espelhar ML no DW (`CREATE TABLE` lacen_ml_*) | Negado ao usuário atual — DBA |
| Bases nominais e-SUS APS / Notifica sem termo de uso | Não ingerir sem autorização SES |

---

## Extratos desta avaliação

| Ação | Resultado |
|------|-----------|
| IndicaSUS / SISREG | Já no staging (2026-08-30 19:46) — sinais ligados ao briefing/parecer/CIEVS |
| CNES_LEITOS | **Extraído** TOP 20k → `cnes_leitos.parquet|csv` (2026-08-30) |
| SIVEP influenza | Soft-fail — sem path local TITAN nem objeto DW |

Ver também: `dw_fontes_uteis_lacen.md`, `fontes_busca_ultimo.txt`, `conhecimento_ve/cruzamento_bases.md`.
