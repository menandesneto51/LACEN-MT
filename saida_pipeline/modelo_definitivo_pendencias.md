# Modelo definitivo — pendências (Radar LACEN / CIEVS)

Atualizado: 2026-08-31 09:35 Hora Padrão Brasil Central

Este arquivo lista campos do modelo desejado: **implementado** com os dados atuais ou **stub** (placeholder) até haver histórico/coluna adequada.

| Campo | Status | Nota |
|-------|--------|------|
| Coeficiente de completude semanal por base | Parcial | Inventário de fontes no staging + flag de SE parcial no briefing; coeficiente formal 0–1 por base ainda depende de calendário de carga DW. |
| Canal endêmico Bortman (razão vs mediana 5 anos) | Implementado | Módulo `ml/canal_endemico_bortman.py` → `canal_endemico.xlsx` + `canal_endemico_classificacao.csv` (272 combinações SE atual; 29 classificadas; 17 em alerta/epidemia). Série preferencial: positivos laboratoriais; NA não vira zero; <3 anos baseline → sem_dado. Radar reforça score se zona alerta/epidemia. |
| Positividade nominal por marcador/metodologia | Implementado | GAL micro (0 registros) → `positividade_por_marcador.csv`. |
| População IBGE 2026 para taxas | Parcial | Usa melhor POPULACAO disponível no staging/weekly; anotar se não for 2026. |
| Exames órfãos consolidados por município (GAL sem SINAN) | Implementado | `briefing_gal_sinan_divergencia.csv` (flag gal_sem_sinan). |
| Deduplicação por ID paciente | Bloqueado | Sem identificador no micro GAL (LGPD / não extraído). |
| Score prioridade municipal | Implementado (proposta) | `score_prioridade_municipal.csv` — rótulo: proposta para homologação. |
| Alertas específicos por sinal | Implementado | `alertas_especificos/alerta_*.md` (+ html). |

## Canal endêmico Bortman (implementado)

Método Bortman (P25/P50/P75) sobre os últimos 5 anos excl. ano atual, mesma SE. Zonas: sucesso / seguranca / alerta / epidemia / sem_dado. Saídas: `canal_endemico.xlsx` (Classificacao, Limites, Metadados) e `canal_endemico_classificacao.csv` para join no Radar.

## Completude semanal (orientação)

Para cada base (GAL, SINAN, SIH, SIM, IndicaSUS, SISREG): completude = semanas_com_carga / semanas_esperadas no ano epidemiológico. Expor no Radar quando o calendário ETL estiver versionado.
