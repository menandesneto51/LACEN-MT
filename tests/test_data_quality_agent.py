import pandas as pd

from quality.data_quality_agent import QualityStatus, run_quality_gate


def test_valid_weekly_passes():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"tests":[10],"positives":[2]})
    report = run_quality_gate(weekly=weekly)
    assert report.status == QualityStatus.PASS
    assert report.publishable is True


def test_positive_greater_than_tests_blocks():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"tests":[1],"positives":[2]})
    report = run_quality_gate(weekly=weekly)
    assert report.status == QualityStatus.BLOCK
    assert report.publishable is False


def test_invalid_epi_week_blocks():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[54],"tests":[1],"positives":[0]})
    assert run_quality_gate(weekly=weekly).status == QualityStatus.BLOCK


def test_old_population_blocks_current_rate_analysis():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"tests":[1],"positives":[0]})
    pop = pd.DataFrame({"ano":[1996],"populacao":[100000]})
    report = run_quality_gate(weekly=weekly, population=pop, analysis_year=2026)
    assert report.status == QualityStatus.BLOCK
    assert any(f.check_id == "DQ_POPULATION_FRESHNESS" for f in report.findings)


def test_negative_tat_blocks():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"tests":[1],"positives":[0]})
    gal = pd.DataFrame({
        "Data_Recebimento_dt":["2026-09-10"],
        "Data_Liberacao_dt":["2026-09-09"],
    })
    report = run_quality_gate(weekly=weekly, gal_micro=gal)
    assert report.status == QualityStatus.BLOCK
