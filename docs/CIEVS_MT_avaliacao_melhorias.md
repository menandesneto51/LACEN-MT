# Avaliação CIEVS-MT — Radar LACEN SE 30/2026

**Documento avaliado:** `docs/SECRETARIA_ESTADO_SAUDE_CIEVS_MT.docx`  
**Cópia com logos:** `docs/CIEVS_MT_com_logos.docx`  
**Fonte do DOCX:** Downloads (`… &bull; CIEVS-MT.docx`, 31/08/2026) — nome original usava entidade HTML `&bull;` em vez de `•`.  
**Cruzamento:** `saida_pipeline/relatorio_cievs_ultimo.txt` (Radar SE30)  
**Data da revisão:** 2026-08-31

---

## Veredito geral

O DOCX já está bem alinhado ao papel de sala CIEVS: one-pager com responsáveis/prazos, sinais de atenção antes das tabelas longas, cuidado explícito de **não declarar surto**, estratificação por marcador (HBV/dengue), SIH como gravidade e lacunas GAL×SINAN.  
Os gaps críticos são **taxas/100 mil**, **cartões probabilidade × impacto × confiança**, **quantificação das lacunas GAL×SINAN** (já disponíveis no Radar) e **fechamento de campos `[requer dado]`** com o pipeline atual.

---

## Must (bloquear versão oficial / validação VE)

1. **Incluir taxas por 100 mil** nos blocos de demanda/positividade e no painel executivo (não só N absoluto). O Radar já calcula (ex.: HBV Juína ~49,6/100 mil; dengue estadual ~0,1/100 mil). Sem taxa, municípios grandes e pequenos ficam incomparáveis — o próprio texto já alerta isso nas internações.
2. **Inserir cartões de risco (probabilidade × impacto × confiança × veredito)** no início (após one-pager ou como coluna do painel). Fonte: bloco “Visão executiva · Cartões de risco” do Radar (dengue×Cuiabá, HBV×Cuiabá/Juína, TB×Cuiabá, etc.). O DOCX tem sinais e score sintético, mas não o formato CIEVS padrão.
3. **Preencher lacunas GAL×SINAN com volumes** (exames órfãos por município), em vez de `[requer dado nominal por município]`. Radar SE30 já lista Colíder, Boa Esperança do Norte, Nova Mutum, Paranaíta, Pontes e Lacerda com N de exames sem notificação — alinhar a lista do §7 (hoje: Lucas/VG/Sorriso/Cuiabá/Campinápolis, focada em dengue) ou declarar o critério (só dengue vs qualquer agravo).
4. **Fechar marcadores HBV e métodos dengue** (`HBsAg / anti-HBc / IgM`; `NS1 / PCR / IgM`) ou marcar explicitamente “indisponível no espelho DW nesta SE” — deixar `[requer dado]` sem status confunde priorização.
5. **Padronizar o KPI de TAT ≤48h** (DOCX cita 23%; Radar KPI ~36%). Uma única fonte de verdade no rodapé metodológico.
6. **Manter e destacar o disclaimer de não-surto** no parecer Juína×HBV (já presente — preservar em qualquer reescrita) e no cabeçalho da versão validada.

---

## Should (próxima SE / revisão VE)

1. **Comparação YoY ou mediana 8 SE** nos sinais principais (dengue +162%, HBV Juína), além do Δ vs SE−1 — especialmente com censura à direita de 4 SE.
2. **Taxas de internação /100 mil** no §6 (Canarana vs Cuiabá) — o texto já pede; falta o número.
3. **Óbitos (SIM)** como camada de gravidade quando o staging tiver cobertura — hoje só SIH/IndicaSUS.
4. **Recomendações por destinatário explícito** (CIEVS estadual · VE municipal · área técnica · LACEN · municípios vizinhos), espelhando R1–R7 com uma coluna “para quem”.
5. **Expandir siglas na 1ª ocorrência** (GAL, SINAN, SIH, TAT, SE) e evitar jargão de pipeline (`exame_sem_notif_semana`, `gal_sem_sinan`).
6. **Hierarquia tipográfica:** §9 “Recomendações” está quase vazio no corpo (só título + intro) — o conteúdo está na Tabela 1; duplicar 3–5 bullets legíveis ou mover a tabela para cima.
7. **Link do painel** apenas no rodapé (não no corpo), com SE de referência única e atraso DW explícito.

---

## Nice (polish)

1. Logos SES | CIEVS-MT | Rede CIEVS no cabeçalho — **feito** em `CIEVS_MT_com_logos.docx` via `scripts/inserir_logos_docx_cievs.py`.
2. Score municipal (§12) só após homologação CIEVS; até lá, rotular como **proposta**.
3. Bloco SRAG/queimadas: manter como lacuna declarada + prazo “próxima SE”, sem misturar com veredito lab-epi atual.
4. Tabela one-pager: coluna “Taxa/100 mil” e “Confiança (alta/média/baixa)”.
5. Espelhar barra de logos no HTML do e-mail Radar (`to_email_html`) — reforçado nesta entrega.

---

## Checklist rápido vs critérios do plano

| Critério | Status no DOCX |
|----------|----------------|
| Cabeçalho logos + SE clara | Logos na cópia com logos; SE 30/2026 ok |
| Sinais de atenção antes de tabelas longas | OK (§2 antes de demanda) |
| Cartões risco prob×impacto×confiança | Ausente (Must) |
| Recomendações por destinatário | Parcial (tabela R1–R7) |
| Lab só quando pertinente | OK (§10) |
| Taxas /100 mil | Ausente / pendente (Must) |
| Δ vs SE anterior | OK |
| GAL×SINAN quantificado | Parcial — lista sem N (Must) |
| SIH gravidade | OK; falta taxa |
| Linguagem simples | Boa; alguns `[requer dado]` e jargão residual |
| Não declarar surto | OK (parecer §11) |

---

## Arquivos desta entrega

| Caminho | Uso |
|---------|-----|
| `docs/SECRETARIA_ESTADO_SAUDE_CIEVS_MT.docx` | Original copiado (sem alteração de logos) |
| `docs/CIEVS_MT_com_logos.docx` | Versão com cabeçalho institucional |
| `docs/CIEVS_MT_avaliacao_melhorias.md` | Esta avaliação |
| `scripts/inserir_logos_docx_cievs.py` | Reprodutível |
| `assets/logos/*` | SES / CIEVS / Rede (já presentes no repo) |
