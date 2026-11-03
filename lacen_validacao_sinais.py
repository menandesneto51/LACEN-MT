# -*- coding: utf-8 -*-
"""Portão de validação de sinais — só publica no alerta o que é validado e relevante.

Cada sinal candidato (``SignalFact``) passa por critérios explícitos e recebe um
status:

* ``VALIDADO``       → entra no Alerta Estratégico;
* ``EM_OBSERVACAO``  → fica no painel/triagem (falta evidência, não é descartado);
* ``DESCARTADO``     → não é sinal epidemiológico (dado ruim ou alvo não elegível).

Critérios (na ordem):

D1 Qualidade da carga  — volume estadual da SE ≥ 50% da mediana das 8 SE anteriores.
D2 Alvo elegível       — classe do alvo (``conhecimento_ve/classe_alvo_alerta.csv``):
                         IgG/avidez e diagnóstico assistencial/rastreio nunca entram.
D3 Positividade válida — sinais de positividade só se a positividade estadual for
                         plausível (classificador de resultado GAL confiável).
E1 Significância       — p-valor < ``P_MAX`` (anomalias v2) ou severidade alta (v1).
E2 Magnitude           — excesso absoluto ≥ ``MIN_EXCESSO`` exames (volume) ou
                         ≥ 2 positivos (positividade).
C  Corroboração        — ao menos uma: persistência (anomalia do mesmo município ×
                         alvo × métrica na SE anterior), positivo laboratorial com
                         positividade válida, ou município vizinho com anomalia do
                         mesmo alvo na mesma SE. Agravo crônico exige persistência.

Agravo de notificação imediata com ≥ 1 positivo (positividade válida) é validado
mesmo sem E1/E2/C: o positivo isolado já é relevante.

Parâmetros por variável de ambiente: ``LACEN_VALID_P_MAX`` (0,01),
``LACEN_VALID_MIN_EXCESSO`` (5), ``LACEN_VALID_CARGA_MIN`` (0,5).
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
CLASSE_CSV = ROOT / "conhecimento_ve" / "classe_alvo_alerta.csv"

P_MAX = float(os.environ.get("LACEN_VALID_P_MAX", "0.01") or 0.01)
MIN_EXCESSO = float(os.environ.get("LACEN_VALID_MIN_EXCESSO", "5") or 5)
CARGA_MIN = float(os.environ.get("LACEN_VALID_CARGA_MIN", "0.5") or 0.5)
POS_PLAUSIVEL_MIN = 0.02  # positividade estadual mínima com n ≥ 500

VALIDADO = "VALIDADO"
EM_OBSERVACAO = "EM_OBSERVACAO"
DESCARTADO = "DESCARTADO"

CLASSES_FORA_DO_ALERTA = {"nao_agudo", "assistencial"}


@dataclass
class Validacao:
    status: str
    classe_alvo: str
    atendidos: list[str] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)
    corroboracoes: list[str] = field(default_factory=list)

    @property
    def publicar(self) -> bool:
        return self.status == VALIDADO

    def resumo(self) -> str:
        if self.publicar:
            base = "; ".join(self.atendidos)
            if self.corroboracoes:
                base += " · corroborado por " + ", ".join(self.corroboracoes)
            return base
        return "; ".join(self.motivos)


@dataclass
class ContextoValidacao:
    """Fatos da SE usados por todos os sinais."""

    se: tuple[int, int]
    se_anterior: tuple[int, int]
    carga_ok: bool = True
    carga_razao: float | None = None
    positividade_valida: bool = True
    positividade_estadual: tuple[int, int] | None = None  # (positivos, exames)
    # (municipio_key, target, metric, (ano, se)) com anomalia
    anomalias: set[tuple[str, str, str, tuple[int, int]]] = field(default_factory=set)
    # municipio_key -> vizinhos (rank ≤ 3)
    vizinhos: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Classe do alvo
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _regras_classe(path: str = str(CLASSE_CSV)) -> tuple[tuple[re.Pattern[str], str], ...]:
    p = Path(path)
    if not p.is_file():
        return ()
    with p.open(encoding="utf-8-sig", newline="") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r.get("ordem") or 0))
    return tuple((re.compile(r["padrao"], re.I), r["classe"].strip()) for r in rows)


def classe_alvo(target: str) -> str:
    t = str(target or "").strip().casefold()
    for pat, classe in _regras_classe():
        if pat.search(t):
            return classe
    return "indefinida"


# ---------------------------------------------------------------------------
# Contexto da SE
# ---------------------------------------------------------------------------

def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v: Any) -> int:
    return int(_f(v))


def montar_contexto(
    *,
    se: tuple[int, int],
    weekly: Iterable[dict[str, Any]],
    anomalias: Iterable[dict[str, Any]] = (),
    vizinhos: Iterable[dict[str, Any]] = (),
    norm_mun=lambda s: str(s or "").strip().upper(),
) -> ContextoValidacao:
    from etl.epi_week import shift_se

    se = (int(se[0]), int(se[1]))
    ant = shift_se(se[0], se[1], -1)
    base_weeks = {shift_se(se[0], se[1], -i) for i in range(1, 9)}
    tot: dict[tuple[int, int], float] = {}
    pos_se = ex_se = 0.0
    for r in weekly:
        yw = (_i(r.get("epi_year")), _i(r.get("epi_week")))
        if yw != se and yw not in base_weeks:
            continue
        t = _f(r.get("tests"))
        tot[yw] = tot.get(yw, 0.0) + t
        if yw == se:
            ex_se += t
            pos_se += _f(r.get("positives"))
    hist = sorted(tot.get(w, 0.0) for w in base_weeks)
    med = (hist[3] + hist[4]) / 2 if len(hist) == 8 else None
    razao = (tot.get(se, 0.0) / med) if med else None
    carga_ok = razao is None or razao >= CARGA_MIN
    pos_valida = not (ex_se >= 500 and pos_se / ex_se < POS_PLAUSIVEL_MIN)

    an: set[tuple[str, str, str, tuple[int, int]]] = set()
    for r in anomalias:
        if "queda" in str(r.get("tipo_anomalia") or "").casefold():
            continue
        an.add((
            norm_mun(r.get("municipio")),
            str(r.get("target") or ""),
            str(r.get("metric") or "").casefold(),
            (_i(r.get("epi_year")), _i(r.get("epi_week"))),
        ))
    viz: dict[str, list[str]] = {}
    for r in vizinhos:
        try:
            if int(float(r.get("rank_vizinho") or 99)) > 3:
                continue
        except (TypeError, ValueError):
            continue
        viz.setdefault(norm_mun(r.get("municipio")), []).append(norm_mun(r.get("vizinho")))
    return ContextoValidacao(
        se=se,
        se_anterior=ant,
        carga_ok=carga_ok,
        carga_razao=razao,
        positividade_valida=pos_valida,
        positividade_estadual=(int(pos_se), int(ex_se)),
        anomalias=an,
        vizinhos=viz,
    )


# ---------------------------------------------------------------------------
# Avaliação de um sinal
# ---------------------------------------------------------------------------

def _metric(tipo: str) -> str:
    return {"volume": "tests", "positividade": "positividade", "incidencia": "incidencia_100k"}.get(
        tipo, tipo
    )


def avaliar_sinal(s: Any, ctx: ContextoValidacao) -> Validacao:
    tipo = str(getattr(s, "tipo_sinal", "") or "")
    target = str(getattr(s, "agravo_raw", "") or "")
    classe = classe_alvo(target)
    v = Validacao(status=VALIDADO, classe_alvo=classe)

    # Lacunas têm validação própria (cobertura SINAN, n ≥ 20) a montante.
    if tipo == "lacuna":
        v.atendidos.append("cruzamento GAL×SINAN com cobertura na SE")
        return v

    # D1 — carga
    if not ctx.carga_ok:
        v.status = DESCARTADO
        v.motivos.append(
            "carga suspeita: volume estadual da SE "
            f"em {100 * (ctx.carga_razao or 0):.0f}% da mediana de 8 SE".replace(".", ",")
        )
        return v
    v.atendidos.append("carga da SE íntegra")

    # D2 — alvo
    if classe in CLASSES_FORA_DO_ALERTA:
        v.status = DESCARTADO
        v.motivos.append(f"alvo não elegível para alerta ({classe})")
        return v
    if classe == "indefinida":
        v.status = EM_OBSERVACAO
        v.motivos.append("alvo sem classificação epidemiológica (revisar regra)")
        return v

    # D3 — positividade
    if tipo == "positividade" and not ctx.positividade_valida:
        v.status = EM_OBSERVACAO
        v.motivos.append("positividade não avaliável (classificação de resultado GAL em revisão)")
        return v

    positivos = _i(getattr(s, "atual_positivos", 0))
    tem_positivo = ctx.positividade_valida and positivos >= 1

    # Notificação imediata: positivo isolado já é relevante.
    if classe == "imediata" and tem_positivo:
        v.atendidos.append(f"agravo de notificação imediata com {positivos} positivo(s)")
        return v

    # E1 — significância
    p = getattr(s, "p_valor", None)
    sev = str(getattr(s, "severidade_estatistica", "") or "").casefold()
    if p is not None:
        if p >= P_MAX:
            v.status = EM_OBSERVACAO
            v.motivos.append(f"sem significância (p={p:.3g} ≥ {P_MAX:g})".replace(".", ","))
            return v
        v.atendidos.append(f"significativo (p={p:.2g})".replace(".", ","))
    elif sev != "alta":
        v.status = EM_OBSERVACAO
        v.motivos.append("severidade estatística não alta")
        return v
    else:
        v.atendidos.append("severidade estatística alta")

    # E2 — magnitude
    if tipo == "positividade":
        if positivos < 2:
            v.status = EM_OBSERVACAO
            v.motivos.append("menos de 2 positivos")
            return v
        v.atendidos.append(f"{positivos} positivos")
    else:
        exc = getattr(s, "excesso", None)
        if exc is None:
            ref = getattr(s, "referencia", None)
            exc = _f(getattr(s, "atual_exames", 0)) - (_f(ref) if ref is not None else 0.0)
        if exc < MIN_EXCESSO:
            v.status = EM_OBSERVACAO
            v.motivos.append(
                f"excesso pequeno ({exc:.0f} exames < {MIN_EXCESSO:g})"
            )
            return v
        v.atendidos.append(f"excesso de {exc:.0f} exames sobre a base")

    # C — corroboração
    mk = str(getattr(s, "municipio_key", "") or "")
    met = _metric(tipo)
    persist = (mk, target, met, ctx.se_anterior) in ctx.anomalias
    if persist:
        v.corroboracoes.append("persistência (SE anterior)")
    if tem_positivo and tipo != "positividade":
        v.corroboracoes.append(f"{positivos} positivo(s) laboratorial(is)")
    viz = [
        n for n in ctx.vizinhos.get(mk, [])
        if any((n, target, m, ctx.se) in ctx.anomalias for m in ("tests", "positividade"))
    ]
    if viz:
        v.corroboracoes.append("vizinho com sinal (" + ", ".join(sorted(viz)[:2]) + ")")

    if classe == "cronica" and not persist:
        v.status = EM_OBSERVACAO
        v.motivos.append("agravo crônico/acompanhamento sem persistência em 2 SE")
        return v
    if not v.corroboracoes:
        v.status = EM_OBSERVACAO
        v.motivos.append("sem corroboração (persistência, positivo ou vizinho)")
        return v
    return v


def triar(facts: list[Any], ctx: ContextoValidacao) -> tuple[list[Any], list[tuple[Any, Validacao]]]:
    """Retorna (validados, todos_com_validacao). Anota ``fact.validacao``."""
    todos: list[tuple[Any, Validacao]] = []
    ok: list[Any] = []
    for f in facts:
        v = avaliar_sinal(f, ctx)
        try:
            f.validacao = v
        except AttributeError:
            pass
        todos.append((f, v))
        if v.publicar:
            ok.append(f)
    return ok, todos


def resumo_triagem(todos: list[tuple[Any, Validacao]]) -> dict[str, Any]:
    cont = {VALIDADO: 0, EM_OBSERVACAO: 0, DESCARTADO: 0}
    motivos: dict[str, int] = {}
    for _, v in todos:
        cont[v.status] = cont.get(v.status, 0) + 1
        if not v.publicar:
            key = re.sub(r"\s*\(.*\)$", "", v.motivos[0]) if v.motivos else "—"
            motivos[key] = motivos.get(key, 0) + 1
    return {"contagem": cont, "motivos": dict(sorted(motivos.items(), key=lambda kv: -kv[1]))}


def exportar_triagem(path: Path | str, todos: list[tuple[Any, Validacao]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "signal_id", "municipio", "agravo_raw", "tipo_sinal", "classe_alvo", "status",
        "atual_exames", "atual_positivos", "referencia", "p_valor",
        "prioridade_epidemiologica", "criterios_atendidos", "corroboracoes", "motivos",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for s, v in todos:
            w.writerow([
                getattr(s, "signal_id", ""), getattr(s, "municipio", ""),
                getattr(s, "agravo_raw", ""), getattr(s, "tipo_sinal", ""),
                v.classe_alvo, v.status, getattr(s, "atual_exames", ""),
                getattr(s, "atual_positivos", ""), getattr(s, "referencia", ""),
                getattr(s, "p_valor", ""), getattr(s, "prioridade_epidemiologica", ""),
                " | ".join(v.atendidos), " | ".join(v.corroboracoes), " | ".join(v.motivos),
            ])
