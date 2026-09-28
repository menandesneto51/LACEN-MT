from pathlib import Path
import json
from importlib.util import spec_from_file_location, module_from_spec


def _load():
    root = Path(__file__).resolve().parents[1]
    spec = spec_from_file_location(
        "dossier", root / "scripts" / "gerar_dossier_sala_decisao_v2_1.py"
    )
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dossier_does_not_auto_decide(tmp_path: Path):
    (tmp_path / "decision_readiness_v2_1.json").write_text(
        json.dumps(
            {
                "overall_status": "READY_FOR_HUMAN_DECISION",
                "decisions": {
                    "DEC-001": {"status": "READY_FOR_HUMAN_DECISION"},
                    "DEC-002": {"status": "READY_FOR_HUMAN_DECISION"},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "gal_temporal_anchor_summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "population_source_comparison_summary.json").write_text(
        "{}", encoding="utf-8"
    )
    text = _load().build_dossier(tmp_path)
    assert "proibida" in text.casefold()
    assert "READY_FOR_HUMAN_DECISION" in text
    assert "- [x]" not in text
