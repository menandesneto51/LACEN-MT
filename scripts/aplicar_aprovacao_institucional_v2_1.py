# -*- coding: utf-8 -*-
"""Aplicar aprovacao institucional V2.1 somente a partir de endosso formal.

Nao aceita autorizacao por chat. Exige arquivo JSON assinado com campos obrigatorios.

Uso:
  1. Preencher docs/decisions/FORMULARIO_APROVACAO_INSTITUCIONAL_V2_1.md
  2. Criar config/institutional_endorsement_v2_1.json
  3. python scripts/aplicar_aprovacao_institucional_v2_1.py --dry-run
  4. python scripts/aplicar_aprovacao_institucional_v2_1.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
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

HIST_LABEL = {
    "nao_reprocessar": "Não reprocessar histórico",
    "reprocessar_integral": "Reprocessar histórico integralmente",
    "reprocessar_periodo": "Reprocessar apenas período definido",
    "duas_series": "Manter duas séries paralelas",
}

ALT_LABEL = {
    "A": "Solicitação como âncora única",
    "B": "Coleta como âncora única",
    "C": "Âncoras distintas por finalidade",
    "D": "Manter regra atual temporariamente e coletar mais evidências",
}


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
    if dec001.get("historical_series") not in HIST_LABEL:
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


def _decider_line(signers: dict) -> str:
    ri = signers.get("responsavel_institucional") or {}
    return f"{ri.get('name')} — {ri.get('role_title')}"


def apply_endorsement(payload: dict) -> None:
    signers = payload["signers"]
    dec001 = payload["DEC-001"]
    dec002 = payload["DEC-002"]
    decided_by = _decider_line(signers)
    decided_at = str(
        (signers.get("responsavel_institucional") or {}).get("signed_at")
    )
    alt = dec001["alternative"]
    hist = dec001["historical_series"]
    priority = list(dec002["source_priority"])
    allow_prev = bool(dec002.get("allow_previous_year"))
    allow_unlisted = bool(dec002.get("allow_unlisted_sources", False))

    decision_status = {
        "registry_version": "v2.1",
        "automatic_decision_allowed": False,
        "decisions": {
            "DEC-001": {
                "title": "Âncora temporal GAL — solicitação × coleta",
                "status": "APPROVED",
                "decided_by": decided_by,
                "decided_at": decided_at,
                "evidence": [
                    "gal_temporal_anchor_summary.json",
                    "gal_temporal_anchor_weekly_comparison.csv",
                    "decision_brief_DEC-001.md",
                    "DEC-001_evidence_packet.md",
                    "institutional_endorsement_v2_1.json",
                ],
                "decision": {
                    "alternative": alt,
                    "anchor": "solicitacao" if alt == "A" else (
                        "coleta" if alt == "B" else "por_finalidade_ou_temporario"
                    ),
                    "historical_series": hist,
                    "rationale": dec001.get("rationale") or "",
                    "adr": "docs/decisions/DEC-001-ancora-temporal-gal.md",
                    "endorsement": "config/institutional_endorsement_v2_1.json",
                },
            },
            "DEC-002": {
                "title": "Prioridade institucional das fontes populacionais",
                "status": "APPROVED",
                "decided_by": decided_by,
                "decided_at": decided_at,
                "evidence": [
                    "population_source_comparison_summary.json",
                    "population_source_coverage_detail.csv",
                    "population_source_pairwise_comparison.csv",
                    "population_governance_v2_1.json",
                    "decision_brief_DEC-002.md",
                    "DEC-002_evidence_packet.md",
                    "institutional_endorsement_v2_1.json",
                ],
                "decision": {
                    "source_priority": priority,
                    "allow_previous_year": allow_prev,
                    "allow_unlisted_sources": allow_unlisted,
                    "rationale": dec002.get("rationale") or "",
                    "adr": "docs/decisions/DEC-002-prioridade-fontes-populacionais.md",
                    "endorsement": "config/institutional_endorsement_v2_1.json",
                },
            },
        },
    }
    (ROOT / "config" / "decision_status_v2_1.json").write_text(
        json.dumps(decision_status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    pop = {
        "version": "v2.1",
        "status": "APPROVED",
        "approved_by": decided_by,
        "approved_at": decided_at,
        "analysis_scope": "municipio_ano",
        "allow_previous_year": allow_prev,
        "source_priority": priority,
        "candidate_sources": [
            "DW:VW_POPULACAO",
            "DW:POPULACAO",
            "DW:POPULACAO_TOTAL",
            "DW:POPULACAO_TCU",
        ],
        "rules": {
            "require_explicit_priority_when_multiple_sources": True,
            "require_exact_analysis_year": True,
            "reject_conflicting_values_within_source": True,
            "expose_source_and_year_in_outputs": True,
            "allow_unlisted_sources": allow_unlisted,
        },
        "decision_note": (
            f"Aprovado por {decided_by} em {decided_at} via "
            "config/institutional_endorsement_v2_1.json."
        ),
    }
    (ROOT / "config" / "population_governance_v2_1.json").write_text(
        json.dumps(pop, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Copiar endosso também para quality evidence list compatibility when replayed.
    # (arquivo canônico permanece em config/)

    clin = signers["clinical_epidemiological"]
    gov = signers["data_governance"]
    ri = signers["responsavel_institucional"]

    def _chk(option: str, chosen: str) -> str:
        return "[x]" if option == chosen else "[ ]"

    hist_checks = {
        "nao_reprocessar": _chk("nao_reprocessar", hist),
        "reprocessar_integral": _chk("reprocessar_integral", hist),
        "reprocessar_periodo": _chk("reprocessar_periodo", hist),
        "duas_series": _chk("duas_series", hist),
    }

    (ROOT / "docs" / "decisions" / "DEC-001-ancora-temporal-gal.md").write_text(
        f"""# Decisão institucional — ADR-001 Âncora temporal GAL

**Status:** APROVADA  
**Produto:** LACEN-MT V2.1  
**Decisão automática:** proibida  
**Data:** {decided_at}  
**Endosso:** `config/institutional_endorsement_v2_1.json`

## Evidências obrigatórias

Consultar `saida_pipeline/quality/gal_temporal_anchor_summary.json` e pacotes DEC-001.

## Decisão

- {_chk('A', alt)} A — Solicitação como âncora única
- {_chk('B', alt)} B — Coleta como âncora única
- {_chk('C', alt)} C — Âncoras distintas por finalidade
- {_chk('D', alt)} D — Manter regra atual temporariamente e coletar mais evidências

### Fundamentação

{dec001.get('rationale') or ALT_LABEL.get(alt, alt)}

### Tratamento da série histórica

- {hist_checks['nao_reprocessar']} Não reprocessar histórico
- {hist_checks['reprocessar_integral']} Reprocessar histórico integralmente
- {hist_checks['reprocessar_periodo']} Reprocessar apenas período definido
- {hist_checks['duas_series']} Manter duas séries paralelas

## Aprovações

- Clinical/Epidemiological Specialist: {clin.get('name')} ({clin.get('role_title')}) — {clin.get('signed_at')}
- Data Governance: {gov.get('name')} ({gov.get('role_title')}) — {gov.get('signed_at')}
- Responsável institucional pelo produto: {ri.get('name')} ({ri.get('role_title')}) — {ri.get('signed_at')}
- Data da decisão: {decided_at}
""",
        encoding="utf-8",
    )

    pri_lines = "\n".join(f"{i}. `{src}`" for i, src in enumerate(priority, 1))
    (ROOT / "docs" / "decisions" / "DEC-002-prioridade-fontes-populacionais.md").write_text(
        f"""# Decisão institucional — prioridade de fontes populacionais

**Status:** APROVADA  
**Configuração alvo:** `config/population_governance_v2_1.json`  
**Decisão automática:** proibida  
**Data:** {decided_at}  
**Endosso:** `config/institutional_endorsement_v2_1.json`

## Prioridade aprovada

{pri_lines}

## Fallback temporal

- {'[x]' if not allow_prev else '[ ]'} Proibido
- {'[x]' if allow_prev else '[ ]'} Permitido sob regra explícita

## Fontes não listadas

- {'[x]' if not allow_unlisted else '[ ]'} Bloquear uso automático
- {'[x]' if allow_unlisted else '[ ]'} Permitir sob condição explícita

### Fundamentação

{dec002.get('rationale') or ''}

## Aprovações

- Security/Data Governance: {gov.get('name')} ({gov.get('role_title')}) — {gov.get('signed_at')}
- Clinical/Epidemiological: {clin.get('name')} ({clin.get('role_title')}) — {clin.get('signed_at')}
- Responsável institucional pelo produto: {ri.get('name')} ({ri.get('role_title')}) — {ri.get('signed_at')}
- Data da decisão: {decided_at}
""",
        encoding="utf-8",
    )

    reviews_path = ROOT / "quality" / "reviews" / "v2_1_initial_reviews.json"
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    reviews["review_version"] = "v2.1-initial-10"
    clinical = reviews["reviews"]["clinical_epidemiological_specialist"]
    clinical["status"] = "PASS"
    clinical["blockers"] = []
    clinical["findings"] = list(clinical.get("findings") or []) + [
        f"DEC-001 aprovada ({alt}) por {clin.get('name')} em {clin.get('signed_at')} "
        "via institutional_endorsement_v2_1.json."
    ]
    clinical["decision"] = (
        f"PASS após endosso formal DEC-001 alternativa {alt}. "
        "Promoção automática permanece proibida."
    )
    clinical["reviewed_at"] = str(clin.get("signed_at"))
    clinical["reviewer"] = f"{clin.get('name')} ({clin.get('role_title')})"

    security = reviews["reviews"]["security_data_governance"]
    security["status"] = "PASS"
    security["blockers"] = []
    security["findings"] = list(security.get("findings") or []) + [
        f"DEC-002 aprovada com source_priority={priority} por {gov.get('name')} "
        f"em {gov.get('signed_at')} via institutional_endorsement_v2_1.json."
    ]
    security["decision"] = (
        "PASS após endosso formal da política populacional (DEC-002). "
        "Promoção automática permanece proibida."
    )
    security["reviewed_at"] = str(gov.get("signed_at"))
    security["reviewer"] = f"{gov.get('name')} ({gov.get('role_title')})"

    ca = reviews["reviews"]["chief_architect"]
    ca["decision"] = (
        "PASS arquitetural mantido. DEC-001/DEC-002 endossadas formalmente; "
        "automatic_promotion_allowed=false."
    )
    ca["reviewed_at"] = decided_at

    qa = reviews["reviews"]["qa"]
    qa["decision"] = (
        "PASS de QA mantido após endosso formal DEC-001/DEC-002. "
        "Não autoriza release automático."
    )
    qa["reviewed_at"] = decided_at

    reviews_path.write_text(
        json.dumps(reviews, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Espelho do endosso em quality/ para o Decision Registry achar a evidência.
    quality_dir = ROOT / "saida_pipeline" / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    (quality_dir / "institutional_endorsement_v2_1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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

    apply_endorsement(payload)
    print("[OK] Configs/ADRs/reviews atualizados a partir do endosso formal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
