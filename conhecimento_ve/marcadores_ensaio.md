# Marcadores e metodologias de ensaio (Radar LACEN / CIEVS)

Documento de referência para o **agente de positividade por marcador** (`lacen_agente_marcadores.py`).  
Objetivo: evitar alertas falsos de “surto” a partir de IgG/soroprevalência e orientar a leitura laboratorial para a Vigilância Epidemiológica (VE).

Siglas (1ª ocorrência): GAL (Gerenciador de Ambiente Laboratorial), HBV (vírus da hepatite B), PCR (reação em cadeia da polimerase), DNA (ácido desoxirribonucleico), RNA (ácido ribonucleico), NS1 (antígeno não estrutural 1 da dengue), IgM / IgG (imunoglobulinas M e G).

## Fonte mestra (editável pela área técnica)

A classificação operacional vem da planilha versionada:

| Artefato | Uso |
|----------|-----|
| `conhecimento_ve/regras_agravo_gal.csv` | Fonte mestra lida pelo agente (git-diffável) — **1 linha por ensaio GAL** (`exame_gal_exato`) |
| `conhecimento_ve/regras_agravo_gal.xlsx` | Mesmo conteúdo + abas Agravos_GAL, Catalogo_Exames, Cobertura, Metadados |
| `conhecimento_ve/Positividade_Por_Agravo_GAL.xlsx` | Modelo conceitual (marcador alerta por agravo, SE30, cascata) |
| `scripts/gerar_regras_agravo_gal.py` | (Re)gera CSV/XLSX a partir do micro GAL + classificação MS |
| `scripts/validar_cobertura_regras_gal.py` | Assert 100% cobertura + casos-ouro MS |
| `saida_pipeline/cobertura_regras_gal.csv` | Relatório exame → classe / flags |

Colunas anti-ruído: `conta_alerta_agudo`, `conta_bortman`, `conta_positividade_agregada`, `validacao_ms`.  
Match no agente: **`exame_gal_exato`** (literal) → regex `padrao_exame` → fallback hardcoded.

**O que NÃO gera alerta epidêmico:** IgG isolada, anti-HBs, anti-HAV IgG, anti-HCV sem RNA, Chagas IgG, TSA/tipagem/ID bacteriana genérica, micológico de rotina, colinesterase.  
**O que gera sinal:** IgM aguda, NS1, HBsAg, anti-HBc IgM, BAAR/TRM-TB/cultura TB, PCR detectável, raiva+, varíola+, sarampo IgM/PCR.

Se o CSV estiver ausente, o agente usa o fallback hardcoded em `lacen_agente_marcadores.py`.

## Fonte de colunas (GAL micro)

Espelho típico em `saida_pipeline/staging_dw/vw_gal_micro_recent*`:

| Coluna | Uso |
|--------|-----|
| `Exame` | Nome do ensaio / alvo (ex.: `Hepatite B, HBsAg`) |
| `Metodologia` | Família técnica (PCR, quimioluminescência, cultura…) |
| `Agravo_Requisicao` / `Agravo_Gal` | Contexto do pedido |
| `Campo_Resultado_1`…`6` | Texto do laudo (Detectável / Reagente / Não Detectável…) |
| `Municipio_Residencia_Paciente` | Município para agregação |
| `Data_Coleta_dt` / `Data_Liberacao_dt` | Temporalidade |

**Não há ID de paciente** no extrato micro atual → deduplicação nominal bloqueada (LGPD / ausência de identificador). Ver `saida_pipeline/modelo_definitivo_pendencias.md`.

## Famílias de interpretação

### Hepatite B (HBV)

| Marcador (padrão no nome do exame) | Leitura para alerta precoce |
|------------------------------------|-----------------------------|
| **Anti-HBs** | Imunidade vacinal ou contato passado — **não** sinal de infecção aguda |
| **Anti-HBc Total** / perfil IgG-like | Contato passado / crônico possível — **não** sozinho = aguda |
| **Anti-HBc IgM** | Compatível com **infecção aguda** (ou reativação) — sinal ativo |
| **HBsAg** | Infecção ativa (aguda ou crônica) — sinal laboratorial ativo; exige clínica + notificação |
| **HBeAg** / **Anti-HBe** | Marcadores de replicação/fase — contextualizar com DNA e clínica |
| **HBV-DNA** (PCR quantitativo) | Presença/ausência do agente (molecular) — confirmatório de replicação |

Regra operacional: **não** elevar prioridade só com anti-HBs ou IgG/total sem IgM, HBsAg ou DNA.

### Molecular (geral)

PCR / RT-PCR / biologia molecular: trata-se **presença ou ausência** do agente quando o resultado é Detectável / Não Detectável. Positividade molecular ≠ incidência populacional, mas é **confirmação laboratorial** útil para a VE.

### Dengue / arboviroses

| Método | Leitura |
|--------|---------|
| NS1 / antígeno | Compatível com infecção recente/aguda |
| PCR / molecular | Confirmação de presença do vírus |
| IgM | Sugere infecção recente (janela) |
| IgG isolada | Soroprevalência / infecção passada — **não** alerta agudo isolado |

### Tuberculose

Cultura / GeneXpert / baciloscopia: positivos são sinais laboratoriais ativos; cruzar com SINAN (Sistema de Informação de Agravos de Notificação) e clínica.

## Classes usadas no código

- `nao_agudo_soroprevalencia` — IgG, anti-HBs, anti-HBc total sem IgM  
- `sinal_agudo_ou_ativo` — IgM anti-HBc, HBsAg, HBV-DNA detectável, NS1, PCR detectável, etc.  
- `molecular_presenca_ausencia` — ensaios moleculares (confirmatorios)  
- `indeterminado` — sem mapeamento seguro no nome do exame  

## Caveat institucional

Positividade laboratorial agregada **não declara surto nem epidemia**. O Radar LACEN emite sinal para investigação pela VE municipal/estadual e pelo CIEVS (Centro de Informações Estratégicas em Vigilância em Saúde).
