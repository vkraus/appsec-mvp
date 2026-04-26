"""OWASP ZAP ingest tests.

REQ-ID coverage (per catalog matrix at mkdocs/docs/platform/reference/catalog.md
lines 39-50; ZAP's prior PASS profile is REQ-ING-HWM=PASS, REQ-ING-AUTH/
PAG/RL=N/A):

- REQ-ING-HWM: bound. Two HWM kinds coexist on this hybrid connector
  (artefact_prefix for the CI/CD-step path; scan_id for the daemon path).
  Both shapes round-trip through the shared src.platform.hwm helpers.
- REQ-ING-AUTH: N/A under the CI/CD-step artefact path (object-storage
  IAM governs access; no native auth on the report files). Bound on
  the daemon path as a hard error when the apikey is missing — the
  contract wrapper refuses to run rather than silently swallow rows.
- REQ-ING-PAG: N/A under the CI/CD-step path (one report per pipeline
  run). Bound on the daemon path via iter_paged_alerts (offset/limit
  pagination of /JSON/alert/view/alerts/).
- REQ-ING-RL: N/A under the CI/CD-step path. The daemon enforces no
  documented per-client rate limit (throughput is daemon-resource
  bounded); skip-marked placeholder for the matrix.

The trigger-discriminator routing tests bind the hybrid invariant from
§3 Quirks of mkdocs/docs/connectors/dast/owasp-zap.md: every input MUST
map to exactly one of {cicd, on_demand} and inputs that match neither
MUST raise rather than land with an ambiguous trigger_context.

No local SparkSession is instantiated — pure-Python contracts only per
CLAUDE.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.connectors.owasp_zap.ingest import (
    DOCUMENTED_RISKS,
    DOCUMENTED_SCAN_KINDS,
    ZAP_ENDPOINTS,
    _scrub_apikey,
    build_alerts_url,
    classify_trigger,
    ingest_contract,
    iter_paged_alerts,
    normalise_cwe_id,
    select_alert_name,
    split_uri_for_dedup,
)
from src.platform.hwm import HwmStore, ScanIdHwm

FIX = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# ---------------------------------------------------------------------------
# REQ-ING-HWM — both HWM shapes bound (artefact_prefix + scan_id).
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_scan_id_hwm_round_trip(tmp_path) -> None:
    """REQ-ING-HWM (daemon path): scan_id HWM persists across runs.

    Per references/dast.md, the on-demand DAST path keys on the numeric
    scanId returned by /JSON/{spider,ascan}/action/scan/. The shared
    src.platform.hwm.ScanIdHwm helper is the canonical store.
    """
    store = HwmStore(tmp_path / "owasp_zap_hwm.json")
    hwm = ScanIdHwm("owasp_zap::daemon::https://app.test", store)

    # First run: no HWM recorded -> None.
    assert hwm.read() is None

    # Simulate scan completion: record the scanId returned by ZAP.
    hwm.write("17")

    # Second run: HWM is resumed from the persisted store.
    resumed = ScanIdHwm("owasp_zap::daemon::https://app.test", store)
    assert resumed.read() == "17"


@pytest.mark.requirement("REQ-ING-HWM")
def test_scan_id_hwm_advances_monotonically(tmp_path) -> None:
    """REQ-ING-HWM: subsequent scans overwrite the recorded scanId.

    ZAP scanId values are monotonic per daemon process; the connector
    advances the HWM forward on every successful read.
    """
    store = HwmStore(tmp_path / "owasp_zap_hwm.json")
    hwm = ScanIdHwm("owasp_zap::daemon::https://app.test", store)
    hwm.write("3")
    hwm.write("4")
    hwm.write("17")
    assert hwm.read() == "17"


@pytest.mark.requirement("REQ-ING-HWM")
def test_artefact_prefix_hwm_round_trip(tmp_path) -> None:
    """REQ-ING-HWM (CI/CD-step path): artefact_prefix HWM persists across runs.

    Per references/dast.md and §3 of the connector page, the CI/CD-step
    path records the most recently ingested object key under cicd/zap/.
    Auto Loader's checkpoint is the primary mechanism; the recorded key
    is a secondary signal used for backfill auditing — but the value
    MUST be persistable through the framework HWM store so the matrix
    stays consistent across both paths.
    """
    store = HwmStore(tmp_path / "owasp_zap_hwm.json")
    hwm = ScanIdHwm("owasp_zap::cicd_artefact::default", store)
    assert hwm.read() is None

    last_key = "cicd/zap/run-2026-04-21T1000Z/baseline.json"
    hwm.write(last_key)

    resumed = ScanIdHwm("owasp_zap::cicd_artefact::default", store)
    assert resumed.read() == last_key


# ---------------------------------------------------------------------------
# Hybrid trigger-discriminator routing (§3 Quirks of the connector page).
# ---------------------------------------------------------------------------


def test_classify_trigger_routing_table() -> None:
    """The trigger-discriminator routing table is the load-bearing
    operational distinction between the CI/CD-step path and the daemon
    path. Every input MUST map to exactly one trigger_context.
    """
    fixture = _load_fixture("cicd_prefix_routing.json")
    for case in fixture["cases"]:
        assert classify_trigger(case["input"]) == case["expected"], case


def test_classify_trigger_rejects_ambiguous_inputs() -> None:
    """Inputs matching neither the cicd/zap/ marker nor an http(s) scheme
    MUST raise — silent fall-through would let an event land in Bronze
    with the wrong HWM shape.
    """
    fixture = _load_fixture("cicd_prefix_routing.json")
    for bad in fixture["rejected"]:
        with pytest.raises(ValueError):
            classify_trigger(bad)


# ---------------------------------------------------------------------------
# REQ-ING-AUTH — N/A under cicd, bound on the on_demand path.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-AUTH")
@pytest.mark.skip(
    reason="N/A: CI/CD-step artefact path has no native auth on report files; "
    "access governed by object-storage IAM (per catalog matrix N/A column)"
)
def test_auth_not_applicable_under_cicd_path() -> None:
    """REQ-ING-AUTH: N/A in the CI/CD-step path — placeholder for the matrix."""
    raise AssertionError("unreachable — test is skip-marked")


def test_ingest_contract_rejects_missing_apikey_on_daemon_path() -> None:
    """Daemon-path safety guard (sibling to REQ-ING-AUTH): the contract
    wrapper refuses to run when the daemon is selected but the apikey
    is missing.

    ZAP rejects requests with a missing or wrong apikey — the documented
    anti-CSRF defence. Catching the misconfiguration at the contract
    boundary is preferable to a 401-flood at runtime.
    """
    spark = MagicMock()
    state = {
        "source": "owasp_zap",
        "run_id": "rid-missing-apikey",
        "extra": {
            "spark": spark,
            "catalog": "appsec_dev",
            "trigger_context": "on_demand",
            "zap_api_url": "https://zap-daemon.internal:8080",
            # zap_api_key deliberately omitted
        },
    }
    with pytest.raises(ValueError, match="zap_api_key"):
        ingest_contract("rid-missing-apikey", state)


def test_ingest_contract_rejects_missing_catalog() -> None:
    """The contract wrapper refuses to run when the target catalog is unset.

    Misconfiguration must surface as a clear error rather than land
    against the wrong catalog.
    """
    spark = MagicMock()
    state = {
        "source": "owasp_zap",
        "run_id": "rid-missing-catalog",
        "extra": {
            "spark": spark,
            "cicd_bucket": "example-zap",
            "cicd_prefix": "cicd/zap/",
        },
    }
    with pytest.raises(ValueError, match="catalog"):
        ingest_contract("rid-missing-catalog", state)


def test_scrub_apikey_strips_query_parameter_value() -> None:
    """The connector MUST scrub the apikey from any logged URL.

    Per §3 Quirks of the connector page, the apikey is a query-string
    parameter (the documented anti-CSRF defence) — without scrubbing
    it would leak into URL-flavour structured logs.
    """
    raw = (
        "http://zap-daemon.internal:8080/JSON/alert/view/alerts/"
        "?baseurl=https://app.test&start=0&count=5000&apikey=top-secret-key"
    )
    scrubbed = _scrub_apikey(raw)
    assert "top-secret-key" not in scrubbed
    assert "apikey=***" in scrubbed
    # Non-secret components survive the scrub.
    assert "baseurl=https://app.test" in scrubbed


# ---------------------------------------------------------------------------
# REQ-ING-PAG — N/A under cicd; bound on the daemon path.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-PAG")
@pytest.mark.skip(
    reason="N/A under CI/CD-step path (one report per pipeline run); "
    "the daemon-path pagination contract is exercised by "
    "test_iter_paged_alerts_terminates_on_short_page below"
)
def test_pagination_not_applicable_under_cicd_path() -> None:
    """REQ-ING-PAG: N/A under the CI/CD-step path — placeholder for the matrix."""
    raise AssertionError("unreachable — test is skip-marked")


def test_iter_paged_alerts_terminates_on_short_page() -> None:
    """Daemon-path pagination contract: offset/limit iteration over
    /JSON/alert/view/alerts/ terminates on a short page.

    This binds the documented end-of-results signal for the offset
    pagination strategy on the daemon path. (REQ-ING-PAG is matrix-N/A
    for the connector overall because the CI/CD-step path drives the
    PASS profile, but the daemon-path iterator MUST be correct on its
    own — exercised here directly.)
    """
    page1 = _load_fixture("alerts.json")  # 2 items
    page_size = 5
    pages = iter([page1, {"alerts": []}])

    def fetch(_url):
        return next(pages)

    out = list(
        iter_paged_alerts(
            fetch,
            base_url="http://zap-daemon.internal:8080",
            baseurl="https://app.test",
            apikey="abc123",
            page_size=page_size,
        )
    )
    # First page returns 2 < page_size -> loop terminates after page 1.
    assert len(out) == 2
    assert out[0]["pluginId"] == "10038"


def test_build_alerts_url_uses_offset_limit_pagination() -> None:
    """build_alerts_url emits the documented start/count pagination knobs."""
    url = build_alerts_url(
        "http://zap-daemon.internal:8080",
        baseurl="https://app.test",
        apikey="key",
        start=10000,
        count=5000,
    )
    assert ZAP_ENDPOINTS["alert_view_alerts"] in url
    assert "start=10000" in url
    assert "count=5000" in url
    assert "baseurl=https" in url


# ---------------------------------------------------------------------------
# REQ-ING-RL — N/A under cicd; documented as N/A on daemon (no quota).
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-RL")
@pytest.mark.skip(
    reason="N/A: ZAP enforces no documented per-client rate limit; "
    "throughput is daemon-resource bounded. CI/CD-step path has "
    "no API quota at all (N/A per catalog matrix)."
)
def test_rate_limit_not_applicable() -> None:
    """REQ-ING-RL: N/A under both ingestion paths — placeholder for the matrix."""
    raise AssertionError("unreachable — test is skip-marked")


# ---------------------------------------------------------------------------
# Connector-shape sanity (vocabulary, helpers).
# ---------------------------------------------------------------------------


def test_documented_risks_match_reference_vocabulary() -> None:
    """ZAP risk vocabulary MUST be exhaustive over the four documented levels."""
    assert set(DOCUMENTED_RISKS) == {"Informational", "Low", "Medium", "High"}


def test_documented_scan_kinds_match_reference_vocabulary() -> None:
    """The connector orchestrates spider and ascan only — not ajax / brute."""
    assert set(DOCUMENTED_SCAN_KINDS) == {"spider", "ascan"}


def test_split_uri_for_dedup_extracts_target_and_path() -> None:
    """Dedup-tuple component split. Mirrors the transform-side split
    so the dedup key tuple from ingest matches the transform's tuple.
    """
    target, path = split_uri_for_dedup("https://app.test/api/users/42?ref=x")
    assert target == "https://app.test"
    assert path == "/api/users/42?ref=x"


def test_split_uri_for_dedup_handles_bare_host() -> None:
    target, path = split_uri_for_dedup("https://app.test")
    assert target == "https://app.test"
    assert path == "/"


def test_select_alert_name_prefers_name_then_alert() -> None:
    """REST API and JSON-report flavours inconsistently populate name vs alert.
    The connector reads name first, falls back to alert, then plugin id.
    """
    assert select_alert_name({"name": "n1", "alert": "a1"}) == "n1"
    assert select_alert_name({"alert": "a1"}) == "a1"
    assert select_alert_name({"pluginid": "10038"}) == "10038"
    assert select_alert_name({}) is None


def test_normalise_cwe_id_collapses_placeholders() -> None:
    """Both cweid and wascid use '-1' as a string sentinel when unmapped.
    The transform converts this to NULL before writing to Silver.
    """
    assert normalise_cwe_id(None) is None
    assert normalise_cwe_id("") is None
    assert normalise_cwe_id("0") is None
    assert normalise_cwe_id("-1") is None
    assert normalise_cwe_id("79") == "79"
    assert normalise_cwe_id(200) == "200"


# ---------------------------------------------------------------------------
# Live-only paths — skip unless the operator explicitly opts in.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skip(reason="live-only: requires a reachable ZAP daemon")
def test_run_against_live_zap_daemon() -> None:
    """End-to-end pull from a real /JSON/alert/view/alerts/ endpoint."""
    raise AssertionError("unreachable — test is skip-marked")
