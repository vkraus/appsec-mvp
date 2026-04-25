"""Bronze-to-silver transform for OWASP ZAP.

Projects the ZAP scan-report envelope onto ``silver_findings`` per the
declarative ``mapping.yml`` shape. ZAP emits a nested document
``site[].alerts[].instances[]``; one Silver row is produced per
``(site, alert, instance)`` triple.

DAST shape (per ``references/dast.md`` and ``mapping.yml``):

- ``url`` carries the per-instance URI (the scanned path that triggered
  the alert).
- ``rule_id_native`` carries the ZAP plugin id (the scanner-internal
  rule identifier).
- ``file_path`` and ``start_line`` are NULL — DAST findings are URL-,
  not file-, located.
- ``cwe_id`` is projected from ZAP's ``cweid`` when present and not
  the placeholder ``""``, ``"0"``, or ``"-1"``.
- ``cve_id`` is NULL — ZAP does not emit CVE identifiers.
- ``status_canonical`` is always ``"open"`` — ZAP scans are
  point-in-time snapshots with no server-side lifecycle. Transition
  to ``resolved`` is computed at the Silver layer by absence in
  successive scans (see status.yml header).

Application linkage (``application_id``) is resolved by joining
``target`` (scheme+host+port from the scanned URI) against
``silver.deployments`` per references/dast.md § "Target Silver tables".
Unmatched targets pass through with a null linkage — this is a
deliberate completeness signal for inventory-gap analysis, NOT a DQ
failure (do NOT drop rows; do NOT raise).

The module exposes four shapes so the framework contract, the
silver-projection logic, the dedup-key builder, and the
deployments-join can each be unit-tested without a live Spark session
(CLAUDE.md ``Don'ts`` forbid local SparkSession fixtures for pure
logic):

- :func:`transform` — framework contract wrapper
  ``transform(bronze_df) -> silver_df``.
- :func:`alerts_to_silver` — fixture-driven path used by tests.
- :func:`dedup_key_for` — pure-Python tuple builder for REQ-DEDUP.
- :func:`apply_deployments_join` — Spark-only ``target`` ->
  ``application_id`` resolver.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    StringType,
    StructField,
    StructType,
)

from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.schemas import silver_findings
from src.platform.silver import normalize_severity, normalize_status

_CONNECTOR_DIR = Path(__file__).parent
_SEVERITY_PATH = _CONNECTOR_DIR / "severity.yml"
_STATUS_PATH = _CONNECTOR_DIR / "status.yml"


# ZAP placeholder cweid values that mean "no CWE classification" — both
# `cweid` and `wascid` use `-1` as a sentinel when unmapped (§3 Quirks).
_CWE_PLACEHOLDERS: frozenset[str] = frozenset({"", "0", "-1"})


# Bronze ``_raw_payload`` shape: the ZAP scan-report JSON envelope. The
# Spark path uses this schema with ``from_json`` to project the nested
# alert/instance structure into rows.
_RAW_INSTANCE_SCHEMA = StructType([
    StructField("uri", StringType(), nullable=True),
    StructField("method", StringType(), nullable=True),
    StructField("evidence", StringType(), nullable=True),
])

_RAW_ALERT_SCHEMA = StructType([
    StructField("pluginid", StringType(), nullable=True),
    StructField("alert", StringType(), nullable=True),
    StructField("name", StringType(), nullable=True),
    StructField("riskdesc", StringType(), nullable=True),
    StructField("riskcode", StringType(), nullable=True),
    StructField("confidence", StringType(), nullable=True),
    StructField("cweid", StringType(), nullable=True),
    StructField("wascid", StringType(), nullable=True),
    StructField("instances", ArrayType(_RAW_INSTANCE_SCHEMA), nullable=True),
])

_RAW_SITE_SCHEMA = StructType([
    StructField("@name", StringType(), nullable=True),
    StructField("@host", StringType(), nullable=True),
    StructField("alerts", ArrayType(_RAW_ALERT_SCHEMA), nullable=True),
])

_RAW_REPORT_SCHEMA = StructType([
    StructField("site", ArrayType(_RAW_SITE_SCHEMA), nullable=True),
    StructField("@generated", StringType(), nullable=True),
])


def _parse_zap_generated_at(raw: str | None) -> datetime | None:
    """Parse ZAP's ``@generated`` scan timestamp into a UTC-aware datetime.

    ZAP emits human-readable ``"Tue, 21 Apr 2026 10:00:00"`` (no
    timezone) at scan time. The framework's timestamp contract requires
    UTC; absent a source offset we treat scan-report time as UTC at the
    Bronze layer (the ZAP daemon's clock is the only authority).
    Returns None on unparseable input — callers fall through to a
    runtime-stamped timestamp.
    """
    if raw is None:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            naive = datetime.strptime(raw, fmt)
            return naive.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _normalize_cwe(raw: Any) -> str | None:
    """Project ZAP ``cweid`` onto the Silver ``cwe_id`` string column.

    Returns None for missing values and the documented ZAP placeholders
    (``""``, ``"0"``, ``"-1"``). All other values are coerced to a string.
    The enrichment side-table (``src/platform/cwe.py``) decorates the
    integer with the ``CWE-`` prefix downstream; the connector
    transform stays in the source-native string form.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s in _CWE_PLACEHOLDERS:
        return None
    return s


def _split_target(uri: str | None) -> tuple[str | None, str | None]:
    """Split a ZAP per-instance ``uri`` into ``(target, uri_path)``.

    DUPLICATE of ``ingest.split_uri_for_dedup`` so the transform can
    do the split without a forward dependency on ingest. The two
    implementations are kept in sync — see test_transform for the
    pinned-shape check.
    """
    if not uri or not isinstance(uri, str):
        return (None, None)
    scheme_end = uri.find("://")
    if scheme_end < 0:
        return (None, uri)
    rest_start = scheme_end + 3
    path_start = uri.find("/", rest_start)
    if path_start < 0:
        return (uri, "/")
    return (uri[:path_start], uri[path_start:])


def dedup_key_for(
    target: str | None, alert_id: str | None, uri_path: str | None
) -> tuple[str | None, str | None, str | None]:
    """Return the dedup tuple ``(target, alert_id, uri_path)`` per the
    DAST category reference (``references/dast.md`` § "Deduplication
    key") and ``mapping.yml``'s ``dedup_key`` block.

    The tuple is the join basis for ``dedup_links`` in the Silver layer.
    Note: the canonical Silver ``silver.findings.url`` carries the full
    URI; the dedup tuple's ``target`` component is the scheme+host+port
    portion of that URI, derived via :func:`_split_target`.
    """
    return (target, alert_id, uri_path)


def _make_finding_id(plugin_id: str | None, uri: str | None) -> str:
    """Compose ``finding_id`` per ``mapping.yml``: ``pluginid + "@" + uri``.

    Both halves are required to land in Silver (the schema marks
    ``finding_id`` non-nullable); REQ-DQ at the transform gate filters
    rows missing either half before this point.
    """
    return f"{plugin_id}@{uri}"


def _extract_risk(riskdesc: str | None) -> str | None:
    """Extract the risk level from ZAP's ``riskdesc`` field.

    The field is composed as ``"<Risk> (<Confidence>)"`` (e.g.
    ``"Medium (High)"``). When the field carries only the bare risk
    word it is returned as-is.
    """
    if not riskdesc:
        return None
    head = riskdesc.split(" (", 1)[0].strip()
    return head or None


def alerts_to_silver(
    spark: SparkSession,
    raw: list[dict[str, Any]],
    *,
    trigger_context: str = "cicd",
    fallback_now: datetime | None = None,
) -> DataFrame:
    """Direct path from a list of ZAP scan-report dicts to ``silver_findings``.

    Each dict matches the JSON document shape (``site[].alerts[]
    .instances[]``). The function flattens to one row per
    ``(site, alert, instance)`` and applies the severity / status
    lookups from ``severity.yml`` / ``status.yml`` (co-located alongside
    this connector module).

    REQ-DQ: rows with no ``pluginid``, no ``site``, or no instance
    ``uri`` are dropped (silver_findings.finding_id is non-nullable;
    the synthetic id requires both halves; the ``target`` dedup
    component requires a host).
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    status_map = load_yaml(StatusMap, _STATUS_PATH)

    rows: list[Row] = []
    for report in raw:
        report_ts = _parse_zap_generated_at(report.get("@generated")) or fallback_now
        if report_ts is None:
            report_ts = datetime.now(tz=UTC)
        for site in report.get("site") or []:
            site_target = site.get("@name") or site.get("@host")
            if not site_target:
                continue
            for alert in site.get("alerts") or []:
                plugin_id = alert.get("pluginid")
                if not plugin_id:
                    continue
                # Severity is keyed off the four-level ``risk`` vocabulary.
                # ZAP's JSON report carries it inside ``riskdesc`` (e.g.
                # ``"Medium (Medium)"``); the leading token is the risk
                # level, the parenthesized token is confidence.
                risk = _extract_risk(alert.get("riskdesc"))
                cwe = _normalize_cwe(alert.get("cweid"))
                instances = alert.get("instances") or []
                if not instances:
                    # ZAP rarely emits an alert without instances; defensive:
                    # REQ-DQ requires we drop rows that cannot produce a
                    # valid (target, alert_id, uri_path) dedup key.
                    continue
                for inst in instances:
                    uri = inst.get("uri")
                    if not uri:
                        continue
                    rows.append(
                        Row(
                            finding_id=_make_finding_id(plugin_id, uri),
                            tool_source="owasp_zap",
                            category="dast",
                            severity_canonical=normalize_severity(risk or "", sev),
                            # ZAP has no server-side lifecycle; status.yml
                            # collapses any input to "open".
                            status_canonical=normalize_status("open", status_map),
                            cwe_id=cwe,
                            cve_id=None,    # DAST: no CVE axis
                            rule_id_native=plugin_id,
                            trigger_context=trigger_context,
                            # application_id is resolved by
                            # apply_deployments_join, not here.
                            repository_id=None,
                            file_path=None,    # DAST shape: URL-located
                            start_line=None,
                            url=uri,
                            first_seen_at=report_ts,
                            last_seen_at=report_ts,
                        )
                    )
    return spark.createDataFrame(rows, schema=silver_findings)


def apply_deployments_join(findings_df: DataFrame, deployments_df: DataFrame) -> DataFrame:
    """Resolve ``application_id`` by joining ``target`` (host portion of
    the URI) against ``silver.deployments``.

    Per ``references/dast.md`` § "Target Silver tables", the join is
    LEFT — unmatched targets pass through with ``application_id`` null
    so an inventory-gap report can surface them downstream. This is a
    deliberate completeness signal — DO NOT drop rows; DO NOT raise on
    unmatched targets.

    ``silver.deployments`` is expected to carry columns ``target``
    (scheme+host+port) and ``application_id``. The join key matches
    the dedup tuple's ``target`` component verbatim.

    The ``url`` column on ``findings_df`` is the full URI; the
    ``target`` projection is the scheme+host+port derived via
    :func:`_split_target`. This helper assumes the caller has already
    materialised that derivation onto ``findings_df`` as a
    ``target`` column. (The ``alerts_to_silver`` path stops at the
    Silver schema columns; the join helper is composed onto the
    output by the orchestrating notebook.)
    """
    return findings_df.alias("f").join(
        deployments_df.alias("d"),
        F.col("f.target") == F.col("d.target"),
        how="left",
    ).select(
        *[F.col(f"f.{c.name}") for c in findings_df.schema.fields],
        F.col("d.application_id").alias("application_id"),
    )


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract: project ``bronze_owasp_zap.findings`` envelope
    rows onto ``silver_findings``.

    The bronze envelope's ``_raw_payload`` carries the full ZAP JSON
    scan-report document per write. The transform parses the envelope,
    explodes ``site -> alerts -> instances``, applies the canonical
    normalization via the declarative lookups, and projects the
    DAST-shaped Silver row.

    REQ-DQ: rows with no ``pluginid``, no scanned ``@name`` /
    ``@host``, or no instance ``uri`` are filtered before they can
    land in Silver (``finding_id`` non-nullable in the schema, plus
    the dedup tuple requires all three).
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    status_map = load_yaml(StatusMap, _STATUS_PATH)

    sev_expr = _map_expr(sev.root, default="info")
    status_expr_open = _map_expr(status_map.root, default="open")

    # Parse envelope payload into the typed scan-report struct, then
    # explode the nested site/alert/instance hierarchy.
    parsed = bronze_df.withColumn(
        "_zap", F.from_json(F.col("_raw_payload"), _RAW_REPORT_SCHEMA)
    )
    sites = parsed.select(
        F.col("trigger_context").alias("_trigger_context")
        if "trigger_context" in bronze_df.columns
        else F.lit("cicd").alias("_trigger_context"),
        F.col("_ingestion_timestamp").alias("_ingestion_timestamp"),
        F.explode(F.col("_zap.site")).alias("_site"),
    )
    alerts = sites.select(
        F.col("_trigger_context"),
        F.col("_ingestion_timestamp"),
        F.coalesce(F.col("_site.`@name`"), F.col("_site.`@host`")).alias("_target"),
        F.explode(F.col("_site.alerts")).alias("_alert"),
    ).filter(F.col("_target").isNotNull() & (F.col("_target") != ""))
    instances = alerts.select(
        F.col("_trigger_context"),
        F.col("_ingestion_timestamp"),
        F.col("_target"),
        F.col("_alert"),
        F.explode(F.col("_alert.instances")).alias("_inst"),
    ).filter(
        F.col("_alert.pluginid").isNotNull()
        & (F.col("_alert.pluginid") != "")
        & F.col("_inst.uri").isNotNull()
        & (F.col("_inst.uri") != "")
    )

    # Risk is the leading token of ``riskdesc`` (e.g. "Medium (High)").
    risk = F.trim(F.split(F.col("_alert.riskdesc"), r"\s*\(", 2).getItem(0))

    # cweid placeholders ("", "0", "-1") collapse to NULL.
    cwe = F.when(
        F.col("_alert.cweid").isNull()
        | F.col("_alert.cweid").isin("", "0", "-1"),
        F.lit(None).cast(StringType()),
    ).otherwise(F.col("_alert.cweid"))

    return instances.select(
        F.concat_ws("@", F.col("_alert.pluginid"), F.col("_inst.uri")).alias(
            "finding_id"
        ),
        F.lit("owasp_zap").alias("tool_source"),
        F.lit("dast").alias("category"),
        sev_expr(risk).alias("severity_canonical"),
        status_expr_open(F.lit("open")).alias("status_canonical"),
        cwe.alias("cwe_id"),
        F.lit(None).cast(StringType()).alias("cve_id"),
        F.col("_alert.pluginid").alias("rule_id_native"),
        F.col("_trigger_context").alias("trigger_context"),
        F.lit(None).cast(StringType()).alias("repository_id"),
        F.lit(None).cast(StringType()).alias("file_path"),
        F.lit(None).cast("int").alias("start_line"),
        F.col("_inst.uri").alias("url"),
        # Bronze ``_ingestion_timestamp`` is the only timestamp the
        # framework guarantees on every envelope row; ZAP's
        # ``@generated`` lives inside the JSON payload but is not
        # required to be present.
        F.col("_ingestion_timestamp").alias("first_seen_at"),
        F.col("_ingestion_timestamp").alias("last_seen_at"),
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
