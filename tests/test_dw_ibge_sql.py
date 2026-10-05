from types import ModuleType
import sys

import pandas as pd

import etl.dw_extract as dw


def test_gal_sql_does_not_zero_pad_ibge_codes(monkeypatch):
    columns = [
        "Data_Solicitacao_dt",
        "Municipio_Residencia_Paciente",
        "IBGE_Municipio_Residencia_Paciente",
        "Agravo_Requisicao",
        "Exame",
        "Status_Exame",
        "Campo_Resultado_1",
    ]
    monkeypatch.setattr(dw, "discover_gal_columns", lambda *args, **kwargs: columns)

    captured = {}
    fake_lacen_dw = ModuleType("lacen_dw")

    def read_sql(mode, queryable, sql):
        captured["sql"] = sql
        return pd.DataFrame()

    fake_lacen_dw.read_sql = read_sql
    monkeypatch.setitem(sys.modules, "lacen_dw", fake_lacen_dw)

    dw.extract_vw_gal_weekly_agg(
        "fake",
        object(),
        weeks_back=4,
        schema="dbo",
        view="VW_GAL",
    )

    sql = captured["sql"]
    assert "RIGHT('0000000'" not in sql
    assert "LTRIM(RTRIM(CAST([IBGE_Municipio_Residencia_Paciente] AS NVARCHAR(20)))) AS municipio_ibge" in sql
