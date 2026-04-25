from datetime import UTC, datetime

import pytest
from pyspark.sql import SparkSession

from src.platform.config import SeverityMap, StatusMap
from src.platform.schemas import silver_findings
from src.platform.silver import (
    dedup_findings,
    normalize_severity,
    normalize_status,
)


@pytest.fixture(scope="module")
def spark():
    return (
        SparkSession.builder
        .appName("silver-tests")
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )


def test_normalize_severity_maps_known():
    sm = SeverityMap.model_validate({"BLOCKER": "critical", "INFO": "low"})
    assert normalize_severity("BLOCKER", sm) == "critical"
    assert normalize_severity("INFO", sm) == "low"


def test_normalize_severity_unknown_is_info():
    sm = SeverityMap.model_validate({"BLOCKER": "critical"})
    assert normalize_severity("WAT", sm) == "info"


def test_normalize_status_known_and_unknown():
    stm = StatusMap.model_validate({"OPEN": "open", "FIXED": "resolved"})
    assert normalize_status("OPEN", stm) == "open"
    # Unknowns default to open
    assert normalize_status("WAT", stm) == "open"


def test_dedup_sast_groups_by_cwe_tuple(spark):
    ts = datetime(2026, 4, 20, tzinfo=UTC)
    rows = [
        # Same (repo, file, line, cwe) across two tools → one group
        ("sq-1", "sonarqube", "sast", "high", "open", "CWE-89", "S2077",
         "periodic", "org/app", "app/db.py", 42, None, ts, ts),
        ("sg-1", "semgrep", "sast", "critical", "open", "CWE-89", "python.sqli",
         "periodic", "org/app", "app/db.py", 42, None, ts, ts),
        # Different file → different group
        ("sq-2", "sonarqube", "sast", "medium", "open", "CWE-79", "S2076",
         "periodic", "org/app", "app/other.py", 7, None, ts, ts),
    ]
    df = spark.createDataFrame(rows, silver_findings)
    deduped = dedup_findings(df).collect()
    # Two groups: (org/app, app/db.py, 42, CWE-89) and (org/app, app/other.py, 7, CWE-79)
    assert len(deduped) == 2
    # The merged group for the first key must use the highest severity: critical
    merged = next(r for r in deduped if r["cwe_id"] == "CWE-89")
    assert merged["severity_canonical"] == "critical"
    assert set(merged["tool_sources"]) == {"sonarqube", "semgrep"}


def test_dedup_sast_without_cwe_falls_back_to_native_rule(spark):
    ts = datetime(2026, 4, 20, tzinfo=UTC)
    # Two sonarqube findings with no CWE on same location but different native rule
    rows = [
        ("a", "sonarqube", "sast", "high", "open", None, "S100",
         "periodic", "org/app", "f.py", 1, None, ts, ts),
        ("b", "sonarqube", "sast", "high", "open", None, "S100",
         "periodic", "org/app", "f.py", 1, None, ts, ts),
        ("c", "sonarqube", "sast", "high", "open", None, "S200",
         "periodic", "org/app", "f.py", 1, None, ts, ts),
    ]
    df = spark.createDataFrame(rows, silver_findings)
    deduped = dedup_findings(df).collect()
    # Two groups: (S100 × same loc) → 1; (S200 × same loc) → 1
    assert len(deduped) == 2


def test_dedup_dast_groups_by_url_rule(spark):
    ts = datetime(2026, 4, 20, tzinfo=UTC)
    rows = [
        ("z-1", "zap", "dast", "high", "open", None, "40018",
         "on_demand", None, None, None, "https://app.test/login", ts, ts),
        ("z-2", "zap", "dast", "high", "open", None, "40018",
         "on_demand", None, None, None, "https://app.test/login", ts, ts),
    ]
    df = spark.createDataFrame(rows, silver_findings)
    deduped = dedup_findings(df).collect()
    assert len(deduped) == 1
