# Databricks notebook source
# ruff: noqa: F821 — dbutils, spark are injected by the Databricks notebook runtime
"""Gold table: ``gold.dedup_link_overlap``.

Cross-tool overlap analytics over ``silver.findings``. The framework
performs deduplication INSIDE each connector's ``transform`` skill via
``src.platform.silver.dedup_findings``; there is no separate
``dedup_links`` table. To answer "how often do two tools find the same
issue?" analytically, this notebook self-joins ``silver.findings`` on
the per-category dedup tuple defined in ``src/platform/silver.py`` and
counts the distinct (tool_source_a, tool_source_b) pairs.

Inputs:
    silver.findings           (category, tool_source, repository_id,
                               file_path, start_line, cwe_id, cve_id,
                               rule_id_native, url)
    silver.suppression_rules  (rule_id, scope, target_pattern, expires_at, …)

Output:
    gold.dedup_link_overlap   (tool_source_a, tool_source_b, category,
                               linked_pair_count)

Per-category dedup tuple (matches ``src.platform.silver.dedup_findings``):

    sast    — (repository_id, file_path, start_line, cwe_id) — only when
              cwe_id IS NOT NULL; without a CWE there is no canonical
              cross-tool linkage.
    sca     — (repository_id, cve_id) — only when cve_id IS NOT NULL.
    secrets — (repository_id, file_path, rule_id_native).
    dast    — (url, rule_id_native).

The ``scm`` and ``waf`` categories have no meaningful cross-tool dedup
in the MVP (single-vendor categories) so they are intentionally skipped.

Pair-ordering convention:
    The self-join condition is ``tool_source_a < tool_source_b``
    (alphabetical). This counts each unordered pair exactly once and
    implicitly excludes intra-tool joins (semgrep-with-semgrep), which
    are not cross-tool overlap.

Suppression:
    Applied BEFORE the self-join so muted findings cannot inflate
    overlap counts (e.g., a sonarqube-wide suppression must drop
    semgrep×sonarqube pairs to zero, not leave them at the pre-mute
    count).

Pure-Python helper ``compute_overlap_rows`` mirrors the Spark transform
and is unit-tested locally per CLAUDE.md (no local SparkSession).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.analytics.lib.suppression import is_row_suppressed

# ---------------------------------------------------------------------------
# Per-category dedup-tuple specification. The keys are the canonical
# AppSec categories that have meaningful cross-tool overlap; ``scm`` and
# ``waf`` are deliberately omitted (single-vendor in the MVP).
#
# Each entry is a tuple of column names. The category-specific filter
# (e.g., "cwe_id IS NOT NULL" for sast) is applied in addition by the
# helper to drop rows whose dedup tuple is incomplete.

CATEGORY_DEDUP_KEYS: dict[str, tuple[str, ...]] = {
    "sast": ("repository_id", "file_path", "start_line", "cwe_id"),
    "sca": ("repository_id", "cve_id"),
    "secrets": ("repository_id", "file_path", "rule_id_native"),
    "dast": ("url", "rule_id_native"),
}

# Columns that, if NULL, drop the finding from overlap consideration for
# the given category — the dedup tuple is incomplete and no canonical
# cross-tool linkage is possible.
CATEGORY_REQUIRED_NONNULL: dict[str, tuple[str, ...]] = {
    "sast": ("cwe_id",),
    "sca": ("cve_id",),
    "secrets": (),
    "dast": (),
}


# ---------------------------------------------------------------------------
# Pure-Python helper — exercised by pytest without a SparkSession.


def compute_overlap_rows(
    findings_rows: Iterable[Mapping[str, Any]],
    suppression_rules: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Compute cross-tool overlap pair counts per category.

    Args:
        findings_rows: Iterable of mappings each carrying at least
            ``category``, ``tool_source``, and the dedup-tuple columns
            for that category. Rows whose category is outside
            :data:`CATEGORY_DEDUP_KEYS` are silently ignored.
        suppression_rules: Iterable of suppression rules applied
            row-by-row before the self-join, so muted findings cannot
            inflate overlap counts.
        now: Reference timestamp for suppression-rule expiration.
            Defaults to ``datetime.now(timezone.utc)``.

    Returns:
        List of dicts with keys ``tool_source_a``, ``tool_source_b``,
        ``category``, ``linked_pair_count``. One row per
        ``(tool_a, tool_b, category)`` triple where ``tool_a < tool_b``
        alphabetically and at least one linked pair exists. Rows are
        sorted by ``(category, tool_source_a, tool_source_b)`` for
        deterministic output.

    The pair count is the number of distinct dedup-tuple values where
    the tool pair co-occurred. Multiple findings from the same tool on
    the same dedup tuple collapse to one (de-duplicated via a set per
    tuple-key).
    """
    if now is None:
        now = datetime.now(UTC)
    rules = list(suppression_rules)

    # Step 1: filter by suppression. Done up-front so subsequent grouping
    # can't re-introduce suppressed findings.
    surviving = [f for f in findings_rows if not is_row_suppressed(f, rules, now=now)]

    # Step 2: per category, collapse findings to dedup-tuple-keyed sets
    # of distinct tool_sources. Then enumerate every unordered pair
    # (a < b) within each set and tally.
    out: list[dict[str, Any]] = []

    for category, key_cols in CATEGORY_DEDUP_KEYS.items():
        required_nonnull = CATEGORY_REQUIRED_NONNULL[category]

        # tuple_key -> set of tool_sources that hit it.
        tuple_to_tools: dict[tuple[Any, ...], set[str]] = {}
        for f in surviving:
            if f.get("category") != category:
                continue
            # Drop rows missing any required-non-null column.
            if any(f.get(c) is None for c in required_nonnull):
                continue
            # Drop rows missing any dedup-key column outright (a None
            # in the tuple is not a meaningful link).
            key = tuple(f.get(c) for c in key_cols)
            if any(v is None for v in key):
                continue
            tool = f.get("tool_source")
            if tool is None:
                continue
            tuple_to_tools.setdefault(key, set()).add(tool)

        # (a, b) -> count of dedup tuples where both tools appeared.
        pair_counts: dict[tuple[str, str], int] = {}
        for tools in tuple_to_tools.values():
            sorted_tools = sorted(tools)
            for i in range(len(sorted_tools)):
                for j in range(i + 1, len(sorted_tools)):
                    a, b = sorted_tools[i], sorted_tools[j]
                    # a < b is guaranteed by sorted_tools and i < j;
                    # this also implicitly excludes intra-tool pairs
                    # because a set deduplicates same-named tools.
                    pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1

        for (a, b), n in pair_counts.items():
            out.append(
                {
                    "tool_source_a": a,
                    "tool_source_b": b,
                    "category": category,
                    "linked_pair_count": n,
                }
            )

    out.sort(key=lambda r: (r["category"], r["tool_source_a"], r["tool_source_b"]))
    return out


# ---------------------------------------------------------------------------
# Notebook driver — Spark application path. Untested locally per CLAUDE.md.

# COMMAND ----------


def _run_notebook() -> None:
    """Notebook entry point — executed only on the Databricks cluster.

    Guarded behind a function so that ``import`` of this module from
    pytest (which does not have ``dbutils`` / ``spark`` injected) does
    not trigger any I/O. The Databricks notebook runtime invokes this
    via the explicit call below; the call only fires when ``dbutils``
    resolves at module scope, i.e. inside the notebook runtime.
    """
    from pyspark.sql import SparkSession

    dbutils.widgets.text("target_catalog", "")
    target_catalog = dbutils.widgets.get("target_catalog")

    spark = SparkSession.builder.getOrCreate()

    silver_prefix = f"{target_catalog}.silver" if target_catalog else "silver"
    gold_prefix = f"{target_catalog}.gold" if target_catalog else "gold"

    findings_df = spark.read.table(f"{silver_prefix}.findings")
    rules_df = spark.read.table(f"{silver_prefix}.suppression_rules")

    findings_rows = [r.asDict() for r in findings_df.collect()]
    suppression_rules = [r.asDict() for r in rules_df.collect()]

    overlap_rows = compute_overlap_rows(
        findings_rows=findings_rows,
        suppression_rules=suppression_rules,
        now=datetime.now(UTC),
    )

    if overlap_rows:
        out_df = spark.createDataFrame(overlap_rows)
    else:
        # Empty input — emit an empty DataFrame with the canonical
        # schema so downstream readers still see a well-typed table.
        from pyspark.sql.types import (
            IntegerType,
            StringType,
            StructField,
            StructType,
        )

        schema = StructType(
            [
                StructField("tool_source_a", StringType(), nullable=False),
                StructField("tool_source_b", StringType(), nullable=False),
                StructField("category", StringType(), nullable=False),
                StructField("linked_pair_count", IntegerType(), nullable=False),
            ]
        )
        out_df = spark.createDataFrame([], schema)

    (
        out_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{gold_prefix}.dedup_link_overlap")
    )

    print(f"wrote {out_df.count()} rows to {gold_prefix}.dedup_link_overlap")


# COMMAND ----------

# The Databricks notebook runtime injects ``dbutils`` as a module-level
# global; pytest does not. Detect the runtime and run the notebook body
# only there. This keeps the module importable from local pytest so the
# pure-Python helper can be exercised.
if "dbutils" in dir():
    _run_notebook()
