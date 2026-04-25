"""Bronze-to-silver transform for Semgrep.

Per the Semgrep connector page (mkdocs/docs/connectors/sast/semgrep.md,
section "Resource schema excerpt > Semgrep CLI JSON output"), this module
projects ``bronze_semgrep.findings`` envelope rows onto ``silver_findings``
by applying the declarative severity and status lookups under
``src/connectors/semgrep/severity.yml`` and
``src/connectors/semgrep/status.yml``, deriving the stable per-run
``finding_id`` triple ``check_id@path:start.line`` (CLI mode emits no
integer ``id``; see Quirks > "CLI mode is stateless"), and projecting
``cwe_id`` from the first element of ``extra.metadata.cwe``.

CLI mode is stateless — every artefact is a complete snapshot with no
server-side lifecycle. The transform defaults ``status_canonical`` to
``open`` for any record without an ``extra.metadata.state`` field, which
covers all CLI-mode findings; the lookup table also covers Cloud Platform
``state`` values for forward compatibility (see status.yml).

The module mirrors the ``src/connectors/sonarqube/transform.py`` shape:

- :func:`transform` — framework contract wrapper
  ``transform(bronze_df) -> silver_df``.
- :func:`findings_to_silver` — fixture-driven path used by tests; takes
  a list of CLI ``results[]`` dicts and returns a Silver DataFrame.
- :func:`dedup_key_for` — pure-Python tuple builder for REQ-DEDUP.

CVE: SAST tools do not emit CVEs (per src/platform/cwe.py and
mapping.yml); ``cve_id`` is projected as ``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.cwe import extract_cwe_from_semgrep
from src.platform.schemas import silver_findings
from src.platform.silver import normalize_severity, normalize_status

_CONNECTOR_DIR = Path(__file__).parent
_SEVERITY_PATH = _CONNECTOR_DIR / "severity.yml"
_STATUS_PATH = _CONNECTOR_DIR / "status.yml"


def _build_finding_id(check_id: str, path: str, start_line: int | None) -> str:
    """Compose the stable per-run finding identifier per mapping.yml:
    ``{check_id}@{path}:{start.line}``. CLI mode has no integer ``id``,
    so this triple is the documented stable form; see semgrep.md
    Quirks > "CLI mode is stateless".
    """
    line = "" if start_line is None else str(start_line)
    return f"{check_id}@{path}:{line}"


def dedup_key_for(finding: dict[str, Any]) -> tuple[str | None, str, str, int | None]:
    """Return the dedup tuple ``(repository_id, file_path, rule_id_native,
    start_line)`` for a Semgrep CLI finding, per the SAST category reference
    (``.claude/skills/generate-connector/references/sast.md`` § "Deduplication
    key"). The tuple is the join basis for ``dedup_links`` in the Silver layer.
    """
    metadata = finding.get("metadata") or {}
    repository_id = metadata.get("repository_id")
    path = finding.get("path") or ""
    rule = finding.get("check_id") or ""
    start_line = (finding.get("start") or {}).get("line")
    return (repository_id, path, rule, start_line)


def _parse_ts(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into a UTC-aware datetime, accepting a
    trailing ``Z`` (per the artefact filename convention used by the
    optional runtime; semgrep itself does not stamp ``results[]`` with a
    timestamp). Returns ``None`` for ``None`` or unparseable input.
    """
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None


def findings_to_silver(
    spark: SparkSession,
    raw: list[dict[str, Any]],
    *,
    trigger_context: str = "cicd",
    scan_started_at: datetime | None = None,
    repository_id: str | None = None,
) -> DataFrame:
    """Direct path from a list of Semgrep CLI ``results[]`` dicts to
    ``silver_findings``. Applies the severity and status lookups, derives
    the stable ``finding_id`` triple, and extracts ``cwe_id`` from
    ``extra.metadata.cwe[0]`` via :func:`src.platform.cwe.extract_cwe_from_semgrep`.

    The Silver schema requires non-null ``first_seen_at`` and
    ``last_seen_at``. CLI artefacts have no per-finding timestamp, so the
    transform stamps both with the artefact's ``scan_started_at`` (or
    current UTC if not provided). On Databricks the bronze envelope's
    ``_ingestion_timestamp`` is used.

    Malformed records — missing ``check_id`` or ``path`` — are dropped
    here (REQ-DQ). On Databricks, an equivalent Lakeflow expectation
    runs at the silver gate.
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    status_map = load_yaml(StatusMap, _STATUS_PATH)
    seen_at = scan_started_at or datetime.now(tz=UTC)

    rows: list[Row] = []
    for r in raw:
        check_id = r.get("check_id")
        path = r.get("path")
        # REQ-DQ: drop malformed rows the Silver schema cannot accept.
        if not check_id or not path:
            continue
        start = r.get("start") or {}
        start_line = start.get("line")
        extra = r.get("extra") or {}
        metadata = extra.get("metadata") or {}

        native_severity = extra.get("severity", "")
        native_state = metadata.get("state")  # CLI emits no state; stays None.

        rows.append(
            Row(
                finding_id=_build_finding_id(check_id, path, start_line),
                tool_source="semgrep",
                category="sast",
                severity_canonical=normalize_severity(native_severity, sev),
                status_canonical=(
                    normalize_status(native_state, status_map)
                    if native_state
                    else "open"
                ),
                cwe_id=extract_cwe_from_semgrep(r),
                cve_id=None,
                rule_id_native=check_id,
                trigger_context=trigger_context,
                repository_id=repository_id,
                file_path=path,
                start_line=start_line,
                url=None,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
        )
    return spark.createDataFrame(rows, schema=silver_findings)


# ---- framework contract ----------------------------------------------------

# Bronze envelope is JSON-text; the source-native columns survive in
# ``_raw_payload``. For the Spark path we parse the payload against the
# documented CLI ``results[]`` element shape.
_RAW_FINDING_SCHEMA = StructType([
    StructField("check_id", StringType(), nullable=False),
    StructField("path", StringType(), nullable=False),
    StructField(
        "start",
        StructType([StructField("line", StringType(), nullable=True)]),
        nullable=True,
    ),
    StructField(
        "extra",
        StructType([
            StructField("severity", StringType(), nullable=True),
            StructField(
                "metadata",
                StructType([
                    StructField("state", StringType(), nullable=True),
                    StructField(
                        "cwe",
                        StringType(),  # JSON-encoded array; first element extracted later.
                        nullable=True,
                    ),
                ]),
                nullable=True,
            ),
        ]),
        nullable=True,
    ),
])


def _map_expr(mapping: dict[str, str], *, default: str):
    """Return a callable that applies a declarative YAML mapping as a
    Spark column expression, coalescing unmapped inputs to ``default``.
    Mirrors ``src/connectors/sonarqube/transform.py``'s helper.
    """
    pairs = []
    for k, v in mapping.items():
        pairs.extend([F.lit(k), F.lit(v)])
    if not pairs:
        return lambda col: F.lit(default)
    mapper = F.create_map(*pairs)
    return lambda col: F.coalesce(mapper[col], F.lit(default))


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract: project ``bronze_semgrep.findings`` envelope
    rows onto ``silver_findings``. Parses the bronze envelope's
    ``_raw_payload`` against the CLI ``results[]`` element shape and
    applies the canonical normalization via the declarative lookups.

    Records missing ``check_id`` or ``path`` are filtered (REQ-DQ).
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    status = load_yaml(StatusMap, _STATUS_PATH)

    sev_expr = _map_expr(sev.root, default="info")
    status_expr_open = _map_expr(status.root, default="open")

    parsed = (
        bronze_df.withColumn(
            "r", F.from_json(F.col("_raw_payload"), _RAW_FINDING_SCHEMA)
        )
        .filter(F.col("r.check_id").isNotNull())
        .filter(F.col("r.path").isNotNull())
    )

    finding_id = F.concat(
        F.col("r.check_id"),
        F.lit("@"),
        F.col("r.path"),
        F.lit(":"),
        F.coalesce(F.col("r.start.line"), F.lit("")),
    )

    return parsed.select(
        finding_id.alias("finding_id"),
        F.lit("semgrep").alias("tool_source"),
        F.lit("sast").alias("category"),
        sev_expr(F.col("r.extra.severity")).alias("severity_canonical"),
        status_expr_open(F.col("r.extra.metadata.state")).alias("status_canonical"),
        # First CWE is in the encoded JSON list; on the Spark path we leave
        # cwe_id null and rely on the side-table enrichment used elsewhere.
        F.lit(None).cast(StringType()).alias("cwe_id"),
        F.lit(None).cast(StringType()).alias("cve_id"),
        F.col("r.check_id").alias("rule_id_native"),
        F.coalesce(F.col("trigger_context"), F.lit("cicd")).alias("trigger_context"),
        F.lit(None).cast(StringType()).alias("repository_id"),
        F.col("r.path").alias("file_path"),
        F.col("r.start.line").cast("int").alias("start_line"),
        F.lit(None).cast(StringType()).alias("url"),
        F.col("_ingestion_timestamp").alias("first_seen_at"),
        F.col("_ingestion_timestamp").alias("last_seen_at"),
    )
