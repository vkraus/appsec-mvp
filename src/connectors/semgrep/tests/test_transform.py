"""Semgrep bronze-to-silver transform tests.

Binds REQ-TRF-MAP, REQ-TRF-SEV, REQ-TRF-STS, REQ-TRF-TS, REQ-DQ, REQ-DEDUP
from the requirement catalog (mkdocs/docs/platform/reference/catalog.md).

Tests that exercise the framework's silver schema use a local Spark session,
matching the established pattern in src/connectors/sonarqube/tests/test_transform.py.
Pure-logic tests (dedup key builder, severity/status lookup, finding_id
composer) run without Spark.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.connectors.semgrep.transform import (
    _build_finding_id,
    dedup_key_for,
    findings_to_silver,
)
from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.silver import normalize_severity, normalize_status

FIX = Path(__file__).parent / "fixtures"

_SEV_PATH = Path(__file__).parents[1] / "severity.yml"
_STATUS_PATH = Path(__file__).parents[1] / "status.yml"

_SCAN_STARTED_AT = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    return (
        SparkSession.builder.appName("semgrep-tests")
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )


def _results_from_fixture() -> list[dict]:
    return json.loads((FIX / "scan_results.json").read_text())["results"]


# --- REQ-TRF-MAP: schema mapping --------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_finding_mapping(spark: SparkSession) -> None:
    """REQ-TRF-MAP: Semgrep CLI ``results[]`` fields map to silver.findings
    with correct types and values. The composite ``finding_id`` is
    ``check_id@path:start.line`` (CLI mode has no integer id; see
    semgrep.md Quirks > "CLI mode is stateless"). ``cwe_id`` is extracted
    from the first element of ``extra.metadata.cwe``; ``cve_id`` is null
    (SAST tools do not emit CVEs).
    """
    raw = _results_from_fixture()
    rows = findings_to_silver(
        spark, raw, trigger_context="cicd",
        scan_started_at=_SCAN_STARTED_AT,
        repository_id="vkraus/juice-shop",
    ).collect()
    out = {r["finding_id"]: r for r in rows}

    expected_id = "python.lang.security.audit.dangerous-os-system@app/main.py:42"
    assert expected_id in out
    row = out[expected_id]
    assert row["tool_source"] == "semgrep"
    assert row["category"] == "sast"
    assert row["rule_id_native"] == "python.lang.security.audit.dangerous-os-system"
    assert row["repository_id"] == "vkraus/juice-shop"
    assert row["file_path"] == "app/main.py"
    assert row["start_line"] == 42
    assert row["trigger_context"] == "cicd"
    assert row["cwe_id"] == "CWE-78"
    assert row["cve_id"] is None  # SAST does not emit CVEs
    assert row["url"] is None


@pytest.mark.requirement("REQ-TRF-MAP")
def test_finding_id_compose() -> None:
    """REQ-TRF-MAP: the stable per-run identifier composes to
    ``check_id@path:start.line``; the components survive verbatim."""
    fid = _build_finding_id(
        "python.lang.security.audit.dangerous-os-system",
        "app/main.py",
        42,
    )
    assert fid == "python.lang.security.audit.dangerous-os-system@app/main.py:42"


# --- REQ-TRF-SEV: severity normalization ------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_normalization_all_levels() -> None:
    """REQ-TRF-SEV: all documented Semgrep CLI severities map to the
    canonical four-level model. ERROR->high, WARNING->medium, INFO->low.
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)

    assert normalize_severity("ERROR", sev) == "high"
    assert normalize_severity("WARNING", sev) == "medium"
    assert normalize_severity("INFO", sev) == "low"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_undocumented_falls_through_to_default() -> None:
    """REQ-TRF-SEV: an undocumented severity value falls through to the
    ``info`` default (per ``src.platform.silver.normalize_severity``)
    rather than crashing or masquerading as a known level.
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)

    assert normalize_severity("EMERGENCY", sev) == "info"


# --- REQ-TRF-STS: status normalization --------------------------------------


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_defaults_to_open_for_cli(spark: SparkSession) -> None:
    """REQ-TRF-STS: CLI mode emits no ``state`` field; every CLI finding
    lands as ``open``. Cloud Platform's ``state="removed"`` maps to
    ``resolved`` for forward compatibility (see status.yml).
    """
    raw = _results_from_fixture()
    rows = findings_to_silver(
        spark, raw, scan_started_at=_SCAN_STARTED_AT,
    ).collect()
    by_id = {r["finding_id"]: r for r in rows}

    # The first three fixtures are CLI-mode (no state) -> open.
    cli_id = "python.lang.security.audit.dangerous-os-system@app/main.py:42"
    assert by_id[cli_id]["status_canonical"] == "open"

    # The fourth fixture carries metadata.state="removed" -> resolved.
    cloud_id = "python.lang.security.audit.cloud-state@app/cloud.py:5"
    assert by_id[cloud_id]["status_canonical"] == "resolved"


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_undocumented_falls_through_to_open() -> None:
    """REQ-TRF-STS: unrecognized state maps to ``open`` per
    src.platform.silver.normalize_status.
    """
    status_map = load_yaml(StatusMap, _STATUS_PATH)
    assert normalize_status("UNKNOWN_STATE", status_map) == "open"


# --- REQ-TRF-TS: timestamp normalization ------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_seen_at_is_utc_datetime(spark: SparkSession) -> None:
    """REQ-TRF-TS: ``first_seen_at`` and ``last_seen_at`` are timezone-aware
    UTC datetimes. CLI artefacts have no per-finding timestamp, so the
    transform stamps both with the artefact's ``scan_started_at``.
    """
    raw = _results_from_fixture()
    rows = findings_to_silver(
        spark, raw, scan_started_at=_SCAN_STARTED_AT,
    ).collect()

    for row in rows:
        assert row["first_seen_at"] == _SCAN_STARTED_AT
        assert row["last_seen_at"] == _SCAN_STARTED_AT
        assert row["first_seen_at"].tzinfo is not None


# --- REQ-DQ: data-quality expectation ---------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_findings_expectation_quarantines_null_check_id(
    spark: SparkSession,
) -> None:
    """REQ-DQ: malformed records (missing ``check_id`` or ``path``) are
    excluded from the Silver output. The Silver schema treats
    ``rule_id_native`` and ``file_path``-derived fields as required
    inputs, so a finding with no rule can never land in silver.findings;
    the transform enforces this gate locally. On Databricks, an
    equivalent Lakeflow expectation runs at the silver gate.
    """
    valid = _results_from_fixture()[0]
    malformed_no_check_id = dict(valid)
    malformed_no_check_id["check_id"] = None
    malformed_no_path = dict(valid)
    malformed_no_path["path"] = None

    batch = [valid, malformed_no_check_id, malformed_no_path]

    rows = findings_to_silver(
        spark, batch, scan_started_at=_SCAN_STARTED_AT,
    ).collect()

    # Only the valid record passes; both malformed records are quarantined.
    assert len(rows) == 1
    assert rows[0]["rule_id_native"] == valid["check_id"]


# --- REQ-DEDUP: dedup-key tuple ---------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_links_against_sonarqube_overlap() -> None:
    """REQ-DEDUP: the dedup key is the tuple ``(repository_id, file_path,
    rule_id_native, start_line)`` per the SAST category reference
    (``.claude/skills/generate-connector/references/sast.md`` §
    "Deduplication key"). Two Semgrep findings on the same
    file+rule+line produce identical dedup keys; distinct files,
    rules, or lines produce distinct keys. The tuple is the join basis
    for ``dedup_links`` across overlapping SAST tools (SonarQube ↔
    Semgrep).
    """
    finding_a = {
        "metadata": {"repository_id": "vkraus/juice-shop"},
        "path": "app/main.py",
        "check_id": "python.lang.security.audit.dangerous-os-system",
        "start": {"line": 42},
    }
    finding_b_same_location = {
        "metadata": {"repository_id": "vkraus/juice-shop"},
        "path": "app/main.py",
        "check_id": "python.lang.security.audit.dangerous-os-system",
        "start": {"line": 42},
    }
    finding_c_different_file = {
        "metadata": {"repository_id": "vkraus/juice-shop"},
        "path": "app/auth.py",
        "check_id": "python.lang.security.audit.dangerous-os-system",
        "start": {"line": 42},
    }
    finding_d_different_rule = {
        "metadata": {"repository_id": "vkraus/juice-shop"},
        "path": "app/main.py",
        "check_id": "python.lang.security.audit.weak-hash",
        "start": {"line": 42},
    }
    finding_e_different_line = {
        "metadata": {"repository_id": "vkraus/juice-shop"},
        "path": "app/main.py",
        "check_id": "python.lang.security.audit.dangerous-os-system",
        "start": {"line": 99},
    }

    key_a = dedup_key_for(finding_a)
    key_b = dedup_key_for(finding_b_same_location)
    key_c = dedup_key_for(finding_c_different_file)
    key_d = dedup_key_for(finding_d_different_rule)
    key_e = dedup_key_for(finding_e_different_line)

    assert key_a == key_b                # linked -> same dedup tuple
    assert key_a != key_c                # distinct file
    assert key_a != key_d                # distinct rule
    assert key_a != key_e                # distinct line
    # The tuple shape itself matches the SAST reference contract.
    assert key_a == (
        "vkraus/juice-shop",
        "app/main.py",
        "python.lang.security.audit.dangerous-os-system",
        42,
    )
