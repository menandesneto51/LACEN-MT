#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera conhecimento_ve/regras_agravo_gal.xlsx (+ CSV espelho) a partir de:
  - Positividade_Por_Agravo_GAL.xlsx (Regras_Por_Agravo + Metadados)
  - Catálogo de exames distintos do GAL micro (staging_dw)
  - Regras anti-ruído pré-carregadas (HBV, dengue/chik, TB, toxo/CMV, moleculares)

Uso:
  python scripts/gerar_regras_agravo_gal.py
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONHECIMENTO = ROOT / "conhecimento_ve"
OUT_XLSX = CONHECIMENTO / "regras_agravo_gal.xlsx"
OUT_CSV = CONHECIMENTO / "regras_agravo_gal.csv"
SRC_POSIT = CONHECIMENTO / "Positividade_Por_Agravo_GAL.xlsx"
STAGE = ROOT / "saida_pipeline" / "staging_dw"

COLS = [
    "agravo_gal",
    "familia",
    "padrao_exame",
    "metodologia",
    "marcador",
    "classe",
    "conta_alerta_agudo",
    "conta_bortman",
    "conta_positividade_agregada",
    "n_minimo",
    "nota_pt",
    "fonte",
]

CLASSE_NAO = "nao_agudo_soroprevalencia"
CLASSE_ATIVO = "sinal_agudo_ou_ativo"
CLASSE_MOL = "molecular_presenca_ausencia"
CLASSE_INDET = "indeterminado"


def _tf(v: bool) -> str:
    return "true" if v else "false"


def _row(
    *,
    agravo_gal: str,
    familia: str,
    padrao_exame: str,
    metodologia: str = "",
    marcador: str,
    classe: str,
    conta_alerta_agudo: bool,
    conta_bortman: bool,
    conta_positividade_agregada: bool,
    n_minimo: int = 3,
    nota_pt: str,
    fonte: str,
) -> dict[str, str]:
    return {
        "agravo_gal": agravo_gal,
        "familia": familia,
        "padrao_exame": padrao_exame,
        "metodologia": metodologia,
        "marcador": marcador,
        "classe": classe,
        "conta_alerta_agudo": _tf(conta_alerta_agudo),
        "conta_bortman": _tf(conta_bortman),
        "conta_positividade_agregada": _tf(conta_positividade_agregada),
        "n_minimo": str(n_minimo),
        "nota_pt": nota_pt,
        "fonte": fonte,
    }


def regras_seed() -> list[dict[str, str]]:
    """Pré-carga anti-ruído (área técnica + planilha Positividade)."""
    f = "Guia MS / LACEN / Positividade_Por_Agravo_GAL"
    rows: list[dict[str, str]] = []

    # --- Hepatite B ---
    rows += [
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"anti[\s\-]?hbs",
            marcador="anti_HBs",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="Anti-HBs: imunidade vacinal ou contato passado — não infecção aguda.",
            fonte=f,
        ),
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"(anti[\s\-]?hbc.*igm|igm.*anti[\s\-]?hbc|anti[\s\-]?hbc\s*[-–]?\s*igm)",
            marcador="anti_HBc_IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="Anti-HBc IgM: marcador de infecção aguda (ou reativação) — sinal para a VE.",
            fonte=f,
        ),
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"anti[\s\-]?hbc",
            marcador="anti_HBc_total",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="Anti-HBc total: contato passado/crônico — não basta sozinho para alerta agudo.",
            fonte=f,
        ),
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"hbsag|hbs[\s\-]?ag",
            marcador="HBsAg",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="HBsAg: infecção ativa (aguda ou crônica) — cruzar com IgM, DNA e notificação.",
            fonte=f,
        ),
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"(dna[\s\-]?hbv|hbv[\s\-]?dna|pesquisa quantitativa do dna hbv)",
            marcador="HBV_DNA",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="HBV-DNA (molecular): presença/ausência do vírus — confirmatório de replicação.",
            fonte=f,
        ),
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"hbeag",
            marcador="HBeAg",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=False,
            conta_positividade_agregada=True,
            nota_pt="HBeAg: marcador de replicação — contextualizar com DNA e clínica.",
            fonte=f,
        ),
        _row(
            agravo_gal="Hepatite B",
            familia="hepatite_b",
            padrao_exame=r"anti[\s\-]?hbe",
            marcador="anti_HBe",
            classe=CLASSE_INDET,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="Anti-HBe: fase da infecção — interpretar no painel completo.",
            fonte=f,
        ),
    ]

    # --- Dengue ---
    rows += [
        _row(
            agravo_gal="Dengue",
            familia="dengue",
            padrao_exame=r"dengue.*ns1|ns1.*dengue|\bns1\b",
            marcador="NS1",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="NS1: compatível com infecção recente/aguda (fase virêmica).",
            fonte=f,
        ),
        _row(
            agravo_gal="Dengue",
            familia="dengue",
            padrao_exame=r"dengue.*igm|\bigm\b.*dengue",
            marcador="IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="IgM dengue: sugere infecção recente — sinal para investigação.",
            fonte=f,
        ),
        _row(
            agravo_gal="Dengue",
            familia="dengue",
            padrao_exame=r"dengue.*igg|\bigg\b.*dengue",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="IgG dengue isolada: soroprevalência / infecção passada — não alerta agudo.",
            fonte=f,
        ),
        _row(
            agravo_gal="Dengue",
            familia="dengue",
            padrao_exame=r"(pesquisa de arbov[ií]rus|zdc|rt[\s\-]?pcr.*dengue|dengue.*pcr)",
            metodologia="pcr|molecular|rt",
            marcador="PCR_arbovirose",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="PCR/arbovírus: presença/ausência confirmatória do vírus.",
            fonte=f,
        ),
    ]

    # --- Chikungunya ---
    rows += [
        _row(
            agravo_gal="Chikungunya",
            familia="chikungunya",
            padrao_exame=r"chikung.*igm",
            marcador="IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="IgM chikungunya: infecção recente — sinal ativo.",
            fonte=f,
        ),
        _row(
            agravo_gal="Chikungunya",
            familia="chikungunya",
            padrao_exame=r"chikung.*igg",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="IgG chikungunya: exposição pretérita — não alerta agudo isolado.",
            fonte=f,
        ),
        _row(
            agravo_gal="Chikungunya",
            familia="chikungunya",
            padrao_exame=r"chikung.*(pcr|molecular|rt[\s\-]?pcr)",
            marcador="PCR_arbovirose",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="RT-PCR chikungunya: presença/ausência na fase aguda.",
            fonte=f,
        ),
    ]

    # --- Zika ---
    rows += [
        _row(
            agravo_gal="Zika",
            familia="zika",
            padrao_exame=r"zika.*igm",
            marcador="IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="IgM zika: sugere infecção recente.",
            fonte=f,
        ),
        _row(
            agravo_gal="Zika",
            familia="zika",
            padrao_exame=r"zika.*igg",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="IgG zika: soroprevalência — não alerta agudo isolado.",
            fonte=f,
        ),
    ]

    # --- Tuberculose ---
    rows += [
        _row(
            agravo_gal="Tuberculose",
            familia="tuberculose",
            padrao_exame=r"(teste r[aá]pido molecular|trm[\s\-]?tb|genexpert)",
            marcador="TRM_TB",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="TRM-TB / GeneXpert: confirmação molecular — sinal laboratorial ativo.",
            fonte=f,
        ),
        _row(
            agravo_gal="Tuberculose",
            familia="tuberculose",
            padrao_exame=r"baciloscopia|baar",
            marcador="BAAR",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="BAAR/baciloscopia: bacilífero potencial — cruzar com SINAN e clínica.",
            fonte=f,
        ),
        _row(
            agravo_gal="Tuberculose",
            familia="tuberculose",
            padrao_exame=r"tuberculose.*cultura|cultura.*micobact",
            marcador="cultura_TB",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="Cultura para micobactérias: padrão-ouro confirmatório.",
            fonte=f,
        ),
    ]

    # --- COVID-19 ---
    rows += [
        _row(
            agravo_gal="COVID-19",
            familia="covid19",
            padrao_exame=r"(covid|sars[\s\-]?cov|coronav).*(pcr|rt[\s\-]?pcr|molecular)",
            marcador="PCR_covid",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="RT-PCR COVID: presença/ausência do agente.",
            fonte=f,
        ),
        _row(
            agravo_gal="COVID-19",
            familia="covid19",
            padrao_exame=r"(covid|sars[\s\-]?cov).*(ant[ií]geno|tr[\s\-]?ag)",
            marcador="antigeno",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="Antígeno COVID: sinal agudo em sintomáticos.",
            fonte=f,
        ),
        _row(
            agravo_gal="COVID-19",
            familia="covid19",
            padrao_exame=r"(covid|sars[\s\-]?cov).*igg",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="IgG COVID: soroprevalência/inquérito — não alerta agudo operacional.",
            fonte=f,
        ),
    ]

    # --- Meningite ---
    rows += [
        _row(
            agravo_gal="Meningite",
            familia="meningite",
            padrao_exame=r"meningit.*(molecular|pcr|cultura|l[ií]quor|lcr)",
            marcador="PCR_cultura_LCR",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="PCR/cultura de LCR: confirmação etiológica — casos esporádicos a investigar se cluster.",
            fonte=f,
        ),
    ]

    # --- Toxo / CMV (caveat IgG) ---
    rows += [
        _row(
            agravo_gal="Toxoplasmose",
            familia="toxoplasmose",
            padrao_exame=r"toxoplasmose.*igg|toxo.*igg",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="Toxo IgG: contato passado — não alerta agudo isolado (usar IgM/avididade).",
            fonte="LACEN / marcadores_ensaio.md",
        ),
        _row(
            agravo_gal="Toxoplasmose",
            familia="toxoplasmose",
            padrao_exame=r"toxoplasmose.*igm|toxo.*igm",
            marcador="IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="Toxo IgM: possível infecção recente — confirmar com avididade/clínica.",
            fonte="LACEN / marcadores_ensaio.md",
        ),
        _row(
            agravo_gal="CMV",
            familia="cmv",
            padrao_exame=r"(citomegalov[ií]rus|cmv).*igg",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="CMV IgG: soroprevalência — não alerta agudo isolado.",
            fonte="LACEN / marcadores_ensaio.md",
        ),
        _row(
            agravo_gal="CMV",
            familia="cmv",
            padrao_exame=r"(citomegalov[ií]rus|cmv).*igm",
            marcador="IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=False,
            conta_positividade_agregada=True,
            nota_pt="CMV IgM: possível infecção recente — contextualizar.",
            fonte="LACEN / marcadores_ensaio.md",
        ),
    ]

    # --- Moleculares genéricos (arbovírus emergentes, etc.) ---
    rows += [
        _row(
            agravo_gal="Oropouche",
            familia="arbovirose_outra",
            padrao_exame=r"oropouche",
            metodologia="molecular|pcr|biologia",
            marcador="molecular",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="Molecular Oropouche: presença/ausência do agente.",
            fonte="GAL micro / LACEN",
        ),
        _row(
            agravo_gal="Mayaro",
            familia="arbovirose_outra",
            padrao_exame=r"mayaro",
            metodologia="molecular|pcr|biologia",
            marcador="molecular",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="Molecular Mayaro: presença/ausência do agente.",
            fonte="GAL micro / LACEN",
        ),
        _row(
            agravo_gal="Genérico",
            familia="outros",
            padrao_exame=r".*",
            metodologia=r"(pcr|rt[\s\-]?pcr|biologia molecular|molecular|genexpert|naat|carga viral)",
            marcador="molecular",
            classe=CLASSE_MOL,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            n_minimo=5,
            nota_pt="Ensaio molecular genérico: presença/ausência do agente — confirmação laboratorial.",
            fonte="marcadores_ensaio.md",
        ),
        _row(
            agravo_gal="Genérico",
            familia="outros",
            padrao_exame=r"\bigg\b",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="IgG/sorologia genérica: soroprevalência — não tratar como epidemia aguda.",
            fonte="marcadores_ensaio.md",
        ),
        _row(
            agravo_gal="Genérico",
            familia="outros",
            padrao_exame=r"\bigm\b",
            marcador="IgM",
            classe=CLASSE_ATIVO,
            conta_alerta_agudo=True,
            conta_bortman=True,
            conta_positividade_agregada=True,
            nota_pt="IgM genérica: janela de infecção recente — sinal laboratorial ativo.",
            fonte="marcadores_ensaio.md",
        ),
    ]
    return rows


def catalogo_exames_micro() -> list[dict[str, str]]:
    """Catálogo único exame × metodologia × agravo do GAL micro."""
    import pandas as pd

    path = None
    for name in (
        "vw_gal_micro_recent.parquet",
        "vw_gal_micro_recent.csv",
    ):
        p = STAGE / name
        if p.exists():
            path = p
            break
    if path is None:
        return []

    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, nrows=60000, low_memory=False)

    cols = {c.casefold(): c for c in df.columns}
    c_ex = cols.get("exame")
    c_met = cols.get("metodologia")
    c_ag = cols.get("agravo_gal") or cols.get("agravo_requisicao")
    if not c_ex:
        return []

    gcols = [c for c in (c_ex, c_met, c_ag) if c]
    g = (
        df[gcols]
        .fillna("")
        .astype(str)
        .groupby(gcols, dropna=False)
        .size()
        .reset_index(name="n_registros")
    )
    g = g.sort_values("n_registros", ascending=False)
    out: list[dict[str, str]] = []
    for _, r in g.iterrows():
        out.append(
            {
                "exame": str(r.get(c_ex) or "").strip(),
                "metodologia": str(r.get(c_met) or "").strip() if c_met else "",
                "agravo_gal": str(r.get(c_ag) or "").strip() if c_ag else "",
                "n_registros": str(int(r["n_registros"])),
            }
        )
    return out


def agravos_da_positividade() -> list[dict[str, str]]:
    if not SRC_POSIT.exists():
        return []
    try:
        import pandas as pd

        df = pd.read_excel(SRC_POSIT, sheet_name="Regras_Por_Agravo")
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, str]] = []
    for _, r in df.iterrows():
        out.append(
            {
                "agravo_gal": str(r.get("Agravo") or "").strip(),
                "marcador_alerta": str(r.get("Marcador_Alerta") or "").strip(),
                "marcadores_contexto": str(r.get("Marcadores_Contexto") or "").strip(),
                "janela_diagnostica": str(r.get("Janela_Diagnostica") or "").strip(),
                "fonte_dados": str(r.get("Fonte_Dados") or "").strip(),
            }
        )
    return out


def gravar(regras: list[dict[str, str]], catalogo: list[dict[str, str]], agravos: list[dict[str, str]]) -> None:
    CONHECIMENTO.mkdir(parents=True, exist_ok=True)

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for row in regras:
            w.writerow({k: row.get(k, "") for k in COLS})

    try:
        import pandas as pd

        meta = pd.DataFrame(
            [
                {"chave": "versao", "valor": "1.0"},
                {"chave": "data", "valor": date.today().isoformat()},
                {"chave": "responsavel", "valor": "área técnica LACEN / CIEVS (editar)"},
                {
                    "chave": "fonte_mestra",
                    "valor": "conhecimento_ve/regras_agravo_gal.csv (+ xlsx)",
                },
                {
                    "chave": "origem_positividade",
                    "valor": str(SRC_POSIT.name) if SRC_POSIT.exists() else "ausente",
                },
                {"chave": "n_regras", "valor": str(len(regras))},
                {"chave": "n_catalogo_exames", "valor": str(len(catalogo))},
            ]
        )
        with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
            pd.DataFrame(regras)[COLS].to_excel(xw, sheet_name="Regras", index=False)
            pd.DataFrame(agravos or [{"agravo_gal": ""}]).to_excel(
                xw, sheet_name="Agravos_GAL", index=False
            )
            pd.DataFrame(catalogo or [{"exame": ""}]).to_excel(
                xw, sheet_name="Catalogo_Exames", index=False
            )
            meta.to_excel(xw, sheet_name="Metadados", index=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[AVISO] XLSX não gerado ({exc}); CSV ok em {OUT_CSV}")


def main() -> None:
    regras = regras_seed()
    catalogo = catalogo_exames_micro()
    agravos = agravos_da_positividade()
    if not agravos and catalogo:
        # fallback: agravos únicos do micro
        seen: set[str] = set()
        for c in catalogo:
            a = c.get("agravo_gal") or ""
            if a and a not in seen:
                seen.add(a)
                agravos.append({"agravo_gal": a, "marcador_alerta": "", "fonte_dados": "GAL micro"})
        # também prefixos de exame
        for c in catalogo[:80]:
            ex = c.get("exame") or ""
            head = re.split(r"[,;]", ex)[0].strip()
            if head and head not in seen:
                seen.add(head)
                agravos.append(
                    {
                        "agravo_gal": head,
                        "marcador_alerta": "",
                        "fonte_dados": "GAL micro (exame)",
                    }
                )

    gravar(regras, catalogo, agravos)
    print(f"Regras: {len(regras)}")
    print(f"Catálogo exames: {len(catalogo)}")
    print(f"Agravos: {len(agravos)}")
    print(f"CSV: {OUT_CSV}")
    print(f"XLSX: {OUT_XLSX} (exists={OUT_XLSX.exists()})")


if __name__ == "__main__":
    main()
