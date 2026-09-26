from types import ModuleType, SimpleNamespace
import sys

import pandas as pd
import pytest

import etl.run_etl_dw as pipeline


def _args(tmp_path):
    return SimpleNamespace(
        outdir=str(tmp_path),
        weeks_back=8,
        micro_days=30,
        local_year_min=2024,
        tcp_timeout=0.1,
        allow_local_fallback=False,
        skip_ml=True,
        skip_cievs=True,
        no_bulk=True,
    )


def _install_fake_mirror(monkeypatch, calls):
    fake = ModuleType("ml.mirror_dw")

    def mark(name, result=None):
        def _fn(*args, **kwargs):
            calls.append(name)
            return result
        return _fn

    fake.append_alerta_emergencia_historico = mark("mirror:append_emergencia")
    fake.append_alerta_historico = mark("mirror:append_alerta")
    fake.atualizar_desfechos = mark("mirror:desfechos")
    fake.build_executive_summaries = mark("mirror:executive")
    fake.seed_alertas_retrospectivos = mark("mirror:seed")
    fake.mirror_to_dw = mark(
        "mirror:write",
        {"dw_ok": True, "error": None, "rows": {"dummy": 1}},
    )
    monkeypatch.setitem(sys.modules, "ml.mirror_dw", fake)


def _prepare_pipeline(monkeypatch, tmp_path, weekly, calls):
    monkeypatch.setattr(
        pipeline,
        "check_dw_tcp",
        lambda timeout=0.1: (True, "fake-dw", 1433),
    )

    def fake_extract(outdir, weeks_back, micro_days):
        stage = pipeline.staging_dir(outdir)
        stage.mkdir(parents=True, exist_ok=True)
        # O runner exige a existência física do agregado; o conteúdo é
        # substituído pelo double de read_parquet abaixo.
        (stage / "vw_gal_weekly_agg.parquet").write_bytes(b"stub")
        return {
            "gal_view": "VW_GAL",
            "objects": [],
            "sources_extracted": ["VW_GAL"],
            "ts": "2026-09-26T12:00:00",
        }

    monkeypatch.setattr(pipeline, "run_extract", fake_extract)

    original_read_parquet = pipeline.pd.read_parquet

    def fake_read_parquet(path, *args, **kwargs):
        path = str(path)
        if path.endswith("vw_gal_weekly_agg.parquet"):
            return pd.DataFrame({
                "epi_year": [2026],
                "epi_week": [37],
                "municipio": ["CUIABÁ"],
                "municipio_ibge": ["5103403"],
                "agravo_raw": ["dengue"],
                "exame_raw": ["ns1"],
                "n_registros": [10],
                "n_positivos_proxy": [2],
            })
        return original_read_parquet(path, *args, **kwargs)

    monkeypatch.setattr(pipeline.pd, "read_parquet", fake_read_parquet)
    monkeypatch.setattr(
        pipeline,
        "weekly_from_dw_agg",
        lambda agg: (
            weekly[["epi_year", "epi_week", "municipio", "municipio_ibge", "target", "tests"]].copy(),
            weekly.copy(),
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "publish_weekly_inputs",
        lambda tests, pos, outdir: {"tests": "stub", "positivity": "stub"},
    )
    monkeypatch.setattr(
        pipeline,
        "build_population_dimension_from_staging",
        lambda *args, **kwargs: pd.DataFrame(),
    )

    def fake_run(args, check=False):
        command = " ".join(str(x) for x in args)
        calls.append(command)
        if "lacen_integracao_final_only.py" in command:
            weekly.to_csv(
                tmp_path / "integrated_weekly_surveillance.csv",
                index=False,
            )
        return 0

    monkeypatch.setattr(pipeline, "_run", fake_run)
    _install_fake_mirror(monkeypatch, calls)


def test_data_quality_block_stops_all_downstream_execution(monkeypatch, tmp_path):
    calls = []
    weekly = pd.DataFrame({
        "epi_year": [2026],
        "epi_week": [37],
        "municipio": ["CUIABÁ"],
        "municipio_ibge": ["5103403"],
        "target": ["dengue"],
        "tests": [1],
        "positives": [2],
    })
    _prepare_pipeline(monkeypatch, tmp_path, weekly, calls)

    with pytest.raises(RuntimeError, match="Data Quality Gate = BLOCK"):
        pipeline.run_pipeline(_args(tmp_path))

    assert any("lacen_integracao_final_only.py" in x for x in calls)
    assert not any("gerar_indicadores_rede_lacen.py" in x for x in calls)
    assert not any("gerar_indicadores_emergencia.py" in x for x in calls)
    assert not any(x.startswith("mirror:") for x in calls)
    assert not any("enviar_relatorio_cievs.py" in x for x in calls)

    validation = (tmp_path / "validacao_etl_dw_ultimo.json").read_text(
        encoding="utf-8"
    )
    assert '"data_quality_status": "BLOCK"' in validation


def test_data_quality_warn_allows_downstream_execution(monkeypatch, tmp_path):
    calls = []
    # Duplicidade gera WARN, mas contagens permanecem válidas.
    weekly = pd.DataFrame({
        "epi_year": [2026, 2026],
        "epi_week": [37, 37],
        "municipio": ["CUIABÁ", "CUIABÁ"],
        "municipio_ibge": ["5103403", "5103403"],
        "target": ["dengue", "dengue"],
        "tests": [10, 10],
        "positives": [2, 2],
    })
    _prepare_pipeline(monkeypatch, tmp_path, weekly, calls)

    report = pipeline.run_pipeline(_args(tmp_path))

    assert report["data_quality_status"] == "WARN"
    assert any("gerar_indicadores_rede_lacen.py" in x for x in calls)
    assert any("gerar_indicadores_emergencia.py" in x for x in calls)
    assert any(x.startswith("mirror:") for x in calls)
    assert not any("enviar_relatorio_cievs.py" in x for x in calls)
    assert report["data_quality_publishable"] is True
