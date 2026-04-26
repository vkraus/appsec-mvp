# Databricks notebook source
# ruff: noqa: F821 — dbutils, spark are injected by the Databricks notebook runtime
"""Admin notebook: insert a single row into ``silver.suppression_rules``.

Operator-driven INSERTs (no UPDATE / DELETE — rules expire via
``expires_at``). The notebook exposes four widgets:

- ``scope`` (combo) — which finding column the rule matches against; one of
  ``tool_source``, ``category``, ``application_id``, ``repository_id``,
  ``file_path``, ``rule_id_native``.
- ``target_pattern`` (text) — literal value or trailing-wildcard
  (e.g. ``"acme/repo-*"``).
- ``expires_at_days`` (text) — number of days from now until the rule
  expires. Must parse to a positive integer.
- ``reason`` (text) — free-form audit note. Required.

The operator's email is read from the Databricks notebook context (no
widget) for the ``created_by`` column.

The pure-Python helpers (``validate_inputs``, ``build_rule_row``) are
exposed at module scope so pytest can exercise them without a
SparkSession (per CLAUDE.md "no local Spark in tests"). The Databricks
runtime invokes ``_run_notebook`` only when ``dbutils`` is present.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

# COMMAND ----------

CANONICAL_SCOPES: frozenset[str] = frozenset(
    {
        "tool_source",
        "category",
        "application_id",
        "repository_id",
        "file_path",
        "rule_id_native",
    }
)


def validate_inputs(
    scope: str,
    target_pattern: str,
    expires_at_days: str,
    reason: str,
) -> int:
    """Validate widget inputs; return ``expires_at_days`` parsed as int.

    Raises ``ValueError`` with a human-readable message on the first
    failure so the operator sees a clear error in the notebook output.
    """
    if scope not in CANONICAL_SCOPES:
        raise ValueError(f"scope {scope!r} is not in the canonical enum {sorted(CANONICAL_SCOPES)}")
    if not target_pattern or not target_pattern.strip():
        raise ValueError("target_pattern must be non-empty")
    if not reason or not reason.strip():
        raise ValueError("reason must be non-empty")

    try:
        days = int(expires_at_days)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"expires_at_days must be a positive integer, got {expires_at_days!r}"
        ) from exc
    if days <= 0:
        raise ValueError(f"expires_at_days must be a positive integer, got {days}")
    return days


def build_rule_row(
    scope: str,
    target_pattern: str,
    expires_at_days: int,
    reason: str,
    created_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a single suppression-rule row.

    ``rule_id`` is a fresh UUID4. ``created_at`` is ``now`` (UTC).
    ``expires_at`` is ``now + expires_at_days``.
    """
    if now is None:
        now = datetime.now(UTC)

    return {
        "rule_id": str(uuid4()),
        "scope": scope,
        "target_pattern": target_pattern.strip(),
        "expires_at": now + timedelta(days=expires_at_days),
        "reason": reason.strip(),
        "created_by": created_by,
        "created_at": now,
    }


# COMMAND ----------


def _operator_email() -> str:
    """Resolve the current operator's email from the notebook context.

    Falls back to ``"unknown"`` if the context is unavailable (the runtime
    sometimes returns ``None`` for service-principal-driven runs).
    """
    try:
        ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
        user = ctx.userName().get()
        return user or "unknown"
    except Exception:  # pragma: no cover — guard against runtime quirks
        return "unknown"


def _run_notebook() -> None:
    """Notebook body — runs only inside the Databricks notebook runtime."""
    dbutils.widgets.text("catalog", "")
    dbutils.widgets.dropdown(
        "scope",
        "tool_source",
        sorted(CANONICAL_SCOPES),
    )
    dbutils.widgets.text("target_pattern", "")
    dbutils.widgets.text("expires_at_days", "30")
    dbutils.widgets.text("reason", "")

    catalog = dbutils.widgets.get("catalog")
    if not catalog:
        raise ValueError("widget 'catalog' must be set to the UC catalog name")

    scope = dbutils.widgets.get("scope")
    target_pattern = dbutils.widgets.get("target_pattern")
    expires_at_days_raw = dbutils.widgets.get("expires_at_days")
    reason = dbutils.widgets.get("reason")

    days = validate_inputs(scope, target_pattern, expires_at_days_raw, reason)
    created_by = _operator_email()

    row = build_rule_row(
        scope=scope,
        target_pattern=target_pattern,
        expires_at_days=days,
        reason=reason,
        created_by=created_by,
    )

    df = spark.createDataFrame([row])
    (df.write.format("delta").mode("append").saveAsTable(f"{catalog}.silver.suppression_rules"))

    print(
        f"appended suppression rule {row['rule_id']} "
        f"(scope={row['scope']}, target_pattern={row['target_pattern']!r}, "
        f"expires_at={row['expires_at'].isoformat()}, "
        f"created_by={row['created_by']}) to "
        f"{catalog}.silver.suppression_rules"
    )


# COMMAND ----------

# The Databricks notebook runtime injects ``dbutils`` as a module-level
# global; pytest does not. Detect the runtime and run the notebook body
# only there. This keeps the module importable from local pytest so the
# pure-Python helpers can be exercised.
if "dbutils" in dir():
    _run_notebook()
