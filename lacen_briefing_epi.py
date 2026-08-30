#!/usr/bin/env python3
"""
Briefing epidemiológico — 5 perguntas de sala de situação (CIEVS).

Responde, na mesma SE operacional do relatório CIEVS/ETL (última SE completa):
  1. Quais doenças mais solicitadas?
  2. Quais com maior positividade?
  3. Em quais localidades?
  4. Há cidades próximas na mesma situação?
  5. Há risco de dispersão?

Uso:
  from lacen_briefing_epi import gerar_briefing_epi, carregar_briefing_epi
  briefing = gerar_briefing_epi("saida_pipeline")
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"

WEEKLY_NAME = "integrated_weekly_surveillance.csv"
VIZINHOS_NAME = "municipio_vizinhos.csv"
ML_RISCO_NAME = "ml_risco_predito.csv"
BRIEFING_CSV = "briefing_epi_se.csv"
BRIEFING_RESUMO = "briefing_epi_se_resumo.txt"

# Alinhado a lacen_relatorio_cievs._week_incomplete / _pick_se_lab
_MIN_TESTS_COMPLETE = 50


def _num(val: Any, default: float | None = None) -> float | None:
    if val is None:
        return default
    s = str(val).strip().replace(",", ".")
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _fmt_se(year: int, week: int) -> str:
    return f"{int(year)}-SE{int(week):02d}"


def _parse_se(se: str | None) -> tuple[int, int] | None:
    if not se or "-SE" not in str(se):
        return None
    try:
        year_s, week_s = str(se).split("-SE", 1)
        return int(year_s), int(week_s)
    except ValueError:
        return None


def _norm_mun(text: object) -> str:
    s = str(text or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def _is_igg(target: str) -> bool:
    t = (target or "").casefold()
    return "igg" in t or "igg_" in t or t.endswith("_igg")


def _is_dengue(target: str) -> bool:
    return "dengue" in (target or "").casefold()


def _is_tb(target: str) -> bool:
    t = (target or "").casefold()
    return "tuberculose" in t or t == "tb" or t.startswith("tb_") or "baciloscopia" in t


def _is_hepatite(target: str) -> bool:
    return "hepatite" in (target or "").casefold()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _week_totals(
    rows: list[dict[str, str]], year: int, week: int
) -> tuple[float, float]:
    pos = tests = 0.0
    for r in rows:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != year or int(w) != week:
            continue
        t = _num(r.get("tests"), 0) or 0
        if t <= 0:
            continue
        tests += t
        pos += _num(r.get("positives"), 0) or 0
    return pos, tests


def _week_incomplete(
    cur_tests: float,
    cur_pos: float,
    prev_tests: float | None,
    prev_pos: float | None,
) -> bool:
    if prev_tests is None or prev_tests <= 0:
        return False
    prev_p = prev_pos or 0.0
    if cur_tests < _MIN_TESTS_COMPLETE and prev_tests >= _MIN_TESTS_COMPLETE:
        return True
    if cur_tests < 0.25 * prev_tests:
        return True
    if cur_pos < 5 and prev_p >= 5 and cur_tests < 0.5 * prev_tests:
        return True
    return False


def pick_se_operacional(
    weekly_rows: list[dict[str, str]],
    se_preferida: str | None = None,
) -> dict[str, Any]:
    """
    Mesma regra CIEVS: prefere última SE completa; se a mais recente
    estiver parcial, usa a anterior.
    """
    prefer = _parse_se(se_preferida)
    weeks = sorted(
        {
            (int(y), int(w))
            for r in weekly_rows
            for y, w in [(_num(r.get("epi_year")), _num(r.get("epi_week")))]
            if y is not None
            and w is not None
            and (_num(r.get("tests"), 0) or 0) > 0
        }
    )
    if prefer and prefer in weeks:
        idx = weeks.index(prefer)
        return {
            "se": prefer,
            "prev": weeks[idx - 1] if idx >= 1 else None,
            "latest": weeks[-1],
            "usou_completa": prefer != weeks[-1],
            "se_parcial": weeks[-1] if prefer != weeks[-1] else None,
            "se_iso": _fmt_se(*prefer),
        }
    if not weeks:
        return {
            "se": None,
            "prev": None,
            "latest": None,
            "usou_completa": False,
            "se_parcial": None,
            "se_iso": "—",
        }
    latest = weeks[-1]
    prev = weeks[-2] if len(weeks) >= 2 else None
    cur_pos, cur_tests = _week_totals(weekly_rows, latest[0], latest[1])
    prev_pos = prev_tests = None
    if prev:
        prev_pos, prev_tests = _week_totals(weekly_rows, prev[0], prev[1])
    incomplete = _week_incomplete(cur_tests, cur_pos, prev_tests, prev_pos)
    if incomplete and prev is not None:
        return {
            "se": prev,
            "prev": weeks[-3] if len(weeks) >= 3 else None,
            "latest": latest,
            "usou_completa": True,
            "se_parcial": latest,
            "se_iso": _fmt_se(*prev),
        }
    return {
        "se": latest,
        "prev": prev,
        "latest": latest,
        "usou_completa": False,
        "se_parcial": None,
        "se_iso": _fmt_se(*latest),
    }


def _filter_se(
    weekly_rows: list[dict[str, str]], se: tuple[int, int]
) -> list[dict[str, str]]:
    y0, w0 = se
    out: list[dict[str, str]] = []
    for r in weekly_rows:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        tests = _num(r.get("tests"), 0) or 0
        if tests <= 0:
            continue
        mun = str(r.get("municipio") or "").strip()
        if not mun or mun.startswith("*"):
            continue
        out.append(r)
    return out


def _agg_by_target(se_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, float]] = {}
    for r in se_rows:
        tgt = str(r.get("target") or "").strip() or "—"
        a = agg.setdefault(tgt, {"tests": 0.0, "positives": 0.0})
        a["tests"] += _num(r.get("tests"), 0) or 0
        a["positives"] += _num(r.get("positives"), 0) or 0
    rows: list[dict[str, Any]] = []
    for tgt, a in agg.items():
        tests = a["tests"]
        pos = a["positives"]
        posi = (pos / tests) if tests > 0 else None
        rows.append(
            {
                "target": tgt,
                "exames": tests,
                "positivos": pos,
                "positividade": posi,
                "tipo_sinal": "Observado",
                "baixa_amostra": False,
                "caveat_igg": _is_igg(tgt),
            }
        )
    return rows


def mais_solicitados(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int] | str,
    top: int = 8,
) -> list[dict[str, Any]]:
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw:
        return []
    rows = _filter_se(list(weekly), yw)
    ranked = sorted(_agg_by_target(rows), key=lambda x: x["exames"], reverse=True)
    return ranked[: max(1, top)]


def maior_positividade(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int] | str,
    min_exames: int = 30,
    top: int = 8,
    min_exames_secundario: int = 10,
) -> list[dict[str, Any]]:
    """
    Top positividade com min_exames=30; completa com lista secundária
    (min=10) marcada baixa_amostra se ainda houver vagas no top.
    """
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw:
        return []
    rows = _filter_se(list(weekly), yw)
    all_tgt = _agg_by_target(rows)

    def _rank(min_t: int, baixa: bool) -> list[dict[str, Any]]:
        cand = [dict(x) for x in all_tgt if x["exames"] >= min_t]
        for x in cand:
            x["baixa_amostra"] = baixa
            x["tipo_sinal"] = "Observado"
        cand.sort(
            key=lambda x: (
                x["positividade"] if x["positividade"] is not None else -1.0,
                x["exames"],
            ),
            reverse=True,
        )
        return cand

    primary = _rank(min_exames, False)
    seen = {x["target"] for x in primary}
    secondary = [
        x for x in _rank(min_exames_secundario, True) if x["target"] not in seen
    ]
    # Prioriza amostra robusta; inclui baixa_amostra só se faltarem slots
    out = primary[:top]
    if len(out) < top:
        out.extend(secondary[: top - len(out)])
    # Se primary já encheu o top, ainda assim anexa até 3 baixa_amostra
    # com flag explícita para o relatório (não misturar no ranking principal)
    elif secondary:
        for x in secondary[:3]:
            if x["target"] not in {o["target"] for o in out}:
                out.append(x)
    return out


def localidades(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int] | str,
    targets_top: Sequence[str],
    top_mun: int = 5,
) -> list[dict[str, Any]]:
    """Top municípios por positivos (ou exames se positivos=0) para cada target."""
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw or not targets_top:
        return []
    rows = _filter_se(list(weekly), yw)
    want = {str(t).strip() for t in targets_top if str(t).strip()}
    by_tgt: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows:
        tgt = str(r.get("target") or "").strip()
        if tgt not in want:
            continue
        mun = _norm_mun(r.get("municipio"))
        if not mun:
            continue
        a = by_tgt.setdefault(tgt, {}).setdefault(
            mun, {"positivos": 0.0, "exames": 0.0}
        )
        a["positivos"] += _num(r.get("positives"), 0) or 0
        a["exames"] += _num(r.get("tests"), 0) or 0

    out: list[dict[str, Any]] = []
    for tgt in targets_top:
        tgt = str(tgt).strip()
        mun_map = by_tgt.get(tgt) or {}
        ranked = sorted(
            mun_map.items(),
            key=lambda kv: (
                kv[1]["positivos"] if kv[1]["positivos"] > 0 else 0,
                kv[1]["exames"],
            ),
            reverse=True,
        )
        # Se todos com positivos=0, ordena só por exames
        if ranked and all(v["positivos"] <= 0 for _, v in ranked):
            ranked = sorted(mun_map.items(), key=lambda kv: kv[1]["exames"], reverse=True)
        for mun, a in ranked[:top_mun]:
            posi = (a["positivos"] / a["exames"]) if a["exames"] else None
            out.append(
                {
                    "target": tgt,
                    "municipio": mun,
                    "positivos": a["positivos"],
                    "exames": a["exames"],
                    "positividade": posi,
                    "tipo_sinal": "Observado",
                    "criterio": "positivos" if a["positivos"] > 0 else "exames",
                }
            )
    return out


def _vizinhos_index(
    vizinhos_rows: list[dict[str, str]],
) -> dict[str, list[tuple[str, float]]]:
    idx: dict[str, list[tuple[str, float]]] = {}
    for r in vizinhos_rows:
        mun = _norm_mun(r.get("municipio"))
        viz = _norm_mun(r.get("vizinho"))
        if not mun or not viz:
            continue
        dist = _num(r.get("dist_km"), 9999.0) or 9999.0
        idx.setdefault(mun, []).append((viz, dist))
    for mun in idx:
        idx[mun].sort(key=lambda x: x[1])
    return idx


def vizinhos_mesma_situacao(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    vizinhos: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int] | str,
    target: str,
    *,
    max_pares: int = 8,
) -> list[dict[str, Any]]:
    """Âncoras com positivo + vizinhos também positivos (mesmo target/SE)."""
    yw = _parse_se(se) if isinstance(se, str) else se
    tgt = str(target or "").strip()
    if not yw or not tgt:
        return []
    rows = [
        r
        for r in _filter_se(list(weekly), yw)
        if str(r.get("target") or "").strip() == tgt
    ]
    pos_by_mun: dict[str, float] = {}
    tests_by_mun: dict[str, float] = {}
    for r in rows:
        mun = _norm_mun(r.get("municipio"))
        pos = _num(r.get("positives"), 0) or 0
        tests = _num(r.get("tests"), 0) or 0
        pos_by_mun[mun] = pos_by_mun.get(mun, 0.0) + pos
        tests_by_mun[mun] = tests_by_mun.get(mun, 0.0) + tests

    anchors = {m for m, p in pos_by_mun.items() if p > 0}
    if not anchors:
        return []

    vidx = _vizinhos_index(list(vizinhos))
    pares: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for mun in sorted(anchors, key=lambda m: pos_by_mun[m], reverse=True):
        for viz, dist in vidx.get(mun, [])[:8]:
            if viz not in anchors:
                continue
            key = tuple(sorted((mun, viz)))
            if key in seen:
                continue
            seen.add(key)
            pares.append(
                {
                    "target": tgt,
                    "municipio": mun,
                    "vizinho": viz,
                    "positivos_ancora": pos_by_mun[mun],
                    "positivos_vizinho": pos_by_mun[viz],
                    "exames_ancora": tests_by_mun.get(mun, 0.0),
                    "exames_vizinho": tests_by_mun.get(viz, 0.0),
                    "dist_km": dist,
                    "tipo_sinal": "Observado",
                }
            )
            if len(pares) >= max_pares:
                return pares
    return pares


def _count_banda_ml(
    ml_rows: list[dict[str, str]],
    se: tuple[int, int],
    target: str | None = None,
    familias: Iterable[str] | None = None,
) -> dict[str, int]:
    y0, w0 = se
    fam_want = {f.casefold() for f in (familias or []) if f}
    tgt = (target or "").strip()
    counts: dict[str, int] = {}
    for r in ml_rows:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is not None and w is not None and (int(y) != y0 or int(w) != w0):
            # Se ML não tem SE, ainda conta (snapshot)
            if y is not None or w is not None:
                continue
        if tgt and str(r.get("target") or "").strip() != tgt:
            if fam_want:
                fam = str(r.get("familia") or "").casefold()
                if fam not in fam_want:
                    continue
            else:
                continue
        banda = str(r.get("banda_risco") or r.get("faixa_predita") or "").strip()
        if not banda:
            continue
        bl = banda.casefold()
        if bl in ("alta", "alto", "crítica", "critica", "muito_alto", "muito alto"):
            key = "Alta/Crítica" if "crit" in bl or "muito" in bl else "Alta"
            if "crit" in bl or "muito" in bl:
                key = "Crítica"
            elif "alta" in bl or "alto" in bl:
                key = "Alta"
            else:
                key = banda
            counts[key] = counts.get(key, 0) + 1
    return counts


def risco_dispersao(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    vizinhos: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int] | str,
    *,
    solicitados: Sequence[dict[str, Any]] | None = None,
    positividade: Sequence[dict[str, Any]] | None = None,
    ml_risco: Sequence[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Regras em português (Observado + linha Predito opcional via ML):
      - dengue alta demanda + baixa pos → atenção territorial / baixa confirmação
      - TB com cluster vizinho → risco local/contatos
      - hepatite com pares vizinhos → focos / investigar perfil do exame
      - IgG alto → soroprevalência; não tratar como epidemia aguda
      - opcional: count banda_risco Alta/Crítica (Predito)
    """
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw:
        return []
    sol = list(solicitados or mais_solicitados(weekly, yw, top=12))
    posi = list(positividade or maior_positividade(weekly, yw, top=12))
    lines: list[dict[str, Any]] = []

    # Dengue: alta demanda + baixa positividade
    for s in sol:
        tgt = str(s.get("target") or "")
        if not _is_dengue(tgt):
            continue
        exames = float(s.get("exames") or 0)
        p = s.get("positividade")
        if exames >= 50 and (p is None or p < 0.05):
            lines.append(
                {
                    "regra": "dengue_demanda_baixa_pos",
                    "target": tgt,
                    "mensagem": (
                        f"{tgt}: alta demanda ({int(exames)} exames) com baixa "
                        f"confirmação laboratorial "
                        f"({(p or 0) * 100:.1f}% pos.) — atenção territorial; "
                        "não interpreta como surto confirmado."
                    ),
                    "tipo_sinal": "Observado",
                }
            )
            break

    # TB com cluster vizinho
    for s in sol:
        tgt = str(s.get("target") or "")
        if not _is_tb(tgt):
            continue
        pares = vizinhos_mesma_situacao(weekly, vizinhos, yw, tgt, max_pares=5)
        if pares:
            n = len(pares)
            exemplares = ", ".join(
                f"{p['municipio']}↔{p['vizinho']}" for p in pares[:2]
            )
            lines.append(
                {
                    "regra": "tb_cluster_vizinho",
                    "target": tgt,
                    "mensagem": (
                        f"{tgt}: {n} par(es) de municípios vizinhos com positivos "
                        f"({exemplares}) — risco local/contatos; investigar rede "
                        "de transmissão e incompletos."
                    ),
                    "tipo_sinal": "Observado",
                    "n_pares": n,
                }
            )
            break

    # Hepatite com pares vizinhos
    hep_targets = []
    for s in sol + posi:
        tgt = str(s.get("target") or "")
        if _is_hepatite(tgt) and tgt not in hep_targets:
            hep_targets.append(tgt)
    for tgt in hep_targets[:3]:
        pares = vizinhos_mesma_situacao(weekly, vizinhos, yw, tgt, max_pares=5)
        if not pares:
            continue
        n = len(pares)
        lines.append(
            {
                "regra": "hepatite_focos_vizinhos",
                "target": tgt,
                "mensagem": (
                    f"{tgt}: {n} par(es) vizinhos com positivos — focos territoriais; "
                    "investigar perfil do exame (marcador agudo vs. crônico) antes "
                    "de classificar dispersão."
                ),
                "tipo_sinal": "Observado",
                "n_pares": n,
            }
        )
        break

    # IgG alto → soroprevalência
    for p in posi:
        tgt = str(p.get("target") or "")
        if not _is_igg(tgt):
            continue
        pv = p.get("positividade")
        if pv is None or pv < 0.4:
            continue
        lines.append(
            {
                "regra": "igg_soroprevalencia",
                "target": tgt,
                "mensagem": (
                    f"{tgt}: positividade elevada "
                    f"({pv * 100:.0f}% em {int(p.get('exames') or 0)} exames) "
                    "reflete soroprevalência/IgG — não tratar como epidemia aguda."
                ),
                "tipo_sinal": "Observado",
                "caveat_igg": True,
            }
        )
        break

    # Predito: bandas ML Alta/Crítica nos top targets
    if ml_risco:
        ml_list = list(ml_risco)
        top_tgts = [str(s.get("target") or "") for s in sol[:5]]
        total_alta = 0
        total_crit = 0
        detalhe: list[str] = []
        for tgt in top_tgts:
            if not tgt:
                continue
            counts = _count_banda_ml(ml_list, yw, target=tgt)
            a = counts.get("Alta", 0)
            c = counts.get("Crítica", 0)
            if a or c:
                total_alta += a
                total_crit += c
                detalhe.append(f"{tgt}: Alta={a}/Crítica={c}")
        if total_alta or total_crit:
            lines.append(
                {
                    "regra": "ml_banda_risco",
                    "target": ";".join(top_tgts[:3]),
                    "mensagem": (
                        f"Predito: {total_alta} mun. em banda Alta e {total_crit} "
                        f"em Crítica nos agravos mais solicitados "
                        f"({'; '.join(detalhe[:3])})."
                    ),
                    "tipo_sinal": "Predito",
                    "n_alta": total_alta,
                    "n_critica": total_crit,
                }
            )

    if not lines:
        lines.append(
            {
                "regra": "sem_sinal_forte",
                "target": "—",
                "mensagem": (
                    "Sem padrão forte de dispersão nas regras dengue/TB/hepatite/IgG "
                    "para esta SE — manter vigilância de rotina."
                ),
                "tipo_sinal": "Observado",
            }
        )
    return lines


@dataclass
class BriefingEpi:
    se_iso: str = "—"
    se_tuple: tuple[int, int] | None = None
    usou_completa: bool = False
    se_parcial: str | None = None
    mais_solicitados: list[dict[str, Any]] = field(default_factory=list)
    maior_positividade: list[dict[str, Any]] = field(default_factory=list)
    localidades: list[dict[str, Any]] = field(default_factory=list)
    vizinhos: list[dict[str, Any]] = field(default_factory=list)
    risco: list[dict[str, Any]] = field(default_factory=list)
    fontes: list[str] = field(default_factory=list)
    usou_ml: bool = False
    rows_flat: list[dict[str, str]] = field(default_factory=list)

    def resumo_linhas(self, max_risco: int = 5) -> list[str]:
        lines = [
            f"Briefing epidemiológico CIEVS — SE {self.se_iso}",
            "Tipo: Observado (lab) · Predito (ML se disponível)",
            "",
            "1) Mais solicitados:",
        ]
        for i, x in enumerate(self.mais_solicitados[:5], 1):
            lines.append(
                f"  {i}. {x['target']}: {int(x['exames'])} exames · "
                f"+{int(x['positivos'])} "
                f"({_pct(x.get('positividade'))}) [Observado]"
            )
        lines.append("2) Maior positividade:")
        for i, x in enumerate(self.maior_positividade[:5], 1):
            flag = " · baixa_amostra" if x.get("baixa_amostra") else ""
            igg = " · caveat IgG" if x.get("caveat_igg") else ""
            lines.append(
                f"  {i}. {x['target']}: {_pct(x.get('positividade'))} "
                f"({int(x['exames'])} exames){flag}{igg} [Observado]"
            )
        lines.append("3) Localidades (top targets):")
        by_t: dict[str, list[dict[str, Any]]] = {}
        for loc in self.localidades:
            by_t.setdefault(str(loc["target"]), []).append(loc)
        for tgt, locs in list(by_t.items())[:4]:
            muns = ", ".join(
                f"{L['municipio']}(+{int(L['positivos'])})" for L in locs[:3]
            )
            lines.append(f"  · {tgt}: {muns or '—'}")
        lines.append("4) Vizinhos na mesma situação:")
        if self.vizinhos:
            for v in self.vizinhos[:5]:
                lines.append(
                    f"  · {v['target']}: {v['municipio']} ↔ {v['vizinho']} "
                    f"(+{int(v['positivos_ancora'])}/+{int(v['positivos_vizinho'])})"
                )
        else:
            lines.append("  (nenhum par vizinho com positivos nos eixos priorizados)")
        lines.append("5) Risco de dispersão:")
        for r in self.risco[:max_risco]:
            lines.append(f"  · [{r.get('tipo_sinal', 'Observado')}] {r['mensagem']}")
        if any(x.get("caveat_igg") for x in self.maior_positividade):
            lines.append(
                "Nota: positividade IgG/sorologia elevada ≠ surto agudo."
            )
        return lines


def _pct(x: float | None, digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _fmt_num(x: Any, digits: int = 0) -> str:
    n = _num(x)
    if n is None:
        return "—"
    if digits == 0:
        return str(int(round(n)))
    return f"{n:.{digits}f}"


def _flatten(briefing: BriefingEpi) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    se = briefing.se_iso

    def add(
        pergunta: str,
        rank: int,
        *,
        target: str = "—",
        municipio: str = "—",
        exames: Any = "",
        positivos: Any = "",
        positividade: Any = "",
        detalhe: str = "",
        tipo_sinal: str = "Observado",
        flag: str = "",
    ) -> None:
        rows.append(
            {
                "se": se,
                "pergunta": pergunta,
                "rank": str(rank),
                "target": target,
                "municipio": municipio,
                "exames": _fmt_num(exames) if exames != "" else "",
                "positivos": _fmt_num(positivos) if positivos != "" else "",
                "positividade": (
                    _pct(positividade)
                    if isinstance(positividade, (int, float))
                    else str(positividade or "")
                ),
                "detalhe": detalhe,
                "tipo_sinal": tipo_sinal,
                "flag": flag,
            }
        )

    for i, x in enumerate(briefing.mais_solicitados, 1):
        add(
            "mais_solicitados",
            i,
            target=str(x["target"]),
            exames=x["exames"],
            positivos=x["positivos"],
            positividade=x.get("positividade"),
            tipo_sinal="Observado",
        )
    for i, x in enumerate(briefing.maior_positividade, 1):
        flags = []
        if x.get("baixa_amostra"):
            flags.append("baixa_amostra")
        if x.get("caveat_igg"):
            flags.append("caveat_igg")
        add(
            "maior_positividade",
            i,
            target=str(x["target"]),
            exames=x["exames"],
            positivos=x["positivos"],
            positividade=x.get("positividade"),
            tipo_sinal="Observado",
            flag=";".join(flags),
        )
    # Agrupa localidades por target para rank sequencial
    rank_loc = 0
    for loc in briefing.localidades:
        rank_loc += 1
        add(
            "localidades",
            rank_loc,
            target=str(loc["target"]),
            municipio=str(loc["municipio"]),
            exames=loc["exames"],
            positivos=loc["positivos"],
            positividade=loc.get("positividade"),
            detalhe=str(loc.get("criterio") or ""),
            tipo_sinal="Observado",
        )
    for i, v in enumerate(briefing.vizinhos, 1):
        add(
            "vizinhos_mesma_situacao",
            i,
            target=str(v["target"]),
            municipio=f"{v['municipio']}↔{v['vizinho']}",
            exames=v.get("exames_ancora"),
            positivos=v.get("positivos_ancora"),
            detalhe=(
                f"vizinho_pos={_fmt_num(v.get('positivos_vizinho'))}; "
                f"dist_km={_fmt_num(v.get('dist_km'), 1)}"
            ),
            tipo_sinal="Observado",
        )
    for i, r in enumerate(briefing.risco, 1):
        add(
            "risco_dispersao",
            i,
            target=str(r.get("target") or "—"),
            detalhe=str(r.get("mensagem") or ""),
            tipo_sinal=str(r.get("tipo_sinal") or "Observado"),
            flag=str(r.get("regra") or ""),
        )
    return rows


def computar_briefing_epi(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    se: str | None = None,
    top: int = 10,
) -> BriefingEpi:
    outdir = Path(outdir)
    weekly = _read_csv(outdir / WEEKLY_NAME)
    viz = _read_csv(outdir / VIZINHOS_NAME)
    ml = _read_csv(outdir / ML_RISCO_NAME)
    fontes = []
    if weekly:
        fontes.append(WEEKLY_NAME)
    if viz:
        fontes.append(VIZINHOS_NAME)
    usou_ml = bool(ml)
    if usou_ml:
        fontes.append(ML_RISCO_NAME)

    pick = pick_se_operacional(weekly, se_preferida=se)
    yw = pick.get("se")
    if not yw:
        return BriefingEpi(fontes=fontes)

    sol = mais_solicitados(weekly, yw, top=top)
    posi = maior_positividade(weekly, yw, min_exames=30, top=top)
    # Localidades: top 4 solicitados + top 2 positividade (únicos)
    tgt_loc: list[str] = []
    for x in sol[:4] + posi[:2]:
        t = str(x.get("target") or "")
        if t and t not in tgt_loc:
            tgt_loc.append(t)
    locs = localidades(weekly, yw, tgt_loc, top_mun=5)

    # Vizinhos: eixos com positivos (TB, hepatite, top posi não-IgG, dengue se pos>0)
    eixos: list[str] = []
    for x in sol + posi:
        t = str(x.get("target") or "")
        if not t or t in eixos:
            continue
        if _is_tb(t) or _is_hepatite(t) or (
            not _is_igg(t) and float(x.get("positivos") or 0) > 0
        ):
            eixos.append(t)
        if len(eixos) >= 4:
            break
    if not eixos:
        eixos = [str(x["target"]) for x in sol[:2] if x.get("target")]

    viz_pares: list[dict[str, Any]] = []
    for t in eixos:
        pares = vizinhos_mesma_situacao(weekly, viz, yw, t, max_pares=4)
        viz_pares.extend(pares)
        if len(viz_pares) >= 8:
            break
    viz_pares = viz_pares[:8]

    risco = risco_dispersao(
        weekly,
        viz,
        yw,
        solicitados=sol,
        positividade=posi,
        ml_risco=ml if usou_ml else None,
    )

    briefing = BriefingEpi(
        se_iso=str(pick.get("se_iso") or _fmt_se(*yw)),
        se_tuple=yw,
        usou_completa=bool(pick.get("usou_completa")),
        se_parcial=(
            _fmt_se(*pick["se_parcial"]) if pick.get("se_parcial") else None
        ),
        mais_solicitados=sol,
        maior_positividade=posi,
        localidades=locs,
        vizinhos=viz_pares,
        risco=risco,
        fontes=fontes,
        usou_ml=usou_ml,
    )
    briefing.rows_flat = _flatten(briefing)
    return briefing


def persistir_briefing(
    briefing: BriefingEpi, outdir: Path | str = OUTDIR_DEFAULT
) -> tuple[Path, Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / BRIEFING_CSV
    txt_path = outdir / BRIEFING_RESUMO
    fields = [
        "se",
        "pergunta",
        "rank",
        "target",
        "municipio",
        "exames",
        "positivos",
        "positividade",
        "detalhe",
        "tipo_sinal",
        "flag",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in briefing.rows_flat:
            w.writerow({k: row.get(k, "") for k in fields})
    txt_path.write_text(
        "\n".join(briefing.resumo_linhas()) + "\n", encoding="utf-8"
    )
    return csv_path, txt_path


def gerar_briefing_epi(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    se: str | None = None,
    top: int = 10,
    persistir: bool = True,
) -> BriefingEpi:
    briefing = computar_briefing_epi(outdir, se=se, top=top)
    if persistir and briefing.se_tuple:
        persistir_briefing(briefing, outdir)
    return briefing


def carregar_briefing_epi(
    outdir: Path | str = OUTDIR_DEFAULT,
) -> list[dict[str, str]]:
    return _read_csv(Path(outdir) / BRIEFING_CSV)


def briefing_para_relatorio(briefing: BriefingEpi) -> dict[str, Any]:
    """Payload enxuto para RelatorioCIEVS (Telegram + e-mail)."""
    return {
        "se_iso": briefing.se_iso,
        "usou_completa": briefing.usou_completa,
        "se_parcial": briefing.se_parcial,
        "mais_solicitados": [
            {
                "target": str(x["target"]),
                "exames": _fmt_num(x["exames"]),
                "positivos": _fmt_num(x["positivos"]),
                "positividade": _pct(x.get("positividade")),
                "tipo_sinal": "Observado",
            }
            for x in briefing.mais_solicitados
        ],
        "maior_positividade": [
            {
                "target": str(x["target"]),
                "exames": _fmt_num(x["exames"]),
                "positivos": _fmt_num(x["positivos"]),
                "positividade": _pct(x.get("positividade")),
                "baixa_amostra": "sim" if x.get("baixa_amostra") else "",
                "caveat_igg": "sim" if x.get("caveat_igg") else "",
                "tipo_sinal": "Observado",
            }
            for x in briefing.maior_positividade
        ],
        "localidades": [
            {
                "target": str(x["target"]),
                "municipio": str(x["municipio"]),
                "positivos": _fmt_num(x["positivos"]),
                "exames": _fmt_num(x["exames"]),
                "positividade": _pct(x.get("positividade")),
                "tipo_sinal": "Observado",
            }
            for x in briefing.localidades
        ],
        "vizinhos": [
            {
                "target": str(v["target"]),
                "par": f"{v['municipio']} ↔ {v['vizinho']}",
                "positivos": (
                    f"+{_fmt_num(v['positivos_ancora'])} / "
                    f"+{_fmt_num(v['positivos_vizinho'])}"
                ),
                "dist_km": _fmt_num(v.get("dist_km"), 1),
                "tipo_sinal": "Observado",
            }
            for v in briefing.vizinhos
        ],
        "risco": [
            {
                "mensagem": str(r.get("mensagem") or ""),
                "tipo_sinal": str(r.get("tipo_sinal") or "Observado"),
                "regra": str(r.get("regra") or ""),
            }
            for r in briefing.risco
        ],
        "fontes": list(briefing.fontes),
        "usou_ml": briefing.usou_ml,
        "nota_igg": (
            "Caveat: positividade elevada em IgG/sorologia reflete "
            "soroprevalência — não tratar como epidemia aguda."
            if any(x.get("caveat_igg") for x in briefing.maior_positividade)
            or any(r.get("caveat_igg") for r in briefing.risco)
            else ""
        ),
    }


if __name__ == "__main__":
    b = gerar_briefing_epi(OUTDIR_DEFAULT)
    print("\n".join(b.resumo_linhas()))
    print(f"\nCSV: {OUTDIR_DEFAULT / BRIEFING_CSV}")
