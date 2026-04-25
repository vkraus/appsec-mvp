"""Transform-side tests for the Dependency-Track connector.

Exercises the pure-Python projection path (``flatten_to_silver_row``,
``normalize_severity``, ``normalize_status``, ``normalize_attributed_on``,
``build_dedup_key``). No local ``SparkSession`` is created — the full
Spark-side pipeline is out of scope for unit tests per CLAUDE.md.

Each test that binds a REQ-ID carries
``@pytest.mark.requirement("REQ-...")``; the catalog lives in
mkdocs/docs/platform/reference/catalog.md.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.connectors.dependency_track.ingest import flatten_finding
from src.connectors.dependency_track.transform import (
    build_dedup_key,
    flatten_to_silver_row,
    load_lookup,
    normalize_attributed_on,
    normalize_severity,
    normalize_status,
    transform,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIX = Path(__file__).parent / "fixtures"
SEV_LOOKUP = yaml.safe_load(
    (REPO_ROOT / "config" / "severity" / "dependency_track.yml").read_text()
)
STATUS_LOOKUP = yaml.safe_load(
    (REPO_ROOT / "config" / "status" / "dependency_track.yml").read_text()
)


def _bronze_rows() -> list[dict]:
    project = json.loads((FIX / "projects_page1.json").read_text())[0]
    findings = json.loads((FIX / "findings_project_one.json").read_text())
    return [flatten_finding(project, f) for f in findings]


# ----- framework-contract ---------------------------------------------------


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_transform_contract_signature() -> None:
    sig = inspect.signature(transform)
    assert list(sig.parameters) == ["bronze_df"]


# ----- REQ-TRF-MAP ----------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_flatten_to_silver_row_projects_all_silver_columns() -> None:
    """REQ-TRF-MAP: every silver.findings column is populated with the
    correct type and null handling. The SCA shape is package-level, so
    ``file_path`` and ``start_line`` are deliberately null."""
    rows = _bronze_rows()
    silver = flatten_to_silver_row(rows[0], SEV_LOOKUP, STATUS_LOOKUP)
    # Required, non-null per silver_findings
    assert silver["finding_id"]
    assert silver["tool_source"] == "dependency_track"
    assert silver["category"] == "sca"
    assert silver["severity_canonical"] == "high"
    assert silver["status_canonical"] == "open"
    assert silver["rule_id_native"] == "CVE-2023-32681"
    assert silver["trigger_context"] == "periodic"
    assert silver["first_seen_at"] == datetime(
        2026, 4, 18, 12, 34, 56, tzinfo=UTC
    )
    assert silver["last_seen_at"] == silver["first_seen_at"]
    # Nullable per SCA shape
    assert silver["file_path"] is None
    assert silver["start_line"] is None
    assert silver["url"] is None
    # CWE comes through as a string (silver schema stores string)
    assert silver["cwe_id"] == "200"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_mapping_yml_declares_every_silver_field() -> None:
    """REQ-TRF-MAP: mapping.yml is authoritative for the Bronze-to-Silver
    projection; every silver.findings column must be referenced so no
    required field is silently dropped in transform."""
    mapping = yaml.safe_load(
        (
            REPO_ROOT
            / "src"
            / "connectors"
            / "dependency_track"
            / "mapping.yml"
        ).read_text()
    )
    declared = set(mapping["fields"].keys())
    required = {
        "finding_id",
        "tool_source",
        "category",
        "severity_canonical",
        "status_canonical",
        "cwe_id",
        "rule_id_native",
        "trigger_context",
        "repository_id",
        "file_path",
        "start_line",
        "url",
        "first_seen_at",
        "last_seen_at",
    }
    assert required.issubset(declared), required - declared


# ----- REQ-TRF-SEV ----------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_covers_every_documented_value() -> None:
    """REQ-TRF-SEV: every documented source value has a mapped canonical
    severity, except UNASSIGNED which is intentionally routed to the
    fallback chain (CVSS derivation -> default). Undocumented values
    fall to the configured default `medium`."""
    # Label mappings
    assert normalize_severity("CRITICAL", None, SEV_LOOKUP) == "critical"
    assert normalize_severity("HIGH", None, SEV_LOOKUP) == "high"
    assert normalize_severity("MEDIUM", None, SEV_LOOKUP) == "medium"
    assert normalize_severity("LOW", None, SEV_LOOKUP) == "low"
    assert normalize_severity("INFO", None, SEV_LOOKUP) == "low"
    # UNASSIGNED with no CVSS -> default `medium` (DQ warning path)
    assert normalize_severity("UNASSIGNED", None, SEV_LOOKUP) == "medium"
    # UNASSIGNED with CVSS v3 9.8 -> critical via derivation rule
    assert normalize_severity("UNASSIGNED", 9.8, SEV_LOOKUP) == "critical"
    assert normalize_severity("UNASSIGNED", 7.1, SEV_LOOKUP) == "high"
    assert normalize_severity("UNASSIGNED", 5.5, SEV_LOOKUP) == "medium"
    assert normalize_severity("UNASSIGNED", 2.3, SEV_LOOKUP) == "low"
    # Undocumented source label -> default
    assert normalize_severity("NOVEL_LABEL", None, SEV_LOOKUP) == "medium"


# ----- REQ-TRF-STS ----------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_lookup_covers_every_documented_state() -> None:
    """REQ-TRF-STS: every documented source status lifecycle value is
    mapped; suppressed findings collapse to `wontfix`."""
    cases = [
        ({"analysis": {"state": "NOT_SET"}}, "open"),
        ({"analysis": {"state": "IN_TRIAGE"}}, "open"),
        ({"analysis": {"state": "EXPLOITABLE"}}, "confirmed"),
        ({"analysis": {"state": "RESOLVED"}}, "resolved"),
        ({"analysis": {"state": "FALSE_POSITIVE"}}, "false_positive"),
        ({"analysis": {"state": "NOT_AFFECTED"}}, "wontfix"),
        ({}, "open"),  # missing analysis -> default open
        ({"isSuppressed": True}, "wontfix"),  # suppressed overrides state
        (
            {"analysis": {"state": "NOT_SET", "suppressed": True}},
            "wontfix",
        ),
    ]
    for finding, expected in cases:
        assert normalize_status(finding, STATUS_LOOKUP) == expected, finding


# ----- REQ-TRF-TS -----------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_attributed_on_parses_to_utc_datetime() -> None:
    """REQ-TRF-TS: Z-terminated ISO-8601 and +00:00-terminated forms
    both produce a tz-aware UTC datetime."""
    assert normalize_attributed_on("2026-04-18T12:34:56Z") == datetime(
        2026, 4, 18, 12, 34, 56, tzinfo=UTC
    )
    assert normalize_attributed_on("2026-04-18T12:34:56+00:00") == datetime(
        2026, 4, 18, 12, 34, 56, tzinfo=UTC
    )
    assert normalize_attributed_on(None) is None


@pytest.mark.requirement("REQ-TRF-TS")
def test_attributed_on_rejects_naive_timestamp() -> None:
    """REQ-TRF-TS: a naive (tz-less) timestamp is rejected loudly."""
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_attributed_on("2026-04-18T12:34:56")


# ----- REQ-DQ ---------------------------------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_unassigned_severity_routes_to_dq_default_not_dropped() -> None:
    """REQ-DQ: UNASSIGNED records are NOT dropped — they route to the
    default severity with a data-quality warning per the connector page
    Quirks. The silver row for the lodash OSV finding must still carry
    a canonical severity and a non-null last_seen_at."""
    rows = _bronze_rows()
    lodash_bronze = next(r for r in rows if r["package_name"] == "lodash")
    silver = flatten_to_silver_row(lodash_bronze, SEV_LOOKUP, STATUS_LOOKUP)
    assert silver["severity_canonical"] == "medium"
    assert silver["status_canonical"] == "confirmed"
    assert silver["last_seen_at"] == datetime(
        2026, 4, 22, 0, 0, 0, tzinfo=UTC
    )


@pytest.mark.requirement("REQ-DQ")
def test_unlinked_project_yields_null_repository_id() -> None:
    """REQ-DQ: unlinkable projects (no repository_id property, no
    name-convention match) land with null repository_id. The connector
    page Quirks prescribes filtering these out at the silver layer; the
    flattener does NOT drop them so the DQ expectation can quarantine
    and count them."""
    projects = json.loads((FIX / "projects_page1.json").read_text())
    unlinked = next(p for p in projects if p["classifier"] == "FIRMWARE")
    findings = json.loads((FIX / "findings_project_one.json").read_text())
    row = flatten_finding(unlinked, findings[0])
    assert row["repository_id"] is None


# ----- REQ-DEDUP ------------------------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_collapses_same_cve_across_advisory_sources() -> None:
    """REQ-DEDUP: one component with CVE-2023-32681 reported by both NVD
    and GHSA collapses under the SCA dedup key
    (repository_id, package_name, cve_id). Different CVEs on the same
    component produce distinct keys."""
    rows = _bronze_rows()
    nvd_row = next(r for r in rows if r["advisory_source"] == "NVD")
    github_row = next(r for r in rows if r["advisory_source"] == "GITHUB")
    osv_row = next(r for r in rows if r["advisory_source"] == "OSV")

    k_nvd = build_dedup_key(nvd_row)
    k_github = build_dedup_key(github_row)
    k_osv = build_dedup_key(osv_row)

    # Same repository, same package, same CVE -> identical dedup key
    # across the two advisory sources (NVD + GHSA alias)
    assert k_nvd == k_github
    assert k_nvd == ("acme/payments-api", "requests", "CVE-2023-32681")

    # Different package -> distinct key
    assert k_osv != k_nvd
    assert k_osv[1] == "lodash"


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_tuple_matches_sca_category_reference() -> None:
    """REQ-DEDUP: the dedup tuple literal is
    (repository_id, package_name, cve_id) per the SCA category reference
    — encoded in transform.build_dedup_key as three positional fields.
    """
    row = {
        "repository_id": "acme/payments-api",
        "package_name": "requests",
        "cve_id": "CVE-2023-32681",
    }
    assert build_dedup_key(row) == (
        "acme/payments-api",
        "requests",
        "CVE-2023-32681",
    )


# ----- lookup loader -------------------------------------------------------


def test_load_lookup_reads_yaml_from_disk() -> None:
    path = REPO_ROOT / "config" / "severity" / "dependency_track.yml"
    loaded = load_lookup(str(path))
    assert loaded["CRITICAL"] == "critical"
    assert loaded["HIGH"] == "high"
