#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de parecer de Vigilância Epidemiológica (VE) — LACEN-MT / CIEVS.

Ingere agregados do briefing epidemiológico (Top 10), recupera trechos do
pacote local alinhado ao Guia de Vigilância MS (RAG-lite por palavras-chave)
e emite parecer institucional em Markdown/HTML/CSV.

Regras de ouro:
  - NÃO declarar "há surto" sem confrontar Observado × critérios do Guia.
  - NÃO inventar números (mesmo padrão de lacen_assistente.py).
  - LLM opcional só reescreve texto já calcado (LACEN_LLM_API_KEY / OPENAI_API_KEY).

Uso:
  from lacen_agente_ve import gerar_parecer_ve
  p = gerar_parecer_ve("saida_pipeline")
  python lacen_agente_ve.py
  python scripts/gerar_relatorio_ve.py --enviar
"""
from __future__ import annotations

import csv
import html
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from lacen_briefing_epi import (
    BriefingEpi,
    _is_hepatite,
    gerar_briefing_epi,
)

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"
KNOW_DIR = ROOT / "conhecimento_ve"
EXCERTOS_DIR = KNOW_DIR / "excertos"

REL_MD = "relatorio_ve_inteligente.md"
REL_HTML = "relatorio_ve_inteligente.html"
REL_CSV = "relatorio_ve_acoes.csv"
REL_JSON = "relatorio_ve_inteligente_meta.json"

# Fontes públicas preferidas (cache local se download ok)
_FONTES_CACHE: list[dict[str, str]] = [
    {
        "id": "hepatites_ms",
        "url": "https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/h/hepatites-virais",
        "familia": "hepatite",
        "arquivo": "hepatites_virais_ms.html.txt",
    },
    {
        "id": "tb_ms",
        "url": "https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/t/tuberculose",
        "familia": "tuberculose",
        "arquivo": "tuberculose_ms.html.txt",
    },
    {
        "id": "dengue_ms",
        "url": "https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/d/dengue",
        "familia": "dengue",
        "arquivo": "dengue_ms.html.txt",
    },
    {
        "id": "meningite_ms",
        "url": "https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/m/meningite",
        "familia": "meningite",
        "arquivo": "meningite_ms.html.txt",
    },
]

_FAMILIA_KW: dict[str, tuple[str, ...]] = {
    "hepatite": ("hepatite", "hbv", "hcv", "hbsag", "anti-hbc"),
    "tuberculose": ("tuberculose", "tb", "baciloscopia", "genexpert"),
    "dengue": ("dengue", "arbovirose", "chikungunya", "zika"),
    "meningite": ("meningite", "neisseria", "meningoc"),
    "igg": ("igg", "soroprevalência", "soroprevalencia", "toxoplasmose", "citomegalov"),
    "surto": ("surto", "epidemia", "cluster", "investigação", "investigacao", "definição de caso"),
}


def _now_local() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _pct_str(x: Any) -> str:
    if x is None or x == "":
        return "—"
    if isinstance(x, str) and "%" in x:
        return x
    try:
        v = float(x)
        if v <= 1.0:
            return f"{100.0 * v:.1f}%"
        return f"{v:.1f}%"
    except (TypeError, ValueError):
        return str(x)


def _intish(x: Any) -> str:
    try:
        return str(int(round(float(x))))
    except (TypeError, ValueError):
        return str(x) if x not in (None, "") else "—"


def _familia_de_target(target: str) -> str:
    t = (target or "").casefold()
    if "hepatite" in t or "hbv" in t or "hcv" in t:
        return "hepatite"
    if "tuberculose" in t or t == "tb" or t.startswith("tb_"):
        return "tuberculose"
    if "dengue" in t or "chikungunya" in t or "zika" in t or "oropouche" in t:
        return "dengue"
    if "meningite" in t:
        return "meningite"
    if "igg" in t:
        return "igg"
    return "surto"


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tentar_cachear_fontes_ms(
    know_dir: Path | str = KNOW_DIR,
    *,
    timeout: int = 20,
) -> list[dict[str, str]]:
    """
    Tenta baixar páginas públicas do MS e gravar excertos curtos (≤12k chars).
    Falha silenciosa → usa notificaveis_resumo.md.
    """
    know = Path(know_dir)
    ex = know / "excertos"
    ex.mkdir(parents=True, exist_ok=True)
    resultados: list[dict[str, str]] = []
    for fonte in _FONTES_CACHE:
        dest = ex / fonte["arquivo"]
        status = "cache_existente" if dest.exists() and dest.stat().st_size > 200 else "pendente"
        if status == "cache_existente":
            resultados.append({**fonte, "status": status, "path": str(dest)})
            continue
        try:
            req = urllib.request.Request(
                fonte["url"],
                headers={"User-Agent": "LACEN-MT-CIEVS-VE-Agent/1.0 (vigilancia; contato institucional)"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            texto = _strip_html(raw)[:12000]
            if len(texto) < 200:
                raise ValueError("conteúdo muito curto")
            dest.write_text(
                f"Fonte: {fonte['url']}\nBaixado em: {_now_local()}\n\n{texto}\n",
                encoding="utf-8",
            )
            resultados.append({**fonte, "status": "baixado", "path": str(dest)})
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            resultados.append({**fonte, "status": f"falha:{exc}", "path": ""})
    return resultados


def _carregar_docs_conhecimento(know_dir: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for path in sorted(know_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text.strip()) < 40:
            continue
        docs.append(
            {
                "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "nome": path.name,
                "texto": text,
            }
        )
    return docs


def recuperar_trechos(
    familias: Sequence[str],
    know_dir: Path | str = KNOW_DIR,
    *,
    max_trechos: int = 6,
    max_chars: int = 900,
) -> list[dict[str, str]]:
    """RAG-lite: casa seções/parágrafos por família de agravo + conceitos de surto."""
    know = Path(know_dir)
    docs = _carregar_docs_conhecimento(know)
    want = {f.casefold() for f in familias if f} | {"surto"}
    keywords: list[str] = []
    for fam in want:
        keywords.extend(_FAMILIA_KW.get(fam, (fam,)))
    keywords = list(dict.fromkeys(k.casefold() for k in keywords if k))

    scored: list[tuple[int, dict[str, str]]] = []
    for doc in docs:
        # Divide por headings markdown ou blocos
        chunks = re.split(r"\n(?=##+\s)", doc["texto"])
        if len(chunks) == 1:
            chunks = re.split(r"\n\n+", doc["texto"])
        for chunk in chunks:
            low = chunk.casefold()
            score = sum(1 for kw in keywords if kw in low)
            if score <= 0:
                continue
            trecho = chunk.strip()
            if len(trecho) > max_chars:
                trecho = trecho[: max_chars - 1].rsplit(" ", 1)[0] + "…"
            scored.append(
                (
                    score,
                    {
                        "fonte": doc["path"],
                        "arquivo": doc["nome"],
                        "score": str(score),
                        "trecho": trecho,
                    },
                )
            )
    scored.sort(key=lambda x: (-x[0], x[1]["fonte"]))
    # Dedup por início do trecho
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, item in scored:
        key = item["trecho"][:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_trechos:
            break
    return out


@dataclass
class CasoEspecial:
    municipio: str
    target: str
    exames: str
    positivos: str
    positividade: str
    titulo: str
    sinal_lab: str
    criterios_guia: list[str] = field(default_factory=list)
    o_que_nao_afirmar: list[str] = field(default_factory=list)
    o_que_investigar: list[str] = field(default_factory=list)
    veredito: str = ""


@dataclass
class ParecerVE:
    se_iso: str = "—"
    gerado_em: str = ""
    resumo_executivo: str = ""
    top_solicitados: list[dict[str, Any]] = field(default_factory=list)
    top_positividade: list[dict[str, Any]] = field(default_factory=list)
    top_localidades: list[dict[str, Any]] = field(default_factory=list)
    top_vizinhos: list[dict[str, Any]] = field(default_factory=list)
    top_riscos: list[dict[str, Any]] = field(default_factory=list)
    casos_especiais: list[CasoEspecial] = field(default_factory=list)
    recomendacoes: dict[str, list[str]] = field(default_factory=dict)
    acoes_csv: list[dict[str, str]] = field(default_factory=list)
    citacoes: list[dict[str, str]] = field(default_factory=list)
    fontes_cache: list[dict[str, str]] = field(default_factory=list)
    markdown: str = ""
    html_doc: str = ""
    telegram_resumo: str = ""
    usou_llm: bool = False
    llm_erro: str = ""
    nota_metodologica: str = (
        "Parecer baseado em agregados Observados (GAL/LACEN) e trechos curados "
        "do Guia/portais MS. Sinal laboratorial ≠ declaração automática de surto. "
        "Números não inventados — apenas valores do briefing/pipeline."
    )

    def __post_init__(self) -> None:
        if not self.gerado_em:
            self.gerado_em = _now_local()


def _detectar_casos_especiais(briefing: BriefingEpi) -> list[CasoEspecial]:
    """
    Destaca municípios com alta carga de positivos em agravos prioritários
    (ex.: Juína × HBV) e aplica template Guia MS (investigar, não declarar).
    """
    casos: list[CasoEspecial] = []
    # Agrupa localidades por target
    by_tgt: dict[str, list[dict[str, Any]]] = {}
    for loc in briefing.localidades:
        by_tgt.setdefault(str(loc.get("target") or ""), []).append(loc)

    for tgt, locs in by_tgt.items():
        if not locs:
            continue
        top = max(locs, key=lambda L: float(L.get("positivos") or 0))
        pos = float(top.get("positivos") or 0)
        exames = float(top.get("exames") or 0)
        posi = top.get("positividade")
        mun = str(top.get("municipio") or "")
        if pos < 5 or exames < 10:
            continue
        # Prioriza hepatite / TB / meningite com positividade elevada ou volume alto
        fam = _familia_de_target(tgt)
        if fam not in {"hepatite", "tuberculose", "meningite"} and pos < 10:
            continue
        if fam == "hepatite" or (posi is not None and float(posi) >= 0.25 and pos >= 8):
            casos.append(
                _template_caso_hbv_ou_generico(
                    mun, tgt, exames, pos, posi, fam
                )
            )
    # Garante Juína HBV se presente nos dados mesmo abaixo do limiar relativo
    for loc in briefing.localidades:
        if (
            "JUINA" in str(loc.get("municipio") or "").upper()
            and _is_hepatite(str(loc.get("target") or ""))
        ):
            if not any(
                c.municipio.upper() == "JUINA" and "hepatite" in c.target.casefold()
                for c in casos
            ):
                casos.insert(
                    0,
                    _template_caso_hbv_ou_generico(
                        str(loc["municipio"]),
                        str(loc["target"]),
                        float(loc.get("exames") or 0),
                        float(loc.get("positivos") or 0),
                        loc.get("positividade"),
                        "hepatite",
                    ),
                )
            break
    return casos[:5]


def _template_caso_hbv_ou_generico(
    mun: str,
    tgt: str,
    exames: float,
    pos: float,
    posi: Any,
    fam: str,
) -> CasoEspecial:
    posi_s = _pct_str(posi)
    sinal = (
        f"[Observado] {mun} — {tgt}: {_intish(exames)} exames · "
        f"+{_intish(pos)} positivos ({posi_s}) na SE de referência. "
        "Sinal laboratorial territorial persistente ou elevado — "
        "requer confronto com critérios do Guia de Vigilância MS."
    )
    if fam == "hepatite":
        criterios = [
            "Aumento de casos de hepatite B **aguda** (definição de caso MS: "
            "clínica + marcadores compatíveis, ex. anti-HBc IgM / perfil agudo) "
            "acima do esperado para o município e período.",
            "Evidência de cadeia de transmissão ou fonte comum (parenteral, "
            "sexual, vertical, procedimentos invasivos, etc.) após investigação.",
            "Notificação e classificação no SINAN conforme lista compulsória vigente.",
        ]
        nao = [
            "NÃO afirmar «há surto de hepatite B em "
            f"{mun}» apenas com base em positividade de exames GAL "
            "(HBsAg/triagem pode incluir infecção crônica e demanda assistencial).",
            "NÃO igualar positividade percentual elevada a incidência de casos novos agudos.",
            "NÃO declarar epidemia intermunicipal só porque há par vizinho com positivos.",
        ]
        investigar = [
            "Discriminar marcadores: agudo (anti-HBc IgM / clínica) vs. crônico (HBsAg isolado em seguimento).",
            "Cruzar com notificações SINAN do município e série histórica (SE anteriores).",
            "Avaliar se o padrão é recorrente (várias SE) — cluster persistente ≠ surto automático, mas prioriza investigação.",
            "Mapear serviços (APS, laboratórios locais, hemodiálise, maternidade) e contatos.",
            "Vacinação hepatite B e busca de suscetíveis conforme indicação MS/APS.",
            "Articular VE municipal/CRS e, se persistir, CIEVS estadual / sala de situação.",
        ]
        veredito = (
            f"**Veredito preliminar (não substitui VE):** há **sinal laboratorial** "
            f"relevante de {tgt} em {mun}. Os critérios de **surto/epidemia** do "
            "Guia de Vigilância MS **não estão automaticamente cumpridos** só com "
            "este agregado — recomenda-se **investigação epidemiológica** antes de "
            "qualquer declaração formal."
        )
    else:
        criterios = [
            "Aplicar definição de caso do Guia MS para o agravo e comparar com o esperado local/temporal.",
            "Verificar vínculos epidemiológicos / cluster espacial-temporal após investigação.",
            "Completar notificação e confirmação laboratorial adequada.",
        ]
        nao = [
            f"NÃO declarar surto de {tgt} em {mun} apenas pelo ranking de positividade GAL.",
            "NÃO omitir a distinção entre Observado (lab) e classificação epidemiológica.",
        ]
        investigar = [
            "Abrir investigação de casos e contatos conforme Guia.",
            "Cruzar GAL × SINAN e qualidade da notificação.",
            "Avaliar vizinhos com o mesmo agravo na SE.",
            "Definir ações de APS e comunicação de risco se indicado pela VE.",
        ]
        veredito = (
            f"**Veredito preliminar:** sinal Observado de {tgt} em {mun} justifica "
            "**investigação**; declaração de surto depende dos critérios do Guia "
            "após análise pela Vigilância Epidemiológica."
        )
    return CasoEspecial(
        municipio=mun,
        target=tgt,
        exames=_intish(exames),
        positivos=_intish(pos),
        positividade=posi_s,
        titulo=f"Caso especial — {mun} × {tgt}",
        sinal_lab=sinal,
        criterios_guia=criterios,
        o_que_nao_afirmar=nao,
        o_que_investigar=investigar,
        veredito=veredito,
    )


def _recomendacoes_areas(
    briefing: BriefingEpi,
    casos: Sequence[CasoEspecial],
    trechos: Sequence[dict[str, str]],
) -> dict[str, list[str]]:
    hep = any(_is_hepatite(str(x.get("target") or "")) for x in briefing.mais_solicitados[:5])
    tb = any("tuberculose" in str(x.get("target") or "").casefold() for x in briefing.mais_solicitados[:5])
    den = any("dengue" in str(x.get("target") or "").casefold() for x in briefing.mais_solicitados[:3])
    mun_foco = casos[0].municipio if casos else "municípios prioritários do Top 10"

    rec: dict[str, list[str]] = {
        "Vigilância Epidemiológica": [
            "Tratar o Top 10 de demanda/positividade/localidades como **fila de investigação**, não como lista de surtos declarados.",
            f"Priorizar definição de caso e cruzamento SINAN nos focos: {mun_foco}.",
            "Documentar se critérios de surto/epidemia do Guia MS estão met/unmet após investigação.",
        ],
        "LACEN / rede laboratorial": [
            "Manter TAT e qualidade analítica nos agravos do Top 10; sinalizar à VE resultados de marcadores agudos quando disponíveis.",
            "Para HBV: discriminar e reportar o tipo de ensaio/marcador sempre que o sistema permitir (evitar ambiguidade agudo×crônico).",
            "Não extrapolar positividade de triagem como coeficiente de ataque.",
        ],
        "Atenção Primária": [
            "Apoiar busca de contatos e adesão conforme protocolo do agravo prioritário.",
            "Reforçar vacinação (hepatite B / outros conforme calendário) nas áreas de maior sinal lab.",
            "Orientar fluxos de coleta e preenchimento adequado das requisições GAL.",
        ],
        "CIEVS / sala de situação": [
            f"Manter monitoramento da SE {briefing.se_iso} com Top 10 Observado e pares vizinhos.",
            "Usar linguagem institucional: «sinal laboratorial / investigar», nunca «há surto» sem critérios.",
            "Atualizar parecer VE a cada ciclo do relatório CIEVS (Bloco F).",
        ],
        "Comunicação": [
            "Alinhar notas com assessoria SES: prevenção e esclarecimento, sem alarmismo.",
            "Se houver investigação em curso, informar que a classificação de surto depende da VE e do Guia MS.",
        ],
    }
    if hep:
        rec["Vigilância Epidemiológica"].append(
            "Hepatite B: estratificar casos agudos vs. crônicos antes de qualquer comunicação de surto."
        )
    if tb:
        rec["Vigilância Epidemiológica"].append(
            "TB: priorizar investigação de contatos e pares de municípios vizinhos com positivos."
        )
    if den:
        rec["CIEVS / sala de situação"].append(
            "Dengue: alta demanda com baixa positividade = atenção territorial; não rotular como surto confirmado só pelo volume de exames."
        )
    if trechos:
        rec["CIEVS / sala de situação"].append(
            "Confronto com trechos locais do pacote conhecimento_ve (Guia/portais MS) anexados nas citações."
        )
    return rec


def _montar_acoes_csv(
    briefing: BriefingEpi,
    casos: Sequence[CasoEspecial],
    recs: dict[str, list[str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    rank = 0
    for c in casos:
        for acao in c.o_que_investigar[:4]:
            rank += 1
            rows.append(
                {
                    "rank": str(rank),
                    "se": briefing.se_iso,
                    "area": "Vigilância Epidemiológica",
                    "municipio": c.municipio,
                    "agravo": c.target,
                    "prioridade": "alta",
                    "acao": acao,
                    "prazo": "7 dias",
                    "tipo_sinal": "Observado",
                    "base": "caso_especial+guia_ms",
                }
            )
    for area, items in recs.items():
        for acao in items[:2]:
            rank += 1
            rows.append(
                {
                    "rank": str(rank),
                    "se": briefing.se_iso,
                    "area": area,
                    "municipio": casos[0].municipio if casos else "—",
                    "agravo": casos[0].target if casos else "multiprio",
                    "prioridade": "media",
                    "acao": acao,
                    "prazo": "15 dias",
                    "tipo_sinal": "Derivado",
                    "base": "recomendacao_area",
                }
            )
    return rows[:40]


def _resumo_executivo(briefing: BriefingEpi, casos: Sequence[CasoEspecial]) -> str:
    sol = briefing.mais_solicitados[:3]
    sol_txt = "; ".join(
        f"{x['target']} ({_intish(x['exames'])} ex., {_pct_str(x.get('positividade'))})"
        for x in sol
    ) or "—"
    caso_txt = ""
    if casos:
        c0 = casos[0]
        caso_txt = (
            f" Destaque: {c0.municipio} × {c0.target} — "
            f"{c0.exames} exames / +{c0.positivos} ({c0.positividade}) [Observado]; "
            "parecer: investigar segundo Guia MS — **não** declarar surto automaticamente."
        )
    return (
        f"SE {briefing.se_iso} — Top demanda: {sol_txt}.{caso_txt} "
        "Parecer VE usa agregados LACEN + critérios do Guia de Vigilância "
        "(definição de caso / esperado / investigação)."
    )


def _render_markdown(p: ParecerVE) -> str:
    lines: list[str] = [
        f"# Parecer VE inteligente — LACEN-MT / CIEVS",
        f"",
        f"**SE:** {p.se_iso}  ",
        f"**Gerado em:** {p.gerado_em}  ",
        f"",
        f"> {p.nota_metodologica}",
        f"",
        f"## 1. Resumo executivo",
        f"",
        p.resumo_executivo,
        f"",
        f"## 2. Top 10 — mais solicitados [Observado]",
        f"",
        "| # | Agravo | Exames | Positivos | Positividade |",
        "|---|--------|--------|-----------|--------------|",
    ]
    for i, x in enumerate(p.top_solicitados[:10], 1):
        lines.append(
            f"| {i} | {x.get('target','—')} | {x.get('exames','—')} | "
            f"{x.get('positivos','—')} | {x.get('positividade','—')} |"
        )
    lines += [
        "",
        "## 3. Top 10 — maior positividade [Observado]",
        "",
        "| # | Agravo | Positividade | Exames | Flag |",
        "|---|--------|--------------|--------|------|",
    ]
    for i, x in enumerate(p.top_positividade[:10], 1):
        flags = []
        if x.get("baixa_amostra"):
            flags.append("baixa_amostra")
        if x.get("caveat_igg"):
            flags.append("caveat_IgG")
        lines.append(
            f"| {i} | {x.get('target','—')} | {x.get('positividade','—')} | "
            f"{x.get('exames','—')} | {', '.join(flags) or '—'} |"
        )
    lines += [
        "",
        "## 4. Top localidades (agravos prioritários) [Observado]",
        "",
        "| Agravo | Município | Positivos | Exames | Positividade |",
        "|--------|-----------|-----------|--------|--------------|",
    ]
    for x in p.top_localidades[:10]:
        lines.append(
            f"| {x.get('target','—')} | {x.get('municipio','—')} | "
            f"{x.get('positivos','—')} | {x.get('exames','—')} | "
            f"{x.get('positividade','—')} |"
        )
    lines += [
        "",
        "## 5. Eixos vizinhos (Top) [Observado]",
        "",
        "| Agravo | Par | Positivos | Dist. km |",
        "|--------|-----|-----------|----------|",
    ]
    if p.top_vizinhos:
        for v in p.top_vizinhos[:10]:
            lines.append(
                f"| {v.get('target','—')} | {v.get('par', v.get('municipio','—'))} | "
                f"{v.get('positivos','—')} | {v.get('dist_km','—')} |"
            )
    else:
        lines.append("| — | (nenhum par) | — | — |")
    lines += ["", "## 6. Riscos / dispersão (Top 10)", ""]
    for i, r in enumerate(p.top_riscos[:10], 1):
        lines.append(
            f"{i}. **[{r.get('tipo_sinal', 'Observado')}]** {r.get('mensagem', '')}"
        )
    if not p.top_riscos:
        lines.append("_Sem sinais na regra de dispersão._")

    lines += ["", "## 7. Casos especiais (sinal lab × critérios Guia MS)", ""]
    if not p.casos_especiais:
        lines.append("_Nenhum caso especial acima dos limiares nesta SE._")
    for c in p.casos_especiais:
        lines += [
            f"### {c.titulo}",
            "",
            f"**Sinal laboratorial:** {c.sinal_lab}",
            "",
            "**Critérios de surto/epidemia (Guia MS) a verificar:**",
        ]
        for item in c.criterios_guia:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**O que NÃO afirmar com o Observado atual:**")
        for item in c.o_que_nao_afirmar:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**O que investigar:**")
        for item in c.o_que_investigar:
            lines.append(f"- {item}")
        lines.append("")
        lines.append(c.veredito)
        lines.append("")

    lines += ["", "## 8. Recomendações por área", ""]
    for area, items in p.recomendacoes.items():
        lines.append(f"### {area}")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    lines += ["", "## 9. Citações e fontes", ""]
    for cit in p.citacoes:
        lines.append(
            f"- `{cit.get('fonte', '—')}` (score={cit.get('score', '—')})"
        )
        trecho = (cit.get("trecho") or "").replace("\n", " ")[:280]
        if trecho:
            lines.append(f"  > {trecho}")
    lines.append("")
    lines.append("- URLs oficiais: `conhecimento_ve/fontes.md`")
    lines.append("- Resumo curado: `conhecimento_ve/notificaveis_resumo.md`")
    for fc in p.fontes_cache:
        lines.append(
            f"- Cache MS `{fc.get('id')}`: {fc.get('status')} — {fc.get('url', '')}"
        )
    if p.usou_llm:
        lines.append("")
        lines.append("_Texto parcialmente reescrito por LLM (sem alteração de números)._")
    if p.llm_erro:
        lines.append(f"_LLM indisponível: {p.llm_erro}_")
    lines.append("")
    lines.append("---")
    lines.append("*Modelo: lacen_agente_ve.py · lacen_briefing_epi.py*")
    return "\n".join(lines)


def _render_html(p: ParecerVE) -> str:
    def esc(s: Any) -> str:
        return html.escape(str(s if s is not None else ""))

    def table(headers: list[str], rows: list[list[str]]) -> str:
        th = "".join(f"<th style='padding:6px 8px;text-align:left'>{esc(h)}</th>" for h in headers)
        body = ""
        for r in rows:
            body += "<tr style='border-bottom:1px solid #e6ebf2'>" + "".join(
                f"<td style='padding:6px 8px'>{esc(c)}</td>" for c in r
            ) + "</tr>"
        if not rows:
            body = f"<tr><td colspan='{len(headers)}' style='padding:8px'>(sem dados)</td></tr>"
        return (
            "<table style='border-collapse:collapse;width:100%;font-size:13px;"
            "border:1px solid #d0d7e2;margin:8px 0 16px'>"
            f"<thead style='background:#1B3281;color:#fff'><tr>{th}</tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    sol_rows = [
        [
            str(i),
            str(x.get("target", "—")),
            str(x.get("exames", "—")),
            str(x.get("positivos", "—")),
            str(x.get("positividade", "—")),
        ]
        for i, x in enumerate(p.top_solicitados[:10], 1)
    ]
    pos_rows = [
        [
            str(i),
            str(x.get("target", "—")),
            str(x.get("positividade", "—")),
            str(x.get("exames", "—")),
        ]
        for i, x in enumerate(p.top_positividade[:10], 1)
    ]
    loc_rows = [
        [
            str(x.get("target", "—")),
            str(x.get("municipio", "—")),
            str(x.get("positivos", "—")),
            str(x.get("exames", "—")),
            str(x.get("positividade", "—")),
        ]
        for x in p.top_localidades[:10]
    ]
    viz_rows = [
        [
            str(v.get("target", "—")),
            str(v.get("par", v.get("municipio", "—"))),
            str(v.get("positivos", "—")),
            str(v.get("dist_km", "—")),
        ]
        for v in p.top_vizinhos[:10]
    ]

    casos_html = ""
    for c in p.casos_especiais:
        casos_html += f"<h4 style='color:#1B3281'>{esc(c.titulo)}</h4>"
        casos_html += f"<p><b>Sinal lab:</b> {esc(c.sinal_lab)}</p>"
        casos_html += "<p><b>Critérios Guia MS a verificar</b></p><ul>"
        casos_html += "".join(f"<li>{esc(i)}</li>" for i in c.criterios_guia)
        casos_html += "</ul><p><b>O que NÃO afirmar</b></p><ul>"
        casos_html += "".join(f"<li>{esc(i)}</li>" for i in c.o_que_nao_afirmar)
        casos_html += "</ul><p><b>Investigar</b></p><ul>"
        casos_html += "".join(f"<li>{esc(i)}</li>" for i in c.o_que_investigar)
        casos_html += f"</ul><p style='background:#f0f4fa;border-left:4px solid #1B3281;padding:8px 12px'>{esc(c.veredito)}</p>"

    rec_html = ""
    for area, items in p.recomendacoes.items():
        rec_html += f"<h4>{esc(area)}</h4><ul>"
        rec_html += "".join(f"<li>{esc(i)}</li>" for i in items)
        rec_html += "</ul>"

    risco_html = "<ol>" + "".join(
        f"<li><small>[{esc(r.get('tipo_sinal','Observado'))}]</small> {esc(r.get('mensagem',''))}</li>"
        for r in p.top_riscos[:10]
    ) + "</ol>"

    cit_html = "<ul>" + "".join(
        f"<li><code>{esc(c.get('fonte'))}</code> — {esc((c.get('trecho') or '')[:200])}</li>"
        for c in p.citacoes
    ) + "</ul>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Parecer VE — SE {esc(p.se_iso)}</title></head>
<body style="margin:0;padding:0;background:#eef2f7;color:#1a1a1a;
font-family:'Segoe UI',Tahoma,Arial,sans-serif;line-height:1.45">
<table role="presentation" width="100%"><tr><td align="center" style="padding:16px">
<table width="760" style="max-width:760px;background:#fff;border:1px solid #d0d7e2">
<tr><td style="background:linear-gradient(135deg,#1B3281,#2a4fa3);color:#fff;padding:18px 22px">
  <div style="font-size:12px;letter-spacing:.08em;opacity:.9">SES-MT · LACEN · CIEVS</div>
  <div style="font-size:22px;font-weight:700;margin-top:4px">Parecer VE (IA + Guia MS)</div>
  <div style="margin-top:6px;font-size:13px">SE <b>{esc(p.se_iso)}</b> · {esc(p.gerado_em)}</div>
</td></tr>
<tr><td style="padding:16px 22px">
<p style="background:#fff4e5;border-left:4px solid #e6a23c;padding:10px 12px;font-size:13px">
{esc(p.nota_metodologica)}</p>
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">1. Resumo executivo</h3>
<p>{esc(p.resumo_executivo)}</p>
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">2. Top 10 solicitados</h3>
{table(["#", "Agravo", "Exames", "Positivos", "Positividade"], sol_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">3. Top 10 positividade</h3>
{table(["#", "Agravo", "Positividade", "Exames"], pos_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">4. Top localidades</h3>
{table(["Agravo", "Município", "Positivos", "Exames", "Positividade"], loc_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">5. Vizinhos</h3>
{table(["Agravo", "Par", "Positivos", "Dist. km"], viz_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">6. Riscos / dispersão</h3>
{risco_html}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7. Casos especiais</h3>
{casos_html or "<p>(nenhum)</p>"}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">8. Recomendações por área</h3>
{rec_html}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">9. Citações</h3>
{cit_html}
<p style="font-size:12px;color:#5a6a85;margin-top:18px">
conhecimento_ve/ · lacen_agente_ve.py · lacen_briefing_epi.py
</p>
</td></tr></table></td></tr></table>
</body></html>"""


def _telegram_resumo(p: ParecerVE) -> str:
    lines = [
        "<b>Parecer VE (Guia MS)</b>",
        f"SE {html.escape(p.se_iso)}",
        "",
    ]
    if p.casos_especiais:
        c = p.casos_especiais[0]
        lines.append(
            html.escape(
                f"Foco: {c.municipio} × {c.target} — "
                f"{c.exames} ex. / +{c.positivos} ({c.positividade})"
            )
        )
        lines.append(
            html.escape(
                "Veredito: sinal lab → investigar; NÃO declarar surto automático."
            )
        )
    else:
        lines.append(html.escape((p.resumo_executivo or "")[:280]))
    top = p.top_solicitados[:3]
    if top:
        lines.append("<i>Top demanda</i>")
        for x in top:
            lines.append(
                html.escape(
                    f"• {x.get('target')}: {x.get('exames')} ex. "
                    f"({x.get('positividade')})"
                )
            )
    lines.append("")
    lines.append(html.escape("Detalhe: saida_pipeline/relatorio_ve_inteligente.html"))
    return "\n".join(lines)


def talvez_reescrever_resumo_llm(parecer: ParecerVE) -> ParecerVE:
    """Opcional: reescreve só o resumo executivo; não envia microdados brutos."""
    key = os.getenv("LACEN_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return parecer
    try:
        payload = json.dumps(
            {
                "model": os.getenv("LACEN_LLM_MODEL", "gpt-4o-mini"),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Você é analista CIEVS/LACEN-MT. Reescreva o resumo "
                            "em tom institucional (PT-BR). NÃO invente números. "
                            "NÃO declare surto; use linguagem de investigação "
                            "conforme Guia de Vigilância MS."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Resumo factual:\n{parecer.resumo_executivo}\n\n"
                            f"Casos:\n"
                            + "\n".join(
                                f"- {c.municipio}/{c.target}: {c.exames} ex, "
                                f"+{c.positivos} ({c.positividade})"
                                for c in parecer.casos_especiais[:3]
                            )
                        ),
                    },
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        parecer.resumo_executivo = text
        parecer.usou_llm = True
    except Exception as exc:  # noqa: BLE001 — freio operacional
        parecer.llm_erro = str(exc)
    return parecer


def _fmt_briefing_rows(briefing: BriefingEpi) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    sol = [
        {
            "target": x["target"],
            "exames": _intish(x["exames"]),
            "positivos": _intish(x["positivos"]),
            "positividade": _pct_str(x.get("positividade")),
            "tipo_sinal": "Observado",
        }
        for x in briefing.mais_solicitados[:10]
    ]
    posi = [
        {
            "target": x["target"],
            "exames": _intish(x["exames"]),
            "positivos": _intish(x["positivos"]),
            "positividade": _pct_str(x.get("positividade")),
            "baixa_amostra": bool(x.get("baixa_amostra")),
            "caveat_igg": bool(x.get("caveat_igg")),
            "tipo_sinal": "Observado",
        }
        for x in briefing.maior_positividade[:10]
    ]
    locs = [
        {
            "target": x["target"],
            "municipio": x["municipio"],
            "exames": _intish(x["exames"]),
            "positivos": _intish(x["positivos"]),
            "positividade": _pct_str(x.get("positividade")),
            "tipo_sinal": "Observado",
        }
        for x in briefing.localidades[:10]
    ]
    viz = [
        {
            "target": v["target"],
            "par": f"{v['municipio']} ↔ {v['vizinho']}",
            "municipio": f"{v['municipio']}↔{v['vizinho']}",
            "positivos": (
                f"+{_intish(v.get('positivos_ancora'))} / "
                f"+{_intish(v.get('positivos_vizinho'))}"
            ),
            "dist_km": (
                f"{float(v['dist_km']):.1f}"
                if v.get("dist_km") is not None
                else "—"
            ),
            "tipo_sinal": "Observado",
        }
        for v in briefing.vizinhos[:10]
    ]
    risco = [
        {
            "mensagem": r.get("mensagem", ""),
            "tipo_sinal": r.get("tipo_sinal", "Observado"),
            "regra": r.get("regra", ""),
        }
        for r in briefing.risco[:10]
    ]
    return sol, posi, locs, viz, risco


def gerar_parecer_ve(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    se: str | None = None,
    top: int = 10,
    know_dir: Path | str = KNOW_DIR,
    tentar_download_ms: bool = True,
    usar_llm: bool = True,
    persistir: bool = True,
    briefing: BriefingEpi | None = None,
) -> ParecerVE:
    """Gera parecer VE completo a partir do briefing (Top N) + conhecimento MS."""
    outdir = Path(outdir)
    know = Path(know_dir)
    know.mkdir(parents=True, exist_ok=True)

    fontes_cache: list[dict[str, str]] = []
    if tentar_download_ms:
        fontes_cache = tentar_cachear_fontes_ms(know)

    if briefing is None:
        briefing = gerar_briefing_epi(outdir, se=se, top=top, persistir=True)

    sol, posi, locs, viz, risco = _fmt_briefing_rows(briefing)
    casos = _detectar_casos_especiais(briefing)
    familias = list(
        dict.fromkeys(
            [_familia_de_target(str(x.get("target") or "")) for x in sol[:5]]
            + [_familia_de_target(c.target) for c in casos]
        )
    )
    trechos = recuperar_trechos(familias, know)
    recs = _recomendacoes_areas(briefing, casos, trechos)
    acoes = _montar_acoes_csv(briefing, casos, recs)

    parecer = ParecerVE(
        se_iso=briefing.se_iso,
        resumo_executivo=_resumo_executivo(briefing, casos),
        top_solicitados=sol,
        top_positividade=posi,
        top_localidades=locs,
        top_vizinhos=viz,
        top_riscos=risco,
        casos_especiais=casos,
        recomendacoes=recs,
        acoes_csv=acoes,
        citacoes=trechos,
        fontes_cache=fontes_cache,
    )
    if usar_llm:
        parecer = talvez_reescrever_resumo_llm(parecer)

    parecer.markdown = _render_markdown(parecer)
    parecer.html_doc = _render_html(parecer)
    parecer.telegram_resumo = _telegram_resumo(parecer)

    if persistir:
        persistir_parecer(parecer, outdir)
    return parecer


def persistir_parecer(
    parecer: ParecerVE, outdir: Path | str = OUTDIR_DEFAULT
) -> dict[str, Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {
        "md": outdir / REL_MD,
        "html": outdir / REL_HTML,
        "csv": outdir / REL_CSV,
        "json": outdir / REL_JSON,
    }
    paths["md"].write_text(parecer.markdown, encoding="utf-8")
    paths["html"].write_text(parecer.html_doc, encoding="utf-8")
    fields = [
        "rank",
        "se",
        "area",
        "municipio",
        "agravo",
        "prioridade",
        "acao",
        "prazo",
        "tipo_sinal",
        "base",
    ]
    with paths["csv"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in parecer.acoes_csv:
            w.writerow({k: row.get(k, "") for k in fields})
    meta = {
        "se": parecer.se_iso,
        "gerado_em": parecer.gerado_em,
        "n_casos_especiais": len(parecer.casos_especiais),
        "casos": [
            {
                "municipio": c.municipio,
                "target": c.target,
                "exames": c.exames,
                "positivos": c.positivos,
                "positividade": c.positividade,
            }
            for c in parecer.casos_especiais
        ],
        "usou_llm": parecer.usou_llm,
        "citacoes": [c.get("fonte") for c in parecer.citacoes],
        "fontes_cache": parecer.fontes_cache,
    }
    paths["json"].write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths


def parecer_para_relatorio(parecer: ParecerVE) -> dict[str, Any]:
    """Payload enxuto para Bloco F do relatório CIEVS."""
    return {
        "se_iso": parecer.se_iso,
        "resumo": parecer.resumo_executivo,
        "telegram": parecer.telegram_resumo,
        "casos": [
            {
                "titulo": c.titulo,
                "municipio": c.municipio,
                "target": c.target,
                "exames": c.exames,
                "positivos": c.positivos,
                "positividade": c.positividade,
                "veredito": c.veredito,
                "nao_afirmar": c.o_que_nao_afirmar[:2],
                "investigar": c.o_que_investigar[:3],
            }
            for c in parecer.casos_especiais
        ],
        "recomendacoes_topo": [
            {"area": area, "acao": items[0]}
            for area, items in parecer.recomendacoes.items()
            if items
        ],
        "arquivos": [REL_MD, REL_HTML, REL_CSV],
        "usou_llm": parecer.usou_llm,
    }


def juina_hbv_one_liner(parecer: ParecerVE | None = None) -> str:
    """One-liner para o agente pai relay sobre Juína HBV."""
    if parecer is None:
        # tenta meta já persistida
        meta_path = OUTDIR_DEFAULT / REL_JSON
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                for c in meta.get("casos") or []:
                    if "JUINA" in str(c.get("municipio", "")).upper() and "hepatite" in str(
                        c.get("target", "")
                    ).casefold():
                        return (
                            f"Juína HBV SE {meta.get('se')}: {c.get('exames')} exames / "
                            f"+{c.get('positivos')} ({c.get('positividade')}) [Observado] — "
                            "sinal lab recorrente; NÃO declarar surto automático; "
                            "investigar marcador agudo×crônico e critérios Guia MS."
                        )
            except (OSError, json.JSONDecodeError):
                pass
        return (
            "Juína HBV: sinal laboratorial elevado no Observado — "
            "investigar segundo Guia MS; não declarar surto automaticamente."
        )
    for c in parecer.casos_especiais:
        if "JUINA" in c.municipio.upper() and "hepatite" in c.target.casefold():
            return (
                f"Juína HBV SE {parecer.se_iso}: {c.exames} exames / "
                f"+{c.positivos} ({c.positividade}) [Observado] — "
                "sinal lab (possível padrão recorrente); critérios de surto do "
                "Guia MS exigem definição de caso agudo + esperado + investigação; "
                "NÃO declarar surto só com positividade GAL."
            )
    return (
        f"SE {parecer.se_iso}: sem linha Juína×HBV destacada nos casos especiais; "
        "ver Top localidades do parecer VE."
    )


if __name__ == "__main__":
    p = gerar_parecer_ve(OUTDIR_DEFAULT)
    print(p.markdown[:4000])
    print("\n---")
    print(juina_hbv_one_liner(p))
    print(f"Arquivos: {OUTDIR_DEFAULT / REL_MD}")
