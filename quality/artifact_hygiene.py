# -*- coding: utf-8 -*-
"""Higiene de artefatos de qualidade — LACEN-MT V2.1.

Varre artefatos textuais gerados pelo pipeline para detectar sinais de segredo,
path local absoluto e identificadores pessoais óbvios antes de publicação/mirror.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import re


@dataclass
class HygieneFinding:
    file: str
    category: str
    status: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECRET_PATTERNS = (
    ("credential", re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*[^\s,;]+")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
)
_LOCAL_PATH_PATTERNS = (
    ("windows_path", re.compile(r"(?i)\b[A-Z]:\\(?:[^\r\n:*?\"<>|]+\\)*[^\r\n:*?\"<>|]*")),
    ("home_path", re.compile(r"(?<!\w)/(?:home|Users)/[^\s,;]+")),
)
_PII_PATTERNS = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
)


def scan_text(text: str, *, file: str = "<memory>") -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    for category, pattern in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(HygieneFinding(file, category, "BLOCK", m.group(0)[:120]))
    for category, pattern in _LOCAL_PATH_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(HygieneFinding(file, category, "WARN", m.group(0)[:120]))
    for category, pattern in _PII_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(HygieneFinding(file, category, "WARN", m.group(0)[:120]))
    return findings


def scan_quality_artifacts(quality_dir: Path | str) -> dict[str, Any]:
    root = Path(quality_dir)
    findings: list[HygieneFinding] = []
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".txt", ".json", ".md", ".csv"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            findings.extend(scan_text(text, file=path.name))

    if any(f.status == "BLOCK" for f in findings):
        status = "BLOCK"
    elif findings:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "status": status,
        "finding_count": len(findings),
        "block_count": sum(f.status == "BLOCK" for f in findings),
        "warn_count": sum(f.status == "WARN" for f in findings),
        "findings": [f.to_dict() for f in findings],
    }


def write_hygiene_report(report: dict[str, Any], outdir: Path | str) -> dict[str, Path]:
    import json

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "artifact_hygiene_v2_1.json"
    txt_path = out / "artifact_hygiene_v2_1.txt"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "LACEN-MT V2.1 — ARTIFACT HYGIENE",
        f"status: {report.get('status')}",
        f"finding_count: {report.get('finding_count')}",
        f"block_count: {report.get('block_count')}",
        f"warn_count: {report.get('warn_count')}",
    ]
    for item in report.get("findings", []):
        lines.append(
            f"- {item['status']} {item['category']} {item['file']}: {item['evidence']}"
        )
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path}
