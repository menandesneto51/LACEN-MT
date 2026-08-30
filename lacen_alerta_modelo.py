#!/usr/bin/env python3
"""
LACEN-MT / CIEVS / Vigidesastres — modelo institucional de alerta.

Gera payload padronizado (TESTE | OPERACIONAL | EMERGÊNCIA) a partir de
`saida_pipeline`, com formatação para Telegram (HTML) e e-mail (assunto +
texto/HTML).

Uso típico:
  from lacen_alerta_modelo import montar_alerta_from_outdir, format_telegram, format_email
"""
from __future__ import annotations

import csv
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Sequence

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"

DASHBOARD_URL = (
    "https://menandesneto51-lacen-mt-lacen-dashboard-integrado-total-nrdgik.streamlit.app/"
)

TipoAlerta = Literal["TESTE", "OPERACIONAL", "EMERGENCIA"]
TipoSinal = Literal["Observado", "Derivado", "Predito", "—"]

SEVERIDADE_ORDEM = ("Baixo", "Moderado", "Alto", "Muito alto", "Crítico")


@dataclass
class ItemAlerta:
    municipio: str
    codigo_ibge: str = "—"
    crs: str = "—"
    tipo_sinal: TipoSinal = "—"
    severidade: str = "—"
    motivo: str = "—"
    fonte: str = "—"  # fila | emergencia | risco | silencio
    tat_p90: str = "—"
    pct_48h: str = "—"
    pressao: str = "—"
    indice_pressao: str = "—"
    prob_ml: str = "—"
    acao_sugerida: str = "—"
    responsavel: str = "—"
    prazo: str = "—"
    agravo_alvo: str = "—"


@dataclass
class AlertaInstitucional:
    tipo: TipoAlerta = "TESTE"
    orgaos: Sequence[str] = ("LACEN-MT", "CIEVS", "Vigidesastres")
    gerado_em: str = ""
    semana_epidemiologica: str = "—"
    dashboard_url: str = DASHBOARD_URL
    itens: list[ItemAlerta] = field(default_factory=list)
    nota: str = ""

    def __post_init__(self) -> None:
        if not self.gerado_em:
            self.gerado_em = (
                datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            )


def _cell(row: dict, *keys: str, default: str = "—") -> str:
    for k in keys:
        if k in row and str(row.get(k) or "").strip():
            return str(row[k]).strip()
    return default


def _read_csv(path: Path, limit: int = 50) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))[:limit]


def _ibge_map(outdir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in ("municipal_master.csv", "municipios_silenciosos.csv"):
        for row in _read_csv(outdir / name, limit=2000):
            mun = _cell(row, "municipio", default="")
            ibge = _cell(row, "codigo_ibge", default="")
            if mun and mun != "—" and ibge and ibge != "—":
                mapping[mun.strip().upper()] = ibge
    return mapping


def _norm_severidade(*candidates: str) -> str:
    raw = " ".join(c for c in candidates if c and c != "—").strip().lower()
    if not raw:
        return "—"
    if any(x in raw for x in ("critic", "crise", "emerg")):
        return "Crítico"
    if any(x in raw for x in ("muito alto", "muito_alto", "alta prior", "p1")):
        return "Muito alto"
    if any(x in raw for x in ("alto", "alta", "p2", "pressao_alta", "pressão alta")):
        return "Alto"
    if any(x in raw for x in ("moder", "medio", "médio", "p3")):
        return "Moderado"
    if any(x in raw for x in ("baixo", "baixa", "p4", "verde")):
        return "Baixo"
    # fallback: use first non-empty candidate capitalized
    for c in candidates:
        if c and c != "—":
            return c[:40]
    return "—"


def _infer_tipo_sinal(row: dict, default: TipoSinal = "Observado") -> TipoSinal:
    blob = " ".join(
        str(row.get(k) or "")
        for k in (
            "tipo_sinal",
            "tipo_sinal_pressao",
            "tipo_sinal_pressao_predita",
            "tipo_sinal_sla",
            "sinal",
            "motivo",
        )
    ).lower()
    if "predit" in blob or "forecast" in blob or "ml" in blob:
        return "Predito"
    if "deriv" in blob or "indicador" in blob or "pressao" in blob or "pressão" in blob:
        return "Derivado"
    if "observ" in blob or "gal" in blob or "sinan" in blob:
        return "Observado"
    return default


def _se_from_emerg(rows: Iterable[dict]) -> str:
    for r in rows:
        y = _cell(r, "epi_year_ref", "epi_year", default="")
        w = _cell(r, "epi_week_ref", "epi_week", "semana_epidemiologica", default="")
        if y != "—" and y and w and w != "—":
            return f"{y}-SE{str(w).zfill(2)}"
    return "—"


def carregar_top_alertas(outdir: Path, top_n: int = 3) -> list[ItemAlerta]:
    """Une fila operacional + emergência + risco/silêncio (top N por fonte)."""
    outdir = Path(outdir)
    ibge = _ibge_map(outdir)
    itens: list[ItemAlerta] = []
    seen: set[str] = set()

    def _add(item: ItemAlerta) -> None:
        key = f"{item.municipio}|{item.fonte}|{item.motivo[:40]}"
        if key in seen:
            return
        seen.add(key)
        if item.codigo_ibge == "—" and item.municipio:
            item.codigo_ibge = ibge.get(item.municipio.strip().upper(), "—")
        itens.append(item)

    fila = _read_csv(outdir / "fila_operacional.csv", top_n)
    for r in fila:
        _add(
            ItemAlerta(
                municipio=_cell(r, "municipio"),
                tipo_sinal=_infer_tipo_sinal(r, "Observado"),
                severidade=_norm_severidade(_cell(r, "prioridade", "sinal")),
                motivo=_cell(r, "motivo", "sinal"),
                fonte="fila",
                acao_sugerida=_cell(r, "acao_sugerida"),
                responsavel=_cell(r, "responsavel"),
                prazo=_cell(r, "prazo_acao"),
                agravo_alvo=_cell(r, "agravo_alvo"),
                pressao=_cell(r, "prioridade", "sinal"),
            )
        )

    emerg = _read_csv(outdir / "indicadores_emergencia_acoes.csv", top_n)
    if not emerg:
        emerg = _read_csv(outdir / "indicadores_emergencia.csv", top_n)
    for r in emerg:
        motivo_parts = []
        for k, label in (
            ("silencio_gal_alerta", "silêncio GAL"),
            ("divergencia_gal_notif", "divergência GAL/notif"),
            ("faixa_pressao", "pressão"),
            ("prioridade_emergencia", "emergência"),
        ):
            v = _cell(r, k, default="")
            if v and v not in ("—", "0", "False", "false", "nao", "não"):
                motivo_parts.append(f"{label}={v}")
        _add(
            ItemAlerta(
                municipio=_cell(r, "municipio"),
                codigo_ibge=_cell(r, "codigo_ibge"),
                tipo_sinal=_infer_tipo_sinal(r, "Derivado"),
                severidade=_norm_severidade(
                    _cell(r, "prioridade_emergencia"),
                    _cell(r, "faixa_pressao"),
                    _cell(r, "faixa_pressao_predita"),
                    _cell(r, "sla_crise"),
                ),
                motivo="; ".join(motivo_parts) if motivo_parts else _cell(r, "sinal", "motivo"),
                fonte="emergencia",
                tat_p90=_cell(r, "tat_p90_dias"),
                pct_48h=_cell(r, "pct_liberado_48h"),
                pressao=_cell(r, "faixa_pressao", "faixa_pressao_predita"),
                indice_pressao=_cell(r, "indice_pressao_rede", "indice_pressao"),
                prob_ml=_cell(r, "prob_pressao_alta_proxima_janela"),
                acao_sugerida=_cell(r, "acao_sugerida", "acao_pressao_predita"),
                responsavel=_cell(r, "responsavel"),
                prazo=_cell(r, "prazo_acao", "sla_crise"),
            )
        )

    risco = _read_csv(outdir / "municipios_em_risco.csv", top_n)
    if not risco:
        risco = _read_csv(outdir / "ml_risco_predito.csv", top_n)
    for r in risco:
        _add(
            ItemAlerta(
                municipio=_cell(r, "municipio"),
                codigo_ibge=_cell(r, "codigo_ibge"),
                tipo_sinal=_infer_tipo_sinal(r, "Predito"),
                severidade=_norm_severidade(
                    _cell(r, "banda_risco", "nivel_risco", "risco", "prioridade")
                ),
                motivo=_cell(r, "motivo", "driver", "drivers", "sinal"),
                fonte="risco",
                prob_ml=_cell(r, "prob", "probabilidade", "score_risco", "score"),
                acao_sugerida=_cell(r, "acao_sugerida"),
                responsavel=_cell(r, "responsavel"),
                prazo=_cell(r, "prazo_acao"),
                agravo_alvo=_cell(r, "agravo_alvo", "target"),
            )
        )

    return itens[: max(top_n * 3, top_n)]


def montar_alerta_from_outdir(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    tipo: TipoAlerta = "TESTE",
    top_n: int = 3,
    nota: str = "",
) -> AlertaInstitucional:
    outdir = Path(outdir)
    emerg = _read_csv(outdir / "indicadores_emergencia_acoes.csv", 5)
    if not emerg:
        emerg = _read_csv(outdir / "indicadores_emergencia.csv", 5)
    itens = carregar_top_alertas(outdir, top_n=top_n)
    if not nota and tipo == "TESTE":
        nota = "Mensagem de TESTE — não constitui alerta operacional oficial."
    return AlertaInstitucional(
        tipo=tipo,
        semana_epidemiologica=_se_from_emerg(emerg),
        itens=itens,
        nota=nota,
    )


def _cabecalho(alerta: AlertaInstitucional) -> str:
    orgs = " / ".join(alerta.orgaos)
    return f"{orgs} — ALERTA [{alerta.tipo}]"


def format_telegram(alerta: AlertaInstitucional, *, max_chars: int = 3900) -> str:
    """HTML curto para Telegram parse_mode=HTML."""
    lines: list[str] = [
        f"<b>{html.escape(_cabecalho(alerta))}</b>",
        f"<i>{html.escape(alerta.gerado_em)}</i> · SE {html.escape(alerta.semana_epidemiologica)}",
    ]
    if alerta.nota:
        lines.append(f"⚠️ {html.escape(alerta.nota)}")
    lines.append("")

    for i, it in enumerate(alerta.itens, 1):
        lines.append(
            f"<b>{i}. {html.escape(it.municipio)}</b> "
            f"(IBGE {html.escape(it.codigo_ibge)}"
            + (f" · CRS {html.escape(it.crs)}" if it.crs != "—" else "")
            + ")"
        )
        lines.append(
            f"Sinal: {html.escape(it.tipo_sinal)} · "
            f"Severidade: <b>{html.escape(it.severidade)}</b> · "
            f"Fonte: {html.escape(it.fonte)}"
        )
        lines.append(f"Motivo: {html.escape(it.motivo[:200])}")
        ind = []
        if it.tat_p90 != "—":
            ind.append(f"TAT p90={it.tat_p90}d")
        if it.pct_48h != "—":
            ind.append(f"%≤48h={it.pct_48h}")
        if it.pressao != "—":
            ind.append(f"pressão={it.pressao}")
        if it.indice_pressao != "—":
            ind.append(f"índice={it.indice_pressao}")
        if it.prob_ml != "—":
            ind.append(f"prob ML={it.prob_ml}")
        if ind:
            lines.append("Indicadores: " + html.escape(" | ".join(ind)))
        lines.append(
            f"Ação: {html.escape(it.acao_sugerida[:160])} · "
            f"Resp: {html.escape(it.responsavel)} · "
            f"Prazo: {html.escape(it.prazo)}"
        )
        lines.append("")

    lines.append(f'Painel: <a href="{html.escape(alerta.dashboard_url)}">dashboard LACEN</a>')
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…(truncado)"
    return text


def format_email_subject(alerta: AlertaInstitucional) -> str:
    n = len(alerta.itens)
    mun = alerta.itens[0].municipio if alerta.itens else "sem itens"
    return (
        f"[{alerta.tipo} LACEN-MT/CIEVS] {n} sinal(is) — "
        f"{mun}… — {alerta.semana_epidemiologica} — {alerta.gerado_em}"
    )


def format_email_plain(alerta: AlertaInstitucional) -> str:
    lines: list[str] = [
        _cabecalho(alerta),
        f"Gerado em: {alerta.gerado_em}",
        f"Semana epidemiológica: {alerta.semana_epidemiologica}",
    ]
    if alerta.nota:
        lines.append(f"Nota: {alerta.nota}")
    lines.append("")
    lines.append("=" * 60)

    for i, it in enumerate(alerta.itens, 1):
        lines.extend(
            [
                "",
                f"{i}. Município: {it.municipio}",
                f"   IBGE: {it.codigo_ibge}"
                + (f" | CRS: {it.crs}" if it.crs != "—" else ""),
                f"   Tipo de sinal: {it.tipo_sinal}",
                f"   Severidade/banda: {it.severidade}",
                f"   Motivo ({it.fonte}): {it.motivo}",
                f"   Indicadores: TAT p90={it.tat_p90} | %≤48h={it.pct_48h} | "
                f"pressão={it.pressao} (índice={it.indice_pressao}) | prob ML={it.prob_ml}",
                f"   Agravo/alvo: {it.agravo_alvo}",
                f"   Ação sugerida: {it.acao_sugerida}",
                f"   Responsável: {it.responsavel}",
                f"   Prazo: {it.prazo}",
            ]
        )

    lines.extend(
        [
            "",
            "=" * 60,
            f"Dashboard: {alerta.dashboard_url}",
            "Modelo: lacen_alerta_modelo.py",
        ]
    )
    return "\n".join(lines)


def format_email_html(alerta: AlertaInstitucional) -> str:
    rows = []
    for it in alerta.itens:
        rows.append(
            "<tr>"
            f"<td>{html.escape(it.municipio)}<br><small>IBGE {html.escape(it.codigo_ibge)}</small></td>"
            f"<td>{html.escape(it.tipo_sinal)}</td>"
            f"<td><b>{html.escape(it.severidade)}</b></td>"
            f"<td>{html.escape(it.motivo[:180])}</td>"
            f"<td>TAT p90={html.escape(it.tat_p90)}<br>%≤48h={html.escape(it.pct_48h)}"
            f"<br>pressão={html.escape(it.pressao)} · ML={html.escape(it.prob_ml)}</td>"
            f"<td>{html.escape(it.acao_sugerida[:120])}<br>"
            f"<small>{html.escape(it.responsavel)} · {html.escape(it.prazo)}</small></td>"
            "</tr>"
        )
    nota_html = (
        f"<p><em>{html.escape(alerta.nota)}</em></p>" if alerta.nota else ""
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{html.escape(_cabecalho(alerta))}</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;color:#1a1a1a">
<h2>{html.escape(_cabecalho(alerta))}</h2>
<p>Gerado em: {html.escape(alerta.gerado_em)} · SE {html.escape(alerta.semana_epidemiologica)}</p>
{nota_html}
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">
<thead style="background:#e8eef5">
<tr>
<th>Município</th><th>Sinal</th><th>Severidade</th>
<th>Motivo</th><th>Indicadores</th><th>Ação / Resp / Prazo</th>
</tr></thead>
<tbody>
{"".join(rows) if rows else "<tr><td colspan='6'>(sem itens)</td></tr>"}
</tbody></table>
<p>Dashboard: <a href="{html.escape(alerta.dashboard_url)}">{html.escape(alerta.dashboard_url)}</a></p>
</body></html>"""


def format_email(alerta: AlertaInstitucional) -> tuple[str, str, str]:
    """Retorna (assunto, corpo_texto, corpo_html)."""
    return (
        format_email_subject(alerta),
        format_email_plain(alerta),
        format_email_html(alerta),
    )


def strip_html_to_plain(text: str) -> str:
    """Utilitário leve para dry-run quando só há HTML."""
    t = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    t = re.sub(r"</p>|</div>|</tr>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


if __name__ == "__main__":
    alerta = montar_alerta_from_outdir(OUTDIR_DEFAULT, tipo="TESTE", top_n=3)
    subj, plain, _html = format_email(alerta)
    print(subj)
    print("-" * 60)
    print(plain)
    print("-" * 60)
    print(format_telegram(alerta))
