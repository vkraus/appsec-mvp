"""SonarQube bronze-to-silver transform tests.

Binds REQ-TRF-MAP, REQ-TRF-SEV, REQ-TRF-STS, REQ-TRF-TS, REQ-DQ, REQ-DEDUP
from the requirement catalog (mkdocs/docs/platform/reference/catalog.md).

Tests that exercise the framework's silver schema use a local Spark session,
matching the established pattern in tests/connectors/github/test_transform.py
and tests/connectors/servicenow/test_transform.py. Pure-logic tests (dedup
key builder, status-composite key, severity/status lookup) run without
Spark.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.connectors.sonarqube.transform import (
    compose_status_key,
    dedup_key_for,
    issues_to_silver,
    split_component,
)
from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.silver import normalize_severity, normalize_status

FIX = Path(__file__).parent / "fixtures"

_SEV_PATH = Path(__file__).parents[1] / "severity.yml"
_STATUS_PATH = Path(__file__).parents[1] / "status.yml"


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    return (
        SparkSession.builder.appName("sonarqube-tests")
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )


def _issues_from_fixture() -> list[dict]:
    return (
        json.loads((FIX / "issues_page1.json").read_text())["issues"]
        + json.loads((FIX / "issues_page2.json").read_text())["issues"]
    )


# --- REQ-TRF-MAP: schema mapping --------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_issue_mapping(spark: SparkSession) -> None:
    """REQ-TRF-MAP: SonarQube /api/issues/search fields map to silver.findings
    with correct types and values. CODE_SMELL is filtered at the Silver gate
    (see sonarqube.md Quirks). The component ``project:path`` is split into
    ``repository_id`` and ``file_path``.
    """
    raw = _issues_from_fixture()
    out = {r["finding_id"]: r for r in issues_to_silver(spark, raw).collect()}

    # 2 of 3 issues land in silver; the CODE_SMELL is filtered.
    assert set(out) == {"AYx1aaaaaaaaaaaaaaa1", "AYx1aaaaaaaaaaaaaaa2"}
    row = out["AYx1aaaaaaaaaaaaaaa1"]
    assert row["tool_source"] == "sonarqube"
    assert row["category"] == "sast"
    assert row["rule_id_native"] == "java:S2259"
    assert row["repository_id"] == "seed-python-a"
    assert row["file_path"] == "src/main/java/com/example/Service.java"
    assert row["start_line"] == 42
    # Envelope columns that carry semantics.
    assert row["trigger_context"] == "periodic"
    assert row["cwe_id"] is None  # enriched via src/platform/cwe.py side table
    assert row["url"] is None      # no per-finding permalink in the API


@pytest.mark.requirement("REQ-TRF-MAP")
def test_component_split_unambiguous_on_first_colon() -> None:
    """REQ-TRF-MAP: ``component`` is split on the first colon only; a file
    path that itself contains a colon (pathological but valid on some
    filesystems) still parses the project key correctly.
    """
    repo, path = split_component("proj-a:weird:file.txt")
    assert repo == "proj-a"
    assert path == "weird:file.txt"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_component_without_colon_rejected() -> None:
    """REQ-TRF-MAP: malformed component values raise rather than silently
    producing a null repository_id.
    """
    with pytest.raises(ValueError, match="does not contain ':'"):
        split_component("no-colon-here")


# --- REQ-TRF-SEV: severity normalization ------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_normalization_all_levels() -> None:
    """REQ-TRF-SEV: all documented SonarQube severities map to the canonical
    four-level model. BLOCKER->critical, CRITICAL->high, MAJOR->medium,
    MINOR->low, INFO->low (direct map avoids DQ warning on high-volume
    informational findings; see sonarqube.md Quirks).
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)

    assert normalize_severity("BLOCKER", sev) == "critical"
    assert normalize_severity("CRITICAL", sev) == "high"
    assert normalize_severity("MAJOR", sev) == "medium"
    assert normalize_severity("MINOR", sev) == "low"
    assert normalize_severity("INFO", sev) == "low"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_undocumented_falls_through_to_default() -> None:
    """REQ-TRF-SEV: an undocumented severity value falls through to the
    ``info`` default (per ``src.platform.silver.normalize_severity``) rather
    than crashing or masquerading as a known level.
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)

    # "EMERGENCY" is not in the SonarQube vocabulary; must fall through.
    assert normalize_severity("EMERGENCY", sev) == "info"


# --- REQ-TRF-STS: status normalization --------------------------------------


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_resolution_normalization() -> None:
    """REQ-TRF-STS: the composite (status, resolution) key resolves to the
    canonical lifecycle. OPEN/REOPENED->open; CONFIRMED->confirmed;
    RESOLVED+FIXED->resolved; RESOLVED+FALSE-POSITIVE->false_positive;
    RESOLVED+WONTFIX->wontfix; CLOSED+REMOVED->resolved.
    """
    status_map = load_yaml(StatusMap, _STATUS_PATH)

    def lookup(status: str | None, resolution: str | None) -> str:
        key = compose_status_key(status, resolution)
        return normalize_status(key, status_map)

    assert lookup("OPEN", None) == "open"
    assert lookup("REOPENED", None) == "open"
    assert lookup("CONFIRMED", None) == "confirmed"
    assert lookup("RESOLVED", "FIXED") == "resolved"
    assert lookup("RESOLVED", "FALSE-POSITIVE") == "false_positive"
    assert lookup("RESOLVED", "WONTFIX") == "wontfix"
    assert lookup("CLOSED", "REMOVED") == "resolved"
    # Hotspot vocabulary also projects into silver.findings.
    assert lookup("TO_REVIEW", None) == "open"
    assert lookup("REVIEWED", "FIXED") == "resolved"
    assert lookup("REVIEWED", "SAFE") == "false_positive"


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_undocumented_falls_through_to_open() -> None:
    """REQ-TRF-STS: unrecognized state maps to ``open`` per
    src.platform.silver.normalize_status.
    """
    status_map = load_yaml(StatusMap, _STATUS_PATH)
    assert normalize_status("UNKNOWN_STATE", status_map) == "open"


# --- REQ-TRF-TS: timestamp normalization ------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_creation_date_to_utc_datetime(spark: SparkSession) -> None:
    """REQ-TRF-TS: ``creationDate`` and ``updateDate`` emitted as UTC
    timezone-aware datetimes regardless of the source offset notation
    (``+0000`` without colon).
    """
    raw = _issues_from_fixture()
    out = {r["finding_id"]: r for r in issues_to_silver(spark, raw).collect()}

    row = out["AYx1aaaaaaaaaaaaaaa1"]
    assert row["first_seen_at"] == datetime(2026, 4, 18, 9, 0, tzinfo=UTC)
    assert row["last_seen_at"] == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)


# --- REQ-DQ: data-quality expectation ---------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_findings_expectation_quarantines_null_rule(spark: SparkSession) -> None:
    """REQ-DQ: a malformed record (missing ``component``, so the Silver
    transform cannot derive ``repository_id`` / ``file_path``) is excluded
    from the Silver output. A valid record passes through unaffected. The
    Silver schema treats ``rule_id_native`` as non-nullable, so a finding
    with no rule can never land in silver.findings; the transform enforces
    this gate locally. On Databricks, an equivalent Lakeflow expectation
    ``expect rule_id_native IS NOT NULL on violation drop row`` runs on the
    silver.findings pipeline.
    """
    valid = _issues_from_fixture()[0]
    malformed_no_component = dict(valid)
    malformed_no_component["key"] = "AYMalformedNoComponent1"
    malformed_no_component["component"] = ""  # empty triggers split failure
    batch = [valid, malformed_no_component]

    rows = issues_to_silver(spark, batch).collect()

    # The valid record passes, the malformed one is quarantined (dropped).
    assert len(rows) == 1
    assert rows[0]["finding_id"] == valid["key"]


# --- REQ-DEDUP: dedup-key tuple ---------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_links_against_semgrep_overlap() -> None:
    """REQ-DEDUP: the dedup key is the tuple ``(repository_id, file_path,
    rule_id)`` per the SAST category reference. Two SonarQube issues on
    the same file+rule produce identical dedup keys; distinct files
    produce distinct keys. The tuple is the join basis for ``dedup_links``
    across overlapping SAST tools (SonarQube ↔ Semgrep).
    """
    issue_a = {
        "component": "seed-python-a:src/main/java/com/example/Service.java",
        "rule": "java:S2259",
    }
    issue_b_same_location = {
        "component": "seed-python-a:src/main/java/com/example/Service.java",
        "rule": "java:S2259",
    }
    issue_c_different_file = {
        "component": "seed-python-a:src/main/java/com/example/Utils.java",
        "rule": "java:S2259",
    }
    issue_d_different_rule = {
        "component": "seed-python-a:src/main/java/com/example/Service.java",
        "rule": "java:S1488",
    }

    key_a = dedup_key_for(issue_a)
    key_b = dedup_key_for(issue_b_same_location)
    key_c = dedup_key_for(issue_c_different_file)
    key_d = dedup_key_for(issue_d_different_rule)

    assert key_a == key_b                # linked -> same dedup tuple
    assert key_a != key_c                # distinct file -> distinct tuple
    assert key_a != key_d                # distinct rule -> distinct tuple
    # The tuple shape itself matches the SAST reference contract.
    assert key_a == (
        "seed-python-a",
        "src/main/java/com/example/Service.java",
        "java:S2259",
    )
