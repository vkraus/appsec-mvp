"""Gold-layer suppression helper.

Operator-authored INSERT-only rows in ``silver.suppression_rules`` mute
findings at Gold-layer aggregation time. ``silver.findings`` retains the
canonical immutable record; this helper filters at read-time inside each
Gold notebook before the aggregation step. Decoupling suppression from
the connector skill chain means transforms never need to know about it.

Rule semantics:
    rule.scope          = which column the rule matches against. Must be
                          a column on the input DataFrame at the call site
                          (rules with scope not present are silently
                          skipped). Canonical scopes: 'tool_source',
                          'category', 'repository_id', 'file_path',
                          'rule_id_native', and (post-join with
                          app_repo_mapping) 'application_id'.
    rule.target_pattern = literal value (exact match) OR trailing-wildcard
                          ('repo/*' matches 'repo' itself or anything
                          beginning with 'repo/').
    rule.expires_at     = rule auto-expires at this timestamp; rules with
                          expires_at <= now are inactive.

The pure-Python rule-matching predicate is exposed for unit testing without
a local SparkSession (CLAUDE.md "Don'ts" prohibits local Spark in tests).
The Spark application is a thin Column-based wrapper.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def is_rule_active(rule: Mapping[str, Any], now: datetime) -> bool:
    """Return True if ``rule.expires_at`` is strictly after ``now``."""
    return rule["expires_at"] > now


def rule_matches_value(rule: Mapping[str, Any], value: Any) -> bool:
    """Return True if ``value`` matches ``rule.target_pattern``.

    Supports literal equality and the trailing-wildcard form ``'prefix/*'``,
    which matches ``'prefix'`` itself or any string beginning with
    ``'prefix/'``.

    Returns False when ``value`` is None.
    """
    if value is None:
        return False
    pattern = rule["target_pattern"]
    if pattern.endswith("/*"):
        prefix = pattern[: -len("/*")]
        return value == prefix or (isinstance(value, str) and value.startswith(prefix + "/"))
    return value == pattern


def is_row_suppressed(
    row: Mapping[str, Any],
    rules: list[Mapping[str, Any]],
    now: datetime | None = None,
) -> bool:
    """Return True if ``row`` is suppressed by ANY active applicable rule.

    A rule is *applicable* iff its ``scope`` is a key in ``row``. Rules
    whose scope is not present in ``row`` are silently skipped (they do
    not apply at this call site).
    """
    if now is None:
        now = datetime.now(UTC)
    for rule in rules:
        if not is_rule_active(rule, now):
            continue
        scope = rule["scope"]
        if scope not in row:
            continue
        if rule_matches_value(rule, row[scope]):
            return True
    return False


def apply_suppression_rules(df, rules_df, now: datetime | None = None):
    """Spark-side application: return ``df`` with suppressed rows removed.

    Reads the rules onto the driver (rules table is small, operator-authored,
    low row count — avoids a cross-join with the large findings df) and
    builds one boolean Column expression that is True when ANY active
    applicable rule matches the row, then filters by negation.

    Pure-Python tests cover the rule-matching semantics via
    :func:`is_row_suppressed`. This Spark wrapper is exercised on the
    Databricks job cluster, not in local pytest (per CLAUDE.md).
    """
    from pyspark.sql import functions as F

    if now is None:
        now = datetime.now(UTC)

    rules = [r.asDict() for r in rules_df.collect() if r["expires_at"] > now]
    if not rules:
        return df

    df_columns = set(df.columns)
    applicable = [r for r in rules if r["scope"] in df_columns]
    if not applicable:
        return df

    suppressed = F.lit(False)
    for r in applicable:
        col = F.col(r["scope"])
        pattern = r["target_pattern"]
        if pattern.endswith("/*"):
            prefix = pattern[: -len("/*")]
            match = (col == F.lit(prefix)) | col.startswith(F.lit(prefix + "/"))
        else:
            match = col == F.lit(pattern)
        suppressed = suppressed | match

    return df.filter(~suppressed)
