# Reestruturação do Alerta Estratégico — Radar LACEN

**Destinatário:** Vigilância Epidemiológica estadual / CIEVS-MT  
**Produto:** Radar LACEN · Alerta Estratégico  
**Status:** Especificação operacional vigente (referência para geração e QA)

---

## Objetivo

Revisar integralmente o gerador do “Radar LACEN · Alerta Estratégico” para que o produto final seja:

- mais técnico;
- mais epidemiologicamente consistente;
- mais curto;
- mais legível;
- mais institucional;
- mais orientado à decisão;
- menos repetitivo;
- menos dependente de linguagem de sistema;
- capaz de diferenciar anomalia estatística de sinal epidemiológico prioritário;
- capaz de diferenciar volume de exames, positividade, pessoa positiva, caso e notificação.

O alerta **NÃO** deve reproduzir todo o painel.

### Separação conceitual

| Produto | Função |
|---------|--------|
| **ALERTA ESTRATÉGICO** | Síntese para decisão, investigação e acionamento |
| **PAINEL RADAR LACEN** | Detalhamento completo, séries, municípios, agravos, marcadores, anomalias e metodologia |
| **ANEXO / METODOLOGIA** | Definições, algoritmos, parâmetros estatísticos, linkage e regras completas |

### Meta do alerta executivo

- aproximadamente 2 páginas;
- aproximadamente 900–1.200 palavras;
- máximo de 5–8 sinais prioritários;
- detalhamento integral permanece no painel.

---

## 1. Princípio central

O alerta deve permitir que um gestor compreenda em menos de 2 minutos:

- o que mudou;
- em qual município;
- qual agravo ou marcador está envolvido;
- se o sinal é de volume, positividade, incidência, silêncio ou linkage;
- qual a magnitude absoluta;
- qual a referência;
- qual a robustez;
- qual a interpretação epidemiológica;
- qual ação precisa ser realizada;
- por quem;
- em qual prazo.

Não transformar automaticamente desvio estatístico em surto.

Aplicar obrigatoriamente:

```
ANOMALIA ESTATÍSTICA
≠ PRIORIDADE EPIDEMIOLÓGICA
≠ SURTO / EPIDEMIA / EMERGÊNCIA
```

---

## 2. Nova estrutura do alerta

1. SÍNTESE EXECUTIVA  
2. SINAIS PRIORITÁRIOS  
3. DESTAQUE TERRITORIAL  
4. LACUNAS LABORATÓRIO × VIGILÂNCIA  
5. ENCAMINHAMENTOS  

Ao final: **NOTA DE INTERPRETAÇÃO** + **PAINEL RADAR LACEN** (link).

Cada sinal deve ser analisado **uma vez**. Nos encaminhamentos, repetir somente a ação relacionada ao sinal.

---

## 3. Cabeçalho

```
RADAR LACEN · SES-MT / CIEVS-MT

ALERTA ESTRATÉGICO — SE XX/AAAA

Situação: [descrição sintética automática]
Atualização: DD/MM/AAAA às HHhMM
Hora de Mato Grosso
```

Não utilizar data ISO no documento público.

---

## 4. KPIs executivos

Limitar a no máximo 6–8 indicadores. Preferência:

- EXAMES  
- RESULTADOS POSITIVOS  
- MUNICÍPIOS COM EXAMES  
- TEMPO MEDIANO DE LIBERAÇÃO  
- LIBERAÇÕES EM ATÉ 48 H  
- SILÊNCIO LABORATORIAL  
- CONFIRMAÇÃO DE SINAIS ANTERIORES  

**PRESSÃO DA REDE:** somente se houver significado validado (escala, unidade, parâmetro, interpretação). Caso contrário, **retirar** do alerta executivo.

---

## 5–7. Indicadores especiais

### Pressão da rede

Auditar o cálculo. Não inventar interpretação. Se não houver definição consolidada: **retirar**.

### Silêncio laboratorial

Formalizar no código: universo, histórico, semanas, critério, total vs grupo, histórico mínimo. No alerta: “Silêncio laboratorial: N municípios”. Em nota: definição real do Radar.

### Confirmação de sinais anteriores

Mostrar numerador e denominador quando disponíveis. Definir formalmente o que significa **CONFIRMADO** (regra real do artefato).

---

## 8. Síntese executiva

Um parágrafo de 4–6 linhas, dinâmico. Não repetir todos os números do cabeçalho.

---

## 9. Tipos de sinal (independentes)

- ANOMALIA DE VOLUME  
- ANOMALIA DE POSITIVIDADE  
- ANOMALIA DE INCIDÊNCIA (somente com base válida)  
- LACUNA LABORATÓRIO × NOTIFICAÇÃO  
- SILÊNCIO LABORATORIAL  
- SINAL DE DESEMPENHO LABORATORIAL  

Nunca misturar tudo em uma única lista.

---

## 10. Exame não é caso

```
EXAME ≠ RESULTADO POSITIVO ≠ PESSOA POSITIVA ≠ CASO ≠ NOTIFICAÇÃO
```

Escrever: “Aumento do **volume de exames** para hepatite B…”. Só afirmar aumento de casos com base epidemiológica válida.

---

## 11–16. Formato, diferença absoluta, robustez e prioridade

Formato padrão do sinal: município · agravo/marcador; tipo | prioridade; atual / anterior / diferença absoluta / referência / positivos / positividade; severidade estatística; robustez; interpretação; **ação**.

Diferença absoluta **antes** da variação percentual. Se anterior = 0: variação “não calculável com denominador zero”.

Positividade: `33,3% (1/3)` — vírgula decimal brasileira.

**Robustez amostral** independente da severidade estatística.

**Prioridade epidemiológica:** ACOMPANHAMENTO | MODERADA | ALTA | CRÍTICA (com critérios definidos).

---

## 17. Ações padronizadas

| Ação | Uso típico |
|------|------------|
| VALIDAR | Marcador / contexto / amostra pequena |
| INVESTIGAR | Volume expressivo ou linkage relevante |
| ACOMPANHAR | Demanda sem positividade (ex.: Juína HBV) |
| ESCALONAR | Evidências compatíveis com investigação de surto |

---

## 18–22. Hepatites, pequeno n, quedas, arredondamento, incidência

- Identificar marcador (A/B/C; HBsAg, anti-HBc, anti-HCV, IgM etc.) quando a fonte permitir.  
- Pequeno n: severidade alta + robustez baixa → VALIDAR MARCADOR.  
- Quedas frágeis: painel, não alerta.  
- QA `DISPLAY_ROUNDING_CONFLICT` se arredondamento apaga a diferença.  
- Não chamar “incidência” sem validação (pessoas únicas, residentes etc.).

---

## 23–28. Juína, linkage e Cuiabá/TB

Destaque Juína resumido (HBV, HCV, diarreicas agrupadas). Auditar 57 × 59 (marcador agudo vs universo do linkage).

Seção **LACUNAS LABORATÓRIO × VIGILÂNCIA**: “sem correspondência identificada no cruzamento disponível” — não afirmar subnotificação.

Cuiabá · Tuberculose: INVESTIGAR LINKAGE.

---

## 29. Dengue

Não inferir ausência de transmissão. Revisar tipo de exame, oportunidade, critérios, definição de caso e notificação. Separar NS1 / RT-PCR / IgM quando possível.

---

## 30–32. Encoding, municípios, emojis

`normalize_lab_description`; municípios por IBGE; sem emojis no documento institucional.

---

## 33–40. Seleção, não repetição, encaminhamentos, Juína/HBV estadual, nota

Máximo 5–8 sinais. `signal_id` único. Encaminhamentos em 48h e 7 dias. Não usar “possível surto/epidemia/emergência” genericamente. Juína: acompanhar no Radar; escalonar só com evidências. Hepatite B estadual: investigar aumento de **volume de exames**, não “aumento de hepatite”. Uma única **NOTA DE INTERPRETAÇÃO**.

---

## 41. Modelo final

```
RADAR LACEN · SES-MT / CIEVS-MT
ALERTA ESTRATÉGICO — SE XX/AAAA
Situação / Atualização
[KPI cards]
1. SÍNTESE EXECUTIVA
2. SINAIS PRIORITÁRIOS
3. DESTAQUE TERRITORIAL
4. LACUNAS LABORATÓRIO × VIGILÂNCIA
5. ENCAMINHAMENTOS (48h / 7 dias)
NOTA DE INTERPRETAÇÃO
Painel Radar LACEN: [link]
```

---

## 42–50. QA

Incluir: truncamento (`TEXT_TRUNCATION_ERROR`), metodologia de anomalias no anexo, objeto `SIGNAL_FACTS`, QA matemático, epidemiológico, textual, redundância, tamanho (900–1.200 palavras). Somente publicar como ALERTA ESTRATÉGICO com itens críticos OK.

---

## 51. Regra final

O produto deve deixar de ser listagem de anomalias e passar a ser instrumento de **triagem epidemiológica**:

```
DADO → ANOMALIA ESTATÍSTICA → VALIDAÇÃO DA ROBUSTEZ
    → INTERPRETAÇÃO EPIDEMIOLÓGICA → PRIORIZAÇÃO → AÇÃO
```

Nunca: `ANOMALIA → SURTO`.

O detalhamento completo permanece no **Painel Radar LACEN**.

---

## 52. Regra de maturação da semana epidemiológica

O Radar LACEN **não** utiliza automaticamente a SE corrente como semana principal de análise (viés de incompletude de resultados).

**Regra padrão:** alerta emitido na SE N → analisar prioritariamente a SE N−1.

Implementação: `lacen_semana_maturacao.py` + cabeçalho em `lacen_alerta_estrategico.py`.

---

## 53. Completude laboratorial (não usar N−1 cegamente)

Antes de fixar a semana principal:

```
completude = exames_com_resultado_final / exames_elegiveis_da_semana × 100
```

Registrar: elegíveis, liberados, pendentes, completude %, data/hora de corte.  
Quando o extract GAL só traz liberados, usa-se proxy de volume (com aviso metodológico).

---

## 54. Critério de maturação (`MIN_COMPLETENESS_FOR_ANALYSIS`)

Parâmetro configurável (env `LACEN_MIN_COMPLETENESS`, sugestão inicial **≥95%** — em validação, não norma institucional):

| Completude | Uso |
|------------|-----|
| ≥95% | madura — análise principal |
| 90–94,9% | análise com aviso explícito |
| <90% | não usar para positividade / anomalia de resultado / incidência; buscar SE anterior madura |

---

## 55. Identificar semana do alerta × semana analisada

Cabeçalho obrigatório separado:

- ALERTA ESTRATÉGICO — SE N/AAAA  
- Semana analisada — SE N−1 (ou anterior madura)  
- Data de corte  
- Completude + elegíveis / liberados / pendentes  

Nunca permitir presumir que a semana do boletim = semana dos dados.

---

## 56–57. Coleta × recebimento × liberação

- **VE:** preferir SE da **coleta**.  
- **Carga operacional:** SE de recebimento/cadastro.  
- **TAT:** recebimento → liberação final.  
- Liberação posterior **retroalimenta** a SE da coleta; não transferir o exame epidemiologicamente para a SE de liberação.

---

## 58. Data de corte

Toda emissão registra `data_corte` (America/Cuiaba), `semana_alerta`, `semana_analisada`, `completude`, `versao_dados` para reprodutibilidade.

---

## 59. Semana corrente como sinal preliminar

Bloco opcional “Sinais preliminares da semana em curso” com selo **DADO PRELIMINAR — SEMANA NÃO CONSOLIDADA**.  
Uso: demanda / pressão operacional / alerta precoce de volume.  
**Não** entrar na análise consolidada de positividade, incidência, anomalia de resultado ou ranking epidemiológico.

---

## 60. Anomalias só com semanas maduras

Baseline estatística exclui semanas incompletas. A SE corrente parcial não entra na linha de base da SE analisada.

---

## 61. Linkage SINAN e defasagem

`MIN_NOTIFICATION_LAG_DAYS` (env; sugestão inicial 3). Antes da janela: “pareamento ainda em maturação”. Depois: “sem correspondência identificada no linkage até a data de corte” — não afirmar subnotificação.

---

## 62. Positividade

Denominador = resultados finais válidos até a data de corte (não pendentes). Formato: `positivos/válidos = X,X%`. Pendentes informados à parte.

---

## 63. Completude por agravo/marcador

Além da global: se o agravo estiver abaixo do limiar, não publicar positividade como consolidada (“resultado ainda em maturação”), mesmo com completude global ≥95%.

---

## 64. QA temporal

Bloquear publicação se:

- `WEEK_MATURITY_ERROR` / semana principal < mín.  
- `CURRENT_WEEK_USED_AS_FINAL_ERROR`  
- `INCOMPLETE_WEEK_IN_BASELINE_ERROR`  
- positividade com exame pendente como final  
- semana corrente parcial apresentada como consolidada  

Avisos: `RESULT_PENDING_BIAS_WARNING`, `LOW_MARKER_COMPLETENESS_WARNING`.

---

## 65. Cabeçalho final esperado

```
RADAR LACEN · SES-MT / CIEVS-MT
ALERTA ESTRATÉGICO — SE 35/2026
Semana analisada: SE 34/2026
Atualização: 02/09/2026 às 11h57
Completude da semana analisada: 97,8%
[…]
```

Se houver preliminar da SE corrente: mencionar no painel / bloco dedicado; não incorporar à consolidada.

---

*Documento de referência para a VE / CIEVS-MT. Implementação: `lacen_alerta_estrategico.py`, `lacen_semana_maturacao.py`.*

---

## Extensão analítica V1 (estatística + linkage)

Implementação principal: `lacen_analise_avancada.py` (consumida por `montar_alerta_estrategico`).

### Fontes e chaves de integração

- **VW_INTERNACAO** (agregado local `staging_dw/sih_mun_cid_familia_agg.csv` ou `sih_mun_semana_agg.csv`): `epi_year`, `epi_week`, `municipio`, `cid_familia`, `n_internacoes`.
- **INDICASUS/VS** (`staging_dw/indicadores.csv` preferencialmente; fallback `indicadoresvigilanciasaude.csv`): município × valor do indicador.
- **População** (`staging_dw/populacao_total.csv`): denominador para internações/100 mil.
- **Forecast** (`ml_forecast_demanda.csv`): predição 1–3 semanas de exames/positividade por agravo.
- **Base laboratorial semanal** (`integrated_weekly_surveillance.csv`): `epi_year`, `epi_week`, `municipio`, `target`, `tests`, `positives`.

Quando a SE analisada não tiver SIH, usa-se a última SE disponível com **ressalva explícita de defasagem**.

### Novos blocos no alerta

- Positividade estadual da semana analisada sempre em `%` com `positivos/válidos`.
- Tendência 4–8 semanas para volume, positividade e internação (`aumento`, `estável`, `queda`).
- Nowcasting preliminar da semana em curso com IC95% e selo `DADO PRELIMINAR — SEMANA NÃO CONSOLIDADA`.
- Predição estadual S+1/S+2/S+3 com intervalos + positividade esperada + predição por agravo (risco).
- Linkage VW_INTERNACAO (n, /100 mil, semana ref.) e contexto INDICASUS.
- Nos **sinais prioritários**: linhas de internação municipal e score INDICASUS quando disponíveis.

### Novos artefatos de saída

- `saida_pipeline/analise_avancada_resumo.csv`
- `saida_pipeline/analise_tendencias.csv`
- `saida_pipeline/analise_nowcasting.csv`
- `saida_pipeline/analise_predicoes.csv`
- `saida_pipeline/analise_linkage_contexto.csv`
- `saida_pipeline/analise_consolidado_mun_agravo.csv`

Parquet é gerado em best-effort quando o ambiente possui engine disponível (`pyarrow`/`fastparquet`).

### QA adicional

Checks adicionais no QA do alerta:

- `POSITIVITY_PERCENT_FORMAT`
- `NOWCAST_WITH_UNCERTAINTY` (exige selo preliminar)
- `PREDICTION_WITH_INTERVAL`
- `LINKAGE_INTERNACAO_PRESENT`
- `LINKAGE_INDICASUS_PRESENT`
- `SIGNAL_LINKAGE_CONTEXT`
- `AGRAVO_FORECAST_PRESENT`
