#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de positividade por marcador / metodologia — Radar LACEN / CIEVS.

Classifica exames do espelho GAL micro (Exame + Metodologia + resultados)
para evitar alertas falsos de IgG/soroprevalência e destacar sinais
agudos/ativos (ex.: HBsAg, IgM anti-HBc, HBV-DNA).

Fonte mestra editável: conhecimento_ve/regras_agravo_gal.csv
(regenerar com scripts/gerar_regras_agravo_gal.py). Fallback: regras hardcoded.

Uso:
  from lacen_agente_marcadores import classificar_exame, agregar_positividade_marcadores
  python lacen_agente_marcadores.py
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"
STAGE = OUTDIR_DEFAULT / "staging_dw"
CONHECIMENTO = ROOT / "conhecimento_ve"
REGRAS_CSV = CONHECIMENTO / "regras_agravo_gal.csv"

POS_MARCADORES_CSV = "positividade_por_marcador.csv"
POS_MARCADORES_RESUMO = "positividade_por_marcador_resumo.md"

# Classes de interpretação (ver conhecimento_ve/marcadores_ensaio.md)
CLASSE_NAO_AGUDO = "nao_agudo_soroprevalencia"
CLASSE_SINAL_ATIVO = "sinal_agudo_ou_ativo"
CLASSE_MOLECULAR = "molecular_presenca_ausencia"
CLASSE_INDET = "indeterminado"

_POS_TOKENS = (
    r"detect[aá]vel",
    r"reagente",
    r"positivo",
    r"positiva",
    r"reactive",
    r"detected",
)
_NEG_TOKENS = (
    r"n[aã]o\s*detect",
    r"n[aã]o\s*reagente",
    r"negativ",
    r"non[\s-]*reactive",
    r"undetect",
)


@dataclass
class ClassificacaoMarcador:
    exame: str
    metodologia: str
    familia: str
    marcador: str
    classe: str
    alerta_agudo: bool
    nota_pt: str
    resultado_bruto: str = ""
    resultado_binario: str = "indeterminado"  # positivo | negativo | indeterminado
    conta_alerta_agudo: bool = False
    conta_bortman: bool = False
    conta_positividade_agregada: bool = False
    fonte_regra: str = ""


@dataclass
class AgregadoMarcador:
    municipio: str
    familia: str
    marcador: str
    classe: str
    metodologia: str
    n_exames: int = 0
    n_positivos: int = 0
    n_negativos: int = 0
    positividade: float | None = None
    alerta_agudo: bool = False
    nota_pt: str = ""
    conta_alerta_agudo: bool = False
    conta_bortman: bool = False
    conta_positividade_agregada: bool = False


@dataclass
class RegraAgravo:
    agravo_gal: str
    familia: str
    padrao_exame: str
    metodologia: str
    marcador: str
    classe: str
    conta_alerta_agudo: bool
    conta_bortman: bool
    conta_positividade_agregada: bool
    n_minimo: int
    nota_pt: str
    fonte: str
    exame_gal_exato: str = ""
    agravo_requisicao: str = ""
    validacao_ms: str = ""
    _rx_exame: re.Pattern[str] | None = field(default=None, repr=False)
    _rx_met: re.Pattern[str] | None = field(default=None, repr=False)
    _exato_cf: str = field(default="", repr=False)


def _as_bool(v: object, default: bool = False) -> bool:
    s = str(v or "").strip().casefold()
    if s in {"1", "true", "sim", "yes", "y", "t"}:
        return True
    if s in {"0", "false", "nao", "não", "no", "n", "f"}:
        return False
    return default


def _compile_rx(pat: str) -> re.Pattern[str] | None:
    p = str(pat or "").strip()
    if not p:
        return None
    try:
        return re.compile(p, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(p), re.IGNORECASE)


@lru_cache(maxsize=1)
def carregar_regras_agravo(path: str | None = None) -> tuple[RegraAgravo, ...]:
    """
    Carrega regras_agravo_gal.csv (fonte mestra). Retorna tupla vazia se ausente.
    Prioridade de match: exame_gal_exato > padrao_exame (regex).
    """
    p = Path(path) if path else REGRAS_CSV
    if not p.exists():
        return tuple()
    out: list[RegraAgravo] = []
    with p.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            exato = str(row.get("exame_gal_exato") or "").strip()
            pad = str(row.get("padrao_exame") or "").strip()
            if not exato and not pad:
                continue
            regra = RegraAgravo(
                agravo_gal=str(row.get("agravo_gal") or "").strip(),
                familia=str(row.get("familia") or "").strip(),
                padrao_exame=pad,
                metodologia=str(row.get("metodologia") or "").strip(),
                marcador=str(row.get("marcador") or "").strip() or "nao_mapeado",
                classe=str(row.get("classe") or CLASSE_INDET).strip() or CLASSE_INDET,
                conta_alerta_agudo=_as_bool(row.get("conta_alerta_agudo")),
                conta_bortman=_as_bool(row.get("conta_bortman")),
                conta_positividade_agregada=_as_bool(
                    row.get("conta_positividade_agregada")
                ),
                n_minimo=int(float(row.get("n_minimo") or 3) or 3),
                nota_pt=str(row.get("nota_pt") or "").strip(),
                fonte=str(row.get("fonte") or "").strip(),
                exame_gal_exato=exato,
                agravo_requisicao=str(row.get("agravo_requisicao") or "").strip(),
                validacao_ms=str(row.get("validacao_ms") or "").strip(),
            )
            regra._exato_cf = _cf(exato) if exato else ""
            regra._rx_exame = _compile_rx(regra.padrao_exame) if pad else None
            regra._rx_met = _compile_rx(regra.metodologia) if regra.metodologia else None
            out.append(regra)

    # Exatas primeiro; depois regex mais longos; genéricos ".*" por último
    out.sort(
        key=lambda r: (
            2 if r.exame_gal_exato else 0,
            0 if r.padrao_exame == ".*" else 1,
            len(r.padrao_exame or r.exame_gal_exato),
            1 if r.metodologia else 0,
        ),
        reverse=True,
    )
    return tuple(out)


def _match_regra(
    exame_cf: str, met_cf: str, familia: str, regras: Sequence[RegraAgravo]
) -> RegraAgravo | None:
    # 1) Match literal do nome do exame GAL
    for r in regras:
        if r._exato_cf and r._exato_cf == exame_cf:
            return r

    # 2) Regex / padrões
    for r in regras:
        if r._rx_exame is None:
            continue
        if not r._rx_exame.search(exame_cf):
            continue
        if r._rx_met is not None and met_cf and not r._rx_met.search(met_cf):
            if r.metodologia:
                continue
        elif r._rx_met is not None and not met_cf:
            if r.padrao_exame in (".*", r"\bigg\b", r"\bigm\b"):
                continue
        return r
    return None


def flags_da_classe(classe: str) -> tuple[bool, bool, bool]:
    """conta_alerta, conta_bortman, conta_positividade_agregada a partir da classe."""
    if classe == CLASSE_NAO_AGUDO:
        return False, False, False
    if classe == CLASSE_SINAL_ATIVO:
        return True, True, True
    if classe == CLASSE_MOLECULAR:
        return True, True, True
    return False, False, False


def filtrar_linhas_marcador(
    linhas: Sequence[dict[str, Any]],
    *,
    uso: str = "alerta",
) -> list[dict[str, Any]]:
    """
    Filtra agregados conforme uso:
      alerta → conta_alerta_agudo
      bortman → conta_bortman
      agregada → conta_positividade_agregada
    """
    key = {
        "alerta": "conta_alerta_agudo",
        "radar": "conta_alerta_agudo",
        "bortman": "conta_bortman",
        "agregada": "conta_positividade_agregada",
        "positividade": "conta_positividade_agregada",
    }.get(uso.casefold(), "conta_alerta_agudo")
    out: list[dict[str, Any]] = []
    for row in linhas:
        flag = row.get(key)
        if flag is None:
            # legado: usa alerta_agudo / classe
            if key == "conta_alerta_agudo":
                flag = row.get("alerta_agudo") or row.get("classe") in (
                    CLASSE_SINAL_ATIVO,
                    CLASSE_MOLECULAR,
                )
            elif key == "conta_bortman":
                flag = row.get("classe") in (CLASSE_SINAL_ATIVO, CLASSE_MOLECULAR)
            else:
                flag = row.get("classe") != CLASSE_NAO_AGUDO
        if _as_bool(flag, default=bool(flag)):
            out.append(dict(row))
    return out


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _cf(text: object) -> str:
    t = _norm(text).casefold()
    t = (
        t.replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
    return t


def _resultado_binario(campos: Sequence[str]) -> str:
    blob = " ".join(_cf(c) for c in campos if c)
    if not blob:
        return "indeterminado"
    # Negativo primeiro (ex.: "Não Detectável" contém "detect")
    for tok in _NEG_TOKENS:
        if re.search(tok, blob):
            return "negativo"
    for tok in _POS_TOKENS:
        if re.search(tok, blob):
            return "positivo"
    return "indeterminado"


def _familia_de_exame(exame: str, agravo: str = "") -> str:
    blob = f"{_cf(exame)} {_cf(agravo)}"
    if "hepatite b" in blob or "hbv" in blob or "hbsag" in blob or "anti hbc" in blob or "anti hbs" in blob:
        return "hepatite_b"
    if "hepatite c" in blob or "hcv" in blob or "anti hcv" in blob:
        return "hepatite_c"
    if "hepatite a" in blob or "hav" in blob:
        return "hepatite_a"
    if "hepatite d" in blob or "hdv" in blob:
        return "hepatite_d"
    if "dengue" in blob:
        return "dengue"
    if "chikung" in blob:
        return "chikungunya"
    if "zika" in blob:
        return "zika"
    if "tubercul" in blob or blob.startswith("tb ") or "genexpert" in blob:
        return "tuberculose"
    if "meningit" in blob:
        return "meningite"
    if "oropouche" in blob or "mayaro" in blob:
        return "arbovirose_outra"
    return "outros"


def _eh_molecular(metodologia: str, exame: str) -> bool:
    blob = f"{_cf(metodologia)} {_cf(exame)}"
    return any(
        k in blob
        for k in (
            "pcr",
            "rt-pcr",
            "rt pcr",
            "biologia molecular",
            "molecular",
            "dna hbv",
            "rna hcv",
            "carga viral",
            "genexpert",
            "naat",
        )
    )


def _classificar_exame_hardcoded(
    exame: str,
    *,
    metodologia: str = "",
    agravo: str = "",
    campos_resultado: Sequence[str] | None = None,
) -> ClassificacaoMarcador:
    """Fallback interno quando a planilha de regras não cobre o ensaio."""
    ex = _norm(exame)
    met = _norm(metodologia)
    fam = _familia_de_exame(ex, agravo)
    ex_cf = _cf(ex)
    campos = list(campos_resultado or [])
    res = _resultado_binario(campos)
    bruto = " | ".join(_norm(c) for c in campos if _norm(c))[:240]

    marcador = "nao_mapeado"
    classe = CLASSE_INDET
    alerta = False
    nota = "Marcador sem mapeamento seguro — revisar laudo nominal."

    # --- HBV ---
    if fam == "hepatite_b" or any(
        k in ex_cf for k in ("hbsag", "anti hbs", "anti hbc", "hbeag", "anti hbe", "dna hbv", "hbv")
    ):
        fam = "hepatite_b"
        if "anti hbs" in ex_cf or "anti-hbs" in ex_cf:
            marcador = "anti_HBs"
            classe = CLASSE_NAO_AGUDO
            alerta = False
            nota = (
                "Anti-HBs: imunidade vacinal ou contato passado — "
                "não interpretar como infecção aguda."
            )
        elif "igm" in ex_cf and ("hbc" in ex_cf or "anti hbc" in ex_cf):
            marcador = "anti_HBc_IgM"
            classe = CLASSE_SINAL_ATIVO
            alerta = True
            nota = (
                "Anti-HBc IgM: compatível com infecção aguda (ou reativação) — "
                "sinal laboratorial ativo para a VE."
            )
        elif "anti hbc" in ex_cf or "anti-hbc" in ex_cf:
            marcador = "anti_HBc_total"
            classe = CLASSE_NAO_AGUDO
            alerta = False
            nota = (
                "Anti-HBc total: contato passado ou crônico possível — "
                "não basta sozinho para alerta de aguda."
            )
        elif "hbsag" in ex_cf or "hbs ag" in ex_cf:
            marcador = "HBsAg"
            classe = CLASSE_SINAL_ATIVO
            alerta = True
            nota = (
                "HBsAg: infecção ativa (aguda ou crônica) — sinal laboratorial; "
                "cruzar com clínica, IgM e notificação (não declarar surto só com isso)."
            )
        elif "dna" in ex_cf or ("hbv" in ex_cf and _eh_molecular(met, ex)):
            marcador = "HBV_DNA"
            classe = CLASSE_MOLECULAR
            alerta = res == "positivo"
            nota = (
                "HBV-DNA (molecular): presença/ausência do vírus — "
                "confirmatorio de replicação quando detectável."
            )
        elif "hbeag" in ex_cf:
            marcador = "HBeAg"
            classe = CLASSE_SINAL_ATIVO
            alerta = True
            nota = "HBeAg: marcador de replicação — contextualizar com DNA e clínica."
        elif "anti hbe" in ex_cf:
            marcador = "anti_HBe"
            classe = CLASSE_INDET
            alerta = False
            nota = "Anti-HBe: fase da infecção — interpretar no painel completo."

    elif _eh_molecular(met, ex):
        marcador = "molecular"
        classe = CLASSE_MOLECULAR
        alerta = res == "positivo"
        nota = (
            "Ensaio molecular: detecta presença/ausência do agente — "
            "usar como confirmação laboratorial, não como incidência."
        )

    elif fam in ("dengue", "chikungunya", "zika", "arbovirose_outra"):
        if "igg" in ex_cf and "igm" not in ex_cf:
            marcador = "IgG"
            classe = CLASSE_NAO_AGUDO
            alerta = False
            nota = "IgG isolada: soroprevalência / infecção passada — não alerta agudo."
        elif "igm" in ex_cf:
            marcador = "IgM"
            classe = CLASSE_SINAL_ATIVO
            alerta = True
            nota = "IgM: sugere infecção recente — sinal para investigação."
        elif "ns1" in ex_cf:
            marcador = "NS1"
            classe = CLASSE_SINAL_ATIVO
            alerta = True
            nota = "NS1: compatível com infecção recente/aguda."
        elif _eh_molecular(met, ex) or "pcr" in ex_cf:
            marcador = "PCR_arbovirose"
            classe = CLASSE_MOLECULAR
            alerta = res == "positivo"
            nota = "PCR arbovirose: presença/ausência confirmatória do vírus."
        else:
            marcador = fam
            classe = CLASSE_INDET
            nota = f"Arbovirose ({fam}): revisar método no laudo."

    elif "igg" in ex_cf and "igm" not in ex_cf:
        marcador = "IgG"
        classe = CLASSE_NAO_AGUDO
        alerta = False
        nota = "IgG/sorologia: reflete soroprevalência — não tratar como epidemia aguda."

    elif "igm" in ex_cf:
        marcador = "IgM"
        classe = CLASSE_SINAL_ATIVO
        alerta = True
        nota = "IgM: janela de infecção recente — sinal laboratorial ativo."

    ca, cb, cp = flags_da_classe(classe)
    # Molecular: alerta só se positivo (presença)
    if classe == CLASSE_MOLECULAR:
        alerta = res == "positivo"
        ca = alerta
    alerta_final = bool(alerta and res == "positivo") if classe != CLASSE_NAO_AGUDO else False
    if classe == CLASSE_NAO_AGUDO:
        alerta_final = False
        ca = False
    elif classe == CLASSE_SINAL_ATIVO:
        alerta_final = res == "positivo"
        ca = True
    return ClassificacaoMarcador(
        exame=ex,
        metodologia=met,
        familia=fam,
        marcador=marcador,
        classe=classe,
        alerta_agudo=alerta_final,
        nota_pt=nota,
        resultado_bruto=bruto,
        resultado_binario=res,
        conta_alerta_agudo=ca and (res == "positivo" if classe == CLASSE_MOLECULAR else True),
        conta_bortman=cb,
        conta_positividade_agregada=cp,
        fonte_regra="hardcoded",
    )


def classificar_exame(
    exame: str,
    *,
    metodologia: str = "",
    agravo: str = "",
    campos_resultado: Sequence[str] | None = None,
) -> ClassificacaoMarcador:
    """
    Classifica um ensaio GAL em família/marcador/classe de alerta.

    Prioridade: planilha ``regras_agravo_gal.csv``; fallback hardcoded.
    HBV: anti-HBs / IgG / contato passado ≠ aguda;
    HBsAg, IgM anti-HBc, HBV-DNA = sinal agudo/ativo.
    Molecular: presença/ausência confirmatória.
    """
    ex = _norm(exame)
    met = _norm(metodologia)
    fam = _familia_de_exame(ex, agravo)
    ex_cf = _cf(ex)
    met_cf = _cf(met)
    campos = list(campos_resultado or [])
    res = _resultado_binario(campos)
    bruto = " | ".join(_norm(c) for c in campos if _norm(c))[:240]

    regras = carregar_regras_agravo()
    if regras:
        matched = _match_regra(ex_cf, met_cf, fam, regras)
        if matched is not None:
            classe = matched.classe or CLASSE_INDET
            fam_out = matched.familia or fam
            ca = matched.conta_alerta_agudo
            cb = matched.conta_bortman
            cp = matched.conta_positividade_agregada
            # Molecular: conta no alerta só se detectável
            if classe == CLASSE_MOLECULAR:
                alerta = res == "positivo" and ca
            elif classe == CLASSE_NAO_AGUDO:
                alerta = False
                ca = False
            else:
                alerta = bool(ca and res == "positivo")
            return ClassificacaoMarcador(
                exame=ex,
                metodologia=met,
                familia=fam_out,
                marcador=matched.marcador,
                classe=classe,
                alerta_agudo=alerta,
                nota_pt=matched.nota_pt
                or "Classificado pela planilha regras_agravo_gal.",
                resultado_bruto=bruto,
                resultado_binario=res,
                conta_alerta_agudo=ca,
                conta_bortman=cb,
                conta_positividade_agregada=cp,
                fonte_regra=matched.fonte or "regras_agravo_gal.csv",
            )

    return _classificar_exame_hardcoded(
        exame,
        metodologia=metodologia,
        agravo=agravo,
        campos_resultado=campos_resultado,
    )


def _ler_gal_micro(outdir: Path) -> list[dict[str, str]]:
    stage = outdir / "staging_dw"
    # Prefer parquet via pandas; fallback CSV sample
    for name in (
        "vw_gal_micro_recent.parquet",
        "vw_gal_micro_recent_for_rede.parquet",
        "vw_gal_micro_recent.csv",
    ):
        path = stage / name
        if not path.exists():
            continue
        if path.suffix == ".parquet":
            try:
                import pandas as pd

                df = pd.read_parquet(path)
                return df.fillna("").astype(str).to_dict(orient="records")
            except Exception:  # noqa: BLE001
                continue
        rows: list[dict[str, str]] = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for i, row in enumerate(csv.DictReader(f)):
                rows.append({k: str(v or "") for k, v in row.items()})
                if i >= 50000:
                    break
        return rows
    return []


def agregar_positividade_marcadores(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    mun_filtro: Sequence[str] | None = None,
    top: int = 80,
) -> dict[str, Any]:
    """
    Agrega positividade nominal por marcador/metodologia a partir do GAL micro.
    Retorna resumo + linhas; persiste CSV se solicitado via persistir_*.
    """
    outdir = Path(outdir)
    rows = _ler_gal_micro(outdir)
    mun_want = {_cf(m) for m in (mun_filtro or []) if m}

    buckets: dict[tuple[str, str, str, str], AgregadoMarcador] = {}
    exemplos: list[dict[str, str]] = []
    n_sem_id = len(rows)
    tem_id_paciente = False

    for r in rows:
        # Detecta coluna de ID paciente (raro no espelho atual)
        for k in r:
            lk = k.casefold()
            if any(
                x in lk
                for x in ("id_paciente", "idpaciente", "cpf", "cns", "prontuario")
            ):
                if str(r.get(k) or "").strip():
                    tem_id_paciente = True

        mun = _norm(
            r.get("Municipio_Residencia_Paciente")
            or r.get("municipio")
            or r.get("Municipio_Solicitante")
            or ""
        )
        if mun_want and _cf(mun) not in mun_want:
            continue
        exame = r.get("Exame") or r.get("exame") or ""
        met = r.get("Metodologia") or r.get("metodologia") or ""
        agravo = r.get("Agravo_Gal") or r.get("Agravo_Requisicao") or ""
        campos = [
            r.get(f"Campo_Resultado_{i}") or r.get(f"campo_resultado_{i}") or ""
            for i in range(1, 7)
        ]
        clf = classificar_exame(
            exame, metodologia=met, agravo=agravo, campos_resultado=campos
        )
        key = (mun.upper(), clf.familia, clf.marcador, clf.classe)
        agg = buckets.get(key)
        if agg is None:
            agg = AgregadoMarcador(
                municipio=mun.upper() if mun else "—",
                familia=clf.familia,
                marcador=clf.marcador,
                classe=clf.classe,
                metodologia=clf.metodologia or met,
                alerta_agudo=clf.conta_alerta_agudo
                or clf.classe in (CLASSE_SINAL_ATIVO, CLASSE_MOLECULAR),
                nota_pt=clf.nota_pt,
                conta_alerta_agudo=clf.conta_alerta_agudo,
                conta_bortman=clf.conta_bortman,
                conta_positividade_agregada=clf.conta_positividade_agregada,
            )
            buckets[key] = agg
        agg.n_exames += 1
        if clf.resultado_binario == "positivo":
            agg.n_positivos += 1
        elif clf.resultado_binario == "negativo":
            agg.n_negativos += 1

        if len(exemplos) < 12 and clf.familia == "hepatite_b":
            exemplos.append(
                {
                    "municipio": mun,
                    "exame": clf.exame,
                    "marcador": clf.marcador,
                    "classe": clf.classe,
                    "resultado": clf.resultado_binario,
                    "nota": clf.nota_pt,
                    "fonte_regra": clf.fonte_regra,
                }
            )

    linhas: list[dict[str, Any]] = []
    for agg in buckets.values():
        denom = agg.n_positivos + agg.n_negativos
        agg.positividade = (agg.n_positivos / denom) if denom > 0 else None
        linhas.append(asdict(agg))

    linhas.sort(
        key=lambda x: (
            0 if x.get("conta_alerta_agudo") or x["classe"] == CLASSE_SINAL_ATIVO else 1,
            -(x["n_positivos"] or 0),
            -(x["n_exames"] or 0),
        )
    )
    n_regras = len(carregar_regras_agravo())
    linhas_alerta = filtrar_linhas_marcador(linhas, uso="alerta")
    linhas = linhas[: max(1, top)]

    return {
        "linhas": linhas,
        "linhas_alerta": filtrar_linhas_marcador(linhas, uso="alerta"),
        "linhas_bortman": filtrar_linhas_marcador(linhas, uso="bortman"),
        "exemplos_hbv": exemplos,
        "n_registros_micro": n_sem_id,
        "n_regras_carregadas": n_regras,
        "n_linhas_alerta": len(linhas_alerta),
        "deduplicacao_paciente": {
            "possivel": tem_id_paciente,
            "motivo": (
                "ID paciente presente no micro"
                if tem_id_paciente
                else "bloqueada — ausência de identificador no espelho GAL micro (LGPD/dado não extraído)"
            ),
        },
        "caveat": (
            "Positividade por marcador (regras_agravo_gal): "
            "IgG/anti-HBs não entram em alerta agudo nem Bortman. "
            "Não declara surto."
        ),
        "fonte_regras": str(REGRAS_CSV) if REGRAS_CSV.exists() else "hardcoded",
    }


def interpretar_hbv_amostra(exame: str, resultado: str = "") -> str:
    """Frase curta em português claro para amostra HBV (validação / relatório)."""
    clf = classificar_exame(
        exame,
        metodologia="PCR" if "dna" in _cf(exame) else "sorologia",
        campos_resultado=[resultado] if resultado else [],
    )
    res = clf.resultado_binario
    if clf.marcador == "anti_HBs":
        return (
            f"Exame «{clf.exame}»: anti-HBs — indica imunidade (vacina ou contato antigo). "
            "Não conta como caso agudo de hepatite B."
        )
    if clf.marcador == "anti_HBc_IgM":
        return (
            f"Exame «{clf.exame}»: anti-HBc IgM — compatível com infecção aguda. "
            f"Resultado lido como {res}. Sinal para a VE investigar (não é surto automático)."
        )
    if clf.marcador == "HBsAg":
        return (
            f"Exame «{clf.exame}»: HBsAg — infecção ativa (pode ser aguda ou crônica). "
            f"Resultado lido como {res}. Cruzar com IgM, DNA e notificação."
        )
    if clf.marcador == "HBV_DNA":
        return (
            f"Exame «{clf.exame}»: DNA do HBV (molecular) — "
            f"{'vírus detectável' if res == 'positivo' else 'vírus não detectável' if res == 'negativo' else 'resultado a revisar'}. "
            "Confirma presença/ausência do agente."
        )
    return f"Exame «{clf.exame}»: {clf.nota_pt}"


def persistir_positividade_marcadores(
    payload: dict[str, Any], outdir: Path | str = OUTDIR_DEFAULT
) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / POS_MARCADORES_CSV
    fields = [
        "municipio",
        "familia",
        "marcador",
        "classe",
        "metodologia",
        "n_exames",
        "n_positivos",
        "n_negativos",
        "positividade",
        "alerta_agudo",
        "conta_alerta_agudo",
        "conta_bortman",
        "conta_positividade_agregada",
        "nota_pt",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in payload.get("linhas") or []:
            out = dict(row)
            if out.get("positividade") is not None:
                out["positividade"] = f"{100.0 * float(out['positividade']):.1f}%"
            w.writerow({k: out.get(k, "") for k in fields})

    md = outdir / POS_MARCADORES_RESUMO
    lines = [
        "# Positividade por marcador / metodologia",
        "",
        str(payload.get("caveat") or ""),
        "",
        f"Registros micro lidos: {payload.get('n_registros_micro', 0)}",
        f"Regras carregadas: {payload.get('n_regras_carregadas', 0)} "
        f"(fonte: {payload.get('fonte_regras', '—')})",
        f"Linhas com conta_alerta_agudo: {payload.get('n_linhas_alerta', 0)}",
        f"Deduplicação paciente: {payload.get('deduplicacao_paciente', {}).get('motivo', '—')}",
        "",
        "## Exemplos HBV",
    ]
    for ex in payload.get("exemplos_hbv") or []:
        lines.append(
            f"- {ex.get('municipio')}: {ex.get('exame')} → {ex.get('marcador')} "
            f"[{ex.get('classe')}] ({ex.get('resultado')}) — {ex.get('nota')}"
        )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    payload = agregar_positividade_marcadores(OUTDIR_DEFAULT)
    path = persistir_positividade_marcadores(payload, OUTDIR_DEFAULT)
    print(f"Linhas: {len(payload.get('linhas') or [])}")
    print(f"CSV: {path}")
    print(interpretar_hbv_amostra("Hepatite B, Anti HBs", "Resultado: Reagente"))
    print(interpretar_hbv_amostra("Hepatite B, HBsAg", "Resultado: Reagente"))
    print(
        interpretar_hbv_amostra(
            "Hepatite B, Pesquisa quantitativa do DNA HBV",
            "Resultado: Detectável",
        )
    )


if __name__ == "__main__":
    main()
