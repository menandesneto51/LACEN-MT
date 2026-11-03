# Radar LACEN: novas funcionalidades, indicadores e alerta somente do que é validado

**Complementa:** `docs/avaliacao_pipeline_alertas.md` (diagnóstico do pipeline)
**Data:** 03/11/2026

---

## 1. Princípio: o alerta publica só o que passou na validação

Até aqui, o alerta publicava qualquer anomalia que somasse pontos no escore de prioridade. Com isso, sinais de rastreio (HPV), de exposição pretérita (IgG) e picos isolados de uma única semana disputavam espaço com sinais epidemiológicos reais.

**Regra nova (implementada em `lacen_validacao_sinais.py`):** todo sinal candidato passa por um **portão de validação** e recebe um status:

| Status | Destino | Significado |
|--------|---------|-------------|
| **VALIDADO** | Alerta Estratégico | Atende a todos os critérios abaixo |
| **EM OBSERVAÇÃO** | Painel / triagem | Pode ser real, mas falta evidência (sem significância, sem corroboração…) |
| **DESCARTADO** | Só triagem | Não é sinal epidemiológico (dado ruim ou alvo não elegível) |

### Critérios, aplicados em ordem

| Código | Critério | Regra | Se falhar |
|--------|----------|-------|-----------|
| D1 | Qualidade da carga | Volume estadual da SE ≥ 50% da mediana das 8 SE anteriores | DESCARTADO |
| D2 | Alvo elegível | Classe do alvo em `conhecimento_ve/classe_alvo_alerta.csv`: IgG/avidez e diagnóstico assistencial/rastreio (HPV, culturas, TSA, resistência) nunca entram | DESCARTADO |
| D2b | Alvo classificado | Alvo sem classe definida | EM OBSERVAÇÃO |
| D3 | Positividade confiável | Sinal de positividade só entra se a positividade estadual for plausível (≥ 2% com n ≥ 500) | EM OBSERVAÇÃO |
| E1 | Significância | p < 0,01 (anomalias v2) ou severidade "alta" (v1) | EM OBSERVAÇÃO |
| E2 | Magnitude | Excesso ≥ 5 exames sobre a base (volume) ou ≥ 2 positivos (positividade) | EM OBSERVAÇÃO |
| C | Corroboração | Pelo menos uma: **persistência** (anomalia na SE anterior), **positivo laboratorial** (com positividade confiável) ou **vizinho** (município entre os 3 mais próximos com sinal do mesmo alvo) | EM OBSERVAÇÃO |
| C-crônico | Persistência obrigatória | Hepatites B/C, HIV, sífilis, hanseníase, Chagas crônica: o volume reflete seguimento clínico, então só entra se persistir por 2 SE | EM OBSERVAÇÃO |
| Imediata | Exceção | Agravo de notificação imediata (raiva, sarampo, rubéola, febre amarela, hantavirose, meningite, febre maculosa etc.) com ≥ 1 positivo (positividade confiável) entra direto | — |

**Lacunas GAL×SINAN** continuam com a validação própria: SINAN com notificações na SE e n ≥ 20.

### O que muda no alerta

- Cada sinal publicado mostra a linha **"Validação: …"** com os critérios atendidos e a corroboração (ex.: "significativo (p=2e-06); excesso de 27 exames sobre a base · corroborado por persistência (SE anterior)").
- Abaixo dos sinais aparece a **linha de triagem**: "N validados · N em observação no painel · N descartados (principais motivos…)".
- A **síntese executiva** é escrita a partir dos sinais validados. Antes, o texto afirmava sempre que "não foi identificada evidência laboratorial suficiente…", fosse qual fosse o dado. Sem nenhum sinal validado, a síntese diz isso explicitamente.
- O **destaque territorial** (Juína) só aparece se houver sinal validado no município.
- O **QA** ganha `SINAIS_VALIDADOS` (FALHA crítica se algum sinal não validado for publicado), o que bloqueia o envio, e `CARGA_SE`.
- A triagem completa vai para `saida_pipeline/alerta_triagem_sinais.csv` (sinal, classe, status, critérios, corroborações e motivos), para o painel e para auditoria.

### Resultado na SE 36/2026 (alerta SE 37, dry-run com dados versionados)

Arquivos: `docs/exemplo_alerta_se37_pos_correcoes.md` e `docs/exemplo_triagem_sinais_se37.csv`.

| Sinal candidato | Status | Motivo / corroboração |
|-----------------|--------|------------------------|
| Cuiabá · dengue (30 vs. base 15,5) | **VALIDADO** | p = 0,0007; excesso de 14; vizinho Várzea Grande com sinal |
| Várzea Grande · dengue (50 vs. 31,2) | **VALIDADO** | p = 0,0012; excesso de 19; vizinho Cuiabá com sinal |
| Juína · hepatite B (49 vs. 17,6) | **VALIDADO** → destaque territorial | p = 6e-10; persistência por 2 SE (crônico) |
| Tangará da Serra · TB (43 vs. 13) | Em observação | Sem persistência, positivo ou vizinho |
| Alta Floresta · TB | Em observação | Sem corroboração |
| Cáceres · HPV (54) | Descartado | Rastreio/assistencial |
| Sinop · culturas/TSA bacteriano (2) | Descartado | Diagnóstico assistencial |

O alerta passou de 5 para 2 sinais publicados + destaque de Juína. A síntese agora descreve o que foi validado: dengue com excesso simultâneo nos dois municípios vizinhos da Baixada Cuiabana, um padrão regional mais relevante do que dois sinais soltos. Tangará·TB, que aparecia como CRÍTICA, fica no painel até persistir ou ser corroborado.

Nesta mesma rodada, corrigi o **destaque de Juína**, que lia a SE do alerta (37, semana em curso: "0 exames") em vez da SE analisada (36: 49 exames). Também ajustei os **encaminhamentos**: quando nada é validado, deixam de pedir "investigar nos municípios citados" e informam que não há acionamento municipal.

### Parâmetros (ajustáveis sem mexer no código)

`LACEN_VALID_P_MAX` (0,01) · `LACEN_VALID_MIN_EXCESSO` (5) · `LACEN_VALID_CARGA_MIN` (0,5) · a classe de cada alvo é editável em `conhecimento_ve/classe_alvo_alerta.csv`. **A lista de agravos de notificação imediata deve ser validada pela VE** contra a lista nacional vigente.

---

## 2. Novas funcionalidades propostas

Ordenadas por impacto sobre a relevância do alerta.

| # | Funcionalidade | Por quê | Esforço | Depende de |
|---|----------------|---------|---------|-----------|
| F1 | **Ciclo de vida do sinal** (`signal_id` estável): NOVO → PERSISTENTE → ESCALADO → EM DECLÍNIO → ENCERRADO. O alerta publica só **novos e escalados**. Os persistentes sem mudança aparecem numa linha-resumo. | Evita repetir o mesmo sinal toda semana e mostra o que mudou | Médio | Histórico de sinais (`alerta_historico.csv`) |
| F2 | **Retroalimentação da VE** por `signal_id`: confirmado / descartado / em investigação / sem retorno, com data. Formulário simples ou planilha compartilhada lida pelo ETL. | Mede o valor preditivo positivo (VPP) real e calibra os limiares do portão com evidência | Médio | Processo com a VE |
| F3 | **Alerta imediato diário** para agravos de notificação imediata com positivo (raiva, sarampo, febre amarela…), separado do boletim semanal. | O ciclo semanal atrasa até 7 dias um evento que exige resposta em 24 h | Baixo | Classificador de resultado confiável (Fase 1) |
| F4 | **Agregação regional/cluster**: municípios vizinhos com sinal do mesmo alvo viram **um** sinal regional (Região de Saúde), com contagem conjunta. | Um cluster é mais relevante do que N sinais municipais soltos | Médio | `municipio_vizinhos.csv` (existe) + tabela de Regiões de Saúde |
| F5 | **Base sazonal** (mesma janela de SE em 3–5 anos; Farrington flexível) para arboviroses e respiratórios. | A base de 8 SE marca toda subida sazonal como anomalia | Médio | Série com pelo menos 3 anos (existe desde 2010) |
| F6 | **Painel de triagem** com `alerta_triagem_sinais.csv`: filtros por status e motivo, e evolução dos sinais em observação. | Dá transparência ao que ficou fora do alerta e por quê | Baixo | — |
| F7 | **"O que mudou desde a última edição"**: bloco automático de 3 linhas (sinais novos, encerrados, escalados). | É a pergunta nº 1 do gestor | Baixo | F1 |
| F8 | **Primeira detecção** de agente no município em 52 SE (ex.: primeiro positivo de Oropouche) como sinal próprio. | Introdução de agente é um insight de alto valor que não aparece como "excesso" | Baixo | Fase 1 |

---

## 3. Novos indicadores

### 3.1 Rede laboratorial (operação)

| Indicador | Fórmula | Uso | Disponível? |
|-----------|---------|-----|-------------|
| Oportunidade por agravo | P50/P90 de (liberação − recebimento), por agravo e município | TAT geral esconde agravos críticos lentos | Sim (datas no GAL) |
| % dentro do prazo-alvo | Liberados no prazo do agravo / liberados (ex.: imediata ≤ 48 h) | Meta operacional por agravo | Sim, com tabela de prazos |
| Pendentes envelhecidos | Exames sem liberação há mais de 7 dias | Backlog acionável | Sim (`Status_Exame`) |
| Taxa de rejeição/recoleta | Amostras rejeitadas / recebidas, por município de origem | Qualidade pré-analítica e capacitação | Verificar campo no GAL |
| % inconclusivo/indeterminado | Indeterminados / liberados, por exame | Qualidade analítica e necessidade de 2ª amostra | Após o classificador (Fase 1) |

### 3.2 Vigilância (epidemiologia)

| Indicador | Fórmula | Uso | Disponível? |
|-----------|---------|-----|-------------|
| Taxa de testagem / 100 mil | Exames do agravo / população × 100 mil | Compara municípios de portes diferentes | Sim (população existe) |
| Razão observado/esperado (O/E) | Observado / esperado sazonal (F5) | Uma métrica única e legível de excesso | Após F5 |
| Positividade por marcador agudo | Positivos/(positivos+negativos) em IgM, NS1, PCR, TRM | Separa infecção ativa de seguimento | Após a Fase 1 |
| Sorotipo/linhagem circulante | Proporção de DENV-1..4 nos PCR tipados | Mudança de sorotipo é preditora de epidemia | Verificar campo no GAL |
| Cobertura do linkage GAL→SINAN | % de positivos com notificação em até 14 dias | Mede a integração lab–VE (substitui a "lacuna" crua) | Após a integração SINAN |
| Tempo positivo → notificação | Mediana (notificação − liberação positiva) | Oportunidade da vigilância | Após a integração SINAN |
| Silêncio relevante | Município com 0 exames do agravo em 4 SE **quando o esperado sazonal é ≥ 3** | Silêncio que importa, não ausência de demanda | Após F5 |
| Gravidade associada | Internações SIH/óbitos SIM por CID compatível / 100 mil, com a defasagem declarada | Contexto de impacto para priorizar | Parcial (SIH com defasagem) |

---

## 4. Insights mais relevantes: o que vale priorizar no texto

Ordem de valor para o gestor:

1. **Agravo imediato com positivo** (raiva, sarampo, febre amarela…). Uma linha, no topo, com a ação e o prazo.
2. **Introdução de agente** em município sem detecção em 52 SE (F8).
3. **Cluster regional validado** (F4): N municípios vizinhos, mesmo agravo, excesso conjunto.
4. **Escalada** de um sinal persistente (F1): ex. de volume para positividade, ou de 1 para 3 municípios.
5. **Mudança de sorotipo** de dengue.
6. **Gargalo operacional que afeta a vigilância**: pendentes envelhecidos ou TAT acima do prazo em agravo imediato.
7. Excesso de volume validado sem positividade. É útil, mas o texto deve tratá-lo como **demanda**, não como transmissão.

Não devem ser publicados no alerta (só no painel): sinais em observação, quedas frágeis, IgG, rastreio, diagnóstico assistencial, lacunas sem SINAN e previsões sem validação de erro.

---

## 5. Ordem de implementação sugerida

1. **Feito agora:** portão de validação + triagem + síntese baseada em dados + QA `SINAIS_VALIDADOS`.
2. **Fase 1** (dados de entrada, ver a avaliação §13): classificador de resultado, SINAN, completude. Isso destrava D3, F3 e F8 e os indicadores de positividade.
3. F1 (ciclo de vida) + F7 ("o que mudou") + F6 (painel de triagem).
4. F5 (base sazonal) + F4 (cluster regional) + O/E e silêncio relevante.
5. F2 (retroalimentação), para recalibrar os limiares do portão com VPP observado.
