"""Bronze-to-silver transform for ServiceNow.

Targets, plural per `references/cmdb.md` and the page §3:

- ``silver.applications`` (from ``cmdb_ci_business_app``)
- ``silver.teams`` (from ``sys_user_group`` or equivalent ownership table)
- ``silver.app_repo_mapping`` (application -> repository linkage; emitted
  only when the deployment populates the ``u_repository_id`` custom column
  on the application record)

CMDB / entity-only shape: NO ``severity_canonical`` / ``status_canonical``
columns are projected; finding-shape semantics do not apply. The transform
does NOT emit ``dedup_links`` rows — entity dedup is handled by the
natural key (``sys_id``) at Bronze-to-Silver upsert time.

Quirks honoured here (per the connector page):
- Instance-local timestamps (``YYYY-MM-DD HH:MM:SS``) are converted to
  UTC datetimes per REQ-TRF-TS. The instance timezone is supplied by the
  caller (read from ``glide.sys.timezone`` or pinned in ``config.yml``).
- Empty-string values (``""``) are coerced to ``None`` for all nullable
  columns so the Silver schema stays honest.
- Custom ``u_*`` columns flow through additively at Bronze under
  schema-on-read; this module projects only the canonical fields.

Per thesis section 4 Future Work, the Spark-side declarative transform is
not yet wired through a generic ``mapping.yml`` applicator. ``transform``
returns an empty DataFrame; the per-record pure-Python helpers
(``normalise_application``, ``normalise_team``, ``normalise_app_repo_link``)
encode the mapping and are exercised by ``tests/test_transform.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pyspark.sql import DataFrame
from pyspark.sql.types import (
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# ServiceNow native datetime format (record-level columns like
# `sys_updated_on`, `sys_created_on`).
_SN_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# Silver-side schema for silver.applications. Mirrors the canonical entity
# shape; reused from `src.platform.schemas` would couple us to that module
# while the broader CMDB triple is still being reconciled — define
# locally and align column-by-column with `silver_applications` there.
silver_applications = StructType([
    StructField("application_id", StringType(), nullable=False),
    StructField("name", StringType(), nullable=False),
    StructField("short_description", StringType(), nullable=True),
    StructField("business_criticality", StringType(), nullable=True),
    StructField("operational_status", StringType(), nullable=True),
    StructField("owned_by", StringType(), nullable=True),
    StructField("used_by", StringType(), nullable=True),
    StructField("valid_from", TimestampType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=False),
])


# Silver-side schema for silver.teams.
silver_teams = StructType([
    StructField("team_id", StringType(), nullable=False),
    StructField("name", StringType(), nullable=False),
    StructField("description", StringType(), nullable=True),
    StructField("email", StringType(), nullable=True),
    StructField("manager", StringType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=False),
])


# Silver-side schema for silver.app_repo_mapping.
silver_app_repo_mapping = StructType([
    StructField("application_id", StringType(), nullable=False),
    StructField("repository_id", StringType(), nullable=False),
    StructField("linked_at", TimestampType(), nullable=False),
])


def _coerce_empty(value: Any) -> Any:
    """Return ``None`` for the empty-string sentinel, else ``value``."""
    return None if value == "" else value


def _resolve_timezone(instance_timezone: str | timezone | ZoneInfo) -> timezone | ZoneInfo:
    """Resolve a timezone identifier to a tzinfo instance.

    Accepts an IANA name (``"Europe/Berlin"``), an already-instantiated
    ``timezone`` (e.g. ``UTC``), or a ``ZoneInfo``. Raises ``ValueError``
    on unknown names so misconfiguration surfaces as a clear error.
    """
    if isinstance(instance_timezone, (timezone, ZoneInfo)):
        return instance_timezone
    if instance_timezone == "UTC":
        return UTC
    return ZoneInfo(instance_timezone)


def normalise_servicenow_datetime(
    value: str | None,
    instance_timezone: str | timezone | ZoneInfo,
) -> datetime | None:
    """Parse a ServiceNow datetime string and convert it to UTC.

    Per the page § Quirks: ServiceNow returns datetime fields as strings
    in ``YYYY-MM-DD HH:MM:SS`` format, encoded in the **instance-local
    timezone**. Failing to convert produces a silent UTC-skew bug that
    the data-quality expectations would not catch — this helper centralises
    the conversion (REQ-TRF-TS).

    Args:
        value: instance-local datetime string, ``None``, or empty string.
        instance_timezone: IANA timezone name or tzinfo instance for the
            ServiceNow instance (typically read from ``glide.sys.timezone``
            and pinned in ``config.yml``).

    Returns:
        Timezone-aware UTC datetime, or ``None`` if the input is empty.

    Raises:
        ValueError: if ``value`` is non-empty but does not match the
            documented native format.
    """
    coerced = _coerce_empty(value)
    if coerced is None:
        return None
    if not isinstance(coerced, str):
        raise ValueError(
            f"servicenow datetime must be a string, got {type(coerced).__name__}"
        )
    tz = _resolve_timezone(instance_timezone)
    parsed = datetime.strptime(coerced, _SN_DATETIME_FORMAT)
    # Attach the instance-local timezone, then convert to UTC. Naive
    # datetimes are NEVER returned to keep downstream HWM contracts honest.
    localised = parsed.replace(tzinfo=tz)
    return localised.astimezone(UTC)


def normalise_application(
    raw: dict[str, Any],
    instance_timezone: str | timezone | ZoneInfo,
) -> dict[str, Any]:
    """Project one ``cmdb_ci_business_app`` record onto silver.applications.

    Empty-string values are coerced to ``None``; instance-local datetimes
    are converted to UTC. Custom ``u_*`` columns are NOT projected here —
    they flow through additively at Bronze.
    """
    return {
        "application_id":       _coerce_empty(raw.get("sys_id")),
        "name":                 _coerce_empty(raw.get("name")),
        "short_description":    _coerce_empty(raw.get("short_description")),
        "business_criticality": _coerce_empty(raw.get("business_criticality")),
        "operational_status":   _coerce_empty(raw.get("operational_status")),
        "owned_by":             _coerce_empty(raw.get("owned_by")),
        "used_by":              _coerce_empty(raw.get("used_by")),
        "valid_from":           normalise_servicenow_datetime(
                                    raw.get("sys_created_on"),
                                    instance_timezone,
                                ),
        "updated_at":           normalise_servicenow_datetime(
                                    raw.get("sys_updated_on"),
                                    instance_timezone,
                                ),
    }


def normalise_team(
    raw: dict[str, Any],
    instance_timezone: str | timezone | ZoneInfo,
) -> dict[str, Any]:
    """Project one ``sys_user_group`` record onto silver.teams.

    The ownership table is a per-deployment knob; the projected fields
    are the canonical subset every deployment is expected to carry.
    """
    return {
        "team_id":     _coerce_empty(raw.get("sys_id")),
        "name":        _coerce_empty(raw.get("name")),
        "description": _coerce_empty(raw.get("description")),
        "email":       _coerce_empty(raw.get("email")),
        "manager":     _coerce_empty(raw.get("manager")),
        "updated_at":  normalise_servicenow_datetime(
                           raw.get("sys_updated_on"),
                           instance_timezone,
                       ),
    }


def normalise_app_repo_link(
    raw: dict[str, Any],
    instance_timezone: str | timezone | ZoneInfo,
) -> dict[str, Any] | None:
    """Project an application-to-repository link onto silver.app_repo_mapping.

    Returns ``None`` (NOT a dict) when the application record carries no
    ``u_repository_id`` value — these rows do NOT land in
    ``silver.app_repo_mapping``; they remain in ``silver.applications``
    only. The custom column is the deployment-specific linkage primitive
    per `mapping.yml`.
    """
    repo_id = _coerce_empty(raw.get("u_repository_id"))
    if repo_id is None:
        return None
    application_id = _coerce_empty(raw.get("sys_id"))
    if application_id is None:
        # Defensive: a record without a sys_id shouldn't occur on real
        # ServiceNow data, but guard against malformed Bronze rows.
        return None
    return {
        "application_id": application_id,
        "repository_id":  repo_id,
        "linked_at":      normalise_servicenow_datetime(
                              raw.get("sys_updated_on"),
                              instance_timezone,
                          ),
    }


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper.

    Per thesis section 4 Future Work, the full declarative mapping onto
    the Silver entity tables (with the instance-timezone-aware datetime
    conversion driven from ``mapping.yml`` plus ``config.yml``'s
    ``instance_timezone`` knob) is not yet wired through a generic
    applicator. This module honors the section 2.4.1 contract
    ``transform(bronze_df) -> silver_df`` by returning an empty
    ``silver_applications`` DataFrame so downstream orchestration can
    chain the call without a runtime error.

    Real implementations: call ``normalise_application`` /
    ``normalise_team`` / ``normalise_app_repo_link`` per Bronze row
    through Spark UDFs or, once a generic YAML applicator exists, drive
    the mapping declaratively from ``mapping.yml``. The three target
    tables are written independently — there is no single fan-out
    DataFrame.
    """
    return bronze_df.sparkSession.createDataFrame([], schema=silver_applications)
