# -*- coding: utf-8 -*-
import pandas as pd
import pytest

from etl.build_weekly_from_gal import weekly_from_dw_agg, weekly_from_local_gal
from etl.resultado_gal import (
    INDETERMINADO, NAO_CLASSIFICADO, NEGATIVO, PENDENTE, POSITIVO,
    classificar_campo, classificar_exame, sql_classe_campo,
)

CASOS = [
    ("Detectável", POSITIVO),
    ("RNA do vírus Dengue detectado", POSITIVO),
    ("Não Detectável", NEGATIVO),
    ("NÃO DETECTADO", NEGATIVO),
    ("Indetectável", NEGATIVO),
    ("Reagente", POSITIVO),
    ("Não reagente", NEGATIVO),
    ("NAO REAGENTE", NEGATIVO),
    ("IgG: Reagente; IgM: Não reagente", POSITIVO),
    ("Positivo para Influenza A; negativo para B", POSITIVO),
    ("Negativo", NEGATIVO),
    ("++", POSITIVO),
    ("Não foram encontrados BAAR", NEGATIVO),
    ("Ausência de crescimento", NEGATIVO),
    ("Indeterminado", INDETERMINADO),
    ("Inconclusivo", INDETERMINADO),
    ("Amostra inadequada", INDETERMINADO),
    ("1.250 UI/mL", None),
    ("", None),
]


@pytest.mark.parametrize("txt,esperado", CASOS)
def test_classificar_campo(txt, esperado):
    assert classificar_campo(txt) == esperado


def test_classificar_exame_regras():
    assert classificar_exame(["Não reagente", "Reagente"]) == POSITIVO
    assert classificar_exame(["Não reagente", "Indeterminado"]) == NEGATIVO
    assert classificar_exame(["", "Inconclusivo"]) == INDETERMINADO
    assert classificar_exame(["1.250 UI/mL"], liberado=True) == NAO_CLASSIFICADO
    assert classificar_exame(["", ""], liberado=False) == PENDENTE


def test_sql_equivale_ao_python():
    """O CASE gerado para o DW classifica igual ao Python (DuckDB local)."""
    duckdb = pytest.importorskip("duckdb")
    sqlglot = pytest.importorskip("sqlglot")
    q = sqlglot.transpile(f"SELECT {sql_classe_campo('Campo_Resultado_1')} AS c FROM t",
                          read="tsql", write="duckdb")[0]
    mapa = {POSITIVO: "P", NEGATIVO: "N", INDETERMINADO: "I"}
    con = duckdb.connect()
    for txt, _ in CASOS:
        con.execute("CREATE OR REPLACE TABLE t(Campo_Resultado_1 VARCHAR)")
        con.execute("INSERT INTO t VALUES (?)", [txt])
        got = con.execute(q).fetchone()[0]
        py = mapa.get(classificar_campo(txt), "X" if txt.strip() else None)
        assert got == py, txt


def test_weekly_dw_v2_usa_validos():
    agg = pd.DataFrame([{
        "epi_year": 2026, "epi_week": 36, "municipio": "cuiaba", "agravo_raw": "dengue",
        "exame_raw": "dengue, ns1", "n_registros": 100, "n_positivos": 20, "n_negativos": 60,
        "n_indeterminados": 5, "n_nao_classificados": 5, "n_pendentes": 10, "n_liberados": 90,
        "n_positivos_proxy": 20,
    }])
    _, pos = weekly_from_dw_agg(agg)
    r = pos.iloc[0]
    assert r.tests == 100 and r.positives == 20 and r.validos == 80 and r.pendentes == 10
    assert r.positivity == pytest.approx(0.25)


def test_weekly_dw_legado_compativel():
    agg = pd.DataFrame([{
        "epi_year": 2026, "epi_week": 36, "municipio": "CUIABA", "agravo_raw": "dengue",
        "exame_raw": "", "n_registros": 50, "n_positivos_proxy": 5,
    }])
    _, pos = weekly_from_dw_agg(agg)
    r = pos.iloc[0]
    assert r.positivity == pytest.approx(0.10) and pd.isna(r.validos)


def test_weekly_local_classifica_campo_a_campo(tmp_path):
    df = pd.DataFrame({
        "Data_Solicitacao_dt": ["2026-09-01"] * 4,
        "Municipio_Residencia_Paciente": ["CUIABA"] * 4,
        "Agravo_Requisicao": ["DENGUE"] * 4,
        "Exame": ["Dengue, NS1"] * 4,
        "Status_Exame": ["Liberado", "Liberado", "Liberado", "Aguardando"],
        "Campo_Resultado_1": ["Detectável", "Não detectável", "Reagente", ""],
    })
    f = tmp_path / "gal.csv"
    df.to_csv(f, index=False, encoding="latin1")
    _, pos = weekly_from_local_gal(f, year_min=2026)
    r = pos.iloc[0]
    assert (r.tests, r.positives, r.negatives, r.pendentes) == (4, 2, 1, 1)
    assert r.positivity == pytest.approx(2 / 3)
