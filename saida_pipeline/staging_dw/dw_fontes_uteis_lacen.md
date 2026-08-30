# Fontes úteis do DW estadual para LACEN-MT / CIEVS

Inventário em `2026-08-30` (VPN SES; TCP `DW_HOST:1433` OK).  
Arquivos: `dw_views_inventory.csv` (todas as **26** views) · `dw_objects_uteis_pattern.csv` (tabelas/views por padrão de nome).

## Resumo rápido

| Família | Existe no DW por nome? | Objeto útil | Papel CIEVS/LACEN |
|--------|-------------------------|-------------|-------------------|
| GAL | sim | `dbo.VW_GAL` | Laboratório — volume/positivos/SE |
| SINAN | sim (23 views) | `dbo.VW_SINAN_*` | Notificação × agravo; cruzamento GAL |
| Internação / SIH | **não** `*SIH*` / `*AIH*` | `dbo.VW_INTERNACAO` (+ tabelas `INTERNACAO_*`) | Gravidade / pressão hospitalar (proxy SIH) |
| SIA | sim (tabelas) | `dbo.SIA`, `dbo.SIA_APAC` | Produção ambulatorial / APAC |
| SISREG | **não** no DW | — (usar host `SISREG_*` / projeto SISREG) | Regulação / filas fora do DW |
| IndicaSUS | **não** `*INDICASUS*` | `INDICADORES*` / `INDICADORESPACTUACAO` | Pactuação/indicadores (proxy no DW); DB IndicaSUS separado |
| SIM | sim (tabela) | `dbo.SIM` | Mortalidade |
| CNES | sim | `CNES_*` | Rede / leitos / estabelecimentos |
| População | sim | `POPULACAO*` | Denominadores / taxas |
| SIVEP | parcial | `SIVEP_MALARIA` | Só malaria no DW; SRAG via SINAN SRAG |
| SINASC | sim | `VW_SINASC` / `SINASC` | Nascidos (contexto perinatal) |

---

## Must-have (pipeline CIEVS / LACEN)

| Objeto | Tipo | Por quê |
|--------|------|---------|
| `dbo.VW_GAL` | VIEW | Fonte laboratorial principal; weekly SE × mun × agravo. |
| `dbo.VW_SINAN_DENGUE` | VIEW | Arbovirose prioritária; cruzamento GAL×SINAN. |
| `dbo.VW_SINAN_CHIKUNGUNYA` | VIEW | Idem arbovírus. |
| `dbo.VW_SINAN_SINDROMERESPIRATORIAAGUDAGRAVE` | VIEW | SRAG/influenza/COVID proxy no SINAN. |
| `dbo.VW_SINAN_MENINGITE` | VIEW | Evento crítico CIEVS. |
| `dbo.VW_SINAN_TUBERCULOSE` | VIEW | Agravo prioritário estadual. |
| `dbo.VW_SINAN_HEPATITE` | VIEW | Vigilância laboratorial × notificação. |
| `dbo.VW_SINAN_NOTIFICACAOINDIVIDUAL` | VIEW | Catch-all / outros agravos. |
| `dbo.VW_INTERNACAO` | VIEW | **Proxy SIH**: AIH, mun, hospital, carater, CID (83 cols). Gravidade e pressão de leitos. |
| `dbo.SIM` | TABLE | Óbitos — fechamento de gravidade. |
| `dbo.CNES_ESTABELECIMENTOS` / `CNES_LEITOS` | TABLE | Capacidade da rede. |
| `dbo.POPULACAO` (ou `POPULACAO_TOTAL`) | TABLE | Denominador para taxas. |

---

## Nice-to-have

| Objeto | Tipo | Por quê |
|--------|------|---------|
| Demais `VW_SINAN_*` | VIEW | Agravos específicos (hanseníase, leishmaniose, sífilis, Hanta, etc.). |
| `dbo.SIA` | TABLE | Ambulatorial; CID/procedimento × mun — correlato leve (TOP N). |
| `dbo.SIA_APAC` | TABLE | Procedimentos de alta complexidade / APAC. |
| `dbo.INDICADORESPACTUACAO` | TABLE | Metas/pactuação municipal (proxy IndicaSUS no DW). |
| `dbo.INDICADORES` / `INDICADORESVIGILANCIASAUDE` | TABLE | Painéis de indicadores SES. |
| `dbo.VW_SINASC` | VIEW | Contexto materno-infantil. |
| `dbo.SIVEP_MALARIA` | TABLE | Malária (cobertura limitada). |
| `CNES_EQUIPES*`, `CNES_PROFISSIONAIS`, `CNES_EQUIPAMENTOS` | TABLE | Detalhe de rede (ESF, equipamentos). |
| `INTERNACAO_REJEITADAS*` | TABLE | Qualidade/auditoria de AIH (secundário). |

---

## Skip (para LACEN/CIEVS agora)

| Objeto / família | Motivo |
|------------------|--------|
| `SIAB*` (cadastro familiar, produção AB antiga) | Baixa relevância imediata para alerta laboratorial/VE; pesado e legado. |
| `TABINDICADORES` / `TABOCUPACAO` | Tabelas de domínio/lookup; usar sob demanda. |
| `POP_IBGE_2021` se `POPULACAO*` já cobre | Redundante. |
| Views/tabelas `*SISREG*` / `*INDICASUS*` | **Não existem no DW** — não inventar join; usar conexões `SISREG_*` e `INDICASUS_*` nos `.env` irmãos. |
| Extrair `SIA` / `VW_INTERNACAO` **completo** sem filtro | Tabelas grandes — só `TOP N` / agregados por SE×mun. |

---

## IndicaSUS e SISREG (fora do catálogo de views)

- **IndicaSUS**: host próprio (`INDICASUS_HOST` ~ `*.222`, DB `BdSES`). Preferir credenciais `INDICASUS_USER`/`PASSWORD` nativas — `INDICASUS_USE_DW_CREDENTIALS` costuma falhar (login DW no host IndicaSUS). Extratos leves: `staging_dw/indicasus_*` (catálogo `ind.Indicador`, mun/região, amostra ocupação). No DW, proxy: `INDICADORES*` / `INDICADORESPACTUACAO`.
- **SISREG**: host próprio (`SISREG_HOST` ~ `*.71`, DB `SES`). Views úteis: `VW_AMBULATORIAL_SOLICITACAO`, `VW_HOSPITALAR_SINTETICO`, `VW_SAMU_FILA_HOSPITALAR`. Extratos: `staging_dw/sisreg_*` (inventário + aggs mun×status; **sem** dump das dezenas de milhões de linhas). Ping TCP opcional; falha **não bloqueia** ETL/CIEVS.
- **SIH**: não há objeto com nome `SIH`/`AIH`; usar `VW_INTERNACAO` (e opcionalmente `SIH_DW_TABLE=VW_INTERNACAO` no `.env`).

---

## Fontes adicionais (pós SIH/SIA)

ETL: `etl/dw_extract.py` + `etl/external_extract.py`. Relatório da última busca: `staging_dw/fontes_busca_ultimo.txt`.

| Fonte | Staging | Nota |
|-------|---------|------|
| Demais `VW_SINAN_*` | `vw_sinan_*.parquet` | TOP N por agravo |
| `VW_SINASC` | `vw_sinasc.*` | perinatal |
| IndicaSUS | `indicasus_*` | host separado |
| SISREG | `sisreg_*` | host separado; aggs leves |

---

## Extensão sugerida no ETL

`etl/dw_extract.py` → GAL/SINAN/SIH/SIA/INDICADORES* + leftovers SINASC/SINAN.  
`etl/external_extract.py` → IndicaSUS + SISREG. Extrair só amostra `TOP N` / janela recente, não full dump.
