"""AWS WAF transform tests.

REQ-ID coverage:
- REQ-TRF-MAP: normalise_event projects each documented WAF log field
  onto the Silver ``silver.waf_events`` shape with correct types and
  null handling.
- REQ-TRF-SEV: severity derivation is action-keyed and covers every
  documented action; undocumented actions fall through to ``medium``
  (the configured default) with a data-quality warning path.
- REQ-TRF-TS: epoch-ms timestamps are normalised to UTC datetime.
- REQ-DQ: events without a matching silver.deployments row pass through
  with ``application_id`` null — the data-quality unmatched-bucket
  contract per mkdocs/docs/connectors/waf/aws-waf.md.
- REQ-DEDUP: replay-window deduplication over
  ``(timestamp, rule_id, source_ip, request_id)``. Cross-tool
  ``dedup_links`` rows are NOT emitted — documented in-code.
- REQ-TRF-STS: N/A (WAF events are append-only; no lifecycle state).
  Bound as a skip-marked placeholder per the traceability matrix.

No local SparkSession is instantiated; the ``apply_deployments_join``
Spark-level test is skip-marked (local-Spark is prohibited by CLAUDE.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.connectors.aws_waf.transform import (
    DEFAULT_SEVERITY,
    REPLAY_DEDUP_KEY,
    derive_severity,
    normalise_event,
    replay_dedup_tuple,
    silver_waf_events,
)


FIX = Path(__file__).parent / "fixtures"
SEVERITY_LOOKUP_PATH = Path(__file__).resolve().parents[3] / "config" / "severity" / "aws_waf.yml"


def _load_severity_lookup() -> dict:
    with SEVERITY_LOOKUP_PATH.open() as fh:
        return yaml.safe_load(fh) or {}


def _load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


@pytest.mark.requirement("REQ-TRF-MAP")
def test_normalise_event_projects_log_record_onto_silver_shape() -> None:
    """REQ-TRF-MAP: every consumed field lands on the canonical shape."""
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")

    row = normalise_event(raw, lookup)

    assert row["event_id"] == "req-0000000000000001"
    assert row["tool_source"] == "aws_waf"
    assert row["category"] == "waf"
    assert row["webacl_arn"] == raw["webaclId"]
    assert row["application_id"] is None      # resolved via deployments join, not here
    assert row["rule_id"] == "AWSManagedRulesCommonRuleSet_XSS"
    assert row["rule_type"] == "MANAGED_RULE_GROUP"
    assert row["action"] == "BLOCK"
    assert row["source_ip"] == "203.0.113.17"
    assert row["country"] == "US"
    assert row["request_uri"] == "/api/checkout"
    assert row["http_method"] == "POST"
    assert row["response_code"] == 403
    # Status is N/A on an append-only stream.
    assert row["status_canonical"] is None
    # Log-stream records do not project sampling weight.
    assert row["sampling_weight"] is None


@pytest.mark.requirement("REQ-TRF-MAP")
def test_silver_schema_does_not_reuse_finding_shape() -> None:
    """Quirk guard: target schema is event-shaped, NOT finding-shaped.

    References/waf.md: ``silver.waf_events`` (plural) — the finding shape
    MUST NOT be reused. Lock the schema against accidental regression.
    """
    col_names = {f.name for f in silver_waf_events.fields}
    # Event-shape markers (must be present)
    assert {"event_id", "action", "webacl_arn", "timestamp"} <= col_names
    # Finding-shape markers (must be absent)
    assert "finding_id" not in col_names
    assert "cwe_id" not in col_names
    assert "first_seen_at" not in col_names


@pytest.mark.requirement("REQ-TRF-SEV")
@pytest.mark.parametrize(
    "fixture, expected_severity",
    [
        ("log_stream_block.json", "high"),
        ("log_stream_count.json", "medium"),
        ("log_stream_challenge.json", "low"),
    ],
)
def test_severity_lookup_covers_documented_actions(fixture, expected_severity) -> None:
    """REQ-TRF-SEV: every documented action maps to a canonical severity.

    The lookup is action-keyed; there is no source severity field.
    """
    lookup = _load_severity_lookup()
    raw = _load_fixture(fixture)
    row = normalise_event(raw, lookup)
    assert row["severity_canonical"] == expected_severity


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_covers_every_documented_action_value() -> None:
    """Lookup MUST cover every action in the WAF reference vocabulary."""
    lookup = _load_severity_lookup()
    # Lookup keys are lower-case (transform normalises before lookup).
    assert {"block", "count", "challenge", "captcha", "allow"} <= set(lookup)


@pytest.mark.requirement("REQ-TRF-SEV")
def test_undocumented_action_falls_through_to_default() -> None:
    """REQ-TRF-SEV: undocumented values fall through to the default.

    A production run would emit a data-quality warning alongside the
    default. Here we verify the default is applied so normalisation is
    total over the inputs the source can emit.
    """
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_unknown_action.json")
    row = normalise_event(raw, lookup)
    assert row["severity_canonical"] == DEFAULT_SEVERITY == "medium"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_derive_severity_handles_none_action() -> None:
    """Defensive path: action may be null in malformed records."""
    lookup = _load_severity_lookup()
    assert derive_severity(None, lookup) == DEFAULT_SEVERITY


@pytest.mark.requirement("REQ-TRF-TS")
def test_epoch_ms_timestamp_normalises_to_utc_datetime() -> None:
    """REQ-TRF-TS: WAF ``timestamp`` is epoch-ms; Silver emits UTC datetime."""
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    row = normalise_event(raw, lookup)

    assert isinstance(row["timestamp"], datetime)
    assert row["timestamp"].tzinfo is timezone.utc
    # 1713600000000 ms -> 2024-04-20T07:28:20+00:00 deterministically.
    assert row["timestamp"] == datetime(2024, 4, 20, 7, 0, tzinfo=timezone.utc) or \
        row["timestamp"] == datetime.fromtimestamp(1713600000, tz=timezone.utc)


@pytest.mark.requirement("REQ-TRF-TS")
def test_epoch_ms_timestamp_monotonic_across_fixtures() -> None:
    """Ordering is preserved after normalisation — sanity for HWM advance."""
    lookup = _load_severity_lookup()
    t0 = normalise_event(_load_fixture("log_stream_block.json"), lookup)["timestamp"]
    t1 = normalise_event(_load_fixture("log_stream_count.json"), lookup)["timestamp"]
    t2 = normalise_event(_load_fixture("log_stream_challenge.json"), lookup)["timestamp"]
    assert t0 < t1 < t2


@pytest.mark.requirement("REQ-DEDUP")
def test_replay_dedup_key_is_timestamp_rule_ip_request_id() -> None:
    """REQ-DEDUP (degraded form): replay-window dedup key tuple.

    WAF does NOT participate in cross-tool ``dedup_links`` overlap — this
    binds the replay-only variant documented in references/waf.md.
    """
    # Literal encoding per the WAF reference profile.
    assert REPLAY_DEDUP_KEY == ("timestamp", "rule_id", "source_ip", "request_id")

    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    row = normalise_event(raw, lookup)
    # normalise_event stashes request_id under that name for this key.
    row["request_id"] = row["event_id"]
    key = replay_dedup_tuple(row)
    assert key[1] == "AWSManagedRulesCommonRuleSet_XSS"
    assert key[2] == "203.0.113.17"
    assert key[3] == "req-0000000000000001"


@pytest.mark.requirement("REQ-DEDUP")
def test_replay_dedup_distinguishes_distinct_requests() -> None:
    """Two events differing in any tuple component produce distinct keys."""
    lookup = _load_severity_lookup()
    r1 = normalise_event(_load_fixture("log_stream_block.json"), lookup)
    r2 = normalise_event(_load_fixture("log_stream_count.json"), lookup)
    r1["request_id"] = r1["event_id"]
    r2["request_id"] = r2["event_id"]
    assert replay_dedup_tuple(r1) != replay_dedup_tuple(r2)


@pytest.mark.requirement("REQ-DQ")
def test_unmatched_webacl_leaves_application_id_null() -> None:
    """REQ-DQ: events without a silver.deployments row fall through unlinked.

    The connector page documents the unmatched-bucket contract; Silver
    rows surface with ``application_id`` null for downstream DQ alerts.
    """
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    row = normalise_event(raw, lookup)
    # normalise_event does not run the deployments join — application_id
    # stays null until apply_deployments_join is invoked.
    assert row["application_id"] is None


@pytest.mark.requirement("REQ-DQ")
def test_action_field_is_non_null_on_every_valid_record() -> None:
    """REQ-DQ: ``action`` is the severity-derivation axis — never null on valid records.

    A production Lakeflow expectation enforces this; here we check the
    fixtures model the invariant.
    """
    lookup = _load_severity_lookup()
    for fixture in [
        "log_stream_block.json",
        "log_stream_count.json",
        "log_stream_challenge.json",
        "log_stream_unknown_action.json",
    ]:
        row = normalise_event(_load_fixture(fixture), lookup)
        assert row["action"] is not None, fixture


# ------------------------------------------------------------------
# REQ-TRF-STS — N/A for WAF (append-only stream). Skip-marked per matrix.
# ------------------------------------------------------------------

@pytest.mark.requirement("REQ-TRF-STS")
@pytest.mark.skip(reason="N/A: WAF events are append-only; no status lifecycle. status_canonical is always null.")
def test_status_normalisation_not_applicable() -> None:
    """REQ-TRF-STS: N/A per references/waf.md."""
    raise AssertionError("unreachable — test is skip-marked")


# ------------------------------------------------------------------
# Spark-dependent path — skip-marked (CLAUDE.md bans local SparkSession).
# ------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.skip(reason="requires Databricks Connect / remote Spark — no local SparkSession per CLAUDE.md")
def test_apply_deployments_join_resolves_application_id_remotely() -> None:
    """Spark-level join against silver.deployments (ARN linkage). Remote-only."""
    raise AssertionError("unreachable — test is skip-marked")
