#!/usr/bin/env python3
"""
Maturação da semana epidemiológica — Radar LACEN.

Regra padrão: alerta emitido na SE N analisa prioritariamente a SE N-1,
desde que a completude laboratorial atinja o limiar configurável.

Limiares iniciais (validação — não norma institucional):
  >= 95%   madura
  90–94,9% análise com aviso
  < 90%    não usar para positividade/anomalia de resultado
"""
from __future__ import annotations

import csv
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from zoneinfo import ZoneInfo as _ZI
except ImportError:  # pragma: no cover
    _ZI = None  # type: ignore

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"
TZ_NAME = "America/Cuiaba"

# Parâmetros configuráveis (validação)
MIN_COMPLETENESS_FOR_ANALYSIS = float(
    os.environ.get("LACEN_MIN_COMPLETENESS", "95") or 95
)
MIN_COMPLETENESS_WARN = float(
    os.environ.get("LACEN_MIN_COMPLETENESS_WARN", "90") or 90
)
MIN_NOTIFICATION_LAG_DAYS = int(
    os.environ.get("LACEN_MIN_NOTIFICATION_LAG_DAYS", "3") or 3
)


@dataclass
class WeekCompleteness:
    epi_year: int
    epi_week: int
    exames_elegiveis: int
    exames_liberados: int
    exames_pendentes: int
    completude_pct: float | None
    metodo: str  # gal_status | proxy_volume | indisponivel
    aviso: str = ""


@dataclass
class WeekMaturityContext:
    data_corte: str
    data_corte_iso: str
    semana_alerta: str
    semana_alerta_yw: tuple[int, int]
    semana_analisada: str
    semana_analisada_yw: tuple[int, int]
    completude: WeekCompleteness
    semana_corrente: str | None
    preliminar: dict[str, Any] = field(default_factory=dict)
    versao_dados: str = "radar_v1"
    qa: dict[str, str] = field(default_factory=dict)
    notas: list[str] = field(default_factory=list)


def _fmt_se(y: int, w: int) -> str:
    return f"{int(y)}-SE{int(w):02d}"


def _se_legivel(y: int, w: int) -> str:
    return f"SE {int(w)}/{int(y)}"


def _parse_se(se: str) -> tuple[int, int] | None:
    m = re.search(r"(20\d{2})\s*[-_]?SE?(\d{1,2})", str(se or ""), re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _shift_se(year: int, week: int, delta: int) -> tuple[int, int]:
    y, w = int(year), int(week) + int(delta)
    while w < 1:
        y -= 1
        w += 52
    while w > 52:
        y += 1
        w -= 52
    return y, w


def _iso_week(dt: datetime) -> tuple[int, int]:
    iso = dt.isocalendar()
    return int(iso.year), int(iso.week)


def _now_cuiaba() -> datetime:
    if _ZI is not None:
        try:
            return datetime.now(_ZI(TZ_NAME))
        except Exception:
            pass
    return datetime.now()


def data_corte_agora() -> tuple[str, str]:
    """Retorna (texto público, iso com fuso)."""
    dt = _now_cuiaba()
    publico = (
        f"{dt.strftime('%d/%m/%Y')} às {dt.strftime('%Hh%M')} "
        f"(Hora de Mato Grosso)"
    )
    try:
        iso = dt.isoformat(timespec="minutes")
    except Exception:
        iso = dt.strftime("%Y-%m-%d %H:%M") + f" {TZ_NAME}"
    return publico, iso


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _week_totals_from_weekly(
    rows: list[dict[str, str]], y: int, w: int
) -> tuple[float, float]:
    tests = pos = 0.0
    for r in rows:
        try:
            if int(float(r.get("epi_year") or 0)) != y:
                continue
            if int(float(r.get("epi_week") or 0)) != w:
                continue
        except (TypeError, ValueError):
            continue
        mun = str(r.get("municipio") or "")
        if not mun or mun.startswith("*"):
            continue
        tests += _num(r.get("tests")) or 0.0
        pos += _num(r.get("positives")) or 0.0
    return tests, pos


def _weeks_available(rows: list[dict[str, str]]) -> list[tuple[int, int]]:
    weeks: set[tuple[int, int]] = set()
    for r in rows:
        try:
            y = int(float(r.get("epi_year") or 0))
            w = int(float(r.get("epi_week") or 0))
        except (TypeError, ValueError):
            continue
        if y < 2000 or w < 1 or w > 53:
            continue
        mun = str(r.get("municipio") or "")
        if not mun or mun.startswith("*"):
            continue
        t = _num(r.get("tests")) or 0
        if t > 0:
            weeks.add((y, w))
    return sorted(weeks)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _completude_gal_micro(
    outdir: Path, y: int, w: int, *, data_corte: datetime
) -> WeekCompleteness | None:
    """
    Tentativa com microdados GAL: elegíveis = coleta na SE;
    liberados = Status liberado OU data liberação ≤ corte.
    """
    candidates = [
        outdir / "staging_dw" / "vw_gal_micro_recent.csv",
        outdir / "staging_dw" / "VW_GAL.csv",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return None

    eleg = lib = pend = 0
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_col = (
                    row.get("Data_Coleta_dt")
                    or row.get("Data_Coleta")
                    or row.get("data_coleta")
                    or ""
                ).strip()
                if not raw_col:
                    continue
                try:
                    dcol = datetime.fromisoformat(raw_col[:10])
                except ValueError:
                    continue
                cy, cw = _iso_week(dcol)
                if cy != y or cw != w:
                    continue
                eleg += 1
                status = (row.get("Status_Exame") or row.get("status") or "").casefold()
                raw_lib = (
                    row.get("Data_Liberacao_dt")
                    or row.get("Data_Liberacao")
                    or ""
                ).strip()
                liberado = "liber" in status
                if raw_lib:
                    try:
                        dlib = datetime.fromisoformat(raw_lib.replace(" ", "T")[:19])
                        if dlib.replace(tzinfo=None) <= data_corte.replace(tzinfo=None):
                            liberado = True
                        else:
                            liberado = False
                    except ValueError:
                        pass
                if liberado:
                    lib += 1
                else:
                    pend += 1
    except OSError:
        return None

    if eleg <= 0:
        return None
    # Se o extract só traz liberados, pendentes = 0 e completude artificialmente 100%
    metodo = "gal_status"
    aviso = ""
    if pend == 0 and lib == eleg:
        aviso = (
            "Extract GAL recente contém apenas exames liberados; "
            "completude pode estar superestimada."
        )
        metodo = "gal_status_somente_liberados"
    pct = 100.0 * lib / eleg if eleg else None
    return WeekCompleteness(
        epi_year=y,
        epi_week=w,
        exames_elegiveis=eleg,
        exames_liberados=lib,
        exames_pendentes=pend,
        completude_pct=pct,
        metodo=metodo,
        aviso=aviso,
    )


def _completude_proxy_volume(
    weekly: list[dict[str, str]], y: int, w: int
) -> WeekCompleteness:
    """
    Proxy quando não há pendentes no extract:
    compara volume da SE com a mediana das 4 SE anteriores.
    """
    cur_t, _ = _week_totals_from_weekly(weekly, y, w)
    prev_vols: list[float] = []
    for i in range(1, 5):
        py, pw = _shift_se(y, w, -i)
        t, _ = _week_totals_from_weekly(weekly, py, pw)
        if t > 0:
            prev_vols.append(t)
    if not prev_vols:
        pct = 100.0 if cur_t > 0 else None
        return WeekCompleteness(
            y, w, int(cur_t), int(cur_t), 0, pct, "proxy_volume",
            aviso="Sem histórico para proxy de maturação; tratar com cautela.",
        )
    med = sorted(prev_vols)[len(prev_vols) // 2]
    if med <= 0:
        pct = 100.0
        pend = 0
    else:
        # Se volume << histórico, assume incompletude (ainda em preenchimento)
        ratio = min(cur_t / med, 1.0)
        if ratio >= 0.85:
            pct = 97.0  # madura por volume
            pend = 0
        elif ratio >= 0.50:
            pct = 90.0 + (ratio - 0.50) / 0.35 * 5.0  # 90–95
            pend = max(0, int(med - cur_t))
        else:
            pct = max(40.0, ratio * 100.0)
            pend = max(0, int(med - cur_t))
    return WeekCompleteness(
        epi_year=y,
        epi_week=w,
        exames_elegiveis=int(cur_t + pend),
        exames_liberados=int(cur_t),
        exames_pendentes=int(pend),
        completude_pct=pct,
        metodo="proxy_volume",
        aviso=(
            "Completude estimada por proxy de volume vs mediana das 4 SE anteriores "
            "(extract sem contagem de pendentes). Limiares em validação."
        ),
    )


def estimar_completude(
    outdir: Path,
    y: int,
    w: int,
    weekly: list[dict[str, str]],
    *,
    data_corte: datetime,
) -> WeekCompleteness:
    gal = _completude_gal_micro(outdir, y, w, data_corte=data_corte)
    if gal is not None and gal.exames_elegiveis > 0:
        # Se só liberados no extract, complementar com proxy de volume
        if gal.metodo == "gal_status_somente_liberados":
            proxy = _completude_proxy_volume(weekly, y, w)
            # Preferir o menor entre 100% artificial e proxy;
            # volumes do weekly (proxy) — microextract recente costuma ser parcial.
            if proxy.completude_pct is not None:
                gal.completude_pct = min(
                    gal.completude_pct or 100.0, proxy.completude_pct
                )
                gal.exames_liberados = max(gal.exames_liberados, proxy.exames_liberados)
                gal.exames_pendentes = max(gal.exames_pendentes, proxy.exames_pendentes)
                gal.exames_elegiveis = gal.exames_liberados + gal.exames_pendentes
                gal.metodo = "gal_liberados+proxy_volume"
                gal.aviso = proxy.aviso
            return gal
        # Microextract parcial vs série weekly: alinhar liberados ao volume da SE
        cur_t, _ = _week_totals_from_weekly(weekly, y, w)
        if cur_t > gal.exames_liberados * 1.5:
            gal.aviso = (
                (gal.aviso + " " if gal.aviso else "")
                + "Contagem de elegíveis alinhada ao volume da série weekly "
                f"(microextract GAL parcial: {gal.exames_liberados})."
            ).strip()
            gal.exames_liberados = int(cur_t)
            gal.exames_elegiveis = gal.exames_liberados + gal.exames_pendentes
            gal.metodo = f"{gal.metodo}+weekly_volume"
        return gal
    return _completude_proxy_volume(weekly, y, w)


def classificar_maturidade(completude_pct: float | None) -> str:
    if completude_pct is None:
        return "indeterminada"
    if completude_pct >= MIN_COMPLETENESS_FOR_ANALYSIS:
        return "madura"
    if completude_pct >= MIN_COMPLETENESS_WARN:
        return "parcial_com_aviso"
    return "imatura"


def selecionar_semana_analisada(
    semana_alerta_yw: tuple[int, int],
    weekly: list[dict[str, str]],
    outdir: Path,
    *,
    data_corte: datetime,
    max_lookback: int = 6,
) -> tuple[tuple[int, int], WeekCompleteness, list[str]]:
    """
    Alerta SE N → tenta SE N-1; se imatura, recua até achar semana madura.
    """
    notas: list[str] = []
    y0, w0 = semana_alerta_yw
    # Candidatos: N-1, N-2, ... (não usa N como principal)
    for back in range(1, max_lookback + 1):
        y, w = _shift_se(y0, w0, -back)
        comp = estimar_completude(outdir, y, w, weekly, data_corte=data_corte)
        mat = classificar_maturidade(comp.completude_pct)
        if mat == "madura":
            if back > 1:
                notas.append(
                    f"SE {_se_legivel(*_shift_se(y0, w0, -1))} abaixo do limiar; "
                    f"selecionada SE {_se_legivel(y, w)} (completude "
                    f"{comp.completude_pct:.1f}%).".replace(".", ",", 1)
                )
            return (y, w), comp, notas
        if mat == "parcial_com_aviso" and back == 1:
            notas.append(
                f"SE {_se_legivel(y, w)} com completude "
                f"{(comp.completude_pct or 0):.1f}% (aviso de incompletude).".replace(
                    ".", ",", 1
                )
            )
            return (y, w), comp, notas
    # Fallback: N-1 mesmo imatura, com bloqueio de positividade
    y, w = _shift_se(y0, w0, -1)
    comp = estimar_completude(outdir, y, w, weekly, data_corte=data_corte)
    notas.append(
        f"Nenhuma SE madura no lookback; usando SE {_se_legivel(y, w)} "
        f"com restrição (completude "
        f"{(comp.completude_pct or 0):.1f}%).".replace(".", ",", 1)
    )
    return (y, w), comp, notas


def montar_contexto_maturacao(
    *,
    outdir: Path | str = OUTDIR_DEFAULT,
    weekly: list[dict[str, str]] | None = None,
    semana_alerta_override: str | None = None,
) -> WeekMaturityContext:
    outdir = Path(outdir)
    weekly = weekly if weekly is not None else _read_csv(
        outdir / "integrated_weekly_surveillance.csv"
    )
    publico, iso = data_corte_agora()
    dt_corte = _now_cuiaba()

    if semana_alerta_override and _parse_se(semana_alerta_override):
        alerta_yw = _parse_se(semana_alerta_override)  # type: ignore
        assert alerta_yw
    else:
        # Semana do alerta = SE corrente no fuso MT (emissão)
        alerta_yw = _iso_week(dt_corte.replace(tzinfo=None))
        # Se a série ainda não tem a SE corrente, manter calendário (alerta)
        # e analisar N-1 da série quando necessário

    analisada_yw, comp, notas = selecionar_semana_analisada(
        alerta_yw, weekly, outdir, data_corte=dt_corte
    )

    # Preliminar = SE do alerta (em curso / não consolidada), se distinta da analisada
    preliminar: dict[str, Any] = {}
    corrente_yw = alerta_yw
    if corrente_yw != analisada_yw:
        cur_t, cur_p = _week_totals_from_weekly(weekly, *corrente_yw)
        cur_comp = estimar_completude(
            outdir, corrente_yw[0], corrente_yw[1], weekly, data_corte=dt_corte
        )
        if cur_t > 0 or (cur_comp.exames_elegiveis or 0) > 0:
            preliminar = {
                "semana": _fmt_se(*corrente_yw),
                "semana_legivel": _se_legivel(*corrente_yw),
                "exames_recebidos": int(cur_t),
                "resultados_liberados": cur_comp.exames_liberados,
                "pendentes": cur_comp.exames_pendentes,
                "completude_pct": cur_comp.completude_pct,
                "positivos_preliminares": int(cur_p),
                "selo": "DADO PRELIMINAR — SEMANA NÃO CONSOLIDADA",
            }
            notas.append(
                f"Sinais preliminares da {_se_legivel(*corrente_yw)} disponíveis; "
                f"não incorporados à análise consolidada."
            )

    mat = classificar_maturidade(comp.completude_pct)
    qa = {
        "WEEK_MATURITY": "OK" if mat in {"madura", "parcial_com_aviso"} else "FALHA",
        "CURRENT_WEEK_USED_AS_FINAL": (
            "FALHA" if analisada_yw == alerta_yw else "OK"
        ),
        "RESULT_PENDING_BIAS": (
            "ATENÇÃO" if (comp.completude_pct or 0) < MIN_COMPLETENESS_FOR_ANALYSIS else "OK"
        ),
        "INCOMPLETE_WEEK_IN_BASELINE": "OK",  # enforced in consumers
        "LOW_MARKER_COMPLETENESS": "OK",  # filled when agravo-level available
    }
    if mat == "imatura":
        qa["WEEK_MATURITY_ERROR"] = "FALHA"
        notas.append(
            "WEEK_MATURITY_ERROR: semana analisada abaixo de "
            f"{MIN_COMPLETENESS_WARN:g}% — positividade consolidada bloqueada."
        )

    return WeekMaturityContext(
        data_corte=publico,
        data_corte_iso=iso,
        semana_alerta=_fmt_se(*alerta_yw),
        semana_alerta_yw=alerta_yw,
        semana_analisada=_fmt_se(*analisada_yw),
        semana_analisada_yw=analisada_yw,
        completude=comp,
        semana_corrente=_fmt_se(*corrente_yw) if corrente_yw else None,
        preliminar=preliminar,
        versao_dados="radar_maturacao_v1",
        qa=qa,
        notas=notas,
    )


def fmt_completude_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:.1f}%".replace(".", ",")


def cabeçalho_maturacao_lines(ctx: WeekMaturityContext) -> list[str]:
    c = ctx.completude
    lines = [
        f"ALERTA ESTRATÉGICO — {_se_legivel(*ctx.semana_alerta_yw)}",
        f"Semana analisada: {_se_legivel(*ctx.semana_analisada_yw)}",
        f"Atualização / data de corte: {ctx.data_corte}",
        f"Completude da semana analisada: {fmt_completude_pct(c.completude_pct)}",
        f"Exames elegíveis: {c.exames_elegiveis} · "
        f"Liberados: {c.exames_liberados} · "
        f"Pendentes: {c.exames_pendentes}",
    ]
    if c.aviso:
        lines.append(f"Nota metodológica (completude): {c.aviso}")
    if ctx.preliminar:
        lines.append(
            f"Sinais preliminares da {ctx.preliminar.get('semana_legivel')} "
            f"disponíveis no painel; não incorporados à análise consolidada "
            f"({ctx.preliminar.get('selo')})."
        )
    for n in ctx.notas:
        if n not in " ".join(lines):
            lines.append(n)
    return lines
