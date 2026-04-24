"""Semgrep bronze ingest.

Reads scan JSON from the shared artifact bucket under two prefixes:
- ``periodic/semgrep/``  produced by the EKS CronJob (long-lived Docker container mode).
- ``cicd/semgrep/``      produced by the Juice Shop GitHub Actions pipeline.

Both paths populate the same bronze table, distinguished by ``trigger_context``.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from src.common.bronze_schema import with_envelope
from src.common.contract import BatchDescriptor, ConnectorState

_PREFIX_TO_CONTEXT = {
    "periodic": "periodic",
    "cicd": "cicd",
}


def classify_prefix(s3_key: str) -> str:
    """Return the trigger_context value for a Semgrep artifact S3 key.

    Raises ValueError if the key does not begin with a recognised prefix.
    """
    parts = PurePosixPath(s3_key).parts
    if len(parts) < 2 or parts[1] != "semgrep":
        raise ValueError(f"unrecognised prefix for Semgrep artifact: {s3_key!r}")
    root = parts[0]
    if root not in _PREFIX_TO_CONTEXT:
        raise ValueError(f"unrecognised prefix for Semgrep artifact: {s3_key!r}")
    return _PREFIX_TO_CONTEXT[root]


def run_ingest_pipeline(
    spark, bucket: str, bronze_table: str, *, run_id: str
) -> None:
    """Databricks entry point. Merges all Semgrep artifacts under both prefixes into bronze.

    This is the source-specific ingestion primitive. The framework-contract
    wrapper ``ingest_contract`` dispatches to this function. ``run_id`` is
    stamped as ``_batch_id`` in the bronze envelope (thesis section 2.2.2).
    """
    from pyspark.sql import functions as F

    base = f"s3://{bucket}"
    df = (
        spark.read.format("binaryFile")
        .option("recursiveFileLookup", "true")
        .load(f"{base}/periodic/semgrep/", f"{base}/cicd/semgrep/")
    )
    df = df.withColumn(
        "trigger_context",
        F.when(F.col("path").contains("/periodic/"), "periodic").otherwise("cicd"),
    )
    df = with_envelope(
        df,
        source_system="semgrep",
        batch_id=run_id,
        hwm_value=None,
    )
    df.writeTo(bronze_table).append()


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for Semgrep.

    The underlying artifact-path ingest keeps its source-specific signature
    (spark session, bucket, bronze table). This wrapper is invoked by the DAB
    job driver, which reads the non-contract arguments from the bundle
    variables via ``state["extra"]``.
    """
    extra = state.get("extra") or {}
    spark = extra.get("spark")
    bucket = extra.get("bucket")
    catalog = extra.get("catalog")
    if spark is None or bucket is None or not catalog:
        raise ValueError(
            "semgrep.ingest_contract requires state['extra'] with spark, bucket, catalog"
        )
    bronze_table = extra.get("bronze_table") or f"{catalog}.bronze_semgrep.findings"

    run_ingest_pipeline(spark, bucket, bronze_table, run_id=run_id)
    return {
        "run_id": run_id,
        "source": "semgrep",
        "record_count": 0,  # write-directly shape. Count is not surfaced in-process.
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
