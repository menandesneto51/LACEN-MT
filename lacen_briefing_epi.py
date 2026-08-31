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
GAL_SINAN_CSV = "briefing_gal_sinan_divergencia.csv"
GEO_HOTSPOTS_CSV = "briefing_geo_hotspots.csv"
CRUZAMENTO_CSV = "briefing_cruzamento_bases.csv"
CRUZAMENTO_SIH_SIA_CSV = "briefing_cruzamento_sih_sia.csv"
SINAIS_REDE_CSV = "briefing_sinais_rede_externa.csv"

# Alinhado a lacen_relatorio_cievs._week_incomplete / _pick_se_lab
_MIN_TESTS_COMPLETE = 50

# Colunas candidatas a endereço (GAL micro / SINAN)
_ADDR_BAIRRO = (
    "bairro", "bairroresidencia", "bairro_residencia", "nm_bairro",
    "bairro_paciente", "ds_bairro",
)
_ADDR_CEP = ("cep", "cep_residencia", "cepresidencia", "nu_cep")
_ADDR_LAT = ("latitude", "lat", "geocampo1", "geo_lat", "nu_latitude")
_ADDR_LON = ("longitude", "lon", "lng", "geocampo2", "geo_lon", "nu_longitude")


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


def _shift_se(year: int, week: int, delta: int) -> tuple[int, int]:
    y, w = int(year), int(week) + int(delta)
    while w < 1:
        y -= 1
        w += 52
    while w > 52:
        y += 1
        w -= 52
    return y, w


def _tendencia_seta(delta_pct: float | None, *, tol_pct: float = 5.0) -> str:
    if delta_pct is None:
        return "→"
    if delta_pct > tol_pct:
        return "↑"
    if delta_pct < -tol_pct:
        return "↓"
    return "→"


def _familia_agravo(target: str, agravo_sinan: str | None = None) -> str:
    """Família canônica para join GAL×SINAN (qualquer evento/agravo)."""
    raw = (agravo_sinan or target or "").strip().casefold()
    t = (target or "").casefold()
    if "hepatite" in raw or "hepatite" in t or "hbv" in t or "hcv" in t:
        return "hepatite"
    if "tuberculose" in raw or "tuberculose" in t or t == "tb" or t.startswith("tb_"):
        return "tuberculose"
    if "dengue" in raw or "dengue" in t:
        return "dengue"
    if "chikungunya" in raw or "chikungunya" in t or "chik" in t:
        return "chikungunya"
    if "zika" in raw or "zika" in t:
        return "zika"
    if "oropouche" in raw or "oropouche" in t:
        return "oropouche"
    if "meningite" in raw or "meningite" in t:
        return "meningite"
    if "leptospir" in raw or "leptospir" in t:
        return "leptospirose"
    if "hantavir" in raw or "hantavir" in t:
        return "hantavirose"
    if "sifilis" in raw or "sífilis" in raw or "sifilis" in t:
        return "sifilis"
    if "srag" in raw or "respiratoria" in raw or "influenza" in t or "covid" in t:
        return "srag"
    if "malaria" in raw or "malária" in raw or "malaria" in t:
        return "malaria"
    if "leishmaniose" in raw or "leishmaniose" in t:
        return "leishmaniose"
    if "hanseniase" in raw or "hanseníase" in raw or "hanseniase" in t:
        return "hanseniase"
    if agravo_sinan and str(agravo_sinan).strip():
        return re.sub(r"\s+", "_", str(agravo_sinan).strip().casefold())
    if target and str(target).strip():
        return re.sub(r"\s+", "_", str(target).strip().casefold())
    return "outros"


def _delta_vs_prev(
    n_se: float,
    n_ant: float | None,
) -> dict[str, Any]:
    ant = float(n_ant) if n_ant is not None else None
    delta = (n_se - ant) if ant is not None else None
    delta_pct = (
        (100.0 * (n_se - ant) / ant) if ant is not None and ant > 0 else None
    )
    return {
        "n_se": n_se,
        "n_se_ant": ant if ant is not None else 0.0,
        "delta": delta if delta is not None else n_se,
        "delta_pct": delta_pct,
        "tendencia": _tendencia_seta(delta_pct),
    }


def _taxa_100k(n: float | None, pop: float | None) -> float | None:
    """Taxa por 100 mil habitantes; None se população indisponível."""
    if n is None or pop is None:
        return None
    try:
        nn, pp = float(n), float(pop)
    except (TypeError, ValueError):
        return None
    if pp <= 0 or math.isnan(pp) or math.isnan(nn):
        return None
    return 100_000.0 * nn / pp


def _fmt_taxa_100k(taxa: float | None, *, digits: int = 1) -> str:
    if taxa is None or (isinstance(taxa, float) and math.isnan(taxa)):
        return "—"
    return f"{float(taxa):.{digits}f}".replace(".", ",")


def frase_taxa_positivos_100k(taxa: float | None, *, digits: int = 1) -> str:
    """Linguagem simples p/ Telegram: 'X positivos por 100 mil habitantes'."""
    if taxa is None or (isinstance(taxa, float) and math.isnan(taxa)):
        return ""
    return (
        f"{_fmt_taxa_100k(taxa, digits=digits)} positivos por 100 mil habitantes"
    )


def carregar_populacao_lookup(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int],
    outdir: Path | str | None = None,
) -> dict[str, float]:
    """
    municipio -> população.
    Preferência: populacao na weekly da SE/ano; fallback populacao_municipio.csv
    (último ano <= ano da SE) e staging_dw/populacao.
    """
    lookup: dict[str, float] = {}
    y0 = int(se[0])

    def _ingest_row(mun: str, pop: float | None, *, overwrite: bool = False) -> None:
        if not mun or pop is None or pop <= 0 or math.isnan(pop):
            return
        if overwrite or mun not in lookup:
            lookup[mun] = float(pop)

    # 1) Weekly na SE (e, se vazio, qualquer semana do mesmo ano)
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or int(y) != y0:
            continue
        mun = _norm_mun(r.get("municipio"))
        pop = _num(r.get("populacao"))
        if w is not None and int(w) == int(se[1]):
            _ingest_row(mun, pop, overwrite=True)
        else:
            _ingest_row(mun, pop, overwrite=False)

    # 2) Fallback CSV oficial
    roots: list[Path] = []
    if outdir is not None:
        roots.append(Path(outdir))
    roots.append(OUTDIR_DEFAULT)
    for root in roots:
        pop_rows = _read_csv(root / "populacao_municipio.csv")
        if not pop_rows:
            pop_rows = _read_csv(root / "staging_dw" / "populacao.csv")
        if not pop_rows:
            continue
        # último ano <= y0 por município
        best: dict[str, tuple[int, float]] = {}
        for r in pop_rows:
            mun = _norm_mun(r.get("municipio") or r.get("Municipio"))
            ano = _num(r.get("ano") or r.get("Ano"))
            pop = _num(r.get("populacao") or r.get("POPULACAO") or r.get("pop"))
            if not mun or ano is None or pop is None or pop <= 0:
                continue
            ia = int(ano)
            if ia > y0:
                continue
            prev = best.get(mun)
            if prev is None or ia > prev[0]:
                best[mun] = (ia, float(pop))
        for mun, (_ano, pop) in best.items():
            _ingest_row(mun, pop, overwrite=False)
        if lookup:
            break
    return lookup


def populacao_estado(lookup: dict[str, float]) -> float | None:
    if not lookup:
        return None
    total = sum(float(v) for v in lookup.values() if v and v > 0)
    return total if total > 0 else None


def _se_tem_dados(
    weekly: list[dict[str, str]], se: tuple[int, int]
) -> bool:
    y0, w0 = se
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        if (_num(r.get("tests"), 0) or 0) > 0:
            return True
    return False


def _agg_counts_target_se(
    weekly: list[dict[str, str]],
    se: tuple[int, int],
    target: str,
    *,
    municipio: str | None = None,
) -> dict[str, float]:
    """Soma exames/positivos/notif na SE (estado ou 1 município)."""
    y0, w0 = se
    tgt = str(target or "").strip()
    mun_f = _norm_mun(municipio) if municipio else ""
    exames = pos = notif = 0.0
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        if str(r.get("target") or "").strip() != tgt:
            continue
        mun = _norm_mun(r.get("municipio"))
        if not mun or mun.startswith("*"):
            continue
        if mun_f and mun != mun_f:
            continue
        exames += _num(r.get("tests"), 0) or 0
        pos += _num(r.get("positives"), 0) or 0
        notif += _num(r.get("notificacoes"), 0) or 0
    return {"exames": exames, "positivos": pos, "notificacoes": notif}


def enriquecer_com_taxas_100k(
    ranked: list[dict[str, Any]],
    weekly: list[dict[str, str]],
    se: tuple[int, int],
    pop_lookup: dict[str, float],
    *,
    nivel: str = "estado",
) -> list[dict[str, Any]]:
    """
    Anexa taxa_exames_100k, taxa_positivos_100k, taxa_notif_100k (se SINAN>0),
    comparações vs SE-1 e YoY (SE equivalente ano anterior) quando a série permite.
    """
    se_ant = _shift_se(se[0], se[1], -1)
    se_yoy = (int(se[0]) - 1, int(se[1]))
    yoy_ok = _se_tem_dados(weekly, se_yoy)
    pop_uf = populacao_estado(pop_lookup)
    out: list[dict[str, Any]] = []
    for row in ranked:
        r = dict(row)
        tgt = str(r.get("target") or "")
        mun = str(r.get("municipio") or "").strip()
        mun_key = _norm_mun(mun) if nivel == "municipio" and mun else ""
        if nivel == "municipio" and mun_key:
            pop = pop_lookup.get(mun_key)
        else:
            pop = pop_uf
        cur = {
            "exames": float(r.get("exames") or 0),
            "positivos": float(r.get("positivos") or 0),
            "notificacoes": float(r.get("notificacoes") or 0),
        }
        # Se notif não veio no rank, busca na weekly
        if cur["notificacoes"] <= 0:
            got = _agg_counts_target_se(
                weekly, se, tgt, municipio=mun_key or None
            )
            cur["notificacoes"] = float(got.get("notificacoes") or 0)
            if cur["exames"] <= 0:
                cur["exames"] = float(got.get("exames") or 0)
            if cur["positivos"] <= 0:
                cur["positivos"] = float(got.get("positivos") or 0)

        ant = _agg_counts_target_se(
            weekly, se_ant, tgt, municipio=mun_key or None
        )
        yoy = (
            _agg_counts_target_se(weekly, se_yoy, tgt, municipio=mun_key or None)
            if yoy_ok
            else None
        )

        taxa_ex = _taxa_100k(cur["exames"], pop)
        taxa_pos = _taxa_100k(cur["positivos"], pop)
        taxa_nf = (
            _taxa_100k(cur["notificacoes"], pop)
            if cur["notificacoes"] > 0
            else None
        )
        taxa_ex_ant = _taxa_100k(ant["exames"], pop)
        taxa_pos_ant = _taxa_100k(ant["positivos"], pop)
        taxa_nf_ant = (
            _taxa_100k(ant["notificacoes"], pop)
            if ant["notificacoes"] > 0
            else None
        )

        def _d_taxa(a: float | None, b: float | None) -> float | None:
            if a is None or b is None:
                return None
            return a - b

        r["populacao_ref"] = pop
        r["notificacoes"] = cur["notificacoes"]
        r["taxa_exames_100k"] = taxa_ex
        r["taxa_positivos_100k"] = taxa_pos
        r["taxa_notif_100k"] = taxa_nf
        r["taxa_exames_100k_se_ant"] = taxa_ex_ant
        r["taxa_positivos_100k_se_ant"] = taxa_pos_ant
        r["taxa_notif_100k_se_ant"] = taxa_nf_ant
        r["delta_taxa_positivos_100k"] = _d_taxa(taxa_pos, taxa_pos_ant)
        r["delta_taxa_exames_100k"] = _d_taxa(taxa_ex, taxa_ex_ant)
        r["frase_taxa_positivos"] = frase_taxa_positivos_100k(taxa_pos)
        if yoy_ok and yoy is not None:
            taxa_pos_yoy = _taxa_100k(yoy["positivos"], pop)
            taxa_ex_yoy = _taxa_100k(yoy["exames"], pop)
            r["taxa_positivos_100k_yoy"] = taxa_pos_yoy
            r["taxa_exames_100k_yoy"] = taxa_ex_yoy
            r["delta_taxa_positivos_100k_yoy"] = _d_taxa(taxa_pos, taxa_pos_yoy)
            r["yoy_disponivel"] = True
            r["nota_yoy"] = ""
        else:
            r["taxa_positivos_100k_yoy"] = None
            r["taxa_exames_100k_yoy"] = None
            r["delta_taxa_positivos_100k_yoy"] = None
            r["yoy_disponivel"] = False
            r["nota_yoy"] = (
                f"YoY omitido: sem série para {_fmt_se(*se_yoy)}"
            )
        out.append(r)
    return out


def _agg_metric_by_target(
    weekly: list[dict[str, str]],
    se: tuple[int, int],
    metric: str,
) -> dict[str, float]:
    """metric: exames | positivos | positividade | notificacoes."""
    y0, w0 = se
    exames: dict[str, float] = {}
    pos: dict[str, float] = {}
    notif: dict[str, float] = {}
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        mun = str(r.get("municipio") or "").strip()
        if not mun or mun.startswith("*"):
            continue
        tgt = str(r.get("target") or "").strip() or "—"
        exames[tgt] = exames.get(tgt, 0.0) + (_num(r.get("tests"), 0) or 0)
        pos[tgt] = pos.get(tgt, 0.0) + (_num(r.get("positives"), 0) or 0)
        notif[tgt] = notif.get(tgt, 0.0) + (_num(r.get("notificacoes"), 0) or 0)
    if metric == "notificacoes":
        return notif
    if metric == "positivos":
        return pos
    if metric == "positividade":
        return {
            t: (pos[t] / exames[t]) if exames.get(t, 0) > 0 else 0.0
            for t in exames
        }
    return exames


def enriquecer_top_com_delta(
    ranked: list[dict[str, Any]],
    weekly: list[dict[str, str]],
    se: tuple[int, int],
    *,
    metric: str = "exames",
    n_anteriores: int = 4,
) -> list[dict[str, Any]]:
    """Anexa n_se, n_se_ant, delta, delta_pct, tendencia (+ mediana_4se)."""
    import statistics

    se_ant = _shift_se(se[0], se[1], -1)
    cur = _agg_metric_by_target(weekly, se, metric)
    prev = _agg_metric_by_target(weekly, se_ant, metric)
    hist_aggs = [
        _agg_metric_by_target(weekly, _shift_se(se[0], se[1], -i), metric)
        for i in range(1, n_anteriores + 1)
    ]
    out: list[dict[str, Any]] = []
    for row in ranked:
        r = dict(row)
        tgt = str(r.get("target") or "")
        n_se = float(cur.get(tgt, r.get(metric) or r.get("exames") or 0) or 0)
        if metric == "exames" and "exames" in r:
            n_se = float(r["exames"] or 0)
        elif metric == "positividade" and r.get("positividade") is not None:
            n_se = float(r["positividade"] or 0)
        elif metric == "notificacoes" and "notificacoes" in r:
            n_se = float(r["notificacoes"] or 0)
        n_ant = float(prev.get(tgt, 0.0) or 0.0)
        d = _delta_vs_prev(n_se, n_ant)
        # positividade: delta em pontos percentuais; delta_pct relativo
        if metric == "positividade":
            d["n_se"] = n_se
            d["n_se_ant"] = n_ant
            d["delta"] = n_se - n_ant
            d["delta_pct"] = (
                (100.0 * (n_se - n_ant) / n_ant) if n_ant > 0 else None
            )
            d["tendencia"] = _tendencia_seta(d["delta_pct"])
        hist_vals = [float(h.get(tgt, 0) or 0) for h in hist_aggs]
        med = statistics.median(hist_vals) if hist_vals else None
        r.update(d)
        r["mediana_4se"] = med
        r["acima_mediana_4se"] = bool(
            med is not None and n_se > med and med >= 0
        )
        out.append(r)
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    return []


def _read_csv_header(path: Path) -> list[str]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.reader(f)
                row = next(reader, None)
                return list(row) if row else []
        except (UnicodeDecodeError, OSError):
            continue
    return []


def _read_csv_sample(path: Path, max_rows: int = 5000) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                out: list[dict[str, str]] = []
                for i, row in enumerate(reader):
                    out.append(row)
                    if i + 1 >= max_rows:
                        break
                return out
        except UnicodeDecodeError:
            continue
    return []


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
        a = agg.setdefault(
            tgt, {"tests": 0.0, "positives": 0.0, "notificacoes": 0.0}
        )
        a["tests"] += _num(r.get("tests"), 0) or 0
        a["positives"] += _num(r.get("positives"), 0) or 0
        a["notificacoes"] += _num(r.get("notificacoes"), 0) or 0
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
                "notificacoes": a["notificacoes"],
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
            mun, {"positivos": 0.0, "exames": 0.0, "notificacoes": 0.0}
        )
        a["positivos"] += _num(r.get("positives"), 0) or 0
        a["exames"] += _num(r.get("tests"), 0) or 0
        a["notificacoes"] += _num(r.get("notificacoes"), 0) or 0

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
                    "notificacoes": a["notificacoes"],
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


def gal_sinan_divergencia(
    weekly: list[dict[str, str]] | Sequence[dict[str, Any]],
    se: tuple[int, int] | str,
    *,
    min_exames: float = 5.0,
    min_notif: float = 1.0,
    top: int = 40,
) -> list[dict[str, Any]]:
    """
    Divergência GAL×SINAN para qualquer evento/agravo na SE.
    Chave: município × família (agravo_sinan/target).
    Flags: gal_sem_sinan | sinan_sem_gal | ambos.
    """
    yw = _parse_se(se) if isinstance(se, str) else se
    if not yw:
        return []
    y0, w0 = yw
    cells: dict[tuple[str, str], dict[str, float | str]] = {}
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        mun = _norm_mun(r.get("municipio"))
        if not mun or mun.startswith("*"):
            continue
        tgt = str(r.get("target") or "").strip()
        fam = _familia_agravo(tgt, str(r.get("agravo_sinan") or "") or None)
        key = (mun, fam)
        a = cells.setdefault(
            key,
            {
                "municipio": mun,
                "familia": fam,
                "target_exemplo": tgt,
                "exames": 0.0,
                "positivos": 0.0,
                "notificacoes": 0.0,
            },
        )
        a["exames"] = float(a["exames"]) + (_num(r.get("tests"), 0) or 0)
        a["positivos"] = float(a["positivos"]) + (_num(r.get("positives"), 0) or 0)
        a["notificacoes"] = float(a["notificacoes"]) + (
            _num(r.get("notificacoes"), 0) or 0
        )
        if tgt and not a.get("target_exemplo"):
            a["target_exemplo"] = tgt

    out: list[dict[str, Any]] = []
    for (_mun, _fam), a in cells.items():
        exames = float(a["exames"])
        notif = float(a["notificacoes"])
        flag = ""
        if exames >= min_exames and notif < min_notif:
            flag = "gal_sem_sinan"
        elif notif >= min_notif and exames <= 0:
            flag = "sinan_sem_gal"
        elif exames >= min_exames and notif >= min_notif:
            flag = "ambos"
        else:
            continue
        if flag == "ambos" and exames < 20 and notif < 3:
            continue
        out.append(
            {
                "municipio": a["municipio"],
                "familia": a["familia"],
                "target": a.get("target_exemplo") or a["familia"],
                "exames": exames,
                "positivos": float(a["positivos"]),
                "notificacoes": notif,
                "flag": flag,
                "gal_sem_sinan": flag == "gal_sem_sinan",
                "sinan_sem_gal": flag == "sinan_sem_gal",
                "tipo_sinal": "Observado",
            }
        )
    # Prioriza divergências puras, depois volume
    out.sort(
        key=lambda x: (
            0 if x["flag"] in ("gal_sem_sinan", "sinan_sem_gal") else 1,
            -(x["exames"] + x["notificacoes"]),
        )
    )
    return out[: max(1, top)]


def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())


def _find_col(cols: Sequence[str], candidates: Sequence[str]) -> str | None:
    norm_map = {_norm_col(c): c for c in cols}
    for cand in candidates:
        hit = norm_map.get(_norm_col(cand))
        if hit:
            return hit
    return None


def detectar_colunas_endereco(cols: Sequence[str]) -> dict[str, str | None]:
    return {
        "bairro": _find_col(cols, _ADDR_BAIRRO),
        "cep": _find_col(cols, _ADDR_CEP),
        "lat": _find_col(cols, _ADDR_LAT),
        "lon": _find_col(cols, _ADDR_LON),
    }


def analise_geo_hotspots(
    weekly: list[dict[str, str]],
    se: tuple[int, int] | str,
    targets: Sequence[str],
    *,
    outdir: Path | str = OUTDIR_DEFAULT,
    top_por_agravo: int = 5,
) -> dict[str, Any]:
    """
    Hotspots geo: bairro/CEP se existirem em staging GAL/SINAN;
    senão município (centroid / codigo_ibge) da weekly.
    """
    yw = _parse_se(se) if isinstance(se, str) else se
    outdir = Path(outdir)
    stage = outdir / "staging_dw"
    result: dict[str, Any] = {
        "nivel": "municipio",
        "nota": "sem endereço no extrato — agregação por município (centroid/IBGE)",
        "fontes_endereco": [],
        "hotspots": [],
    }
    if not yw:
        return result

    # 1) Tenta micro GAL + extratos SINAN com bairro/CEP
    addr_rows: list[dict[str, Any]] = []
    fontes: list[str] = []
    for path in sorted(stage.glob("vw_gal_micro*.csv")) + sorted(
        stage.glob("vw_sinan*.csv")
    ):
        cols = _read_csv_header(path)
        if not cols:
            continue
        det = detectar_colunas_endereco(cols)
        if not (det["bairro"] or det["cep"]):
            continue
        sample = _read_csv_sample(path, max_rows=8000)
        if not sample:
            continue
        fontes.append(path.name)
        mun_col = _find_col(
            cols,
            (
                "municipio",
                "MunicipioResidencia",
                "Municipio_Residencia_Paciente",
                "MunicipioNotificacao",
            ),
        )
        agr_col = _find_col(
            cols,
            (
                "agravo",
                "Agravo_Gal",
                "Agravo_Requisicao",
                "target",
                "CID10",
                "Agravo",
            ),
        )
        for r in sample:
            bairro = str(r.get(det["bairro"] or "") or "").strip() if det["bairro"] else ""
            cep = str(r.get(det["cep"] or "") or "").strip() if det["cep"] else ""
            if not bairro and not cep:
                continue
            mun = _norm_mun(r.get(mun_col)) if mun_col else ""
            agr = str(r.get(agr_col) or "").strip() if agr_col else ""
            addr_rows.append(
                {
                    "municipio": mun,
                    "bairro": bairro or f"CEP {cep}",
                    "cep": cep,
                    "agravo": agr,
                    "fonte": path.name,
                }
            )

    if addr_rows:
        result["nivel"] = "bairro_cep"
        result["nota"] = (
            "Hotspots por bairro/CEP a partir de extratos com endereço "
            f"({', '.join(fontes[:4])})."
        )
        result["fontes_endereco"] = fontes
        # agrega top bairros (global + por agravo se possível)
        counts: dict[tuple[str, str, str], int] = {}
        for r in addr_rows:
            key = (r["municipio"] or "—", r["bairro"], r.get("agravo") or "—")
            counts[key] = counts.get(key, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[: top_por_agravo * 4]
        for (mun, bairro, agr), n in ranked:
            result["hotspots"].append(
                {
                    "nivel": "bairro_cep",
                    "municipio": mun,
                    "local": bairro,
                    "agravo": agr,
                    "n": n,
                    "codigo_ibge": "",
                    "latitude": "",
                    "longitude": "",
                    "tipo_sinal": "Observado",
                }
            )
        return result

    # 2) Fallback município via weekly + lat/lon/IBGE
    result["nivel"] = "municipio"
    result["nota"] = "sem endereço no extrato — mapa por município (centroid/codigo_ibge)"
    want = {str(t).strip() for t in targets if str(t).strip()}
    y0, w0 = yw
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in weekly:
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None or int(y) != y0 or int(w) != w0:
            continue
        tgt = str(r.get("target") or "").strip()
        if want and tgt not in want:
            continue
        mun = _norm_mun(r.get("municipio"))
        if not mun:
            continue
        key = (mun, tgt)
        a = by_key.setdefault(
            key,
            {
                "municipio": mun,
                "agravo": tgt,
                "exames": 0.0,
                "positivos": 0.0,
                "notificacoes": 0.0,
                "codigo_ibge": str(r.get("codigo_ibge") or "").replace(".0", ""),
                "latitude": r.get("latitude") or "",
                "longitude": r.get("longitude") or "",
            },
        )
        a["exames"] += _num(r.get("tests"), 0) or 0
        a["positivos"] += _num(r.get("positives"), 0) or 0
        a["notificacoes"] += _num(r.get("notificacoes"), 0) or 0
        if not a["codigo_ibge"] and r.get("codigo_ibge"):
            a["codigo_ibge"] = str(r.get("codigo_ibge")).replace(".0", "")
        if not a["latitude"] and r.get("latitude"):
            a["latitude"] = r.get("latitude")
            a["longitude"] = r.get("longitude")

    ranked_m = sorted(
        by_key.values(),
        key=lambda x: (x["positivos"], x["exames"], x["notificacoes"]),
        reverse=True,
    )
    for a in ranked_m[: top_por_agravo * max(1, len(want) or 1)]:
        result["hotspots"].append(
            {
                "nivel": "municipio",
                "municipio": a["municipio"],
                "local": a["municipio"],
                "agravo": a["agravo"],
                "n": int(a["exames"]),
                "positivos": a["positivos"],
                "notificacoes": a["notificacoes"],
                "codigo_ibge": a["codigo_ibge"],
                "latitude": a["latitude"],
                "longitude": a["longitude"],
                "tipo_sinal": "Observado",
            }
        )
    return result


def inventariar_cruzamento_bases(
    outdir: Path | str = OUTDIR_DEFAULT,
) -> list[dict[str, Any]]:
    """
    Lista fontes extras no staging DW (IndicaSUS/SISREG/SIH/SIA/SIM/SINAN…)
    para seção de cruzamento no relatório VE — não bloqueia se ausentes.
    """
    stage = Path(outdir) / "staging_dw"
    catalog = [
        ("SINAN", ("sinan",), "Notificação compulsória — vínculo mun×agravo com GAL"),
        ("GAL", ("vw_gal", "gal"), "Exames LACEN — demanda e positividade"),
        (
            "SIH",
            ("sih", "aih", "internac", "vw_internacao"),
            "Proxy SIH via VW_INTERNACAO — internacoes correlatas (CID×mun)",
        ),
        ("SIA", ("sia", "ambulator"), "Produção ambulatorial correlata (SIA/SIA_APAC)"),
        ("SIVEP/SRAG", ("sivep", "srag", "sindromerespiratoria"), "SRAG / respiratório"),
        ("SIM", ("sim", "obito", "óbito"), "Óbitos — letalidade contextual"),
        ("CNES", ("cnes",), "Capacidade da rede (leitos/equipes)"),
        (
            "IndicaSUS",
            ("indica", "pactuac", "indicasus_"),
            "Pactuação / INDICADORES* no DW + host IndicaSUS (indicasus_*)",
        ),
        (
            "SISREG",
            ("sisreg",),
            "Regulação — host SISREG_* (sisreg_* no staging; sem view no DW)",
        ),
        ("SINASC", ("sinasc",), "Nascidos vivos — contexto perinatal"),
        ("POPULACAO", ("populac",), "Denominadores municipais"),
    ]
    files = []
    if stage.exists():
        files = [p.name.casefold() for p in stage.iterdir() if p.is_file()]
    meta_sources: list[str] = []
    meta_path = stage / "extract_meta.json"
    if meta_path.exists():
        try:
            import json

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_sources = [
                str(s).casefold() for s in (meta.get("sources_extracted") or [])
            ]
        except (OSError, ValueError, TypeError):
            pass

    out: list[dict[str, Any]] = []
    for nome, needles, valor in catalog:
        hits = [
            f
            for f in files
            if any(nd in f for nd in needles)
            and not f.endswith(".json")
        ]
        src_hits = [s for s in meta_sources if any(nd in s for nd in needles)]
        presente = bool(hits or src_hits)
        out.append(
            {
                "fonte": nome,
                "presente": presente,
                "arquivos": ", ".join(hits[:4]) if hits else ("meta" if src_hits else ""),
                "quando_agrega": valor,
                "status": "extraído" if presente else "ausente no DW/staging",
            }
        )
    # SISREG: se meta tem ping, anotar sem marcar como extraído do DW
    for row in out:
        if row["fonte"] != "SISREG":
            continue
        try:
            import json

            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            ping = meta.get("sisreg_ping") or {}
            if ping.get("ok") is True and not row["presente"]:
                row["status"] = "host separado (TCP OK; sem view DW)"
                row["arquivos"] = row["arquivos"] or "sisreg_ping"
            elif ping.get("ok") is False and not row["presente"]:
                row["status"] = "host separado (TCP falhou; não bloqueia)"
            elif ping.get("ok") is None and not row["presente"]:
                row["status"] = "ausente no DW — usar SISREG_* (não bloqueia)"
        except (OSError, ValueError, TypeError):
            pass
    return out


def carregar_cruzamento_sih_sia(
    outdir: Path | str = OUTDIR_DEFAULT,
) -> dict[str, Any]:
    """
    Lê agregados SIH/SIA do staging DW (VW_INTERNACAO / SIA).
    Retorna dict com top_mun, caveat — vazio se ausente (não bloqueia).
    """
    import json

    stage = Path(outdir) / "staging_dw"
    empty: dict[str, Any] = {
        "caveat": (
            "Cruzamento SIH/SIA indisponível nesta remessa "
            "(rode etl/dw_extract com VPN)."
        ),
        "top_mun": [],
        "sih_rows": 0,
        "sia_rows": 0,
        "familias": [],
    }
    resumo_path = stage / "cruzamento_sih_sia_resumo.json"
    if resumo_path.exists():
        try:
            data = json.loads(resumo_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("top_mun", [])
                data.setdefault("caveat", empty["caveat"])
                return data
        except (OSError, ValueError, TypeError):
            pass

    # Fallback: CSV top mun
    top_csv = stage / "cruzamento_sih_sia_top_mun.csv"
    if top_csv.exists():
        rows = _read_csv(top_csv)
        return {
            "caveat": (
                "Cruzamento SIH/SIA é correlato por CID×município "
                "(proxy VW_INTERNACAO / SIA); não confirma surto."
            ),
            "top_mun": [
                {
                    "fonte": r.get("fonte") or "SIH/VW_INTERNACAO",
                    "municipio": r.get("municipio") or "—",
                    "cid_familia": r.get("cid_familia") or "—",
                    "n": int(float(r["n"])) if str(r.get("n") or "").replace(".", "", 1).isdigit() else 0,
                }
                for r in rows[:15]
            ],
            "sih_rows": 0,
            "sia_rows": 0,
            "familias": sorted({r.get("cid_familia") or "" for r in rows if r.get("cid_familia")}),
        }
    return empty


def carregar_sinais_rede_externa(
    outdir: Path | str = OUTDIR_DEFAULT,
) -> dict[str, Any]:
    """
    Sinais leves IndicaSUS (ocupação) + SISREG (filas/status) do staging.
    Não bloqueia se ausentes. Não inclui dados nominais.
    """
    stage = Path(outdir) / "staging_dw"
    out: dict[str, Any] = {
        "indicasus_ocupacao_top": [],
        "sisreg_hosp_top": [],
        "sisreg_amb_pendente_top": [],
        "caveat": (
            "IndicaSUS/SISREG são sinais de rede/regulação (hosts separados); "
            "não confirmam surto nem substituem GAL×SINAN."
        ),
        "presente": False,
    }

    occ_path = stage / "indicasus_ocupacao_agg.csv"
    if occ_path.exists():
        rows = _read_csv(occ_path)
        scored: list[dict[str, Any]] = []
        for r in rows:
            n = _num(r.get("n"), 0.0) or 0.0
            scored.append(
                {
                    "fonte": "IndicaSUS",
                    "tipo_leito": str(r.get("tipo_leito") or "—")[:60],
                    "situacao": str(r.get("situacao_covid") or r.get("situacao") or "—")[:40],
                    "data_ref": str(r.get("data_ref") or "")[:12],
                    "n": int(n),
                }
            )
        scored.sort(key=lambda x: -int(x.get("n") or 0))
        out["indicasus_ocupacao_top"] = scored[:12]
        if scored:
            out["presente"] = True

    hosp_path = stage / "sisreg_hosp_mun_status_agg.csv"
    if hosp_path.exists():
        rows = _read_csv(hosp_path)
        scored = []
        for r in rows:
            n = _num(r.get("n_solicitacoes") or r.get("n"), 0.0) or 0.0
            scored.append(
                {
                    "fonte": "SISREG/hosp",
                    "municipio": str(r.get("municipio") or "—")[:40],
                    "status": str(r.get("status") or "—")[:40],
                    "n": int(n),
                }
            )
        scored.sort(key=lambda x: -int(x.get("n") or 0))
        out["sisreg_hosp_top"] = scored[:10]
        if scored:
            out["presente"] = True

    amb_path = stage / "sisreg_amb_mun_status_agg.csv"
    if amb_path.exists():
        rows = _read_csv(amb_path)
        scored = []
        for r in rows:
            st = str(r.get("status_solicitacao") or r.get("status") or "").upper()
            if "PENDENTE" not in st and "FILA" not in st:
                continue
            n = _num(r.get("n_solicitacoes") or r.get("n"), 0.0) or 0.0
            scored.append(
                {
                    "fonte": "SISREG/amb",
                    "municipio": str(r.get("municipio") or "—")[:40],
                    "status": str(r.get("status_solicitacao") or r.get("status") or "—")[:60],
                    "procedimento": str(r.get("nome_grupo_procedimento") or "")[:50],
                    "n": int(n),
                }
            )
        scored.sort(key=lambda x: -int(x.get("n") or 0))
        out["sisreg_amb_pendente_top"] = scored[:10]
        if scored:
            out["presente"] = True

    return out


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
    cartoes_risco: list[dict[str, Any]] = field(default_factory=list)
    gal_sinan: list[dict[str, Any]] = field(default_factory=list)
    geo: dict[str, Any] = field(default_factory=dict)
    cruzamento_bases: list[dict[str, Any]] = field(default_factory=list)
    cruzamento_sih_sia: dict[str, Any] = field(default_factory=dict)
    sinais_rede: dict[str, Any] = field(default_factory=dict)
    fontes: list[str] = field(default_factory=list)
    usou_ml: bool = False
    nota_taxas: str = ""
    rows_flat: list[dict[str, str]] = field(default_factory=list)

    def resumo_linhas(self, max_risco: int = 5) -> list[str]:
        lines = [
            f"Briefing epidemiológico CIEVS — SE {self.se_iso}",
            "Tipo: Observado (lab) · Predito (ML se disponível)",
            "",
            "1) Mais solicitados (N + Δ vs SE-1 + taxa/100 mil):",
        ]
        for i, x in enumerate(self.mais_solicitados[:5], 1):
            dlt = x.get("delta")
            pct = x.get("delta_pct")
            pct_s = f"{pct:+.0f}%" if pct is not None else "—"
            taxa_s = x.get("frase_taxa_positivos") or ""
            if not taxa_s and x.get("taxa_positivos_100k") is not None:
                taxa_s = frase_taxa_positivos_100k(x.get("taxa_positivos_100k"))
            taxa_bit = f" · {taxa_s}" if taxa_s else ""
            lines.append(
                f"  {i}. {x['target']}: {int(x['exames'])} exames · "
                f"Δ={int(dlt) if dlt is not None else '—'} ({pct_s}) "
                f"{x.get('tendencia', '→')} · +{int(x['positivos'])} "
                f"({_pct(x.get('positividade'))}){taxa_bit} [Observado]"
            )
        if self.nota_taxas:
            lines.append(f"  Nota taxas: {self.nota_taxas}")
        lines.append("2) Maior positividade (Δ vs SE-1):")
        for i, x in enumerate(self.maior_positividade[:5], 1):
            flag = " · baixa_amostra" if x.get("baixa_amostra") else ""
            igg = " · caveat IgG" if x.get("caveat_igg") else ""
            pct = x.get("delta_pct")
            pct_s = f"{pct:+.0f}%" if pct is not None else "—"
            taxa_s = x.get("frase_taxa_positivos") or ""
            taxa_bit = f" · {taxa_s}" if taxa_s else ""
            lines.append(
                f"  {i}. {x['target']}: {_pct(x.get('positividade'))} "
                f"({int(x['exames'])} exames) Δ%={pct_s} "
                f"{x.get('tendencia', '→')}{flag}{igg}{taxa_bit} [Observado]"
            )
        lines.append("3) Localidades (top targets):")
        by_t: dict[str, list[dict[str, Any]]] = {}
        for loc in self.localidades:
            by_t.setdefault(str(loc["target"]), []).append(loc)
        for tgt, locs in list(by_t.items())[:4]:
            bits = []
            for L in locs[:3]:
                tx = L.get("frase_taxa_positivos") or ""
                if tx:
                    bits.append(
                        f"{L['municipio']}(+{int(L['positivos'])}; {tx})"
                    )
                else:
                    bits.append(f"{L['municipio']}(+{int(L['positivos'])})")
            lines.append(f"  · {tgt}: {', '.join(bits) or '—'}")
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
        if self.cartoes_risco:
            lines.append("5b) Cartões de risco (evento):")
            for c in self.cartoes_risco[:5]:
                lines.append(
                    f"  · {c.get('evento', '—')}: prob={c.get('probabilidade', '—')} "
                    f"impacto={c.get('impacto', '—')} · {c.get('veredito', '—')} "
                    f"[{c.get('confianca', 'Observado')}]"
                )
        if self.gal_sinan:
            n_gal = sum(1 for g in self.gal_sinan if g.get("gal_sem_sinan"))
            n_sin = sum(1 for g in self.gal_sinan if g.get("sinan_sem_gal"))
            lines.append(
                f"6) GAL×SINAN (qualquer agravo): {n_gal} gal_sem_sinan · "
                f"{n_sin} sinan_sem_gal"
            )
        geo = self.geo or {}
        if geo:
            lines.append(
                f"7) Geo: nível={geo.get('nivel', '—')} — {geo.get('nota', '')[:120]}"
            )
        sih = self.cruzamento_sih_sia or {}
        top_sih = sih.get("top_mun") or []
        if top_sih:
            lines.append("7b) Cruzamento SIH/SIA (proxy VW_INTERNACAO):")
            for row in top_sih[:6]:
                lines.append(
                    f"  · {row.get('municipio')} × {row.get('cid_familia')}: "
                    f"n={row.get('n')} [{row.get('fonte', 'SIH')}]"
                )
            caveat = str(sih.get("caveat") or "")
            if caveat:
                lines.append(f"  Caveat: {caveat[:160]}")
        rede = self.sinais_rede or {}
        if rede.get("presente"):
            lines.append("7c) Sinais IndicaSUS / SISREG:")
            for row in (rede.get("indicasus_ocupacao_top") or [])[:4]:
                lines.append(
                    f"  · IndicaSUS ocupação: {row.get('tipo_leito')} / "
                    f"{row.get('situacao')} n={row.get('n')} ({row.get('data_ref')})"
                )
            for row in (rede.get("sisreg_hosp_top") or [])[:4]:
                lines.append(
                    f"  · SISREG hosp: {row.get('municipio')} [{row.get('status')}] "
                    f"n={row.get('n')}"
                )
            for row in (rede.get("sisreg_amb_pendente_top") or [])[:3]:
                lines.append(
                    f"  · SISREG amb pendente: {row.get('municipio')} "
                    f"n={row.get('n')}"
                )
            cav = str(rede.get("caveat") or "")
            if cav:
                lines.append(f"  Caveat: {cav[:160]}")
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

    def _fmt_pct_delta(v: Any) -> str:
        n = _num(v)
        if n is None:
            return ""
        return f"{n:+.1f}"

    def add(
        pergunta: str,
        rank: int,
        *,
        target: str = "—",
        municipio: str = "—",
        exames: Any = "",
        positivos: Any = "",
        positividade: Any = "",
        n_se: Any = "",
        n_se_ant: Any = "",
        delta: Any = "",
        delta_pct: Any = "",
        tendencia: str = "",
        taxa_exames_100k: Any = "",
        taxa_positivos_100k: Any = "",
        taxa_notif_100k: Any = "",
        detalhe: str = "",
        tipo_sinal: str = "Observado",
        flag: str = "",
    ) -> None:
        def _smart_num(v: Any) -> str:
            if v == "" or v is None:
                return ""
            n = _num(v)
            if n is None:
                return ""
            if abs(n) < 2 and abs(n) != int(abs(n)):
                return f"{n:.4f}"
            return _fmt_num(n, 0)

        def _taxa_cell(v: Any) -> str:
            if v == "" or v is None:
                return ""
            n = _num(v)
            if n is None:
                return ""
            return _fmt_taxa_100k(n)

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
                "n_se": _smart_num(n_se),
                "n_se_ant": _smart_num(n_se_ant),
                "delta": _smart_num(delta),
                "delta_pct": _fmt_pct_delta(delta_pct),
                "tendencia": tendencia or "",
                "taxa_exames_100k": _taxa_cell(taxa_exames_100k),
                "taxa_positivos_100k": _taxa_cell(taxa_positivos_100k),
                "taxa_notif_100k": _taxa_cell(taxa_notif_100k),
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
            n_se=x.get("n_se", x.get("exames")),
            n_se_ant=x.get("n_se_ant"),
            delta=x.get("delta"),
            delta_pct=x.get("delta_pct"),
            tendencia=str(x.get("tendencia") or ""),
            taxa_exames_100k=x.get("taxa_exames_100k"),
            taxa_positivos_100k=x.get("taxa_positivos_100k"),
            taxa_notif_100k=x.get("taxa_notif_100k"),
            detalhe=f"mediana_4se={x.get('mediana_4se')}",
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
            n_se=x.get("n_se", x.get("positividade")),
            n_se_ant=x.get("n_se_ant"),
            delta=x.get("delta"),
            delta_pct=x.get("delta_pct"),
            tendencia=str(x.get("tendencia") or ""),
            taxa_exames_100k=x.get("taxa_exames_100k"),
            taxa_positivos_100k=x.get("taxa_positivos_100k"),
            taxa_notif_100k=x.get("taxa_notif_100k"),
            tipo_sinal="Observado",
            flag=";".join(flags),
        )
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
            taxa_exames_100k=loc.get("taxa_exames_100k"),
            taxa_positivos_100k=loc.get("taxa_positivos_100k"),
            taxa_notif_100k=loc.get("taxa_notif_100k"),
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
    for i, g in enumerate(briefing.gal_sinan, 1):
        add(
            "gal_sinan",
            i,
            target=str(g.get("target") or g.get("familia") or "—"),
            municipio=str(g.get("municipio") or "—"),
            exames=g.get("exames"),
            positivos=g.get("positivos"),
            detalhe=f"notif={g.get('notificacoes')}",
            flag=str(g.get("flag") or ""),
            tipo_sinal="Observado",
        )
    for i, h in enumerate((briefing.geo or {}).get("hotspots") or [], 1):
        add(
            "geo_hotspot",
            i,
            target=str(h.get("agravo") or "—"),
            municipio=str(h.get("municipio") or "—"),
            exames=h.get("n"),
            detalhe=f"{h.get('nivel')}:{h.get('local')} ibge={h.get('codigo_ibge')}",
            tipo_sinal="Observado",
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

    sol = enriquecer_top_com_delta(
        mais_solicitados(weekly, yw, top=top),
        weekly,
        yw,
        metric="exames",
    )
    posi = enriquecer_top_com_delta(
        maior_positividade(weekly, yw, min_exames=30, top=top),
        weekly,
        yw,
        metric="positividade",
    )
    pop_lookup = carregar_populacao_lookup(weekly, yw, outdir=outdir)
    sol = enriquecer_com_taxas_100k(
        sol, weekly, yw, pop_lookup, nivel="estado"
    )
    posi = enriquecer_com_taxas_100k(
        posi, weekly, yw, pop_lookup, nivel="estado"
    )
    nota_taxas = ""
    if not pop_lookup:
        nota_taxas = "população indisponível — taxas /100 mil omitidas"
    else:
        yoy_flags = [bool(x.get("yoy_disponivel")) for x in sol[:3]]
        if yoy_flags and not any(yoy_flags):
            nota_taxas = str(sol[0].get("nota_yoy") or "YoY omitido (série)")
        elif any(x.get("yoy_disponivel") for x in sol):
            nota_taxas = "taxas vs SE-1 e YoY (mesma SE do ano anterior)"
        else:
            nota_taxas = "taxas vs SE-1"

    # Localidades: top 4 solicitados + top 2 positividade (únicos)
    tgt_loc: list[str] = []
    for x in sol[:4] + posi[:2]:
        t = str(x.get("target") or "")
        if t and t not in tgt_loc:
            tgt_loc.append(t)
    locs = localidades(weekly, yw, tgt_loc, top_mun=5)
    locs = enriquecer_com_taxas_100k(
        locs, weekly, yw, pop_lookup, nivel="municipio"
    )

    # Vizinhos: eixos com positivos (TB, hepatite, top posi não-IgG, dengue se pos>0)
    # + qualquer top solicitado com positivos (co-sinal territorial)
    eixos: list[str] = []
    for x in sol + posi:
        t = str(x.get("target") or "")
        if not t or t in eixos:
            continue
        if _is_tb(t) or _is_hepatite(t) or (
            not _is_igg(t) and float(x.get("positivos") or 0) > 0
        ):
            eixos.append(t)
        if len(eixos) >= 6:
            break
    if not eixos:
        eixos = [str(x["target"]) for x in sol[:2] if x.get("target")]

    viz_pares: list[dict[str, Any]] = []
    for t in eixos:
        pares = vizinhos_mesma_situacao(weekly, viz, yw, t, max_pares=4)
        viz_pares.extend(pares)
        if len(viz_pares) >= 10:
            break
    viz_pares = viz_pares[:10]

    risco = risco_dispersao(
        weekly,
        viz,
        yw,
        solicitados=sol,
        positividade=posi,
        ml_risco=ml if usou_ml else None,
    )

    gal_sinan = gal_sinan_divergencia(weekly, yw, top=40)
    if gal_sinan:
        fontes.append("GAL×SINAN (mun×família, qualquer agravo)")

    geo = analise_geo_hotspots(
        weekly, yw, tgt_loc or [str(x.get("target")) for x in sol[:5]], outdir=outdir
    )
    if geo.get("fontes_endereco"):
        fontes.extend(geo["fontes_endereco"][:3])
    else:
        fontes.append("geo município (codigo_ibge/lat-lon weekly)")

    cruz = inventariar_cruzamento_bases(outdir)
    presentes = [c["fonte"] for c in cruz if c.get("presente")]
    if presentes:
        fontes.append("DW cruzamento: " + ", ".join(presentes[:6]))

    sih_sia = carregar_cruzamento_sih_sia(outdir)
    if sih_sia.get("top_mun"):
        fontes.append("Cruzamento SIH/SIA (VW_INTERNACAO)")

    sinais_rede = carregar_sinais_rede_externa(outdir)
    if sinais_rede.get("presente"):
        fontes.append("IndicaSUS/SISREG (ocupação + filas)")

    try:
        from lacen_radar_risco import gerar_cartoes_risco

        cartoes = gerar_cartoes_risco(
            se_iso=str(pick.get("se_iso") or _fmt_se(*yw)),
            solicitados=sol,
            positividade=posi,
            localidades=locs,
            vizinhos=viz_pares,
            gal_sinan=gal_sinan,
            cruzamento_sih_sia=sih_sia,
            top=12,
        )
        if cartoes:
            fontes.append("cartões de risco evento (CIEVS)")
    except Exception:  # noqa: BLE001
        cartoes = []

    if pop_lookup:
        fontes.append("populacao (weekly/populacao_municipio)")

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
        cartoes_risco=cartoes,
        gal_sinan=gal_sinan,
        geo=geo,
        cruzamento_bases=cruz,
        cruzamento_sih_sia=sih_sia,
        sinais_rede=sinais_rede,
        fontes=fontes,
        usou_ml=usou_ml,
        nota_taxas=nota_taxas,
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
        "n_se",
        "n_se_ant",
        "delta",
        "delta_pct",
        "tendencia",
        "taxa_exames_100k",
        "taxa_positivos_100k",
        "taxa_notif_100k",
        "detalhe",
        "tipo_sinal",
        "flag",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in briefing.rows_flat:
            w.writerow({k: row.get(k, "") for k in fields})
    txt_path.write_text(
        "\n".join(briefing.resumo_linhas()) + "\n", encoding="utf-8"
    )

    # GAL×SINAN
    gs_path = outdir / GAL_SINAN_CSV
    gs_fields = [
        "municipio", "familia", "target", "exames", "positivos",
        "notificacoes", "flag", "gal_sem_sinan", "sinan_sem_gal", "tipo_sinal",
    ]
    with gs_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=gs_fields, extrasaction="ignore")
        w.writeheader()
        for row in briefing.gal_sinan:
            w.writerow({k: row.get(k, "") for k in gs_fields})

    # Geo hotspots
    geo_path = outdir / GEO_HOTSPOTS_CSV
    hotspots = (briefing.geo or {}).get("hotspots") or []
    geo_fields = [
        "nivel", "municipio", "local", "agravo", "n", "positivos",
        "notificacoes", "codigo_ibge", "latitude", "longitude", "tipo_sinal",
    ]
    with geo_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=geo_fields, extrasaction="ignore")
        w.writeheader()
        for row in hotspots:
            w.writerow({k: row.get(k, "") for k in geo_fields})

    # Cruzamento bases
    cruz_path = outdir / CRUZAMENTO_CSV
    cruz_fields = ["fonte", "presente", "arquivos", "quando_agrega", "status"]
    with cruz_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cruz_fields, extrasaction="ignore")
        w.writeheader()
        for row in briefing.cruzamento_bases:
            w.writerow({k: row.get(k, "") for k in cruz_fields})

    # Cruzamento SIH/SIA top mun
    sih_path = outdir / CRUZAMENTO_SIH_SIA_CSV
    sih_fields = ["fonte", "municipio", "cid_familia", "n", "caveat"]
    caveat = str((briefing.cruzamento_sih_sia or {}).get("caveat") or "")
    with sih_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sih_fields, extrasaction="ignore")
        w.writeheader()
        for row in (briefing.cruzamento_sih_sia or {}).get("top_mun") or []:
            w.writerow(
                {
                    "fonte": row.get("fonte", ""),
                    "municipio": row.get("municipio", ""),
                    "cid_familia": row.get("cid_familia", ""),
                    "n": row.get("n", ""),
                    "caveat": caveat[:240],
                }
            )

    # Sinais IndicaSUS / SISREG
    rede_path = outdir / SINAIS_REDE_CSV
    rede = briefing.sinais_rede or {}
    rede_fields = ["fonte", "municipio", "status", "detalhe", "n", "caveat"]
    cav_rede = str(rede.get("caveat") or "")
    with rede_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rede_fields, extrasaction="ignore")
        w.writeheader()
        for row in rede.get("indicasus_ocupacao_top") or []:
            w.writerow(
                {
                    "fonte": row.get("fonte", "IndicaSUS"),
                    "municipio": "—",
                    "status": row.get("situacao", ""),
                    "detalhe": f"{row.get('tipo_leito', '')} @ {row.get('data_ref', '')}",
                    "n": row.get("n", ""),
                    "caveat": cav_rede[:240],
                }
            )
        for row in rede.get("sisreg_hosp_top") or []:
            w.writerow(
                {
                    "fonte": row.get("fonte", "SISREG/hosp"),
                    "municipio": row.get("municipio", ""),
                    "status": row.get("status", ""),
                    "detalhe": "hospitalar",
                    "n": row.get("n", ""),
                    "caveat": cav_rede[:240],
                }
            )
        for row in rede.get("sisreg_amb_pendente_top") or []:
            w.writerow(
                {
                    "fonte": row.get("fonte", "SISREG/amb"),
                    "municipio": row.get("municipio", ""),
                    "status": row.get("status", ""),
                    "detalhe": row.get("procedimento", ""),
                    "n": row.get("n", ""),
                    "caveat": cav_rede[:240],
                }
            )

    # Cartões de risco CIEVS
    if briefing.cartoes_risco:
        try:
            from lacen_radar_risco import persistir_cartoes_risco

            persistir_cartoes_risco(briefing.cartoes_risco, outdir)
        except Exception:  # noqa: BLE001
            pass

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

    def _row_delta(x: dict[str, Any]) -> dict[str, str]:
        pct = x.get("delta_pct")
        return {
            "n_se": _fmt_num(x.get("n_se", x.get("exames"))),
            "n_se_ant": _fmt_num(x.get("n_se_ant")),
            "delta": _fmt_num(x.get("delta")),
            "delta_pct": (
                f"{float(pct):+.1f}%" if pct is not None else "—"
            ),
            "tendencia": str(x.get("tendencia") or "→"),
            "mediana_4se": _fmt_num(x.get("mediana_4se"), 2)
            if x.get("mediana_4se") is not None
            else "—",
        }

    def _row_taxas(x: dict[str, Any]) -> dict[str, str]:
        frase = str(x.get("frase_taxa_positivos") or "")
        if not frase and x.get("taxa_positivos_100k") is not None:
            frase = frase_taxa_positivos_100k(x.get("taxa_positivos_100k"))
        notif = x.get("taxa_notif_100k")
        yoy = x.get("taxa_positivos_100k_yoy")
        return {
            "taxa_exames_100k": _fmt_taxa_100k(x.get("taxa_exames_100k")),
            "taxa_positivos_100k": _fmt_taxa_100k(x.get("taxa_positivos_100k")),
            "taxa_notif_100k": (
                _fmt_taxa_100k(notif) if notif is not None else ""
            ),
            "frase_taxa_positivos": frase,
            "taxa_positivos_100k_yoy": (
                _fmt_taxa_100k(yoy) if yoy is not None else ""
            ),
            "yoy_disponivel": "sim" if x.get("yoy_disponivel") else "",
            "nota_yoy": str(x.get("nota_yoy") or ""),
        }

    try:
        from lacen_radar_risco import cartoes_para_relatorio

        cartoes_rel = cartoes_para_relatorio(briefing.cartoes_risco, top=8)
    except Exception:  # noqa: BLE001
        cartoes_rel = []

    return {
        "se_iso": briefing.se_iso,
        "usou_completa": briefing.usou_completa,
        "se_parcial": briefing.se_parcial,
        "nota_taxas": briefing.nota_taxas,
        "mais_solicitados": [
            {
                "target": str(x["target"]),
                "exames": _fmt_num(x["exames"]),
                "positivos": _fmt_num(x["positivos"]),
                "positividade": _pct(x.get("positividade")),
                "tipo_sinal": "Observado",
                **_row_delta(x),
                **_row_taxas(x),
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
                **_row_delta(x),
                **_row_taxas(x),
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
                **_row_taxas(x),
            }
            for x in briefing.localidades
        ],
        "cartoes_risco": cartoes_rel,
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
        "gal_sinan": [
            {
                "municipio": str(g.get("municipio") or "—"),
                "familia": str(g.get("familia") or "—"),
                "target": str(g.get("target") or "—"),
                "exames": _fmt_num(g.get("exames")),
                "notificacoes": _fmt_num(g.get("notificacoes")),
                "flag": str(g.get("flag") or ""),
                "gal_sem_sinan": "sim" if g.get("gal_sem_sinan") else "",
                "sinan_sem_gal": "sim" if g.get("sinan_sem_gal") else "",
                "tipo_sinal": "Observado",
            }
            for g in briefing.gal_sinan[:20]
        ],
        "geo_nivel": str((briefing.geo or {}).get("nivel") or "municipio"),
        "geo_nota": str((briefing.geo or {}).get("nota") or ""),
        "geo_hotspots": [
            {
                "municipio": str(h.get("municipio") or "—"),
                "local": str(h.get("local") or "—"),
                "agravo": str(h.get("agravo") or "—"),
                "n": _fmt_num(h.get("n")),
                "codigo_ibge": str(h.get("codigo_ibge") or ""),
                "nivel": str(h.get("nivel") or ""),
            }
            for h in ((briefing.geo or {}).get("hotspots") or [])[:15]
        ],
        "cruzamento_bases": [
            {
                "fonte": str(c.get("fonte") or ""),
                "status": str(c.get("status") or ""),
                "presente": "sim" if c.get("presente") else "",
                "quando_agrega": str(c.get("quando_agrega") or ""),
            }
            for c in briefing.cruzamento_bases
        ],
        "cruzamento_sih_sia": {
            "caveat": str((briefing.cruzamento_sih_sia or {}).get("caveat") or ""),
            "top_mun": [
                {
                    "fonte": str(r.get("fonte") or ""),
                    "municipio": str(r.get("municipio") or "—"),
                    "cid_familia": str(r.get("cid_familia") or "—"),
                    "n": _fmt_num(r.get("n")),
                }
                for r in ((briefing.cruzamento_sih_sia or {}).get("top_mun") or [])[:12]
            ],
            "familias": list((briefing.cruzamento_sih_sia or {}).get("familias") or []),
        },
        "sinais_rede": {
            "caveat": str((briefing.sinais_rede or {}).get("caveat") or ""),
            "presente": bool((briefing.sinais_rede or {}).get("presente")),
            "indicasus_ocupacao_top": [
                {
                    "tipo_leito": str(r.get("tipo_leito") or "—"),
                    "situacao": str(r.get("situacao") or "—"),
                    "data_ref": str(r.get("data_ref") or ""),
                    "n": _fmt_num(r.get("n")),
                }
                for r in ((briefing.sinais_rede or {}).get("indicasus_ocupacao_top") or [])[:8]
            ],
            "sisreg_hosp_top": [
                {
                    "municipio": str(r.get("municipio") or "—"),
                    "status": str(r.get("status") or "—"),
                    "n": _fmt_num(r.get("n")),
                }
                for r in ((briefing.sinais_rede or {}).get("sisreg_hosp_top") or [])[:8]
            ],
            "sisreg_amb_pendente_top": [
                {
                    "municipio": str(r.get("municipio") or "—"),
                    "status": str(r.get("status") or "—"),
                    "n": _fmt_num(r.get("n")),
                }
                for r in ((briefing.sinais_rede or {}).get("sisreg_amb_pendente_top") or [])[:8]
            ],
        },
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
