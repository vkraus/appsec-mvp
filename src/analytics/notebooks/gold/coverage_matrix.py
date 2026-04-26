# Databricks notebook source
# ruff: noqa: F821 — dbutils, spark are injected by the Databricks notebook runtime
"""Gold table: ``gold.coverage_matrix``.

Cross-source coverage of AppSec tooling per repository × tool category.
Answers: "did each tool category run recently against this repo?" — the
operational counterpart to risk-posture (which counts findings). Coverage
is about whether the tool RAN AT ALL, not whether it produced findings.

Inputs:
    silver.repositories      (repository_id)
    silver.findings          (repository_id, category, last_seen_at)

Output:
    gold.coverage_matrix     (repository_id, category, last_scan_at,
                              is_stale, staleness_threshold_days)

Logic:
    1. Cross-join every repository with every canonical category, so the
       output matrix is dense (one row per repo × category, even when no
       finding exists for that pair).
    2. LEFT JOIN with MAX(last_seen_at) per (repository_id, category) from
       silver.findings, providing the latest tool-run timestamp.
    3. is_stale = last_scan_at IS NULL OR last_scan_at < now -
       staleness_threshold_days. Null = never ran = stale.

Suppression note:
    Suppression rules hide findings from triage views; coverage is about
    whether a tool ran at all. apply_suppression_rules() is intentionally
    NOT called here.

Pure-Python helper ``compute_coverage_rows`` mirrors the Spark transform
and is unit-tested locally per CLAUDE.md (no local SparkSession).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

# ---------------------------------------------------------------------------
# Canonical AppSec tool categories the matrix tracks. Aligned with
# src/connectors/* config.yml `category` field and silver.findings.category.

CANONICAL_CATEGORIES: tuple[str, ...] = ("sast", "sca", "secrets", "scm")

DEFAULT_STALENESS_THRESHOLD_DAYS = 30


# ---------------------------------------------------------------------------
# Pure-Python helper — exercised by pytest without a SparkSession.


def compute_coverage_rows(
    repository_rows: Iterable[Mapping[str, Any]],
    finding_rows: Iterable[Mapping[str, Any]],
    now: datetime,
    threshold_days: int = DEFAULT_STALENESS_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """Compute the dense coverage matrix as a list of row dicts.

    Args:
        repository_rows: Iterable of mappings each carrying at least
            ``repository_id``. Extra columns are ignored.
        finding_rows: Iterable of mappings each carrying ``repository_id``,
            ``category``, and ``last_seen_at`` (datetime). Extra columns
            ignored. Findings whose category is outside
            :data:`CANONICAL_CATEGORIES` are silently skipped — coverage
            tracks the canonical tool categories only.
        now: Reference timestamp for staleness comparison. Caller-supplied
            so unit tests are deterministic; the notebook driver passes
            ``datetime.now(timezone.utc)``.
        threshold_days: A row is stale when ``last_scan_at`` is None OR
            ``last_scan_at < now - threshold_days``. Defaults to
            :data:`DEFAULT_STALENESS_THRESHOLD_DAYS` (30).

    Returns:
        Dense list of dicts: one row per (repository_id × canonical
        category). Each row has keys ``repository_id``, ``category``,
        ``last_scan_at`` (datetime or None), ``is_stale`` (bool),
        ``staleness_threshold_days`` (int).
    """
    cutoff = now - timedelta(days=threshold_days)

    # Reduce findings to MAX(last_seen_at) per (repo, category). Skip
    # categories outside the canonical set so off-spec findings cannot
    # leak into the matrix's dense shape.
    latest: dict[tuple[str, str], datetime] = {}
    for f in finding_rows:
        cat = f["category"]
        if cat not in CANONICAL_CATEGORIES:
            continue
        repo = f["repository_id"]
        if repo is None:
            continue
        ts = f["last_seen_at"]
        key = (repo, cat)
        prev = latest.get(key)
        if prev is None or ts > prev:
            latest[key] = ts

    out: list[dict[str, Any]] = []
    for r in repository_rows:
        repo = r["repository_id"]
        for cat in CANONICAL_CATEGORIES:
            last_scan_at = latest.get((repo, cat))
            is_stale = last_scan_at is None or last_scan_at < cutoff
            out.append({
                "repository_id": repo,
                "category": cat,
                "last_scan_at": last_scan_at,
                "is_stale": is_stale,
                "staleness_threshold_days": threshold_days,
            })
    return out


# ---------------------------------------------------------------------------
# Notebook driver — Spark application path. Untested locally per CLAUDE.md.

# COMMAND ----------

dbutils.widgets.text("target_catalog", "")
dbutils.widgets.text("staleness_threshold_days", str(DEFAULT_STALENESS_THRESHOLD_DAYS))

target_catalog = dbutils.widgets.get("target_catalog")
threshold_days = int(dbutils.widgets.get("staleness_threshold_days"))

# COMMAND ----------

from pyspark.sql import functions as F

silver_prefix = f"{target_catalog}.silver" if target_catalog else "silver"
gold_prefix = f"{target_catalog}.gold" if target_catalog else "gold"

repos = spark.read.table(f"{silver_prefix}.repositories").select("repository_id")
findings = (
    spark.read.table(f"{silver_prefix}.findings")
    .select("repository_id", "category", "last_seen_at")
    .where(F.col("repository_id").isNotNull())
    .where(F.col("category").isin(*CANONICAL_CATEGORIES))
)

# COMMAND ----------

# Cross-join repos × canonical categories so the matrix is dense.
categories_df = spark.createDataFrame(
    [(c,) for c in CANONICAL_CATEGORIES], ["category"]
)
matrix = repos.crossJoin(categories_df)

# Latest scan per (repo, category) from findings.
latest = (
    findings.groupBy("repository_id", "category")
    .agg(F.max("last_seen_at").alias("last_scan_at"))
)

# LEFT JOIN: every cell in the matrix gets a last_scan_at (or null).
joined = matrix.join(latest, on=["repository_id", "category"], how="left")

# Staleness: null = never ran = stale; otherwise compare to cutoff.
cutoff_expr = F.current_timestamp() - F.expr(f"INTERVAL {threshold_days} DAYS")
result = joined.withColumn(
    "is_stale",
    F.col("last_scan_at").isNull() | (F.col("last_scan_at") < cutoff_expr),
).withColumn(
    "staleness_threshold_days", F.lit(threshold_days).cast("int")
).select(
    "repository_id",
    "category",
    "last_scan_at",
    "is_stale",
    "staleness_threshold_days",
)

# COMMAND ----------

(
    result.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{gold_prefix}.coverage_matrix")
)

print(f"wrote {gold_prefix}.coverage_matrix; threshold_days={threshold_days}")
