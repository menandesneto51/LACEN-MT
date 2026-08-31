#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera conhecimento_ve/regras_agravo_gal.xlsx (+ CSV) com cobertura 100% do
GAL micro (Exame × Metodologia), alinhada a princípios do MS (IgG≠aguda;
molecular=presença; triagem crônica ≠ epidemia).

Também grava saida_pipeline/cobertura_regras_gal.csv e
saida_pipeline/catalogo_gal_exame_met_agravo.csv.

Uso:
  python scripts/gerar_regras_agravo_gal.py
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONHECIMENTO = ROOT / "conhecimento_ve"
OUTDIR = ROOT / "saida_pipeline"
OUT_XLSX = CONHECIMENTO / "regras_agravo_gal.xlsx"
OUT_CSV = CONHECIMENTO / "regras_agravo_gal.csv"
OUT_COB = OUTDIR / "cobertura_regras_gal.csv"
OUT_CAT = OUTDIR / "catalogo_gal_exame_met_agravo.csv"
SRC_POSIT = CONHECIMENTO / "Positividade_Por_Agravo_GAL.xlsx"
STAGE = OUTDIR / "staging_dw"

COLS = [
    "agravo_gal",
    "familia",
    "agravo_requisicao",
    "exame_gal_exato",
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
    "validacao_ms",
]

CLASSE_NAO = "nao_agudo_soroprevalencia"
CLASSE_ATIVO = "sinal_agudo_ou_ativo"
CLASSE_MOL = "molecular_presenca_ausencia"
CLASSE_INDET = "indeterminado"

F_MS = "Guia MS / notificaveis_resumo / Positividade_Por_Agravo_GAL"
F_LACEN = "LACEN / princípios MS (marcador agudo vs cicatriz)"
F_REV = "revisar_area_tecnica — sem definição aguda inequívoca no nome"


def _tf(v: bool) -> str:
    return "true" if v else "false"


def _cf(text: object) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    for a, b in (
        ("á", "a"),
        ("à", "a"),
        ("ã", "a"),
        ("â", "a"),
        ("é", "e"),
        ("ê", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ô", "o"),
        ("õ", "o"),
        ("ú", "u"),
        ("ç", "c"),
    ):
        t = t.replace(a, b)
    return t


def _row(**kw: object) -> dict[str, str]:
    return {
        "agravo_gal": str(kw.get("agravo_gal") or ""),
        "familia": str(kw.get("familia") or ""),
        "agravo_requisicao": str(kw.get("agravo_requisicao") or ""),
        "exame_gal_exato": str(kw.get("exame_gal_exato") or ""),
        "padrao_exame": str(kw.get("padrao_exame") or ""),
        "metodologia": str(kw.get("metodologia") or ""),
        "marcador": str(kw.get("marcador") or ""),
        "classe": str(kw.get("classe") or CLASSE_INDET),
        "conta_alerta_agudo": _tf(bool(kw.get("conta_alerta_agudo"))),
        "conta_bortman": _tf(bool(kw.get("conta_bortman"))),
        "conta_positividade_agregada": _tf(bool(kw.get("conta_positividade_agregada"))),
        "n_minimo": str(int(kw.get("n_minimo") or 3)),
        "nota_pt": str(kw.get("nota_pt") or ""),
        "fonte": str(kw.get("fonte") or F_LACEN),
        "validacao_ms": str(kw.get("validacao_ms") or "parcial"),
    }


def _nao(marcador: str, nota: str, *, familia: str, agravo: str, validacao: str = "ok") -> dict:
    return dict(
        familia=familia,
        agravo_gal=agravo,
        marcador=marcador,
        classe=CLASSE_NAO,
        conta_alerta_agudo=False,
        conta_bortman=False,
        conta_positividade_agregada=False,
        nota_pt=nota,
        fonte=F_MS,
        validacao_ms=validacao,
    )


def _ativo(
    marcador: str,
    nota: str,
    *,
    familia: str,
    agravo: str,
    bortman: bool = True,
    validacao: str = "ok",
    n_minimo: int = 3,
) -> dict:
    return dict(
        familia=familia,
        agravo_gal=agravo,
        marcador=marcador,
        classe=CLASSE_ATIVO,
        conta_alerta_agudo=True,
        conta_bortman=bortman,
        conta_positividade_agregada=True,
        nota_pt=nota,
        fonte=F_MS,
        validacao_ms=validacao,
        n_minimo=n_minimo,
    )


def _mol(
    marcador: str,
    nota: str,
    *,
    familia: str,
    agravo: str,
    validacao: str = "ok",
    n_minimo: int = 3,
    bortman: bool = True,
) -> dict:
    return dict(
        familia=familia,
        agravo_gal=agravo,
        marcador=marcador,
        classe=CLASSE_MOL,
        conta_alerta_agudo=True,
        conta_bortman=bortman,
        conta_positividade_agregada=True,
        nota_pt=nota,
        fonte=F_MS,
        validacao_ms=validacao,
        n_minimo=n_minimo,
    )


def _indet(
    marcador: str,
    nota: str,
    *,
    familia: str,
    agravo: str,
    validacao: str = "revisar_area_tecnica",
) -> dict:
    return dict(
        familia=familia,
        agravo_gal=agravo,
        marcador=marcador,
        classe=CLASSE_INDET,
        conta_alerta_agudo=False,
        conta_bortman=False,
        conta_positividade_agregada=False,
        nota_pt=nota,
        fonte=F_REV,
        validacao_ms=validacao,
    )


def _eh_molecular(exame: str, met: str) -> bool:
    blob = f"{_cf(exame)} {_cf(met)}"
    keys = (
        "pcr",
        "rt-pcr",
        "rt pcr",
        "biologia molecular",
        "molecular",
        "genexpert",
        "naat",
        "carga viral",
        "nested pcr",
        "sequenciamento",
        "dna ",
        "rna ",
    )
    return any(k in blob for k in keys)


def classificar_ensaio_ms(exame: str, metodologia: str = "", agravo_req: str = "") -> dict:
    """
    Classificação MS-aligned por nome do ensaio GAL.
    Retorna kwargs para _row (sem exame_gal_exato / padrao).
    """
    ex = str(exame or "").strip()
    met = str(metodologia or "").strip()
    agr = str(agravo_req or "").strip()
    e = _cf(ex)
    m = _cf(met)
    a = _cf(agr)

    # --- Hepatite B painel ---
    if "hepatite b" in e or "hbv" in e:
        if "anti hbs" in e or "anti-hbs" in e:
            return _nao(
                "anti_HBs",
                "Anti-HBs: imunidade vacinal ou contato passado — não infecção aguda.",
                familia="hepatite_b",
                agravo="Hepatite B",
            )
        if "igm" in e and "hbc" in e:
            return _ativo(
                "anti_HBc_IgM",
                "Anti-HBc IgM: marcador de infecção aguda (ou reativação) — sinal para a VE.",
                familia="hepatite_b",
                agravo="Hepatite B",
            )
        if "anti hbc" in e:
            return _nao(
                "anti_HBc_total",
                "Anti-HBc total: contato passado/crônico — não basta sozinho para alerta agudo.",
                familia="hepatite_b",
                agravo="Hepatite B",
            )
        if "hbsag" in e or "hbs ag" in e:
            return _ativo(
                "HBsAg",
                "HBsAg: infecção ativa (aguda ou crônica) — cruzar com IgM, DNA e notificação.",
                familia="hepatite_b",
                agravo="Hepatite B",
            )
        if "dna" in e or "pesquisa quantitativa" in e:
            return _mol(
                "HBV_DNA",
                "HBV-DNA: presença/ausência do vírus — confirmatório de replicação.",
                familia="hepatite_b",
                agravo="Hepatite B",
            )
        if "hbeag" in e:
            return _ativo(
                "HBeAg",
                "HBeAg: marcador de replicação — contextualizar com DNA e clínica.",
                familia="hepatite_b",
                agravo="Hepatite B",
                bortman=False,
            )
        if "anti hbe" in e:
            return _indet(
                "anti_HBe",
                "Anti-HBe: fase da infecção — interpretar no painel completo (não alerta isolado).",
                familia="hepatite_b",
                agravo="Hepatite B",
                validacao="parcial",
            )

    # --- Hepatite C ---
    if "hepatite c" in e or "hcv" in e:
        if "rna" in e or "pesquisa quantitativa" in e or _eh_molecular(ex, met):
            return _mol(
                "HCV_RNA",
                "RNA HCV: presença/ausência do vírus — confirma infecção ativa.",
                familia="hepatite_c",
                agravo="Hepatite C",
            )
        if "anti hcv" in e or "anti-hcv" in e:
            return _nao(
                "anti_HCV",
                "Anti-HCV: exposição/cicatriz possível — não alerta agudo sem RNA/clínica.",
                familia="hepatite_c",
                agravo="Hepatite C",
            )

    # --- Hepatite A ---
    if "hepatite a" in e or "hav" in e:
        if "igm" in e:
            return _ativo(
                "anti_HAV_IgM",
                "Anti-HAV IgM: compatível com hepatite A aguda — sinal para a VE.",
                familia="hepatite_a",
                agravo="Hepatite A",
            )
        if "igg" in e:
            return _nao(
                "anti_HAV_IgG",
                "Anti-HAV IgG: imunidade/contato passado — não alerta agudo.",
                familia="hepatite_a",
                agravo="Hepatite A",
            )

    # --- Hepatite D ---
    if "hepatite d" in e or "hdv" in e:
        if "rna" in e or _eh_molecular(ex, met):
            return _mol(
                "HDV_RNA",
                "RNA HDV: presença/ausência — contextualizar com HBV.",
                familia="hepatite_d",
                agravo="Hepatite D",
            )
        return _nao(
            "anti_HDV",
            "Anti-HDV total: exposição — não basta sozinho para alerta agudo.",
            familia="hepatite_d",
            agravo="Hepatite D",
            validacao="parcial",
        )

    # --- Dengue / Chik / Zika ---
    if e.startswith("dengue") or ", dengue" in e or e == "dengue":
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "IgG dengue: soroprevalência — não alerta agudo isolado.",
                familia="dengue",
                agravo="Dengue",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "IgM dengue: infecção recente — sinal para investigação.",
                familia="dengue",
                agravo="Dengue",
            )
        if "ns1" in e:
            return _ativo(
                "NS1",
                "NS1: fase virêmica — sinal agudo.",
                familia="dengue",
                agravo="Dengue",
            )

    if "chikung" in e:
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "IgG chikungunya: exposição pretérita — não alerta agudo isolado.",
                familia="chikungunya",
                agravo="Chikungunya",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "IgM chikungunya: infecção recente — sinal ativo.",
                familia="chikungunya",
                agravo="Chikungunya",
            )

    if e.startswith("zika") or "zika," in e:
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "IgG zika: soroprevalência — não alerta agudo isolado.",
                familia="zika",
                agravo="Zika",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "IgM zika: infecção recente — sinal para investigação.",
                familia="zika",
                agravo="Zika",
            )

    if "pesquisa de arbovirus" in e or "zdc" in e:
        return _mol(
            "PCR_arbovirose",
            "Painel arbovírus (ZDC): presença/ausência — confirmação laboratorial.",
            familia="dengue",
            agravo="Arbovírus (ZDC)",
        )

    # Arbovírus emergentes moleculares
    for nome, fam, ag in (
        ("oropouche", "arbovirose_outra", "Oropouche"),
        ("mayaro", "arbovirose_outra", "Mayaro"),
        ("saint louis", "arbovirose_outra", "Encefalite Saint Louis"),
        ("nilo ocidental", "arbovirose_outra", "Febre do Nilo Ocidental"),
        ("febre amarela", "febre_amarela", "Febre Amarela"),
        ("hantavirus", "hantavirose", "Hantavirose"),
    ):
        if nome in e:
            if "igg" in e and "igm" not in e:
                return _nao(
                    "IgG",
                    f"IgG {ag}: soroprevalência — não alerta agudo isolado.",
                    familia=fam,
                    agravo=ag,
                )
            if "igm" in e:
                return _ativo(
                    "IgM",
                    f"IgM {ag}: infecção recente — sinal para a VE.",
                    familia=fam,
                    agravo=ag,
                )
            if _eh_molecular(ex, met) or "biologia molecular" in e:
                return _mol(
                    "molecular",
                    f"Molecular {ag}: presença/ausência do agente.",
                    familia=fam,
                    agravo=ag,
                )

    # --- Tuberculose ---
    if "tubercul" in e or "trm" in e:
        if "teste rapido molecular" in e or "trm" in e:
            return _mol(
                "TRM_TB",
                "TRM-TB: confirmação molecular — sinal laboratorial ativo (MS/PNCT).",
                familia="tuberculose",
                agravo="Tuberculose",
            )
        if "baciloscopia" in e or "baar" in e:
            return _ativo(
                "BAAR",
                "BAAR/baciloscopia: bacilífero potencial — cruzar com SINAN.",
                familia="tuberculose",
                agravo="Tuberculose",
            )
        if "cultura" in e:
            return _ativo(
                "cultura_TB",
                "Cultura para micobactérias: padrão-ouro confirmatório.",
                familia="tuberculose",
                agravo="Tuberculose",
            )
        if "lf-lam" in e or "lf lam" in e or "lam" in e:
            return _ativo(
                "LF_LAM",
                "LF-LAM: antígeno urinário — sinal auxiliar em TB (contextualizar).",
                familia="tuberculose",
                agravo="Tuberculose",
                validacao="parcial",
            )
        if "sensibilidade" in e or "tsa" in e:
            return _indet(
                "TSA_TB",
                "Teste de sensibilidade TB: resultado operacional — não taxa de epidemia.",
                familia="tuberculose",
                agravo="Tuberculose",
                validacao="parcial",
            )
        # "Tuberculose" ELISA genérico — frequentemente IGRA/sorologia de apoio
        if "enzimaimunoensaio" in m or "elisa" in m:
            return _indet(
                "sorologia_TB",
                "Ensaio sorológico TB: não substitui BAAR/TRM/cultura para alerta epidêmico.",
                familia="tuberculose",
                agravo="Tuberculose",
                validacao="parcial",
            )

    # --- Meningite ---
    if "meningit" in e:
        if "sorotipagem" in e or "tipagem" in e or "tsa" in e:
            return _indet(
                "tipagem_meningite",
                "Tipagem/TSA meningite: apoio laboratorial — cluster exige clínica+VE.",
                familia="meningite",
                agravo="Meningite",
                validacao="parcial",
            )
        if "microscopia" in e or "gram" in m:
            return _ativo(
                "microscopia_LCR",
                "Microscopia/Gram de LCR: sinal laboratorial — investigar com PCR/cultura.",
                familia="meningite",
                agravo="Meningite",
                bortman=False,
                validacao="parcial",
            )
        if _eh_molecular(ex, met) or "cultura" in e or "cultura" in m:
            return _mol(
                "PCR_cultura_LCR",
                "PCR/cultura LCR: confirmação etiológica — investigar se agregação.",
                familia="meningite",
                agravo="Meningite",
            )
        return _ativo(
            "meningite",
            "Meningite: ensaio a revisar com método — sinal potencial para VE.",
            familia="meningite",
            agravo="Meningite",
            validacao="parcial",
        )

    # --- Hanseníase ---
    if "hanseniase" in e:
        if "sensibilidade" in e or "lpa" in m:
            return _indet(
                "TSA_hanseniase",
                "Sensibilidade genotípica hanseníase: operacional — não epidemia.",
                familia="hanseniase",
                agravo="Hanseníase",
                validacao="parcial",
            )
        if _eh_molecular(ex, met):
            return _mol(
                "PCR_hanseniase",
                "PCR hanseníase: presença do agente — cruzar com clínica/SINAN.",
                familia="hanseniase",
                agravo="Hanseníase",
            )
        return _ativo(
            "BAAR_hanseniase",
            "Baciloscopia hanseníase: sinal laboratorial ativo — VE/SINAN.",
            familia="hanseniase",
            agravo="Hanseníase",
        )

    # --- Raiva (alto impacto) ---
    if e == "raiva" or e.startswith("raiva"):
        return _ativo(
            "raiva",
            "Raiva: qualquer positivo prioriza investigação imediata (não declarar surto só com lab).",
            familia="raiva",
            agravo="Raiva",
            n_minimo=1,
        )

    # --- Chagas ---
    if "chagas" in e:
        if "igg" in e:
            return _nao(
                "IgG",
                "Chagas IgG: infecção crônica/passada frequente — não alerta agudo isolado.",
                familia="chagas",
                agravo="Doença de Chagas",
            )
        # Quimioluminescência genérica = triagem
        return _nao(
            "sorologia_chagas",
            "Sorologia Chagas (triagem): cicatriz/crônica possível — confirmar algoritmo MS.",
            familia="chagas",
            agravo="Doença de Chagas",
            validacao="parcial",
        )

    # --- Toxo / CMV ---
    if "toxoplasmose" in e or "toxo" in e:
        if "avidez" in e:
            return _indet(
                "avidez_IgG",
                "Avidez IgG toxo: diferencia infecção recente vs antiga — interpretar com IgM.",
                familia="toxoplasmose",
                agravo="Toxoplasmose",
                validacao="parcial",
            )
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "Toxo IgG: contato passado — não alerta agudo isolado.",
                familia="toxoplasmose",
                agravo="Toxoplasmose",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "Toxo IgM: possível infecção recente — confirmar avididade/clínica.",
                familia="toxoplasmose",
                agravo="Toxoplasmose",
            )

    if "citomegalovirus" in e or "cmv" in e:
        if "avidez" in e:
            return _indet(
                "avidez_IgG",
                "Avidez IgG CMV: apoio à interpretação de infecção recente.",
                familia="cmv",
                agravo="CMV",
                validacao="parcial",
            )
        if "dna" in e or _eh_molecular(ex, met):
            return _mol(
                "CMV_DNA",
                "DNA CMV: presença/ausência — confirmatório.",
                familia="cmv",
                agravo="CMV",
            )
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "CMV IgG: soroprevalência — não alerta agudo isolado.",
                familia="cmv",
                agravo="CMV",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "CMV IgM: possível infecção recente — contextualizar.",
                familia="cmv",
                agravo="CMV",
                bortman=False,
            )

    # --- LV / LT ---
    if "leishmaniose visceral" in e:
        if "teste rapido" in e or "total" in e or "enzimaimunoensaio" in m:
            return _ativo(
                "sorologia_LV",
                "Sorologia/TR LV: sinal laboratorial — cruzar clínica/SINAN (não surto automático).",
                familia="leishmaniose_visceral",
                agravo="Leishmaniose Visceral",
                validacao="parcial",
            )
    if "leishmaniose tegumentar" in e:
        if "igg" in e:
            return _nao(
                "IgG",
                "LT IgG: exposição — não alerta epidêmico isolado.",
                familia="leishmaniose_tegumentar",
                agravo="Leishmaniose Tegumentar",
                validacao="parcial",
            )

    # --- Leptospirose ---
    if "leptospirose" in e:
        if "igm" in e:
            return _ativo(
                "IgM",
                "Leptospirose IgM: infecção recente possível — confirmar MAT/clínica.",
                familia="leptospirose",
                agravo="Leptospirose",
            )
        if "mat" in e or "mat" in m or "aglutinacao" in m:
            return _ativo(
                "MAT",
                "MAT leptospirose: confirmação sorológica — sinal para VE.",
                familia="leptospirose",
                agravo="Leptospirose",
            )

    # --- COVID / respiratórios / influenza ---
    if "covid" in e or "sars" in e:
        if "igg" in e:
            return _nao(
                "IgG",
                "IgG COVID: soroprevalência — não alerta agudo operacional.",
                familia="covid19",
                agravo="COVID-19",
            )
        if _eh_molecular(ex, met) or "antigeno" in e:
            return _mol(
                "PCR_covid",
                "COVID molecular/antígeno: presença — sinal agudo em sintomáticos.",
                familia="covid19",
                agravo="COVID-19",
            )

    if "virus respiratorio" in e or e == "influenza" or "influenza" in e:
        return _mol(
            "painel_respiratorio",
            "Vírus respiratórios/influenza: presença/ausência — não declarar epidemia só com positividade.",
            familia="respiratorio",
            agravo="Influenza / Vírus Respiratórios",
            validacao="parcial",
        )

    # --- IST / HIV / Sífilis / HTLV ---
    if "multipatogenos ist" in e or ("ist" in e and "multipatogenos" in e):
        return _mol(
            "PCR_IST",
            "Multiplex IST: presença de patógeno — investigar caso a caso (não epidemia agregada).",
            familia="ist",
            agravo="DST/IST",
            validacao="parcial",
        )
    if e == "hiv" or e.startswith("hiv"):
        return _ativo(
            "HIV",
            "HIV (triagem/confirmação): caso a caso — não usar % para epidemia municipal no Radar.",
            familia="hiv",
            agravo="HIV",
            bortman=False,
            validacao="parcial",
            n_minimo=1,
        )
    if "sifilis" in e:
        return _ativo(
            "sifilis",
            "Sífilis: reagente exige algoritmo (não-treponêmico/treponêmico) — VE/APS.",
            familia="sifilis",
            agravo="Sífilis",
            bortman=False,
            validacao="parcial",
        )
    if "htlv" in e:
        return _nao(
            "HTLV",
            "HTLV: infecção crônica/triagem — não alerta agudo epidêmico.",
            familia="htlv",
            agravo="HTLV",
            validacao="parcial",
        )

    # --- Sarampo / rubéola / varicela / varíola ---
    if "sarampo" in e:
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "Sarampo IgG: imunidade/passado — não alerta agudo.",
                familia="sarampo",
                agravo="Sarampo",
            )
        if "igm" in e or _eh_molecular(ex, met):
            return _ativo(
                "IgM_ou_PCR",
                "Sarampo IgM/PCR: sinal de infecção recente — investigar imediatamente.",
                familia="sarampo",
                agravo="Sarampo",
                n_minimo=1,
            )
    if "rubeola" in e:
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "Rubéola IgG: imunidade — não alerta agudo.",
                familia="rubeola",
                agravo="Rubéola",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "Rubéola IgM: infecção recente possível — investigar.",
                familia="rubeola",
                agravo="Rubéola",
                n_minimo=1,
            )
    if "variola" in e and "varicela" not in e:
        return _mol(
            "PCR_variola",
            "Varíola PCR: evento de alto impacto — 1 detectável prioriza resposta (não declarar sozinho).",
            familia="variola",
            agravo="Varíola",
            n_minimo=1,
        )
    if "varicela" in e:
        return _mol(
            "PCR_VZV",
            "Varicela/VZV molecular: presença do agente — contextualizar surto institucional.",
            familia="varicela",
            agravo="Varicela",
            validacao="parcial",
        )

    # --- Febre maculosa / brucelose / etc. ---
    if "febre maculosa" in e or "ricketts" in e:
        if _eh_molecular(ex, met):
            return _mol(
                "PCR_rickettsia",
                "PCR febre maculosa: presença — investigar (doença de notificação).",
                familia="febre_maculosa",
                agravo="Febre Maculosa",
                n_minimo=1,
            )
        return _ativo(
            "sorologia_pareada",
            "Sorologia febre maculosa (amostra): interpretar pareamento — sinal para VE.",
            familia="febre_maculosa",
            agravo="Febre Maculosa",
            validacao="parcial",
            n_minimo=1,
        )

    if "brucelose" in e:
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "Brucelose IgG: exposição passada possível — não alerta agudo isolado.",
                familia="brucelose",
                agravo="Brucelose",
            )
        if "igm" in e or "rosa bengala" in e or "rosa bengala" in m:
            return _ativo(
                "IgM_ou_RB",
                "Brucelose IgM/Rosa Bengala: sinal — confirmar e notificar.",
                familia="brucelose",
                agravo="Brucelose",
                validacao="parcial",
            )

    # --- Parasitos / micológicos ---
    if "esquistossomose" in e:
        if "sorologia" in e:
            return _nao(
                "sorologia",
                "Esquistossomose sorologia: exposição — Kato-Katz confirma carga.",
                familia="esquistossomose",
                agravo="Esquistossomose",
                validacao="parcial",
            )
        return _ativo(
            "Kato_Katz",
            "Kato-Katz: ovos = infecção ativa — sinal para VE.",
            familia="esquistossomose",
            agravo="Esquistossomose",
        )

    if "filariose" in e:
        return _ativo(
            "filariose",
            "Filariose (antígeno/parasitológico): sinal laboratorial — investigar.",
            familia="filariose",
            agravo="Filariose",
            validacao="parcial",
            n_minimo=1,
        )

    if "malaria" in e:
        return _mol(
            "malaria",
            "Malária molecular: presença do Plasmodium — notificar/investigar.",
            familia="malaria",
            agravo="Malária",
            n_minimo=1,
        )

    if "hidatidose" in e:
        return _nao(
            "IgG",
            "Hidatidose IgG: exposição — confirmar clínica/imagem.",
            familia="hidatidose",
            agravo="Hidatidose",
            validacao="parcial",
        )

    if any(
        k in e
        for k in (
            "fungos",
            "cultura para fungos",
            "paracoccidioidomicose",
            "histoplasmose",
            "aspergilose",
            "criptococos",
            "criptococo",
        )
    ):
        if "teste rapido" in e or "criptococ" in e:
            return _ativo(
                "antigeno_criptococo",
                "Criptococo TR: sinal clínico-laboratorial — não epidemia comunitária típica.",
                familia="micose",
                agravo="Criptococose",
                bortman=False,
                validacao="parcial",
            )
        if "sensibilidade" in e:
            return _indet(
                "TSA_fungos",
                "TSA fungos: operacional — fora do Radar epidêmico.",
                familia="micose",
                agravo="Micose",
                validacao="parcial",
            )
        if "imunodifusao" in m or "paracoccidio" in e or "histoplasmose" in e or "aspergilose" in e:
            return _ativo(
                "sorologia_micose",
                "Sorologia micose profunda: sinal — investigar casos (não % epidêmica).",
                familia="micose",
                agravo=ex.split(",")[0][:40],
                bortman=False,
                validacao="parcial",
            )
        return _indet(
            "micologico",
            "Micológico direto/cultura: apoio diagnóstico — não alerta epidêmico CIEVS padrão.",
            familia="micose",
            agravo="Micose",
            validacao="parcial",
        )

    # --- Herpes / parvovirus / rotavirus / norovirus / adenovirus / bordetella ---
    if "herpes" in e:
        return _mol(
            "PCR_HSV",
            "HSV molecular: presença — caso clínico, não epidemia agregada típica.",
            familia="herpes",
            agravo="Herpes",
            bortman=False,
            validacao="parcial",
        )
    if "parvovirus" in e or "parvovirus" in e:
        if "igg" in e and "igm" not in e:
            return _nao(
                "IgG",
                "Parvovírus IgG: passado — não alerta agudo.",
                familia="parvovirus",
                agravo="Parvovirose",
            )
        if "igm" in e:
            return _ativo(
                "IgM",
                "Parvovírus IgM: infecção recente possível.",
                familia="parvovirus",
                agravo="Parvovirose",
                bortman=False,
            )
    if "rotavirus" in e or "norovirus" in e or "adenovirus" in e:
        return _mol(
            "PCR_gastro",
            "Agente diarréico molecular: presença — investigar surto institucional se cluster.",
            familia="gastroenterite",
            agravo="Doenças diarréicas",
            validacao="parcial",
        )
    if "bordetella" in e or "coqueluche" in e:
        return _mol(
            "PCR_coqueluche",
            "Bordetella/coqueluche PCR: presença — investigar contatos.",
            familia="coqueluche",
            agravo="Coqueluche",
            n_minimo=1,
        )
    if "borreliose" in e:
        return _mol(
            "PCR_borrelia",
            "Borreliose molecular: presença — investigar.",
            familia="borreliose",
            agravo="Borreliose",
            validacao="parcial",
            n_minimo=1,
        )

    # --- DCJ / prião ---
    if "prionica" in e or "creutzfeldt" in e or "14-3-3" in e:
        return _ativo(
            "proteina_14_3_3",
            "DCJ/14-3-3: evento raro de alto impacto — acionar protocolo (não surto comunitário).",
            familia="dcj",
            agravo="Doença de Creutzfeldt-Jakob",
            bortman=False,
            n_minimo=1,
            validacao="parcial",
        )

    # --- Bacteriologia operacional ---
    if "carbapenemase" in e or "genes de resistencia" in e:
        return _indet(
            "resistencia",
            "Resistência antimicrobiana (carbapenemases/genes): vigilância hospitalar — não % epidêmica municipal.",
            familia="bacteriologia",
            agravo="Infecção/colonização",
            validacao="parcial",
        )

    if e.startswith("bacterias") or "streptococcus" in e or "micobacterias" in e:
        if "cultura" in e or "hemocultura" in m or "identificacao" in e:
            return _indet(
                "cultura_bacteriana",
                "Cultura/ID bacteriana: operacional/assistencial — fora do cartão epidemia CIEVS.",
                familia="bacteriologia",
                agravo="Infecção/colonização",
                validacao="parcial",
            )
        if "sensibilidade" in e or "carbapenemase" in e or "genes de resistencia" in e:
            return _indet(
                "resistencia",
                "Resistência antimicrobiana: vigilância hospitalar — não % epidêmica municipal.",
                familia="bacteriologia",
                agravo="Infecção/colonização",
                validacao="parcial",
            )

    # --- Colinesterase (intoxicação) ---
    if "colinesterase" in e:
        return _indet(
            "colinesterase",
            "Colinesterase: marcador de exposição a organofosforados — VE toxicológica, não epidemia infecciosa.",
            familia="intoxicacao",
            agravo="Intoxicação Exógena",
            validacao="parcial",
        )

    # --- Genéricos IgG / IgM / molecular ---
    if _eh_molecular(ex, met) or "biologia molecular" in e:
        fam = a.replace(" ", "_")[:40] if a else "outros"
        return _mol(
            "molecular",
            f"Molecular ({ex[:60]}): presença/ausência do agente — confirmação laboratorial.",
            familia=fam or "outros",
            agravo=agr or ex.split(",")[0][:40],
            validacao="parcial",
        )

    if re.search(r"\bigg\b", e) and "igm" not in e and "avidez" not in e:
        return _nao(
            "IgG",
            f"IgG ({ex[:50]}): soroprevalência — não tratar como epidemia aguda.",
            familia="outros",
            agravo=agr or ex.split(",")[0][:40],
            validacao="parcial",
        )

    if re.search(r"\bigm\b", e):
        return _ativo(
            "IgM",
            f"IgM ({ex[:50]}): janela recente — sinal laboratorial para investigar.",
            familia="outros",
            agravo=agr or ex.split(",")[0][:40],
            validacao="parcial",
        )

    return _indet(
        "nao_mapeado_revisar",
        f"Ensaio «{ex[:80]}»: sem marcador agudo inequívoco no nome — revisar área técnica antes de alerta.",
        familia="outros",
        agravo=agr or ex.split(",")[0][:40] or "Outros",
        validacao="revisar_area_tecnica",
    )


def regras_padrao_fallback() -> list[dict[str, str]]:
    """Padrões genéricos (baixa prioridade) se exame novo aparecer sem linha exata."""
    return [
        _row(
            agravo_gal="Genérico",
            familia="outros",
            padrao_exame=r"\bigg\b",
            marcador="IgG",
            classe=CLASSE_NAO,
            conta_alerta_agudo=False,
            conta_bortman=False,
            conta_positividade_agregada=False,
            nota_pt="IgG genérica: soroprevalência — não epidemia aguda.",
            fonte=F_MS,
            validacao_ms="ok",
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
            nota_pt="IgM genérica: infecção recente possível — investigar.",
            fonte=F_MS,
            validacao_ms="ok",
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
            nota_pt="Molecular genérico: presença/ausência do agente.",
            fonte=F_MS,
            validacao_ms="parcial",
        ),
    ]


def catalogo_micro() -> list[dict[str, str]]:
    import pandas as pd

    path = STAGE / "vw_gal_micro_recent.parquet"
    if not path.exists():
        path = STAGE / "vw_gal_micro_recent.csv"
    if not path.exists():
        return []

    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, low_memory=False)
    df = df.fillna("")
    # catálogo com agravo
    g = (
        df.groupby(["Exame", "Metodologia", "Agravo_Requisicao"], dropna=False)
        .size()
        .reset_index(name="n_registros")
        .sort_values("n_registros", ascending=False)
    )
    OUTDIR.mkdir(parents=True, exist_ok=True)
    g.to_csv(OUT_CAT, index=False, encoding="utf-8-sig")

    # um agravo dominante por exame×met
    top = (
        g.sort_values("n_registros", ascending=False)
        .groupby(["Exame", "Metodologia"], as_index=False)
        .first()
    )
    tot = (
        df.groupby(["Exame", "Metodologia"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    top = top.merge(tot, on=["Exame", "Metodologia"], how="left")
    out: list[dict[str, str]] = []
    for _, r in top.sort_values("n", ascending=False).iterrows():
        out.append(
            {
                "exame": str(r["Exame"]).strip(),
                "metodologia": str(r["Metodologia"]).strip(),
                "agravo_requisicao": str(r["Agravo_Requisicao"]).strip(),
                "n_registros": str(int(r["n"])),
            }
        )
    return out


def gerar_regras_do_catalogo(catalogo: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    regras: list[dict[str, str]] = []
    cobertura: list[dict[str, str]] = []
    seen_exato: set[tuple[str, str]] = set()

    for c in catalogo:
        ex = c["exame"]
        met = c["metodologia"]
        key = (_cf(ex), _cf(met))
        if key in seen_exato:
            continue
        seen_exato.add(key)
        cls = classificar_ensaio_ms(ex, met, c.get("agravo_requisicao") or "")
        row = _row(
            exame_gal_exato=ex,
            metodologia="",  # match exato pelo nome; met informativa na cobertura
            padrao_exame="",
            agravo_requisicao=c.get("agravo_requisicao") or "",
            **cls,
        )
        # guardar met no campo metodologia só se útil para documentação
        row["metodologia"] = ""
        regras.append(row)
        cobertura.append(
            {
                "exame": ex,
                "metodologia": met,
                "agravo_requisicao": c.get("agravo_requisicao") or "",
                "n_registros": c.get("n_registros") or "",
                "marcador": row["marcador"],
                "classe": row["classe"],
                "conta_alerta_agudo": row["conta_alerta_agudo"],
                "conta_bortman": row["conta_bortman"],
                "conta_positividade_agregada": row["conta_positividade_agregada"],
                "validacao_ms": row["validacao_ms"],
                "fonte": row["fonte"],
                "nota_pt": row["nota_pt"],
            }
        )

    regras.extend(regras_padrao_fallback())
    return regras, cobertura


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
                "fonte_dados": str(r.get("Fonte_Dados") or "").strip(),
            }
        )
    return out


def gravar(
    regras: list[dict[str, str]],
    cobertura: list[dict[str, str]],
    agravos: list[dict[str, str]],
) -> None:
    CONHECIMENTO.mkdir(parents=True, exist_ok=True)
    OUTDIR.mkdir(parents=True, exist_ok=True)

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for row in regras:
            w.writerow({k: row.get(k, "") for k in COLS})

    cob_fields = [
        "exame",
        "metodologia",
        "agravo_requisicao",
        "n_registros",
        "marcador",
        "classe",
        "conta_alerta_agudo",
        "conta_bortman",
        "conta_positividade_agregada",
        "validacao_ms",
        "fonte",
        "nota_pt",
    ]
    with OUT_COB.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cob_fields, extrasaction="ignore")
        w.writeheader()
        for row in cobertura:
            w.writerow({k: row.get(k, "") for k in cob_fields})

    try:
        import pandas as pd

        meta = pd.DataFrame(
            [
                {"chave": "versao", "valor": "2.0"},
                {"chave": "data", "valor": date.today().isoformat()},
                {"chave": "responsavel", "valor": "área técnica LACEN / CIEVS (editar)"},
                {"chave": "n_regras", "valor": str(len(regras))},
                {"chave": "n_cobertura_exames", "valor": str(len(cobertura))},
                {
                    "chave": "principio_ms",
                    "valor": "IgG/anti-HBs/anti-HCV≠alerta; molecular=presença; lab≠surto automático",
                },
            ]
        )
        with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
            pd.DataFrame(regras)[COLS].to_excel(xw, sheet_name="Regras", index=False)
            pd.DataFrame(agravos or [{"agravo_gal": ""}]).to_excel(
                xw, sheet_name="Agravos_GAL", index=False
            )
            pd.DataFrame(cobertura).to_excel(xw, sheet_name="Catalogo_Exames", index=False)
            meta.to_excel(xw, sheet_name="Metadados", index=False)
            pd.DataFrame(cobertura).to_excel(xw, sheet_name="Cobertura", index=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[AVISO] XLSX: {exc}")


def main() -> None:
    catalogo = catalogo_micro()
    regras, cobertura = gerar_regras_do_catalogo(catalogo)
    agravos = agravos_da_positividade()
    if not agravos:
        seen: set[str] = set()
        for c in catalogo:
            a = c.get("agravo_requisicao") or ""
            if a and a not in seen:
                seen.add(a)
                agravos.append({"agravo_gal": a, "marcador_alerta": "", "fonte_dados": "GAL micro"})
    gravar(regras, cobertura, agravos)
    n_map = sum(1 for c in cobertura if c["marcador"] != "nao_mapeado_revisar")
    n_alerta = sum(1 for c in cobertura if c["conta_alerta_agudo"] == "true")
    print(f"Catálogo exames: {len(catalogo)}")
    print(f"Regras: {len(regras)} (exatas={len(cobertura)} + genéricos)")
    print(f"Mapeados (≠revisar): {n_map}/{len(cobertura)}")
    print(f"Com conta_alerta_agudo: {n_alerta}")
    print(f"CSV: {OUT_CSV}")
    print(f"Cobertura: {OUT_COB}")
    print(f"XLSX: {OUT_XLSX}")


if __name__ == "__main__":
    main()
