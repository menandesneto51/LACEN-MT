# -*- coding: utf-8 -*-
from pathlib import Path
import importlib.util


def _load_apply_mod():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "aplicar_aprovacao_institucional_v2_1.py"
    spec = importlib.util.spec_from_file_location("aplicar_aprovacao", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_endorsement_rejects_chat_authorization():
    mod = _load_apply_mod()
    payload = {
        "schema_version": "v2.1-endorsement-1",
        "automatic_decision_allowed": False,
        "DEC-001": {
            "alternative": "A",
            "historical_series": "nao_reprocessar",
        },
        "DEC-002": {
            "source_priority": ["DW:POPULACAO_TOTAL"],
            "allow_previous_year": False,
        },
        "signers": {
            "responsavel_institucional": {
                "name": "Autorizacao explicita no chat Cursor",
                "role_title": "Gestor",
                "signed_at": "2026-09-27",
            },
            "clinical_epidemiological": {
                "name": "Fulano da Silva",
                "role_title": "Epidemiologista",
                "signed_at": "2026-09-27",
            },
            "data_governance": {
                "name": "Beltrano Souza",
                "role_title": "Governanca",
                "signed_at": "2026-09-27",
            },
        },
    }
    errors = mod.validate_endorsement(payload)
    assert any("chat" in e.casefold() or "agente" in e.casefold() for e in errors)


def test_endorsement_accepts_named_institutional_signers():
    mod = _load_apply_mod()
    payload = {
        "schema_version": "v2.1-endorsement-1",
        "automatic_decision_allowed": False,
        "DEC-001": {
            "alternative": "A",
            "historical_series": "nao_reprocessar",
            "rationale": "Preservar serie atual.",
        },
        "DEC-002": {
            "source_priority": ["DW:POPULACAO_TOTAL"],
            "allow_previous_year": False,
            "allow_unlisted_sources": False,
        },
        "signers": {
            "responsavel_institucional": {
                "name": "Maria Aparecida Exemplo",
                "role_title": "Diretora LACEN-MT",
                "signed_at": "2026-09-27",
            },
            "clinical_epidemiological": {
                "name": "Joao Epidemiologista Exemplo",
                "role_title": "Referencia VE",
                "signed_at": "2026-09-27",
            },
            "data_governance": {
                "name": "Ana Governanca Exemplo",
                "role_title": "Gestao de dados",
                "signed_at": "2026-09-27",
            },
        },
    }
    assert mod.validate_endorsement(payload) == []
