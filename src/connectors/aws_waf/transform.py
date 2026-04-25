"""Bronze-to-silver transform for AWS WAF.

Target: ``silver.waf_events`` (plural; event-shaped, NOT ``silver.findings``).
Severity is DERIVED from the ``action`` field via the action-keyed lookup
at ``config/severity/aws_waf.yml`` (there is no source severity field).
Status is N/A — WAF events are append-only; the ``status_canonical``
column is left null.

Application linkage: the WebACL ARN (``webaclId``) is joined against
``silver.deployments`` at transform time to resolve ``application_id``.
This mirrors the DAST ``target`` join in shape.

Replay-window deduplication (within-source) is performed over
``(timestamp, rule_id, source_ip, request_id)`` per the WAF capability
surface. This recovers from re-delivered events only; the canonical
``dedup_links`` table targets cross-tool finding overlap, which WAF
does NOT participate in. See
``mkdocs/docs/platform/reference/canonical-mapping.md``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pyspark.sql import DataFrame
from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


# Replay-window dedup key — encoded literally per references/waf.md.
# Cross-tool overlap is NOT emitted (no dedup_links rows for WAF).
REPLAY_DEDUP_KEY: tuple[str, ...] = (
    "timestamp",
    "rule_id",
    "source_ip",
    "request_id",
)


# Silver-side schema for silver.waf_events. Event-shape; deliberately not
# reusing silver_findings (which is finding-shape).
silver_waf_events = StructType([
    StructField("event_id", StringType(), nullable=False),
    StructField("tool_source", StringType(), nullable=False),
    StructField("category", StringType(), nullable=False),
    StructField("timestamp", TimestampType(), nullable=False),
    StructField("webacl_arn", StringType(), nullable=False),
    StructField("application_id", StringType(), nullable=True),   # resolved via ARN join
    StructField("rule_id", StringType(), nullable=True),
    StructField("rule_type", StringType(), nullable=True),
    StructField("action", StringType(), nullable=False),
    StructField("severity_canonical", StringType(), nullable=False),
    StructField("status_canonical", StringType(), nullable=True), # N/A (append-only)
    StructField("source_ip", StringType(), nullable=True),
    StructField("country", StringType(), nullable=True),
    StructField("request_uri", StringType(), nullable=True),
    StructField("http_method", StringType(), nullable=True),
    StructField("response_code", IntegerType(), nullable=True),
    StructField("sampling_weight", LongType(), nullable=True),
    StructField("ingested_at", TimestampType(), nullable=False),
])


# Epoch-ms to UTC datetime helper, used by both the pure-Python normaliser
# and the Spark path. WAF log records emit ``timestamp`` as epoch
# milliseconds; the SDK fallback already returns a ``datetime``.
def _epoch_ms_to_utc(ms: int | float) -> datetime:
    if ms is None:
        raise ValueError("aws_waf timestamp is required")
    return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)


# Default severity for undocumented action values (REQ-TRF-SEV).
DEFAULT_SEVERITY: str = "medium"


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


def replay_dedup_tuple(row: dict) -> tuple:
    """Return the (timestamp, rule_id, source_ip, request_id) tuple for a row.

    Used for replay-window deduplication — within-source only, recovering
    from re-delivered events. NOT to be confused with cross-tool
    ``dedup_links`` linkage (which WAF does not participate in).
    """
    return (
        row.get("timestamp"),
        row.get("rule_id"),
        row.get("source_ip"),
        row.get("request_id"),
    )


def normalise_event(raw: dict, severity_lookup: dict) -> dict:
    """Pure-Python normalisation of a single WAF log record onto the Silver shape.

    No Spark required; used in unit tests to exercise REQ-TRF-MAP,
    REQ-TRF-SEV, and REQ-TRF-TS without a local SparkSession.

    The ``application_id`` field is left null here; it is resolved by
    ``apply_deployments_join`` when a silver.deployments DataFrame is
    available.
    """
    http = raw.get("httpRequest") or {}
    ts_raw = raw.get("timestamp")
    action = raw.get("action")
    return {
        "event_id": http.get("requestId"),
        "tool_source": "aws_waf",
        "category": "waf",
        "timestamp": _epoch_ms_to_utc(ts_raw),
        "webacl_arn": raw.get("webaclId"),
        "application_id": None,
        "rule_id": raw.get("terminatingRuleId"),
        "rule_type": raw.get("terminatingRuleType"),
        "action": action,
        "severity_canonical": derive_severity(action, severity_lookup),
        "status_canonical": None,   # N/A per append-only stream
        "source_ip": http.get("clientIp"),
        "country": http.get("country"),
        "request_uri": http.get("uri"),
        "http_method": http.get("httpMethod"),
        "response_code": raw.get("responseCodeSent"),
        # SDK-fallback rows project sampling weight; log-stream rows do not.
        "sampling_weight": raw.get("Weight"),
        # Convenience field used by replay_dedup_tuple; not projected into
        # the Silver schema.
        "request_id": http.get("requestId"),
    }


def apply_deployments_join(events_df: DataFrame, deployments_df: DataFrame) -> DataFrame:
    """Resolve ``application_id`` by joining on the WebACL ARN.

    ``silver.deployments`` is expected to carry columns ``webacl_arn`` and
    ``application_id``. Events without a matching deployment row pass
    through with ``application_id`` null; the REQ-DQ unmatched-bucket
    expectation would flag them in a production pipeline.

    Mirrors the DAST ``target`` join in shape; see ``references/waf.md``
    for the category invariant.
    """
    from pyspark.sql import functions as F

    joined = events_df.alias("e").join(
        deployments_df.alias("d"),
        F.col("e.webacl_arn") == F.col("d.webacl_arn"),
        how="left",
    )
    return joined.select(
        *[F.col(f"e.{c.name}") for c in events_df.schema.fields if c.name != "application_id"],
        F.col("d.application_id").alias("application_id"),
    )


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper.

    Per thesis section 4 Future Work, the full declarative mapping onto
    ``silver.waf_events`` (with the declarative severity-lookup applicator
    and the ``silver.deployments`` join) is not yet wired through the
    generic ``mapping.yml`` applicator. This module honors the section
    2.4.1 contract ``transform(bronze_df) -> silver_df`` by returning an
    empty ``silver_waf_events`` DataFrame so downstream orchestration can
    chain the call without a runtime error.

    Real implementations: call ``normalise_event`` per Bronze row through
    a Spark UDF or, once a generic YAML applicator exists, drive the
    mapping declaratively from ``mapping.yml``. Then call
    ``apply_deployments_join`` to resolve ``application_id`` via the
    WebACL ARN join.
    """
    return bronze_df.sparkSession.createDataFrame([], schema=silver_waf_events)
