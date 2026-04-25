"""AWS WAF bronze ingest.

Two result sources, selected by ``config.yml::ingestion_mode``:

- ``log_stream`` (preferred): autoloader-style Spark read over the
  Firehose-to-S3 prefix. No WAF-API authentication; the Databricks
  workspace's AWS service credential reads from the destination directly.
- ``sdk_sampled`` (fallback only): boto3 WAFv2 ``GetSampledRequests``
  against the account's WebACLs, per the connector page. When this mode
  is chosen the per-record ``Weight`` field MUST be preserved into Bronze
  for downstream extrapolation. CloudFront-scoped WebACLs require the
  ``us-east-1`` regional endpoint.

Both paths stamp the thesis section 2.2.2 bronze envelope and land in
the same bronze table, discriminated by ``_source_system`` subkey
``log_stream`` or ``sdk_sampled`` via the ``ingestion_mode`` column.

Dedup (replay-window, within-source) is performed at transform time
against ``(timestamp, rule_id, source_ip, request_id)`` per
``mkdocs/docs/platform/reference/canonical-mapping.md``. Cross-tool
overlap does NOT apply to WAF — no ``dedup_links`` rows are emitted.
"""

from __future__ import annotations

from collections.abc import Iterator

from src.platform.bronze_schema import with_envelope
from src.platform.contract import BatchDescriptor, ConnectorState

# Documented AWS WAF action values. Used to normalise observed actions
# into the severity lookup's vocabulary; undocumented values fall
# through to the configured default (``medium``) with a data-quality
# warning per REQ-TRF-SEV.
DOCUMENTED_ACTIONS: tuple[str, ...] = (
    "ALLOW",
    "BLOCK",
    "COUNT",
    "CAPTCHA",
    "CHALLENGE",
)


def classify_ingestion_mode(mode: str) -> str:
    """Return the canonical ingestion_mode value for a configured mode.

    Raises ValueError on any value outside the documented surface — the
    log-stream (preferred) / SDK-fallback split is the only legal axis
    per the WAF reference profile.
    """
    if mode not in {"log_stream", "sdk_sampled"}:
        raise ValueError(
            f"aws_waf.ingestion_mode must be 'log_stream' or 'sdk_sampled', got {mode!r}"
        )
    return mode


def iter_sampled_requests(client, web_acl_arn: str, rule_metric_name: str,
                          scope: str, start_time, end_time,
                          max_items: int = 500) -> Iterator[dict]:
    """Yield records from boto3 ``wafv2.get_sampled_requests``.

    Used by the SDK-fallback mode only. ``Weight`` is preserved on each
    yielded record — callers MUST NOT drop it before Bronze write.

    Args:
        client: boto3 ``wafv2`` client. Must be region-bound to ``us-east-1``
            for CloudFront-scoped WebACLs and to the resource's home region
            for regional WebACLs.
        web_acl_arn: WebACL ARN; also projected as ``webaclId`` on each
            emitted record for transform-time deployments join.
        rule_metric_name: The rule's metric name (``GetSampledRequests``
            expects the metric name, not the rule id).
        scope: ``REGIONAL`` or ``CLOUDFRONT``.
        start_time, end_time: datetime bounds; AWS caps the window at
            three hours.
        max_items: hard cap per call (AWS limit 500).
    """
    response = client.get_sampled_requests(
        WebAclArn=web_acl_arn,
        RuleMetricName=rule_metric_name,
        Scope=scope,
        TimeWindow={"StartTime": start_time, "EndTime": end_time},
        MaxItems=max_items,
    )
    for sample in response.get("SampledRequests", []):
        # Preserve the Weight verbatim; downstream extrapolation depends on it.
        # Project webaclId onto the sample so Bronze rows from both modes
        # share the ARN-based linkage key.
        sample["webaclId"] = web_acl_arn
        yield sample


def run_ingest_pipeline(
    spark,
    *,
    ingestion_mode: str,
    bucket: str | None,
    prefix: str | None,
    bronze_table: str,
    run_id: str,
) -> None:
    """Databricks entry point. Reads from the configured surface into bronze.

    Only the ``log_stream`` branch is wired against Spark in the MVP. The
    ``sdk_sampled`` branch is wired through ``iter_sampled_requests`` for
    per-call fidelity but the bulk Bronze write is left to the caller
    (no ad-hoc local HTTP; boto3 is the permitted SDK path per the
    thesis section 2.4.1 tooling preference).

    ``run_id`` is stamped as ``_batch_id`` in the bronze envelope per
    thesis section 2.2.2.
    """
    from pyspark.sql import functions as F

    classify_ingestion_mode(ingestion_mode)

    if ingestion_mode != "log_stream":
        raise NotImplementedError(
            "aws_waf: SDK fallback Spark write is not implemented; use "
            "iter_sampled_requests and write via the caller's driver."
        )

    if not bucket or not prefix:
        raise ValueError(
            "aws_waf log_stream ingest requires bucket and prefix"
        )

    df = (
        spark.read.format("json")
        .option("recursiveFileLookup", "true")
        .load(f"s3://{bucket}/{prefix}")
    )
    df = df.withColumn("ingestion_mode", F.lit("log_stream"))
    df = with_envelope(
        df,
        source_system="aws_waf",
        batch_id=run_id,
        hwm_value=None,      # HWM is max(timestamp) observed; recorded out-of-band
    )
    df.writeTo(bronze_table).append()


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for AWS WAF.

    The log-stream ingestion primitive keeps its source-specific signature
    (spark session, bucket, prefix, bronze table). This wrapper is invoked
    by the DAB job driver, which reads the non-contract arguments from the
    bundle variables via ``state["extra"]``.

    REQ-ING-AUTH: IAM resolution is deferred to the workspace's AWS service
    credential — ``state["extra"]`` does NOT carry raw AWS keys. An explicit
    check for the credential reference raises ValueError when absent so
    misconfiguration surfaces as a clear error rather than a silent failure.
    """
    extra = state.get("extra") or {}
    spark = extra.get("spark")
    catalog = extra.get("catalog")
    ingestion_mode = extra.get("ingestion_mode", "log_stream")
    bucket = extra.get("bucket")
    prefix = extra.get("prefix", "waf/firehose/")
    # REQ-ING-AUTH guard — the IAM service credential reference MUST be set.
    iam_credential_ref = extra.get("aws_credential_ref")

    if spark is None or not catalog:
        raise ValueError(
            "aws_waf.ingest_contract requires state['extra'] with spark, catalog"
        )
    if not iam_credential_ref:
        raise ValueError(
            "aws_waf.ingest_contract requires state['extra']['aws_credential_ref'] "
            "(Databricks AWS service credential name); refusing to run"
        )

    bronze_table = extra.get("bronze_table") or f"{catalog}.bronze_aws_waf.events"

    run_ingest_pipeline(
        spark,
        ingestion_mode=ingestion_mode,
        bucket=bucket,
        prefix=prefix,
        bronze_table=bronze_table,
        run_id=run_id,
    )
    return {
        "run_id": run_id,
        "source": "aws_waf",
        "record_count": 0,   # write-directly shape; count not surfaced in-process
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
