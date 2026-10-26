# -*- coding: utf-8 -*-
"""Publicação semanal sem semana em curso; trava de envio após ETL com falha."""
import json
from datetime import date

import pandas as pd

from etl.build_weekly_from_gal import choose_se_operacional, publish_weekly_inputs


def _t(rows):
    return pd.DataFrame(rows, columns=["epi_year", "epi_week", "target", "municipio", "tests"])


def test_publish_descarta_semana_em_curso(tmp_path):
    tests = _t([(2026, 35, "dengue", "CUIABA", 10), (2026, 36, "dengue", "CUIABA", 3)])
    pos = tests.assign(positives=0, negatives=tests["tests"], positivity=0.0)
    info = publish_weekly_inputs(tests, pos, tmp_path, ate_se=(2026, 35))
    out = pd.read_csv(tmp_path / "weekly_tests_by_target_municipio.csv")
    assert out["epi_week"].tolist() == [35]
    assert info["se_max"] == "2026-SE35"


def test_se_usada_ignora_semana_em_curso():
    weekly = _t([(2026, 34, "dengue", "CUIABA", 9), (2026, 36, "dengue", "CUIABA", 3)])
    info = choose_se_operacional(weekly, hoje=date(2026, 9, 11))  # última SE completa = 35
    assert info["se_usada"] == "2026-SE34"
    assert info["se_esperada"] == "2026-SE35"


def test_envio_bloqueado_quando_etl_falhou(tmp_path):
    import scripts.enviar_relatorio_cievs as env

    (tmp_path / "validacao_etl_dw_ultimo.json").write_text(
        json.dumps({"status": "FALHA", "ts": "2026-10-26T07:00:00", "aviso": "ml falhou"}), encoding="utf-8"
    )
    assert env.main(["--outdir", str(tmp_path), "--telegram"]) == 5
    assert "FALHA" in env._bloqueio_por_etl(tmp_path)

    (tmp_path / "validacao_etl_dw_ultimo.json").write_text(json.dumps({"status": "OK"}), encoding="utf-8")
    assert env._bloqueio_por_etl(tmp_path) is None
