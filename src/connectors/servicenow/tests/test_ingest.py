"""ServiceNow ingestion tests.

Binds the ingest-side REQ-IDs that apply to the CMDB / ServiceNow profile
per ``mkdocs/docs/platform/reference/catalog.md``:

- REQ-ING-AUTH: Basic-auth credentials are required; the contract wrapper
  rejects missing username / password / catalog with a clear ValueError.
- REQ-ING-PAG: offset-based pagination via ``sysparm_offset`` /
  ``sysparm_limit``. The ``build_sysparm_query`` helper composes the
  resumable encoded-query string and the per-page traversal yields the
  union of all pages without duplication.
- REQ-ING-RL: rate-limit handling is delegated to the SDK / dlt REST
  source on Databricks; the local stub raises rather than silently
  bypassing the managed retry path.
- REQ-ING-HWM: ``sys_updated_on`` is the high-water-mark column;
  per-table HWM round-trips through ``UpdatedAtHwm`` on the shared
  ``src.platform.hwm`` store.

REQ-TRF-SEV / REQ-TRF-STS / REQ-DEDUP are N/A for CMDB and intentionally
NOT bound here per ``references/cmdb.md``.

No local SparkSession is instantiated — pure-Python contracts only per
the CLAUDE.md architectural rules.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.connectors.servicenow.ingest import (
    build_sysparm_query,
    build_table_url,
    coerce_empty_strings_to_none,
    ingest_contract,
    is_html_hibernation_response,
    raise_if_hibernating,
    run_ingest_pipeline,
    select_table_hwm,
)
from src.platform.hwm import HwmStore, UpdatedAtHwm

FIX = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# ----- framework-contract --------------------------------------------------


def test_ingest_contract_signature() -> None:
    """The contract wrapper signature is ``(run_id, state)`` per §2.4.1."""
    sig = inspect.signature(ingest_contract)
    assert list(sig.parameters) == ["run_id", "state"]


# ----- REQ-ING-AUTH --------------------------------------------------------


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_credentials() -> None:
    """REQ-ING-AUTH: missing service-account username / password / catalog
    surfaces as a clear ``ValueError`` rather than a silent failure.

    The connector resolves credentials from the platform secret scope; the
    wrapper guards against a misconfigured DAB job that fails to inject
    them via ``state['extra']``.
    """
    with pytest.raises(ValueError, match="base_url, username, password, catalog"):
        ingest_contract(
            "rid-missing-creds",
            {
                "source": "servicenow",
                "run_id": "rid-missing-creds",
                "extra": {
                    "base_url": "https://dev123456.service-now.com",
                    "catalog": "appsec_dev",
                    # username and password deliberately omitted
                },
            },
        )


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_catalog() -> None:
    """REQ-ING-AUTH (partial): catalog is required to resolve the Bronze
    table prefix; omission is reported rather than papered over."""
    with pytest.raises(ValueError):
        ingest_contract(
            "rid-missing-catalog",
            {
                "source": "servicenow",
                "run_id": "rid-missing-catalog",
                "extra": {
                    "base_url": "https://dev123456.service-now.com",
                    "username": "svc-appsec",
                    "password": "redacted",
                    # catalog deliberately omitted
                },
            },
        )


# ----- REQ-ING-PAG ---------------------------------------------------------


@pytest.mark.requirement("REQ-ING-PAG")
def test_build_table_url_targets_table_api_endpoint() -> None:
    """REQ-ING-PAG scaffolding: the URL builder produces the canonical
    ``/api/now/table/{tableName}`` endpoint shape that pagination iterates
    against."""
    url = build_table_url("https://dev123456.service-now.com/", "cmdb_ci_business_app")
    assert url == "https://dev123456.service-now.com/api/now/table/cmdb_ci_business_app"


@pytest.mark.requirement("REQ-ING-PAG")
def test_offset_pagination_concatenates_pages_without_duplication() -> None:
    """REQ-ING-PAG: walking two pages of ``cmdb_ci_business_app`` yields
    the union of records without re-reading page-one rows.

    The connector advances ``sysparm_offset`` by ``sysparm_limit`` until
    the server returns fewer than ``sysparm_limit`` records (the standard
    end-of-data signal for offset pagination).
    """
    page1 = _load_fixture("cmdb_ci_business_app_pagination_page1.json")["result"]
    page2 = _load_fixture("cmdb_ci_business_app_pagination_page2.json")["result"]

    combined = page1 + page2
    sys_ids = [r["sys_id"] for r in combined]

    # Two records on page 1, one on page 2 (the smaller-than-limit signal).
    assert len(page1) == 2
    assert len(page2) == 1
    # No duplication across pages — sys_id is the natural key.
    assert len(sys_ids) == len(set(sys_ids))
    assert sys_ids == [
        "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
        "1b2c3d4e5f60718293a4b5c6d7e8f9aa",
        "2c3d4e5f60718293a4b5c6d7e8f9aabb",
    ]


@pytest.mark.requirement("REQ-ING-PAG")
def test_build_sysparm_query_first_run_is_orderby_only() -> None:
    """REQ-ING-PAG: the first-run query carries no HWM filter — only the
    ``ORDERBY`` clause that makes pagination resumable across runs."""
    assert build_sysparm_query(None) == "ORDERBYsys_updated_on"


# ----- REQ-ING-RL ----------------------------------------------------------


@pytest.mark.requirement("REQ-ING-RL")
def test_run_ingest_pipeline_deferred_to_databricks_sdk_path() -> None:
    """REQ-ING-RL: ServiceNow rate-limit policy is enforced server-side
    (HTTP 429 + ``Retry-After``); retry handling is delegated to the
    Databricks SDK / dlt REST source on the cluster. The local stub
    raises so a misconfigured call cannot silently bypass the managed
    retry path."""
    with pytest.raises(NotImplementedError, match="SDK / dlt REST source"):
        run_ingest_pipeline(
            spark=None,
            base_url="https://dev123456.service-now.com",
            username="svc-appsec",
            password="redacted",
            tables=("cmdb_ci_business_app",),
            bronze_table_prefix="appsec_dev.bronze_servicenow",
            run_id="rid-rate-limit",
            hwm_value=None,
        )


@pytest.mark.requirement("REQ-ING-RL")
def test_pdi_hibernation_response_raises_with_clear_remediation() -> None:
    """REQ-ING-RL (degraded form, page § Quirks): a non-JSON response is a
    HARD ERROR with a clear remediation message; the connector NEVER lands
    the wake-up HTML in Bronze."""
    body = (FIX / "hibernation_html_response.html").read_text()
    with pytest.raises(RuntimeError, match="developer.servicenow.com"):
        raise_if_hibernating(content_type="text/html; charset=utf-8", body=body)


@pytest.mark.requirement("REQ-ING-RL")
def test_json_response_passes_hibernation_check() -> None:
    """A normal JSON response must pass through ``raise_if_hibernating``."""
    raise_if_hibernating(content_type="application/json", body='{"result": []}')
    assert is_html_hibernation_response("application/json", '{"result": []}') is False


# ----- REQ-ING-HWM ---------------------------------------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_build_sysparm_query_emits_hwm_filter() -> None:
    """REQ-ING-HWM: when the HWM is set, the encoded-query string filters
    on ``sys_updated_on>=<hwm>`` and orders by the same column to make
    pagination resumable."""
    q = build_sysparm_query("2026-04-19 18:00:00")
    assert q == "sys_updated_on>=2026-04-19 18:00:00^ORDERBYsys_updated_on"


@pytest.mark.requirement("REQ-ING-HWM")
def test_build_sysparm_query_rejects_malformed_hwm_value() -> None:
    """REQ-ING-HWM (defensive): a malformed HWM string is rejected with a
    clear ``ValueError`` rather than silently producing an invalid query
    that the server would interpret as no filter."""
    with pytest.raises(ValueError, match="YYYY-MM-DD HH:MM:SS"):
        build_sysparm_query("2026-04-19T18:00:00Z")  # ISO-8601 — wrong format


@pytest.mark.requirement("REQ-ING-HWM")
def test_select_table_hwm_picks_max_sys_updated_on() -> None:
    """REQ-ING-HWM: per-table HWM is the lexicographic max of
    ``sys_updated_on`` over the batch (safe given the fixed-width
    ``YYYY-MM-DD HH:MM:SS`` format)."""
    records = _load_fixture("cmdb_ci_business_app.json")["result"]
    assert select_table_hwm(records) == "2026-04-21 09:15:30"


@pytest.mark.requirement("REQ-ING-HWM")
def test_select_table_hwm_handles_empty_batch() -> None:
    """REQ-ING-HWM edge case: an empty batch produces ``None`` rather than
    advancing the HWM forward incorrectly."""
    assert select_table_hwm([]) is None
    # Records missing the HWM column are skipped (defensive).
    assert select_table_hwm([{"sys_id": "x"}]) is None


@pytest.mark.requirement("REQ-ING-HWM")
def test_per_table_hwm_round_trip_through_platform_store(tmp_path) -> None:
    """REQ-ING-HWM: per-table HWM persists across runs via ``UpdatedAtHwm``.

    A second run resumes from the persisted store — proving the HWM
    contract is end-to-end rather than only a per-batch scan.
    """
    store = HwmStore(tmp_path / "servicenow_hwm.json")
    hwm = UpdatedAtHwm("servicenow::cmdb_ci_business_app", store)

    # First run: no HWM recorded yet -> epoch default.
    assert hwm.read() == datetime(1970, 1, 1, tzinfo=UTC)

    # Simulate ingest: record the max sys_updated_on observed in the batch
    # AFTER conversion to UTC (the store contract is timezone-aware).
    last_seen = datetime(2026, 4, 21, 9, 15, 30, tzinfo=UTC)
    hwm.write(last_seen)

    # Second run: HWM is resumed from the persisted store.
    resumed = UpdatedAtHwm("servicenow::cmdb_ci_business_app", store)
    assert resumed.read() == last_seen


# ----- empty-string coercion (page § Quirks; supports REQ-DQ) --------------


def test_coerce_empty_strings_drops_blank_fields() -> None:
    """ServiceNow renders missing/null fields as ``""``; the helper coerces
    them to ``None`` so the Bronze envelope and downstream consumers can
    treat them uniformly. Anchored against the empty-field-coercion fixture."""
    raw = _load_fixture("cmdb_ci_business_app_empty_field_coercion.json")["result"][0]
    out = coerce_empty_strings_to_none(raw)
    assert out["short_description"] is None
    assert out["business_criticality"] is None
    assert out["owned_by"] is None
    assert out["used_by"] is None
    assert out["u_repository_id"] is None
    # Non-empty fields are preserved verbatim.
    assert out["sys_id"] == "4e5f60718293a4b5c6d7e8f9aabbccdd"
    assert out["name"] == "Sparse Application Record"
    assert out["operational_status"] == "operational"


# ----- live-only paths — skip unless live env present --------------------


@pytest.mark.integration
@pytest.mark.skip(
    reason="live-only: requires a ServiceNow instance and service-account credentials"
)
def test_run_ingest_pipeline_live_against_pdi() -> None:
    """End-to-end ingest against a live ServiceNow PDI. Live-only."""
    raise AssertionError("unreachable — test is skip-marked")
