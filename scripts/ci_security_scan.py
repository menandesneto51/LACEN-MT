# -*- coding: utf-8 -*-
"""Varredura mínima de segurança do repositório para CI.

Foca em segredos de alta confiança. Exemplos/templates são ignorados por desenho.
Não substitui secret scanning da plataforma.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".csv", ".sql", ".bat", ".ps1", ".env",
}
IGNORE_PARTS = {".git", ".venv", "venv", "__pycache__", "node_modules"}
IGNORE_NAMES = {
    ".env.example",
    "secrets.toml.example",
}

PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[ps]_[A-Za-z0-9]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token)"
            r"\b\s*[:=]\s*['\"]?([^\s,'\";#]{8,})"
        ),
    ),
)

PLACEHOLDER_MARKERS = {
    "example", "exemplo", "troque", "changeme", "placeholder",
    "your_", "<", "dummy", "fake", "test", "teste",
}


def _iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_PARTS for part in path.parts):
            continue
        if path.name in IGNORE_NAMES or path.name.endswith(".example"):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and not path.name.startswith(".env"):
            continue
        yield path


def _is_placeholder(value: str) -> bool:
    v = value.casefold()
    return any(marker in v for marker in PLACEHOLDER_MARKERS)


def main() -> int:
    findings: list[str] = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for category, pattern in PATTERNS:
            for match in pattern.finditer(text):
                evidence = match.group(0)[:120]
                if category == "credential_assignment":
                    value = match.group(2)
                    if _is_placeholder(value):
                        continue
                findings.append(f"{category}: {path.relative_to(ROOT)}: {evidence}")

    if findings:
        print("SECURITY SCAN: BLOCK")
        for finding in findings:
            print("- " + finding)
        return 1

    print("SECURITY SCAN: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
