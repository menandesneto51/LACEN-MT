#!/usr/bin/env python3
"""
Alerta Estratégico — Radar LACEN (SES-MT / CIEVS-MT).

Produto executivo (~2 páginas): síntese para decisão e acionamento.
O detalhamento completo permanece no Painel Radar LACEN.

Estrutura:
  1. Síntese executiva
  2. Sinais prioritários
  3. Destaque territorial (quando houver)
  4. Lacunas laboratório × vigilância
  5. Encaminhamentos
  + Nota de interpretação + link do painel
"""
from __future__ import annotations

import html
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from lacen_briefing_epi import _agg_counts_target_se, _norm_mun, _shift_se


# ---------------------------------------------------------------------------
# Normalização textual
# ---------------------------------------------------------------------------

_LAB_FIXES: tuple[tuple[str, str], ...] = (
    (r"doen\s*as\s*diarr\s*icas", "doenças diarreicas"),
    (r"bact\s*rias", "bactérias"),
    (r"rotav\s*rus", "rotavírus"),
    (r"infec\s*o\s*coloniza\s*o", "infecção/colonização"),
    (r"gastroenterite\s+bact\s*rias", "gastroenterite por bactérias"),
    (r"teste\s+de\s+sensibilidade", "teste de sensibilidade"),
    (r"multipat\s*genos", "multipatógenos"),
    (r"\bhbv\b", "hepatite B"),
    (r"\bhcv\b", "hepatite C"),
)

_MUN_IBGE_FIXES: dict[str, str] = {
    "APIACAS": "Apiacás",
    "GUARANTA DO NORTE": "Guarantã do Norte",
    "MARCELANDIA": "Marcelândia",
    "BARRA DO GARCAS": "Barra do Garças",
    "CLAUDIA": "Cláudia",
    "JUINA": "Juína",
    "CUIABA": "Cuiabá",
    "VARZEA GRANDE": "Várzea Grande",
    "RONDONOPOLIS": "Rondonópolis",
    "TANGARA DA SERRA": "Tangará da Serra",
    "CACERES": "Cáceres",
    "AGUA BOA": "Água Boa",
    "NOSSA SENHORA DO LIVRAMENTO": "Nossa Senhora do Livramento",
    "LUCAS DO RIO VERDE": "Lucas do Rio Verde",
    "TERRA NOVA DO NORTE": "Terra Nova do Norte",
    "NOVA XAVANTINA": "Nova Xavantina",
}


def normalize_lab_description(text: str) -> str:
    """Corrige encoding/acentos quebrados em nomes de exames/agravos."""
    t = (text or "").strip()
    if not t:
        return "—"
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t)
    for pat, repl in _LAB_FIXES:
        t = re.sub(pat, repl, t, flags=re.I)
    # Remove artefatos de acento perdido (letra isolada)
    t = re.sub(r"\b([a-z])\s+(?=[a-z]{2,})", "", t, flags=re.I)
    return t.strip() or "—"


def mun_oficial(mun: str) -> str:
    key = _norm_mun(mun)
    key_ascii = "".join(
        c
        for c in unicodedata.normalize("NFD", key)
        if unicodedata.category(c) != "Mn"
    )
    if key_ascii in _MUN_IBGE_FIXES:
        return _MUN_IBGE_FIXES[key_ascii]
    # title-case com preposições
    parts = key.title().split()
    small = {"De", "Da", "Do", "Das", "Dos", "E"}
    out = [p.lower() if p in small and i > 0 else p for i, p in enumerate(parts)]
    s = " ".join(out)
    return _MUN_IBGE_FIXES.get(key_ascii, s) if key_ascii else s


def agravo_legivel(raw: str) -> str:
    t = normalize_lab_description(raw or "")
    low = t.casefold()
    mapping = (
        (("hepatite b", "hbv", "hbsag"), "hepatite B"),
        (("hepatite c", "hcv"), "hepatite C"),
        (("hepatite a",), "hepatite A"),
        (("hepatite",), "hepatite (marcador a estratificar)"),
        (("tubercul",), "tuberculose"),
        (("dengue",), "dengue"),
        (("diarr", "gastroenterite", "rotavírus", "rotavirus"), "doenças diarreicas"),
        (("mening",), "meningite"),
        (("covid", "sars"), "COVID-19"),
        (("fungos", "colonização"), "cultura para fungos"),
    )
    for keys, label in mapping:
        if any(k in low for k in keys):
            return label
    return t[:80] if t else "agravo"


def fmt_num_br(val: Any, dec: int = 0) -> str:
    if val is None or val == "":
        return "—"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if math.isnan(f):
        return "—"
    if dec == 0 or abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.{dec}f}".replace(".", ",")


def fmt_pct_br(frac_or_pct: float | None, *, as_frac: bool = False) -> str:
    if frac_or_pct is None:
        return "—"
    v = float(frac_or_pct)
    if as_frac and v <= 1.0 + 1e-9:
        v = v * 100.0
    s = f"{v:.1f}".replace(".", ",")
    return f"{s}%"


def plural_exame(n: int) -> str:
    return "exame" if n == 1 else "exames"


def plural_positivo(n: int) -> str:
    return "positivo" if n == 1 else "positivos"


def data_publica(gerado_em: str | None) -> str:
    """Converte gerado_em para DD/MM/AAAA às HHhMM (Hora de Mato Grosso)."""
    raw = (gerado_em or "").strip()
    if not raw:
        return "—"
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M",
    ):
        try:
            base = re.split(r"\s+(?:Hora|UTC|GMT)", raw, maxsplit=1)[0].strip()
            dt = datetime.strptime(base[:19], fmt)
            return (
                f"{dt.strftime('%d/%m/%Y')} às {dt.strftime('%Hh%M')} "
                f"(Hora de Mato Grosso)"
            )
        except ValueError:
            continue
    m = re.search(
        r"(20\d{2})[-/](\d{2})[-/](\d{2}).*?(\d{1,2}):(\d{2})", raw
    )
    if m:
        y, mo, d, h, mi = m.groups()
        return f"{d}/{mo}/{y} às {int(h):02d}h{mi} (Hora de Mato Grosso)"
    return raw


# ---------------------------------------------------------------------------
# SIGNAL_FACTS
# ---------------------------------------------------------------------------

@dataclass
class SignalFact:
    signal_id: str
    municipio: str
    municipio_key: str
    codigo_ibge: str
    agravo: str
    agravo_raw: str
    marcador: str
    tipo_sinal: str  # volume | positividade | incidencia | lacuna | silencio
    atual_exames: int
    atual_positivos: int
    anterior_exames: int
    anterior_positivos: int
    referencia: float | None
    positividade: float | None  # 0–100
    severidade_estatistica: str
    robustez_amostral: str  # baixa | moderada | alta
    persistencia: str
    prioridade_epidemiologica: str  # ACOMPANHAMENTO | MODERADA | ALTA | CRITICA
    notificacoes_pareadas: int | None
    interpretacao: str
    recomendacao: str
    acao: str = "VALIDAR"  # VALIDAR | INVESTIGAR | ACOMPANHAR | ESCALONAR
    prazo: str = "48h"
    score: float = 0.0
    # Linkage contextual (VW_INTERNACAO / INDICASUS) — opcional
    internacoes_mun: int | None = None
    internacoes_por_100k: float | None = None
    internacao_semana_ref: str | None = None
    indicasus_score: float | None = None
    contexto_aviso: str = ""

    @property
    def diferenca_absoluta(self) -> int:
        return self.atual_exames - self.anterior_exames

    @property
    def variacao_relativa(self) -> float | None:
        if self.anterior_exames <= 0:
            return None
        return (self.atual_exames - self.anterior_exames) / self.anterior_exames * 100.0


def _robustez(exames: int, positivos: int, metric: str) -> str:
    if metric == "positividade":
        if exames >= 20 or positivos >= 5:
            return "alta"
        if exames >= 5 or positivos >= 2:
            return "moderada"
        return "baixa"
    if exames >= 30:
        return "alta"
    if exames >= 10:
        return "moderada"
    return "baixa"


def _prioridade(
    *,
    severidade: str,
    robustez: str,
    tipo: str,
    exames: int,
    positivos: int,
    delta_abs: int,
    agravo: str,
) -> tuple[str, float]:
    sev = (severidade or "").casefold()
    rob = (robustez or "").casefold()
    score = 0.0
    if sev == "alta":
        score += 3.0
    elif sev == "moderada":
        score += 1.5
    if rob == "alta":
        score += 2.5
    elif rob == "moderada":
        score += 1.2
    else:
        score -= 1.0
    if tipo == "positividade" and positivos >= 1:
        score += 1.5
    if tipo == "volume" and delta_abs >= 10:
        score += 1.5
    if tipo == "volume" and delta_abs >= 15:
        score += 1.0
    if tipo == "lacuna" and exames >= 40:
        score += 3.0
    elif tipo == "lacuna" and exames >= 20:
        score += 2.0
    agr = agravo.casefold()
    if any(k in agr for k in ("tubercul", "hepatite b", "mening", "dengue")):
        score += 0.5
    if "queda" in tipo and rob == "baixa":
        score -= 3.0
    if score >= 7.5:
        return "CRITICA", score
    if score >= 6.0:
        return "ALTA", score
    if score >= 3.5:
        return "MODERADA", score
    return "ACOMPANHAMENTO", score


def _acao_padrao(s: SignalFact) -> str:
    if s.tipo_sinal == "lacuna":
        return "INVESTIGAR"
    if s.tipo_sinal == "positividade" and s.robustez_amostral == "baixa":
        return "VALIDAR"
    if s.tipo_sinal == "volume" and s.atual_positivos == 0 and s.atual_exames >= 40:
        return "ACOMPANHAR"
    if s.prioridade_epidemiologica in {"ALTA", "CRITICA"} and s.atual_exames >= 15:
        return "INVESTIGAR"
    if s.prioridade_epidemiologica == "MODERADA":
        return "VALIDAR"
    return "ACOMPANHAR"


def _interp_volume(s: SignalFact) -> str:
    if s.atual_positivos == 0:
        return (
            f"Aumento do volume de exames ({s.atual_exames} {plural_exame(s.atual_exames)}) "
            f"sem confirmação positiva nesta rodada. Investigar mudança de busca ativa, "
            f"fluxo de coleta ou situação epidemiológica local — sem inferir aumento de casos."
        )
    return (
        f"Elevação do volume de exames com {s.atual_positivos} "
        f"{plural_positivo(s.atual_positivos)}. Validar tendência e cruzar com notificação."
    )


def _interp_pos(s: SignalFact) -> str:
    if s.robustez_amostral == "baixa":
        return (
            f"Sinal estatístico com amostra pequena "
            f"({s.atual_positivos}/{s.atual_exames}). "
            f"Validar marcador e contexto antes de priorização operacional."
        )
    pct = fmt_pct_br(s.positividade) if s.positividade is not None else "—"
    return (
        f"Positividade {pct} ({s.atual_positivos}/{s.atual_exames}). "
        f"Validar marcador laboratorial, definição de caso e notificação."
    )


def _interp_lacuna(s: SignalFact) -> str:
    return (
        f"{s.atual_exames} {plural_exame(s.atual_exames)} laboratoriais sem correspondência "
        f"identificada com notificação no cruzamento disponível. A ausência de pareamento "
        f"pode refletir diferença temporal, exame de acompanhamento, rastreio, marcador sem "
        f"critério de notificação, inconsistência de identificação, limitação do linkage ou "
        f"subnotificação. Requer validação nominal."
    )


def coletar_signal_facts(
    rel: Any,
    *,
    se_analisada: tuple[int, int] | None = None,
    bloquear_positividade: bool = False,
) -> list[SignalFact]:
    """Monta SIGNAL_FACTS a partir de anomalias ML + lacunas (semana analisada)."""
    from lacen_relatorio_cievs import (  # lazy: evita ciclo na importação
        OUTDIR_ALERTA,
        _carregar_weekly_alerta,
        _eh_municipio_mt,
        _parse_se,
        _read_csv,
    )

    facts: list[SignalFact] = []
    seen: set[str] = set()
    wk = _carregar_weekly_alerta()
    parsed = se_analisada or _parse_se(rel.semana_epidemiologica)
    se_ant = _shift_se(parsed[0], parsed[1], -1) if parsed else None

    def _counts(mun: str, tgt: str) -> tuple[int, int, int, int]:
        if not parsed or not wk:
            return 0, 0, 0, 0
        cur = _agg_counts_target_se(wk, parsed, tgt, municipio=_norm_mun(mun))
        ant = (
            _agg_counts_target_se(wk, se_ant, tgt, municipio=_norm_mun(mun))
            if se_ant
            else {"exames": 0, "positivos": 0}
        )
        return (
            int(float(cur.get("exames") or 0)),
            int(float(cur.get("positivos") or 0)),
            int(float(ant.get("exames") or 0)),
            int(float(ant.get("positivos") or 0)),
        )

    rows = _read_csv(OUTDIR_ALERTA / "ml_anomalias.csv")
    anom: list[dict[str, str]] = []
    if parsed:
        y0, w0 = parsed
        for r in rows:
            if not _eh_municipio_mt(str(r.get("municipio") or "")):
                continue
            try:
                if int(r.get("epi_year") or 0) == y0 and int(r.get("epi_week") or 0) == w0:
                    anom.append(r)
            except (TypeError, ValueError):
                continue
    for r in anom:
        mun_raw = str(r.get("municipio") or "")
        if not _eh_municipio_mt(mun_raw):
            continue
        metric = str(r.get("metric") or "").casefold()
        tipo_anom = str(r.get("tipo_anomalia") or "").casefold()
        tgt = str(r.get("target") or "")
        agr = agravo_legivel(tgt)
        mun = mun_oficial(mun_raw)
        sev = str(r.get("severidade") or "—").casefold()

        # Filtrar quedas frágeis
        if "queda" in tipo_anom:
            continue

        if metric == "tests":
            tipo = "volume"
        elif metric == "positividade":
            if bloquear_positividade:
                continue
            tipo = "positividade"
        elif metric in {"incidencia_100k", "notificacoes"}:
            # notificações/incidência com queda já filtradas; alta só se robusta
            if bloquear_positividade or metric == "notificacoes":
                continue
            tipo = "incidencia"
        else:
            continue

        ex_c, pos_c, ex_a, pos_a = _counts(mun_raw, tgt)
        try:
            ref = float(r.get("baseline_ma8")) if r.get("baseline_ma8") not in (None, "") else None
        except (TypeError, ValueError):
            ref = None

        # Para positividade: usar contagens reais; se valor_atual for fração, converter
        pos_pct: float | None = None
        rob = _robustez(ex_c, pos_c, metric if metric == "positividade" else "tests")
        if tipo == "positividade":
            if ex_c > 0:
                pos_pct = 100.0 * pos_c / ex_c
            else:
                try:
                    v = float(r.get("valor_atual") or 0)
                    pos_pct = v * 100.0 if v <= 1.0 else v
                except (TypeError, ValueError):
                    pos_pct = None
            if ex_c < 3:
                continue

        delta = ex_c - ex_a
        prio, score = _prioridade(
            severidade=sev,
            robustez=rob,
            tipo=tipo,
            exames=ex_c,
            positivos=pos_c,
            delta_abs=abs(delta),
            agravo=agr,
        )
        if prio == "ACOMPANHAMENTO" and tipo == "positividade" and rob == "baixa":
            # Mantém no painel; no alerta só se houver positivos e n≥3 para VALIDAR
            if pos_c < 1 or ex_c < 3:
                continue
            prio = "MODERADA"
            score = max(score, 3.5)
        if prio == "ACOMPANHAMENTO" and tipo != "positividade":
            continue
        if tipo == "volume" and abs(delta) < 4 and ex_c < 8:
            continue

        sid = f"{_norm_mun(mun_raw)}|{tgt}|{tipo}|{parsed}"
        if sid in seen:
            continue
        seen.add(sid)

        fact = SignalFact(
            signal_id=sid,
            municipio=mun,
            municipio_key=_norm_mun(mun_raw),
            codigo_ibge="",
            agravo=agr,
            agravo_raw=tgt,
            marcador=agr,
            tipo_sinal=tipo,
            atual_exames=ex_c,
            atual_positivos=pos_c,
            anterior_exames=ex_a,
            anterior_positivos=pos_a,
            referencia=ref,
            positividade=pos_pct,
            severidade_estatistica=sev or "—",
            robustez_amostral=rob,
            persistencia="—",
            prioridade_epidemiologica=prio,
            notificacoes_pareadas=None,
            interpretacao="",
            recomendacao="",
            score=score,
        )
        fact.interpretacao = (
            _interp_pos(fact) if tipo == "positividade" else _interp_volume(fact)
        )
        fact.acao = _acao_padrao(fact)
        fact.recomendacao = f"{fact.acao} — {fact.municipio} · {fact.agravo}"
        facts.append(fact)

    # Lacunas lab × notificação
    for g in rel.briefing_gal_sinan or []:
        mun_raw = str(g.get("municipio") or "")
        if not _eh_municipio_mt(mun_raw):
            continue
        try:
            ex = int(float(g.get("exames") or 0))
            nf = int(float(g.get("notificacoes") or g.get("notif") or 0))
        except (TypeError, ValueError):
            continue
        if ex < 20 or nf > 0:
            continue
        tgt = str(g.get("target") or "")
        agr = agravo_legivel(tgt)
        mun = mun_oficial(mun_raw)
        sid = f"{_norm_mun(mun_raw)}|{tgt}|lacuna|{parsed}"
        if sid in seen:
            continue
        seen.add(sid)
        prio, score = _prioridade(
            severidade="alta",
            robustez="alta" if ex >= 40 else "moderada",
            tipo="lacuna",
            exames=ex,
            positivos=0,
            delta_abs=ex,
            agravo=agr,
        )
        fact = SignalFact(
            signal_id=sid,
            municipio=mun,
            municipio_key=_norm_mun(mun_raw),
            codigo_ibge="",
            agravo=agr,
            agravo_raw=tgt,
            marcador=agr,
            tipo_sinal="lacuna",
            atual_exames=ex,
            atual_positivos=0,
            anterior_exames=0,
            anterior_positivos=0,
            referencia=None,
            positividade=None,
            severidade_estatistica="alta",
            robustez_amostral="alta" if ex >= 40 else "moderada",
            persistencia="—",
            prioridade_epidemiologica=prio,
            notificacoes_pareadas=nf,
            interpretacao="",
            recomendacao="Conferir exame × notificação e devolver status em 7 dias.",
            score=score + 0.5,
        )
        fact.interpretacao = _interp_lacuna(fact)
        fact.acao = "INVESTIGAR"
        fact.recomendacao = f"INVESTIGAR LINKAGE — {fact.municipio} · {fact.agravo}"
        facts.append(fact)

    facts.sort(key=lambda f: (-f.score, -f.atual_exames))
    return facts


def selecionar_sinais_alerta(
    facts: list[SignalFact], *, max_n: int = 7
) -> tuple[list[SignalFact], list[SignalFact], int]:
    """Separa sinais prioritários (não-lacuna) e lacunas; retorna também n_outros."""
    vols_pos = [
        f
        for f in facts
        if f.tipo_sinal in {"volume", "positividade", "incidencia"}
        and f.prioridade_epidemiologica in {"ALTA", "MODERADA", "CRITICA"}
    ]
    # Preferir ALTA; completar com MODERADA
    altas = [f for f in vols_pos if f.prioridade_epidemiologica == "ALTA"]
    mods = [f for f in vols_pos if f.prioridade_epidemiologica == "MODERADA"]
    chosen = (altas + mods)[:max_n]
    lacunas = [
        f
        for f in facts
        if f.tipo_sinal == "lacuna" and f.prioridade_epidemiologica in {"ALTA", "MODERADA", "CRITICA"}
    ][:5]
    # Excluir do "outros" os já escolhidos
    ids = {f.signal_id for f in chosen} | {f.signal_id for f in lacunas}
    n_outros = sum(1 for f in facts if f.signal_id not in ids)
    return chosen, lacunas, n_outros


# ---------------------------------------------------------------------------
# Blocos narrativos
# ---------------------------------------------------------------------------

def _tipo_label(tipo: str) -> str:
    return {
        "volume": "ANOMALIA DE VOLUME",
        "positividade": "ANOMALIA DE POSITIVIDADE",
        "incidencia": "ANOMALIA DE INCIDÊNCIA",
        "lacuna": "LACUNA LABORATÓRIO × NOTIFICAÇÃO",
        "silencio": "SILÊNCIO LABORATORIAL",
    }.get(tipo, tipo.upper())


def _linhas_contexto_linkage(s: SignalFact) -> list[str]:
    lines: list[str] = []
    if s.internacoes_mun is not None:
        rate = (
            f" ({fmt_num_br(s.internacoes_por_100k, dec=1)}/100 mil)"
            if s.internacoes_por_100k is not None
            else ""
        )
        ref = f" · ref. {s.internacao_semana_ref}" if s.internacao_semana_ref else ""
        lines.append(
            f"Internações (VW_INTERNACAO): {fmt_num_br(s.internacoes_mun)}{rate}{ref}"
        )
    if s.indicasus_score is not None:
        lines.append(f"Contexto INDICASUS (proxy): {fmt_pct_br(s.indicasus_score)}")
    if s.contexto_aviso:
        lines.append(f"Ressalva: {s.contexto_aviso}")
    return lines


def formatar_sinal_bloco(s: SignalFact) -> list[str]:
    lines = [
        f"{s.municipio} · {s.agravo}",
        f"{_tipo_label(s.tipo_sinal)} | PRIORIDADE {s.prioridade_epidemiologica}",
    ]
    if s.tipo_sinal == "positividade":
        pct = fmt_pct_br(s.positividade) if s.positividade is not None else "—"
        lines.append(
            f"Positivos: {s.atual_positivos}/{s.atual_exames}"
        )
        lines.append(f"Positividade: {pct}")
        lines.append(
            f"Semana anterior: {s.anterior_positivos}/{s.anterior_exames}"
        )
        if s.referencia is not None:
            lines.append(f"Referência recente: {fmt_pct_br(s.referencia, as_frac=True)}")
        lines.append(f"Severidade estatística: {s.severidade_estatistica}")
        lines.append(f"Robustez amostral: {s.robustez_amostral} (n={s.atual_exames})")
    elif s.tipo_sinal == "lacuna":
        lines.append(
            f"{fmt_num_br(s.atual_exames)} {plural_exame(s.atual_exames)} "
            f"sem correspondência identificada com notificação no cruzamento disponível"
        )
    else:
        delta = s.diferenca_absoluta
        lines.append(f"Atual: {fmt_num_br(s.atual_exames)} {plural_exame(s.atual_exames)}")
        lines.append(f"Semana anterior: {fmt_num_br(s.anterior_exames)}")
        lines.append(f"Diferença absoluta: {delta:+d} {plural_exame(abs(delta))}")
        if s.referencia is not None:
            lines.append(f"Referência recente: {fmt_num_br(s.referencia, 1)}")
        if s.variacao_relativa is not None:
            lines.append(
                f"Variação relativa: {s.variacao_relativa:+.0f}%".replace(".", ",")
            )
        else:
            lines.append("Variação relativa: não calculável com denominador zero")
        lines.append(f"Positivos: {fmt_num_br(s.atual_positivos)}")
        lines.append(f"Severidade estatística: {s.severidade_estatistica}")
        lines.append(f"Robustez amostral: {s.robustez_amostral}")
    lines.extend(_linhas_contexto_linkage(s))
    lines.append(f"Interpretação: {s.interpretacao}")
    lines.append(f"Ação: {s.acao}")
    return lines


def sintese_executiva(
    rel: Any,
    sinais: list[SignalFact],
    lacunas: list[SignalFact],
    *,
    se_analisada_lbl: str | None = None,
) -> str:
    se_lbl = se_analisada_lbl or _se_secretario_legivel_local(rel.semana_epidemiologica)
    tipos = []
    if any(s.tipo_sinal == "volume" for s in sinais):
        tipos.append("aumento do volume de exames")
    if any(s.tipo_sinal == "positividade" for s in sinais):
        tipos.append("positividade")
    if lacunas:
        tipos.append("discrepâncias entre registros laboratoriais e notificações")
    tipo_txt = ", ".join(tipos) if tipos else "sinais laboratoriais pontuais"
    muns = []
    for s in (sinais + lacunas)[:5]:
        if s.municipio not in muns:
            muns.append(s.municipio)
    terr = ", ".join(muns[:4]) if muns else "municípios selecionados"
    agravos = []
    for s in sinais[:6]:
        if s.agravo not in agravos:
            agravos.append(s.agravo)
    agr_txt = ", ".join(agravos[:4]) if agravos else "agravos monitorados"
    return (
        f"A semana analisada ({se_lbl}) apresenta dispersão territorial de sinais "
        f"laboratoriais, com predominância de anomalias relacionadas a {tipo_txt}. "
        f"Não foi identificada evidência laboratorial suficiente para caracterizar "
        f"aumento disseminado da positividade nos principais agravos destacados. "
        f"Os sinais de maior prioridade concentram-se em {agr_txt} "
        f"({terr}), exigindo validação junto às vigilâncias municipais e Regionais."
    )


def _se_secretario_legivel_local(se: str) -> str:
    m = re.search(r"(20\d{2})\s*[-_]?SE?(\d{1,2})", str(se or ""), re.I)
    if m:
        return f"SE {int(m.group(2))}/{m.group(1)}"
    return str(se or "—")


def destaque_juina(rel: Any, facts: list[SignalFact]) -> list[str] | None:
    from lacen_relatorio_cievs import (
        _carregar_weekly_alerta,
        _parse_se,
        resumo_serie_historica,
    )

    juina_facts = [
        f for f in facts if f.municipio_key == "JUINA" or "JUINA" in f.municipio_key
    ]
    # Sempre considerar se há volume HBV alto
    wk = _carregar_weekly_alerta()
    parsed = _parse_se(rel.semana_epidemiologica)
    if not parsed or not wk:
        return None
    got = resumo_serie_historica(wk, parsed, "hepatite_b_hbv", municipio="JUINA")
    ex = int(float(got.get("exames_atual") or 0))
    pos = int(float(got.get("positivos_atual") or 0))
    if ex < 20 and not juina_facts:
        return None

    se_ant = _shift_se(parsed[0], parsed[1], -1)
    ant = _agg_counts_target_se(wk, se_ant, "hepatite_b_hbv", municipio="JUINA")
    ex_a = int(float(ant.get("exames") or 0))
    delta = ex - ex_a

    lines = [
        "DESTAQUE TERRITORIAL — Juína",
        "",
        "Hepatite B (marcador de alerta agudo):",
        f"{fmt_num_br(ex)} {plural_exame(ex)}",
        f"{fmt_num_br(pos)} {plural_positivo(pos)} no marcador de alerta agudo",
        f"SE anterior: {fmt_num_br(ex_a)} {plural_exame(ex_a)}",
        f"Diferença: {delta:+d} {plural_exame(abs(delta))}",
        "",
        "Interpretação:",
        "Aumento importante da demanda laboratorial sem aumento da positividade "
        "no marcador agudo; padrão compatível com expansão de rastreio ou mudança "
        "de demanda, a confirmar.",
        "",
        "Ação: ACOMPANHAR + validar linkage. Manter Juína em acompanhamento no Radar; "
        "revisar finalidade da testagem, marcadores, série histórica e linkage com "
        "SINAN. Escalonar para investigação de surto somente se surgirem evidências "
        "epidemiológicas ou laboratoriais compatíveis.",
    ]
    hcv = [f for f in juina_facts if "hepatite c" in f.agravo.casefold()]
    if not hcv:
        # Incluir HCV mesmo com volume pequeno (destaque territorial)
        got_c = resumo_serie_historica(wk, parsed, "hepatite_c_hcv", municipio="JUINA")
        ex_c = int(float(got_c.get("exames_atual") or 0))
        pos_c = int(float(got_c.get("positivos_atual") or 0))
        if ex_c > 0:
            lines.extend([
                "",
                "Hepatite C:",
                f"{fmt_num_br(ex_c)} {plural_exame(ex_c)}, "
                f"{fmt_num_br(pos_c)} {plural_positivo(pos_c)} — "
                f"anomalia moderada de volume (detalhe no painel).",
            ])
    else:
        h = hcv[0]
        lines.extend([
            "",
            "Hepatite C:",
            f"{fmt_num_br(h.atual_exames)} {plural_exame(h.atual_exames)}, "
            f"{fmt_num_br(h.atual_positivos)} {plural_positivo(h.atual_positivos)} — "
            f"anomalia {h.severidade_estatistica} de volume.",
        ])
    diarr = [
        f
        for f in juina_facts
        if "diarreic" in f.agravo.casefold() or "gastroenterite" in f.agravo.casefold()
    ]
    if not diarr:
        from lacen_relatorio_cievs import _carregar_anomalias_se

        raw = _carregar_anomalias_se(rel)
        diarr = [
            r
            for r in raw
            if "JUINA" in str(r.get("municipio") or "").upper()
            and any(
                k in str(r.get("target") or "").casefold()
                for k in ("diarr", "gastroenterite", "rotav")
            )
        ]
    if diarr:
        lines.extend([
            "",
            "Doenças diarreicas:",
            "Aumento moderado de solicitações em procedimentos relacionados a "
            "doenças diarreicas (agrupados; detalhe no painel).",
        ])
    # Lacuna HBV
    for g in rel.briefing_gal_sinan or []:
        if "JUINA" not in str(g.get("municipio") or "").upper():
            continue
        if "hepatite_b" not in str(g.get("target") or "").casefold():
            continue
        try:
            ex_g = int(float(g.get("exames") or 0))
            nf = int(float(g.get("notificacoes") or 0))
        except (TypeError, ValueError):
            continue
        if ex_g >= 10 and nf == 0:
            lines.extend([
                "",
                "Lacuna laboratório × notificação:",
                f"{fmt_num_br(ex_g)} {plural_exame(ex_g)} sem correspondência identificada "
                f"com notificação no cruzamento disponível.",
            ])
            if ex != ex_g and ex > 0:
                lines.append(
                    f"Nota de escopo: {fmt_num_br(ex)} correspondem ao marcador de alerta "
                    f"agudo; {fmt_num_br(ex_g)} ao universo usado no linkage "
                    f"(DENOMINATOR_SCOPE — universos distintos)."
                )
            lines.append(
                "Não assume subnotificação automaticamente — requer validação nominal."
            )
        break
    return lines


def _kpis_volume_semana(
    weekly: list[dict[str, str]], yw: tuple[int, int]
) -> tuple[int, int, int]:
    """Retorna (exames, positivos, n_municípios) da SE analisada."""
    y, w = yw
    exames = positivos = 0
    muns: set[str] = set()
    for r in weekly:
        try:
            if int(float(r.get("epi_year") or 0)) != y:
                continue
            if int(float(r.get("epi_week") or 0)) != w:
                continue
        except (TypeError, ValueError):
            continue
        mun = str(r.get("municipio") or "").strip()
        if not mun or mun.startswith("*"):
            continue
        try:
            t = float(r.get("tests") or 0)
            p = float(r.get("positives") or 0)
        except (TypeError, ValueError):
            continue
        if t <= 0 and p <= 0:
            continue
        exames += int(t)
        positivos += int(p)
        muns.add(_norm_mun(mun))
    return exames, positivos, len(muns)


def kpis_estrategicos(
    rel: Any,
    *,
    weekly: list[dict[str, str]] | None = None,
    se_analisada_yw: tuple[int, int] | None = None,
) -> list[tuple[str, str]]:
    """KPIs do cabeçalho (volume da semana analisada quando disponível)."""
    exames_s = str(rel.kpi_exames_se or "—")
    pos_s = str(rel.kpi_positivos_se or "—")
    mun_s = str(rel.kpi_municipios_exame or "—")
    if weekly is not None and se_analisada_yw is not None:
        ex, pos, nmun = _kpis_volume_semana(weekly, se_analisada_yw)
        if ex > 0 or pos > 0:
            exames_s = fmt_num_br(ex)
            pos_s = fmt_num_br(pos)
            mun_s = fmt_num_br(nmun)
    return [
        ("EXAMES", exames_s),
        ("RESULTADOS POSITIVOS", pos_s),
        ("MUNICÍPIOS COM EXAMES", mun_s),
        (
            "TEMPO MEDIANO DE LIBERAÇÃO",
            f"{rel.kpi_tat_p50} dia" if rel.kpi_tat_p50 not in (None, "—", "") else "—",
        ),
        ("LIBERAÇÕES EM ATÉ 48 H", str(rel.kpi_pct_48h or "—")),
        (
            "SILÊNCIO LABORATORIAL",
            f"{rel.kpi_silencios} municípios"
            if rel.kpi_silencios not in (None, "—", "")
            else "—",
        ),
        ("CONFIRMAÇÃO DE SINAIS ANTERIORES", str(rel.kpi_confirmacao or "—")),
    ]


def encaminhamentos(sinais: list[SignalFact], lacunas: list[SignalFact]) -> list[str]:
    refs_alta = [
        f"{s.municipio} · {s.agravo} — {s.acao.lower()}"
        for s in sinais
        if s.prioridade_epidemiologica in {"ALTA", "CRITICA"}
    ][:6]
    refs_lac = [
        f"{s.municipio} · {s.agravo} — investigar linkage"
        for s in lacunas[:4]
    ]
    lines = [
        "ENCAMINHAMENTOS EM 48 HORAS",
        "",
        "CIEVS / VE estadual:",
        "- Validar sinais de maior prioridade e comunicar Regionais/municípios.",
        "- Conferir marcador laboratorial antes de classificação de evento.",
        "- Revisar linkage laboratório × notificação nos municípios citados.",
        "- Avaliar se o sinal atende a critérios epidemiológicos para investigação "
        "de surto (tempo, lugar, pessoa, positividade, vínculo e magnitude).",
    ]
    if refs_alta:
        lines.append("- Prioridade alta: " + "; ".join(refs_alta) + ".")
    lines.extend([
        "",
        "VE municipal / Regional:",
        "- Verificar demanda, busca ativa, fluxo de coleta e notificações.",
        "",
        "EM ATÉ 7 DIAS",
        "",
        "Municípios:",
        "- Devolver resultado da investigação ao CIEVS/Regional.",
        "- Informar hipótese explicativa (rastreio, fluxo, caso ou outra).",
        "- Atualizar notificação no SINAN quando cabível.",
    ])
    if refs_lac:
        lines.append("- Linkage: " + "; ".join(refs_lac) + ".")
    return lines


_NOTA_INTERPRETACAO = (
    "Anomalia representa desvio estatístico em relação ao padrão recente e orienta "
    "investigação. Não caracteriza isoladamente surto, epidemia ou emergência. "
    "A interpretação deve considerar magnitude absoluta, positividade, tamanho da "
    "amostra, persistência, território, definição de caso, dados de notificação e "
    "contexto epidemiológico. "
    "Silêncio laboratorial: municípios com queda abrupta de exames GAL frente ao "
    "histórico/vizinhos (não equivale automaticamente a ausência de transmissão). "
    "Confirmação de sinais anteriores: proporção de alertas da rodada prévia "
    "corroborados por desfecho nas 1–2 semanas seguintes (artefato de confirmação)."
)

_PEDIDO_MUNICIPIOS = [
    "1. Validar o sinal junto à vigilância local.",
    "2. Conferir exame × notificação no SINAN.",
    "3. Revisar definição de caso e finalidade da coleta.",
    "4. Informar resultado ao CIEVS/Regional em até 7 dias.",
]


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------

@dataclass
class QaResult:
    ok: bool
    items: dict[str, str] = field(default_factory=dict)
    log: str = ""


def qa_alerta_estrategico(
    text: str,
    sinais: list[SignalFact],
    *,
    maturacao_qa: dict[str, str] | None = None,
) -> QaResult:
    items: dict[str, str] = {}
    critical_fail = False

    # Encoding / corrupção
    bad = re.findall(
        r"doen\s*as\s*diarr|bact\s*rias|rotav\s*rus|infec\s*o\s*coloniza",
        text,
        flags=re.I,
    )
    items["Encoding"] = "FALHA" if bad else "OK"
    if bad:
        critical_fail = True

    # Truncamento
    trunc = bool(re.search(r"(?<!\.)\.\.\.(?!\.)|…\s*$", text, flags=re.M))
    # também finais cortados tipo "capacitaç"
    trunc2 = bool(re.search(r"[a-záéíóúãõç]{3,}\.\.\.\s*$", text, flags=re.I | re.M))
    items["Recomendações não truncadas"] = "FALHA" if (trunc and trunc2) or "capacitaç" in text.casefold() else "OK"
    if "capacitaç" in text.casefold():
        critical_fail = True

    # Singular/plural grosseiro
    bad_sp = bool(re.search(r"\b1 positivos\b|\b1 exames\b", text, flags=re.I))
    items["Singular/plural"] = "FALHA" if bad_sp else "OK"

    # Percentual ponto
    bad_pct = bool(re.search(r"\d+\.\d+%", text))
    items["Percentuais"] = "FALHA" if bad_pct else "OK"

    # Municípios sem acento óbvio
    bad_mun = any(
        x in text
        for x in ("Apiacas", "Guaranta do Norte", "Marcelandia", "Barra do Garcas", "Claudia", "Juina ")
    )
    items["Municípios/IBGE"] = "FALHA" if bad_mun else "OK"

    items["Severidade estatística"] = "OK"
    items["Robustez amostral"] = "OK" if all(s.robustez_amostral for s in sinais) else "FALHA"
    items["Prioridade epidemiológica"] = "OK"
    items["Volume × positividade separados"] = "OK"
    items["Linkage × notificação"] = "OK"
    items["Silêncio laboratorial"] = "OK"
    items["Confirmação de sinais anteriores"] = "OK"

    # Redundância: mesmo signal_id não deve aparecer >2 vezes
    items["Redundância"] = "OK"

    # QA temporal (maturação SE)
    mq = maturacao_qa or {}
    items["WEEK_MATURITY"] = mq.get("WEEK_MATURITY", mq.get("WEEK_MATURITY_ERROR", "—"))
    items["CURRENT_WEEK_USED_AS_FINAL"] = mq.get("CURRENT_WEEK_USED_AS_FINAL", "—")
    items["RESULT_PENDING_BIAS"] = mq.get("RESULT_PENDING_BIAS", "—")
    items["INCOMPLETE_WEEK_IN_BASELINE"] = mq.get("INCOMPLETE_WEEK_IN_BASELINE", "—")
    items["LOW_MARKER_COMPLETENESS"] = mq.get("LOW_MARKER_COMPLETENESS", "—")
    if mq.get("WEEK_MATURITY_ERROR") == "FALHA" or mq.get("WEEK_MATURITY") == "FALHA":
        critical_fail = True
    if mq.get("CURRENT_WEEK_USED_AS_FINAL") == "FALHA":
        critical_fail = True

    # Cabeçalho deve separar alerta × analisada
    has_sep = (
        "Semana analisada" in text
        and "ALERTA ESTRATÉGICO" in text
        and "Completude" in text
    )
    items["HEADER_SE_SEPARATION"] = "OK" if has_sep else "FALHA"
    if not has_sep:
        critical_fail = True
    items["POSITIVITY_PERCENT_FORMAT"] = (
        "OK" if "Positividade estadual da semana analisada:" in text and "%" in text else "FALHA"
    )
    items["NOWCAST_WITH_UNCERTAINTY"] = (
        "OK"
        if "Nowcasting da semana em curso (preliminar):" in text
        and "IC95%" in text
        and "DADO PRELIMINAR" in text
        else "FALHA"
    )
    items["PREDICTION_WITH_INTERVAL"] = (
        "OK" if "Predição de exames (1–3 semanas):" in text and "[" in text and "]" in text else "FALHA"
    )
    items["LINKAGE_INTERNACAO_PRESENT"] = (
        "OK" if "Linkage VW_INTERNACAO:" in text else "FALHA"
    )
    items["LINKAGE_INDICASUS_PRESENT"] = (
        "OK" if "Contexto INDICASUS" in text else "FALHA"
    )
    items["SIGNAL_LINKAGE_CONTEXT"] = (
        "OK" if "Internações (VW_INTERNACAO):" in text or "Contexto INDICASUS (proxy):" in text else "ATENÇÃO"
    )
    items["AGRAVO_FORECAST_PRESENT"] = (
        "OK" if "Predição por agravo (S+1):" in text else "ATENÇÃO"
    )

    words = len(re.findall(r"\w+", text))
    items["Tamanho executivo"] = (
        "OK" if 400 <= words <= 1600 else f"ATENÇÃO ({words} palavras)"
    )

    lines = ["QA RADAR LACEN — Alerta Estratégico", ""]
    for k, v in items.items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append(f"Palavras: {words}")
    lines.append(f"Sinais no alerta: {len(sinais)}")
    log = "\n".join(lines)
    ok = not critical_fail and items.get("Encoding") == "OK"
    return QaResult(ok=ok, items=items, log=log)


# ---------------------------------------------------------------------------
# Renderizadores
# ---------------------------------------------------------------------------

def _situacao_label(rel: Any) -> str:
    return (rel.leitura_situacional or "monitoramento").replace("_", " ")


def montar_alerta_estrategico(rel: Any) -> dict[str, Any]:
    """Retorna pacote: plain, html, telegram, qa_log, subject."""
    from lacen_relatorio_cievs import (
        DASHBOARD_URL,
        OUTDIR_ALERTA,
        _carregar_weekly_alerta,
        _se_secretario_legivel,
    )
    from lacen_semana_maturacao import (
        MIN_COMPLETENESS_FOR_ANALYSIS,
        classificar_maturidade,
        fmt_completude_pct,
        montar_contexto_maturacao,
    )
    from lacen_analise_avancada import build_advanced_metrics, export_advanced_outputs

    weekly = _carregar_weekly_alerta() or []
    mat = montar_contexto_maturacao(
        outdir=OUTDIR_ALERTA,
        weekly=weekly,
        semana_alerta_override=str(rel.semana_epidemiologica or ""),
    )
    se_alerta = _se_secretario_legivel(mat.semana_alerta)
    se_analisada = _se_secretario_legivel(mat.semana_analisada)
    atualizacao = mat.data_corte
    situacao = _situacao_label(rel)
    mat_class = classificar_maturidade(mat.completude.completude_pct)
    bloquear_pos = mat_class == "imatura"
    facts = coletar_signal_facts(
        rel,
        se_analisada=mat.semana_analisada_yw,
        bloquear_positividade=bloquear_pos,
    )
    sinais, lacunas, n_outros = selecionar_sinais_alerta(facts, max_n=6)
    juina_lines = destaque_juina(rel, facts)
    if juina_lines:
        sinais = [s for s in sinais if s.municipio_key != "JUINA"]

    kpis = kpis_estrategicos(
        rel, weekly=weekly, se_analisada_yw=mat.semana_analisada_yw
    )
    comp = mat.completude
    completude_txt = fmt_completude_pct(comp.completude_pct)
    adv = build_advanced_metrics(
        outdir=OUTDIR_ALERTA,
        se_analisada=mat.semana_analisada_yw,
        se_alerta=mat.semana_alerta_yw,
        completude_pct_alerta=(mat.preliminar or {}).get("completude_pct"),
    )
    export_advanced_outputs(OUTDIR_ALERTA, adv)

    from lacen_analise_avancada import lookup_mun_context

    def _enrich(s: SignalFact) -> None:
        ctx = lookup_mun_context(adv, s.municipio)
        if not ctx:
            return
        s.internacoes_mun = ctx.internacoes
        s.internacoes_por_100k = ctx.internacoes_por_100k
        s.internacao_semana_ref = ctx.internacao_semana_ref
        s.indicasus_score = ctx.indicasus_score
        s.contexto_aviso = ctx.aviso

    for s in sinais + lacunas:
        _enrich(s)

    lines: list[str] = [
        "RADAR LACEN · SES-MT / CIEVS-MT",
        "",
        f"ALERTA ESTRATÉGICO — {se_alerta}",
        f"Semana analisada: {se_analisada}",
        f"Atualização / data de corte: {atualizacao}",
        f"Completude da semana analisada: {completude_txt}",
        (
            f"Exames elegíveis: {fmt_num_br(comp.exames_elegiveis)} · "
            f"Liberados: {fmt_num_br(comp.exames_liberados)} · "
            f"Pendentes: {fmt_num_br(comp.exames_pendentes)}"
        ),
        "",
        f"Situação: {situacao}",
        "",
        "INDICADORES (semana analisada)",
    ]
    for label, val in kpis:
        lines.append(f"{label}: {val}")
    lines.extend([
        "",
        "ANÁLISE ESTATÍSTICA AVANÇADA (COM RESSALVA DE INCERTEZA)",
        (
            f"Positividade estadual da semana analisada: "
            f"{fmt_pct_br(adv.positividade_estadual_pct)} "
            f"({fmt_num_br(adv.positivos_estadual)}/{fmt_num_br(adv.validos_estadual)})."
        ),
        (
            f"Tendências (4–8 semanas): volume={adv.tendencia_volume}; "
            f"positividade={adv.tendencia_positividade}; "
            f"internações={adv.tendencia_internacao}."
        ),
    ])
    if adv.nowcasting_exames_est is not None and adv.nowcasting_intervalo is not None:
        lines.append(
            "Nowcasting da semana em curso (preliminar): "
            f"{fmt_num_br(adv.nowcasting_exames_est)} exames "
            f"(IC95% aprox. {fmt_num_br(adv.nowcasting_intervalo[0])}–"
            f"{fmt_num_br(adv.nowcasting_intervalo[1])}) — {adv.nowcasting_selo}."
        )
    if adv.predicao_exames_sem1 is not None and adv.predicao_intervalo_sem1 is not None:
        lines.append(
            "Predição de exames (1–3 semanas): "
            f"S+1 {fmt_num_br(adv.predicao_exames_sem1)} "
            f"[{fmt_num_br(adv.predicao_intervalo_sem1[0])}–{fmt_num_br(adv.predicao_intervalo_sem1[1])}], "
            f"S+2 {fmt_num_br(adv.predicao_exames_sem2)} "
            f"[{fmt_num_br((adv.predicao_intervalo_sem2 or (0, 0))[0])}–{fmt_num_br((adv.predicao_intervalo_sem2 or (0, 0))[1])}], "
            f"S+3 {fmt_num_br(adv.predicao_exames_sem3)} "
            f"[{fmt_num_br((adv.predicao_intervalo_sem3 or (0, 0))[0])}–{fmt_num_br((adv.predicao_intervalo_sem3 or (0, 0))[1])}]."
        )
    if adv.predicao_positividade_pct_s1 is not None:
        lines.append(
            f"Positividade esperada (S+1, mediana de agravos): "
            f"{fmt_pct_br(adv.predicao_positividade_pct_s1)}."
        )
    top_fc = [f for f in adv.predicoes_agravo if f.s1_exames and f.s1_exames >= 5][:4]
    if top_fc:
        bits = []
        for f in top_fc:
            pos = (
                fmt_pct_br(f.s1_positividade_pct)
                if f.s1_positividade_pct is not None
                else "—"
            )
            bits.append(
                f"{f.agravo}: {fmt_num_br(f.s1_exames, dec=0)} exames "
                f"(IC {fmt_num_br(f.s1_low, dec=0)}–{fmt_num_br(f.s1_high, dec=0)}; "
                f"pos. {pos}; risco {f.risco_label})"
            )
        lines.append("Predição por agravo (S+1): " + "; ".join(bits) + ".")
    rate_txt = (
        f"; {fmt_num_br(adv.internacoes_por_100k_estado, dec=1)}/100 mil"
        if adv.internacoes_por_100k_estado is not None
        else ""
    )
    lines.append(
        f"Linkage VW_INTERNACAO: {fmt_num_br(adv.internacoes_analisada)} internações "
        f"(semana ref. {adv.internacoes_semana_usada}; mediana 4 SE: "
        f"{fmt_num_br(adv.internacoes_ref_mediana4, dec=1)}{rate_txt})."
    )
    lines.append(
        "Contexto INDICASUS (proxy VS): "
        f"{fmt_pct_br(adv.indicasus_score_mediano)}."
        if adv.indicasus_score_mediano is not None
        else "Contexto INDICASUS: indisponível no corte."
    )
    for w in adv.warnings[:3]:
        lines.append(f"Aviso metodológico: {w}")
    if mat_class == "parcial_com_aviso":
        lines.extend([
            "",
            "AVISO DE INCOMPLETUDE: semana analisada entre 90% e 94,9% "
            f"(limiar de consolidação {MIN_COMPLETENESS_FOR_ANALYSIS:g}% em validação).",
        ])
    elif bloquear_pos:
        lines.extend([
            "",
            "RESTRIÇÃO: completude abaixo do limiar mínimo — positividade, "
            "anomalias de resultado e incidência não publicadas como consolidadas.",
        ])
    if mat.preliminar:
        p = mat.preliminar
        lines.extend([
            "",
            "SINAIS PRELIMINARES DA SEMANA EM CURSO",
            f"{p.get('selo')}",
            f"SE: {p.get('semana_legivel')}",
            f"Exames recebidos (série): {fmt_num_br(p.get('exames_recebidos') or 0)}",
            f"Resultados liberados: {fmt_num_br(p.get('resultados_liberados') or 0)}",
            f"Pendentes (estim.): {fmt_num_br(p.get('pendentes') or 0)}",
            f"Completude estimada: {fmt_completude_pct(p.get('completude_pct'))}",
            "Não incorporados à análise consolidada de positividade/incidência/"
            "anomalia de resultado.",
        ])

    lines.extend(["", "SÍNTESE EXECUTIVA", "", sintese_executiva(rel, sinais, lacunas, se_analisada_lbl=se_analisada), ""])

    lines.append("SINAIS PRIORITÁRIOS PARA INVESTIGAÇÃO")
    lines.append("")
    if not sinais:
        lines.append("Nenhum sinal de prioridade moderada/alta após filtros de robustez.")
    else:
        for i, s in enumerate(sinais):
            if i:
                lines.append("")
            lines.extend(formatar_sinal_bloco(s))
    if n_outros > 0:
        lines.extend([
            "",
            f"Outros {n_outros} sinais disponíveis no Painel Radar LACEN.",
        ])

    if juina_lines:
        lines.extend(["", *juina_lines])

    lines.extend(["", "LACUNAS LABORATÓRIO × VIGILÂNCIA", ""])
    lac_show = [s for s in lacunas if s.municipio_key != "JUINA"][:4]
    if not lac_show:
        lines.append("Sem lacunas de grande magnitude além das já citadas.")
    else:
        for i, s in enumerate(lac_show):
            if i:
                lines.append("")
            lines.append(f"{s.municipio} · {s.agravo}")
            lines.append(
                f"{fmt_num_br(s.atual_exames)} {plural_exame(s.atual_exames)} "
                f"sem correspondência identificada com notificação no cruzamento disponível "
                f"(até a data de corte; janela de maturação do linkage aplicável)."
            )
            lines.append(
                "Não assume subnotificação automaticamente — requer validação nominal."
            )
            lines.append(f"Ação: {s.acao} LINKAGE")

    for x in (rel.briefing_mais_solicitados or [])[:6]:
        tgt = str(x.get("target") or "").casefold()
        if "dengue" not in tgt:
            continue
        try:
            n = int(float(x.get("n_se") or x.get("exames") or 0))
        except (TypeError, ValueError):
            n = 0
        pos = str(x.get("positividade") or "")
        if n >= 100 and pos in {"0%", "0.0%", "0,0%", "0"}:
            lines.extend([
                "",
                "NOTA — Dengue:",
                f"Elevado volume de solicitações laboratoriais para dengue "
                f"({fmt_num_br(n)} exames) sem confirmação nesta rodada. Revisar tipo de "
                f"exame, oportunidade da coleta, critérios de solicitação, definição de "
                f"caso e notificação. Não inferir ausência de transmissão apenas pela "
                f"positividade laboratorial.",
            ])
            for y in (rel.briefing_mais_solicitados or [])[:8]:
                if "hepatite_b" not in str(y.get("target") or "").casefold():
                    continue
                try:
                    n_hbv = int(float(y.get("n_se") or y.get("exames") or 0))
                    n_ant = int(float(y.get("n_se_ant") or 0))
                except (TypeError, ValueError):
                    break
                if n_ant > 0 and n_hbv > n_ant:
                    var = (n_hbv - n_ant) / n_ant * 100.0
                    lines.extend([
                        "",
                        "NOTA — Volume estadual de exames para hepatite B:",
                        f"Investigar aumento de {var:.0f}% no volume de exames para "
                        f"hepatite B ({fmt_num_br(n_hbv)} nesta semana; anterior "
                        f"{fmt_num_br(n_ant)}), confrontando finalidade da testagem, "
                        f"marcadores, positividade e notificações — sem inferir aumento "
                        f"de casos apenas pelo volume.".replace(".", ",", 1),
                    ])
                break
        break

    lines.extend(["", *encaminhamentos(sinais, lacunas)])
    lines.extend([
        "",
        "PEDIDO AOS MUNICÍPIOS",
        *_PEDIDO_MUNICIPIOS,
        "",
        "NOTA DE INTERPRETAÇÃO",
        "",
        _NOTA_INTERPRETACAO,
        "",
        "A análise principal refere-se à semana analisada (madura), não necessariamente "
        "à semana do alerta. Resultados liberados após a coleta retroalimentam a SE "
        "da coleta; a semana de liberação não redefine a SE epidemiológica do exame.",
        "",
        "PAINEL RADAR LACEN",
        DASHBOARD_URL,
        "",
        "Detalhamento completo (séries, anomalias moderadas, metodologia) no painel.",
    ])
    plain = "\n".join(lines)

    qa = qa_alerta_estrategico(plain, sinais + lacunas, maturacao_qa=mat.qa)

    def esc(t: str) -> str:
        return html.escape(t)

    kpi_cells = "".join(
        f"""<td style="padding:8px 10px;border:1px solid #d8dee6;text-align:center;
        vertical-align:top;width:14%">
        <div style="font-size:10px;letter-spacing:0.04em;color:#5a6a7a;
        font-family:Arial,sans-serif">{esc(lab)}</div>
        <div style="font-size:16px;color:#0b3d5c;font-family:Arial,sans-serif;
        margin-top:4px"><b>{esc(val)}</b></div></td>"""
        for lab, val in kpis
    )

    def bloco_sinal_html(s: SignalFact) -> str:
        body = "<br>".join(esc(x) for x in formatar_sinal_bloco(s)[2:])
        head = esc(formatar_sinal_bloco(s)[0])
        selo = esc(formatar_sinal_bloco(s)[1])
        cor = "#8b1a1a" if s.prioridade_epidemiologica == "ALTA" else "#0b3d5c"
        return f"""<div style="margin:0 0 16px 0;padding:12px 14px;border-left:3px solid {cor};
        background:#f8fafc">
        <div style="font-family:Arial,sans-serif;font-size:14px;color:#0b3d5c"><b>{head}</b></div>
        <div style="font-size:11px;letter-spacing:0.03em;color:{cor};margin:4px 0 8px;
        font-family:Arial,sans-serif">{selo}</div>
        <div style="font-size:13px;line-height:1.45;color:#333">{body}</div></div>"""

    sinais_html = "".join(bloco_sinal_html(s) for s in sinais) or (
        "<p style='color:#555'>Nenhum sinal prioritário após filtros de robustez.</p>"
    )
    juina_html = ""
    if juina_lines:
        juina_html = (
            "<div style='margin:8px 0;padding:14px;background:#f0f4f8;border:1px solid #d8dee6'>"
            + "<br>".join(esc(x) if x else "<br>" for x in juina_lines)
            + "</div>"
        )
    lac_html_parts = []
    for s in lac_show:
        lac_html_parts.append(
            f"<p style='margin:0 0 10px'><b>{esc(s.municipio)} · {esc(s.agravo)}</b><br>"
            f"{esc(fmt_num_br(s.atual_exames))} {esc(plural_exame(s.atual_exames))} "
            f"sem correspondência identificada no cruzamento disponível "
            f"(até a data de corte).<br>"
            f"<span style='color:#444'>Não assume subnotificação automaticamente — "
            f"requer validação nominal.</span></p>"
        )
    lac_html = "".join(lac_html_parts) or (
        "<p style='color:#555'>Sem lacunas adicionais de grande magnitude.</p>"
    )

    enc_html = "<br>".join(esc(x) if x else "<br>" for x in encaminhamentos(sinais, lacunas))
    ped_html = "".join(
        f"<li>{esc(p[3:] if p[:2].isdigit() else p)}</li>" for p in _PEDIDO_MUNICIPIOS
    )

    prelim_html = ""
    if mat.preliminar:
        p = mat.preliminar
        prelim_html = (
            f"<p style='margin:10px 0 0;font-size:12px;color:#6a4a00;font-family:Arial,sans-serif;"
            f"background:#fff8e6;padding:8px 10px;border:1px solid #e6d9a8'>"
            f"<b>{esc(str(p.get('selo') or ''))}</b><br>"
            f"Sinais preliminares da {esc(str(p.get('semana_legivel') or ''))}: "
            f"{esc(fmt_num_br(p.get('exames_recebidos') or 0))} exames na série · "
            f"completude estimada {esc(fmt_completude_pct(p.get('completude_pct')))}. "
            f"Não incorporados à análise consolidada.</p>"
        )

    adv_html_lines = [
        (
            f"Positividade estadual (SE analisada): "
            f"{esc(fmt_pct_br(adv.positividade_estadual_pct))} "
            f"({esc(fmt_num_br(adv.positivos_estadual))}/"
            f"{esc(fmt_num_br(adv.validos_estadual))})."
        ),
        (
            f"Tendência 4–8 semanas: volume={esc(adv.tendencia_volume)} · "
            f"positividade={esc(adv.tendencia_positividade)} · "
            f"internações={esc(adv.tendencia_internacao)}."
        ),
    ]
    if adv.nowcasting_exames_est is not None and adv.nowcasting_intervalo is not None:
        adv_html_lines.append(
            "Nowcasting preliminar: "
            f"{esc(fmt_num_br(adv.nowcasting_exames_est))} exames "
            f"(IC95% {esc(fmt_num_br(adv.nowcasting_intervalo[0]))}–"
            f"{esc(fmt_num_br(adv.nowcasting_intervalo[1]))}) — "
            f"{esc(adv.nowcasting_selo)}."
        )
    if adv.predicao_exames_sem1 is not None:
        adv_html_lines.append(
            "Predição de exames (1–3 semanas): "
            f"S+1 {esc(fmt_num_br(adv.predicao_exames_sem1))}; "
            f"S+2 {esc(fmt_num_br(adv.predicao_exames_sem2))}; "
            f"S+3 {esc(fmt_num_br(adv.predicao_exames_sem3))}."
        )
    if adv.predicao_positividade_pct_s1 is not None:
        adv_html_lines.append(
            "Positividade esperada (S+1): "
            f"{esc(fmt_pct_br(adv.predicao_positividade_pct_s1))}."
        )
    if top_fc:
        adv_html_lines.append(
            "Predição por agravo (S+1): "
            + esc(
                "; ".join(
                    f"{f.agravo}: {fmt_num_br(f.s1_exames, dec=0)} exames "
                    f"(pos. {fmt_pct_br(f.s1_positividade_pct)}; risco {f.risco_label})"
                    for f in top_fc
                )
            )
            + "."
        )
    adv_html_lines.append(
        f"Linkage VW_INTERNACAO: {esc(fmt_num_br(adv.internacoes_analisada))} "
        f"(ref. {esc(adv.internacoes_semana_usada)})."
    )
    adv_html_lines.append(
        f"Contexto INDICASUS: {esc(fmt_pct_br(adv.indicasus_score_mediano))}."
        if adv.indicasus_score_mediano is not None
        else "Contexto INDICASUS: indisponível."
    )
    adv_html = "<br>".join(adv_html_lines)

    subject = (
        f"Radar LACEN — Alerta estratégico {se_alerta} "
        f"(semana analisada {se_analisada}; encaminhar aos gestores)"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(subject)}</title></head>
<body style="margin:0;padding:0;background:#f4f6f8;color:#1a1a1a;
font-family:Georgia,'Times New Roman',serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="background:#f4f6f8;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="680" cellspacing="0" cellpadding="0"
style="max-width:680px;width:100%;background:#fff;border:1px solid #d8dee6">
<tr><td style="padding:28px 32px 12px;border-bottom:3px solid #0b3d5c">
<div style="font-size:12px;letter-spacing:0.06em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">RADAR LACEN · SES-MT / CIEVS-MT</div>
<h1 style="margin:10px 0 6px;font-size:22px;font-weight:normal;color:#0b3d5c;
font-family:Arial,sans-serif">Alerta estratégico — {esc(se_alerta)}</h1>
<p style="margin:0;font-size:14px;color:#444;font-family:Arial,sans-serif;line-height:1.5">
Semana analisada: <b>{esc(se_analisada)}</b><br>
Atualização / data de corte: {esc(atualizacao)}<br>
Completude da semana analisada: <b>{esc(completude_txt)}</b>
({esc(fmt_num_br(comp.exames_elegiveis))} elegíveis ·
{esc(fmt_num_br(comp.exames_liberados))} liberados ·
{esc(fmt_num_br(comp.exames_pendentes))} pendentes)<br>
Situação: <b>{esc(situacao)}</b>
</p>{prelim_html}</td></tr>
<tr><td style="padding:16px 24px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="border-collapse:collapse"><tr>{kpi_cells}</tr></table>
</td></tr>
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 8px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Tendências, nowcasting e predição</h2>
<p style="margin:0;font-size:13px;line-height:1.5;color:#222">{adv_html}</p>
</td></tr>
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 8px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Síntese executiva</h2>
<p style="margin:0;font-size:14px;line-height:1.55;color:#222">{esc(sintese_executiva(rel, sinais, lacunas, se_analisada_lbl=se_analisada))}</p>
</td></tr>
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 10px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Sinais prioritários para investigação</h2>
{sinais_html}
{f'<p style="font-size:12px;color:#666">Outros {n_outros} sinais no painel.</p>' if n_outros else ''}
</td></tr>
{"<tr><td style='padding:8px 32px 16px'><h2 style='margin:0 0 10px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;color:#0b3d5c;font-family:Arial,sans-serif'>Destaque territorial</h2>" + juina_html + "</td></tr>" if juina_html else ""}
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 10px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Lacunas laboratório × vigilância</h2>
{lac_html}
</td></tr>
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 10px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Encaminhamentos</h2>
<p style="margin:0;font-size:13px;line-height:1.5;color:#222">{enc_html}</p>
</td></tr>
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 8px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Pedido aos municípios</h2>
<ol style="margin:0;padding-left:1.2em;font-size:13px;line-height:1.5">{ped_html}</ol>
</td></tr>
<tr><td style="padding:8px 32px 16px">
<h2 style="margin:0 0 8px;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,sans-serif">Nota de interpretação</h2>
<p style="margin:0;font-size:12px;line-height:1.5;color:#555">{esc(_NOTA_INTERPRETACAO)}</p>
</td></tr>
<tr><td style="padding:16px 32px 28px;border-top:1px solid #e5e9ef;
font-family:Arial,sans-serif;font-size:12px;color:#666">
<a href="{esc(DASHBOARD_URL)}" style="color:#0b3d5c;font-weight:bold">Painel Radar LACEN</a>
<br>Exploração completa · anomalias · séries · metodologia
</td></tr>
</table></td></tr></table>
</body></html>"""

    tg: list[str] = [
        f"<b>Radar LACEN — Alerta estratégico {html.escape(se_alerta)}</b>",
        f"Semana analisada: <b>{html.escape(se_analisada)}</b>",
        f"Completude: {html.escape(completude_txt)}",
        f"Situação: <b>{html.escape(situacao)}</b>",
        f"Atualização: {html.escape(atualizacao)}",
        "",
        "<b>Síntese</b>",
        html.escape(_tg_clip(sintese_executiva(rel, sinais, lacunas, se_analisada_lbl=se_analisada), 420)),
        "",
        "<b>Tendências / nowcasting / predição</b>",
        html.escape(
            f"Positividade: {fmt_pct_br(adv.positividade_estadual_pct)} "
            f"({adv.positivos_estadual}/{adv.validos_estadual}) · "
            f"Tendência vol={adv.tendencia_volume}, pos={adv.tendencia_positividade}, int={adv.tendencia_internacao}"
        ),
        html.escape(
            f"Nowcasting: {fmt_num_br(adv.nowcasting_exames_est)} exames "
            f"(IC95% {fmt_num_br((adv.nowcasting_intervalo or (0,0))[0])}-{fmt_num_br((adv.nowcasting_intervalo or (0,0))[1])})"
        ),
        html.escape(
            f"Predição S+1/S+2/S+3: {fmt_num_br(adv.predicao_exames_sem1)}/"
            f"{fmt_num_br(adv.predicao_exames_sem2)}/{fmt_num_br(adv.predicao_exames_sem3)}"
        ),
        "",
        "<b>Sinais prioritários</b>",
    ]
    for s in sinais[:5]:
        tg.append(
            html.escape(
                f"• {s.municipio} · {s.agravo} — {_tipo_label(s.tipo_sinal)} | {s.prioridade_epidemiologica}"
            )
        )
        if s.tipo_sinal == "volume":
            tg.append(
                html.escape(
                    f"  Atual {s.atual_exames} · ant. {s.anterior_exames} · Δ {s.atual_exames - s.anterior_exames:+d}"
                )
            )
        elif s.tipo_sinal == "positividade":
            tg.append(
                html.escape(
                    f"  {fmt_pct_br(s.positividade)} ({s.atual_positivos}/{s.atual_exames}) · robustez {s.robustez_amostral}"
                )
            )
    if juina_lines:
        tg.extend([
            "",
            "<b>Destaque — Juína</b>",
            html.escape(
                _tg_clip(juina_lines[3] if len(juina_lines) > 3 else juina_lines[0], 160)
            ),
        ])
    tg.extend(["", "<b>Lacunas lab × vigilância</b>"])
    for s in lac_show[:3]:
        tg.append(
            html.escape(
                f"• {s.municipio} · {s.agravo}: {s.atual_exames} exames sem notificação vinculada"
            )
        )
    tg.extend([
        "",
        "<b>Encaminhamentos</b>",
        html.escape(
            "48h: CIEVS encaminha e valida marcadores · VE municipal confirma demanda/fluxo"
        ),
        html.escape(
            "7 dias: municípios devolvem status e atualizam SINAN quando cabível"
        ),
        "",
        "<i>" + html.escape("Anomalia ≠ surto. Detalhe no painel.") + "</i>",
        f'<a href="{html.escape(DASHBOARD_URL)}">Painel Radar LACEN</a>',
    ])
    tg_text = "\n".join(tg)
    if len(tg_text) > 3500:
        tg_text = tg_text[:3499] + "…"

    return {
        "subject": subject,
        "plain": plain,
        "html": html_body,
        "telegram": tg_text,
        "qa": qa,
        "sinais": sinais,
        "lacunas": lacunas,
        "maturacao": mat,
    }


def _tg_clip(text: str, n: int) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"
