from quality.artifact_hygiene import scan_quality_artifacts, scan_text, write_hygiene_report


def test_secret_pattern_blocks():
    findings = scan_text("api_key=ABCDEF1234567890")
    assert any(f.status == "BLOCK" and f.category == "credential" for f in findings)


def test_bearer_token_blocks():
    findings = scan_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123")
    assert any(f.status == "BLOCK" and f.category == "bearer_token" for f in findings)


def test_local_windows_path_warns():
    findings = scan_text(r"C:\Users\person\project\saida.csv")
    assert any(f.status == "WARN" and f.category == "windows_path" for f in findings)


def test_email_and_cpf_warn():
    findings = scan_text("nome@exemplo.com 123.456.789-00")
    categories = {f.category for f in findings}
    assert "email" in categories
    assert "cpf" in categories


def test_clean_quality_dir_passes(tmp_path):
    (tmp_path / "clean.json").write_text('{"status":"PASS"}', encoding="utf-8")
    report = scan_quality_artifacts(tmp_path)
    assert report["status"] == "PASS"
    assert report["finding_count"] == 0


def test_quality_dir_with_secret_blocks(tmp_path):
    (tmp_path / "bad.txt").write_text("password=supersecret", encoding="utf-8")
    report = scan_quality_artifacts(tmp_path)
    assert report["status"] == "BLOCK"
    assert report["block_count"] == 1


def test_hygiene_report_writes_artifacts(tmp_path):
    report = {"status":"PASS","finding_count":0,"block_count":0,"warn_count":0,"findings":[]}
    paths = write_hygiene_report(report, tmp_path)
    assert paths["json"].exists()
    assert paths["txt"].exists()
