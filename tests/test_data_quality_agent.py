import pandas as pd

from quality.data_quality_agent import QualityStatus, run_quality_gate


def test_valid_weekly_passes():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"municipio_ibge":["5103403"],"tests":[10],"positives":[2]})
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
    report = run_quality_gate(weekly=weekly, population=pop, analysis_year=2026, population_required=True)
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


def test_population_is_not_required_for_count_only_products():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"tests":[10],"positives":[2]})
    report = run_quality_gate(weekly=weekly, analysis_year=2026)
    assert report.status in (QualityStatus.PASS, QualityStatus.WARN)
    assert report.publishable is True
    assert not any(f.check_id == "DQ_POPULATION_MISSING" for f in report.findings)


def test_population_required_blocks_without_denominator():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[37],"tests":[10],"positives":[2]})
    report = run_quality_gate(
        weekly=weekly,
        analysis_year=2026,
        population_required=True,
    )
    assert report.status == QualityStatus.BLOCK
    assert any(f.check_id == "DQ_POPULATION_MISSING" for f in report.findings)


def test_missing_required_value_warns_completeness():
    weekly = pd.DataFrame({
        "epi_year":[2026, 2026],
        "epi_week":[37, 37],
        "tests":[10, None],
        "positives":[2, 0],
    })
    report = run_quality_gate(weekly=weekly)
    assert report.status == QualityStatus.WARN
    assert any(
        f.check_id == "DQ_COMPLETENESS_TESTS" and f.status == QualityStatus.WARN
        for f in report.findings
    )


def test_duplicate_weekly_key_warns_without_blocking():
    weekly = pd.DataFrame({
        "epi_year":[2026, 2026],
        "epi_week":[37, 37],
        "municipio":["Cuiabá", "Cuiabá"],
        "agravo":["Dengue", "Dengue"],
        "tests":[10, 10],
        "positives":[2, 2],
    })
    report = run_quality_gate(weekly=weekly)
    assert report.status == QualityStatus.WARN
    assert report.publishable is True
    assert any(f.check_id == "DQ_DUPLICATES" for f in report.findings)


def test_epi_week_53_is_valid_domain():
    weekly = pd.DataFrame({"epi_year":[2026],"epi_week":[53],"tests":[1],"positives":[0]})
    report = run_quality_gate(weekly=weekly)
    assert report.status in (QualityStatus.PASS, QualityStatus.WARN)
    assert report.publishable is True


def test_ibge_code_validation_warns_on_bad_format():
    weekly = pd.DataFrame({
        "epi_year":[2026],
        "epi_week":[37],
        "municipio":["Cuiabá"],
        "municipio_ibge":["510340"],
        "tests":[10],
        "positives":[2],
    })
    report = run_quality_gate(weekly=weekly)
    assert report.status == QualityStatus.WARN
    assert any(
        f.check_id == "DQ_IBGE_CODE" and f.status == QualityStatus.WARN
        for f in report.findings
    )


def test_ibge_code_validation_accepts_seven_digits():
    weekly = pd.DataFrame({
        "epi_year":[2026],
        "epi_week":[37],
        "municipio":["Cuiabá"],
        "municipio_ibge":["5103403"],
        "tests":[10],
        "positives":[2],
    })
    report = run_quality_gate(weekly=weekly)
    assert report.publishable is True
    assert any(
        f.check_id == "DQ_IBGE_CODE" and f.status == QualityStatus.PASS
        for f in report.findings
    )
