"""TruffleHog bronze ingest (CLI-artefact path).

TruffleHog is a self-contained CLI binary that runs on CI/CD runners; it is
not a service with an API. Each invocation writes `--json` line-delimited
output to a Databricks Volume under object keys shaped
``trufflehog/<repository_id>/<commit_sha>.jsonl``. The connector ingests those
artefacts and normalises them into ``silver.findings``.

This ingest path deviates from the standard Lakeflow Connect → SDK → dlt
preference order per references/secrets.md § "Ingestion-tooling preference":
CLI-based secret scanners are the documented exception alongside Semgrep
Docker (see CLAUDE.md § "Architectural rules"). The connector treats the
volume prefix as the ingestion surface and uses the autoloader-style
``binaryFile`` / JSON reader from Spark to materialise Bronze rows.

Full-reload semantics: there is no record-level update column. The HWM is
the most recent commit SHA per repository (for the ``git`` source kind) and
is supplied as ``--since-commit=<sha>`` on the next CI/CD run purely as an
optimisation. The Bronze-to-Silver dedup key
``(repository_id, commit_sha, secret_type, file_path)`` enforces idempotence
regardless of ``--since-commit``.

REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL are N/A for the CLI-artefact path —
TruffleHog itself has no API to authenticate to, paginate, or be rate-limited
against. Authentication to the upstream source (GitHub PAT, AWS credentials,
SSH key) is handled by the CI/CD runner, out of band of this connector.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from src.common.bronze_schema import with_envelope
from src.common.contract import BatchDescriptor, ConnectorState

_PREFIX_ROOT = "trufflehog"


def parse_artefact_key(key: str) -> tuple[str, str]:
    """Return ``(repository_id, commit_sha)`` extracted from an artefact key.

    Expected key shape: ``trufflehog/<repository_id>/<commit_sha>.jsonl``.
    The shape encodes the dedup label so the connector can recover it even
    when the JSON records happen to omit a field. Raises ``ValueError`` for
    unrecognised shapes so ingest can fail loudly rather than silently
    mis-labelling Bronze rows.
    """
    parts = PurePosixPath(key).parts
    if len(parts) < 3 or parts[0] != _PREFIX_ROOT:
        raise ValueError(f"unrecognised TruffleHog artefact key: {key!r}")
    repository_id = parts[1]
    # Commit SHA is the stem of the final part. Accept `.jsonl`, `.json`, and
    # bare (for flexibility with older runners).
    stem = parts[-1]
    for suffix in (".jsonl", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if not stem:
        raise ValueError(f"unrecognised TruffleHog artefact key: {key!r}")
    return repository_id, stem


def derive_validity_status(verified: bool | None, verification_error: str | None) -> str:
    """Map TruffleHog's ``Verified`` + ``VerificationError`` to canonical ``validity_status``.

    Per mkdocs/docs/connectors/secrets/trufflehog.md § "Enumerations":

    - ``Verified=True``                                      -> ``active``
    - ``Verified=False`` + empty ``VerificationError``       -> ``inactive``
    - ``Verified=False`` + non-empty ``VerificationError``   -> ``unknown``
    - verification not attempted (``--no-verification``, ``Verified is None``) -> ``unknown``
    """
    if verified is True:
        return "active"
    if verified is False:
        if verification_error:
            return "unknown"
        return "inactive"
    # verification not attempted
    return "unknown"


def run_ingest_pipeline(
    spark, volume_uri: str, bronze_table: str, *, run_id: str
) -> None:
    """Databricks entry point. Reads TruffleHog JSONL artefacts into bronze.

    ``volume_uri`` is a Databricks Volume URI rooted at the
    ``trufflehog/`` prefix (e.g. ``/Volumes/<catalog>/<schema>/artefacts``).
    The connector reads line-delimited JSON from that location, stamps the
    bronze envelope (thesis section 2.2.2), and appends to ``bronze_table``.
    """
    from pyspark.sql import functions as F

    df = (
        spark.read.option("multiLine", "false")
        .json(f"{volume_uri.rstrip('/')}/{_PREFIX_ROOT}/")
    )
    # Record the trigger_context for observability; CI/CD-step is the
    # dominant deployment style for TruffleHog per the secrets reference.
    df = df.withColumn("trigger_context", F.lit("cicd"))
    df = with_envelope(
        df,
        source_system="trufflehog",
        batch_id=run_id,
        hwm_value=None,
    )
    df.writeTo(bronze_table).append()


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for TruffleHog.

    The underlying artefact-path ingest keeps its source-specific signature
    (spark session, volume URI, bronze table). This wrapper is invoked by
    the DAB job driver, which reads the non-contract arguments from the
    bundle variables via ``state["extra"]``.
    """
    extra = state.get("extra") or {}
    spark = extra.get("spark")
    volume_uri = extra.get("volume_uri")
    catalog = extra.get("catalog")
    if spark is None or not volume_uri or not catalog:
        raise ValueError(
            "trufflehog.ingest_contract requires state['extra'] with spark, volume_uri, catalog"
        )
    bronze_table = extra.get("bronze_table") or f"{catalog}.bronze_trufflehog.findings"

    run_ingest_pipeline(spark, volume_uri, bronze_table, run_id=run_id)
    return {
        "run_id": run_id,
        "source": "trufflehog",
        "record_count": 0,  # write-directly shape. Count is not surfaced in-process.
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
