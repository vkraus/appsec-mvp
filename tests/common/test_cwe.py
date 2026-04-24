from src.common.cwe import extract_cwe_from_sonarqube, extract_cwe_from_semgrep


def test_sonarqube_security_standards_with_cwe():
    issue = {"securityCategory": "sql-injection", "cwe": ["89"]}
    assert extract_cwe_from_sonarqube(issue) == "CWE-89"


def test_sonarqube_security_standards_alt_shape():
    issue = {"securityStandards": ["cwe:79", "owaspTop10:a3"]}
    assert extract_cwe_from_sonarqube(issue) == "CWE-79"


def test_sonarqube_no_cwe_returns_none():
    assert extract_cwe_from_sonarqube({"securityCategory": "other"}) is None


def test_semgrep_metadata_cwe_single_string():
    finding = {"extra": {"metadata": {"cwe": "CWE-89: SQL Injection"}}}
    assert extract_cwe_from_semgrep(finding) == "CWE-89"


def test_semgrep_metadata_cwe_list():
    finding = {"extra": {"metadata": {"cwe": ["CWE-79", "CWE-80"]}}}
    # Take the first one — the Silver layer is one CWE per finding
    assert extract_cwe_from_semgrep(finding) == "CWE-79"


def test_semgrep_no_cwe_returns_none():
    assert extract_cwe_from_semgrep({"extra": {"metadata": {}}}) is None
