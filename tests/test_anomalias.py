# -*- coding: utf-8 -*-
import math

import pandas as pd

from etl.epi_week import shift_se
from ml.anomalias import binom_sf, detect_anomalias_v2, poisson_sf


def test_poisson_sf():
    assert poisson_sf(0, 3.0) == 1.0
    assert math.isclose(poisson_sf(1, 2.0), 1 - math.exp(-2.0), rel_tol=1e-9)
    assert poisson_sf(30, 5.0) < 1e-8


def test_binom_sf():
    assert math.isclose(binom_sf(1, 1, 0.3), 0.3, rel_tol=1e-9)
    assert math.isclose(binom_sf(2, 2, 0.5), 0.25, rel_tol=1e-9)


def _serie(vals, last=(2027, 2), mun="CUIABA", tgt="dengue", pos=None):
    rows = []
    n = len(vals)
    for i, v in enumerate(vals):
        y, w = shift_se(last[0], last[1], -(n - 1 - i))
        if v is None:  # semana sem exame: linha ausente (painel esparso)
            continue
        rows.append({"municipio": mun, "target": tgt, "epi_year": y, "epi_week": w,
                     "tests": v, "positives": (pos[i] if pos else 0)})
    return pd.DataFrame(rows)


def test_base_exclui_semana_e_preenche_zeros():
    # 8 semanas com 0–2 exames (várias ausentes) e pico de 20 na última,
    # atravessando a SE 53/2026.
    df = _serie([2, None, 1, None, None, 2, 1, None, None, None, None, 20])
    out = detect_anomalias_v2(df, n_semanas_avaliadas=1)
    hit = out[(out.metric == "tests")]
    assert len(hit) == 1
    r = hit.iloc[0]
    assert (r.epi_year, r.epi_week) == (2027, 2)
    # base = média de 8 SE anteriores com zeros (não a média das observadas)
    assert math.isclose(r.baseline_ma8, (2 + 1) / 8, rel_tol=1e-9)  # SE −8…−1
    assert r.severidade == "alta"


def test_pequeno_n_nao_dispara():
    df = _serie([1] * 11 + [3])
    out = detect_anomalias_v2(df, n_semanas_avaliadas=1)
    assert out.empty


def test_avalia_semana_anterior_mesmo_com_linha_na_corrente():
    # pico na penúltima SE (analisada) e linha também na SE corrente
    df = _serie([3] * 10 + [30, 2])
    out = detect_anomalias_v2(df, n_semanas_avaliadas=2)
    alvo = shift_se(2027, 2, -1)
    assert ((out.epi_year == alvo[0]) & (out.epi_week == alvo[1]) & (out.metric == "tests")).any()


def test_positividade_binomial():
    pos = [1] * 11 + [12]
    df = _serie([20] * 12, pos=pos)
    out = detect_anomalias_v2(df, n_semanas_avaliadas=1)
    assert (out.metric == "positividade").any()
