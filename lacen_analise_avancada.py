#!/usr/bin/env python3
"""
Camada analítica avançada — Radar LACEN.

Consolida:
  - positividade % (n_pos/n_validos)
  - tendência 4–8 semanas
  - nowcasting da SE de alerta
  - predição 1–3 semanas (volume/positividade/risco)
  - linkage VW_INTERNACAO (município × família CID)
  - contexto INDICASUS / indicadores VS

Artefatos em saida_pipeline/analise_*.csv (+ parquet best-effort).
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lacen_briefing_epi import _norm_mun, _shift_se

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"

_CID_MAP = (
    (("dengue", "chikung", "zika", "arbovir"), "dengue_arbovirose"),
    (("tubercul",), "tuberculose"),
    (("hepatite", "hbv", "hcv", "hav"), "hepatite"),
)


@dataclass
class MunContext:
    municipio: str
    municipio_key: str
    internacoes: int
    internacoes_por_100k: float | None
    internacao_semana_ref: str
    cid_familia: str | None
    indicasus_score: float | None
    aviso: str = ""


@dataclass
class AgravoForecast:
    agravo: str
    target: str
    s1_exames: float | None
    s1_low: float | None
    s1_high: float | None
    s1_positividade_pct: float | None
    s2_exames: float | None
    s3_exames: float | None
    risco_label: str
    metodo: str


@dataclass
class AdvancedMetrics:
    se_analisada: tuple[int, int]
    se_alerta: tuple[int, int]
    positividade_estadual_pct: float | None
    positivos_estadual: int
    validos_estadual: int
    tendencia_volume: str
    tendencia_positividade: str
    tendencia_internacao: str
    nowcasting_exames_est: int | None
    nowcasting_intervalo: tuple[int, int] | None
    nowcasting_selo: str
    predicao_exames_sem1: int | None
    predicao_exames_sem2: int | None
    predicao_exames_sem3: int | None
    predicao_intervalo_sem1: tuple[int, int] | None
    predicao_intervalo_sem2: tuple[int, int] | None
    predicao_intervalo_sem3: tuple[int, int] | None
    predicao_positividade_pct_s1: float | None
    predicoes_agravo: list[AgravoForecast]
    internacoes_analisada: int
    internacoes_ref_mediana4: float
    internacoes_semana_usada: str
    internacoes_por_100k_estado: float | None
    indicasus_score_mediano: float | None
    mun_context: dict[str, MunContext]
    consolidado_rows: list[dict[str, Any]]
    fonte_internacao: str
    fonte_indicasus: str
    warnings: list[str] = field(default_factory=list)
    versao: str = "analise_avancada_v2"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _clean(s: Any) -> str:
    return re.sub(r"[\x00-\x1f]", "", str(s or "")).strip()


def _to_int(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _to_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _fmt_se(y: int, w: int) -> str:
    return f"{int(y)}-SE{int(w):02d}"


def _trend(cur: float, base: float) -> str:
    if base <= 0 and cur > 0:
        return "aumento"
    if base <= 0:
        return "estável"
    ratio = (cur - base) / base
    if ratio >= 0.15:
        return "aumento"
    if ratio <= -0.15:
        return "queda"
    return "estável"


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(max(var, 0.0))


def _fmt_interval(center: float, sd: float) -> tuple[int, int]:
    low = max(0, int(round(center - 1.96 * sd)))
    high = max(low, int(round(center + 1.96 * sd)))
    return low, high


def _cid_familia(agravo: str) -> str | None:
    low = (agravo or "").casefold()
    for keys, fam in _CID_MAP:
        if any(k in low for k in keys):
            return fam
    return None


def _series_weekly(
    weekly: list[dict[str, str]], yw: tuple[int, int], key: str
) -> list[float]:
    y, w = yw
    vals: list[float] = []
    for i in range(8):
        yi, wi = _shift_se(y, w, -i)
        total = 0.0
        for r in weekly:
            if _to_int(r.get("epi_year")) != yi or _to_int(r.get("epi_week")) != wi:
                continue
            mun = _clean(r.get("municipio"))
            if not mun or mun.startswith("*"):
                continue
            total += float(_to_float(r.get(key)) or 0.0)
        vals.append(total)
    return vals


def _load_populacao(outdir: Path) -> dict[str, int]:
    rows = _read_csv(outdir / "staging_dw" / "populacao_total.csv")
    if not rows:
        rows = _read_csv(outdir / "staging_dw" / "populacao.csv")
    by_mun: dict[str, dict[str, float]] = {}
    for r in rows:
        mun = _norm_mun(_clean(r.get("Municipio")))
        if not mun:
            continue
        ano = _clean(r.get("Ano"))
        pop = _to_float(r.get("PopulacaoResidente")) or 0.0
        by_mun.setdefault(mun, {})
        by_mun[mun][ano] = by_mun[mun].get(ano, 0.0) + pop
    out: dict[str, int] = {}
    for mun, anos in by_mun.items():
        if not anos:
            continue
        latest = max(anos.keys())
        out[mun] = int(anos[latest])
    return out


def _load_indicasus_scores(outdir: Path) -> dict[str, float]:
    """Score municipal a partir de INDICADORES / VS (último ano disponível)."""
    rows = _read_csv(outdir / "staging_dw" / "indicadores.csv")
    scores: dict[str, list[float]] = {}
    if rows:
        # preferir anos mais recentes
        anos = sorted({_clean(r.get("ANO")) for r in rows if _clean(r.get("ANO"))})
        keep = set(anos[-2:]) if anos else set()
        for r in rows:
            if keep and _clean(r.get("ANO")) not in keep:
                continue
            mun = _norm_mun(_clean(r.get("MUNICIPIO")))
            val = _to_float(r.get("VALORINDICADORMUNICIPIO"))
            if mun and val is not None:
                scores.setdefault(mun, []).append(val)
    if not scores:
        vs = _read_csv(outdir / "staging_dw" / "indicadoresvigilanciasaude.csv")
        anos = sorted({_clean(r.get("Ano")) for r in vs if _clean(r.get("Ano"))})
        keep = set(anos[-1:]) if anos else set()
        for r in vs:
            if keep and _clean(r.get("Ano")) not in keep:
                continue
            mun = _norm_mun(_clean(r.get("Municipio")))
            num = _to_float(r.get("Numerador"))
            den = _to_float(r.get("Denominador"))
            if mun and num is not None and den and den > 0:
                scores.setdefault(mun, []).append(100.0 * num / den)
    return {k: _median(v) for k, v in scores.items() if v}


def _sih_weeks(sih: list[dict[str, str]]) -> list[tuple[int, int]]:
    weeks: set[tuple[int, int]] = set()
    for r in sih:
        y, w = _to_int(r.get("epi_year")), _to_int(r.get("epi_week"))
        if y >= 2000 and 1 <= w <= 53:
            weeks.add((y, w))
    return sorted(weeks)


def _internacoes_semana(
    sih: list[dict[str, str]], yw: tuple[int, int], *, familia: str | None = None
) -> int:
    y, w = yw
    n = 0
    for r in sih:
        if _to_int(r.get("epi_year")) != y or _to_int(r.get("epi_week")) != w:
            continue
        if familia and _clean(r.get("cid_familia")).casefold() != familia.casefold():
            continue
        n += _to_int(r.get("n_internacoes"))
    return n


def _internacoes_mun(
    sih: list[dict[str, str]],
    yw: tuple[int, int],
    mun_key: str,
    *,
    familia: str | None = None,
) -> int:
    y, w = yw
    n = 0
    for r in sih:
        if _to_int(r.get("epi_year")) != y or _to_int(r.get("epi_week")) != w:
            continue
        if _norm_mun(_clean(r.get("municipio"))) != mun_key:
            continue
        if familia and _clean(r.get("cid_familia")).casefold() != familia.casefold():
            # se família pedida e não bate, ainda conta total do mun se familia None
            continue
        n += _to_int(r.get("n_internacoes"))
    return n


def _escolher_semana_sih(
    sih: list[dict[str, str]], se_analisada: tuple[int, int]
) -> tuple[tuple[int, int], str]:
    """Usa SE analisada; se vazia, recua à última SE com dados SIH (lag operacional)."""
    if _internacoes_semana(sih, se_analisada) > 0:
        return se_analisada, "semana_analisada"
    weeks = _sih_weeks(sih)
    if not weeks:
        return se_analisada, "indisponivel"
    # última semana SIH <= analisada, senão última disponível
    cand = [w for w in weeks if w <= se_analisada]
    chosen = cand[-1] if cand else weeks[-1]
    return chosen, "lag_sih_ultima_disponivel"


def _load_forecasts(outdir: Path) -> list[AgravoForecast]:
    rows = _read_csv(outdir / "ml_forecast_demanda.csv")
    by_tgt: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        tgt = _clean(r.get("target"))
        if not tgt:
            continue
        by_tgt.setdefault(tgt, []).append(r)
    out: list[AgravoForecast] = []
    priority = ("dengue", "tuberculose", "hepatite_b", "hepatite_c", "covid", "sars")
    keys = sorted(
        by_tgt.keys(),
        key=lambda t: (0 if any(p in t.casefold() for p in priority) else 1, t),
    )
    for tgt in keys[:12]:
        steps = {
            _to_int(r.get("forecast_step")): r
            for r in by_tgt[tgt]
            if _to_int(r.get("forecast_step")) in {1, 2, 3}
        }
        if 1 not in steps:
            continue
        s1 = steps[1]
        s2 = steps.get(2)
        s3 = steps.get(3)
        pos = _to_float(s1.get("forecast_positividade"))
        pos_pct = (pos * 100.0) if pos is not None and pos <= 1.0 else pos
        exames = _to_float(s1.get("forecast_tests")) or 0.0
        if pos_pct is not None and pos_pct >= 5 and exames >= 20:
            risco = "alto"
        elif pos_pct is not None and pos_pct >= 2 and exames >= 10:
            risco = "moderado"
        else:
            risco = "baixo"
        out.append(
            AgravoForecast(
                agravo=tgt.replace("_", " "),
                target=tgt,
                s1_exames=_to_float(s1.get("forecast_tests")),
                s1_low=_to_float(s1.get("forecast_tests_low")),
                s1_high=_to_float(s1.get("forecast_tests_high")),
                s1_positividade_pct=pos_pct,
                s2_exames=_to_float(s2.get("forecast_tests")) if s2 else None,
                s3_exames=_to_float(s3.get("forecast_tests")) if s3 else None,
                risco_label=risco,
                metodo=_clean(s1.get("metodo")) or "ewma",
            )
        )
    return out


def _build_consolidado(
    weekly: list[dict[str, str]],
    se_analisada: tuple[int, int],
    sih: list[dict[str, str]],
    sih_yw: tuple[int, int],
    pop: dict[str, int],
    ind_scores: dict[str, float],
) -> list[dict[str, Any]]:
    y, w = se_analisada
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for r in weekly:
        if _to_int(r.get("epi_year")) != y or _to_int(r.get("epi_week")) != w:
            continue
        mun = _clean(r.get("municipio"))
        if not mun or mun.startswith("*"):
            continue
        tgt = _clean(r.get("target") or r.get("agravo") or "geral")
        key = (_norm_mun(mun), tgt.casefold())
        ex = _to_int(r.get("tests"))
        pos = _to_int(r.get("positives"))
        if key not in agg:
            agg[key] = {
                "epi_year": y,
                "epi_week": w,
                "municipio": mun,
                "municipio_key": _norm_mun(mun),
                "agravo": tgt,
                "exames": 0,
                "positivos": 0,
            }
        agg[key]["exames"] += ex
        agg[key]["positivos"] += pos

    rows: list[dict[str, Any]] = []
    for item in agg.values():
        ex = int(item["exames"])
        pos = int(item["positivos"])
        pct = (100.0 * pos / ex) if ex > 0 else None
        fam = _cid_familia(str(item["agravo"]))
        mk = str(item["municipio_key"])
        intern = _internacoes_mun(sih, sih_yw, mk, familia=fam) if fam else _internacoes_mun(
            sih, sih_yw, mk
        )
        pop_n = pop.get(mk)
        rate = (100000.0 * intern / pop_n) if pop_n and pop_n > 0 else None
        rows.append(
            {
                **item,
                "positividade_pct": None if pct is None else round(pct, 4),
                "cid_familia": fam or "",
                "internacoes": intern,
                "internacoes_por_100k": None if rate is None else round(rate, 4),
                "indicasus_score": ind_scores.get(mk),
                "sih_semana_ref": _fmt_se(*sih_yw),
            }
        )
    rows.sort(key=lambda x: (-int(x["exames"]), str(x["municipio"]), str(x["agravo"])))
    return rows


def build_advanced_metrics(
    *,
    outdir: Path | str = OUTDIR_DEFAULT,
    se_analisada: tuple[int, int],
    se_alerta: tuple[int, int],
    completude_pct_alerta: float | None,
) -> AdvancedMetrics:
    outdir = Path(outdir)
    weekly = _read_csv(outdir / "integrated_weekly_surveillance.csv")
    sih = _read_csv(outdir / "staging_dw" / "sih_mun_cid_familia_agg.csv")
    if not sih:
        # fallback: totais municipais sem família CID
        raw = _read_csv(outdir / "staging_dw" / "sih_mun_semana_agg.csv")
        sih = [
            {
                **r,
                "cid_familia": "",
            }
            for r in raw
        ]
    pop = _load_populacao(outdir)
    ind_scores = _load_indicasus_scores(outdir)
    sih_yw, sih_mode = _escolher_semana_sih(sih, se_analisada)

    exams_series = _series_weekly(weekly, se_analisada, "tests")
    pos_series = _series_weekly(weekly, se_analisada, "positives")
    cur_ex = exams_series[0] if exams_series else 0.0
    cur_pos = pos_series[0] if pos_series else 0.0
    base_ex = _median(exams_series[1:5]) if len(exams_series) > 1 else 0.0
    base_pos = _median(pos_series[1:5]) if len(pos_series) > 1 else 0.0
    pos_pct = (100.0 * cur_pos / cur_ex) if cur_ex > 0 else None
    base_pct = (100.0 * base_pos / base_ex) if base_ex > 0 else 0.0

    intern_cur = _internacoes_semana(sih, sih_yw)
    intern_prev = [
        float(_internacoes_semana(sih, _shift_se(sih_yw[0], sih_yw[1], -i)))
        for i in range(1, 5)
    ]
    intern_med = _median(intern_prev)
    pop_estado = sum(pop.values()) or None
    intern_100k = (
        100000.0 * intern_cur / pop_estado if pop_estado and pop_estado > 0 else None
    )

    alert_ex_series = _series_weekly(weekly, se_alerta, "tests")
    now_obs = alert_ex_series[0] if alert_ex_series else 0.0
    comp = completude_pct_alerta or 0.0
    now_est = int(round(now_obs / max(comp / 100.0, 0.20))) if now_obs > 0 else None
    now_sd = _std(exams_series[1:5]) if len(exams_series) > 4 else _std(exams_series)
    now_itv = (
        _fmt_interval(float(now_est), max(now_sd, now_est * 0.10)) if now_est else None
    )
    now_selo = "DADO PRELIMINAR — SEMANA NÃO CONSOLIDADA"

    hist = exams_series[:6] if exams_series else []
    m_hist = (sum(hist) / len(hist)) if hist else 0.0
    sd_hist = _std(hist)
    p1 = int(round(m_hist)) if m_hist > 0 else None
    p2 = int(round(m_hist * 1.02)) if m_hist > 0 else None
    p3 = int(round(m_hist * 1.04)) if m_hist > 0 else None
    p1i = _fmt_interval(float(p1), max(sd_hist, (p1 or 0) * 0.12)) if p1 else None
    p2i = _fmt_interval(float(p2), max(sd_hist, (p2 or 0) * 0.14)) if p2 else None
    p3i = _fmt_interval(float(p3), max(sd_hist, (p3 or 0) * 0.16)) if p3 else None

    # positividade esperada S+1: média ponderada dos forecasts prioritários
    forecasts = _load_forecasts(outdir)
    pos_preds = [
        f.s1_positividade_pct
        for f in forecasts
        if f.s1_positividade_pct is not None and f.s1_exames and f.s1_exames >= 5
    ]
    pred_pos = _median(pos_preds) if pos_preds else None

    consolidado = _build_consolidado(
        weekly, se_analisada, sih, sih_yw, pop, ind_scores
    )

    mun_ctx: dict[str, MunContext] = {}
    for row in consolidado:
        mk = str(row["municipio_key"])
        if mk in mun_ctx:
            # acumula internações máximas relevantes
            if int(row["internacoes"]) > mun_ctx[mk].internacoes:
                mun_ctx[mk].internacoes = int(row["internacoes"])
                mun_ctx[mk].internacoes_por_100k = row.get("internacoes_por_100k")
                mun_ctx[mk].cid_familia = row.get("cid_familia") or None
            continue
        aviso = ""
        if sih_mode == "lag_sih_ultima_disponivel":
            aviso = f"Internações referem-se a {_fmt_se(*sih_yw)} (lag SIH)."
        mun_ctx[mk] = MunContext(
            municipio=str(row["municipio"]),
            municipio_key=mk,
            internacoes=int(row["internacoes"]),
            internacoes_por_100k=row.get("internacoes_por_100k"),
            internacao_semana_ref=_fmt_se(*sih_yw),
            cid_familia=row.get("cid_familia") or None,
            indicasus_score=row.get("indicasus_score"),
            aviso=aviso,
        )

    warnings: list[str] = []
    if not sih:
        warnings.append("Linkage de internação indisponível no corte.")
    elif sih_mode == "lag_sih_ultima_disponivel":
        warnings.append(
            f"SIH sem dados na SE analisada; usando {_fmt_se(*sih_yw)} "
            "(última disponível — ressalva de defasagem)."
        )
    if not ind_scores:
        warnings.append("Base INDICASUS/indicadores indisponível ou sem valores recentes.")
    if completude_pct_alerta is not None and completude_pct_alerta < 95:
        warnings.append(
            "Nowcasting com alta incerteza por completude parcial da SE de alerta."
        )

    fonte_sih = (
        "staging_dw/sih_mun_cid_familia_agg.csv"
        if (outdir / "staging_dw" / "sih_mun_cid_familia_agg.csv").is_file()
        else "staging_dw/sih_mun_semana_agg.csv"
    )
    fonte_ind = (
        "staging_dw/indicadores.csv"
        if (outdir / "staging_dw" / "indicadores.csv").is_file()
        else "staging_dw/indicadoresvigilanciasaude.csv"
    )

    return AdvancedMetrics(
        se_analisada=se_analisada,
        se_alerta=se_alerta,
        positividade_estadual_pct=pos_pct,
        positivos_estadual=int(cur_pos),
        validos_estadual=int(cur_ex),
        tendencia_volume=_trend(cur_ex, base_ex),
        tendencia_positividade=_trend(pos_pct or 0.0, base_pct),
        tendencia_internacao=_trend(float(intern_cur), intern_med),
        nowcasting_exames_est=now_est,
        nowcasting_intervalo=now_itv,
        nowcasting_selo=now_selo,
        predicao_exames_sem1=p1,
        predicao_exames_sem2=p2,
        predicao_exames_sem3=p3,
        predicao_intervalo_sem1=p1i,
        predicao_intervalo_sem2=p2i,
        predicao_intervalo_sem3=p3i,
        predicao_positividade_pct_s1=pred_pos,
        predicoes_agravo=forecasts,
        internacoes_analisada=intern_cur,
        internacoes_ref_mediana4=intern_med,
        internacoes_semana_usada=_fmt_se(*sih_yw),
        internacoes_por_100k_estado=intern_100k,
        indicasus_score_mediano=_median(list(ind_scores.values())) if ind_scores else None,
        mun_context=mun_ctx,
        consolidado_rows=consolidado,
        fonte_internacao=fonte_sih,
        fonte_indicasus=fonte_ind,
        warnings=warnings,
    )


def lookup_mun_context(m: AdvancedMetrics, municipio: str) -> MunContext | None:
    return m.mun_context.get(_norm_mun(municipio))


def export_advanced_outputs(outdir: Path | str, m: AdvancedMetrics) -> None:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    def _write_csv(p: Path, header: list[str], data: list[list[Any]]) -> None:
        with p.open("w", encoding="utf-8", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(header)
            wr.writerows(data)

    resumo = [
        ["versao", m.versao],
        ["se_analisada", _fmt_se(*m.se_analisada)],
        ["se_alerta", _fmt_se(*m.se_alerta)],
        [
            "positividade_estadual_pct",
            "" if m.positividade_estadual_pct is None else f"{m.positividade_estadual_pct:.4f}",
        ],
        ["positivos_estadual", str(m.positivos_estadual)],
        ["validos_estadual", str(m.validos_estadual)],
        ["tendencia_volume", m.tendencia_volume],
        ["tendencia_positividade", m.tendencia_positividade],
        ["tendencia_internacao", m.tendencia_internacao],
        [
            "nowcasting_exames_est",
            "" if m.nowcasting_exames_est is None else str(m.nowcasting_exames_est),
        ],
        ["nowcasting_selo", m.nowcasting_selo],
        [
            "predicao_exames_sem1",
            "" if m.predicao_exames_sem1 is None else str(m.predicao_exames_sem1),
        ],
        [
            "predicao_exames_sem2",
            "" if m.predicao_exames_sem2 is None else str(m.predicao_exames_sem2),
        ],
        [
            "predicao_exames_sem3",
            "" if m.predicao_exames_sem3 is None else str(m.predicao_exames_sem3),
        ],
        [
            "predicao_positividade_pct_s1",
            ""
            if m.predicao_positividade_pct_s1 is None
            else f"{m.predicao_positividade_pct_s1:.4f}",
        ],
        ["internacoes", str(m.internacoes_analisada)],
        ["internacoes_semana_usada", m.internacoes_semana_usada],
        ["internacoes_mediana4", f"{m.internacoes_ref_mediana4:.2f}"],
        [
            "internacoes_por_100k_estado",
            ""
            if m.internacoes_por_100k_estado is None
            else f"{m.internacoes_por_100k_estado:.4f}",
        ],
        [
            "indicasus_score_mediano",
            ""
            if m.indicasus_score_mediano is None
            else f"{m.indicasus_score_mediano:.4f}",
        ],
        ["warnings", " | ".join(m.warnings)],
        ["fonte_internacao", m.fonte_internacao],
        ["fonte_indicasus", m.fonte_indicasus],
    ]
    _write_csv(outdir / "analise_avancada_resumo.csv", ["metrica", "valor"], resumo)

    _write_csv(
        outdir / "analise_tendencias.csv",
        ["escopo", "semana", "metrica", "tendencia"],
        [
            ["se_analisada", _fmt_se(*m.se_analisada), "volume", m.tendencia_volume],
            [
                "se_analisada",
                _fmt_se(*m.se_analisada),
                "positividade",
                m.tendencia_positividade,
            ],
            [
                "se_analisada",
                _fmt_se(*m.se_analisada),
                "internacao",
                m.tendencia_internacao,
            ],
        ],
    )

    _write_csv(
        outdir / "analise_nowcasting.csv",
        [
            "semana_alerta",
            "estimativa_exames",
            "ic95_low",
            "ic95_high",
            "selo",
            "completude_ref_pct",
        ],
        [
            [
                _fmt_se(*m.se_alerta),
                m.nowcasting_exames_est,
                (m.nowcasting_intervalo or (None, None))[0],
                (m.nowcasting_intervalo or (None, None))[1],
                m.nowcasting_selo,
                "",
            ]
        ],
    )

    pred_rows = [
        [
            f.agravo,
            f.target,
            f.s1_exames,
            f.s1_low,
            f.s1_high,
            f.s1_positividade_pct,
            f.s2_exames,
            f.s3_exames,
            f.risco_label,
            f.metodo,
        ]
        for f in m.predicoes_agravo
    ]
    # também linha estadual agregada
    pred_rows.insert(
        0,
        [
            "estadual_volume",
            "statewide_tests",
            m.predicao_exames_sem1,
            (m.predicao_intervalo_sem1 or (None, None))[0],
            (m.predicao_intervalo_sem1 or (None, None))[1],
            m.predicao_positividade_pct_s1,
            m.predicao_exames_sem2,
            m.predicao_exames_sem3,
            "—",
            "media_historica_6se",
        ],
    )
    _write_csv(
        outdir / "analise_predicoes.csv",
        [
            "agravo",
            "target",
            "s1_exames",
            "s1_low",
            "s1_high",
            "s1_positividade_pct",
            "s2_exames",
            "s3_exames",
            "risco",
            "metodo",
        ],
        pred_rows,
    )

    lnk_rows = [
        [
            ctx.municipio,
            ctx.municipio_key,
            ctx.internacoes,
            ctx.internacoes_por_100k,
            ctx.internacao_semana_ref,
            ctx.cid_familia or "",
            ctx.indicasus_score,
            ctx.aviso,
            m.fonte_internacao,
            m.fonte_indicasus,
        ]
        for ctx in sorted(m.mun_context.values(), key=lambda x: -x.internacoes)[:200]
    ]
    _write_csv(
        outdir / "analise_linkage_contexto.csv",
        [
            "municipio",
            "municipio_key",
            "internacoes",
            "internacoes_por_100k",
            "sih_semana_ref",
            "cid_familia",
            "indicasus_score",
            "aviso",
            "fonte_internacao",
            "fonte_indicasus",
        ],
        lnk_rows,
    )

    cons_header = [
        "epi_year",
        "epi_week",
        "municipio",
        "municipio_key",
        "agravo",
        "exames",
        "positivos",
        "positividade_pct",
        "cid_familia",
        "internacoes",
        "internacoes_por_100k",
        "indicasus_score",
        "sih_semana_ref",
    ]
    cons_data = [
        [r.get(h) for h in cons_header] for r in m.consolidado_rows[:5000]
    ]
    _write_csv(outdir / "analise_consolidado_mun_agravo.csv", cons_header, cons_data)

    try:
        import pandas as pd

        pd.DataFrame(resumo, columns=["metrica", "valor"]).to_parquet(
            outdir / "analise_avancada_resumo.parquet", index=False
        )
        pd.DataFrame(m.consolidado_rows).to_parquet(
            outdir / "analise_consolidado_mun_agravo.parquet", index=False
        )
        pd.DataFrame(
            pred_rows,
            columns=[
                "agravo",
                "target",
                "s1_exames",
                "s1_low",
                "s1_high",
                "s1_positividade_pct",
                "s2_exames",
                "s3_exames",
                "risco",
                "metodo",
            ],
        ).to_parquet(outdir / "analise_predicoes.parquet", index=False)
        pd.DataFrame(
            lnk_rows,
            columns=[
                "municipio",
                "municipio_key",
                "internacoes",
                "internacoes_por_100k",
                "sih_semana_ref",
                "cid_familia",
                "indicasus_score",
                "aviso",
                "fonte_internacao",
                "fonte_indicasus",
            ],
        ).to_parquet(outdir / "analise_linkage_contexto.parquet", index=False)
    except Exception:
        pass
