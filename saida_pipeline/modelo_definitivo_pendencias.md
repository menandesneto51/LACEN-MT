# Modelo definitivo — pendências (Radar LACEN / CIEVS)

Atualizado: 2026-08-31 09:03 Hora Padrão Brasil Central

Este arquivo lista campos do modelo desejado: **implementado** com os dados atuais ou **stub** (placeholder) até haver histórico/coluna adequada.

| Campo | Status | Nota |
|-------|--------|------|
| Coeficiente de completude semanal por base | Parcial | Inventário de fontes no staging + flag de SE parcial no briefing; coeficiente formal 0–1 por base ainda depende de calendário de carga DW. |
| Canal endêmico Bortman (razão vs mediana 5 anos) | Parcial | Histórico semanal disponível ≈ 67439 células; canal completo exige ≥5 anos da mesma SE. Stub: razão vs mediana das últimas SE disponíveis quando a série for curta. |
| Positividade nominal por marcador/metodologia | Implementado | GAL micro (19120 registros) → `positividade_por_marcador.csv`. |
| População IBGE 2026 para taxas | Parcial | POPULACAO no staging com ano(s) 1996 — usar como denominador; confirmar se equivale a IBGE 2026. |
| Exames órfãos consolidados por município (GAL sem SINAN) | Implementado | `briefing_gal_sinan_divergencia.csv` (flag gal_sem_sinan). |
| Deduplicação por ID paciente | Bloqueado | bloqueada — ausência de identificador no espelho GAL micro (LGPD/dado não extraído) |
| Score prioridade municipal | Implementado (proposta) | `score_prioridade_municipal.csv` — rótulo: proposta para homologação. |
| Alertas específicos por sinal | Implementado | `alertas_especificos/alerta_*.md` (+ html). |

## Canal endêmico Bortman (stub)

Quando a série semanal por município×agravo tiver pelo menos 5 anos da mesma semana epidemiológica, calcular: razão = valor_atual / mediana_histórica_5anos. Faixas clássicas (Bortman): sucesso / alerta / epidemia conforme percentis. **Nesta remessa:** não calcular falso canal — apenas registrar pendência.

## Completude semanal (orientação)

Para cada base (GAL, SINAN, SIH, SIM, IndicaSUS, SISREG): completude = semanas_com_carga / semanas_esperadas no ano epidemiológico. Expor no Radar quando o calendário ETL estiver versionado.
