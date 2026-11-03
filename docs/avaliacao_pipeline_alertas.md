# Avaliação do pipeline Radar LACEN: da extração ao alerta

**Escopo:** todas as etapas, do DW/GAL até o envio do alerta (ETL → semana epidemiológica → classificação de alvo → painel/ML → maturação → anomalias → priorização → QA → produtos/envio → retroalimentação).
**Base da avaliação:** código do repositório e artefatos versionados em `saida_pipeline/` (última carga: SE 36/2026, alerta SE 37/2026).
**Data:** 03/11/2026

---

## Resumo

A arquitetura e a especificação (`docs/alerta_estrategico_especificacao_ve.md`) estão boas: separam anomalia, prioridade e surto, tratam a maturação da semana, padronizam as ações (VALIDAR, INVESTIGAR, ACOMPANHAR, ESCALONAR) e têm um QA explícito. O problema está na **qualidade dos dados que entram no alerta**. Hoje, três defeitos de entrada pesam mais do que qualquer ajuste estatístico:

1. **A positividade está quebrada na origem.** Entre a SE 28 e a SE 36/2026, a série integrada registra dengue com 1 positivo em 1.902 exames, SARS-CoV-2 com 0 em 390, influenza com 0 em 311 e hepatite B com 0 em 982. No estado, a positividade da SE 36 foi de 0,6% (8/1.231). Esses valores não são plausíveis: o classificador de resultado (`LIKE '%positiv%'`/`'%reagent%'`) não reconhece "Detectável/Detectado" (PCR) e conta exames não liberados no denominador. Na prática, **nenhum sinal de positividade consegue ser gerado** e o alerta passa a depender só de volume.
2. **O SINAN parou de entrar na série integrada na SE 19/2026.** O campo `notificacoes` vale 0 em todas as semanas da SE 20 em diante, mesmo com as views `VW_SINAN_*` sendo extraídas do DW. Por isso, **todas as "lacunas laboratório × vigilância" do alerta SE 37 eram artefatos**: Tangará da Serra·TB (73), Várzea Grande·dengue (50), Cuiabá·TB (35) e Várzea Grande·TB (27) foram encaminhadas para "INVESTIGAR LINKAGE" sem nenhum SINAN para comparar.
3. **A completude da semana é fabricada quando falta o dado de pendentes.** O proxy de volume atribui 97% fixo sempre que o volume chega a 85% da mediana. O cabeçalho então mostra "Completude 97,0% · Pendentes: 0", e o QA `WEEK_MATURITY` passa por construção.

Somam-se a isso bugs de lógica que derrubavam justamente os sinais mais fortes: os sinais CRÍTICA eram descartados na seleção, a base das anomalias incluía a própria semana avaliada e o QA não bloqueava o envio. **Esses bugs foram corrigidos nesta entrega** (ver §12). Os três defeitos de entrada dependem do DW e de reprocessamento, e ficam como prioridade 1 do roteiro (§13).

---

## Fluxo avaliado

```
DW (VW_GAL, VW_SINAN_*, VW_INTERNACAO, SIM, CNES, POP)
  └─ etl/dw_extract.py ──► etl/build_weekly_from_gal.py ──► weekly_tests / positivity
        └─ lacen_integracao_final_only.py ──► integrated_weekly_surveillance.csv
              ├─ ml/features.py ─► ml/train.py / ml/models.py ─► ml_anomalias, ml_risco, ml_silencio
              ├─ ml/canal_endemico_bortman.py, gerar_confirmacao_emergencia.py
              └─ lacen_semana_maturacao.py + lacen_analise_avancada.py
                    └─ lacen_alerta_estrategico.py (SIGNAL_FACTS → seleção → QA)
                          └─ scripts/enviar_relatorio_cievs.py ─► e-mail / Telegram
```

Gravidade: **[C]** crítico (o alerta pode afirmar algo falso), **[A]** alto (distorce a priorização), **[M]** médio, **[B]** baixo.

---

## 1. Extração (DW / GAL)

| # | Achado | Grav. | Evidência |
|---|--------|-------|-----------|
| 1.1 | O classificador de positivo é um `LIKE` sobre a concatenação de `Campo_Resultado_1..6` + `Observacao_Resultado`. Não reconhece **Detectável/Detectado** (PCR, TRM, painel respiratório). Em exames com vários campos, "IgG: Reagente; IgM: Não reagente" vira **negativo**, porque a expressão contém "não reagent". | C | `etl/dw_extract.py:431`; positividade de 0% em PCR SARS-CoV-2 e influenza |
| 1.2 | O denominador da positividade é `COUNT(*)` e inclui pendentes. `n_liberados` é calculado no SQL e **descartado** em `weekly_from_dw_agg`. Isso contraria o §62 da especificação ("denominador = resultados finais válidos"). | C | `etl/build_weekly_from_gal.py:76-88` |
| 1.3 | As regras curadas por marcador (`conhecimento_ve/regras_agravo_gal.csv`: IgG fora do alerta agudo, `conta_positividade_agregada`) são usadas no briefing, no radar e no canal endêmico, **mas não na série principal** que alimenta o ML e as anomalias. Cada camada usa uma definição diferente de "positivo". | A | `grep regras_agravo_gal`: ausente de `etl/` e `ml/features.py` |
| 1.4 | O SINAN extraído do DW não chega a `integrated_weekly_surveillance`. `notificacoes = 0` desde a SE 20/2026, e `sinan_weekly_municipio.csv` termina na SE 19 (CSV local). | C | `saida_pipeline/sinan_weekly_municipio.csv`, `integrated_weekly_surveillance.csv` |
| 1.5 | Uma carga incompleta passa sem aviso: a SE 31/2026 tem 167 exames, contra 1.200–1.400 nas vizinhas. A queda é tratada como real (anomalia, silêncio, base de comparação). | A | série estadual SE 28–36 |
| 1.6 | `GETDATE()` usa a hora do servidor, não a de Cuiabá. A janela é de 60 SE com corte por solicitação. | B | `dw_extract.py:445` |
| 1.7 | Espelho DW: sem permissão de `CREATE TABLE`, então o histórico de alertas fica só em CSV local. | M | `validacao_etl_dw_ultimo.txt` |

**Propostas**
- Criar uma **função única `classificar_resultado(campos, exame, metodologia) → positivo | negativo | indeterminado | pendente | invalido`**, por campo (sem concatenar), com dicionário versionado em `conhecimento_ve/` (Detectável, Detectado, Reagente, Positivo, "Não detectável", "Não reagente", Inconclusivo, Indeterminado). Ela deve ser aplicada no SQL ou no microdado, e calibrada antes contra `diagnosticar_codigo_resultados_gal.py` numa amostra rotulada pelo LACEN.
- Emitir, por SE × município × alvo, as colunas `exames_solicitados`, `liberados`, `positivos`, `negativos`, `indeterminados` e `pendentes`. A positividade passa a ser `positivos / (positivos + negativos)`.
- Aplicar `regras_agravo_gal.csv` (`conta_positividade_agregada`, `conta_alerta_agudo`) **na construção da série**, não só nos relatórios.
- Integrar `VW_SINAN_*` (agregado SE × município × agravo) em `sinan_weekly_municipio.csv` a cada execução, e **falhar o ETL** (ou marcar `sinan_ok=false`) quando a última SE do SINAN estiver mais de 2 SE atrás da do GAL.
- Adicionar um **teste de carga**: volume estadual da SE abaixo de 50% da mediana de 8 SE ⇒ `carga_suspeita=true`. A semana fica fora das bases de comparação e entra num aviso no alerta.

## 2. Semana epidemiológica

| # | Achado | Grav. |
|---|--------|-------|
| 2.1 | O sistema usa **semana ISO (segunda a domingo)**. A SE oficial do Ministério da Saúde/SINAN vai de **domingo a sábado**. Exames de domingo caem em SE diferentes nos dois calendários, e o rótulo publicado ("SE 36/2026") não coincide exatamente com boletins e com o `SEM_NOT` do SINAN. | A |
| 2.2 | As âncoras são inconsistentes: a série semanal usa a **data de solicitação** (`epi_week.py`), a completude usa a **data de coleta** (`_completude_gal_micro`) e a especificação (§56) pede **coleta** para a VE. | A |
| 2.3 | **Bug da SE 53 (corrigido):** seis implementações de "SE ± n" assumiam 52 semanas (maturação, briefing, agente VE, espelho DW) ou 53 fixas (forecast, confirmação, integração, builder). 2026 tem SE 53. No alerta da SE 1/2027, a "SE N−1" seria calculada como SE 52/2026, e as previsões de 2027 gerariam uma SE 53 inexistente. | C |

**Propostas:** migrar para a SE do MS (domingo a sábado; SE 1 = semana que contém o primeiro sábado de janeiro) numa função única em `etl/epi_week.py`, usando-a no SQL (via `DATEFIRST 7`, ou calculada em Python sobre o microdado) e reprocessando o histórico. Fixar **coleta** como âncora epidemiológica e **recebimento** como âncora operacional/TAT, como manda a especificação.

## 3. Classificação de alvo (agravo)

| # | Achado | Grav. |
|---|--------|-------|
| 3.1 | `infer_target` procura o padrão em `agravo + exame`, e `dengue` é a primeira regra. Com agravo de requisição "DENGUE", os exames **Oropouche, Mayaro, Saint Louis, Nilo Ocidental (molecular), Chikungunya e Zika (IgM/IgG)** viram todos `dengue`. No catálogo GAL, esses exames somam mais registros do que os de dengue propriamente dita, então o "volume de dengue" está inflado. Verificado: `infer_target('dengue','oropouche, biologia molecular') → 'dengue'`. | A |
| 3.2 | O slug remove acentos de forma destrutiva: `hansen_ase_hansen_ase`, `doen_as_sexualmente_transmitidas_…`. São alvos duplicados ou ilegíveis na série. | M |

**Propostas:** classificar **primeiro pelo exame** (via `regras_agravo_gal.csv`, que já mapeia `exame_gal_exato → familia/marcador`) e só depois pelo agravo de requisição. Normalizar com `unicodedata` antes de gerar o slug. **Atenção:** isso muda o histórico, então exige **reprocessamento completo**. `publish_weekly_inputs` só substitui as SE da janela recente; sem reprocessar, a série ganharia uma quebra artificial.

## 4. Painel semanal e features (ML)

| # | Achado | Grav. |
|---|--------|-------|
| 4.1 | **O painel é esparso:** só existem linhas em semanas com exame (0% das linhas com `tests == 0`; desde 2025, a série município × alvo mediana tem uma única semana observada). Assim, `lag1` é a "última semana observada" (que pode ser de meses atrás), `ma4`/`ma8` são médias das últimas 4/8 semanas *observadas*, e `semanas_consec_sem_exame` vale sempre 0. | C |
| 4.2 | Consequência: o rótulo `y_silencio = next_tests ≤ 0` só vale 1 na **última linha de cada série** (`shift(-1)` = NaN → 0). O modelo de silêncio aprende "fim da série", não silêncio. | C |
| 4.3 | As médias móveis incluem a própria semana. | A |
| 4.4 | `y_alerta` usa `risco_composto` da semana seguinte, que também é feature. Mede sobretudo **persistência**; a AUC e a "confirmação" ficam infladas. | A |
| 4.5 | O forecast EWMA usa intervalo de ±1 DP (≈68%) e o apresenta como "intervalo". Na análise avançada, S+2 e S+3 eram S+1 × 1,02 e × 1,04, uma tendência de alta fixa no código **(corrigido: projeção de persistência)**. | A |

**Propostas:** completar o painel no calendário (município × alvo × SE, preenchendo zeros e limitando a séries ativas nos últimos 12 meses), recalcular as features com `shift(1)` antes do `rolling`, redefinir `y_silencio` sobre o painel completo e **retreinar** (`ml/train.py`), registrando a quebra de versão em `models_store/meta.json`. Intervalos de previsão: quantis empíricos de erro no backtest, ou Poisson/binomial negativa.

## 5. Maturação e completude da semana

| # | Achado | Grav. |
|---|--------|-------|
| 5.1 | Sem contagem de pendentes, `_completude_proxy_volume` devolve **97,0% fixo** quando o volume chega a 85% da mediana de 4 SE, e "pendentes = 0". O cabeçalho exibe isso como se fosse medida. | C |
| 5.2 | O proxy confunde **queda real** com incompletude: um silêncio verdadeiro faz a semana parecer "imatura" e o sistema recua para uma SE anterior, escondendo o próprio silêncio. Um surto, ao contrário, sempre parece "maduro". | A |
| 5.3 | O nowcast (`obs / completude`) herda o proxy e não usa a distribuição empírica de atraso. | M |

**Propostas:** a completude real já é viável, porque o SQL calcula `n_liberados`. Basta agregar por **SE de coleta** e publicar `pendentes = n_registros − n_liberados` (§1). Quando o método for proxy, exibir "estimada por volume (razão X% da mediana)" em vez de um percentual com cara de medida, e não deixar o QA `WEEK_MATURITY` passar só pelo proxy. Nowcasting: tabela de atraso coleta→liberação das últimas 12 SE (triângulo de atraso; abordagem tipo NobBS/chain-ladder).

## 6. Detecção de anomalias

**v1 (substituída nesta entrega):** `(atual − ma8) / ma8 ≥ 0,5`, com severidade "alta" a partir de +100%. Tinha cinco problemas: (a) a base incluía a semana; (b) a base era calculada sobre semanas observadas (4.1); (c) não considerava o tamanho amostral (1 → 2 exames = alta); (d) avaliava só a **última linha de cada série**, de modo que séries ativas com linha na SE corrente (parcial) **perdiam a SE analisada (N−1)**, que é exatamente o que o alerta lê; (e) não fazia teste para positividade.

**v2 (implementada, `ml/anomalias.py`):** série completa no calendário (zeros incluídos); base = média das 8 SE **anteriores**; volume e notificações pela cauda de Poisson `P(X ≥ atual | λ)`, com λ mínimo de 0,5 e excesso mínimo de 3; positividade pela cauda binomial, com n ≥ 5, k ≥ 2 e aumento ≥ 10 p.p.; severidade alta se p < 0,001 e moderada se p < 0,01; avaliação das 4 últimas SE do calendário. As colunas de saída são compatíveis com a v1. `LACEN_ANOMALIA_METODO=legado` restaura a v1 para comparação. Na SE 36/2026 com os dados versionados, a v2 gerou 36 anomalias de volume (16 alta, 20 moderada) e a v1 gerou 55, entre elas 8 de "notificações" (todas espúrias, já que o SINAN está zerado) e 5 de positividade.

**Próximos passos:**
- **Sazonalidade:** a base de 8 SE marca toda subida sazonal de dengue como anomalia. Usar uma base sazonal (mesma janela de SE em anos anteriores, Farrington flexível ou o próprio canal endêmico) para arboviroses e respiratórios.
- **Multiplicidade:** são cerca de 140 municípios × 20 alvos × 3 métricas por semana. Controlar com FDR (Benjamini-Hochberg) ou subir o limiar para "alta".
- **Persistência:** exigir 2 de 3 SE para VALIDAR→INVESTIGAR, mantendo exceção para agravos de notificação imediata (raiva, meningite, febre amarela, sarampo etc.), em que qualquer positivo prioriza.
- **Agregação espacial:** municípios vizinhos (`municipio_vizinhos.csv` já existe) com excesso simultâneo devem formar um único sinal regional.

## 7. Priorização e seleção de sinais

| # | Achado | Grav. |
|---|--------|-------|
| 7.1 | **Sinais CRÍTICA eram descartados (corrigido).** `selecionar_sinais_alerta` montava `altas + mods` e ignorava `CRITICA`, embora o escore chegue a 7,5 justamente nos casos mais fortes (severidade alta + robustez alta + excesso grande). | C |
| 7.2 | O escore é aditivo e ad hoc (bônus de +0,5 para "tubercul/hepatite b/mening/dengue" fixo no código), e a severidade de toda lacuna é fixa em "alta". | M |
| 7.3 | O "Destaque Juína" está fixo no código (`destaque_juina`). Um município não deve ter tratamento especial embutido no gerador. | M |

**Propostas:** documentar a matriz **probabilidade (p-valor/persistência) × impacto (agravo: imediato/grave/rotina) × confiança (robustez, completude, cobertura SINAN)** numa tabela versionada (`conhecimento_ve/matriz_prioridade.csv`). Trocar o bônus fixo pela classe do agravo em `regras_agravo_gal.csv` e generalizar o "destaque territorial" para o município com mais sinais e excesso agregado na SE.

## 8. QA do alerta

| # | Achado | Grav. |
|---|--------|-------|
| 8.1 | **Sete itens eram fixados em "OK" sem verificação** (severidade, prioridade, volume×positividade, linkage, silêncio, confirmação, redundância). O relatório de QA dava uma falsa garantia. **(Corrigido: agora são checagens reais.)** | C |
| 8.2 | **O QA não bloqueava o envio (corrigido no modo estratégico):** `pack["qa"].ok` só era impresso. A especificação (§42–50) diz "somente publicar com itens críticos OK". | C |
| 8.3 | Vários itens são só "string presente" (`"IC95%" in text`), o que garante formato e não conteúdo. A checagem de acentuação de municípios usa uma lista fixa de 6 nomes. | M |

**Novos itens:** `SINAN_COBERTURA` (lacuna publicada sem SINAN na SE ⇒ FALHA crítica), `POSITIVIDADE_PLAUSIVEL` (positividade estadual < 2% com n ≥ 500 ⇒ ATENÇÃO), `Linguagem anomalia ≠ surto` ("possível surto/epidemia/emergência" ⇒ FALHA crítica), `Redundância` (`signal_id` repetido ⇒ FALHA crítica). Próximo passo: validar os nomes de municípios contra a tabela IBGE de MT (`municipal_master.csv`).

## 9. Produtos e disseminação

| # | Achado | Grav. |
|---|--------|-------|
| 9.1 | **O modo padrão de envio é o "alerta unificado"** (`format_alerta_unificado`), não o Alerta Estratégico especificado. O unificado usa emojis, "Gerado em" em vez da separação semana do alerta × semana analisada e **não passa pelo QA**. O produto especificado só sai com `--legado --secretario`. | C |
| 9.2 | Há cinco produtos sobrepostos (unificado, estratégico, CIEVS técnico, relatório VE inteligente, briefing) gerados por módulos de 1,6 mil a 5,6 mil linhas, com regras de texto duplicadas. | M |
| 9.3 | O destinatário padrão do e-mail é um endereço pessoal (Gmail) fixo no código. Isso é risco institucional e de LGPD: o envio deveria falhar sem `EMAIL_TO` configurado. | M |

**Propostas:** tornar o **Alerta Estratégico (com QA) o produto padrão** e o unificado um formato de canal (Telegram curto) **derivado dos mesmos `SIGNAL_FACTS`**. Assim, um único conjunto de sinais e um único QA alimentam todos os canais. Remover o destinatário pessoal padrão.

## 10. Retroalimentação e avaliação de desempenho

"Confirmação de sinais anteriores: 168 de 333 (50%)" mede **persistência de volume** nas 1–2 SE seguintes (`_confirm_tipo`), não confirmação epidemiológica. É natural que metade dos picos persista. Esse rótulo induz o gestor a ler o número como acurácia.

**Proposta:** registrar o desfecho por `signal_id`, informado pela VE municipal ou pelo CIEVS (`confirmado | descartado | em investigação | sem retorno`, com data), numa planilha ou tabela `lacen_alerta_desfecho`. Com isso dá para reportar **VPP real**, **tempo até resposta** e **taxa de retorno**, e renomear o indicador atual para "Persistência de sinais anteriores".

## 11. Engenharia e operação

- **Não havia nenhum teste automatizado.** Esta entrega adiciona `tests/` (15 testes, `pytest`).
- Há helpers duplicados (seis versões de "SE ± n", várias de `_read_csv`/`_norm_mun`). Consolidar em `etl/`.
- Os scripts `.bat` procuram nomes como `lacen_builder_integrado_total(18).py`: renomear e versionar só os oficiais.
- Artefatos CSV/Parquet versionados no git crescem a cada carga. Considerar publicar em storage com manifesto (hash + SE) e versionar só o manifesto.
- Falta CI: um workflow simples (`pytest` + `python -m compileall`) pegaria regressões como a do §7.1.

---

## 12. O que foi implementado nesta entrega

| Mudança | Arquivos |
|---------|----------|
| `shift_se`/`semanas_no_ano` corretos para anos ISO de 52/53 SE; as 8 implementações locais passam a delegar para eles | `etl/epi_week.py`, `lacen_semana_maturacao.py`, `lacen_briefing_epi.py`, `lacen_agente_ve.py`, `ml/mirror_dw.py`, `ml/models.py`, `gerar_confirmacao_emergencia.py`, `lacen_integracao_final_only.py`, `lacen_builder_integrado_total.py` |
| Sinais CRÍTICA entram no alerta (ordem CRÍTICA → ALTA → MODERADA), com rótulo "CRÍTICA" e cor de destaque no HTML | `lacen_alerta_estrategico.py` |
| Lacunas GAL×SINAN suprimidas quando o SINAN não tem notificações na SE analisada, com nota explicativa no alerta | `lacen_alerta_estrategico.py` |
| QA com checagens reais + itens `SINAN_COBERTURA`, `POSITIVIDADE_PLAUSIVEL`, linguagem de surto e redundância | `lacen_alerta_estrategico.py` |
| O envio do Alerta Estratégico é bloqueado com QA crítico em FALHA (código de saída 2); `--forcar-envio` só depois de revisão humana | `scripts/enviar_relatorio_cievs.py` |
| Detecção de anomalias v2 (Poisson/binomial, calendário completo, base sem a SE, últimas 4 SE) | `ml/anomalias.py`, `ml/models.py` |
| Predição S+2/S+3 sem o fator ×1,02/×1,04 | `lacen_analise_avancada.py` |
| "10,6 dias" (antes: "10,6 dia") | `lacen_alerta_estrategico.py` |
| Testes automatizados | `tests/` |

Como rodar os testes: `python -m pytest -q tests`

### Resultado do dry-run (SE 37/2026, dados versionados, sem envio)

O alerta regenerado está em `docs/exemplo_alerta_se37_pos_correcoes.md`, e o QA em `…_qa.txt`.
- Três sinais **CRÍTICA** que a versão anterior descartava agora encabeçam o alerta: Tangará da Serra·TB (43 vs. 13), Cuiabá·dengue (30 vs. 3) e Cáceres·HPV (54 vs. 0).
- A seção de lacunas mostra que o cruzamento não foi avaliado, porque o SINAN parou na SE 19/2026. Não há mais "INVESTIGAR LINKAGE" sem base.
- O QA marca `POSITIVIDADE_PLAUSIVEL: ATENÇÃO (8/1231)` e `SINAN_COBERTURA: ATENÇÃO`.

O dry-run também expôs dois problemas que **não** foram corrigidos aqui:
- **Cáceres·"papilomavirus humano hpv papiloma rus biologia molecular":** HPV é rastreio (não deveria entrar como sinal agudo) e o slug está corrompido. Isso confirma 1.3 e 3.2: a série principal precisa aplicar `conta_alerta_agudo` de `regras_agravo_gal.csv`.
- **CRÍTICA + ACOMPANHAR** (Tangará·TB): a regra "volume ≥ 40 sem positivos ⇒ ACOMPANHAR" em `_acao_padrao` é contraditória enquanto a positividade estiver quebrada (1.1), já que todo sinal tem 0 positivos. Revisar a regra depois da Fase 1.

## 13. Roteiro proposto

| Fase | Prazo sugerido | Itens | Dependência |
|------|----------------|-------|-------------|
| **1 — Dados de entrada** | 1–2 semanas | Classificador de resultado por campo (1.1) + denominador com liberados (1.2) + pendentes/completude real (5.1) + integração SINAN do DW com trava (1.4) + teste de carga (1.5) | Acesso DW; amostra rotulada pelo LACEN |
| **2 — Reprocessamento** | 2–4 semanas | Alvo pelo exame (3.1) e slug (3.2); SE do MS e âncora coleta (2.1–2.2); painel completo e retreino (4.1–4.4) | Fase 1; janela de reprocessamento histórico |
| **3 — Método e produto** | 1–2 meses | Base sazonal/Farrington + FDR + persistência + agregação regional (§6); matriz de prioridade (§7); produto único com QA (9.1); retroalimentação por `signal_id` (§10); CI | Validação VE/CIEVS |

**Validação sugerida antes de oficializar a v2:** rodar v1 e v2 em paralelo por 4 SE (`LACEN_ANOMALIA_METODO=legado` gera a v1) e fazer revisão cega dos sinais por um técnico da VE.

---

## 14. Fase 1 — o que já foi implementado (03/11/2026)

Feito sem acesso ao DW (VPN fora do ar); **validar na primeira execução com dados reais**.

| Item | Situação | Onde |
|------|----------|------|
| 1.1 Classificador de resultado por campo (Detectável, cruzes, campos com vários alvos) | Implementado; SQL e Python geram a mesma classe (teste com DuckDB) | `etl/resultado_gal.py`, `etl/dw_extract.py` |
| 1.2 Denominador = válidos (positivos + negativos); pendentes contados à parte | Implementado na série, na integração, na análise avançada, nos sinais e nas anomalias | `etl/build_weekly_from_gal.py`, `lacen_integracao_final_only.py` |
| 1.4 SINAN do DW na série semanal + aviso de defasagem | Implementado (agregação no DW por view; hepatite e SRAG passam a parear) | `etl/sinan_dw.py`, `etl/run_etl_dw.py` |
| 1.5 Carga suspeita (SE < 50% da mediana de 8 SE) | Implementado no relatório de validação do ETL | `etl/run_etl_dw.py` |
| 5.1 Completude medida por pendentes; proxy rotulado como estimativa | Implementado; "Pendentes: 0" do proxy deixa de ser publicado | `lacen_semana_maturacao.py`, `lacen_alerta_estrategico.py` |
| §10 "Confirmação" → "Persistência de sinais anteriores" | Renomeado no alerta e no QA | `lacen_alerta_estrategico.py` |

**Primeira execução com o DW de volta (checklist):**

1. Rodar `rodar_etl_dw.bat --skip-cievs` e abrir `saida_pipeline\validacao_etl_dw_ultimo.txt`: conferir `sinan_dw` (views agregadas e falhas), `sinan_se_max`, `sinan_atraso_se`, `carga_suspeita`.
2. Conferir a positividade estadual da SE: deve sair da faixa de ~0,6% para valores plausíveis por agravo. Se continuar baixa, rodar `diagnosticar_codigo_resultados_gal.py` e acrescentar os textos de resultado que faltam em `etl/resultado_gal.py`.
3. Se alguma `VW_SINAN_*` aparecer em `views_falha` por "colunas não identificadas", informar os nomes das colunas de data e município dessa view para ajuste de `pick_columns`.
4. **Reprocessar o histórico** com o classificador novo antes de comparar positividade e positivos com anos anteriores (canal endêmico, anomalias, ML).
