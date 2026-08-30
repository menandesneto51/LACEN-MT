# -*- coding: utf-8 -*-
"""Busca fontes adicionais: DW leftovers (SINASC/SINAN restantes) + IndicaSUS + SISREG."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.dw_extract import (  # noqa: E402
    DW_LEFTOVER_MUST,
    SINAN_PRIORITY_VIEWS,
    connect_or_raise,
    extract_optional_view,
    list_relevant_objects,
    staging_dir,
)
from etl.external_extract import (  # noqa: E402
    run_external_extract,
    write_fontes_busca_report,
)


def main() -> None:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "saida_pipeline"
    stage = staging_dir(outdir)
    meta: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "fontes_adicionais",
        "objects": [],
        "sources_extracted": [],
        "files": {},
        "dw_leftovers": {},
    }

    leftover_ok: list[str] = []
    leftover_fail: list[str] = []
    extracted: list[str] = []

    mode, q = connect_or_raise()
    try:
        inv = list_relevant_objects(mode, q)
        meta["objects"] = inv.to_dict(orient="records")
        names = set(inv["TABLE_NAME"].astype(str).str.upper())
        existing_stems = {p.stem.upper() for p in stage.glob("*.parquet")}

        todo: list[str] = []
        for cand in list(SINAN_PRIORITY_VIEWS) + list(DW_LEFTOVER_MUST):
            if cand in names and cand not in existing_stems:
                todo.append(cand)
        for n in sorted(names):
            if n.startswith("VW_SINAN_") and n not in existing_stems and n not in todo:
                todo.append(n)
            if n == "VW_SINASC" and n not in existing_stems and n not in todo:
                todo.append(n)

        print(f"[DW] leftovers a extrair: {len(todo)} → {todo}", flush=True)
        for cand in todo:
            top = 30_000 if cand.startswith("VW_SINAN") or cand == "VW_SINASC" else 50_000
            df = extract_optional_view(mode, q, cand, top=top)
            if df is not None and not df.empty:
                safe = re.sub(r"[^a-z0-9_]+", "_", cand.lower())
                df.to_parquet(stage / f"{safe}.parquet", index=False)
                df.to_csv(stage / f"{safe}.csv", index=False, encoding="utf-8-sig")
                meta["files"][safe] = f"{safe}.parquet"
                leftover_ok.append(cand)
                extracted.append(f"dbo.{cand}")
                print(f"[DW] {cand} ← {len(df)} linhas", flush=True)
            else:
                leftover_fail.append(cand)
                print(f"[DW] fail/empty {cand}", flush=True)
        meta["sources_extracted"] = extracted
        meta["dw_leftovers"] = {
            "attempted": todo,
            "extracted_count": len(leftover_ok),
            "extracted": leftover_ok,
            "failures": leftover_fail,
        }
    finally:
        if mode == "pyodbc" and q is not None:
            try:
                q.close()
            except Exception:
                pass

    external = run_external_extract(outdir)
    meta["external"] = {
        "indicasus_ok": bool((external.get("indicasus") or {}).get("ok")),
        "sisreg_ok": bool((external.get("sisreg") or {}).get("ok")),
        "indicasus_objects": (external.get("indicasus") or {}).get("objects_listed"),
        "sisreg_objects": (external.get("sisreg") or {}).get("objects_listed"),
    }
    write_fontes_busca_report(stage, dw_meta=meta, external=external)

    # merge into extract_meta.json if present
    meta_path = stage / "extract_meta.json"
    prev = {}
    if meta_path.exists():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    prev["fontes_adicionais"] = meta
    prev["external"] = meta.get("external")
    prev["dw_leftovers"] = meta.get("dw_leftovers")
    srcs = list(prev.get("sources_extracted") or [])
    for s in extracted:
        if s not in srcs:
            srcs.append(s)
    prev["sources_extracted"] = srcs
    meta_path.write_text(json.dumps(prev, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(meta["external"], indent=2, ensure_ascii=False), flush=True)
    print(f"leftovers ok={leftover_ok} fail={leftover_fail}", flush=True)


if __name__ == "__main__":
    main()
