# -*- coding: utf-8 -*-
"""Gera CSVs territoriais sem pandas (fallback). Usa integrated_weekly_surveillance.csv."""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path


def to_float(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def norm_mun(x: object) -> str:
    return str(x or "").strip().upper()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"[OK] {path.name}: {len(rows)} linhas")


def load_municipal_universe(outdir: Path) -> dict[str, dict]:
    """municipio -> {populacao, indice_vulnerabilidade}."""
    universe: dict[str, dict] = {}
    mm = outdir / "municipal_master.csv"
    if mm.exists():
        with mm.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                mun = norm_mun(row.get("municipio"))
                if not mun:
                    continue
                universe[mun] = {
                    "populacao": to_float(row.get("populacao"), math.nan),
                    "indice_vulnerabilidade": to_float(row.get("indice_vulnerabilidade"), 0.0),
                }
    pop = outdir / "populacao_municipio.csv"
    if pop.exists():
        latest: dict[str, tuple[float, float]] = {}
        with pop.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                mun = norm_mun(row.get("municipio"))
                if not mun:
                    continue
                ano = to_float(row.get("ano"), 0)
                populacao = to_float(row.get("populacao"), math.nan)
                prev = latest.get(mun)
                if prev is None or ano >= prev[0]:
                    latest[mun] = (ano, populacao)
        for mun, (_ano, populacao) in latest.items():
            if mun not in universe:
                universe[mun] = {"populacao": populacao, "indice_vulnerabilidade": 0.0}
            elif math.isnan(universe[mun]["populacao"]):
                universe[mun]["populacao"] = populacao
    return universe


def main():
    outdir = Path("saida_pipeline")
    src = outdir / "integrated_weekly_surveillance.csv"
    if not src.exists():
        raise SystemExit(f"Arquivo não encontrado: {src}")

    all_rows: list[dict] = []
    week_keys: set[tuple[int, int]] = set()

    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mun = norm_mun(row.get("municipio"))
            tgt = (row.get("target") or "").strip()
            if not mun or not tgt:
                continue
            ey = int(to_float(row.get("epi_year"), 0))
            ew = int(to_float(row.get("epi_week"), 0))
            week_keys.add((ey, ew))
            risco = min(10.0, max(0.0, to_float(row.get("risco_composto"))))
            all_rows.append({
                "municipio": mun,
                "target": tgt,
                "epi_year": ey,
                "epi_week": ew,
                "tests": to_float(row.get("tests")),
                "positives": to_float(row.get("positives")),
                "notificacoes": to_float(row.get("notificacoes")),
                "populacao": to_float(row.get("populacao"), math.nan),
                "risco_composto": risco,
                "positividade": to_float(row.get("positividade"), math.nan),
                "solicitacoes_100k": to_float(row.get("solicitacoes_100k"), math.nan),
                "nivel_risco": (row.get("nivel_risco") or "").strip(),
            })

    recent_weeks = set(sorted(week_keys)[-8:])
    recent_rows = [r for r in all_rows if (r["epi_year"], r["epi_week"]) in recent_weeks]

    # mun x target na janela recente
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in recent_rows:
        buckets[(r["municipio"], r["target"])].append(r)

    mun_target = []
    for (mun, tgt), rows in buckets.items():
        tests = sum(r["tests"] for r in rows)
        positives = sum(r["positives"] for r in rows)
        notif = sum(r["notificacoes"] for r in rows)
        pops = [r["populacao"] for r in rows if not math.isnan(r["populacao"])]
        riscos = [r["risco_composto"] for r in rows]
        pos_rates = [r["positividade"] for r in rows if not math.isnan(r["positividade"])]
        sol = [r["solicitacoes_100k"] for r in rows if not math.isnan(r["solicitacoes_100k"])]
        niveis = [r["nivel_risco"] for r in rows if r["nivel_risco"]]
        pos_media = (positives / tests) if tests > 0 else (sum(pos_rates) / len(pos_rates) if pos_rates else math.nan)
        taxa = (tests / notif) if notif > 0 else (math.nan if tests > 0 else 0.0)
        silencio = tests == 0 and notif > 0
        baixo = notif >= 3 and tests < max(1.0, notif * 0.2)
        mun_target.append({
            "municipio": mun,
            "target": tgt,
            "semanas": len(rows),
            "tests": tests,
            "positives": positives,
            "notificacoes": notif,
            "populacao": max(pops) if pops else "",
            "risco_medio": sum(riscos) / len(riscos) if riscos else 0.0,
            "risco_max": max(riscos) if riscos else 0.0,
            "positividade_media": pos_media if not math.isnan(pos_media) else "",
            "solicitacoes_100k_media": sum(sol) / len(sol) if sol else "",
            "nivel_risco_max": max(niveis) if niveis else "",
            "taxa_utilizacao": taxa if not math.isnan(taxa) else "",
            "silencio_laboratorial": silencio,
            "baixo_uso_lacen": baixo,
            "exames_por_100_notificacoes": (tests / notif * 100.0) if notif > 0 else "",
            "exames_por_100k": (tests / max(pops) * 100000.0) if pops and max(pops) > 0 else "",
            "classificacao_uso": (
                "silencio" if silencio else
                "baixo" if baixo else
                ("adequado_ou_alto" if (not math.isnan(taxa) and taxa >= 1.0) else "intermediario")
            ),
        })

    by_mun: dict[str, list[dict]] = defaultdict(list)
    for r in mun_target:
        by_mun[r["municipio"]].append(r)

    risco_rows = []
    for mun, items in by_mun.items():
        alvos = len(items)
        tests = sum(i["tests"] for i in items)
        positives = sum(i["positives"] for i in items)
        notif = sum(i["notificacoes"] for i in items)
        pops = [to_float(i["populacao"], math.nan) for i in items if i["populacao"] != ""]
        risco_medio = min(10.0, sum(i["risco_medio"] for i in items) / alvos) if alvos else 0.0
        risco_max = min(10.0, max(i["risco_max"] for i in items)) if items else 0.0
        pos_vals = [to_float(i["positividade_media"], math.nan) for i in items if i["positividade_media"] != ""]
        alvos_alto = sum(1 for i in items if i["nivel_risco_max"] == "alto_alerta")
        alvos_alerta = sum(1 for i in items if i["nivel_risco_max"] in {"alerta", "alto_alerta"})
        score = risco_max * 0.55 + risco_medio * 0.25 + ((alvos_alerta / alvos) if alvos else 0.0) * 0.20
        if score < 1:
            faixa = "habitual"
        elif score < 2:
            faixa = "atencao"
        elif score < 3:
            faixa = "alerta"
        else:
            faixa = "alto_alerta"
        risco_rows.append({
            "municipio": mun,
            "alvos_monitorados": alvos,
            "tests_8sem": tests,
            "positives_8sem": positives,
            "notificacoes_8sem": notif,
            "populacao": max(pops) if pops else "",
            "risco_medio": risco_medio,
            "risco_max": risco_max,
            "positividade_media": (sum(pos_vals) / len(pos_vals)) if pos_vals else "",
            "alvos_alto_alerta": alvos_alto,
            "alvos_alerta": alvos_alerta,
            "score_risco_territorial": score,
            "faixa_risco": faixa,
        })
    risco_rows.sort(key=lambda r: (r["score_risco_territorial"], r["risco_max"]), reverse=True)

    # Atividade recente/histórica por município
    recent_by_mun: dict[str, dict] = defaultdict(lambda: {"tests": 0.0, "notif": 0.0, "positives": 0.0, "alvos": set()})
    hist_by_mun: dict[str, dict] = defaultdict(lambda: {"tests": 0.0, "notif": 0.0, "semanas": 0})
    for r in recent_rows:
        d = recent_by_mun[r["municipio"]]
        d["tests"] += r["tests"]
        d["notif"] += r["notificacoes"]
        d["positives"] += r["positives"]
        d["alvos"].add(r["target"])
    for r in all_rows:
        d = hist_by_mun[r["municipio"]]
        d["tests"] += r["tests"]
        d["notif"] += r["notificacoes"]
        d["semanas"] += 1

    universe = load_municipal_universe(outdir)
    if not universe:
        for mun in hist_by_mun:
            universe[mun] = {"populacao": math.nan, "indice_vulnerabilidade": 0.0}

    silenciosos = []
    for mun, meta in universe.items():
        tests_recent = recent_by_mun[mun]["tests"]
        notif_recent = recent_by_mun[mun]["notif"]
        positives_recent = recent_by_mun[mun]["positives"]
        tests_hist = hist_by_mun[mun]["tests"]
        pop = meta["populacao"] if not math.isnan(meta["populacao"]) else 0.0
        vuln = meta["indice_vulnerabilidade"]
        sem_envio = tests_recent <= 0
        teve_hist = tests_hist > 0
        notif_sem_exame = notif_recent > 0

        if sem_envio and (notif_sem_exame or (teve_hist and pop >= 5000 and vuln >= 0.5)):
            classe = "silencio_critico"
        elif sem_envio and (pop >= 10000 or (teve_hist and pop >= 3000)):
            classe = "silencio_provavel"
        elif sem_envio and pop >= 3000:
            classe = "silencio_moderado"
        elif notif_recent >= 3 and tests_recent < max(1.0, notif_recent * 0.2):
            classe = "baixo_uso_lacen"
        else:
            classe = ""
        if not classe:
            continue
        score = (
            (2.0 if sem_envio else 0.0)
            + (0.5 if (sem_envio and not teve_hist) else 0.0)
            + (2.0 if notif_sem_exame else 0.0)
            + (1.0 if pop >= 10000 else 0.0)
            + (0.5 if pop >= 5000 else 0.0)
            + (1.0 if vuln >= 0.5 else 0.0)
            + (0.5 if vuln >= 1.0 else 0.0)
        )
        silenciosos.append({
            "municipio": mun,
            "target": "",
            "tests_recent": tests_recent,
            "notif_recent": notif_recent,
            "positives_recent": positives_recent,
            "tests_hist": tests_hist,
            "populacao": pop if pop else "",
            "indice_vulnerabilidade": vuln,
            "tipo_sinal": classe,
            "classificacao_silencio": classe,
            "score_silencio": score,
        })

    for r in mun_target:
        if not (r["silencio_laboratorial"] or r["baixo_uso_lacen"]):
            continue
        tipo = "silencio_laboratorial" if r["silencio_laboratorial"] else "baixo_uso_lacen"
        silenciosos.append({
            "municipio": r["municipio"],
            "target": r["target"],
            "tests_recent": r["tests"],
            "notif_recent": r["notificacoes"],
            "positives_recent": r["positives"],
            "tests_hist": "",
            "populacao": r["populacao"],
            "indice_vulnerabilidade": "",
            "tipo_sinal": tipo,
            "classificacao_silencio": tipo,
            "score_silencio": 3.0 if r["silencio_laboratorial"] else 2.0,
        })

    silenciosos.sort(key=lambda r: (-r["score_silencio"], -to_float(r["notif_recent"]), to_float(r["tests_recent"]), r["municipio"]))

    util = sorted(mun_target, key=lambda r: (
        0 if r["taxa_utilizacao"] == "" else 1,
        to_float(r["taxa_utilizacao"], 9999),
        -r["notificacoes"],
    ))

    write_csv(
        outdir / "municipios_em_risco.csv",
        risco_rows,
        [
            "municipio", "alvos_monitorados", "tests_8sem", "positives_8sem", "notificacoes_8sem",
            "populacao", "risco_medio", "risco_max", "positividade_media", "alvos_alto_alerta",
            "alvos_alerta", "score_risco_territorial", "faixa_risco",
        ],
    )
    write_csv(
        outdir / "municipios_silenciosos.csv",
        silenciosos,
        [
            "municipio", "target", "tests_recent", "notif_recent", "positives_recent", "tests_hist",
            "populacao", "indice_vulnerabilidade", "tipo_sinal", "classificacao_silencio", "score_silencio",
        ],
    )
    write_csv(
        outdir / "taxa_utilizacao_lacen.csv",
        util,
        [
            "municipio", "target", "semanas", "tests", "positives", "notificacoes", "populacao",
            "positividade_media", "taxa_utilizacao", "exames_por_100_notificacoes", "exames_por_100k",
            "silencio_laboratorial", "baixo_uso_lacen", "classificacao_uso",
        ],
    )
    print("[FINAL] Inteligência territorial gerada (stdlib).")


if __name__ == "__main__":
    main()
