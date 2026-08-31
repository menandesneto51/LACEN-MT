#!/usr/bin/env python3
"""
Cartões de risco de evento — Radar LACEN / CIEVS.

Probabilidade × impacto × confiança → veredito operacional e ações
por destinatário. Não declara surto/epidemia automaticamente.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any, Sequence

from lacen_briefing_epi import (
    OUTDIR_DEFAULT,
    _familia_agravo,
    _fmt_taxa_100k,
    _is_hepatite,
    _is_igg,
    _is_tb,
    _norm_mun,
    _num,
    _pct,
    frase_taxa_positivos_100k,
)

RADAR_RISCO_CSV = "radar_eventos_risco.csv"

_NIVEL_ORD = {"baixo": 0, "médio": 1, "medio": 1, "alto": 2}
_ORD_NIVEL = {0: "baixo", 1: "médio", 2: "alto"}


def _clip(text: str, n: int = 180) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _nivel_from_score(score: float, *, hi: float = 2.5, mid: float = 1.2) -> str:
    if score >= hi:
        return "alto"
    if score >= mid:
        return "médio"
    return "baixo"


def _bump(nivel: str, steps: int = 1) -> str:
    i = _NIVEL_ORD.get((nivel or "baixo").casefold(), 0)
    return _ORD_NIVEL[max(0, min(2, i + steps))]


def _lacen_pertinente(target: str, familia: str) -> bool:
    """LACEN só entra se o agravo tipicamente exige apoio laboratorial."""
    t = (target or "").casefold()
    f = (familia or "").casefold()
    if _is_igg(target):
        return False
    keys = (
        "hepatite", "hbv", "hcv", "tubercul", "meningite", "hantavir",
        "leptospir", "oropouche", "chikung", "zika", "dengue", "malaria",
        "leishmani", "sifilis", "sífilis",
    )
    blob = f"{t} {f}"
    return any(k in blob for k in keys)


def _sih_index(
    cruzamento_sih_sia: dict[str, Any] | None,
) -> dict[tuple[str, str], float]:
    """(familia, municipio_norm) -> n internações."""
    out: dict[tuple[str, str], float] = {}
    for row in (cruzamento_sih_sia or {}).get("top_mun") or []:
        fam = _familia_agravo("", str(row.get("cid_familia") or ""))
        mun = _norm_mun(row.get("municipio"))
        n = _num(row.get("n"), 0) or 0
        if fam and mun and n > 0:
            key = (fam, mun)
            out[key] = max(out.get(key, 0.0), float(n))
    return out


def _gal_sinan_index(
    gal_sinan: Sequence[dict[str, Any]] | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for g in gal_sinan or []:
        fam = str(g.get("familia") or _familia_agravo(str(g.get("target") or "")))
        mun = _norm_mun(g.get("municipio"))
        if not fam or not mun:
            continue
        out[(fam.casefold(), mun)] = dict(g)
    return out


def _cluster_index(
    vizinhos: Sequence[dict[str, Any]] | None,
) -> dict[tuple[str, str], int]:
    """(target, municipio) -> n pares em que o mun aparece."""
    counts: dict[tuple[str, str], int] = {}
    for v in vizinhos or []:
        tgt = str(v.get("target") or "").strip()
        for key in ("municipio", "vizinho"):
            mun = _norm_mun(v.get(key))
            if tgt and mun:
                k = (tgt, mun)
                counts[k] = counts.get(k, 0) + 1
    return counts


def _candidato_from_localidade(loc: dict[str, Any]) -> dict[str, Any]:
    return {
        "origem": "localidade",
        "target": str(loc.get("target") or ""),
        "municipio": _norm_mun(loc.get("municipio")),
        "exames": float(loc.get("exames") or 0),
        "positivos": float(loc.get("positivos") or 0),
        "notificacoes": float(loc.get("notificacoes") or 0),
        "positividade": loc.get("positividade"),
        "delta_pct": loc.get("delta_pct"),
        "tendencia": loc.get("tendencia") or "→",
        "taxa_positivos_100k": loc.get("taxa_positivos_100k"),
        "taxa_exames_100k": loc.get("taxa_exames_100k"),
        "taxa_notif_100k": loc.get("taxa_notif_100k"),
        "frase_taxa_positivos": loc.get("frase_taxa_positivos") or "",
        "caveat_igg": bool(loc.get("caveat_igg")),
        "baixa_amostra": bool(loc.get("baixa_amostra")),
        "tipo_sinal": str(loc.get("tipo_sinal") or "Observado"),
    }


def _enriquecer_candidato_com_estado(
    cand: dict[str, Any],
    solicitados: Sequence[dict[str, Any]],
    positividade: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    tgt = cand["target"]
    for src in list(solicitados) + list(positividade):
        if str(src.get("target") or "") != tgt:
            continue
        if cand.get("delta_pct") is None and src.get("delta_pct") is not None:
            cand["delta_pct"] = src.get("delta_pct")
            cand["tendencia"] = src.get("tendencia") or cand.get("tendencia")
        if cand.get("positividade") is None and src.get("positividade") is not None:
            cand["positividade"] = src.get("positividade")
        if src.get("caveat_igg"):
            cand["caveat_igg"] = True
        if src.get("baixa_amostra"):
            cand["baixa_amostra"] = True
        break
    return cand


def montar_cartao_risco(
    cand: dict[str, Any],
    *,
    clusters: dict[tuple[str, str], int],
    sih: dict[tuple[str, str], float],
    gaps: dict[tuple[str, str], dict[str, Any]],
    atraso_se: int | None = None,
    ml_banda: str | None = None,
    bortman: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tgt = str(cand.get("target") or "")
    mun = _norm_mun(cand.get("municipio"))
    fam = _familia_agravo(tgt)
    evento = f"{tgt} × {mun}" if mun else tgt

    score_p = 0.0
    score_i = 0.0
    regras: list[str] = []
    tipo = str(cand.get("tipo_sinal") or "Observado")
    zona_bortman = ""

    delta = cand.get("delta_pct")
    dlt = float(delta) if delta is not None else None
    if dlt is not None:
        if dlt >= 50:
            score_p += 2.0
            regras.append(f"Δ demanda {dlt:+.0f}% vs SE-1 (≥50%)")
        elif dlt >= 25:
            score_p += 1.2
            regras.append(f"Δ demanda {dlt:+.0f}% vs SE-1 (≥25%)")
        elif dlt >= 10:
            score_p += 0.5
            regras.append(f"Δ demanda {dlt:+.0f}% vs SE-1")

    posi = cand.get("positividade")
    if posi is not None:
        try:
            pv = float(posi)
        except (TypeError, ValueError):
            pv = None
        if pv is not None:
            if pv >= 0.25 and not cand.get("caveat_igg"):
                score_p += 1.5
                regras.append(f"positividade {_pct(pv)}")
            elif pv >= 0.12 and not cand.get("caveat_igg"):
                score_p += 0.8
                regras.append(f"positividade {_pct(pv)}")
            elif cand.get("caveat_igg") and pv >= 0.20:
                score_p += 0.3
                regras.append(f"positividade IgG {_pct(pv)} (caveat sorologia)")

    n_pos = float(cand.get("positivos") or 0)
    n_ex = float(cand.get("exames") or 0)
    if n_pos >= 10:
        score_p += 0.8
        score_i += 0.6
        regras.append(f"{int(n_pos)} positivos na SE")
    elif n_pos >= 3:
        score_p += 0.4
        regras.append(f"{int(n_pos)} positivos na SE")
    elif n_ex >= 80:
        score_i += 0.4
        regras.append(f"volume {int(n_ex)} exames (proxy impacto)")

    n_cluster = clusters.get((tgt, mun), 0)
    if n_cluster >= 2:
        score_p += 1.2
        score_i += 0.8
        regras.append(f"cluster vizinhos (n={n_cluster})")
    elif n_cluster == 1:
        score_p += 0.6
        score_i += 0.3
        regras.append("par vizinho com positivos")

    intern = sih.get((fam, mun), 0.0)
    if intern >= 20:
        score_i += 2.0
        score_p += 0.5
        regras.append(f"internações SIH n={int(intern)}")
    elif intern >= 5:
        score_i += 1.2
        score_p += 0.3
        regras.append(f"internações SIH n={int(intern)}")
    elif intern > 0:
        score_i += 0.5
        regras.append(f"internações SIH n={int(intern)}")

    gap = gaps.get((fam.casefold(), mun))
    if gap:
        flag = str(gap.get("flag") or "")
        if gap.get("gal_sem_sinan") or "gal_sem" in flag.casefold():
            score_p += 1.0
            tipo = "Derivado"
            regras.append("lacuna GAL sem notificação SINAN")
        if gap.get("sinan_sem_gal") or "sinan_sem" in flag.casefold():
            score_p += 0.7
            tipo = "Derivado"
            regras.append("lacuna SINAN sem exame GAL")

    if ml_banda and str(ml_banda).casefold() in {"alta", "alto", "crítica", "critica"}:
        score_p += 0.8
        tipo = "Predito" if tipo == "Observado" else tipo
        regras.append(f"ML banda {ml_banda}")

    # Canal endêmico Bortman (P25/P50/P75) — reforça evidência se alerta/epidemia
    # Se o candidato é só IgG/soroprevalência, não eleva para "epidemia" via Bortman.
    binfo = (bortman or {}).get((tgt, mun)) if bortman else None
    so_igg = bool(cand.get("caveat_igg")) or bool(cand.get("somente_nao_agudo"))
    if binfo and not so_igg:
        zona = str(binfo.get("zona") or "").casefold()
        zona_bortman = zona
        if zona == "epidemia":
            score_p += 1.5
            score_i += 0.5
            tipo = "Derivado" if tipo == "Observado" else tipo
            razao = binfo.get("razao_vs_p50")
            extra = f" (razão vs P50={razao})" if razao not in (None, "") else ""
            regras.append(f"canal endêmico Bortman: zona epidemia{extra}")
        elif zona == "alerta":
            score_p += 1.0
            tipo = "Derivado" if tipo == "Observado" else tipo
            razao = binfo.get("razao_vs_p50")
            extra = f" (razão vs P50={razao})" if razao not in (None, "") else ""
            regras.append(f"canal endêmico Bortman: zona alerta{extra}")
    elif binfo and so_igg:
        zona_bortman = str(binfo.get("zona") or "")
        regras.append(
            "Bortman ignorado para score: marcador não agudo (regras_agravo_gal)"
        )

    if cand.get("baixa_amostra"):
        score_p = max(0.0, score_p - 0.6)
        regras.append("baixa amostra — cautela")

    if cand.get("caveat_igg"):
        score_p = max(0.0, score_p - 0.8)
        regras.append("IgG/sorologia ≠ surto agudo")

    # Dispersão territorial: TB/hepatite com cluster elevam impacto
    if n_cluster and (_is_tb(tgt) or _is_hepatite(tgt)):
        score_i += 0.5

    probabilidade = _nivel_from_score(score_p)
    impacto = _nivel_from_score(score_i, hi=2.0, mid=0.9)

    atraso_txt = ""
    if atraso_se is not None and int(atraso_se) > 0:
        atraso_txt = f" · atraso {int(atraso_se)} SE"
    confianca = f"{tipo}{atraso_txt}"

    # Veredito operacional (nunca declara surto)
    if probabilidade == "alto" and impacto in {"médio", "alto"}:
        veredito = "investigar"
    elif probabilidade == "alto" or (
        probabilidade == "médio" and impacto == "alto"
    ):
        veredito = "investigar"
    elif probabilidade == "médio" or impacto == "médio":
        veredito = "monitorar"
    else:
        veredito = "sinal lab — não declarar surto"

    if cand.get("caveat_igg") and veredito == "investigar":
        veredito = "monitorar"

    taxa_frase = cand.get("frase_taxa_positivos") or frase_taxa_positivos_100k(
        cand.get("taxa_positivos_100k")
    )
    taxa_notif = cand.get("taxa_notif_100k")
    taxa_notif_s = (
        f"{_fmt_taxa_100k(taxa_notif)} notif./100 mil"
        if taxa_notif is not None
        else ""
    )

    acoes: dict[str, str] = {}
    nome_evt = f"{tgt} em {mun}" if mun else tgt
    if veredito == "investigar":
        acoes["CIEVS"] = _clip(
            f"Priorizar investigação de {nome_evt}: cruzar lab × notificação, "
            f"avaliar definição de caso e comunicação com VE municipal."
        )
        acoes["VE municipal"] = _clip(
            f"Investigar casos/contatos de {tgt} em {mun}; "
            f"verificar oportunidade de notificação e busca ativa."
        )
        acoes["área técnica"] = _clip(
            f"Validar critérios clínico-laboratoriais de {tgt}; "
            f"orientar rede sobre definição de caso."
        )
        if n_cluster:
            acoes["vizinhos"] = _clip(
                f"Alerta coordenado aos municípios vizinhos com sinal de {tgt}."
            )
    elif veredito == "monitorar":
        acoes["CIEVS"] = _clip(
            f"Manter {nome_evt} sob monitoramento na sala de situação; "
            f"revisar na próxima SE."
        )
        acoes["VE municipal"] = _clip(
            f"Acompanhar tendência de {tgt} em {mun}; reforçar notificação "
            f"oportuna se houver suspeitos."
        )
        acoes["área técnica"] = _clip(
            f"Acompanhar positividade/demanda de {tgt}; alertar se persistir alta."
        )
        if n_cluster:
            acoes["vizinhos"] = _clip(
                f"Informar vizinhos sobre co-sinal de {tgt} (monitoramento)."
            )
    else:
        acoes["CIEVS"] = _clip(
            f"Registrar sinal lab de {nome_evt} sem declaração de surto; "
            f"aguardar convergência com notificação/clínica."
        )
        acoes["VE municipal"] = _clip(
            f"Não declarar surto por sinal lab isolado de {tgt}; "
            f"investigar se houver casos clínicos."
        )

    if _lacen_pertinente(tgt, fam) and veredito in {"investigar", "monitorar"}:
        acoes["LACEN"] = _clip(
            f"Apoiar {tgt}: priorizar TAT/confirmação se fila impactar a VE "
            f"deste agravo; comunicar resultados críticos à VE/CIEVS."
        )

    # Canal endêmico: reforça recomendação em linguagem clara
    if zona_bortman == "epidemia":
        acoes["CIEVS"] = _clip(
            f"Canal endêmico em zona epidêmica (estatística) em {nome_evt}: "
            f"priorizar investigação (não declarar epidemia automaticamente)."
        )
        if not acoes.get("VE municipal"):
            acoes["VE municipal"] = _clip(
                f"Investigar {tgt} em {mun}: exames positivos acima do esperado "
                f"para esta semana nos últimos anos (marcador de alerta)."
            )
    elif zona_bortman == "alerta":
        tip = (
            f"Canal endêmico em zona de alerta para {nome_evt}: "
            f"reforçar monitoramento e cruzar com notificação."
        )
        if veredito == "investigar":
            acoes["CIEVS"] = _clip(
                f"{acoes.get('CIEVS', '')} {tip}".strip()
            )
        else:
            acoes["CIEVS"] = _clip(tip)

    score_rank = (
        _NIVEL_ORD.get(probabilidade, 0) * 3
        + _NIVEL_ORD.get(impacto, 0) * 2
        + score_p
        + score_i
    )

    return {
        "se": "",
        "evento": evento,
        "agravo": tgt,
        "familia": fam,
        "municipio": mun or "—",
        "probabilidade": probabilidade,
        "impacto": impacto,
        "confianca": confianca,
        "veredito": veredito,
        "tipo_sinal": tipo,
        "score": round(score_rank, 3),
        "regras": "; ".join(regras) if regras else "sem regra disparada",
        "taxa_positivos_100k": cand.get("taxa_positivos_100k"),
        "taxa_exames_100k": cand.get("taxa_exames_100k"),
        "taxa_notif_100k": taxa_notif,
        "frase_taxa_positivos": taxa_frase,
        "frase_taxa_notif": taxa_notif_s,
        "exames": int(n_ex),
        "positivos": int(n_pos),
        "positividade": posi,
        "delta_pct": dlt,
        "internacoes_sih": intern if intern else "",
        "zona_bortman": zona_bortman,
        "acao_cievs": acoes.get("CIEVS", ""),
        "acao_ve_mun": acoes.get("VE municipal", ""),
        "acao_area_tecnica": acoes.get("área técnica", ""),
        "acao_vizinhos": acoes.get("vizinhos", ""),
        "acao_lacen": acoes.get("LACEN", ""),
        "acoes": acoes,
    }


def gerar_cartoes_risco(
    *,
    se_iso: str,
    solicitados: Sequence[dict[str, Any]] | None = None,
    positividade: Sequence[dict[str, Any]] | None = None,
    localidades: Sequence[dict[str, Any]] | None = None,
    vizinhos: Sequence[dict[str, Any]] | None = None,
    gal_sinan: Sequence[dict[str, Any]] | None = None,
    cruzamento_sih_sia: dict[str, Any] | None = None,
    atraso_se: int | None = None,
    top: int = 12,
    outdir: Path | str | None = None,
    bortman: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Gera cartões ranqueados (agravo × município) a partir do briefing."""
    sol = list(solicitados or [])
    posi = list(positividade or [])
    locs = list(localidades or [])
    clusters = _cluster_index(vizinhos)
    sih = _sih_index(cruzamento_sih_sia)
    gaps = _gal_sinan_index(gal_sinan)
    bortman_idx = bortman
    if bortman_idx is None and outdir is not None:
        try:
            from ml.canal_endemico_bortman import carregar_indice_bortman

            bortman_idx = carregar_indice_bortman(outdir, se_iso=se_iso)
        except Exception:  # noqa: BLE001
            bortman_idx = {}

    candidatos: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for loc in locs:
        c = _candidato_from_localidade(loc)
        if not c["target"] or not c["municipio"]:
            continue
        key = (c["target"], c["municipio"])
        if key in seen:
            continue
        seen.add(key)
        candidatos.append(_enriquecer_candidato_com_estado(c, sol, posi))

    # Gaps GAL×SINAN sem localidade já listada
    for g in gal_sinan or []:
        tgt = str(g.get("target") or g.get("familia") or "")
        mun = _norm_mun(g.get("municipio"))
        if not tgt or not mun:
            continue
        # Prefer target concreto; senão família
        key_tgt = str(g.get("target") or tgt)
        key = (key_tgt, mun)
        if key in seen:
            continue
        if not (g.get("gal_sem_sinan") or g.get("sinan_sem_gal")):
            continue
        seen.add(key)
        candidatos.append(
            {
                "origem": "gal_sinan",
                "target": key_tgt,
                "municipio": mun,
                "exames": float(g.get("exames") or 0),
                "positivos": float(g.get("positivos") or 0),
                "notificacoes": float(g.get("notificacoes") or 0),
                "positividade": None,
                "delta_pct": None,
                "tendencia": "→",
                "taxa_positivos_100k": None,
                "frase_taxa_positivos": "",
                "caveat_igg": _is_igg(key_tgt),
                "baixa_amostra": False,
                "tipo_sinal": "Derivado",
            }
        )

    # Clusters sem localidade
    for v in vizinhos or []:
        tgt = str(v.get("target") or "")
        for mk in ("municipio", "vizinho"):
            mun = _norm_mun(v.get(mk))
            if not tgt or not mun:
                continue
            key = (tgt, mun)
            if key in seen:
                continue
            seen.add(key)
            candidatos.append(
                _enriquecer_candidato_com_estado(
                    {
                        "origem": "cluster",
                        "target": tgt,
                        "municipio": mun,
                        "exames": 0.0,
                        "positivos": float(
                            v.get("positivos_ancora")
                            if mk == "municipio"
                            else v.get("positivos_vizinho")
                            or 0
                        ),
                        "notificacoes": 0.0,
                        "positividade": None,
                        "delta_pct": None,
                        "tendencia": "→",
                        "taxa_positivos_100k": None,
                        "frase_taxa_positivos": "",
                        "caveat_igg": _is_igg(tgt),
                        "baixa_amostra": False,
                        "tipo_sinal": "Observado",
                    },
                    sol,
                    posi,
                )
            )

    cartoes = [
        montar_cartao_risco(
            c,
            clusters=clusters,
            sih=sih,
            gaps=gaps,
            atraso_se=atraso_se,
            bortman=bortman_idx,
        )
        for c in candidatos
    ]
    for c in cartoes:
        c["se"] = se_iso
    cartoes.sort(
        key=lambda x: (
            -float(x.get("score") or 0),
            -float(x.get("positivos") or 0),
            str(x.get("evento") or ""),
        )
    )
    # Diversifica: no máx. 2 por agravo no top
    out: list[dict[str, Any]] = []
    por_agravo: dict[str, int] = {}
    for c in cartoes:
        if float(c.get("score") or 0) <= 0 and not c.get("regras"):
            continue
        ag = str(c.get("agravo") or "")
        if por_agravo.get(ag, 0) >= 2 and len(out) >= 5:
            continue
        por_agravo[ag] = por_agravo.get(ag, 0) + 1
        out.append(c)
        if len(out) >= top:
            break
    return out


def persistir_cartoes_risco(
    cartoes: Sequence[dict[str, Any]],
    outdir: Path | str = OUTDIR_DEFAULT,
) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / RADAR_RISCO_CSV
    fields = [
        "se",
        "evento",
        "agravo",
        "familia",
        "municipio",
        "probabilidade",
        "impacto",
        "confianca",
        "veredito",
        "tipo_sinal",
        "score",
        "regras",
        "exames",
        "positivos",
        "positividade",
        "delta_pct",
        "taxa_exames_100k",
        "taxa_positivos_100k",
        "taxa_notif_100k",
        "frase_taxa_positivos",
        "internacoes_sih",
        "zona_bortman",
        "acao_cievs",
        "acao_ve_mun",
        "acao_area_tecnica",
        "acao_vizinhos",
        "acao_lacen",
    ]

    def _cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            if math.isnan(v):
                return ""
            return f"{v:.4f}".rstrip("0").rstrip(".")
        if isinstance(v, dict):
            return ""
        return str(v)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in cartoes:
            w.writerow({k: _cell(row.get(k)) for k in fields})
    return path


def cartoes_para_relatorio(
    cartoes: Sequence[dict[str, Any]], *, top: int = 5
) -> list[dict[str, str]]:
    """Payload stringificado para Telegram / e-mail."""
    out: list[dict[str, str]] = []
    for c in list(cartoes)[:top]:
        taxa = str(c.get("frase_taxa_positivos") or "")
        if not taxa and c.get("taxa_positivos_100k") is not None:
            taxa = frase_taxa_positivos_100k(c.get("taxa_positivos_100k"))
        notif = str(c.get("frase_taxa_notif") or "")
        acoes = c.get("acoes") if isinstance(c.get("acoes"), dict) else {}
        if not acoes:
            acoes = {
                k.replace("acao_", "").replace("_", " "): c.get(k, "")
                for k in (
                    "acao_cievs",
                    "acao_ve_mun",
                    "acao_area_tecnica",
                    "acao_vizinhos",
                    "acao_lacen",
                )
                if c.get(k)
            }
        out.append(
            {
                "evento": str(c.get("evento") or "—"),
                "agravo": str(c.get("agravo") or "—"),
                "municipio": str(c.get("municipio") or "—"),
                "probabilidade": str(c.get("probabilidade") or "—"),
                "impacto": str(c.get("impacto") or "—"),
                "confianca": str(c.get("confianca") or "Observado"),
                "veredito": str(c.get("veredito") or "—"),
                "regras": str(c.get("regras") or ""),
                "taxa_positivos": taxa,
                "taxa_notif": notif,
                "taxa_exames_100k": (
                    _fmt_taxa_100k(c.get("taxa_exames_100k"))
                    if c.get("taxa_exames_100k") is not None
                    else "—"
                ),
                "taxa_positivos_100k": (
                    _fmt_taxa_100k(c.get("taxa_positivos_100k"))
                    if c.get("taxa_positivos_100k") is not None
                    else "—"
                ),
                "acao_cievs": str(acoes.get("CIEVS") or c.get("acao_cievs") or ""),
                "acao_ve_mun": str(
                    acoes.get("VE municipal") or c.get("acao_ve_mun") or ""
                ),
                "acao_area_tecnica": str(
                    acoes.get("área técnica") or c.get("acao_area_tecnica") or ""
                ),
                "acao_vizinhos": str(
                    acoes.get("vizinhos") or c.get("acao_vizinhos") or ""
                ),
                "acao_lacen": str(acoes.get("LACEN") or c.get("acao_lacen") or ""),
                "tipo_sinal": str(c.get("tipo_sinal") or "Observado"),
                "zona_bortman": str(c.get("zona_bortman") or ""),
            }
        )
    return out
