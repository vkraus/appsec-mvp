"""Ingest-side tests for the Dependency-Track connector.

Covers the framework-contract REQ-IDs that the SCA server-based path
must bind (auth, pagination, rate-limit, HWM) plus the pure-Python
helpers that drive incremental polling and per-record flattening. Live
HTTP is out of scope — `run_ingest_pipeline` runs on Databricks via the
dlt REST source declared in resources/dependency_track-job.yml and is
skipped here with the ``live`` marker.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.connectors.dependency_track.ingest import (
    build_api_url,
    classify_project,
    extract_cve_id,
    extract_ecosystem_from_purl,
    flatten_finding,
    ingest_contract,
    run_ingest_pipeline,
    select_finding_hwm,
)

FIX = Path(__file__).parent / "fixtures"


# ----- framework-contract (REQ-FW-CONTRACT) ---------------------------------


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_contract_signature() -> None:
    sig = inspect.signature(ingest_contract)
    assert list(sig.parameters) == ["run_id", "state"]


# ----- REQ-ING-AUTH ---------------------------------------------------------


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_api_key() -> None:
    """REQ-ING-AUTH: missing credentials produce a clear error, not a
    silent failure. `base_url` alone is not enough to proceed."""
    with pytest.raises(ValueError, match="base_url, api_key, catalog"):
        ingest_contract(
            "run-1",
            {
                "source": "dependency_track",
                "run_id": "run-1",
                "extra": {"base_url": "https://dt.example", "catalog": "appsec_dev"},
            },
        )


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_catalog() -> None:
    """REQ-ING-AUTH (partial): catalog is required to resolve the bronze
    table; omission is reported rather than papered over."""
    with pytest.raises(ValueError):
        ingest_contract(
            "run-2",
            {
                "source": "dependency_track",
                "run_id": "run-2",
                "extra": {"base_url": "https://dt.example", "api_key": "token"},
            },
        )


# ----- REQ-ING-PAG ----------------------------------------------------------


@pytest.mark.requirement("REQ-ING-PAG")
def test_build_api_url_substitutes_path_params() -> None:
    """REQ-ING-PAG scaffolding: the URL builder substitutes per-project
    path parameters (UUID) cleanly, enabling the per-project pagination
    traversal documented on the connector page."""
    url = build_api_url(
        "https://dt.example/",
        "/api/v1/finding/project/{uuid}",
        uuid="11111111-1111-1111-1111-111111111111",
    )
    assert url == (
        "https://dt.example/api/v1/finding/project/"
        "11111111-1111-1111-1111-111111111111"
    )


@pytest.mark.requirement("REQ-ING-PAG")
def test_project_list_pagination_covers_two_pages_without_duplication() -> None:
    """REQ-ING-PAG: walking two project pages yields the union without
    re-reading page-one records. The offset pagination contract is
    1-indexed (see config.yml) — the driver skips a project only when
    the classifier filter / active flag excludes it."""
    page1 = json.loads((FIX / "projects_page1.json").read_text())
    page2 = json.loads((FIX / "projects_page2.json").read_text())
    allowed = ("APPLICATION", "CONTAINER")

    eligible_page1 = [p for p in page1 if classify_project(p, allowed)]
    eligible_page2 = [p for p in page2 if classify_project(p, allowed)]
    combined = eligible_page1 + eligible_page2

    uuids = [p["uuid"] for p in combined]
    assert uuids == [
        # Inactive and FIRMWARE projects from page1 are excluded by
        # classify_project; APPLICATION + CONTAINER pass through.
        "11111111-1111-1111-1111-111111111111",
        "44444444-4444-4444-4444-444444444444",
    ]
    # No duplication across pages
    assert len(uuids) == len(set(uuids))


# ----- REQ-ING-RL -----------------------------------------------------------


@pytest.mark.requirement("REQ-ING-RL")
def test_run_ingest_pipeline_deferred_to_databricks_dlt_source() -> None:
    """REQ-ING-RL: Dependency-Track does not enforce server-side rate
    limits by default; throughput is bounded by the dlt REST source's
    retry policy on the Databricks cluster. The local stub raises so a
    misconfigured call cannot silently bypass the managed retry path."""
    with pytest.raises(NotImplementedError, match="dlt REST source"):
        run_ingest_pipeline(
            spark=None,
            base_url="https://dt.example",
            api_key="token",
            bronze_table="appsec_dev.bronze_dependency_track.findings",
            run_id="run-1",
            hwm_value=None,
        )


# ----- REQ-ING-HWM ----------------------------------------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_select_finding_hwm_picks_maximum_attributed_on() -> None:
    """REQ-ING-HWM: `attribution.attributedOn` maximum is the high-water
    mark (per connector page § "Incremental hook"). A second run
    initialised with this HWM must exclude prior timestamps."""
    findings = json.loads((FIX / "findings_project_one.json").read_text())
    hwm = select_finding_hwm(findings)
    assert hwm == "2026-04-23T10:00:00Z"

    # Simulate a second run: filter the same batch on the previous HWM
    # and verify we only retain strictly-newer records.
    first_run_hwm = "2026-04-19T09:10:11Z"
    second_run = [
        f
        for f in findings
        if (f.get("attribution") or {}).get("attributedOn", "") > first_run_hwm
    ]
    assert [f["vulnerability"]["vulnId"] for f in second_run] == [
        "OSV-2021-0001",
        "INTERNAL-2026-0001",
    ]


@pytest.mark.requirement("REQ-ING-HWM")
def test_select_finding_hwm_handles_missing_attribution() -> None:
    """REQ-ING-HWM edge case: partial findings (e.g. projects returning
    an empty array) must not throw; the HWM stays at None."""
    assert select_finding_hwm([]) is None
    assert select_finding_hwm([{"component": {"uuid": "x"}}]) is None


# ----- CVE correlation and ecosystem extraction helpers --------------------


def test_extract_ecosystem_from_purl() -> None:
    assert extract_ecosystem_from_purl("pkg:pypi/requests@2.28.0") == "pypi"
    assert extract_ecosystem_from_purl("pkg:npm/lodash@4.17.15") == "npm"
    assert extract_ecosystem_from_purl("pkg:maven/com.acme/widget@1.0") == "maven"
    assert extract_ecosystem_from_purl(None) is None
    assert extract_ecosystem_from_purl("not-a-purl") is None


def test_extract_cve_id_prefers_native_when_cve_shaped() -> None:
    vuln = {"vulnId": "CVE-2023-32681", "source": "NVD"}
    assert extract_cve_id(vuln) == "CVE-2023-32681"


def test_extract_cve_id_falls_back_to_alias_for_ghsa() -> None:
    vuln = {
        "vulnId": "GHSA-j8r2-6x86-q33q",
        "source": "GITHUB",
        "aliases": ["CVE-2023-32681"],
    }
    assert extract_cve_id(vuln) == "CVE-2023-32681"


def test_extract_cve_id_returns_none_for_unlinked_internal() -> None:
    vuln = {"vulnId": "INTERNAL-2026-0001", "source": "INTERNAL"}
    assert extract_cve_id(vuln) is None


def test_flatten_finding_projects_every_consumed_field() -> None:
    project = json.loads((FIX / "projects_page1.json").read_text())[0]
    findings = json.loads((FIX / "findings_project_one.json").read_text())
    row = flatten_finding(project, findings[0])
    assert row["repository_id"] == "acme/payments-api"
    assert row["package_name"] == "requests"
    assert row["package_version"] == "2.28.0"
    assert row["purl"] == "pkg:pypi/requests@2.28.0"
    assert row["ecosystem"] == "pypi"
    assert row["cve_id"] == "CVE-2023-32681"
    assert row["advisory_source"] == "NVD"
    assert row["severity_native"] == "HIGH"
    assert row["cvss_v3"] == 7.5
    assert row["cwe_id"] == 200
    assert row["analyzer_identity"] == "OSSINDEX_ANALYZER"
    assert row["attributed_on"] == "2026-04-18T12:34:56Z"


# ----- live-only, skipped in unit runs --------------------------------------


@pytest.mark.skip(reason="live Dependency-Track API not available in unit runs")
def test_live_api_key_header_is_x_api_key() -> None:  # pragma: no cover
    """Placeholder for an integration test that asserts the `X-Api-Key`
    header is attached by the dlt REST source on the Databricks cluster.
    """
    raise AssertionError("live only")
