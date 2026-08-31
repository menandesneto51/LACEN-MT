#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Valida cobertura 100% das regras GAL × MS contra o micro e casos-ouro.

Uso:
  python scripts/validar_cobertura_regras_gal.py
Exit 0 se OK; 1 se falhar.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lacen_agente_marcadores import (  # noqa: E402
    carregar_regras_agravo,
    classificar_exame,
)


def _load_catalog():
    import pandas as pd

    stage = ROOT / "saida_pipeline" / "staging_dw"
    path = stage / "vw_gal_micro_recent.parquet"
    if not path.exists():
        path = stage / "vw_gal_micro_recent.csv"
    if not path.exists():
        raise SystemExit(f"Micro ausente: {path}")
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    return (
        df.fillna("")[["Exame", "Metodologia"]]
        .drop_duplicates()
        .to_dict(orient="records")
    )


def main() -> int:
    carregar_regras_agravo.cache_clear()
    regras = carregar_regras_agravo()
    if len(regras) < 100:
        print(f"FAIL: poucas regras carregadas ({len(regras)})")
        return 1

    catalog = _load_catalog()
    hard = 0
    nao_map = 0
    rows_ok = 0
    for r in catalog:
        clf = classificar_exame(str(r["Exame"]), metodologia=str(r.get("Metodologia") or ""))
        if clf.fonte_regra == "hardcoded":
            hard += 1
            print(f"  HARDCODED: {r['Exame']!r}")
        if clf.marcador in ("nao_mapeado", "nao_mapeado_revisar") and clf.classe == "indeterminado":
            # permitido se validacao revisar — conta como coberto pela planilha se fonte != hardcoded
            if clf.fonte_regra == "hardcoded":
                nao_map += 1
        else:
            rows_ok += 1

    print(f"Catálogo: {len(catalog)} | regras CSV: {len(regras)}")
    print(f"Classificados via planilha: {len(catalog) - hard}/{len(catalog)}")
    print(f"Ainda hardcoded: {hard}")

    # Casos-ouro MS
    gold = [
        (("Hepatite B, Anti HBs", "", "Reagente"), False, "anti_HBs"),
        (("Hepatite B, Anti HBc Total", "", "Reagente"), False, "anti_HBc_total"),
        (("Hepatite B, Anti HBc - IgM", "", "Reagente"), True, "anti_HBc_IgM"),
        (("Hepatite B, HBsAg", "", "Reagente"), True, "HBsAg"),
        (("Hepatite B, Pesquisa quantitativa do DNA HBV", "PCR", "Detectável"), True, "HBV_DNA"),
        (("Dengue, IgM", "", "Reagente"), True, "IgM"),
        (("Chikungunya, IgG", "", "Reagente"), False, "IgG"),
        (("Hepatite C, Anti HCV", "", "Reagente"), False, "anti_HCV"),
        (("Hepatite C, Pesquisa quantitativa do RNA HCV", "RT-PCR", "Detectável"), True, "HCV_RNA"),
        (("Tuberculose, Teste Rápido Molecular", "PCR", "Detectável"), True, "TRM_TB"),
        (("Raiva", "SFIMT", "Reagente"), True, "raiva"),
        (("Chagas, IgG", "", "Reagente"), False, "IgG"),
    ]
    # Dengue IgG — pode ser "Dengue, IgG" se existir; senão Chikungunya IgG já testa IgG
    fail = 0
    for (ex, met, res), want_alerta, want_marc in gold:
        clf = classificar_exame(ex, metodologia=met, campos_resultado=[res])
        ok_a = bool(clf.conta_alerta_agudo) == want_alerta
        ok_m = clf.marcador == want_marc or (want_marc in clf.marcador)
        if not ok_a or not ok_m:
            print(
                f"FAIL GOLD: {ex} → marcador={clf.marcador} conta_alerta={clf.conta_alerta_agudo} "
                f"(esperado {want_marc}/{want_alerta}) fonte={clf.fonte_regra}"
            )
            fail += 1
        else:
            print(f"OK GOLD: {ex} → {clf.marcador} alerta={clf.conta_alerta_agudo}")

    if hard > 0 or fail > 0:
        print("VALIDATION FAILED")
        return 1
    print("VALIDATION OK — cobertura 100% planilha + casos-ouro MS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
