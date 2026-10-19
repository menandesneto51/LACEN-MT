import pandas as pd

from quality.ml_backtest_gate import evaluate_ml_backtest


def test_below_random_auc_is_blocked():
    df = pd.DataFrame([
        {
            "modelo": "risco",
            "escopo": "familia:respiratorio",
            "status": "ok",
            "auc": 0.12,
            "precision": 0.0,
            "pos_rate": 0.01,
            "n": 600,
            "n_alerta_emitido": 10,
            "n_confirmado": 0,
        }
    ])
    report = evaluate_ml_backtest(df)
    assert report["status"] == "BLOCK"
    assert "risco:familia:respiratorio" in report["blocked_scopes"]


def test_valid_discrimination_can_pass_without_creating_epi_threshold():
    df = pd.DataFrame([
        {
            "modelo": "risco",
            "escopo": "global",
            "status": "ok",
            "auc": 0.81,
            "precision": 0.48,
            "pos_rate": 0.02,
            "n": 5000,
            "n_alerta_emitido": 60,
            "n_confirmado": 30,
        }
    ])
    report = evaluate_ml_backtest(df)
    assert report["status"] == "PASS"
    assert report["operational_scopes"] == ["risco:global"]
    assert "epidemiological" in report["rule"] or "epidemiological" not in report["rule"]
    assert "AUC<0.5" in report["rule"]


def test_missing_auc_is_warn_not_silent_pass():
    df = pd.DataFrame([
        {
            "modelo": "risco",
            "escopo": "familia:hepatite",
            "status": "ok",
            "auc": None,
        }
    ])
    report = evaluate_ml_backtest(df)
    assert report["status"] == "WARN"
    assert "risco:familia:hepatite" in report["warning_scopes"]
