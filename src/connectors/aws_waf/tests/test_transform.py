"""AWS WAF transform tests.

Target: silver.findings (was previously the dedicated silver.waf_events;
collapsed for schema uniformity). REQ-ID coverage:

- REQ-TRF-MAP: normalise_event projects each documented WAF log field
  onto the canonical silver.findings shape with correct types and null
  handling for the columns that don't apply (cwe_id, cve_id, repository_id,
  file_path, start_line).
- REQ-TRF-SEV: severity derivation is action-keyed and covers every
  documented action; undocumented actions fall through to ``medium`` (the
  configured default) with a data-quality warning path.
- REQ-TRF-TS: epoch-ms timestamps are normalised to UTC datetime; both
  first_seen_at and last_seen_at carry the same (point-in-time) value.
- REQ-DQ: rows have non-null finding_id (deterministic hash), non-null
  rule_id_native, and the configured status_canonical literal.
- REQ-TRF-STS: status_canonical is the literal ``open`` (matches trufflehog
  convention for sources without a native lifecycle).
- REQ-DEDUP: deterministic finding_id hash collapses re-deliveries; cross-
  tool ``dedup_links`` rows are NOT emitted (WAF doesn't share dedup tuples
  with SAST/SCA/secrets/DAST). N/A on the catalog matrix.

No local SparkSession is instantiated per CLAUDE.md "Don'ts".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.connectors.aws_waf.transform import (
    DEFAULT_SEVERITY,
    STATUS_LITERAL,
    derive_finding_id,
    derive_severity,
    normalise_event,
)

FIX = Path(__file__).parent / "fixtures"
SEVERITY_LOOKUP_PATH = Path(__file__).resolve().parents[1] / "severity.yml"


def _load_severity_lookup() -> dict:
    with SEVERITY_LOOKUP_PATH.open() as fh:
        return yaml.safe_load(fh) or {}


def _load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


@pytest.mark.requirement("REQ-TRF-MAP")
def test_normalise_event_projects_log_record_onto_silver_findings_shape() -> None:
    """REQ-TRF-MAP: every consumed field lands on silver.findings columns."""
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")

    row = normalise_event(raw, lookup)

    # Required columns must be populated.
    assert isinstance(row["finding_id"], str) and len(row["finding_id"]) == 64
    assert row["tool_source"] == "aws_waf"
    assert row["category"] == "waf"
    assert row["severity_canonical"] == "high"
    assert row["status_canonical"] == "open"
    assert row["rule_id_native"] == "AWSManagedRulesCommonRuleSet_XSS"
    assert row["trigger_context"] == "live-traffic"
    assert row["url"] == "/api/checkout"

    # Columns that don't apply to WAF events are null.
    assert row["cwe_id"] is None
    assert row["cve_id"] is None
    assert row["repository_id"] is None
    assert row["file_path"] is None
    assert row["start_line"] is None

    # Telemetry NOT carried by silver.findings is absent from the output.
    assert "source_ip" not in row
    assert "country" not in row
    assert "http_method" not in row
    assert "response_code" not in row
    assert "sampling_weight" not in row
    assert "action" not in row  # action drives severity, then is dropped
    assert "rule_type" not in row
    assert "webacl_arn" not in row  # carried only into the finding_id hash


@pytest.mark.requirement("REQ-TRF-MAP")
def test_silver_target_is_canonical_findings_shape() -> None:
    """Quirk guard: target schema is silver.findings, not silver.waf_events.

    This locks the post-collapse design: WAF events become finding rows
    sharing the canonical envelope with SAST / SCA / secrets / DAST sources.
    """
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    row = normalise_event(raw, lookup)

    # silver.findings markers (must be present)
    assert {"finding_id", "tool_source", "category", "severity_canonical",
            "status_canonical", "rule_id_native", "trigger_context",
            "first_seen_at", "last_seen_at"} <= row.keys()

    # silver.waf_events markers (must be ABSENT — schema collapsed)
    assert "event_id" not in row
    assert "action" not in row
    assert "webacl_arn" not in row


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
    """REQ-TRF-SEV: every documented action maps to a canonical severity."""
    lookup = _load_severity_lookup()
    raw = _load_fixture(fixture)
    row = normalise_event(raw, lookup)
    assert row["severity_canonical"] == expected_severity


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_covers_every_documented_action_value() -> None:
    """Lookup MUST cover every action in the WAF reference vocabulary."""
    lookup = _load_severity_lookup()
    assert {"block", "count", "challenge", "captcha", "allow"} <= set(lookup)


@pytest.mark.requirement("REQ-TRF-SEV")
def test_undocumented_action_falls_through_to_default() -> None:
    """REQ-TRF-SEV: undocumented values fall through to the default."""
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
    """REQ-TRF-TS: WAF ``timestamp`` is epoch-ms; first_seen_at/last_seen_at are UTC datetime."""
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    row = normalise_event(raw, lookup)

    assert isinstance(row["first_seen_at"], datetime)
    assert row["first_seen_at"].tzinfo is UTC
    # Point-in-time: first_seen_at == last_seen_at
    assert row["first_seen_at"] == row["last_seen_at"]


@pytest.mark.requirement("REQ-TRF-TS")
def test_epoch_ms_timestamp_monotonic_across_fixtures() -> None:
    """Ordering is preserved after normalisation — sanity for HWM advance."""
    lookup = _load_severity_lookup()
    t0 = normalise_event(_load_fixture("log_stream_block.json"), lookup)["first_seen_at"]
    t1 = normalise_event(_load_fixture("log_stream_count.json"), lookup)["first_seen_at"]
    t2 = normalise_event(_load_fixture("log_stream_challenge.json"), lookup)["first_seen_at"]
    assert t0 < t1 < t2


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_canonical_is_literal_open() -> None:
    """REQ-TRF-STS (degraded form): status is the literal ``open``.

    Matches the trufflehog convention. WAF events have no native lifecycle;
    the canonical status is fixed.
    """
    assert STATUS_LITERAL == "open"

    lookup = _load_severity_lookup()
    for fixture in (
        "log_stream_block.json",
        "log_stream_count.json",
        "log_stream_challenge.json",
        "log_stream_unknown_action.json",
    ):
        row = normalise_event(_load_fixture(fixture), lookup)
        assert row["status_canonical"] == "open", fixture


@pytest.mark.requirement("REQ-DEDUP")
def test_finding_id_is_deterministic_sha256_of_arn_request_ts() -> None:
    """REQ-DEDUP (degraded form): finding_id is a deterministic hash so
    re-delivery of the same WAF event collapses to one row at MERGE time.

    WAF does NOT participate in cross-tool ``dedup_links`` overlap — this
    binds the replay-only variant documented in references/waf.md.
    """
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    row1 = normalise_event(raw, lookup)
    row2 = normalise_event(raw, lookup)
    # Idempotent: same input → same finding_id.
    assert row1["finding_id"] == row2["finding_id"]
    # Length and hex shape: SHA-256 = 64 hex chars.
    assert len(row1["finding_id"]) == 64
    assert all(c in "0123456789abcdef" for c in row1["finding_id"])


@pytest.mark.requirement("REQ-DEDUP")
def test_finding_id_distinguishes_distinct_events() -> None:
    """Two events differing in any hash component produce distinct finding_ids."""
    lookup = _load_severity_lookup()
    r1 = normalise_event(_load_fixture("log_stream_block.json"), lookup)
    r2 = normalise_event(_load_fixture("log_stream_count.json"), lookup)
    r3 = normalise_event(_load_fixture("log_stream_challenge.json"), lookup)
    assert r1["finding_id"] != r2["finding_id"]
    assert r2["finding_id"] != r3["finding_id"]
    assert r1["finding_id"] != r3["finding_id"]


@pytest.mark.requirement("REQ-DEDUP")
def test_derive_finding_id_requires_all_components() -> None:
    """Defensive path: missing component must raise — no silent collisions."""
    with pytest.raises(ValueError):
        derive_finding_id(None, "req-1", 1713600000000)
    with pytest.raises(ValueError):
        derive_finding_id("arn:aws:wafv2:us-east-1:123:webacl/X/abc", None, 1713600000000)
    with pytest.raises(ValueError):
        derive_finding_id("arn:aws:wafv2:us-east-1:123:webacl/X/abc", "req-1", None)


@pytest.mark.requirement("REQ-DQ")
def test_required_columns_are_non_null_on_every_valid_record() -> None:
    """REQ-DQ: silver.findings NOT NULL columns must populate on valid records.

    finding_id, tool_source, category, severity_canonical, status_canonical,
    rule_id_native, trigger_context, first_seen_at, last_seen_at are all
    NOT NULL on the canonical schema.
    """
    lookup = _load_severity_lookup()
    for fixture in (
        "log_stream_block.json",
        "log_stream_count.json",
        "log_stream_challenge.json",
        "log_stream_unknown_action.json",
    ):
        row = normalise_event(_load_fixture(fixture), lookup)
        for col in ("finding_id", "tool_source", "category", "severity_canonical",
                    "status_canonical", "rule_id_native", "trigger_context",
                    "first_seen_at", "last_seen_at"):
            assert row.get(col) is not None, f"{fixture}: {col} is null"


@pytest.mark.requirement("REQ-DQ")
def test_unknown_rule_id_falls_back_to_sentinel() -> None:
    """REQ-DQ: terminatingRuleId may be null in some sampled-traffic paths;
    transform substitutes the canonical sentinel rather than dropping the row."""
    lookup = _load_severity_lookup()
    raw = _load_fixture("log_stream_block.json")
    raw["terminatingRuleId"] = None
    row = normalise_event(raw, lookup)
    assert row["rule_id_native"] == "UNKNOWN"
