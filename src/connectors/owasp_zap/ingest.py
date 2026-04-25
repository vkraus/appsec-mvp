"""OWASP ZAP bronze ingest.

Two result sources:
- On-demand API pulls against the long-lived ZAP daemon (trigger_context = 'on_demand').
- CI/CD-step artifacts under s3://<bucket>/cicd/zap/... (trigger_context = 'cicd').

Both flow into the same bronze table with the appropriate trigger_context.
"""

from __future__ import annotations

from src.platform.bronze_schema import with_envelope
from src.platform.contract import BatchDescriptor, ConnectorState


def classify_source(path_or_url: str) -> str:
    """Map an input path/URL to the canonical trigger_context value."""
    if path_or_url.startswith(("s3://", "s3a://")) and "/cicd/zap/" in path_or_url:
        return "cicd"
    if path_or_url.startswith("api://") or path_or_url.startswith("http"):
        return "on_demand"
    raise ValueError(f"cannot classify ZAP source: {path_or_url!r}")


def run_ingest_pipeline(
    spark,
    bucket: str,
    zap_api_url: str,
    zap_api_key: str,
    bronze_table: str,
    *,
    run_id: str,
) -> None:
    """Databricks entry point. Merges both ZAP sources into bronze.

    This is the source-specific ingestion primitive. The framework-contract
    wrapper ``ingest_contract`` dispatches to this function. ``run_id`` is
    stamped as ``_batch_id`` in the bronze envelope (thesis section 2.2.2).
    """
    from pyspark.sql import functions as F

    cicd_df = (
        spark.read.json(f"s3://{bucket}/cicd/zap/")
        .withColumn("trigger_context", F.lit("cicd"))
    )
    cicd_df = with_envelope(
        cicd_df,
        source_system="owasp_zap",
        batch_id=run_id,
        hwm_value=None,
    )
    cicd_df.writeTo(bronze_table).append()


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for OWASP ZAP.

    The underlying artifact-path and API ingest keeps its source-specific
    signature (spark session, bucket, API URL, API key, bronze table).
    This wrapper is invoked by the DAB job driver, which reads the non-contract
    arguments from the bundle variables via ``state["extra"]``.
    """
    extra = state.get("extra") or {}
    spark = extra.get("spark")
    bucket = extra.get("bucket")
    zap_api_url = extra.get("zap_api_url")
    zap_api_key = extra.get("zap_api_key")
    catalog = extra.get("catalog")
    if (
        spark is None
        or bucket is None
        or zap_api_url is None
        or zap_api_key is None
        or not catalog
    ):
        raise ValueError(
            "owasp_zap.ingest_contract requires state['extra'] with spark, bucket, "
            "zap_api_url, zap_api_key, catalog"
        )
    bronze_table = extra.get("bronze_table") or f"{catalog}.bronze_owasp_zap.findings"

    run_ingest_pipeline(
        spark, bucket, zap_api_url, zap_api_key, bronze_table, run_id=run_id
    )
    return {
        "run_id": run_id,
        "source": "owasp_zap",
        "record_count": 0,  # write-directly shape. Count is not surfaced in-process.
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
