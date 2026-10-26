# Avaliação técnica — estabilidade, precisão e confiabilidade

**Escopo:** LACEN-MT (pipeline ETL + ML + dashboard + relatórios CIEVS) e CIEVS-IA (consulta documental)
**Data:** 2026-10-26 · **Base avaliada:** branch `main` (último commit de dados: 2026-09-11, SE36/37)
**Método:** leitura de código, execução de verificações sobre os artefatos versionados em `saida_pipeline/`, testes do CIEVS-IA.

---

## 1. Resumo executivo

O sistema já tem uma base boa: há rastreabilidade do ETL (`validacao_etl_dw_ultimo.txt`), backtest temporal, cuidado explícito com "não declarar surto", envio de alertas com aprovação humana e segredos fora do código. Os riscos principais estão em **quatro pontos que afetam diretamente a precisão do que é comunicado ao CIEVS**:

| # | Problema | Impacto | Prioridade |
|---|----------|---------|-----------|
| 1 | Semana epidemiológica calculada como **ISO (seg–dom)**, não pelo calendário MS/SINAN (dom–sáb) | Em 2026, o rótulo "SE" fica **1 semana à frente** do SINAN em 6 de cada 7 dias; cruzamento GAL×SINAN desalinhado | **P0** |
| 2 | Semana corrente **incompleta** entra nas séries e nos modelos | Gera falsas "quedas atípicas" e falsos "silêncios" na última SE | **P0** |
| 3 | "Último snapshot" por município×agravo usa a **última linha com dado**, mesmo que seja de 2024/2025 | Alertas e anomalias "atuais" incluem semanas antigas | **P0** |
| 4 | Limiar dos modelos escolhido **no próprio conjunto de teste**; modelos com AUC < 0,5 continuam em uso | Métricas de backtest otimistas; alertas sem poder preditivo em produção | **P1** |

A estabilidade operacional (falhas silenciosas, ausência de testes, dados versionados no git) é o segundo bloco, detalhado na seção 3.

---

## 2. Precisão epidemiológica (P0/P1)

### 2.1 Semana epidemiológica ISO ≠ SE do Ministério da Saúde — **P0**

**Evidência:** `etl/epi_week.py` define a convenção como `datetime.isocalendar()` (segunda a domingo). O mesmo cálculo está **replicado em ~10 lugares** (`lacen_builder_integrado_total.py:460,541,631`, `lacen_analysis_pipeline_completo_corrigido.py:434,721`, `etl/build_weekly_from_gal.py:142`, `etl/dw_extract.py:419,750,906`, `lacen_relatorio_cievs.py:462`, `lacen_agente_marcadores.py:587`, `lacen_semana_maturacao.py:100`, `reparar_sim_weekly.py:89`), inclusive no SQL (`DATEPART(iso_week, …)`).

A SE do MS/SINAN vai de **domingo a sábado**, e a SE 1 é a semana que contém mais dias de janeiro. Verificação feita:

| Data | ISO | SE MS |
|------|-----|-------|
| 2026-09-05 (sáb) | 2026-W36 | **SE 35** |
| 2026-09-06 (dom) | 2026-W36 | SE 36 |
| 2026-09-11 (sex) | 2026-W37 | **SE 36** |
| 2026-10-26 (seg) | 2026-W44 | **SE 43** |

- Em 2026 a SE MS 1 começa em 04/01/2026 (2025 tem SE 53). Por isso **todo o ano de 2026 está deslocado em +1** no rótulo, exceto aos domingos.
- Entre 2024 e 2026, **38%** dos dias caem em semanas diferentes nas duas convenções.
- Consequência prática: o "Radar SE36" corresponde à **SE 35** do SINAN; o cruzamento GAL×SINAN (que usa `SEM_NOT`/`SEM_PRI` no padrão MS) compara semanas diferentes, o que infla "exames sem notificação" e divergências.

**Proposta:**
1. Implementar `epi_week_ms(date) -> (ano_se, se)` em `etl/epi_week.py` (domingo–sábado, regra do 4º dia de janeiro), com testes unitários usando o calendário oficial do SINAN para 2024–2027.
2. Substituir **todas** as cópias por chamadas a esse módulo (no SQL: calcular a data e converter em Python, ou uma tabela-calendário `dim_se` no DW).
3. Reprocessar o histórico e registrar a mudança no rodapé metodológico ("a partir de SE xx/2026 as semanas seguem o calendário MS").

### 2.2 Semana incompleta tratada como semana real — **P0**

**Evidência:** `integrated_weekly_surveillance.csv` contém 2026-W37 com 618 exames (≈ metade das semanas anteriores, ~1.300). Em `ml_anomalias.csv` o maior bloco é `2026-W37 / queda_atipica` (43 linhas), puro efeito de semana parcial. A própria validação mostra `atraso_dias: 5` na SE usada, ou seja, também a SE "fechada" ainda está em maturação (resultados liberados depois).

**Proposta:**
- Cortar as séries em `semana_completa_mais_recente()` **antes** de gerar features (não só no relatório).
- Usar `lacen_semana_maturacao.py` de fato: aplicar fator de maturação/nowcasting (ex.: proporção histórica liberada até D+n) ou marcar as últimas 1–2 SE como "provisórias" e **excluí-las das regras de queda/silêncio**.
- Exibir no dashboard e no e-mail: "SE xx provisória — N% dos resultados esperados".

### 2.3 Snapshot "atual" mistura semanas antigas — **P0**

**Evidência:** `ml/features.py:175` — `latest_week_snapshot` faz `groupby(["municipio","target"]).tail(1)`. Resultado: `ml_silencio_predito.csv` (6.101 linhas) tem previsões cuja "última semana" vai de **2024-W38 a 2026-W37**; `ml_anomalias.csv` (659 linhas) tem anomalias de 2025 apresentadas junto com as atuais.

**Proposta:** o snapshot deve ser **a SE de referência para todos** os pares município×agravo, preenchendo com zero (e `semanas_sem_exame`) quem não teve exame. Anomalias/alertas de semanas anteriores à SE de referência devem ser descartados ou ir para um histórico separado.

### 2.4 Detector de anomalias sensível demais — **P1**

**Evidência:** `ml/models.py:98` marca anomalia quando `|atual − MA8| / MA8 ≥ 0,5`, sem considerar variância nem volume. 235 das 430 anomalias de `tests` têm baseline < 3 exames/semana (ex.: de 2 para 1 = "queda atípica alta").

**Proposta:** trocar por teste de contagem — limite superior/inferior Poisson ou binomial negativa sobre a MA8 (ou EARS C2/C3, Farrington simplificado), com **mínimo de eventos** (ex.: baseline ≥ 5) e correção para múltiplas comparações (há ~milhares de pares município×agravo por semana). O canal endêmico de Bortman (`ml/canal_endemico_bortman.py`) já existe e pode ser a referência para os agravos com histórico suficiente.

### 2.5 Avaliação dos modelos otimista — **P1**

**Evidência (`ml/train.py`):**
- Linha 246: `_best_threshold(yte, prob)` escolhe o limiar **no conjunto de teste** e as métricas (precision, recall, F1) são reportadas nesse mesmo conjunto → vazamento.
- `ml_backtest_summary.csv`: `risco/familia:respiratorio` tem **AUC 0,12** (pior que aleatório) e `hepatite` precisão 3,7%; mesmo assim os bundles são gravados e usados em `ml/models.py:260` sem nenhum filtro de qualidade.
- O modelo final é o treinado em 80% das semanas; as 21 semanas mais recentes (as mais relevantes) não entram no modelo de produção.
- `y_alerta` é derivado das regras do próprio pipeline: o modelo aprende a reproduzir a regra. Vale confirmar se as features não incluem os mesmos componentes da regra (risco de circularidade).

**Proposta:**
1. Divisão em três blocos temporais: treino → validação (escolha de limiar e calibração) → teste (só métricas). Ou *rolling-origin backtest* com várias janelas.
2. **Portão de qualidade:** só publicar modelo por família se AUC ≥ 0,65 e n positivos ≥ 30 no teste; caso contrário, cair para o modelo global ou para a regra, e mostrar "modelo não validado" no painel.
3. Após validar, re-treinar com todas as semanas para produção, mantendo o limiar escolhido na validação.
4. Registrar no `meta.json` versão dos dados (hash), data de corte e métricas — e exibir no dashboard.

### 2.6 Positividade agregada pouco informativa — **P2**

A positividade semanal estadual está em 0,3–0,8% (ex.: SE36: 8 positivos em 1.231 exames). Isso indica que o denominador mistura exames de triagem/controle com exames diagnósticos. A tabela `conhecimento_ve/regras_agravo_gal.csv` (`conta_positividade_agregada`, `classe`, `marcador`) já tem a estrutura certa — o ganho de precisão vem de **calcular positividade por marcador/método** (NS1, IgM, PCR, HBsAg…) e só agregar o que a regra marca como comparável.

---

## 3. Estabilidade e confiabilidade operacional

### 3.1 Falhas silenciosas no pipeline — **P0**

- `etl/run_etl_dw.py:44` — `_run(..., check=False)` por padrão: se `lacen_integracao_final_only.py`, `gerar_indicadores_*.py` ou `ml.run_ml_pipeline` falharem, o pipeline **continua** e os arquivos antigos em `saida_pipeline/` são publicados como se fossem novos. O código de saída fica só em `passos`.
- 206 blocos `except`/`except Exception` no projeto, 65 deles com `pass`/`continue`/`return None`/DataFrame vazio logo em seguida. Erros de leitura viram "sem dados", que o dashboard mostra como "nenhum alerta".
- Só 1 arquivo usa `logging`; há 171 `print()`.

**Proposta:**
- Etapas críticas (`integracao_final`, `ml`) com `check=True`; ao falhar, **não** publicar artefatos e escrever `status: FALHA` no arquivo de validação.
- Escrever saídas em diretório temporário e trocar de forma atômica (`saida_pipeline/.tmp_<run>` → `os.replace`) ao final de um run bem-sucedido.
- Gravar `run_manifest.json` (id do run, SE MS, hashes dos insumos, linhas por saída, versão do código/modelo) e fazer o dashboard **ler o manifesto** e mostrar a data e o status do último run.
- Substituir `print` por `logging` com arquivo rotativo em `logs/` e revisar os `except` que devolvem vazio: ou propagar, ou registrar `WARNING` com o nome do arquivo.

### 3.2 Validação de dados (contratos) — **P1**

Não há verificação de esquema/limites entre as etapas. Proposta: um módulo `etl/checks.py` (pandas puro ou `pandera`) executado ao final do ETL com regras como:
- colunas obrigatórias e tipos em `integrated_weekly_surveillance`;
- `0 ≤ positives ≤ tests`; `epi_week` em 1–53; município ∈ 141 códigos IBGE de MT;
- volume da SE de referência entre 50% e 200% da mediana de 8 SE (senão: `ALERTA_QUALIDADE`, e o envio CIEVS fica bloqueado até revisão);
- sem duplicatas em (ano_se, se, município, agravo).

### 3.3 Ausência de testes automatizados e CI — **P1**

LACEN-MT não tem nenhum teste e nenhum workflow em `.github/`. Proposta mínima (1–2 dias):
1. `tests/test_epi_week.py` — calendário MS 2024–2027 (protege o item 2.1).
2. `tests/test_checks.py` — contratos do item 3.2 sobre os CSV versionados.
3. `tests/test_ml_split.py` — garante que o limiar não é escolhido no teste e que o snapshot usa a SE de referência.
4. Smoke test do dashboard: importar o módulo e carregar cada aba com os dados versionados (`streamlit.testing.v1.AppTest`).
5. GitHub Actions rodando `pytest` + `python -m compileall` a cada push.

### 3.4 Dependências sem versão fixa — **P1**

`requirements.txt` usa apenas `>=` (pandas, numpy, streamlit, scikit-learn…). Os `.joblib` em `ml/models_store/` dependem da versão exata do scikit-learn; um upgrade automático no Streamlit Cloud pode quebrar o `joblib.load` ou mudar resultados. Proposta: `requirements.lock` (`pip freeze` ou `pip-tools`) usado no Cloud e no servidor, e gravar `sklearn.__version__` no `meta.json`, conferindo ao carregar.

### 3.5 Dados versionados no git — **P2**

`saida_pipeline/` é publicado via commit (41 commits só de dados; pack de 43 MB, repositório de 136 MB). Isso faz o histórico crescer a cada SE e mistura código com dados. Proposta: manter no git apenas amostras/fixtures e publicar os artefatos do painel em armazenamento separado (bucket/Release do GitHub/branch `data` órfã), ou ao menos só os `.parquet` (hoje há CSV + Parquet duplicados).

### 3.6 Atualização do painel — **P2**

- `@st.cache_data` sem `ttl` (`lacen_dashboard_integrado_total.py:553,566,1109`): o Cloud só vê dados novos após reboot manual. Usar `ttl` ou chave de cache pelo `mtime`/hash do manifesto.
- Última atualização dos dados: **2026-09-11** (≈ 6 semanas atrás na data desta avaliação). O painel deveria exibir um banner vermelho quando `hoje − data_do_run > 10 dias`.

### 3.7 Código monolítico e duplicado — **P2**

`lacen_relatorio_cievs.py` (5.616 linhas), `lacen_dashboard_integrado_total.py` (4.129), `lacen_briefing_epi.py` (3.290); 17 scripts `.bat` com fluxos parecidos (`rodar_lacen_sistema_completo*.bat`, `instalar_*`). Proposta incremental: extrair funções comuns (SE, leitura de saídas, nomes de municípios, população/taxa por 100 mil) para um pacote `lacen/` e deixar um único ponto de entrada (`python -m etl.run_etl_dw`) com um `.bat` fino.

### 3.8 Privacidade / LGPD — **P1**

- Não foram encontradas colunas nominais (nome, CPF, CNS) nos CSV versionados. 
- Porém o painel é **público por padrão** (`STREAMLIT_CLOUD.md`) e publica contagens por município×agravo×semana, inclusive agravos sensíveis (HIV/aids, sífilis, violência) em municípios pequenos — células com 1–3 casos podem permitir reidentificação.
- Proposta: tornar o login obrigatório por padrão (`LACEN_REQUIRE_AUTH=1`) ou, na versão pública, suprimir células < 5 e agregar agravos sensíveis por região de saúde.

---

## 4. CIEVS-IA (repositório `cievs-ia`)

Testes: 7/7 passam. Achados:

| # | Problema | Evidência | Proposta |
|---|----------|-----------|----------|
| 1 | **PDFs principais não abrem (404)** | Arquivos no git com nome corrompido (`Guia de vigil├óncia…`, `…diagn├│stico…`, ZIP extraído em cp437). O índice guarda o nome correto → `GET /api/v2/documents/3/pdf` e `/4/pdf` retornam 404 (Guia de Vigilância, 456 p., e Protocolo de raiva) | Renomear os arquivos para UTF-8 e adicionar teste que abre todos os PDFs do catálogo |
| 2 | Índice não detecta arquivo alterado/removido | `ingest()` pula pelo nome; não há gatilhos de DELETE/UPDATE no FTS5 | Comparar `sha256` por caminho; remover documentos ausentes; triggers `AFTER DELETE/UPDATE` no `passage_fts` |
| 3 | Documento **histórico/vencido** aparece no topo | Busca "raiva": as 3 primeiras evidências são de nota de 2017 (HISTÓRICO) | Penalizar `bm25` por status (ex.: ×1,5 para HISTÓRICO/VENCIDO) e diversificar (máx. 2 trechos por documento) |
| 4 | Filtros aplicados depois do `LIMIT` | `/api/v2/search` busca 25 e filtra depois → filtro pode zerar resultados existentes | Aplicar `status`/`arquivo` no `WHERE` do SQL |
| 5 | Duplicatas do manual LACEN indexadas duas vezes | 2 PDFs `VENCIDO` com 51 páginas cada | Deduplicar por similaridade de texto, não só `sha256` |
| 6 | Indexação na importação do módulo | `app/main.py` chama `_ingest_documentos()` no import → início lento e testes dependentes do disco | Mover para evento `lifespan` e usar índice temporário nos testes |
| 7 | Comparação de token não constante | `request.headers.get(...) != token` | `hmac.compare_digest` |
| 8 | API `fitz` depreciada | aviso do PyMuPDF | `import pymupdf` |

---

## 5. Plano sugerido

| Fase | Duração | Itens |
|------|---------|-------|
| **1 — Correção de precisão** | 1–2 semanas | 2.1 (SE MS + testes), 2.2 (corte de semana incompleta), 2.3 (snapshot na SE de referência), 3.1 (falha interrompe publicação), CIEVS-IA #1 |
| **2 — Confiabilidade** | 2–3 semanas | 2.5 (split treino/validação/teste + portão de qualidade), 3.2 (contratos), 3.3 (testes + CI), 3.4 (lock de dependências), 3.6 (banner de dados desatualizados), 3.8 (auth por padrão) |
| **3 — Qualidade analítica** | 3–4 semanas | 2.4 (detector por contagem/Bortman), 2.6 (positividade por marcador), nowcasting da SE provisória, CIEVS-IA #2–#5 |
| **4 — Manutenção** | contínuo | 3.5 (dados fora do git), 3.7 (modularização), logging estruturado |

**Indicadores para acompanhar a melhoria:** % de SE com `status: OK` no manifesto; atraso médio do painel (dias); taxa de alertas confirmados (`alerta_historico.csv`) por família; nº de anomalias por SE (esperado cair de ~60–80 para um número que a equipe consiga investigar); AUC e precisão@20 em teste realmente fora da amostra.
