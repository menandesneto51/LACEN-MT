# -*- coding: utf-8 -*-
"""Lineage mínimo por produto — LACEN-MT V2.1."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import json


@dataclass
class ProductLineage:
    product: str
    logical_sources: list[str]
    cutoff: str | None
    pipeline: str
    pipeline_version: str
    dependencies: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_product_lineage(
    *,
    product: str,
    logical_sources: list[str] | None,
    cutoff: str | None,
    dependencies: list[str] | None = None,
    notes: list[str] | None = None,
    pipeline: str = "etl.run_etl_dw",
    pipeline_version: str = "v2.1",
) -> ProductLineage:
    return ProductLineage(
        product=product,
        logical_sources=sorted({str(x) for x in (logical_sources or []) if str(x).strip()}),
        cutoff=cutoff,
        pipeline=pipeline,
        pipeline_version=pipeline_version,
        dependencies=list(dependencies or []),
        notes=list(notes or []),
    )


def write_lineage_registry(
    lineage: list[ProductLineage],
    outdir: Path | str,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "product_lineage_v2_1.json"
    txt_path = out / "product_lineage_v2_1.txt"

    payload = {
        "registry_version": "v2.1",
        "products": [item.to_dict() for item in lineage],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["LACEN-MT V2.1 — PRODUCT LINEAGE", ""]
    for item in lineage:
        lines += [
            f"[{item.product}]",
            f"sources: {', '.join(item.logical_sources) or '—'}",
            f"cutoff: {item.cutoff or '—'}",
            f"pipeline: {item.pipeline}@{item.pipeline_version}",
            f"dependencies: {', '.join(item.dependencies) or '—'}",
            "",
        ]
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "txt": txt_path}


def contains_absolute_local_path(value: str) -> bool:
    import re
    text = str(value)
    return bool(
        re.search(r"(?i)\b[A-Z]:\\", text)
        or re.search(r"(?<!\w)/(?:home|Users)/", text)
    )
