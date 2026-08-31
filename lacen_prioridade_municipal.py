#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Score de prioridade municipal (proposta p/ homologação CIEVS) +
alertas específicos por sinal + pendências do modelo definitivo.

score = 3*excesso_lab + 2*positividade_anomala + 1*lacuna_sinan + 1*internacoes_graves
Componentes normalizados 0–1 de forma transparente.
"""
from __future__ import annotations

import csv
import html
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"

SCORE_CSV = "score_prioridade_municipal.csv"
PENDENCIAS_MD = "modelo_definitivo_pendencias.md"
ALERTAS_DIR = "alertas_especificos"


def _num(val: Any, default: float | None = None) -> float | None:
    if val is None or val == "":
        return default
    try:
        x = float(str(val).replace("%", "").replace(",", ".").strip())
        if math.isnan(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def _norm_mun(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().upper()


def _slug(text: str) -> str:
    t = (
        str(text or "")
        .casefold()
        .replace("á", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t[:48] or "x"


def _norm01(values: Sequence[float]) -> list[float]:
    """Min-max 0–1; se todos iguais, retorna 0."""
    xs = [float(v) for v in values]
    if not xs:
        return []
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return [0.0 for _ in xs]
    return [(v - lo) / (hi - lo) for v in xs]


def _pct_frase(delta_pct: float | None) -> str:
    if delta_pct is None:
        return "sem comparação com a semana anterior"
    d = float(delta_pct)
    pct = f"{abs(d):.0f}".replace(".", ",")
    if d > 0.5:
        return f"subiu {pct}% em relação à semana anterior"
    if d < -0.5:
        return f"caiu {pct}% em relação à semana anterior"
    return "quase estável em relação à semana anterior"


def calcular_score_prioridade_municipal(
    *,
    localidades: Sequence[dict[str, Any]] | None = None,
    solicitados: Sequence[dict[str, Any]] | None = None,
    positividade: Sequence[dict[str, Any]] | None = None,
    gal_sinan: Sequence[dict[str, Any]] | None = None,
    cruzamento_sih_sia: dict[str, Any] | None = None,
    se_iso: str = "—",
) -> list[dict[str, Any]]:
    """
    Proposta para homologação CIEVS.

    score = 3*excesso_lab + 2*positividade_anomala + 1*lacuna_sinan + 1*internacoes_graves
    Cada componente é normalizado 0–1 entre os municípios candidatos.
    """
    # Agrega por município
    by_mun: dict[str, dict[str, float]] = {}

    def _row(mun: str) -> dict[str, float]:
        m = _norm_mun(mun)
        if not m or m in {"—", "-", "*ESTADO*"}:
            return {}
        return by_mun.setdefault(
            m,
            {
                "excesso_lab_raw": 0.0,
                "pos_anomala_raw": 0.0,
                "lacuna_raw": 0.0,
                "intern_raw": 0.0,
                "exames": 0.0,
                "positivos": 0.0,
            },
        )

    # Excesso lab: Δ% positivo de demanda (solicitados) + volume local
    delta_by_tgt: dict[str, float] = {}
    for s in solicitados or []:
        tgt = str(s.get("target") or "")
        d = _num(s.get("delta_pct"))
        if tgt and d is not None and d > 0:
            delta_by_tgt[tgt] = max(delta_by_tgt.get(tgt, 0.0), float(d))

    for loc in localidades or []:
        r = _row(str(loc.get("municipio") or ""))
        if not r:
            continue
        ex = _num(loc.get("exames"), 0) or 0
        pos = _num(loc.get("positivos"), 0) or 0
        r["exames"] += ex
        r["positivos"] += pos
        dlt = _num(loc.get("delta_pct"))
        if dlt is None:
            dlt = delta_by_tgt.get(str(loc.get("target") or ""), 0.0)
        # excesso: volume * max(0, delta%/100)
        r["excesso_lab_raw"] += ex * max(0.0, float(dlt or 0) / 100.0)
        pv = _num(loc.get("positividade"))
        if pv is not None and not loc.get("caveat_igg"):
            # anomalia simples: positividade * positivos (peso amostra)
            r["pos_anomala_raw"] = max(
                r["pos_anomala_raw"], float(pv) * max(1.0, pos)
            )

    for p in positividade or []:
        # Sem município: contribui pouco via flag estadual — skip mun-level
        if p.get("caveat_igg"):
            continue
        pv = _num(p.get("positividade"))
        if pv is None:
            continue
        # reforça municípios já listados com mesma família/target
        tgt = str(p.get("target") or "")
        for loc in localidades or []:
            if str(loc.get("target") or "") != tgt:
                continue
            r = _row(str(loc.get("municipio") or ""))
            if not r:
                continue
            r["pos_anomala_raw"] = max(
                r["pos_anomala_raw"],
                float(pv) * max(1.0, _num(loc.get("positivos"), 0) or 0),
            )

    for g in gal_sinan or []:
        if not (g.get("gal_sem_sinan") or str(g.get("flag") or "") == "gal_sem_sinan"):
            continue
        r = _row(str(g.get("municipio") or ""))
        if not r:
            continue
        r["lacuna_raw"] += _num(g.get("exames"), 0) or 0

    for row in (cruzamento_sih_sia or {}).get("top_mun") or []:
        r = _row(str(row.get("municipio") or ""))
        if not r:
            continue
        r["intern_raw"] += _num(row.get("n"), 0) or 0

    if not by_mun:
        return []

    muns = sorted(by_mun.keys())
    excesso = _norm01([by_mun[m]["excesso_lab_raw"] for m in muns])
    pos_a = _norm01([by_mun[m]["pos_anomala_raw"] for m in muns])
    lacuna = _norm01([by_mun[m]["lacuna_raw"] for m in muns])
    intern = _norm01([by_mun[m]["intern_raw"] for m in muns])

    out: list[dict[str, Any]] = []
    for i, m in enumerate(muns):
        e, p, l, g = excesso[i], pos_a[i], lacuna[i], intern[i]
        score = 3.0 * e + 2.0 * p + 1.0 * l + 1.0 * g
        out.append(
            {
                "se": se_iso,
                "municipio": m,
                "excesso_lab_0_1": round(e, 4),
                "positividade_anomala_0_1": round(p, 4),
                "lacuna_sinan_0_1": round(l, 4),
                "internacoes_graves_0_1": round(g, 4),
                "score": round(score, 4),
                "exames": int(by_mun[m]["exames"]),
                "positivos": int(by_mun[m]["positivos"]),
                "rotulo": "proposta para homologação",
                "formula": (
                    "score = 3*excesso_lab + 2*positividade_anomala "
                    "+ 1*lacuna_sinan + 1*internacoes_graves "
                    "(componentes normalizados 0–1)"
                ),
            }
        )
    out.sort(key=lambda x: -float(x["score"]))
    return out


def persistir_score_prioridade(
    rows: Sequence[dict[str, Any]], outdir: Path | str = OUTDIR_DEFAULT
) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / SCORE_CSV
    fields = [
        "se",
        "municipio",
        "excesso_lab_0_1",
        "positividade_anomala_0_1",
        "lacuna_sinan_0_1",
        "internacoes_graves_0_1",
        "score",
        "exames",
        "positivos",
        "rotulo",
        "formula",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})
    return path


def filtrar_sih_para_sinais(
    cruzamento_sih_sia: dict[str, Any] | None,
    *,
    municipios_sinal: Sequence[str],
    familias: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Mantém internações SIH dos municípios em alta positividade / pico de demanda
    (não só tops genéricos do estado).
    """
    base = dict(cruzamento_sih_sia or {})
    want = {_norm_mun(m) for m in municipios_sinal if m}
    fam_want = {str(f).casefold() for f in (familias or []) if f}
    top = list(base.get("top_mun") or [])
    filtrado = []
    for row in top:
        mun = _norm_mun(row.get("municipio"))
        if want and mun not in want:
            continue
        fam = str(row.get("cid_familia") or "").casefold()
        if fam_want and not any(f in fam or fam in f for f in fam_want):
            # ainda inclui se município está no sinal (gravidade local)
            pass
        filtrado.append(dict(row))
    # Se filtro esvaziou mas há sinais, tenta agregar do staging externo via top original
    # apenas dos muns desejados (já feito). Se vazio, mantém caveat.
    out = dict(base)
    out["top_mun"] = filtrado[:20]
    out["filtro"] = "municipios_em_sinal_positividade_ou_demanda"
    out["municipios_filtro"] = sorted(want)
    if filtrado:
        out["caveat"] = (
            "Internações (Sistema de Informações Hospitalares — SIH) "
            "restritas aos municípios com sinal de positividade ou pico de demanda. "
            "Correlação por família de CID; não confirma surto."
        )
    else:
        out["caveat"] = (
            str(base.get("caveat") or "")
            + " Sem internações SIH nos municípios do sinal nesta remessa."
        ).strip()
    return out


def vizinhos_a_partir_do_sinal(
    weekly: Sequence[dict[str, Any]],
    vizinhos_rows: Sequence[dict[str, Any]],
    se: tuple[int, int],
    *,
    municipio_ancora: str,
    target: str,
    max_viz: int = 8,
) -> list[dict[str, Any]]:
    """
    Parte do município citado no sinal e compara positividade/demanda nos vizinhos.
    """
    from lacen_briefing_epi import (
        _filter_se,
        _norm_mun as _nm,
        _num as _n,
        _vizinhos_index,
    )

    ancora = _nm(municipio_ancora)
    tgt = str(target or "").strip()
    if not ancora or not tgt:
        return []
    rows = [
        r
        for r in _filter_se(list(weekly), se)
        if str(r.get("target") or "").strip() == tgt
    ]
    pos_by: dict[str, float] = {}
    ex_by: dict[str, float] = {}
    for r in rows:
        mun = _nm(r.get("municipio"))
        pos_by[mun] = pos_by.get(mun, 0.0) + (_n(r.get("positives"), 0) or 0)
        ex_by[mun] = ex_by.get(mun, 0.0) + (_n(r.get("tests"), 0) or 0)

    vidx = _vizinhos_index(list(vizinhos_rows))
    out: list[dict[str, Any]] = []
    for viz, dist in vidx.get(ancora, [])[: max_viz * 2]:
        out.append(
            {
                "target": tgt,
                "municipio": ancora,
                "vizinho": viz,
                "positivos_ancora": pos_by.get(ancora, 0.0),
                "positivos_vizinho": pos_by.get(viz, 0.0),
                "exames_ancora": ex_by.get(ancora, 0.0),
                "exames_vizinho": ex_by.get(viz, 0.0),
                "positividade_ancora": (
                    (pos_by.get(ancora, 0) / ex_by[ancora])
                    if ex_by.get(ancora, 0) > 0
                    else None
                ),
                "positividade_vizinho": (
                    (pos_by.get(viz, 0) / ex_by[viz]) if ex_by.get(viz, 0) > 0 else None
                ),
                "dist_km": dist,
                "origem_analise": "ancora_do_sinal",
                "tipo_sinal": "Observado",
            }
        )
        if len(out) >= max_viz:
            break
    return out


def coletar_lacunas_vigilancia(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    municipios: Sequence[str] | None = None,
    top: int = 40,
) -> list[dict[str, Any]]:
    """
    Lacunas além de GAL×SINAN: varre staging (SINAN views, IndicaSUS, SISREG, SIM)
    e registra presença/ausência por fonte, com foco nos municípios do sinal.
    """
    from lacen_briefing_epi import _read_csv, inventariar_cruzamento_bases

    outdir = Path(outdir)
    stage = outdir / "staging_dw"
    want = {_norm_mun(m) for m in (municipios or []) if m}
    inv = inventariar_cruzamento_bases(outdir)
    out: list[dict[str, Any]] = []

    for row in inv:
        fonte = str(row.get("fonte") or "")
        # Evita misturar SIVEP-gripe como bloco padrão de vírus respiratórios
        if fonte.upper().startswith("SIVEP"):
            out.append(
                {
                    "fonte": fonte,
                    "tipo": "inventario",
                    "municipio": "—",
                    "status": row.get("status"),
                    "detalhe": (
                        "Base respiratória/SRAG listada só como inventário — "
                        "não entra como seção padrão do Radar salvo sinal explícito."
                    ),
                    "presente": bool(row.get("presente")),
                }
            )
            continue
        out.append(
            {
                "fonte": fonte,
                "tipo": "inventario",
                "municipio": "—",
                "status": row.get("status"),
                "detalhe": row.get("quando_agrega") or "",
                "presente": bool(row.get("presente")),
            }
        )

    # GAL sem SINAN (órfãos) — já é lacuna clássica
    gs = outdir / "briefing_gal_sinan_divergencia.csv"
    if gs.exists():
        for r in _read_csv(gs):
            if str(r.get("flag") or "") != "gal_sem_sinan" and not str(
                r.get("gal_sem_sinan") or ""
            ).lower() in {"1", "true", "sim"}:
                continue
            mun = _norm_mun(r.get("municipio"))
            if want and mun not in want:
                continue
            out.append(
                {
                    "fonte": "GAL×SINAN",
                    "tipo": "exame_sem_notificacao",
                    "municipio": mun,
                    "status": "gal_sem_sinan",
                    "detalhe": (
                        f"família {r.get('familia')}: "
                        f"{r.get('exames')} exames sem notificação na SE"
                    ),
                    "presente": True,
                    "exames": r.get("exames"),
                    "familia": r.get("familia"),
                }
            )

    # SIM óbitos (se houver município)
    sim_path = stage / "sim.csv"
    if sim_path.exists() and want:
        try:
            rows = _read_csv(sim_path)
            # Amostra limitada
            hits = 0
            for r in rows[:5000]:
                mun = _norm_mun(
                    r.get("municipio")
                    or r.get("Municipio")
                    or r.get("mun_ocor")
                    or r.get("mun_resid")
                    or ""
                )
                if mun in want:
                    hits += 1
            out.append(
                {
                    "fonte": "SIM",
                    "tipo": "cobertura",
                    "municipio": ",".join(sorted(want)[:5]),
                    "status": "amostra_staging",
                    "detalhe": f"{hits} linhas SIM tocando municípios do sinal (amostra)",
                    "presente": True,
                }
            )
        except OSError:
            pass

    return out[:top]


def escrever_alertas_especificos(
    *,
    se_iso: str,
    cartoes: Sequence[dict[str, Any]],
    localidades: Sequence[dict[str, Any]] | None = None,
    vizinhos: Sequence[dict[str, Any]] | None = None,
    gal_sinan: Sequence[dict[str, Any]] | None = None,
    cruzamento_sih_sia: dict[str, Any] | None = None,
    lacunas: Sequence[dict[str, Any]] | None = None,
    marcadores: Sequence[dict[str, Any]] | None = None,
    outdir: Path | str = OUTDIR_DEFAULT,
    max_alertas: int = 8,
) -> list[Path]:
    """
    Gera alerta_{agravo}_{municipio}_{se}.md (+ html) para sinais prioritários.
    """
    outdir = Path(outdir)
    dest = outdir / ALERTAS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    se_slug = _slug(se_iso.replace("/", "_"))

    # Prioriza cartões com veredito alto/médio
    ranked = sorted(
        list(cartoes or []),
        key=lambda c: (
            0
            if str(c.get("probabilidade") or "").casefold() == "alto"
            else 1
            if str(c.get("probabilidade") or "").casefold() in {"médio", "medio"}
            else 2,
            -float(_num(c.get("score"), 0) or 0),
        ),
    )

    for card in ranked[:max_alertas]:
        mun = _norm_mun(card.get("municipio"))
        tgt = str(
            card.get("agravo")
            or card.get("target")
            or card.get("familia")
            or "agravo"
        ).strip()
        # Evita "dengue × CUIABA" no slug
        if "×" in tgt or " x " in tgt.casefold():
            tgt = tgt.split("×")[0].split(" x ")[0].strip()
        if not mun or mun == "—":
            continue
        # Filtra vírus respiratórios genéricos sem sinal explícito no cartão
        tcf = tgt.casefold()
        if any(k in tcf for k in ("respirat", "influenza", "srag", "covid", "sivep")):
            # só mantém se probabilidade alta
            if str(card.get("probabilidade") or "").casefold() != "alto":
                continue

        fname = f"alerta_{_slug(tgt)}_{_slug(mun)}_{se_slug}"
        md_path = dest / f"{fname}.md"
        html_path = dest / f"{fname}.html"

        locs = [
            L
            for L in (localidades or [])
            if _norm_mun(L.get("municipio")) == mun
            and (
                str(L.get("target") or "") == tgt
                or _slug(str(L.get("target") or "")) == _slug(tgt)
            )
        ]
        viz = [
            v
            for v in (vizinhos or [])
            if _norm_mun(v.get("municipio")) == mun
            or _norm_mun(v.get("vizinho")) == mun
        ]
        gaps = [
            g
            for g in (gal_sinan or [])
            if _norm_mun(g.get("municipio")) == mun
        ]
        sih_rows = [
            r
            for r in (cruzamento_sih_sia or {}).get("top_mun") or []
            if _norm_mun(r.get("municipio")) == mun
        ]
        marks = [
            m
            for m in (marcadores or [])
            if _norm_mun(m.get("municipio")) in {mun, "—", ""}
            and (
                "hepat" in str(m.get("familia") or "")
                or _slug(tgt) in _slug(str(m.get("familia") or ""))
                or True
            )
        ][:8]
        lac_loc = [
            x
            for x in (lacunas or [])
            if _norm_mun(x.get("municipio")) in {mun, "—", ""}
            or mun in str(x.get("municipio") or "").upper()
        ][:10]

        dlt = _num(card.get("delta_pct"))
        var = _pct_frase(dlt)
        acoes = card.get("acoes") if isinstance(card.get("acoes"), dict) else {}

        lines = [
            f"# Alerta específico — {tgt} × {mun}",
            "",
            f"**Semana epidemiológica:** {se_iso}",
            f"**Destinatários:** área técnica · Vigilância Epidemiológica (VE) municipal · CIEVS",
            "",
            "> **Aviso:** este documento é sinal para investigação. "
            "**Não declara surto nem epidemia automaticamente.**",
            "",
            "## 1. Evidência",
            "",
            f"- Agravo/alvo: **{tgt}**",
            f"- Município: **{mun}**",
            f"- Exames: {card.get('exames', '—')} · positivos: {card.get('positivos', '—')}",
            f"- Positividade: {card.get('positividade', '—')}",
            f"- Variação: {var}",
            f"- Probabilidade: {card.get('probabilidade', '—')} · "
            f"Impacto: {card.get('impacto', '—')} · "
            f"Confiança: {card.get('confianca', '—')}",
            f"- Veredito operacional: {card.get('veredito', '—')}",
            "",
            "## 2. Interpretação de marcadores",
            "",
        ]
        if marks:
            for m in marks:
                if str(m.get("classe") or "") == "nao_agudo_soroprevalencia":
                    continue
                lines.append(
                    f"- {m.get('marcador')} ({m.get('metodologia') or 'método n/d'}): "
                    f"{m.get('n_positivos', 0)} positivos / {m.get('n_exames', 0)} exames "
                    f"— {m.get('nota_pt', '')}"
                )
            # caveat IgG
            if any(
                str(m.get("classe")) == "nao_agudo_soroprevalencia" for m in marks
            ):
                lines.append(
                    "- Caveat: IgG / anti-HBs / soroprevalência **não** elevam alerta agudo."
                )
        else:
            lines.append(
                "- Marcadores nominais indisponíveis nesta remessa ou sem micro GAL "
                "para o município — usar painel do laudo (HBsAg / IgM / DNA quando HBV)."
            )

        lines.extend(["", "## 3. Taxas e local", ""])
        if locs:
            for L in locs[:5]:
                frase = L.get("frase_taxa_positivos") or ""
                lines.append(
                    f"- {L.get('municipio')}: +{L.get('positivos')} "
                    f"({L.get('positividade', '—')})"
                    + (f" · {frase}" if frase else "")
                )
        else:
            lines.append("- Sem detalhe municipal adicional além do cartão.")

        lines.extend(["", "## 4. Vizinhos (a partir do município do sinal)", ""])
        if viz:
            for v in viz[:6]:
                lines.append(
                    f"- {v.get('municipio')} ↔ {v.get('vizinho')}: "
                    f"+{v.get('positivos_ancora')}/+{v.get('positivos_vizinho')} "
                    f"(exames {v.get('exames_ancora')}/{v.get('exames_vizinho')})"
                )
        else:
            lines.append(
                "- Sem pares vizinhos com o mesmo alvo a partir deste município nesta SE."
            )

        lines.extend(["", "## 5. Internações (SIH)", ""])
        if sih_rows:
            for r in sih_rows[:6]:
                lines.append(
                    f"- {r.get('municipio')} × {r.get('cid_familia')}: "
                    f"n={r.get('n')} [{r.get('fonte', 'SIH')}]"
                )
        else:
            lines.append("- Sem internações SIH filtradas para este município/sinal.")

        lines.extend(["", "## 6. Lacunas de vigilância", ""])
        if gaps:
            for g in gaps[:6]:
                lines.append(
                    f"- GAL×SINAN: {g.get('flag')} — "
                    f"{g.get('exames')} exames / {g.get('notificacoes')} notificações "
                    f"({g.get('familia')})"
                )
        for x in lac_loc[:6]:
            if x.get("fonte") == "GAL×SINAN":
                continue
            lines.append(
                f"- {x.get('fonte')}: {x.get('detalhe') or x.get('status')} "
                f"[{'presente' if x.get('presente') else 'ausente'}]"
            )
        if not gaps and not lac_loc:
            lines.append("- Sem lacunas adicionais registradas.")

        lines.extend(
            [
                "",
                "## 7. Ações sugeridas",
                "",
                f"- CIEVS: {acoes.get('CIEVS') or card.get('acao_cievs') or '—'}",
                f"- VE municipal: {acoes.get('VE municipal') or card.get('acao_ve_mun') or '—'}",
                f"- Área técnica: {acoes.get('área técnica') or card.get('acao_area_tecnica') or '—'}",
                f"- Vizinhos: {acoes.get('vizinhos') or card.get('acao_vizinhos') or '—'}",
                f"- LACEN: {acoes.get('LACEN') or card.get('acao_lacen') or '—'}",
                "",
                "## 8. Disclaimer",
                "",
                "Radar LACEN / CIEVS — sinal operacional. "
                "A declaração de surto, epidemia ou emergência cabe à VE "
                "após definição de caso, investigação e critérios do Guia MS.",
                "",
                f"_Gerado em {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')}_",
            ]
        )
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        body_html = "<br/>\n".join(
            html.escape(ln) if not ln.startswith("#") else f"<h2>{html.escape(ln.lstrip('#').strip())}</h2>"
            for ln in lines
            if ln != ""
        )
        html_path.write_text(
            "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'/>"
            f"<title>{html.escape(fname)}</title></head><body>"
            f"<pre style='font-family:Segoe UI,Arial,sans-serif;white-space:pre-wrap'>"
            f"{html.escape(md_path.read_text(encoding='utf-8'))}</pre>"
            "</body></html>\n",
            encoding="utf-8",
        )
        written.append(md_path)
    return written


def gerar_modelo_pendencias(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    marcadores_payload: dict[str, Any] | None = None,
    weekly_n_se: int | None = None,
    pop_ano_nota: str = "",
) -> Path:
    """
    Documenta o que o modelo definitivo pede vs o que os dados permitem agora.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / PENDENCIAS_MD
    dedup = (marcadores_payload or {}).get("deduplicacao_paciente") or {}
    n_micro = (marcadores_payload or {}).get("n_registros_micro", 0)

    bortman_status = "Stub"
    bortman_nota = (
        f"Histórico semanal disponível ≈ {weekly_n_se if weekly_n_se is not None else 'n/d'} "
        "células; canal completo exige ≥3 anos da mesma SE no baseline (método Bortman). "
        "Stub: razão vs mediana das últimas SE disponíveis quando a série for curta."
    )
    bortman_section = [
        "## Canal endêmico Bortman (stub)",
        "",
        "Quando a série semanal por município×agravo tiver pelo menos 3 anos da mesma "
        "semana epidemiológica no baseline (excluindo o ano atual), calcular P25/P50/P75 "
        "e classificar zonas sucesso / seguranca / alerta / epidemia. "
        "**Nesta remessa:** não calcular falso canal — apenas registrar pendência.",
        "",
    ]
    canal_csv = outdir / "canal_endemico_classificacao.csv"
    if canal_csv.exists():
        try:
            import csv as _csv

            with canal_csv.open(encoding="utf-8-sig", newline="") as f:
                rows = list(_csv.DictReader(f))
            n_tot = len(rows)
            n_ok = sum(
                1
                for r in rows
                if str(r.get("zona") or "").casefold() not in {"", "sem_dado"}
            )
            n_risco = sum(
                1
                for r in rows
                if str(r.get("zona") or "").casefold() in {"alerta", "epidemia"}
            )
            if n_ok > 0:
                bortman_status = "Implementado"
                bortman_nota = (
                    f"Módulo `ml/canal_endemico_bortman.py` → "
                    f"`canal_endemico.xlsx` + `canal_endemico_classificacao.csv` "
                    f"({n_tot} combinações SE atual; {n_ok} classificadas; "
                    f"{n_risco} em alerta/epidemia). "
                    "Série preferencial: positivos laboratoriais; NA não vira zero; "
                    "<3 anos baseline → sem_dado. Radar reforça score se zona alerta/epidemia."
                )
                bortman_section = [
                    "## Canal endêmico Bortman (implementado)",
                    "",
                    "Método Bortman (P25/P50/P75) sobre os últimos 5 anos excl. ano atual, "
                    "mesma SE. Zonas: sucesso / seguranca / alerta / epidemia / sem_dado. "
                    "Saídas: `canal_endemico.xlsx` (Classificacao, Limites, Metadados) e "
                    "`canal_endemico_classificacao.csv` para join no Radar.",
                    "",
                ]
            else:
                bortman_status = "Parcial"
                bortman_nota = (
                    f"Arquivo gerado ({n_tot} linhas), mas todas em sem_dado "
                    "(série ainda curta por município×agravo×SE)."
                )
                bortman_section = [
                    "## Canal endêmico Bortman (parcial)",
                    "",
                    "Módulo presente; classificação ainda limitada por histórico insuficiente "
                    "em várias combinações (<3 anos baseline com observação).",
                    "",
                ]
        except OSError:
            pass

    lines = [
        "# Modelo definitivo — pendências (Radar LACEN / CIEVS)",
        "",
        f"Atualizado: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "Este arquivo lista campos do modelo desejado: **implementado** com os dados atuais "
        "ou **stub** (placeholder) até haver histórico/coluna adequada.",
        "",
        "| Campo | Status | Nota |",
        "|-------|--------|------|",
        "| Coeficiente de completude semanal por base | Parcial | "
        "Inventário de fontes no staging + flag de SE parcial no briefing; "
        "coeficiente formal 0–1 por base ainda depende de calendário de carga DW. |",
        f"| Canal endêmico Bortman (razão vs mediana 5 anos) | "
        f"{bortman_status} | {bortman_nota} |",
        f"| Positividade nominal por marcador/metodologia | Implementado | "
        f"GAL micro ({n_micro} registros) → `positividade_por_marcador.csv`. |",
        f"| População IBGE 2026 para taxas | Parcial | "
        f"{pop_ano_nota or 'Usa melhor POPULACAO disponível no staging/weekly; '
        'anotar se não for 2026.'} |",
        "| Exames órfãos consolidados por município (GAL sem SINAN) | Implementado | "
        "`briefing_gal_sinan_divergencia.csv` (flag gal_sem_sinan). |",
        f"| Deduplicação por ID paciente | Bloqueado | "
        f"{dedup.get('motivo') or 'Sem identificador no micro GAL (LGPD / não extraído).'} |",
        "| Score prioridade municipal | Implementado (proposta) | "
        "`score_prioridade_municipal.csv` — rótulo: proposta para homologação. |",
        "| Alertas específicos por sinal | Implementado | "
        "`alertas_especificos/alerta_*.md` (+ html). |",
        "",
        *bortman_section,
        "## Completude semanal (orientação)",
        "",
        "Para cada base (GAL, SINAN, SIH, SIM, IndicaSUS, SISREG): "
        "completude = semanas_com_carga / semanas_esperadas no ano epidemiológico. "
        "Expor no Radar quando o calendário ETL estiver versionado.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def stub_canal_bortman(
    weekly: Sequence[dict[str, Any]],
    *,
    target: str,
    municipio: str,
    se: tuple[int, int],
) -> dict[str, Any]:
    """
    Stub transparente: se houver poucas SE do mesmo target×mun, devolve pendente;
    se houver várias SE, razão vs mediana das SE anteriores (não é canal 5 anos).
    """
    from lacen_briefing_epi import _norm_mun as _nm, _num as _n

    mun = _nm(municipio)
    tgt = str(target or "").strip()
    y0, w0 = se
    series: list[float] = []
    atual: float | None = None
    for r in weekly:
        if str(r.get("target") or "").strip() != tgt:
            continue
        if _nm(r.get("municipio")) != mun:
            continue
        y = _n(r.get("epi_year"))
        w = _n(r.get("epi_week"))
        if y is None or w is None:
            continue
        val = _n(r.get("positives"), 0) or 0
        if int(y) == y0 and int(w) == w0:
            atual = float(val)
        else:
            series.append(float(val))
    if atual is None:
        return {
            "status": "sem_dado_se_atual",
            "razao": None,
            "nota": "Sem valor na SE atual para canal.",
        }
    if len(series) < 8:
        return {
            "status": "stub_serie_curta",
            "razao": None,
            "n_se_historico": len(series),
            "nota": (
                "Canal endêmico Bortman (5 anos) indisponível — "
                f"apenas {len(series)} SE históricas no espelho."
            ),
        }
    series_sorted = sorted(series)
    mid = series_sorted[len(series_sorted) // 2]
    razao = (atual / mid) if mid > 0 else None
    return {
        "status": "proxy_mediana_serie_curta",
        "razao": round(razao, 3) if razao is not None else None,
        "mediana_historica": mid,
        "atual": atual,
        "n_se_historico": len(series),
        "nota": (
            "Proxy (mediana da série disponível) — "
            "não substitui canal Bortman de 5 anos."
        ),
    }
