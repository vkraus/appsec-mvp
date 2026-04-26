"""Semgrep bronze ingest (CLI / Docker-artefact path).

Semgrep is a CLI tool that runs in a Docker container — either as a
Kubernetes (EKS) ``CronJob`` (periodic-global lane) or as a GitHub Actions
step (CI/CD-step lane). Both invocations write `--json` or `--sarif` v2.1.0
artefacts to S3 prefixes:

    s3://<bucket>/periodic/semgrep/<repo>/<YYYYMMDDTHHMMSSZ>.{json,sarif}
    s3://<bucket>/cicd/semgrep/<repo>/<commit-sha>.{json,sarif}

The connector ingests those artefacts; it does NOT invoke `semgrep` itself
and does NOT call the Semgrep AppSec Platform Cloud API.

This ingest path deviates from the standard Lakeflow Connect → SDK → dlt
preference order per references/sast.md § "Ingestion-tooling preference":
CLI-based SAST is the documented exception alongside TruffleHog (see
CLAUDE.md § "Architectural rules"). The connector treats the two S3
prefixes as the ingestion surface and uses Auto Loader (cloudFiles) to
materialise Bronze rows. Both prefixes land into one Bronze table with a
`trigger_context` discriminator column ('periodic' | 'cicd').

Full-reload semantics: Semgrep emits no record-level update column. The
HWM differs by lane (per references/sast.md § "Incremental strategy" —
CLI-based SAST):

    cicd lane     -> commit_sha          (HWM is the most recent SHA per repo)
    periodic lane -> scan_start_timestamp (HWM is the most recent ISO8601 ts)

The Bronze→Silver dedup key (repository_id, file_path, rule_id) per
references/sast.md § "Deduplication key" enforces idempotence regardless
of which artefacts get reread.

REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL are N/A for the CLI-artefact path —
Semgrep CLI itself has no API to authenticate to, paginate, or be rate-
limited against. The catalog matrix at
mkdocs/docs/platform/reference/catalog.md marks all three N/A on the
Semgrep row with the rationale "the CLI artifact ingestion path has no
API auth, pagination, or rate limit." Authentication to the artefact
bucket is handled by IAM on the bucket, out of band of this connector.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from src.platform.bronze_schema import with_envelope
from src.platform.contract import BatchDescriptor, ConnectorState

# The two artefact prefixes (per the connector page §3 "API surface").
# Both land in the single bronze_semgrep.findings table; the
# trigger_context column distinguishes them downstream.
PREFIX_CICD = "cicd/semgrep"
PREFIX_PERIODIC = "periodic/semgrep"

TriggerContext = Literal["cicd", "periodic"]

# Recognised artefact extensions. Routing by file extension lets a
# deployment switch flavours (or run both) without connector changes.
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".json", ".sarif")


def detect_trigger_context(key: str) -> TriggerContext:
    """Return the trigger_context discriminator for the artefact key.

    The two prefixes encode the lane (per the connector page § "Quirks"
    — "Two artefact prefixes, one Bronze table, distinguished by
    `trigger_context`"). Raises ``ValueError`` for keys that match neither
    prefix so ingest fails loudly rather than silently mis-tagging rows.
    """
    if not key:
        raise ValueError(f"unrecognised Semgrep artefact key: {key!r}")
    normalised = key.lstrip("/")
    if normalised.startswith(PREFIX_CICD + "/") or normalised == PREFIX_CICD:
        return "cicd"
    if normalised.startswith(PREFIX_PERIODIC + "/") or normalised == PREFIX_PERIODIC:
        return "periodic"
    raise ValueError(
        f"unrecognised Semgrep artefact key: {key!r} "
        f"(expected prefix '{PREFIX_CICD}/' or '{PREFIX_PERIODIC}/')"
    )


def parse_artefact_key(key: str) -> tuple[TriggerContext, str, str]:
    """Return ``(trigger_context, repository_id, hwm_value)`` from an artefact key.

    Expected key shapes (per connector page § "API surface"):

        cicd/semgrep/<repo>/<commit-sha>.{json,sarif}
        periodic/semgrep/<repo>/<YYYYMMDDTHHMMSSZ>.{json,sarif}

    For the cicd lane, ``hwm_value`` is the commit SHA (the stem of the
    final segment). For the periodic lane, ``hwm_value`` is the
    scan-start timestamp (also the stem). The shape encodes the per-
    lane HWM so Bronze can recover it independently of the document
    body. Raises ``ValueError`` for unrecognised shapes.
    """
    trigger_context = detect_trigger_context(key)
    parts = PurePosixPath(key.lstrip("/")).parts
    # Need at least: <lane>/semgrep/<repo>/<stem>.<ext>  -> 4 parts.
    if len(parts) < 4:
        raise ValueError(
            f"unrecognised Semgrep artefact key: {key!r} "
            f"(expected '<lane>/semgrep/<repo>/<stem>.{{json,sarif}}')"
        )
    repository_id = parts[2]
    final = parts[-1]

    stem = final
    matched = False
    for suffix in SUPPORTED_EXTENSIONS:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            matched = True
            break
    if not matched:
        raise ValueError(
            f"unrecognised Semgrep artefact extension: {key!r} "
            f"(expected one of {SUPPORTED_EXTENSIONS})"
        )
    if not stem:
        raise ValueError(f"unrecognised Semgrep artefact key: {key!r}")
    return trigger_context, repository_id, stem


def detect_format(key: str) -> Literal["json", "sarif"]:
    """Return the artefact format ('json' or 'sarif') based on extension.

    Both `--json` (Semgrep-native) and `--sarif` (SARIF v2.1.0) artefacts
    coexist (per connector page § "Quirks" — "JSON and SARIF coexist").
    The transform dispatches on this discriminator so a deployment can
    switch flavours without connector changes.
    """
    if key.endswith(".sarif"):
        return "sarif"
    if key.endswith(".json"):
        return "json"
    raise ValueError(
        f"unrecognised Semgrep artefact extension: {key!r} (expected one of {SUPPORTED_EXTENSIONS})"
    )


def run_ingest_pipeline(spark, bucket_uri: str, bronze_table: str, *, run_id: str) -> None:
    """Databricks entry point. Reads Semgrep JSON / SARIF artefacts into bronze.

    ``bucket_uri`` is the S3 (or volume) URI rooted at the artefact bucket
    that holds ``cicd/semgrep/`` and ``periodic/semgrep/`` prefixes. The
    function reads both prefixes via Auto Loader's ``cloudFiles`` reader,
    stamps the bronze envelope (thesis section 2.2.2), and appends to
    ``bronze_table``. Each row carries its lane's ``trigger_context``
    derived from the source path, NOT from the document body.
    """
    from pyspark.sql import functions as F

    base = bucket_uri.rstrip("/")
    cicd_path = f"{base}/{PREFIX_CICD}/"
    periodic_path = f"{base}/{PREFIX_PERIODIC}/"

    cicd_df = (
        spark.read.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .load(cicd_path)
        .withColumn("trigger_context", F.lit("cicd"))
    )
    periodic_df = (
        spark.read.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .load(periodic_path)
        .withColumn("trigger_context", F.lit("periodic"))
    )
    df = cicd_df.unionByName(periodic_df)

    df = with_envelope(
        df,
        source_system="semgrep",
        batch_id=run_id,
        hwm_value=None,
    )
    df.writeTo(bronze_table).append()


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for Semgrep.

    The underlying CLI-artefact ingest keeps its source-specific signature
    (spark session, bucket URI, bronze table). This wrapper is invoked by
    the DAB job driver, which reads the non-contract arguments from the
    bundle variables via ``state['extra']``.
    """
    extra = state.get("extra") or {}
    spark = extra.get("spark")
    bucket_uri = extra.get("bucket_uri")
    catalog = extra.get("catalog")
    if spark is None or not bucket_uri or not catalog:
        raise ValueError(
            "semgrep.ingest_contract requires state['extra'] with spark, bucket_uri, catalog"
        )
    bronze_table = extra.get("bronze_table") or f"{catalog}.bronze_semgrep.findings"

    run_ingest_pipeline(spark, bucket_uri, bronze_table, run_id=run_id)
    return {
        "run_id": run_id,
        "source": "semgrep",
        "record_count": 0,  # write-directly shape. Count is not surfaced in-process.
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
