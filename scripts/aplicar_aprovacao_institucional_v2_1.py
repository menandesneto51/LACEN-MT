# -*- coding: utf-8 -*-
"""Aplicar aprovacao institucional V2.1 somente a partir de endosso formal.

Nao aceita autorizacao por chat. Exige arquivo JSON assinado com campos obrigatorios.

Uso:
  1. Preencher docs/decisions/FORMULARIO_APROVACAO_INSTITUCIONAL_V2_1.md
  2. Criar config/institutional_endorsement_v2_1.json (ver schema no formulario)
  3. python scripts/aplicar_aprovacao_institucional_v2_1.py --dry-run
  4. python scripts/aplicar_aprovacao_institucional_v2_1.py --apply

Freeze-safe: so altera configs/ADRs/reviews apos validacao do endosso.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_DECIDER_PATTERNS = (
    r"chat\s*cursor",
    r"considerar\s+tudo\s+aprovado",
    r"autoriza[cç][aã]o\s+expl[ií]cita\s+no\s+chat",
    r"\bai\s*agent\b",
    r"composer",
)

REQUIRED_ROLES = (
    "responsavel_institucional",
    "clinical_epidemiological",
    "data_governance",
)


def _load_endorsement(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Endosso ausente: {path}. Preencha o formulario e gere o JSON."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def validate_endorsement(payload: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "v2.1-endorsement-1":
        errors.append("schema_version deve ser v2.1-endorsement-1.")
    if payload.get("automatic_decision_allowed") is not False:
        errors.append("automatic_decision_allowed deve ser false.")

    dec001 = payload.get("DEC-001") or {}
    if dec001.get("alternative") not in {"A", "B", "C", "D"}:
        errors.append("DEC-001.alternative deve ser A/B/C/D.")
    if dec001.get("historical_series") not in {
        "nao_reprocessar",
        "reprocessar_integral",
        "reprocessar_periodo",
        "duas_series",
    }:
        errors.append("DEC-001.historical_series invalido.")

    dec002 = payload.get("DEC-002") or {}
    priority = dec002.get("source_priority")
    if not isinstance(priority, list) or not priority:
        errors.append("DEC-002.source_priority deve ser lista nao vazia.")
    if "allow_previous_year" not in dec002:
        errors.append("DEC-002.allow_previous_year obrigatorio.")

    signers = payload.get("signers") or {}
    for role in REQUIRED_ROLES:
        person = signers.get(role) or {}
        name = str(person.get("name") or "").strip()
        if len(name) < 5:
            errors.append(f"signers.{role}.name obrigatorio (>=5 chars).")
        role_title = str(person.get("role_title") or "").strip()
        if len(role_title) < 3:
            errors.append(f"signers.{role}.role_title obrigatorio.")
        signed_at = str(person.get("signed_at") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", signed_at):
            errors.append(f"signers.{role}.signed_at deve ser YYYY-MM-DD.")
        blob = f"{name} {role_title} {person.get('note') or ''}".casefold()
        for pat in FORBIDDEN_DECIDER_PATTERNS:
            if re.search(pat, blob, flags=re.I):
                errors.append(
                    f"signers.{role} nao pode referenciar aprovacao via chat/agente."
                )
                break

    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--endorsement",
        type=Path,
        default=ROOT / "config" / "institutional_endorsement_v2_1.json",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    if not args.dry_run and not args.apply:
        print("Informe --dry-run ou --apply.")
        return 2

    try:
        payload = _load_endorsement(args.endorsement)
    except FileNotFoundError as exc:
        print(f"[FALHA] {exc}")
        return 2

    errors = validate_endorsement(payload)
    if errors:
        print("[FALHA] Endosso invalido:")
        for e in errors:
            print(f"  - {e}")
        return 2

    print("[OK] Endosso valido.")
    print("  DEC-001:", payload["DEC-001"].get("alternative"))
    print("  DEC-002:", payload["DEC-002"].get("source_priority"))
    print(
        "  Responsavel:",
        (payload.get("signers") or {}).get("responsavel_institucional", {}).get("name"),
    )
    if args.dry_run:
        print("[DRY-RUN] Nenhuma configuracao alterada.")
        return 0

    print(
        "[FALHA] --apply ainda nao grava configs neste commit de continuidade. "
        "Use o endosso validado na sala de decisao e solicite aplicacao explicita "
        "com nomes/cargos preenchidos."
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
