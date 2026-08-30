#!/usr/bin/env python3
"""
LACEN-MT / CIEVS / Vigidesastres — relatório institucional 2×/semana.

Monta payload fixo (blocos A–D) a partir de agregados em `saida_pipeline`
(sem PII/microdados) e formata para Telegram (curto) e e-mail (completo).

Uso:
  from lacen_relatorio_cievs import montar_relatorio, to_telegram_markdown, to_email_html
"""
from __future__ import annotations

import csv
import html
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"

DASHBOARD_URL = (
    "https://menandesneto51-lacen-mt-lacen-dashboard-integrado-total-nrdgik.streamlit.app/"
)

ORGAOS = ("LACEN-MT", "CIEVS", "Vigidesastres")


def _cell(row: dict, *keys: str, default: str = "—") -> str:
    for k in keys:
        if k in row and str(row.get(k) or "").strip():
            return str(row[k]).strip()
    return default


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


def _fmt_pct(x: float | None, digits: int = 0) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    v = x * 100 if abs(x) <= 1.5 else x
    return f"{v:.{digits}f}%"


def _fmt_num(x: float | None, digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.{digits}f}"


def _truthy(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    if s in ("1", "true", "sim", "yes", "t", "verdadeiro"):
        return True
    n = _num(val)
    return n is not None and n > 0 and s not in ("0", "false", "nao", "não", "n")


def _read_csv(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if limit is not None:
        return rows[:limit]
    return rows


def _short_driver(text: str, max_len: int = 120) -> str:
    t = (text or "").strip()
    if not t or t == "—":
        return "—"
    # Prefer first semicolon-separated driver chunk
    chunk = t.split(";")[0].strip()
    if len(chunk) > max_len:
        return chunk[: max_len - 1] + "…"
    return chunk


@dataclass
class RelatorioCIEVS:
    """Payload institucional do relatório 2×/semana."""

    orgaos: Sequence[str] = ORGAOS
    gerado_em: str = ""
    semana_epidemiologica: str = "—"
    leitura_situacional: str = "rede estável"
    dashboard_url: str = DASHBOARD_URL
    # Bloco A
    top_positivos: list[dict[str, str]] = field(default_factory=list)
    variacao_se: str = "—"
    n_primeira_deteccao_alerta: int = 0
    top_divergencias: list[dict[str, str]] = field(default_factory=list)
    # Bloco B
    tat_mediano: str = "—"
    tat_p90: str = "—"
    pct_48h: str = "—"
    top_pressao: list[dict[str, str]] = field(default_factory=list)
    silencio_vizinho_quente: list[dict[str, str]] = field(default_factory=list)
    # Bloco C
    fila_acoes: list[dict[str, str]] = field(default_factory=list)
    preditos_alta: list[dict[str, str]] = field(default_factory=list)
    # Bloco D
    cobertura_municipios: str = "—"
    confirmacao_alertas: str = "—"
    fontes_presentes: list[str] = field(default_factory=list)
    nota: str = (
        "Relatório agregado — rótulos Observado / Derivado / Predito. "
        "Sem PII ou microdados nominais."
    )

    def __post_init__(self) -> None:
        if not self.gerado_em:
            self.gerado_em = (
                datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            )


def _semana_ref(outdir: Path) -> str:
    for name in (
        "executive_state_summary.csv",
        "indicadores_emergencia_acoes.csv",
        "indicadores_emergencia.csv",
        "emergencia_confirmacao_detalhe.csv",
    ):
        rows = _read_csv(outdir / name, 5)
        for r in rows:
            y = _cell(r, "epi_year_max", "epi_year_ref", "epi_year", default="")
            w = _cell(
                r,
                "epi_week_max",
                "epi_week_ref",
                "epi_week",
                "semana_epidemiologica",
                default="",
            )
            if y and y != "—" and w and w != "—":
                try:
                    return f"{int(float(y))}-SE{int(float(w)):02d}"
                except ValueError:
                    return f"{y}-SE{w}"
    return "—"


def _leitura_situacional(resumo: dict, rede: dict, n_pressao: int, n_silencio: int) -> str:
    """1 linha: rede estável / sob pressão / dispersão."""
    pct48 = _num(resumo.get("kpi_pct_liberado_48h") or rede.get("pct_liberado_48h_mediano"))
    pressao = _num(resumo.get("kpi_indice_pressao_rede"))
    n_sla = int(_num(resumo.get("n_municipios_sla_crise"), 0) or 0)
    n_alta = int(_num(resumo.get("n_municipios_pressao_alta_critica"), 0) or 0)
    n_div = int(_num(resumo.get("kpi_n_divergencia_gal_notif"), 0) or 0)

    if n_alta >= 15 or (pressao is not None and pressao >= 55) or (
        pct48 is not None and pct48 < 0.4 and n_sla >= 40
    ):
        return "rede sob pressão"
    if n_div >= 50 or n_silencio >= 5 or (
        n_pressao >= 3 and n_div >= 20
    ):
        return "dispersão territorial"
    return "rede estável"


def _top_positivos(outdir: Path, top_n: int = 5) -> tuple[list[dict[str, str]], str]:
    """Top municípios por positivos/positividade (janela recente) + variação vs SE anterior."""
    path = outdir / "integrated_weekly_surveillance.csv"
    rows = _read_csv(path)
    if not rows:
        # fallback: target summary
        tgt = _read_csv(outdir / "integrated_target_municipio_summary.csv")
        agg: dict[str, dict[str, float]] = {}
        for r in tgt:
            mun = _cell(r, "municipio", default="")
            if not mun or mun.startswith("*"):
                continue
            pos = _num(r.get("positivos"), 0) or 0
            tests = _num(r.get("testes"), 0) or 0
            a = agg.setdefault(mun, {"positivos": 0.0, "testes": 0.0})
            a["positivos"] += pos
            a["testes"] += tests
        ranked = sorted(agg.items(), key=lambda x: x[1]["positivos"], reverse=True)[:top_n]
        out = []
        for mun, a in ranked:
            posi = (a["positivos"] / a["testes"]) if a["testes"] else None
            out.append(
                {
                    "municipio": mun,
                    "positivos": _fmt_num(a["positivos"], 0),
                    "positividade": _fmt_pct(posi),
                    "familia": "—",
                    "tipo_sinal": "Observado",
                }
            )
        return out, "variação SE: indisponível (sem série semanal)"

    # Parse weeks with tests > 0
    parsed: list[tuple[int, int, str, float, float, str]] = []
    for r in rows:
        tests = _num(r.get("tests"), 0) or 0
        if tests <= 0:
            continue
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None:
            continue
        mun = _cell(r, "municipio", default="")
        if not mun or mun.startswith("*"):
            continue
        pos = _num(r.get("positives"), 0) or 0
        fam = _cell(r, "familia", "target", default="—")
        parsed.append((int(y), int(w), mun, pos, tests, fam))

    if not parsed:
        return [], "variação SE: sem exames na série"

    weeks = sorted({(y, w) for y, w, *_ in parsed})
    cur_y, cur_w = weeks[-1]
    prev = weeks[-2] if len(weeks) >= 2 else None

    def _agg(year: int, week: int) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for y, w, mun, pos, tests, fam in parsed:
            if y != year or w != week:
                continue
            a = out.setdefault(mun, {"positivos": 0.0, "testes": 0.0})
            a["positivos"] += pos
            a["testes"] += tests
            a["_fam"] = fam  # type: ignore[assignment]
        return out

    # Prefer last 4 SE window for ranking when current SE is sparse
    window = weeks[-4:] if len(weeks) >= 4 else weeks
    win_agg: dict[str, dict[str, Any]] = {}
    for y, w in window:
        for yy, ww, mun, pos, tests, fam in parsed:
            if (yy, ww) != (y, w):
                continue
            a = win_agg.setdefault(mun, {"positivos": 0.0, "testes": 0.0, "familia": fam})
            a["positivos"] += pos
            a["testes"] += tests

    ranked = sorted(win_agg.items(), key=lambda x: x[1]["positivos"], reverse=True)[:top_n]
    out_list: list[dict[str, str]] = []
    for mun, a in ranked:
        posi = (a["positivos"] / a["testes"]) if a["testes"] else None
        out_list.append(
            {
                "municipio": mun,
                "positivos": _fmt_num(a["positivos"], 0),
                "positividade": _fmt_pct(posi),
                "familia": str(a.get("familia") or "—"),
                "tipo_sinal": "Observado",
            }
        )

    # Variação statewide positivos vs SE anterior
    cur_agg = _agg(cur_y, cur_w)
    cur_pos = sum(v["positivos"] for v in cur_agg.values())
    if prev:
        prev_agg = _agg(prev[0], prev[1])
        prev_pos = sum(v["positivos"] for v in prev_agg.values())
        if prev_pos > 0:
            delta = (cur_pos - prev_pos) / prev_pos
            variacao = (
                f"Observado: positivos estaduais SE{cur_w:02d}={_fmt_num(cur_pos, 0)} "
                f"vs SE{prev[1]:02d}={_fmt_num(prev_pos, 0)} ({delta:+.0%})"
            )
        else:
            variacao = (
                f"Observado: positivos SE{cur_w:02d}={_fmt_num(cur_pos, 0)}; "
                f"SE anterior sem base"
            )
    else:
        variacao = f"Observado: positivos SE{cur_w:02d}={_fmt_num(cur_pos, 0)} (sem SE anterior)"

    # Enrich with family aggregates if available
    fam_rows = [
        r
        for r in _read_csv(outdir / "indicadores_rede_por_familia.csv", 20)
        if _cell(r, "granularidade") == "familia"
        or _cell(r, "municipio") in ("ESTADO_MT", "ESTADO", "—", "")
    ]
    if fam_rows and out_list:
        # attach note of top family by exames as context line in familia field when missing
        top_fam = sorted(
            fam_rows, key=lambda r: _num(r.get("exames"), 0) or 0, reverse=True
        )[:3]
        if top_fam and out_list[0].get("familia") in ("—",):
            out_list[0]["familia"] = _cell(top_fam[0], "familia")

    return out_list, variacao


def _count_primeira_deteccao(outdir: Path, se_ref: str) -> int:
    """Municípios com 1ª detecção/alerta na SE de referência (histórico carimbado)."""
    hist = _read_csv(outdir / "alerta_emergencia_historico.csv")
    if not hist:
        # fallback: fila com sinal alerta_*
        fila = _read_csv(outdir / "fila_operacional.csv")
        return sum(
            1
            for r in fila
            if "alerta" in _cell(r, "sinal").lower() or "detec" in _cell(r, "sinal").lower()
        )

    # Parse SE from se_ref like 2026-SE21
    year = week = None
    if "-SE" in se_ref:
        try:
            year_s, week_s = se_ref.split("-SE", 1)
            year, week = int(year_s), int(week_s)
        except ValueError:
            pass

    first_seen: dict[str, tuple[int, int]] = {}
    for r in hist:
        mun = _cell(r, "municipio", default="")
        if not mun:
            continue
        y = _num(r.get("ano_se") or r.get("epi_year"))
        w = _num(r.get("semana_epidemiologica") or r.get("epi_week"))
        if y is None or w is None:
            continue
        key = mun.upper()
        yw = (int(y), int(w))
        if key not in first_seen or yw < first_seen[key]:
            first_seen[key] = yw

    if year is None or week is None:
        return len(first_seen)

    return sum(1 for yw in first_seen.values() if yw == (year, week))


def _top_divergencias(outdir: Path, top_n: int = 5) -> list[dict[str, str]]:
    emerg = _read_csv(outdir / "indicadores_emergencia.csv")
    rows = [r for r in emerg if _truthy(r.get("divergencia_gal_notif"))]
    # Prefer quality gaps as ranking proxy
    qual = {
        _cell(r, "municipio").upper(): r
        for r in _read_csv(outdir / "qualidade_dado_municipal.csv")
    }

    def _rank_key(r: dict) -> tuple:
        mun = _cell(r, "municipio").upper()
        q = qual.get(mun, {})
        gap = 1 if _truthy(q.get("gap_sinan_sem_exame")) else 0
        notif = _num(q.get("notif_sinan"), 0) or 0
        exames = _num(q.get("exames") or r.get("exames"), 0) or 0
        return (-gap, -notif, exames)

    rows = sorted(rows, key=_rank_key)[:top_n]
    out = []
    for r in rows:
        mun = _cell(r, "municipio")
        q = qual.get(mun.upper(), {})
        out.append(
            {
                "municipio": mun,
                "tipo": _cell(r, "tipo_divergencia", default="GAL×SINAN"),
                "notif_sinan": _fmt_num(_num(q.get("notif_sinan")), 0),
                "exames": _fmt_num(_num(q.get("exames") or r.get("exames")), 0),
                "tipo_sinal": "Observado",
            }
        )
    return out


def _bloco_rede(outdir: Path) -> tuple[str, str, str, list[dict], list[dict], dict, dict]:
    resumo_rows = _read_csv(outdir / "indicadores_emergencia_resumo.csv", 1)
    rede_rows = _read_csv(outdir / "indicadores_rede_resumo.csv", 1)
    resumo = resumo_rows[0] if resumo_rows else {}
    rede = rede_rows[0] if rede_rows else {}

    tat_med = _fmt_num(
        _num(rede.get("tat_mediano_estadual") or resumo.get("kpi_tat_mediano")), 1
    )
    tat_p90 = _fmt_num(
        _num(resumo.get("kpi_tat_p90_dias") or rede.get("tat_p90_estadual")), 1
    )
    pct48 = _fmt_pct(
        _num(resumo.get("kpi_pct_liberado_48h") or rede.get("pct_liberado_48h_mediano"))
    )

    emerg = _read_csv(outdir / "indicadores_emergencia.csv")
    pressao_rows = sorted(
        [
            r
            for r in emerg
            if any(
                x in _cell(r, "faixa_pressao").lower()
                for x in ("alta", "critic", "crít")
            )
        ],
        key=lambda r: _num(r.get("indice_pressao_rede"), 0) or 0,
        reverse=True,
    )[:5]
    top_pressao = []
    for r in pressao_rows:
        top_pressao.append(
            {
                "municipio": _cell(r, "municipio"),
                "faixa": _cell(r, "faixa_pressao"),
                "indice": _fmt_num(_num(r.get("indice_pressao_rede")), 1),
                "backlog": _fmt_num(_num(r.get("backlog_estimado")), 0),
                "rejeicao": _fmt_pct(_num(r.get("pct_rejeitado"))),
                "tipo_sinal": "Derivado",
            }
        )

    # Silêncio GAL + vizinho sob pressão
    viz_map: dict[str, list[str]] = {}
    for r in _read_csv(outdir / "municipio_vizinhos.csv"):
        mun = _cell(r, "municipio", default="").upper()
        viz = _cell(r, "vizinho", "municipio_vizinho", "neighbor", default="")
        if mun and viz:
            viz_map.setdefault(mun, []).append(viz)

    pressao_by_mun = {
        _cell(r, "municipio").upper(): r
        for r in emerg
        if _cell(r, "municipio") != "—"
    }

    silencio_rows = [
        r
        for r in emerg
        if _truthy(r.get("silencio_gal_alerta"))
        or _truthy(r.get("silencio_gal_vs_vizinhos"))
    ]
    silencio_out: list[dict[str, str]] = []
    for r in silencio_rows:
        mun = _cell(r, "municipio")
        hot = []
        for v in viz_map.get(mun.upper(), []):
            pr = pressao_by_mun.get(v.upper())
            if not pr:
                continue
            faixa = _cell(pr, "faixa_pressao").lower()
            if any(x in faixa for x in ("alta", "critic", "crít", "moder")):
                hot.append(f"{v}({_cell(pr, 'faixa_pressao')})")
        # Also flag if CSV already marks vs_vizinhos
        flag_viz = _truthy(r.get("silencio_gal_vs_vizinhos"))
        silencio_out.append(
            {
                "municipio": mun,
                "tipo_silencio": _cell(r, "tipo_silencio_gal", default="silêncio GAL"),
                "vizinho_quente": (
                    ", ".join(hot[:3])
                    if hot
                    else ("marcado" if flag_viz else "não identificado")
                ),
                "tipo_sinal": "Observado",
            }
        )
    silencio_out = silencio_out[:5]

    return tat_med, tat_p90, pct48, top_pressao, silencio_out, resumo, rede


def _fila_acoes(outdir: Path, top_n: int = 10) -> list[dict[str, str]]:
    rows = _read_csv(outdir / "fila_operacional.csv", top_n)
    out = []
    for r in rows:
        sinal = _cell(r, "sinal")
        tipo = "Predito" if "predit" in sinal.lower() else (
            "Derivado" if any(x in sinal.lower() for x in ("pressao", "pressão", "sla"))
            else "Observado"
        )
        out.append(
            {
                "municipio": _cell(r, "municipio"),
                "sinal": sinal,
                "banda": _cell(r, "prioridade"),
                "acao": _cell(r, "acao_sugerida"),
                "responsavel": _cell(r, "responsavel"),
                "prazo": _cell(r, "prazo_acao"),
                "tipo_sinal": tipo,
            }
        )
    return out


def _preditos_alta(outdir: Path, top_n: int = 5) -> list[dict[str, str]]:
    risco = _read_csv(outdir / "ml_risco_predito.csv")
    if not risco:
        risco = _read_csv(outdir / "municipios_em_risco.csv")

    # Prefer latest SE present in executive summary / max with data
    se = _semana_ref(outdir)
    year = week = None
    if "-SE" in se:
        try:
            ys, ws = se.split("-SE", 1)
            year, week = int(ys), int(ws)
        except ValueError:
            pass

    filtered = []
    for r in risco:
        banda = _cell(r, "banda_risco", "faixa_predita", "nivel_risco", "risco")
        if not any(x in banda.lower() for x in ("alta", "alto", "critic", "crít")):
            continue
        if year is not None and week is not None:
            y = _num(r.get("epi_year"))
            w = _num(r.get("epi_week"))
            if y is not None and w is not None and (int(y), int(w)) != (year, week):
                # keep if no SE match at all later
                r = dict(r)
                r["_se_match"] = 0
            else:
                r = dict(r)
                r["_se_match"] = 1
        else:
            r = dict(r)
            r["_se_match"] = 0
        filtered.append(r)

    if any(r.get("_se_match") == 1 for r in filtered):
        filtered = [r for r in filtered if r.get("_se_match") == 1]
    else:
        # fallback: highest prob among Alta/Crítica
        pass

    filtered = sorted(
        filtered,
        key=lambda r: _num(
            r.get("prob_alerta_proxima_janela")
            or r.get("prob")
            or r.get("risco_composto")
            or r.get("score"),
            0,
        )
        or 0,
        reverse=True,
    )

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in filtered:
        mun = _cell(r, "municipio")
        fam = _cell(r, "familia", "target", "agravo_alvo")
        key = f"{mun}|{fam}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "municipio": mun,
                "banda": _cell(r, "banda_risco", "faixa_predita", "nivel_risco"),
                "familia": fam,
                "driver": _short_driver(_cell(r, "drivers", "driver", "motivo")),
                "prob": _fmt_pct(
                    _num(r.get("prob_alerta_proxima_janela") or r.get("prob")), 0
                ),
                "tipo_sinal": "Predito",
            }
        )
        if len(out) >= top_n:
            break
    return out


def _qualidade(outdir: Path) -> tuple[str, str]:
    qual = _read_csv(outdir / "qualidade_dado_municipal.csv")
    rede = _read_csv(outdir / "indicadores_rede_resumo.csv", 1)
    n_qual = len([r for r in qual if not _cell(r, "municipio").startswith("*")])
    n_rede = int(_num(rede[0].get("n_municipios"), 0) or 0) if rede else 0
    faixas: dict[str, int] = {}
    for r in qual:
        if _cell(r, "municipio").startswith("*"):
            continue
        f = _cell(r, "faixa_confianca", default="n/d")
        faixas[f] = faixas.get(f, 0) + 1
    faixa_txt = ", ".join(f"{k}={v}" for k, v in sorted(faixas.items(), key=lambda x: -x[1]))
    cobertura = (
        f"Observado: {n_qual} mun. com qualidade "
        f"(rede GAL={n_rede or '—'}); faixas: {faixa_txt or '—'}"
    )

    conf_rows = _read_csv(outdir / "emergencia_confirmacao_resumo.csv", 1)
    if conf_rows:
        c = conf_rows[0]
        taxa = _fmt_pct(_num(c.get("taxa_confirmacao_geral")))
        n_ok = _fmt_num(_num(c.get("n_confirmados")), 0)
        n_av = _fmt_num(_num(c.get("n_alertas_avaliados")), 0)
        tipo = _cell(c, "tipo_sinal", default="Observado")
        confirmacao = (
            f"{tipo}: confirmação alertas rodada anterior = {taxa} "
            f"({n_ok}/{n_av}); modo={_cell(c, 'modo_confirmacao')}"
        )
    else:
        confirmacao = "Confirmação: artefato emergencia_confirmacao_* ausente"

    return cobertura, confirmacao


def montar_relatorio(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    top_fila: int = 10,
    top_predito: int = 5,
) -> RelatorioCIEVS:
    outdir = Path(outdir)
    fontes = []
    for name in (
        "fila_operacional.csv",
        "indicadores_emergencia.csv",
        "indicadores_emergencia_resumo.csv",
        "indicadores_rede_resumo.csv",
        "ml_risco_predito.csv",
        "qualidade_dado_municipal.csv",
        "emergencia_confirmacao_resumo.csv",
        "integrated_weekly_surveillance.csv",
        "executive_state_summary.csv",
    ):
        if (outdir / name).is_file():
            fontes.append(name)

    se = _semana_ref(outdir)
    top_pos, variacao = _top_positivos(outdir, top_n=5)
    n_1a = _count_primeira_deteccao(outdir, se)
    diverg = _top_divergencias(outdir, top_n=5)
    tat_med, tat_p90, pct48, top_pressao, silencio, resumo, rede = _bloco_rede(outdir)
    leitura = _leitura_situacional(resumo, rede, len(top_pressao), len(silencio))
    fila = _fila_acoes(outdir, top_n=top_fila)
    preditos = _preditos_alta(outdir, top_n=top_predito)
    cobertura, confirmacao = _qualidade(outdir)

    return RelatorioCIEVS(
        semana_epidemiologica=se,
        leitura_situacional=leitura,
        top_positivos=top_pos,
        variacao_se=variacao,
        n_primeira_deteccao_alerta=n_1a,
        top_divergencias=diverg,
        tat_mediano=tat_med,
        tat_p90=tat_p90,
        pct_48h=pct48,
        top_pressao=top_pressao,
        silencio_vizinho_quente=silencio,
        fila_acoes=fila,
        preditos_alta=preditos,
        cobertura_municipios=cobertura,
        confirmacao_alertas=confirmacao,
        fontes_presentes=fontes,
    )


def _cabecalho(rel: RelatorioCIEVS) -> str:
    return f"{' / '.join(rel.orgaos)} — Relatório 2×/semana"


def to_telegram_markdown(rel: RelatorioCIEVS, *, max_chars: int = 3900) -> str:
    """HTML curto para Telegram (parse_mode=HTML). Top ~5 ações."""
    lines: list[str] = [
        f"<b>{html.escape(_cabecalho(rel))}</b>",
        f"SE {html.escape(rel.semana_epidemiologica)} · {html.escape(rel.gerado_em)}",
        f"Leitura: <b>{html.escape(rel.leitura_situacional)}</b>",
        "",
        "<b>A — Lab-epi</b> [Observado]",
    ]
    if rel.top_positivos:
        tops = "; ".join(
            f"{x['municipio']} (+{x['positivos']}, {x['positividade']})"
            for x in rel.top_positivos[:3]
        )
        lines.append(html.escape(f"Top positivos: {tops}"))
    lines.append(html.escape(rel.variacao_se[:180]))
    lines.append(
        html.escape(
            f"1ª detecção/alerta: {rel.n_primeira_deteccao_alerta} mun. · "
            f"Diverg. GAL×SINAN top: "
            + ", ".join(d["municipio"] for d in rel.top_divergencias[:3])
        )
    )
    lines.extend(
        [
            "",
            "<b>B — Rede</b> [Derivado]",
            html.escape(
                f"TAT med={rel.tat_mediano}d · p90={rel.tat_p90}d · %≤48h={rel.pct_48h}"
            ),
        ]
    )
    if rel.top_pressao:
        lines.append(
            html.escape(
                "Pressão: "
                + "; ".join(
                    f"{x['municipio']}({x['faixa']}/{x['indice']})"
                    for x in rel.top_pressao[:3]
                )
            )
        )
    if rel.silencio_vizinho_quente:
        lines.append(
            html.escape(
                "Silêncio GAL: "
                + "; ".join(
                    f"{x['municipio']}→{x['vizinho_quente']}"
                    for x in rel.silencio_vizinho_quente[:2]
                )
            )
        )
    lines.extend(["", "<b>C — Ações</b> (top 5)"])
    for i, a in enumerate(rel.fila_acoes[:5], 1):
        lines.append(
            f"<b>{i}. {html.escape(a['municipio'])}</b> "
            f"[{html.escape(a['tipo_sinal'])}] "
            f"{html.escape(a['sinal'])}/{html.escape(a['banda'])}"
        )
        lines.append(
            html.escape(
                f"→ {a['acao'][:100]} · {a['responsavel'][:40]} · {a['prazo']}"
            )
        )
    if rel.preditos_alta:
        lines.append("<b>Predito Alta/Crítica</b>")
        for p in rel.preditos_alta[:3]:
            lines.append(
                html.escape(
                    f"• {p['municipio']} [{p['banda']}] {p['familia']}: {p['driver'][:80]}"
                )
            )
    lines.extend(
        [
            "",
            "<b>D — Qualidade</b>",
            html.escape(rel.cobertura_municipios[:160]),
            html.escape(rel.confirmacao_alertas[:160]),
            f'<a href="{html.escape(rel.dashboard_url)}">Dashboard LACEN</a>',
        ]
    )
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…(truncado)"
    return text


def to_email_subject(rel: RelatorioCIEVS) -> str:
    return (
        f"[CIEVS Relatório 2×/semana] {rel.semana_epidemiologica} — "
        f"{rel.leitura_situacional} — LACEN-MT · {rel.gerado_em}"
    )


def to_email_plain(rel: RelatorioCIEVS) -> str:
    lines: list[str] = [
        _cabecalho(rel),
        f"SE de referência: {rel.semana_epidemiologica}",
        f"Gerado em: {rel.gerado_em}",
        f"Leitura situacional: {rel.leitura_situacional}",
        rel.nota,
        "",
        "=" * 64,
        "BLOCO A — Situação lab-epi [Observado / Derivado]",
        "-" * 64,
        rel.variacao_se,
        f"Municípios 1ª detecção/alerta (SE ref.): {rel.n_primeira_deteccao_alerta}",
        "",
        "Top municípios (positivos / positividade):",
    ]
    for i, x in enumerate(rel.top_positivos, 1):
        lines.append(
            f"  {i}. {x['municipio']} — +{x['positivos']} · "
            f"pos={x['positividade']} · fam={x['familia']} [{x['tipo_sinal']}]"
        )
    lines.append("")
    lines.append("Top divergências GAL×SINAN:")
    for i, d in enumerate(rel.top_divergencias, 1):
        lines.append(
            f"  {i}. {d['municipio']} — {d['tipo']} · "
            f"notif={d['notif_sinan']} · exames={d['exames']} [{d['tipo_sinal']}]"
        )

    lines.extend(
        [
            "",
            "=" * 64,
            "BLOCO B — Rede [Derivado / Observado]",
            "-" * 64,
            f"TAT mediano estadual: {rel.tat_mediano} d",
            f"TAT p90 estadual: {rel.tat_p90} d",
            f"% liberado ≤48h: {rel.pct_48h}",
            "",
            "Top pressão / backlog / rejeição:",
        ]
    )
    for i, p in enumerate(rel.top_pressao, 1):
        lines.append(
            f"  {i}. {p['municipio']} — {p['faixa']} · índice={p['indice']} · "
            f"backlog={p['backlog']} · rejeição={p['rejeicao']} [{p['tipo_sinal']}]"
        )
    lines.append("")
    lines.append("Silêncio GAL (vizinho quente):")
    if rel.silencio_vizinho_quente:
        for i, s in enumerate(rel.silencio_vizinho_quente, 1):
            lines.append(
                f"  {i}. {s['municipio']} — {s['tipo_silencio']} · "
                f"vizinho={s['vizinho_quente']} [{s['tipo_sinal']}]"
            )
    else:
        lines.append("  (nenhum silêncio GAL com vizinho quente na rodada)")

    lines.extend(
        [
            "",
            "=" * 64,
            "BLOCO C — Ações [Observado / Derivado / Predito]",
            "-" * 64,
            "Fila operacional (top 10):",
        ]
    )
    for i, a in enumerate(rel.fila_acoes[:10], 1):
        lines.append(
            f"  {i}. {a['municipio']} | {a['sinal']} | {a['banda']} | "
            f"{a['acao'][:140]} | {a['responsavel']} | {a['prazo']} [{a['tipo_sinal']}]"
        )
    lines.append("")
    lines.append("Predito Alta/Crítica (até 5):")
    for i, p in enumerate(rel.preditos_alta, 1):
        lines.append(
            f"  {i}. {p['municipio']} | {p['banda']} | {p['familia']} | "
            f"driver={p['driver']} | prob={p['prob']} [{p['tipo_sinal']}]"
        )

    lines.extend(
        [
            "",
            "=" * 64,
            "BLOCO D — Qualidade",
            "-" * 64,
            rel.cobertura_municipios,
            rel.confirmacao_alertas,
            f"Dashboard: {rel.dashboard_url}",
            "",
            f"Fontes: {', '.join(rel.fontes_presentes) or '—'}",
            "Modelo: lacen_relatorio_cievs.py",
        ]
    )
    return "\n".join(lines)


def to_email_html(rel: RelatorioCIEVS) -> str:
    def _li_pos() -> str:
        if not rel.top_positivos:
            return "<li>(sem dados)</li>"
        return "".join(
            "<li>"
            f"<b>{html.escape(x['municipio'])}</b> — +{html.escape(x['positivos'])} · "
            f"{html.escape(x['positividade'])} · {html.escape(x['familia'])} "
            f"<small>[{html.escape(x['tipo_sinal'])}]</small></li>"
            for x in rel.top_positivos
        )

    def _li_div() -> str:
        if not rel.top_divergencias:
            return "<li>(nenhuma)</li>"
        return "".join(
            "<li>"
            f"<b>{html.escape(d['municipio'])}</b> — {html.escape(d['tipo'])} · "
            f"notif={html.escape(d['notif_sinan'])} · exames={html.escape(d['exames'])} "
            f"<small>[{html.escape(d['tipo_sinal'])}]</small></li>"
            for d in rel.top_divergencias
        )

    fila_rows = []
    for a in rel.fila_acoes[:10]:
        fila_rows.append(
            "<tr>"
            f"<td>{html.escape(a['municipio'])}</td>"
            f"<td>{html.escape(a['sinal'])}<br><small>{html.escape(a['tipo_sinal'])}</small></td>"
            f"<td><b>{html.escape(a['banda'])}</b></td>"
            f"<td>{html.escape(a['acao'][:160])}</td>"
            f"<td>{html.escape(a['responsavel'])}</td>"
            f"<td>{html.escape(a['prazo'])}</td>"
            "</tr>"
        )

    pred_rows = []
    for p in rel.preditos_alta:
        pred_rows.append(
            "<tr>"
            f"<td>{html.escape(p['municipio'])}</td>"
            f"<td>{html.escape(p['banda'])}</td>"
            f"<td>{html.escape(p['familia'])}</td>"
            f"<td>{html.escape(p['driver'])}</td>"
            f"<td>{html.escape(p['prob'])}</td>"
            "</tr>"
        )

    press_li = "".join(
        "<li>"
        f"<b>{html.escape(p['municipio'])}</b> — {html.escape(p['faixa'])} · "
        f"índice={html.escape(p['indice'])} · backlog={html.escape(p['backlog'])} · "
        f"rejeição={html.escape(p['rejeicao'])}</li>"
        for p in rel.top_pressao
    ) or "<li>(nenhum)</li>"

    sil_li = "".join(
        "<li>"
        f"<b>{html.escape(s['municipio'])}</b> — {html.escape(s['tipo_silencio'])} · "
        f"vizinho={html.escape(s['vizinho_quente'])}</li>"
        for s in rel.silencio_vizinho_quente
    ) or "<li>(nenhum silêncio GAL com vizinho quente)</li>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{html.escape(_cabecalho(rel))}</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;color:#1a1a1a;line-height:1.4">
<h2 style="color:#1B3281">{html.escape(_cabecalho(rel))}</h2>
<p>SE de referência: <b>{html.escape(rel.semana_epidemiologica)}</b><br>
Gerado em: {html.escape(rel.gerado_em)}<br>
Leitura situacional: <b>{html.escape(rel.leitura_situacional)}</b></p>
<p><em>{html.escape(rel.nota)}</em></p>

<h3>A — Situação lab-epi</h3>
<p>{html.escape(rel.variacao_se)}</p>
<p>1ª detecção/alerta: <b>{rel.n_primeira_deteccao_alerta}</b> municípios</p>
<p><b>Top positivos</b></p><ul>{_li_pos()}</ul>
<p><b>Top divergências GAL×SINAN</b></p><ul>{_li_div()}</ul>

<h3>B — Rede</h3>
<p>TAT mediano: <b>{html.escape(rel.tat_mediano)} d</b> ·
p90: <b>{html.escape(rel.tat_p90)} d</b> ·
%≤48h: <b>{html.escape(rel.pct_48h)}</b></p>
<p><b>Pressão / backlog / rejeição</b></p><ul>{press_li}</ul>
<p><b>Silêncio GAL × vizinho quente</b></p><ul>{sil_li}</ul>

<h3>C — Ações</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;width:100%">
<thead style="background:#e8eef5">
<tr><th>Município</th><th>Sinal</th><th>Banda</th><th>Ação</th><th>Responsável</th><th>Prazo</th></tr>
</thead>
<tbody>
{"".join(fila_rows) if fila_rows else "<tr><td colspan='6'>(fila vazia)</td></tr>"}
</tbody></table>
<p><b>Predito Alta/Crítica</b></p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">
<thead style="background:#f5e8e8">
<tr><th>Município</th><th>Banda</th><th>Família</th><th>Driver</th><th>Prob</th></tr>
</thead>
<tbody>
{"".join(pred_rows) if pred_rows else "<tr><td colspan='5'>(nenhum)</td></tr>"}
</tbody></table>

<h3>D — Qualidade</h3>
<p>{html.escape(rel.cobertura_municipios)}</p>
<p>{html.escape(rel.confirmacao_alertas)}</p>
<p>Dashboard: <a href="{html.escape(rel.dashboard_url)}">{html.escape(rel.dashboard_url)}</a></p>
</body></html>"""


def format_email(rel: RelatorioCIEVS) -> tuple[str, str, str]:
    """Retorna (assunto, corpo_texto, corpo_html)."""
    return to_email_subject(rel), to_email_plain(rel), to_email_html(rel)


if __name__ == "__main__":
    rel = montar_relatorio(OUTDIR_DEFAULT)
    subj, plain, _ = format_email(rel)
    print(subj)
    print("-" * 60)
    print(plain)
    print("-" * 60)
    print(to_telegram_markdown(rel))
