#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de parecer de Vigilância Epidemiológica (VE) — LACEN-MT / CIEVS.

Ingere agregados do briefing epidemiológico (Top 10 notificações/SINAN ou
proxy exames + Top 10 positividade), compara com SE anteriores, recupera
trechos do pacote local alinhado ao Guia de Vigilância MS (RAG-lite) e emite
alerta/recomendações por destinatário (SES-MT, CIEVS, área técnica,
município, vizinhos).

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
import statistics
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from lacen_briefing_epi import (
    BriefingEpi,
    WEEKLY_NAME,
    _fmt_se,
    _is_hepatite,
    _num,
    _parse_se,
    _read_csv,
    enriquecer_top_com_delta,
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

_AREA_TECNICA: dict[str, str] = {
    "hepatite": "Área técnica — Hepatites virais",
    "tuberculose": "Área técnica — Tuberculose",
    "dengue": "Área técnica — Arboviroses",
    "meningite": "Área técnica — Meningites",
    "igg": "Área técnica — Sorologias / IgG",
    "surto": "Área técnica — Vigilância de agravos",
}

CSV_FIELDS = [
    "agravo",
    "destinatario",
    "recomendacao",
    "prazo",
    "severidade",
    "se_ref",
    "evidencia",
]


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


def _area_tecnica_de(target: str) -> str:
    return _AREA_TECNICA.get(_familia_de_target(target), _AREA_TECNICA["surto"])


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


# ---------------------------------------------------------------------------
# Série temporal / Top notificações
# ---------------------------------------------------------------------------


def _shift_se(year: int, week: int, delta: int) -> tuple[int, int]:
    """Avança/recua SE (delta negativo = semanas anteriores)."""
    y, w = int(year), int(week) + int(delta)
    while w < 1:
        y -= 1
        w += 52
    while w > 52:
        y += 1
        w -= 52
    return y, w


def _semanas_anteriores(se: tuple[int, int], n: int = 4) -> list[tuple[int, int]]:
    """Últimas n SE anteriores à de referência (SE-1 … SE-n)."""
    return [_shift_se(se[0], se[1], -i) for i in range(1, n + 1)]


def _agg_target_semana(
    weekly: list[dict[str, str]],
    se: tuple[int, int],
) -> dict[str, dict[str, float]]:
    """Agrega por target: exames, positivos, notificacoes (inclui linhas só-SINAN)."""
    y0, w0 = se
    agg: dict[str, dict[str, float]] = {}
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        mun = str(r.get("municipio") or "").strip()
        if not mun or mun.startswith("*"):
            continue
        tests = _num(r.get("tests"), 0) or 0
        notif = _num(r.get("notificacoes"), 0) or 0
        if tests <= 0 and notif <= 0:
            continue
        tgt = str(r.get("target") or r.get("agravo_sinan") or "").strip() or "—"
        a = agg.setdefault(tgt, {"exames": 0.0, "positivos": 0.0, "notificacoes": 0.0})
        a["exames"] += tests
        a["positivos"] += _num(r.get("positives"), 0) or 0
        a["notificacoes"] += notif
    return agg


def top_notificacoes(
    weekly: list[dict[str, str]],
    se: tuple[int, int] | str,
    top: int = 10,
    *,
    min_notif_se: float = 1.0,
) -> tuple[list[dict[str, Any]], str]:
    """
    Top 10 por notificações SINAN quando a SE tem volume; senão proxy por exames GAL
    (rotulado explicitamente).
    """
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw:
        return [], "indisponivel"
    agg = _agg_target_semana(weekly, yw)
    total_notif = sum(v["notificacoes"] for v in agg.values())
    if total_notif >= min_notif_se:
        ranked = sorted(
            (
                {
                    "target": tgt,
                    "notificacoes": a["notificacoes"],
                    "exames": a["exames"],
                    "positivos": a["positivos"],
                    "positividade": (
                        (a["positivos"] / a["exames"]) if a["exames"] > 0 else None
                    ),
                    "fonte_metrica": "SINAN",
                    "rotulo": "notificações SINAN",
                    "tipo_sinal": "Observado",
                }
                for tgt, a in agg.items()
                if a["notificacoes"] > 0
            ),
            key=lambda x: (x["notificacoes"], x["exames"]),
            reverse=True,
        )
        return ranked[: max(1, top)], "SINAN"
    ranked = sorted(
        (
            {
                "target": tgt,
                "notificacoes": a["notificacoes"],
                "exames": a["exames"],
                "positivos": a["positivos"],
                "positividade": (
                    (a["positivos"] / a["exames"]) if a["exames"] > 0 else None
                ),
                "fonte_metrica": "proxy_exames_GAL",
                "rotulo": "proxy: exames GAL (SINAN zerado/atrasado na SE)",
                "tipo_sinal": "Observado",
            }
            for tgt, a in agg.items()
            if a["exames"] > 0
        ),
        key=lambda x: (x["exames"], x["positivos"]),
        reverse=True,
    )
    return ranked[: max(1, top)], "proxy_exames_GAL"


def _tendencia_seta(delta: float | None, *, tol_pct: float = 5.0) -> str:
    if delta is None:
        return "→"
    if delta > tol_pct:
        return "↑"
    if delta < -tol_pct:
        return "↓"
    return "→"


def comparar_com_semanas_anteriores(
    weekly: list[dict[str, str]],
    se: tuple[int, int] | str,
    targets: Sequence[str],
    *,
    n_anteriores: int = 4,
    metrica: str = "auto",
) -> list[dict[str, Any]]:
    """
    Para cada target: valor SE atual vs SE-1, SE-2 e mediana das últimas 4 SE.
    Métrica: notificacoes se disponíveis na SE; senão exames; também positividade.
    """
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw:
        return []
    prevs = _semanas_anteriores(yw, n_anteriores)
    cur_agg = _agg_target_semana(weekly, yw)
    prev_aggs = {pse: _agg_target_semana(weekly, pse) for pse in prevs}
    total_notif = sum(v["notificacoes"] for v in cur_agg.values())
    use_notif = metrica == "notificacoes" or (
        metrica == "auto" and total_notif >= 1.0
    )
    metric_key = "notificacoes" if use_notif else "exames"
    out: list[dict[str, Any]] = []
    for tgt in targets:
        if not tgt:
            continue
        cur = cur_agg.get(tgt, {"exames": 0.0, "positivos": 0.0, "notificacoes": 0.0})
        val_cur = float(cur.get(metric_key) or 0)
        pos_cur = float(cur.get("positivos") or 0)
        exames_cur = float(cur.get("exames") or 0)
        posi_cur = (pos_cur / exames_cur) if exames_cur > 0 else None

        hist_vals: list[float] = []
        hist_posi: list[float] = []
        se_vals: dict[str, float] = {}
        for pse in prevs:
            a = prev_aggs[pse].get(
                tgt, {"exames": 0.0, "positivos": 0.0, "notificacoes": 0.0}
            )
            v = float(a.get(metric_key) or 0)
            hist_vals.append(v)
            se_vals[_fmt_se(*pse)] = v
            pe, pp = float(a.get("exames") or 0), float(a.get("positivos") or 0)
            if pe > 0:
                hist_posi.append(pp / pe)

        se1 = hist_vals[0] if hist_vals else None
        se2 = hist_vals[1] if len(hist_vals) > 1 else None
        delta_abs_1 = (val_cur - se1) if se1 is not None else None
        delta_pct_1 = (
            (100.0 * (val_cur - se1) / se1) if se1 and se1 > 0 else None
        )
        delta_abs_2 = (val_cur - se2) if se2 is not None else None
        delta_pct_2 = (
            (100.0 * (val_cur - se2) / se2) if se2 and se2 > 0 else None
        )
        mediana = statistics.median(hist_vals) if hist_vals else None
        acima_mediana = bool(
            mediana is not None and val_cur > mediana and mediana >= 0
        )
        posi_med = statistics.median(hist_posi) if hist_posi else None
        acima_mediana_posi = bool(
            posi_cur is not None
            and posi_med is not None
            and posi_cur > posi_med
        )
        out.append(
            {
                "target": tgt,
                "metrica": metric_key,
                "fonte_metrica": "SINAN" if use_notif else "proxy_exames_GAL",
                "valor_se": val_cur,
                "exames_se": exames_cur,
                "positivos_se": pos_cur,
                "positividade_se": posi_cur,
                "se_menos_1": se1,
                "delta_abs_se1": delta_abs_1,
                "delta_pct_se1": delta_pct_1,
                "tendencia_se1": _tendencia_seta(delta_pct_1),
                "se_menos_2": se2,
                "delta_abs_se2": delta_abs_2,
                "delta_pct_se2": delta_pct_2,
                "tendencia_se2": _tendencia_seta(delta_pct_2),
                "mediana_4se": mediana,
                "acima_mediana_4se": acima_mediana,
                "acima_mediana_positividade_4se": acima_mediana_posi,
                "serie_anteriores": se_vals,
                "se_ref": _fmt_se(*yw),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


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
    comparacao: dict[str, Any] = field(default_factory=dict)
    vizinhos_risco: list[dict[str, Any]] = field(default_factory=list)
    severidade: str = "media"


@dataclass
class ParecerVE:
    se_iso: str = "—"
    gerado_em: str = ""
    resumo_executivo: str = ""
    top_notificacoes: list[dict[str, Any]] = field(default_factory=list)
    fonte_notificacoes: str = "proxy_exames_GAL"
    top_solicitados: list[dict[str, Any]] = field(default_factory=list)
    top_positividade: list[dict[str, Any]] = field(default_factory=list)
    comparacao_semanas: list[dict[str, Any]] = field(default_factory=list)
    top_localidades: list[dict[str, Any]] = field(default_factory=list)
    top_vizinhos: list[dict[str, Any]] = field(default_factory=list)
    top_riscos: list[dict[str, Any]] = field(default_factory=list)
    gal_sinan: list[dict[str, Any]] = field(default_factory=list)
    geo_nivel: str = "municipio"
    geo_nota: str = ""
    geo_hotspots: list[dict[str, Any]] = field(default_factory=list)
    cruzamento_bases: list[dict[str, Any]] = field(default_factory=list)
    cruzamento_sih_sia: dict[str, Any] = field(default_factory=dict)
    sinais_rede: dict[str, Any] = field(default_factory=dict)
    casos_especiais: list[CasoEspecial] = field(default_factory=list)
    recomendacoes: dict[str, list[str]] = field(default_factory=dict)
    recomendacoes_por_agravo: list[dict[str, Any]] = field(default_factory=list)
    acoes_csv: list[dict[str, str]] = field(default_factory=list)
    citacoes: list[dict[str, str]] = field(default_factory=list)
    fontes_cache: list[dict[str, str]] = field(default_factory=list)
    markdown: str = ""
    html_doc: str = ""
    telegram_resumo: str = ""
    telegram_alertas: list[str] = field(default_factory=list)
    usou_llm: bool = False
    llm_erro: str = ""
    nota_metodologica: str = (
        "Parecer baseado em agregados Observados (GAL/LACEN ± SINAN) e trechos "
        "curados do Guia/portais MS. Compara SE atual com SE-1/SE-2 e mediana "
        "das 4 SE anteriores. Sinal laboratorial ≠ declaração automática de surto. "
        "Números não inventados — apenas valores do briefing/pipeline."
    )

    def __post_init__(self) -> None:
        if not self.gerado_em:
            self.gerado_em = _now_local()


def _fmt_delta(delta_abs: Any, delta_pct: Any, seta: str) -> str:
    if delta_abs is None:
        return "—"
    pct = f"{delta_pct:+.0f}%" if delta_pct is not None else "—"
    return f"{seta} {_intish(delta_abs)} ({pct})"


def _detectar_casos_especiais(
    briefing: BriefingEpi,
    comparacao: Sequence[dict[str, Any]] | None = None,
    vizinhos: Sequence[dict[str, Any]] | None = None,
) -> list[CasoEspecial]:
    """
    Destaca municípios com alta carga de positivos em agravos prioritários
    (ex.: Juína × HBV) e aplica template Guia MS (investigar, não declarar).
    """
    comp_by = {str(c.get("target")): c for c in (comparacao or [])}
    casos: list[CasoEspecial] = []
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
        fam = _familia_de_target(tgt)
        if fam not in {"hepatite", "tuberculose", "meningite"} and pos < 10:
            continue
        if fam == "hepatite" or (posi is not None and float(posi) >= 0.25 and pos >= 8):
            viz_t = [
                v
                for v in (vizinhos or briefing.vizinhos)
                if str(v.get("target")) == tgt
                and (
                    mun.upper() in str(v.get("municipio") or "").upper()
                    or mun.upper() in str(v.get("vizinho") or "").upper()
                    or mun.upper() in str(v.get("par") or "").upper()
                )
            ]
            casos.append(
                _template_caso_hbv_ou_generico(
                    mun,
                    tgt,
                    exames,
                    pos,
                    posi,
                    fam,
                    comparacao=comp_by.get(tgt),
                    vizinhos_risco=viz_t,
                )
            )
    for loc in briefing.localidades:
        if (
            "JUINA" in str(loc.get("municipio") or "").upper()
            and _is_hepatite(str(loc.get("target") or ""))
        ):
            if not any(
                c.municipio.upper() == "JUINA" and "hepatite" in c.target.casefold()
                for c in casos
            ):
                tgt = str(loc["target"])
                viz_t = [
                    v
                    for v in (vizinhos or briefing.vizinhos)
                    if str(v.get("target")) == tgt
                ]
                casos.insert(
                    0,
                    _template_caso_hbv_ou_generico(
                        str(loc["municipio"]),
                        tgt,
                        float(loc.get("exames") or 0),
                        float(loc.get("positivos") or 0),
                        loc.get("positividade"),
                        "hepatite",
                        comparacao=comp_by.get(tgt),
                        vizinhos_risco=viz_t,
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
    *,
    comparacao: dict[str, Any] | None = None,
    vizinhos_risco: Sequence[dict[str, Any]] | None = None,
) -> CasoEspecial:
    posi_s = _pct_str(posi)
    comp = comparacao or {}
    comp_txt = ""
    if comp:
        comp_txt = (
            f" Vs SE-1: {_fmt_delta(comp.get('delta_abs_se1'), comp.get('delta_pct_se1'), comp.get('tendencia_se1', '→'))}"
            f" · Vs SE-2: {_fmt_delta(comp.get('delta_abs_se2'), comp.get('delta_pct_se2'), comp.get('tendencia_se2', '→'))}"
            f" · mediana 4 SE ({comp.get('metrica', '—')}): {_intish(comp.get('mediana_4se'))}"
            + (
                " [acima da mediana]"
                if comp.get("acima_mediana_4se")
                else ""
            )
            + "."
        )
    sinal = (
        f"[Observado] {mun} — {tgt}: {_intish(exames)} exames · "
        f"+{_intish(pos)} positivos ({posi_s}) na SE de referência.{comp_txt} "
        "Sinal laboratorial territorial — requer confronto com critérios do "
        "Guia de Vigilância MS (investigação; sem declaração automática de surto)."
    )
    sev = "alta" if (
        (posi is not None and float(posi) >= 0.4 and pos >= 10)
        or comp.get("acima_mediana_4se")
        or (vizinhos_risco and len(list(vizinhos_risco)) >= 1 and pos >= 8)
    ) else "media"

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
        comparacao=dict(comp) if comp else {},
        vizinhos_risco=list(vizinhos_risco or []),
        severidade=sev,
    )


def _evidencia_caso(c: CasoEspecial, se_iso: str) -> str:
    parts = [
        f"SE {se_iso}: {c.exames} ex. / +{c.positivos} ({c.positividade}) [Observado]"
    ]
    comp = c.comparacao or {}
    if comp:
        parts.append(
            f"ΔSE-1 {_fmt_delta(comp.get('delta_abs_se1'), comp.get('delta_pct_se1'), comp.get('tendencia_se1', '→'))}"
        )
        if comp.get("acima_mediana_4se"):
            parts.append("acima mediana 4 SE")
    if c.vizinhos_risco:
        pares = []
        for v in c.vizinhos_risco[:2]:
            pares.append(
                f"{v.get('municipio', '?')}↔{v.get('vizinho', v.get('par', '?'))}"
            )
        parts.append("vizinhos: " + "; ".join(pares))
    return " · ".join(parts)


def _recomendacoes_por_destinatario(
    briefing: BriefingEpi,
    casos: Sequence[CasoEspecial],
    trechos: Sequence[dict[str, str]],
) -> tuple[dict[str, list[str]], list[dict[str, Any]], list[dict[str, str]]]:
    """
    Recomendações endereçadas a SES-MT, CIEVS, área técnica, município(s)
    e municípios próximos (se co-positividade / risco de dispersão).
    """
    se = briefing.se_iso
    rec_areas: dict[str, list[str]] = {
        "SES-MT": [],
        "CIEVS": [],
        "Área técnica": [],
        "Município(s)": [],
        "Municípios próximos": [],
    }
    por_agravo: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []

    if not casos:
        # Fallback genérico a partir do Top
        focos = ", ".join(
            f"{x.get('municipio')}×{x.get('target')}"
            for x in briefing.localidades[:3]
        ) or "municípios do Top 10"
        gen = [
            (
                "SES-MT",
                "media",
                "15 dias",
                "multiprio",
                f"Acompanhar fila de investigação da SE {se} ({focos}); "
                "sem declaração automática de surto.",
                f"Top localidades SE {se}",
            ),
            (
                "CIEVS",
                "media",
                "7 dias",
                "multiprio",
                "Manter sala de situação com Top 10 + comparação SE-1/SE-2; "
                "linguagem de investigação (Guia MS).",
                f"Briefing SE {se}",
            ),
        ]
        for dest, sev, prazo, agr, texto, evid in gen:
            rec_areas.setdefault(dest, []).append(texto)
            rows.append(
                {
                    "agravo": agr,
                    "destinatario": dest,
                    "recomendacao": texto,
                    "prazo": prazo,
                    "severidade": sev,
                    "se_ref": se,
                    "evidencia": evid,
                }
            )
        return rec_areas, por_agravo, rows

    for c in casos:
        fam = _familia_de_target(c.target)
        area_tec = _area_tecnica_de(c.target)
        evid = _evidencia_caso(c, se)
        sev = c.severidade
        guia_hint = ""
        for t in trechos:
            if any(kw in (t.get("trecho") or "").casefold() for kw in _FAMILIA_KW.get(fam, ())):
                guia_hint = f" (ref. local `{t.get('arquivo', '')}`)"
                break

        linhas_dest: list[tuple[str, str, str]] = [
            (
                "SES-MT",
                "15 dias",
                (
                    f"Monitorar sinal de {c.target} em {c.municipio} na SE {se}; "
                    "apoiar CRS/VE municipal na investigação conforme Guia MS"
                    f"{guia_hint} — sem declarar surto automaticamente."
                ),
            ),
            (
                "CIEVS",
                "7 dias",
                (
                    f"Incluir {c.municipio}×{c.target} na sala de situação; "
                    "confrontar Observado × esperado (série SE-1/SE-2/mediana 4 SE); "
                    "manter linguagem «investigar / sinal lab», não «há surto»."
                ),
            ),
            (
                area_tec,
                "7 dias",
                (
                    f"Programa {fam}: estratificar marcadores/definição de caso em "
                    f"{c.municipio}; orientar rede sobre fluxo de notificação e "
                    f"conduta técnica do agravo {c.target}."
                ),
            ),
            (
                f"Município — {c.municipio}",
                "7 dias",
                (
                    f"VE municipal de {c.municipio}: abrir/atualizar investigação de "
                    f"{c.target}; cruzar GAL×SINAN; aplicar definição de caso MS; "
                    + (
                        c.o_que_investigar[0]
                        if c.o_que_investigar
                        else "mapear contatos e fontes."
                    )
                ),
            ),
        ]
        if c.vizinhos_risco:
            pares = ", ".join(
                f"{v.get('municipio')}↔{v.get('vizinho')}"
                for v in c.vizinhos_risco[:3]
            )
            linhas_dest.append(
                (
                    "Municípios próximos",
                    "7 dias",
                    (
                        f"Alerta de co-positividade / risco de dispersão ({c.target}): "
                        f"{pares}. Reforçar vigilância ativa e comunicação entre VE "
                        "municipais; não interpretar par vizinho como surto intermunicipal "
                        "automático."
                    ),
                ),
            )
            rec_areas["Municípios próximos"].append(linhas_dest[-1][2])

        dest_map: dict[str, str] = {}
        for dest, prazo, texto in linhas_dest:
            dest_map[dest] = texto
            key_area = (
                "Área técnica"
                if dest.startswith("Área técnica")
                else (
                    "Município(s)"
                    if dest.startswith("Município —")
                    else dest
                )
            )
            rec_areas.setdefault(key_area, []).append(texto)
            rows.append(
                {
                    "agravo": c.target,
                    "destinatario": dest,
                    "recomendacao": texto,
                    "prazo": prazo,
                    "severidade": sev,
                    "se_ref": se,
                    "evidencia": evid,
                }
            )

        por_agravo.append(
            {
                "agravo": c.target,
                "municipio": c.municipio,
                "severidade": sev,
                "evidencia": evid,
                "destinatarios": dest_map,
            }
        )

    # Dedup curto por área
    for k, items in list(rec_areas.items()):
        seen: set[str] = set()
        uniq: list[str] = []
        for it in items:
            if it in seen:
                continue
            seen.add(it)
            uniq.append(it)
        rec_areas[k] = uniq[:6]
    return rec_areas, por_agravo, rows[:60]


def _resumo_executivo(
    briefing: BriefingEpi,
    casos: Sequence[CasoEspecial],
    fonte_notif: str,
    comparacao: Sequence[dict[str, Any]],
) -> str:
    sol = briefing.mais_solicitados[:3]
    sol_txt = "; ".join(
        f"{x['target']} ({_intish(x['exames'])} ex., {_pct_str(x.get('positividade'))})"
        for x in sol
    ) or "—"
    fonte_txt = (
        "notificações SINAN"
        if fonte_notif == "SINAN"
        else "proxy exames GAL (SINAN zerado/atrasado)"
    )
    caso_txt = ""
    if casos:
        c0 = casos[0]
        caso_txt = (
            f" Destaque: {c0.municipio} × {c0.target} — "
            f"{c0.exames} exames / +{c0.positivos} ({c0.positividade}) [Observado]; "
            "parecer: investigar segundo Guia MS — **não** declarar surto automaticamente."
        )
    comp_txt = ""
    if comparacao:
        c = comparacao[0]
        comp_txt = (
            f" Comparação ({c.get('target')}): vs SE-1 "
            f"{_fmt_delta(c.get('delta_abs_se1'), c.get('delta_pct_se1'), c.get('tendencia_se1', '→'))}"
            + (
                "; acima da mediana das 4 SE."
                if c.get("acima_mediana_4se")
                else "."
            )
        )
    return (
        f"SE {briefing.se_iso} — Top demanda/proxy ({fonte_txt}): {sol_txt}."
        f"{caso_txt}{comp_txt} "
        "Parecer VE usa agregados LACEN ± SINAN + critérios do Guia de Vigilância "
        "(definição de caso / esperado / investigação)."
    )


def _render_markdown(p: ParecerVE) -> str:
    fonte = p.fonte_notificacoes
    rotulo_top = (
        "notificações SINAN"
        if fonte == "SINAN"
        else "proxy: exames GAL (SINAN indisponível/zerado na SE)"
    )
    lines: list[str] = [
        "# Parecer VE inteligente — LACEN-MT / CIEVS",
        "",
        f"**SE:** {p.se_iso}  ",
        f"**Gerado em:** {p.gerado_em}  ",
        "",
        f"> {p.nota_metodologica}",
        "",
        "## 1. Resumo executivo",
        "",
        p.resumo_executivo,
        "",
        f"## 2. Top 10 — {rotulo_top} [Observado]",
        "",
        "| # | Agravo | n_se | n_se_ant | Δ | Δ% | Tend. | Positivos | Positividade | Fonte |",
        "|---|--------|------|----------|---|----|-------|-----------|--------------|-------|",
    ]
    for i, x in enumerate(p.top_notificacoes[:10], 1):
        met = (
            x.get("n_se")
            if x.get("n_se") is not None
            else (
                x.get("notificacoes")
                if fonte == "SINAN"
                else x.get("exames")
            )
        )
        pct = x.get("delta_pct")
        pct_s = f"{float(pct):+.1f}%" if pct is not None else "—"
        lines.append(
            f"| {i} | {x.get('target','—')} | {_intish(met)} | "
            f"{_intish(x.get('n_se_ant'))} | {_intish(x.get('delta'))} | "
            f"{pct_s} | {x.get('tendencia', '→')} | "
            f"{_intish(x.get('positivos'))} | {_pct_str(x.get('positividade'))} | "
            f"{x.get('fonte_metrica', fonte)} |"
        )
    lines += [
        "",
        "## 3. Top 10 — maior positividade [Observado]",
        "",
        "| # | Agravo | Positividade | n_se | n_se_ant | Δ% | Tend. | Mediana 4SE | Exames | Flag |",
        "|---|--------|--------------|------|----------|----|-------|-------------|--------|------|",
    ]
    for i, x in enumerate(p.top_positividade[:10], 1):
        flags = []
        if x.get("baixa_amostra"):
            flags.append("baixa_amostra")
        if x.get("caveat_igg"):
            flags.append("caveat_IgG")
        pct = x.get("delta_pct")
        pct_s = f"{float(pct):+.1f}%" if pct is not None else "—"
        med = x.get("mediana_4se")
        med_s = _pct_str(med) if isinstance(med, float) else (_intish(med) if med is not None else "—")
        lines.append(
            f"| {i} | {x.get('target','—')} | {x.get('positividade','—')} | "
            f"{_pct_str(x.get('n_se')) if isinstance(x.get('n_se'), float) and float(x.get('n_se') or 0) <= 1 else x.get('positividade','—')} | "
            f"{_pct_str(x.get('n_se_ant')) if isinstance(x.get('n_se_ant'), float) and float(x.get('n_se_ant') or 0) <= 1 else '—'} | "
            f"{pct_s} | {x.get('tendencia', '→')} | {med_s} | "
            f"{x.get('exames','—')} | {', '.join(flags) or '—'} |"
        )
    lines += [
        "",
        "## 4. Comparação com SE anteriores",
        "",
        "| Agravo | Métrica | SE | SE-1 (Δ) | SE-2 (Δ) | Mediana 4 SE | Flag |",
        "|--------|---------|----|----------|----------|--------------|------|",
    ]
    if p.comparacao_semanas:
        for c in p.comparacao_semanas[:12]:
            flag = []
            if c.get("acima_mediana_4se"):
                flag.append("acima mediana 4 SE")
            if c.get("acima_mediana_positividade_4se"):
                flag.append("posi>mediana")
            lines.append(
                f"| {c.get('target','—')} | {c.get('metrica','—')} | "
                f"{_intish(c.get('valor_se'))} | "
                f"{_fmt_delta(c.get('delta_abs_se1'), c.get('delta_pct_se1'), c.get('tendencia_se1','→'))} | "
                f"{_fmt_delta(c.get('delta_abs_se2'), c.get('delta_pct_se2'), c.get('tendencia_se2','→'))} | "
                f"{_intish(c.get('mediana_4se'))} | {', '.join(flag) or '—'} |"
            )
    else:
        lines.append("| — | — | — | — | — | — | (sem série) |")

    lines += [
        "",
        "## 5. Top localidades (agravos prioritários) [Observado]",
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
        "## 6. Eixos vizinhos (Top) [Observado]",
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
    lines += ["", "## 7. Riscos / dispersão (Top 10)", ""]
    for i, r in enumerate(p.top_riscos[:10], 1):
        lines.append(
            f"{i}. **[{r.get('tipo_sinal', 'Observado')}]** {r.get('mensagem', '')}"
        )
    if not p.top_riscos:
        lines.append("_Sem sinais na regra de dispersão._")

    lines += [
        "",
        "## 7b. GAL×SINAN (qualquer agravo — mun×família)",
        "",
        "| Município | Família | Exames | Notif. | Flag |",
        "|-----------|---------|--------|--------|------|",
    ]
    if p.gal_sinan:
        for g in p.gal_sinan[:15]:
            lines.append(
                f"| {g.get('municipio','—')} | {g.get('familia', g.get('target','—'))} | "
                f"{_intish(g.get('exames'))} | {_intish(g.get('notificacoes'))} | "
                f"{g.get('flag','—')} |"
            )
    else:
        lines.append("| — | — | — | — | (sem divergência acima do limiar) |")

    lines += [
        "",
        f"## 7c. Geo hotspots (nível: {p.geo_nivel})",
        "",
        f"_{p.geo_nota}_",
        "",
        "| Município | Local | Agravo | N | IBGE |",
        "|-----------|-------|--------|---|------|",
    ]
    if p.geo_hotspots:
        for h in p.geo_hotspots[:12]:
            lines.append(
                f"| {h.get('municipio','—')} | {h.get('local','—')} | "
                f"{h.get('agravo','—')} | {_intish(h.get('n'))} | "
                f"{h.get('codigo_ibge','')} |"
            )
    else:
        lines.append("| — | — | — | — | — |")

    lines += [
        "",
        "## 7d. Cruzamento de bases (DW staging)",
        "",
        "| Fonte | Status | Quando agrega |",
        "|-------|--------|---------------|",
    ]
    if p.cruzamento_bases:
        for c in p.cruzamento_bases:
            lines.append(
                f"| {c.get('fonte','—')} | {c.get('status','—')} | "
                f"{c.get('quando_agrega','—')} |"
            )
    else:
        lines.append("| — | (inventário vazio) | ver conhecimento_ve/cruzamento_bases.md |")
    lines.append("")
    lines.append(
        "Prioridade e valor de cada base: `conhecimento_ve/cruzamento_bases.md`."
    )

    lines += [
        "",
        "## 7e. Cruzamento SIH/SIA (proxy VW_INTERNACAO)",
        "",
    ]
    sih = p.cruzamento_sih_sia or {}
    top_sih = sih.get("top_mun") or []
    if top_sih:
        lines += [
            "| Município | Família CID | N | Fonte |",
            "|-----------|-------------|---|-------|",
        ]
        for r in top_sih[:12]:
            lines.append(
                f"| {r.get('municipio','—')} | {r.get('cid_familia','—')} | "
                f"{_intish(r.get('n'))} | {r.get('fonte','SIH')} |"
            )
        caveat = str(sih.get("caveat") or "")
        if caveat:
            lines += ["", f"_Caveat:_ {caveat}"]
    else:
        lines.append(
            "_Sem agregados SIH/SIA nesta remessa "
            "(extrair `VW_INTERNACAO`/`SIA` via `etl/dw_extract`)._"
        )

    lines += [
        "",
        "## 7f. Sinais IndicaSUS / SISREG (rede e regulação)",
        "",
    ]
    rede = p.sinais_rede or {}
    if rede.get("presente"):
        occ = rede.get("indicasus_ocupacao_top") or []
        if occ:
            lines += [
                "**IndicaSUS — ocupação (amostra):**",
                "",
                "| Tipo leito | Situação | Data | N |",
                "|------------|----------|------|---|",
            ]
            for r in occ[:8]:
                lines.append(
                    f"| {r.get('tipo_leito','—')} | {r.get('situacao','—')} | "
                    f"{r.get('data_ref','—')} | {_intish(r.get('n'))} |"
                )
            lines.append("")
        hosp = rede.get("sisreg_hosp_top") or []
        if hosp:
            lines += [
                "**SISREG hospitalar (top mun×status):**",
                "",
                "| Município | Status | N |",
                "|-----------|--------|---|",
            ]
            for r in hosp[:8]:
                lines.append(
                    f"| {r.get('municipio','—')} | {r.get('status','—')} | "
                    f"{_intish(r.get('n'))} |"
                )
            lines.append("")
        amb = rede.get("sisreg_amb_pendente_top") or []
        if amb:
            lines += [
                "**SISREG ambulatorial — pendentes/fila:**",
                "",
                "| Município | Status | N |",
                "|-----------|--------|---|",
            ]
            for r in amb[:8]:
                lines.append(
                    f"| {r.get('municipio','—')} | {r.get('status','—')} | "
                    f"{_intish(r.get('n'))} |"
                )
            lines.append("")
        cav = str(rede.get("caveat") or "")
        if cav:
            lines.append(f"_Caveat:_ {cav}")
    else:
        lines.append(
            "_Sem sinais IndicaSUS/SISREG no staging "
            "(rode `etl/external_extract` com VPN)._"
        )

    lines += ["", "## 8. Casos especiais (sinal lab × critérios Guia MS)", ""]
    if not p.casos_especiais:
        lines.append("_Nenhum caso especial acima dos limiares nesta SE._")
    for c in p.casos_especiais:
        lines += [
            f"### {c.titulo}",
            "",
            f"**Severidade:** {c.severidade}  ",
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

    lines += ["", "## 9. Recomendações por destinatário / agravo", ""]
    if p.recomendacoes_por_agravo:
        for block in p.recomendacoes_por_agravo:
            lines.append(
                f"### {block.get('municipio','—')} × {block.get('agravo','—')} "
                f"({block.get('severidade','')})"
            )
            lines.append(f"_Evidência:_ {block.get('evidencia','—')}")
            lines.append("")
            for dest, texto in (block.get("destinatarios") or {}).items():
                lines.append(f"- **{dest}:** {texto}")
            lines.append("")
    else:
        for area, items in p.recomendacoes.items():
            lines.append(f"### {area}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

    lines += ["", "## 10. Citações e fontes", ""]
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

    fonte = p.fonte_notificacoes
    rotulo = (
        "notificações SINAN"
        if fonte == "SINAN"
        else "proxy exames GAL (SINAN zerado/atrasado)"
    )
    notif_rows = [
        [
            str(i),
            str(x.get("target", "—")),
            _intish(
                x.get("n_se")
                if x.get("n_se") is not None
                else (x.get("notificacoes") if fonte == "SINAN" else x.get("exames"))
            ),
            _intish(x.get("n_se_ant")),
            _intish(x.get("delta")),
            (
                f"{float(x['delta_pct']):+.1f}%"
                if x.get("delta_pct") is not None
                else "—"
            ),
            str(x.get("tendencia") or "→"),
            _intish(x.get("positivos")),
            _pct_str(x.get("positividade")),
        ]
        for i, x in enumerate(p.top_notificacoes[:10], 1)
    ]
    pos_rows = [
        [
            str(i),
            str(x.get("target", "—")),
            str(x.get("positividade", "—")),
            (
                f"{float(x['delta_pct']):+.1f}%"
                if x.get("delta_pct") is not None
                else "—"
            ),
            str(x.get("tendencia") or "→"),
            str(x.get("exames", "—")),
        ]
        for i, x in enumerate(p.top_positividade[:10], 1)
    ]
    comp_rows = [
        [
            str(c.get("target", "—")),
            str(c.get("metrica", "—")),
            _intish(c.get("valor_se")),
            _fmt_delta(
                c.get("delta_abs_se1"), c.get("delta_pct_se1"), c.get("tendencia_se1", "→")
            ),
            _fmt_delta(
                c.get("delta_abs_se2"), c.get("delta_pct_se2"), c.get("tendencia_se2", "→")
            ),
            _intish(c.get("mediana_4se")),
            (
                "acima mediana 4 SE"
                if c.get("acima_mediana_4se")
                else "—"
            ),
        ]
        for c in p.comparacao_semanas[:12]
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
        casos_html += f"<h4 style='color:#1B3281'>{esc(c.titulo)} · {esc(c.severidade)}</h4>"
        casos_html += f"<p><b>Sinal lab:</b> {esc(c.sinal_lab)}</p>"
        casos_html += "<p><b>Critérios Guia MS a verificar</b></p><ul>"
        casos_html += "".join(f"<li>{esc(i)}</li>" for i in c.criterios_guia)
        casos_html += "</ul><p><b>O que NÃO afirmar</b></p><ul>"
        casos_html += "".join(f"<li>{esc(i)}</li>" for i in c.o_que_nao_afirmar)
        casos_html += "</ul><p><b>Investigar</b></p><ul>"
        casos_html += "".join(f"<li>{esc(i)}</li>" for i in c.o_que_investigar)
        casos_html += (
            f"</ul><p style='background:#f0f4fa;border-left:4px solid #1B3281;"
            f"padding:8px 12px'>{esc(c.veredito)}</p>"
        )

    dest_html = ""
    for block in p.recomendacoes_por_agravo:
        dest_html += (
            f"<h4>{esc(block.get('municipio'))} × {esc(block.get('agravo'))} "
            f"({esc(block.get('severidade'))})</h4>"
        )
        dest_html += f"<p style='font-size:12px;color:#5a6a85'>{esc(block.get('evidencia'))}</p><ul>"
        for dest, texto in (block.get("destinatarios") or {}).items():
            dest_html += f"<li><b>{esc(dest)}:</b> {esc(texto)}</li>"
        dest_html += "</ul>"
    if not dest_html:
        for area, items in p.recomendacoes.items():
            dest_html += f"<h4>{esc(area)}</h4><ul>"
            dest_html += "".join(f"<li>{esc(i)}</li>" for i in items)
            dest_html += "</ul>"

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
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">2. Top 10 — {esc(rotulo)}</h3>
{table(["#", "Agravo", "n_se", "n_se_ant", "Δ", "Δ%", "Tend.", "Positivos", "Positividade"], notif_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">3. Top 10 positividade</h3>
{table(["#", "Agravo", "Positividade", "Δ% vs SE-1", "Tend.", "Exames"], pos_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">4. Comparação SE-1 / SE-2 / mediana 4 SE</h3>
{table(["Agravo", "Métrica", "SE", "Δ SE-1", "Δ SE-2", "Mediana 4SE", "Flag"], comp_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">5. Top localidades</h3>
{table(["Agravo", "Município", "Positivos", "Exames", "Positividade"], loc_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">6. Vizinhos</h3>
{table(["Agravo", "Par", "Positivos", "Dist. km"], viz_rows)}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7. Riscos / dispersão</h3>
{risco_html}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7b. GAL×SINAN (qualquer agravo)</h3>
{table(["Município", "Família", "Exames", "Notif.", "Flag"], [
    [str(g.get("municipio","—")), str(g.get("familia", g.get("target","—"))),
     _intish(g.get("exames")), _intish(g.get("notificacoes")), str(g.get("flag","—"))]
    for g in p.gal_sinan[:12]
])}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7c. Geo ({esc(p.geo_nivel)})</h3>
<p style="font-size:12px;color:#5a6a85">{esc(p.geo_nota)}</p>
{table(["Município", "Local", "Agravo", "N", "IBGE"], [
    [str(h.get("municipio","—")), str(h.get("local","—")), str(h.get("agravo","—")),
     _intish(h.get("n")), str(h.get("codigo_ibge") or "")]
    for h in p.geo_hotspots[:12]
])}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7d. Cruzamento de bases</h3>
{table(["Fonte", "Status", "Quando agrega"], [
    [str(c.get("fonte","—")), str(c.get("status","—")), str(c.get("quando_agrega","—"))]
    for c in p.cruzamento_bases
])}
<p style="font-size:12px">Ver <code>conhecimento_ve/cruzamento_bases.md</code>.</p>
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7e. Cruzamento SIH/SIA (VW_INTERNACAO)</h3>
{table(["Município", "Família CID", "N", "Fonte"], [
    [str(r.get("municipio","—")), str(r.get("cid_familia","—")),
     _intish(r.get("n")), str(r.get("fonte") or "SIH")]
    for r in ((p.cruzamento_sih_sia or {}).get("top_mun") or [])[:12]
])}
{f"<p style='font-size:12px;color:#5a6a85'><i>{esc(str((p.cruzamento_sih_sia or {}).get('caveat') or '')[:280])}</i></p>" if (p.cruzamento_sih_sia or {}).get("caveat") else "<p style='font-size:12px'>(sem agregados SIH/SIA)</p>"}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">7f. IndicaSUS / SISREG</h3>
{table(["Fonte", "Município/Tipo", "Status", "N"], (
    [
        ["IndicaSUS", str(r.get("tipo_leito","—")), str(r.get("situacao","—")), _intish(r.get("n"))]
        for r in ((p.sinais_rede or {}).get("indicasus_ocupacao_top") or [])[:6]
    ]
    + [
        ["SISREG/hosp", str(r.get("municipio","—")), str(r.get("status","—")), _intish(r.get("n"))]
        for r in ((p.sinais_rede or {}).get("sisreg_hosp_top") or [])[:6]
    ]
    + [
        ["SISREG/amb", str(r.get("municipio","—")), str(r.get("status","—")), _intish(r.get("n"))]
        for r in ((p.sinais_rede or {}).get("sisreg_amb_pendente_top") or [])[:4]
    ]
) if (p.sinais_rede or {}).get("presente") else [])}
{f"<p style='font-size:12px;color:#5a6a85'><i>{esc(str((p.sinais_rede or {}).get('caveat') or '')[:280])}</i></p>" if (p.sinais_rede or {}).get("presente") else "<p style='font-size:12px'>(sem IndicaSUS/SISREG no staging)</p>"}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">8. Casos especiais</h3>
{casos_html or "<p>(nenhum)</p>"}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">9. Recomendações por destinatário</h3>
{dest_html}
<h3 style="color:#1B3281;border-bottom:2px solid #1B3281">10. Citações</h3>
{cit_html}
<p style="font-size:12px;color:#5a6a85;margin-top:18px">
conhecimento_ve/ · lacen_agente_ve.py · lacen_briefing_epi.py
</p>
</td></tr></table></td></tr></table>
</body></html>"""


def _telegram_alerta_agravo(c: CasoEspecial, se_iso: str) -> str:
    comp = c.comparacao or {}
    delta = _fmt_delta(
        comp.get("delta_abs_se1"), comp.get("delta_pct_se1"), comp.get("tendencia_se1", "→")
    )
    flag = " · acima mediana 4SE" if comp.get("acima_mediana_4se") else ""
    return "\n".join(
        [
            f"<b>Alerta VE · {html.escape(c.severidade.upper())}</b>",
            html.escape(f"{c.municipio} × {c.target} · SE {se_iso}"),
            html.escape(
                f"{c.exames} ex. / +{c.positivos} ({c.positividade}) [Observado]"
            ),
            html.escape(f"Vs SE-1: {delta}{flag}"),
            html.escape(
                "Investigar (Guia MS) — NÃO declarar surto automaticamente."
            ),
        ]
    )


def _telegram_resumo(p: ParecerVE) -> str:
    lines = [
        "<b>Parecer VE (Guia MS)</b>",
        f"SE {html.escape(p.se_iso)}",
        "",
    ]
    alertas = p.telegram_alertas[:3]
    if alertas:
        for i, a in enumerate(alertas, 1):
            if i > 1:
                lines.append("")
            lines.append(a)
    elif p.casos_especiais:
        lines.append(_telegram_alerta_agravo(p.casos_especiais[0], p.se_iso))
    else:
        lines.append(html.escape((p.resumo_executivo or "")[:280]))
    top = p.top_notificacoes[:3] or p.top_solicitados[:3]
    if top:
        lines.append("")
        fonte = "SINAN" if p.fonte_notificacoes == "SINAN" else "proxy exames"
        lines.append(f"<i>Top ({html.escape(fonte)})</i>")
        for x in top:
            val = (
                x.get("notificacoes")
                if p.fonte_notificacoes == "SINAN"
                else x.get("exames")
            )
            lines.append(
                html.escape(
                    f"• {x.get('target')}: {_intish(val)} "
                    f"({_pct_str(x.get('positividade'))})"
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
                            "conforme Guia de Vigilância MS. Mencione comparação "
                            "com semanas anteriores se houver."
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


def _delta_fields(x: dict[str, Any]) -> dict[str, Any]:
    pct = x.get("delta_pct")
    return {
        "n_se": x.get("n_se", x.get("exames")),
        "n_se_ant": x.get("n_se_ant"),
        "delta": x.get("delta"),
        "delta_pct": pct,
        "delta_pct_str": f"{float(pct):+.1f}%" if pct is not None else "—",
        "tendencia": x.get("tendencia") or "→",
        "mediana_4se": x.get("mediana_4se"),
    }


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
            **_delta_fields(x),
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
            **_delta_fields(x),
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
            "municipio_ancora": v.get("municipio"),
            "vizinho": v.get("vizinho"),
            "positivos_ancora": v.get("positivos_ancora"),
            "positivos_vizinho": v.get("positivos_vizinho"),
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
    """Gera parecer VE completo: Top notif/proxy + positividade + ΔSE + destinatários."""
    outdir = Path(outdir)
    know = Path(know_dir)
    know.mkdir(parents=True, exist_ok=True)

    fontes_cache: list[dict[str, str]] = []
    if tentar_download_ms:
        fontes_cache = tentar_cachear_fontes_ms(know)

    if briefing is None:
        briefing = gerar_briefing_epi(outdir, se=se, top=top, persistir=True)

    weekly = _read_csv(outdir / WEEKLY_NAME)
    yw = briefing.se_tuple or _parse_se(briefing.se_iso)
    if yw is None and se:
        yw = _parse_se(se)

    top_notif: list[dict[str, Any]] = []
    fonte_notif = "proxy_exames_GAL"
    if yw and weekly:
        top_notif, fonte_notif = top_notificacoes(weekly, yw, top=top)
        metric = "notificacoes" if fonte_notif == "SINAN" else "exames"
        top_notif = enriquecer_top_com_delta(top_notif, weekly, yw, metric=metric)

    sol, posi, locs, viz, risco = _fmt_briefing_rows(briefing)

    # Targets para comparação: união de top notif + positividade + localidades foco
    targets_comp: list[str] = []
    for seq in (top_notif, briefing.maior_positividade, briefing.mais_solicitados):
        for x in seq[:8]:
            t = str(x.get("target") or "")
            if t and t not in targets_comp:
                targets_comp.append(t)
    for loc in briefing.localidades[:6]:
        t = str(loc.get("target") or "")
        if t and t not in targets_comp:
            targets_comp.append(t)

    comparacao: list[dict[str, Any]] = []
    if yw and weekly and targets_comp:
        comparacao = comparar_com_semanas_anteriores(
            weekly, yw, targets_comp[:12], n_anteriores=4
        )

    casos = _detectar_casos_especiais(briefing, comparacao, briefing.vizinhos)
    familias = list(
        dict.fromkeys(
            [_familia_de_target(str(x.get("target") or "")) for x in (top_notif or sol)[:5]]
            + [_familia_de_target(c.target) for c in casos]
        )
    )
    trechos = recuperar_trechos(familias, know)
    recs, por_agravo, acoes = _recomendacoes_por_destinatario(briefing, casos, trechos)

    geo = briefing.geo or {}
    parecer = ParecerVE(
        se_iso=briefing.se_iso,
        resumo_executivo=_resumo_executivo(
            briefing, casos, fonte_notif, comparacao
        ),
        top_notificacoes=top_notif or [
            {
                "target": x["target"],
                "exames": x.get("exames"),
                "positivos": x.get("positivos"),
                "positividade": x.get("positividade"),
                "notificacoes": 0,
                "fonte_metrica": "proxy_exames_GAL",
                **{k: x.get(k) for k in ("n_se", "n_se_ant", "delta", "delta_pct", "tendencia", "mediana_4se")},
            }
            for x in sol
        ],
        fonte_notificacoes=fonte_notif,
        top_solicitados=sol,
        top_positividade=posi,
        comparacao_semanas=comparacao,
        top_localidades=locs,
        top_vizinhos=viz,
        top_riscos=risco,
        gal_sinan=list(briefing.gal_sinan or [])[:25],
        geo_nivel=str(geo.get("nivel") or "municipio"),
        geo_nota=str(geo.get("nota") or ""),
        geo_hotspots=list(geo.get("hotspots") or [])[:15],
        cruzamento_bases=list(briefing.cruzamento_bases or []),
        cruzamento_sih_sia=dict(briefing.cruzamento_sih_sia or {}),
        sinais_rede=dict(briefing.sinais_rede or {}),
        casos_especiais=casos,
        recomendacoes=recs,
        recomendacoes_por_agravo=por_agravo,
        acoes_csv=acoes,
        citacoes=trechos,
        fontes_cache=fontes_cache,
    )
    parecer.telegram_alertas = [
        _telegram_alerta_agravo(c, parecer.se_iso) for c in casos[:3]
    ]
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
    with paths["csv"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for row in parecer.acoes_csv:
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    meta = {
        "se": parecer.se_iso,
        "gerado_em": parecer.gerado_em,
        "fonte_notificacoes": parecer.fonte_notificacoes,
        "n_casos_especiais": len(parecer.casos_especiais),
        "casos": [
            {
                "municipio": c.municipio,
                "target": c.target,
                "exames": c.exames,
                "positivos": c.positivos,
                "positividade": c.positividade,
                "severidade": c.severidade,
                "comparacao": {
                    k: c.comparacao.get(k)
                    for k in (
                        "delta_abs_se1",
                        "delta_pct_se1",
                        "tendencia_se1",
                        "mediana_4se",
                        "acima_mediana_4se",
                        "metrica",
                    )
                    if c.comparacao
                },
            }
            for c in parecer.casos_especiais
        ],
        "comparacao_semanas": [
            {
                "target": c.get("target"),
                "metrica": c.get("metrica"),
                "valor_se": c.get("valor_se"),
                "delta_pct_se1": c.get("delta_pct_se1"),
                "tendencia_se1": c.get("tendencia_se1"),
                "acima_mediana_4se": c.get("acima_mediana_4se"),
            }
            for c in parecer.comparacao_semanas[:12]
        ],
        "recomendacoes_por_agravo": parecer.recomendacoes_por_agravo,
        "usou_llm": parecer.usou_llm,
        "citacoes": [c.get("fonte") for c in parecer.citacoes],
        "fontes_cache": parecer.fontes_cache,
        "cruzamento_sih_sia": parecer.cruzamento_sih_sia or {},
        "sinais_rede": parecer.sinais_rede or {},
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
        "fonte_notificacoes": parecer.fonte_notificacoes,
        "comparacao": parecer.comparacao_semanas[:8],
        "casos": [
            {
                "titulo": c.titulo,
                "municipio": c.municipio,
                "target": c.target,
                "exames": c.exames,
                "positivos": c.positivos,
                "positividade": c.positividade,
                "veredito": c.veredito,
                "severidade": c.severidade,
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
        "recomendacoes_por_agravo": parecer.recomendacoes_por_agravo,
        "arquivos": [REL_MD, REL_HTML, REL_CSV],
        "usou_llm": parecer.usou_llm,
    }


def juina_hbv_one_liner(parecer: ParecerVE | None = None) -> str:
    """One-liner para o agente pai relay sobre Juína HBV."""
    if parecer is None:
        meta_path = OUTDIR_DEFAULT / REL_JSON
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                for c in meta.get("casos") or []:
                    if "JUINA" in str(c.get("municipio", "")).upper() and "hepatite" in str(
                        c.get("target", "")
                    ).casefold():
                        comp = c.get("comparacao") or {}
                        delta = ""
                        if comp.get("delta_pct_se1") is not None:
                            delta = (
                                f" · vs SE-1 {comp.get('tendencia_se1', '→')} "
                                f"{comp.get('delta_pct_se1'):+.0f}%"
                            )
                        return (
                            f"Juína HBV SE {meta.get('se')}: {c.get('exames')} exames / "
                            f"+{c.get('positivos')} ({c.get('positividade')}) [Observado]"
                            f"{delta} — sinal lab; NÃO declarar surto automático; "
                            "investigar marcador agudo×crônico e critérios Guia MS."
                        )
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return (
            "Juína HBV: sinal laboratorial elevado no Observado — "
            "investigar segundo Guia MS; não declarar surto automaticamente."
        )
    for c in parecer.casos_especiais:
        if "JUINA" in c.municipio.upper() and "hepatite" in c.target.casefold():
            comp = c.comparacao or {}
            delta = ""
            if comp.get("delta_pct_se1") is not None:
                delta = (
                    f" · vs SE-1 {comp.get('tendencia_se1', '→')} "
                    f"{float(comp['delta_pct_se1']):+.0f}%"
                )
            return (
                f"Juína HBV SE {parecer.se_iso}: {c.exames} exames / "
                f"+{c.positivos} ({c.positividade}) [Observado]{delta} — "
                "sinal lab; critérios de surto do Guia MS exigem definição de "
                "caso agudo + esperado + investigação; NÃO declarar surto só "
                "com positividade GAL."
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
