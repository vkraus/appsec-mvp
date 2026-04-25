"""Bronze-to-silver transform for SonarQube.

Per the SonarQube connector page (mkdocs/docs/connectors/sast/sonarqube.md,
section "Mapping example"), this module projects
``bronze_sonarqube.issues`` onto ``silver_findings`` by applying the
declarative severity and status lookups under ``config/severity/`` and
``config/status/``, splitting the ``component`` field on the first colon
to derive ``file_path`` and ``repository_id``, and filtering the
``type`` enumeration to ``BUG`` / ``VULNERABILITY`` (CODE_SMELL findings
are retained in Bronze but are not security findings and are excluded
from Silver).

Rule-pack drift: SonarQube rule IDs follow ``repository:ruleKey`` and are
treated as stable across MVP runs; the dedup key embeds ``rule_id`` as-is
per the SAST category reference (``.claude/skills/generate-connector/
references/sast.md``).

The module intentionally exposes three shapes so the framework contract,
the silver-projection logic, and the dedup-key builder can each be
unit-tested without a live Spark session (CLAUDE.md ``Don'ts`` forbid
local SparkSession fixtures):

- :func:`transform` — framework contract wrapper
  ``transform(bronze_df) -> silver_df``.
- :func:`issues_to_silver` — fixture-driven path used by tests.
- :func:`dedup_key_for` — pure-Python tuple builder for REQ-DEDUP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

from src.common.config import SeverityMap, StatusMap, load_yaml
from src.common.schemas import silver_findings
from src.common.silver import normalize_severity, normalize_status


_CONFIG_ROOT = Path(__file__).parents[3] / "config"
_SEVERITY_PATH = _CONFIG_ROOT / "severity" / "sonarqube.yml"
_STATUS_PATH = _CONFIG_ROOT / "status" / "sonarqube.yml"


_SILVER_TYPES_FOR_FINDINGS: frozenset[str] = frozenset({"BUG", "VULNERABILITY"})


_RAW_ISSUE_SCHEMA = StructType([
    StructField("key", StringType(), nullable=False),
    StructField("rule", StringType(), nullable=False),
    StructField("severity", StringType(), nullable=True),
    StructField("status", StringType(), nullable=True),
    StructField("resolution", StringType(), nullable=True),
    StructField("project", StringType(), nullable=True),
    StructField("component", StringType(), nullable=True),
    StructField("line", IntegerType(), nullable=True),
    StructField("type", StringType(), nullable=True),
    StructField("creationDate", StringType(), nullable=True),
    StructField("updateDate", StringType(), nullable=True),
])


def _parse_sonar_ts(raw: str | None) -> datetime | None:
    """Parse SonarQube's ISO-8601 with numeric offset (e.g.
    ``2026-04-20T10:00:00+0000``) into a timezone-aware UTC datetime.

    The API emits a zero-offset suffix without the colon
    (``+0000``) which ``datetime.fromisoformat`` did not accept before
    Python 3.11. Normalize to the ``+00:00`` form first, then parse.
    """
    if raw is None:
        return None
    normalized = raw
    # "+0000" -> "+00:00"; "-0500" -> "-05:00".
    if len(normalized) >= 5 and normalized[-5] in ("+", "-") and normalized[-3] != ":":
        normalized = normalized[:-2] + ":" + normalized[-2:]
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    return dt.astimezone(timezone.utc)


def split_component(component: str) -> tuple[str, str]:
    """Split a SonarQube component value (``project-key:relative/path``)
    into ``(repository_id, file_path)`` on the first colon.

    Project keys cannot contain colons, so the split is unambiguous (see
    sonarqube.md, "Quirks > Component field encoding").
    """
    if ":" not in component:
        raise ValueError(
            f"sonarqube: component value does not contain ':'; "
            f"cannot split into (project, file_path): {component!r}"
        )
    project, file_path = component.split(":", 1)
    return project, file_path


def compose_status_key(status: str | None, resolution: str | None) -> str:
    """Compose the lookup key for ``config/status/sonarqube.yml``.

    - Issues: when ``status`` is RESOLVED or CLOSED, resolution refines it;
      the composite key is ``STATUS-RESOLUTION``. Otherwise the bare status
      is used.
    - Hotspots: when ``status`` is REVIEWED, the resolution (FIXED / SAFE /
      ACKNOWLEDGED) refines the lifecycle outcome; the composite shape is
      identical to issues (``STATUS-RESOLUTION``).

    ``None`` inputs fall through to the upstream default (``open``) via
    :func:`src.common.silver.normalize_status`.
    """
    if status is None:
        return ""
    if resolution and status in ("RESOLVED", "CLOSED", "REVIEWED"):
        return f"{status}-{resolution}"
    return status


def dedup_key_for(issue: dict[str, Any]) -> tuple[str, str, str]:
    """Return the dedup tuple ``(repository_id, file_path, rule_id)`` for
    a SonarQube issue, per the SAST category reference
    (``references/sast.md`` § "Deduplication key"). The tuple is the
    join basis for ``dedup_links`` in the Silver layer.
    """
    repository_id, file_path = split_component(issue["component"])
    return (repository_id, file_path, issue["rule"])


def issues_to_silver(spark: SparkSession, raw: list[dict[str, Any]]) -> DataFrame:
    """Direct path from a list of SonarQube ``/api/issues/search`` dicts
    to ``silver_findings``. Filters out ``CODE_SMELL`` issues (not
    security findings; see sonarqube.md "Quirks > CODE_SMELL filtering"),
    applies the severity and status lookups, and derives
    ``repository_id`` / ``file_path`` from ``component``.
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    status = load_yaml(StatusMap, _STATUS_PATH)
    rows: list[Row] = []
    for r in raw:
        if r.get("type") == "CODE_SMELL":
            continue
        component = r.get("component") or ""
        try:
            repository_id, file_path = split_component(component)
        except ValueError:
            # The transform contract filters malformed records rather than
            # quarantining here; Lakeflow expectations (REQ-DQ) at the
            # Silver gate perform the quarantine in production.
            continue
        creation = _parse_sonar_ts(r.get("creationDate"))
        update = _parse_sonar_ts(r.get("updateDate"))
        # Silver envelope requires non-null first_seen_at / last_seen_at.
        if creation is None or update is None:
            continue
        rows.append(
            Row(
                finding_id=r["key"],
                tool_source="sonarqube",
                category="sast",
                severity_canonical=normalize_severity(r.get("severity", ""), sev),
                status_canonical=normalize_status(
                    compose_status_key(r.get("status"), r.get("resolution")),
                    status,
                ),
                cwe_id=None,
                rule_id_native=r["rule"],
                trigger_context="periodic",
                repository_id=repository_id,
                file_path=file_path,
                start_line=r.get("line"),
                url=None,
                first_seen_at=creation,
                last_seen_at=update,
            )
        )
    return spark.createDataFrame(rows, schema=silver_findings)


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract: project ``bronze_sonarqube.issues`` envelope
    rows onto ``silver_findings``. Parses the bronze envelope's
    ``_raw_payload`` against the known issue fields and applies the
    canonical normalization via the declarative lookups.

    ``CODE_SMELL`` rows are filtered (see Quirks on the connector page).
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    status = load_yaml(StatusMap, _STATUS_PATH)

    sev_expr = _map_expr(sev.root, default="medium")
    status_expr_open = _map_expr(status.root, default="open")

    parsed = bronze_df.withColumn(
        "r", F.from_json(F.col("_raw_payload"), _RAW_ISSUE_SCHEMA)
    ).filter(F.col("r.type").isin(*_SILVER_TYPES_FOR_FINDINGS))

    status_key = F.when(
        F.col("r.status").isin("RESOLVED", "CLOSED", "REVIEWED")
        & F.col("r.resolution").isNotNull(),
        F.concat_ws("-", F.col("r.status"), F.col("r.resolution")),
    ).otherwise(F.col("r.status"))

    # component split on first ':'; repository_id = left, file_path = right.
    split = F.split(F.col("r.component"), ":", 2)
    repo = split.getItem(0)
    file_path = split.getItem(1)

    return parsed.select(
        F.col("r.key").alias("finding_id"),
        F.lit("sonarqube").alias("tool_source"),
        F.lit("sast").alias("category"),
        sev_expr(F.col("r.severity")).alias("severity_canonical"),
        status_expr_open(status_key).alias("status_canonical"),
        F.lit(None).cast(StringType()).alias("cwe_id"),
        F.col("r.rule").alias("rule_id_native"),
        F.lit("periodic").alias("trigger_context"),
        repo.alias("repository_id"),
        file_path.alias("file_path"),
        F.col("r.line").alias("start_line"),
        F.lit(None).cast(StringType()).alias("url"),
        F.to_timestamp(F.col("r.creationDate")).alias("first_seen_at"),
        F.to_timestamp(F.col("r.updateDate")).alias("last_seen_at"),
    )


def _map_expr(mapping: dict[str, str], *, default: str):
    """Return a callable that applies a declarative YAML mapping as a
    Spark column expression, coalescing unmapped inputs to ``default``.
    """
    pairs = []
    for k, v in mapping.items():
        pairs.extend([F.lit(k), F.lit(v)])
    if not pairs:
        return lambda col: F.lit(default)
    mapper = F.create_map(*pairs)
    return lambda col: F.coalesce(mapper[col], F.lit(default))
