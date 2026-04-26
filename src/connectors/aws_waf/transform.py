"""Bronze-to-silver transform for AWS WAF.

Target: ``silver.findings`` (canonical, finding-shape — was previously the
dedicated ``silver.waf_events`` table; collapsed for schema-uniformity with
all other connectors).

Each WAF log record becomes one finding row. Severity is DERIVED from the
``action`` field via the action-keyed lookup at ``severity.yml`` (there is
no source severity field). Status is the literal ``open`` (matches the
trufflehog convention for sources without a native lifecycle).

The ``finding_id`` is a deterministic SHA-256 hash of
``(webacl_arn, request_id, timestamp_ms)`` so re-deliveries of the same
event collapse to the same row at MERGE time. Replay-window deduplication
is achieved by the deterministic hash + a Bronze-to-Silver MERGE.

WAF-specific telemetry NOT carried by ``silver.findings`` (``source_ip``,
``country``, ``http_method``, ``response_code``, ``sampling_weight``,
``rule_type``, ``action`` itself) is intentionally dropped from the
canonical record. Operators who need that detail query the upstream WAF
logs (S3 prefix or CloudWatch) directly. See
``mkdocs/docs/connectors/waf/aws-waf.md``.

Application linkage: WAF events have no native ``repository_id`` (WebACLs
are bound to load balancers, not repos), so ``repository_id`` is null.
Gold-side aggregations that join through ``silver.app_repo_mapping``
will therefore bucket WAF findings under the ``__UNMAPPED__`` sentinel
unless an operator extends the mapping with a webacl_arn → application_id
table (out of scope for the MVP).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pyspark.sql import DataFrame

from src.platform.schemas import silver_findings

# Default severity for undocumented action values (REQ-TRF-SEV).
DEFAULT_SEVERITY: str = "medium"

# Status canonical literal — WAF events have no native lifecycle. Matches
# the trufflehog convention.
STATUS_LITERAL: str = "open"


# Epoch-ms to UTC datetime helper, used by both the pure-Python normaliser
# and the Spark path. WAF log records emit ``timestamp`` as epoch
# milliseconds; the SDK fallback already returns a ``datetime``.
def _epoch_ms_to_utc(ms: int | float) -> datetime:
    if ms is None:
        raise ValueError("aws_waf timestamp is required")
    return datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC)


def derive_severity(action: str | None, lookup: dict) -> str:
    """Return the canonical severity for an AWS WAF action.

    The lookup is action-keyed (block/allow/count/challenge/captcha).
    Action values are normalised to lower-case before lookup; undocumented
    values fall through to ``DEFAULT_SEVERITY`` (``medium``), which — per
    REQ-TRF-SEV — a production run would log as a data-quality warning.
    """
    if action is None:
        return DEFAULT_SEVERITY
    normalised = str(action).lower()
    return lookup.get(normalised, DEFAULT_SEVERITY)


def derive_finding_id(webacl_arn: str | None, request_id: str | None, ts_ms: int | float | None) -> str:
    """Return a deterministic SHA-256 finding_id for a WAF event.

    Hash of ``(webacl_arn, request_id, timestamp_ms)`` so re-deliveries of
    the same event from the upstream Firehose / CloudWatch path collapse
    to one row at MERGE time. All three components are required —
    transforms must validate non-null before calling this.
    """
    if webacl_arn is None or request_id is None or ts_ms is None:
        raise ValueError(
            "derive_finding_id requires webacl_arn, request_id, and ts_ms"
        )
    payload = f"{webacl_arn}|{request_id}|{int(ts_ms)}".encode()
    return hashlib.sha256(payload).hexdigest()


def normalise_event(raw: dict, severity_lookup: dict, *, trigger_context: str = "live-traffic") -> dict:
    """Pure-Python normalisation of a single WAF log record onto silver.findings.

    No Spark required; used in unit tests to exercise REQ-TRF-MAP,
    REQ-TRF-SEV, and REQ-TRF-TS without a local SparkSession.

    Returns a dict with exactly the columns of ``silver.findings``. Any
    WAF-specific telemetry beyond severity / rule_id / url is intentionally
    omitted — the canonical record drops it.
    """
    http = raw.get("httpRequest") or {}
    ts_raw = raw.get("timestamp")
    action = raw.get("action")
    webacl_arn = raw.get("webaclId")
    request_id = http.get("requestId")
    rule_id_native = raw.get("terminatingRuleId") or "UNKNOWN"

    ts_dt = _epoch_ms_to_utc(ts_raw)

    return {
        "finding_id": derive_finding_id(webacl_arn, request_id, ts_raw),
        "tool_source": "aws_waf",
        "category": "waf",
        "severity_canonical": derive_severity(action, severity_lookup),
        "status_canonical": STATUS_LITERAL,
        "cwe_id": None,
        "cve_id": None,
        "rule_id_native": rule_id_native,
        "trigger_context": trigger_context,
        "repository_id": None,
        "file_path": None,
        "start_line": None,
        "url": http.get("uri"),
        "first_seen_at": ts_dt,
        "last_seen_at": ts_dt,
    }


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper.

    Per thesis section 4 Future Work, the full declarative mapping onto
    ``silver.findings`` is not yet wired through the generic ``mapping.yml``
    applicator. This module honors the section 2.4.1 contract
    ``transform(bronze_df) -> silver_df`` by returning an empty
    ``silver_findings``-shaped DataFrame so downstream orchestration can
    chain the call without a runtime error.

    Real implementations: call ``normalise_event`` per Bronze row through
    a Spark UDF (or, once a generic YAML applicator exists, drive the
    mapping declaratively from ``mapping.yml``).
    """
    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)
