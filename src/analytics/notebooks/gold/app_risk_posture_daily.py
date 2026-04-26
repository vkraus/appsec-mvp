# Databricks notebook source
# ruff: noqa: F821 — dbutils, spark are injected by the Databricks notebook runtime
"""Gold-layer notebook: ``gold.app_risk_posture_daily``.

Daily snapshot of open + closed finding counts per ``application_id`` ×
``severity_canonical``. Findings whose ``repository_id`` does not map to
an application are emitted under the sentinel ``application_id =
"__UNMAPPED__"`` so the table is complete (no findings dropped).

Suppression is applied *post-join* with ``silver.app_repo_mapping`` so
that suppression rules with ``scope = application_id`` resolve correctly
(the ``application_id`` column is only present after the join).

The aggregation logic lives in :func:`compute_posture_rows`, a pure-Python
helper taking lists of dicts and returning a list of dicts. The notebook
calls the helper via a ``spark.createDataFrame`` round-trip; pytest
exercises the same helper without a SparkSession (per CLAUDE.md "no local
Spark in tests").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from pyspark.sql import SparkSession

from src.analytics.lib.suppression import is_row_suppressed

# COMMAND ----------

UNMAPPED_SENTINEL = "__UNMAPPED__"
OPEN_STATUS = "open"
CLOSED_STATUSES = frozenset({"resolved", "wontfix", "false_positive"})


def compute_posture_rows(
    findings_rows: Iterable[Mapping[str, Any]],
    app_repo_rows: Iterable[Mapping[str, Any]],
    suppression_rules: Iterable[Mapping[str, Any]],
    snapshot_date: date,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate finding counts per (application_id, severity_canonical).

    Pure Python: no Spark dependency. Mirrors the Spark SQL the notebook
    runs on the cluster so that pytest can exercise the same logic.

    Steps:

    1. Build a ``repository_id -> application_id`` index from
       ``app_repo_rows``. If a repository maps to multiple applications,
       the finding is duplicated (one row per app) — matches a Spark
       INNER-then-LEFT-OUTER join semantics.
    2. For each finding, attach ``application_id`` (sentinel
       ``__UNMAPPED__`` if the repo does not appear in the mapping).
    3. Apply suppression rules against the post-join row (so rules
       scoped to ``application_id`` resolve).
    4. Group by ``(application_id, severity_canonical)`` and tally
       ``open_count`` / ``closed_count``.
    5. Stamp each output row with ``snapshot_date``.
    """
    if now is None:
        now = datetime.now(UTC)

    rules = list(suppression_rules)

    repo_to_apps: dict[str, list[str]] = {}
    for m in app_repo_rows:
        repo = m.get("repository_id")
        app = m.get("application_id")
        if repo is None or app is None:
            continue
        repo_to_apps.setdefault(repo, []).append(app)

    counts: dict[tuple[str, str | None], dict[str, int]] = {}

    for f in findings_rows:
        repo = f.get("repository_id")
        severity = f.get("severity_canonical")
        status = f.get("status_canonical")

        apps = repo_to_apps.get(repo, [UNMAPPED_SENTINEL]) if repo else [UNMAPPED_SENTINEL]

        for app in apps:
            joined_row = dict(f)
            joined_row["application_id"] = app
            if is_row_suppressed(joined_row, rules, now=now):
                continue

            key = (app, severity)
            bucket = counts.setdefault(key, {"open_count": 0, "closed_count": 0})
            if status == OPEN_STATUS:
                bucket["open_count"] += 1
            elif status in CLOSED_STATUSES:
                bucket["closed_count"] += 1

    return [
        {
            "snapshot_date": snapshot_date,
            "application_id": app,
            "severity_canonical": severity,
            "open_count": bucket["open_count"],
            "closed_count": bucket["closed_count"],
        }
        for (app, severity), bucket in sorted(
            counts.items(),
            key=lambda kv: (kv[0][0] or "", kv[0][1] or ""),
        )
    ]


# COMMAND ----------


def _run_notebook() -> None:
    """Notebook entry point — executed only on the Databricks cluster.

    Guarded behind a function so that ``import`` of this module from
    pytest (which does not have ``dbutils`` / ``spark`` injected) does
    not trigger any I/O. The Databricks notebook runtime invokes this
    via the explicit call below; the call only fires when ``dbutils``
    resolves at module scope, i.e. inside the notebook runtime.
    """
    dbutils.widgets.text("catalog", "")
    catalog = dbutils.widgets.get("catalog")
    if not catalog:
        raise ValueError("widget 'catalog' must be set to the UC catalog name")

    spark = SparkSession.builder.getOrCreate()

    findings_df = spark.read.table(f"{catalog}.silver.findings")
    app_repo_df = spark.read.table(f"{catalog}.silver.app_repo_mapping")
    rules_df = spark.read.table(f"{catalog}.silver.suppression_rules")

    findings_rows = [r.asDict() for r in findings_df.collect()]
    app_repo_rows = [r.asDict() for r in app_repo_df.collect()]
    suppression_rules = [r.asDict() for r in rules_df.collect()]

    posture_rows = compute_posture_rows(
        findings_rows=findings_rows,
        app_repo_rows=app_repo_rows,
        suppression_rules=suppression_rules,
        snapshot_date=date.today(),
    )

    if posture_rows:
        out_df = spark.createDataFrame(posture_rows)
    else:
        # Empty input — emit an empty DataFrame with the canonical
        # schema so downstream readers still see a well-typed table.
        from pyspark.sql.types import (
            DateType,
            IntegerType,
            StringType,
            StructField,
            StructType,
        )

        schema = StructType(
            [
                StructField("snapshot_date", DateType(), nullable=False),
                StructField("application_id", StringType(), nullable=True),
                StructField("severity_canonical", StringType(), nullable=True),
                StructField("open_count", IntegerType(), nullable=False),
                StructField("closed_count", IntegerType(), nullable=False),
            ]
        )
        out_df = spark.createDataFrame([], schema)

    (
        out_df.write.format("delta")
        .mode("overwrite")
        .saveAsTable(f"{catalog}.gold.app_risk_posture_daily")
    )

    print(f"wrote {out_df.count()} rows to {catalog}.gold.app_risk_posture_daily")


# COMMAND ----------

# The Databricks notebook runtime injects ``dbutils`` as a module-level
# global; pytest does not. Detect the runtime and run the notebook body
# only there. This keeps the module importable from local pytest so the
# pure-Python helper can be exercised.
if "dbutils" in dir():
    _run_notebook()
