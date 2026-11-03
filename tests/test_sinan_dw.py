# -*- coding: utf-8 -*-
import pandas as pd
import pytest

import etl.sinan_dw as sd
from etl.epi_week import shift_se


def test_pick_columns_variantes():
    c = sd.pick_columns(["NU_NOTIFIC", "DT_NOTIFIC", "ID_MN_RESI", "SG_UF", "DT_ENCERRA"])
    assert c["date"] == "DT_NOTIFIC" and c["mun"] == "ID_MN_RESI" and c["mun_tipo"] == "codigo"
    assert c["encerramento"] == "DT_ENCERRA"
    c = sd.pick_columns(["DataNotificacao", "MunicipioResidencia", "CodigoMunicipioResidencia", "UfResidencia"])
    assert c["date"] == "DataNotificacao" and c["mun"] == "MunicipioResidencia" and c["mun_tipo"] == "nome"
    c = sd.pick_columns(["DataDosPrimeirosSintomas", "Municipio_Residencia", "ID_AGRAVO"])
    assert c["date"] == "DataDosPrimeirosSintomas" and c["agravo"] == "ID_AGRAVO"


def test_cid_e_view():
    assert sd.cid_to_target("A90") == "dengue"
    assert sd.cid_to_target("A92.0") == "chikungunya"
    assert sd.cid_to_target("B16.9") == "hepatite"
    assert sd.cid_to_target("Z99") == "outros"
    assert sd.target_from_view("VW_SINAN_HEPATITE") == "hepatite"
    assert sd.target_from_view("VW_SINAN_VIOLENCIADOMESTICASEXUALEOUOUTRAS") is None


def _master():
    return pd.DataFrame({"municipio": ["CUIABA", "VARZEA GRANDE"], "codigo_ibge": [5103403.0, 5108402.0]})


def test_normalizar_por_codigo_6_e_7_digitos():
    cod = sd.mapa_codigo_municipio(_master())
    raw = pd.DataFrame({"epi_year": [2026, 2026, 2026], "epi_week": [40, 40, 40],
                        "municipio_raw": ["510340", "5108402", "999999"], "agravo_raw": [None] * 3,
                        "notificacoes_sinan": [3, 2, 9], "encerrados_sinan": [1, 0, 0]})
    out = sd.normalizar_agg(raw, "VW_SINAN_HEPATITE", "codigo", cod)
    assert set(out["municipio"]) == {"CUIABA", "VARZEA GRANDE"}  # código desconhecido sai
    assert (out["target"] == "hepatite").all() and out["notificacoes_sinan"].sum() == 5


def test_normalizar_ficha_individual_por_cid():
    raw = pd.DataFrame({"epi_year": [2026, 2026], "epi_week": [40, 40],
                        "municipio_raw": ["Cuiabá", "Cuiabá"], "agravo_raw": ["A90", "B05"],
                        "notificacoes_sinan": [4, 1], "encerrados_sinan": [0, 0]})
    out = sd.normalizar_agg(raw, "VW_SINAN_NOTIFICACAOINDIVIDUAL", "nome", {})
    assert dict(zip(out["target"], out["notificacoes_sinan"])) == {"dengue": 4, "sarampo": 1}
    assert (out["municipio"] == "CUIABA").all()


def test_merge_substitui_so_semanas_extraidas():
    old = pd.DataFrame({"epi_year": [2026, 2026], "epi_week": [18, 40], "ano": [2026, 2026],
                        "target": ["dengue", "dengue"], "municipio": ["CUIABA", "CUIABA"],
                        "notificacoes_sinan": [10, 1], "encerrados_sinan": [0, 0]})
    new = pd.DataFrame({"epi_year": [2026], "epi_week": [40], "ano": [2026], "target": ["dengue"],
                        "municipio": ["CUIABA"], "notificacoes_sinan": [7], "encerrados_sinan": [0]})
    m = sd.merge_sinan_weekly(old, new)
    assert dict(zip(m["epi_week"], m["notificacoes_sinan"])) == {18: 10, 40: 7}


def test_status_sinan_atraso():
    s = pd.DataFrame({"epi_year": [2026], "epi_week": [19], "notificacoes_sinan": [5]})
    st = sd.status_sinan(s, (2026, 36))
    assert st["sinan_se_max"] == "2026-SE19" and st["sinan_atraso_se"] == 17 and not st["sinan_ok"]
    assert sd.status_sinan(s, (2026, 20))["sinan_ok"]


def test_sql_agg_valido():
    sqlglot = pytest.importorskip("sqlglot")
    cols = {"date": "DT_NOTIFIC", "mun": "ID_MN_RESI", "agravo": "ID_AGRAVO", "encerramento": "DT_ENCERRA"}
    sqlglot.parse_one(sd.sql_agg("dbo", "VW_SINAN_DENGUE", cols, 434), read="tsql")


def test_run_sinan_dw_com_dw_simulado(tmp_path, monkeypatch):
    _master().to_csv(tmp_path / "municipal_master.csv", index=False)
    pd.DataFrame({"epi_year": [2026], "epi_week": [10], "ano": [2026], "target": ["dengue"],
                  "municipio": ["CUIABA"], "notificacoes_sinan": [3], "encerrados_sinan": [0]}
                 ).to_csv(tmp_path / "sinan_weekly_municipio.csv", index=False)

    import etl.dw_extract as dx
    import lacen_dw

    class _Q:
        def close(self):
            pass

    inv = pd.DataFrame({"TABLE_SCHEMA": ["dbo", "dbo"],
                        "TABLE_NAME": ["VW_SINAN_HEPATITE", "VW_SINAN_ANIMAISPECONHENTOS"]})
    monkeypatch.setattr(dx, "connect_or_raise", lambda: ("pyodbc", _Q()))
    monkeypatch.setattr(dx, "list_relevant_objects", lambda m, q: inv)
    monkeypatch.setattr(dx, "discover_table_columns", lambda m, q, s, t: ["DT_NOTIFIC", "ID_MN_RESI"])
    monkeypatch.setattr(lacen_dw, "read_sql", lambda m, q, sql: pd.DataFrame({
        "epi_year": [2026], "epi_week": [36], "municipio_raw": ["510340"], "agravo_raw": [None],
        "notificacoes_sinan": [6], "encerrados_sinan": [2]}))
    meta = sd.run_sinan_dw(tmp_path, weeks_back=4)
    assert meta["views_ok"] == ["VW_SINAN_HEPATITE"]
    out = pd.read_csv(tmp_path / "sinan_weekly_municipio.csv")
    assert set(zip(out["target"], out["epi_week"])) == {("dengue", 10), ("hepatite", 36)}


def test_checar_carga():
    from etl.run_etl_dw import checar_carga

    se = (2026, 36)
    rows = [{"epi_year": se[0], "epi_week": se[1], "tests": 160, "positives": 0, "municipio": "A"}]
    for i in range(1, 9):
        y, w = shift_se(*se, -i)
        rows.append({"epi_year": y, "epi_week": w, "tests": 1200, "positives": 0, "municipio": "A"})
    out = checar_carga(pd.DataFrame(rows), se)
    assert out["carga_suspeita"] and out["carga_razao"] == pytest.approx(160 / 1200, abs=1e-3)
    rows[0]["tests"] = 1100
    assert not checar_carga(pd.DataFrame(rows), se)["carga_suspeita"]
