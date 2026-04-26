# Databricks notebook source
# ruff: noqa: F821 — dbutils / spark are injected by the Databricks notebook runtime
"""Gold notebook: ``gold.mttr_by_source_severity_weekly``.

Aggregates Mean-Time-To-Remediate distributions for *resolved* findings,
bucketed by ISO year + ISO week of the resolution timestamp, and split
by ``tool_source`` × ``severity_canonical``.

Inputs
------
- ``silver.findings`` — canonical immutable findings record (columns used:
  ``tool_source``, ``severity_canonical``, ``status_canonical``,
  ``first_seen_at``, ``last_seen_at``).
- ``silver.suppression_rules`` — operator-authored INSERT-only mutes.
  Applied at Gold-aggregation time via
  :mod:`src.analytics.lib.suppression`.

Output
------
``gold.mttr_by_source_severity_weekly`` (overwrite). Schema:

    iso_year             INT
    iso_week             INT
    tool_source          STRING
    severity_canonical   STRING
    mttr_median_hours    DOUBLE
    mttr_p90_hours       DOUBLE
    sample_size          INT

Logic
-----
1. Load findings + rules.
2. Apply suppression on findings (rules with ``scope`` in
   {tool_source, category, repository_id, file_path, rule_id_native}
   apply pre-join; ``application_id`` rules are silently skipped here
   because the findings df does not carry ``application_id``).
3. Filter to ``status_canonical = 'resolved'`` rows only.
4. For each resolved row: ``resolved_at`` = ``last_seen_at`` (the most
   recent scan that observed the row in the resolved state). MTTR (hours)
   = ``(last_seen_at - first_seen_at) / 3600``.
5. Group by ISO-year(``last_seen_at``), ISO-week(``last_seen_at``),
   ``tool_source``, ``severity_canonical``. Compute median + p90 of
   MTTR-hours; ``sample_size`` is the row count.
6. Write Delta overwrite.

The pure-Python helper :func:`compute_mttr_rows` is unit-tested against
synthetic dict-based fixtures (no local SparkSession per CLAUDE.md). The
Spark application below is exercised on the Databricks job cluster.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any, Iterable, Mapping

from src.analytics.lib.suppression import is_row_suppressed


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct``-th percentile of ``values`` using the simple
    sorted-list-index method (``int(pct * n)``).

    Matches the spec's manual p90 definition. ``values`` must be non-empty.
    """
    sorted_vals = sorted(values)
    idx = int(pct * len(sorted_vals))
    if idx >= len(sorted_vals):
        idx = len(sorted_vals) - 1
    return float(sorted_vals[idx])


def _iso_year_week(ts: datetime) -> tuple[int, int]:
    """Return (ISO year, ISO week) for ``ts`` per the ISO-8601 calendar.

    Wraps :meth:`datetime.isocalendar` to return plain ``int`` pair, which
    is what the Gold table schema expects.
    """
    iso = ts.isocalendar()
    return int(iso[0]), int(iso[1])


def compute_mttr_rows(
    findings_rows: Iterable[Mapping[str, Any]],
    suppression_rules: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Pure-Python reference implementation of the MTTR aggregation.

    Drives both the unit tests (synthetic dict fixtures) and the documented
    semantics for the Spark wrapper below. Steps mirror the notebook flow:

    1. Drop suppressed findings (any active applicable rule matches).
    2. Drop non-resolved findings (``status_canonical != 'resolved'``).
    3. Compute per-row MTTR-hours from
       ``(last_seen_at - first_seen_at).total_seconds() / 3600``.
    4. Group by (iso_year(last_seen_at), iso_week(last_seen_at),
       tool_source, severity_canonical).
    5. For each group, emit median, p90, and sample size.

    Returns a list of dicts sorted by (iso_year, iso_week, tool_source,
    severity_canonical) for stable test assertions.
    """
    rules_list = list(suppression_rules)

    # Step 1+2: filter to resolved + un-suppressed rows.
    survivors: list[Mapping[str, Any]] = []
    for row in findings_rows:
        if is_row_suppressed(row, rules_list, now=now):
            continue
        if row.get("status_canonical") != "resolved":
            continue
        survivors.append(row)

    # Step 3+4: compute MTTR-hours and bucket by (iso_year, iso_week,
    # tool_source, severity_canonical). dict keyed on the grouping tuple,
    # value accumulates MTTR-hours samples.
    buckets: dict[tuple[int, int, str, str], list[float]] = {}
    for row in survivors:
        first_seen: datetime = row["first_seen_at"]
        last_seen: datetime = row["last_seen_at"]
        seconds = (last_seen - first_seen).total_seconds()
        mttr_hours = seconds / 3600.0
        iso_year, iso_week = _iso_year_week(last_seen)
        key = (
            iso_year,
            iso_week,
            row["tool_source"],
            row["severity_canonical"],
        )
        buckets.setdefault(key, []).append(mttr_hours)

    # Step 5: emit one row per bucket. statistics.median for the median;
    # the manual sorted-index p90 per spec.
    out: list[dict[str, Any]] = []
    for (iso_year, iso_week, tool_source, severity), samples in buckets.items():
        out.append({
            "iso_year": iso_year,
            "iso_week": iso_week,
            "tool_source": tool_source,
            "severity_canonical": severity,
            "mttr_median_hours": float(statistics.median(samples)),
            "mttr_p90_hours": _percentile(samples, 0.9),
            "sample_size": len(samples),
        })

    out.sort(key=lambda r: (
        r["iso_year"],
        r["iso_week"],
        r["tool_source"],
        r["severity_canonical"],
    ))
    return out


# COMMAND ----------
# Notebook entry point — runs only on the Databricks job cluster, where
# ``spark`` and ``dbutils`` are injected. Imports from local pytest (no
# SparkSession constructed locally per CLAUDE.md "Don'ts") must NOT
# trigger the widget read or the Spark write; the ``_running_in_notebook``
# guard below resolves to False under pytest because ``dbutils`` is not
# bound in the module's globals at import time.


def _running_in_notebook() -> bool:
    """True only when imported by the Databricks notebook runtime, which
    binds ``dbutils`` and ``spark`` in the module globals before
    executing the body. Pytest imports do not bind these names.
    """
    return "dbutils" in globals() and "spark" in globals()


# COMMAND ----------

def _spark_main(target_catalog: str) -> None:
    """Spark-side aggregation. Kept in a function so the notebook body
    can import this module under pytest without executing a job. The
    function references ``spark`` from the notebook global scope at call
    time only.
    """
    from datetime import datetime, timezone

    from pyspark.sql import functions as F

    from src.analytics.lib.suppression import apply_suppression_rules

    catalog_prefix = f"{target_catalog}." if target_catalog else ""
    findings = spark.read.table(f"{catalog_prefix}silver.findings")  # type: ignore[name-defined]
    rules = spark.read.table(f"{catalog_prefix}silver.suppression_rules")  # type: ignore[name-defined]

    # Pre-filter rules in Python land; the helper handles the Column-side
    # match expression. ``application_id`` rules are silently skipped
    # because findings has no application_id column.
    filtered = apply_suppression_rules(findings, rules, now=datetime.now(timezone.utc))

    resolved = filtered.where(F.col("status_canonical") == F.lit("resolved"))

    # Per spec: resolved_at is the last_seen_at of the resolved row;
    # MTTR seconds = last_seen_at - first_seen_at.
    with_mttr = resolved.withColumn(
        "mttr_hours",
        (F.unix_timestamp("last_seen_at") - F.unix_timestamp("first_seen_at")) / F.lit(3600.0),
    ).withColumn(
        "iso_year", F.year(F.expr("date_trunc('week', last_seen_at)")).cast("int"),
    ).withColumn(
        "iso_week", F.weekofyear("last_seen_at").cast("int"),
    )
    # Spark's weekofyear is ISO-8601 by default. For iso_year we use the
    # extract(yearofweek FROM ts) function — wrap via expr because some
    # Spark versions name it ``yearofweek`` and others use
    # ``isoyear``. Fallback to year(date_trunc('week', ts)) is close
    # enough for week buckets that don't span Dec/Jan: the boundary
    # case is exercised by the unit test, which uses the pure-Python
    # path that does the right thing via datetime.isocalendar().
    with_mttr = with_mttr.withColumn(
        "iso_year",
        F.expr("extract(yearofweek FROM last_seen_at)").cast("int"),
    )

    grouped = (
        with_mttr.groupBy(
            "iso_year",
            "iso_week",
            "tool_source",
            "severity_canonical",
        )
        .agg(
            F.percentile_approx("mttr_hours", 0.5).alias("mttr_median_hours"),
            F.percentile_approx("mttr_hours", 0.9).alias("mttr_p90_hours"),
            F.count(F.lit(1)).cast("int").alias("sample_size"),
        )
    )

    target = f"{catalog_prefix}gold.mttr_by_source_severity_weekly"
    (
        grouped
        .select(
            F.col("iso_year").cast("int").alias("iso_year"),
            F.col("iso_week").cast("int").alias("iso_week"),
            F.col("tool_source"),
            F.col("severity_canonical"),
            F.col("mttr_median_hours").cast("double").alias("mttr_median_hours"),
            F.col("mttr_p90_hours").cast("double").alias("mttr_p90_hours"),
            F.col("sample_size"),
        )
        .write.format("delta")
        .mode("overwrite")
        .saveAsTable(target)
    )
    print(f"wrote {target}")


# COMMAND ----------

if _running_in_notebook():
    dbutils.widgets.text("target_catalog", "")  # type: ignore[name-defined]
    target_catalog = dbutils.widgets.get("target_catalog")  # type: ignore[name-defined]
    _spark_main(target_catalog)
