"""ServiceNow Table API ingestion.

CMDB / entity-only source. Reads `cmdb_ci_business_app` and any related CI
tables configured under `tables` in `config.yml`, lands each as its own
Bronze table, and advances a per-table high-water mark on `sys_updated_on`.
The Bronze-to-Silver join into `silver.applications`, `silver.teams`, and
`silver.app_repo_mapping` happens at transform time — NOT here.

Ingestion tooling preference (thesis §2.4.1): Lakeflow Connect → Databricks
SDK → dlt. ServiceNow has no first-party Lakeflow connector at MVP time, so
this connector targets the Databricks SDK / dlt REST source path. Live HTTP
runs only inside `run_ingest_pipeline`; the pure-Python helpers below
(`build_table_url`, `build_sysparm_query`, `is_html_hibernation_response`,
`coerce_empty_strings_to_none`, `select_table_hwm`) drive unit-testable
logic exercised by `tests/test_ingest.py`.

Quirks honoured here (per the connector page):
- `sysparm_display_value=false` and `sysparm_exclude_reference_link=true`
  are appended to every Table API call.
- A non-JSON `Content-Type` (the Personal Developer Instance hibernation
  HTML wake-up page) is treated as a HARD ERROR with a clear remediation
  message — never landed in Bronze.
- Empty-string field values (`""`) are kept on the wire and coerced to
  `None` at the helper level so downstream Bronze writes can either
  preserve them under schema-on-read or drop them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from src.platform.contract import BatchDescriptor, ConnectorState

# Recognises the ServiceNow record-level datetime format
# (`YYYY-MM-DD HH:MM:SS`, instance-local timezone).
_SN_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

# JSON content-type marker. PDI hibernation responses arrive as
# `text/html; charset=utf-8` even though the HTTP status is 200.
_JSON_CONTENT_TYPE_PREFIX = "application/json"

# PDI wake-up page sentinel — appears in the HTML body when the
# instance is hibernating. Used as a secondary check when the
# Content-Type header is misreported.
_PDI_WAKE_SENTINEL = "developer.servicenow.com"


def build_table_url(base_url: str, table_name: str) -> str:
    """Compose a Table API URL for a given CI table.

    Args:
        base_url: ``https://<instance>.service-now.com`` (no trailing slash
            required; the helper strips it defensively).
        table_name: e.g. ``cmdb_ci_business_app``.

    Returns:
        ``https://<instance>.service-now.com/api/now/table/<table_name>``.
    """
    return f"{base_url.rstrip('/')}/api/now/table/{table_name}"


def build_sysparm_query(
    hwm_value: str | None,
    *,
    order_by: str = "sys_updated_on",
) -> str:
    """Return the ServiceNow encoded-query string for the HWM filter.

    Per the connector page § "Incremental hook":

    - When ``hwm_value`` is ``None`` (first run), no filter is applied;
      the query is ``ORDERBYsys_updated_on`` to make pagination resumable.
    - When ``hwm_value`` is set, the filter is
      ``sys_updated_on>=YYYY-MM-DD HH:MM:SS^ORDERBYsys_updated_on``. The
      ``>=`` boundary re-reads records updated within the same second as
      the previous watermark; downstream upsert on ``sys_id`` is idempotent.

    Args:
        hwm_value: instance-local datetime string in the ServiceNow native
            format, or ``None`` for first-run.
        order_by: column to order results by; defaults to ``sys_updated_on``.

    Returns:
        ServiceNow encoded-query string suitable for the ``sysparm_query``
        URL parameter.
    """
    if hwm_value is None:
        return f"ORDERBY{order_by}"
    if not _SN_DATETIME_RE.match(hwm_value):
        raise ValueError(f"servicenow hwm_value must be 'YYYY-MM-DD HH:MM:SS', got {hwm_value!r}")
    return f"sys_updated_on>={hwm_value}^ORDERBY{order_by}"


def is_html_hibernation_response(content_type: str | None, body: str | None) -> bool:
    """Return True iff the response is the PDI hibernation wake-up page.

    Per the connector page § Quirks: hibernating Personal Developer
    Instances return an HTTP 200 with an HTML wake-up page instead of
    JSON. The connector treats this as a hard error rather than landing
    the HTML in Bronze.

    Args:
        content_type: the ``Content-Type`` response header (case-insensitive
            match on the JSON prefix).
        body: the response body string. When the header is missing or
            misreported, the body is scanned for the wake-up sentinel.
    """
    if content_type and content_type.lower().startswith(_JSON_CONTENT_TYPE_PREFIX):
        return False
    if body and _PDI_WAKE_SENTINEL in body and "<html" in body.lower():
        return True
    # Conservative: if the content type is set but is not JSON, treat as
    # hibernation. This matches the page's prescription that any non-JSON
    # response on the Table API is a hard error.
    return bool(content_type and not content_type.lower().startswith(_JSON_CONTENT_TYPE_PREFIX))


def raise_if_hibernating(content_type: str | None, body: str | None) -> None:
    """Raise a clear runtime error when the instance is hibernating.

    The remediation message points the operator at the developer
    portal — the only path to wake a hibernating PDI.
    """
    if is_html_hibernation_response(content_type, body):
        raise RuntimeError(
            "ServiceNow Table API returned a non-JSON response. The "
            "Personal Developer Instance is likely hibernating — wake "
            "it at https://developer.servicenow.com and retry. The HTML "
            "wake-up page is NEVER landed in Bronze."
        )


def coerce_empty_strings_to_none(record: Mapping[str, Any]) -> dict[str, Any]:
    """Replace empty-string values with ``None`` on a Table API record.

    ServiceNow renders missing or null field values as the empty string
    ``""`` rather than JSON ``null`` (page § Quirks). The transform
    coerces these to ``NULL`` for nullable Silver columns; doing the same
    coercion at the Bronze envelope level keeps the data shape honest
    for downstream consumers that join on natural keys.
    """
    return {k: (None if v == "" else v) for k, v in record.items()}


def select_table_hwm(records: Iterable[Mapping[str, Any]]) -> str | None:
    """Return the maximum ``sys_updated_on`` across a batch, or ``None``.

    The values are instance-local datetime strings in
    ``YYYY-MM-DD HH:MM:SS`` format; lexicographic max is safe across the
    fixed-width format. Returns ``None`` when the batch is empty or no
    record carries a parseable value.
    """
    best: str | None = None
    for r in records:
        ts = r.get("sys_updated_on")
        if not ts or not _SN_DATETIME_RE.match(str(ts)):
            continue
        if best is None or ts > best:
            best = ts
    return best


def run_ingest_pipeline(
    spark,
    *,
    base_url: str,
    username: str,
    password: str,
    tables: Iterable[str],
    bronze_table_prefix: str,
    run_id: str,
    hwm_value: str | None = None,
) -> None:
    """Databricks entry point — backed by the Databricks SDK / dlt REST source.

    Kept thin: the actual pipeline is declared in the bundle fragment at
    ``src/connectors/servicenow/resources/job.yml``; this function is the
    source-specific primitive that the contract wrapper calls. Live HTTP
    is not exercised in unit tests (CLAUDE.md "No local Spark").

    Authentication is HTTP Basic with a service-account username + password
    resolved from the platform secret scope (REQ-ING-AUTH). Every Table
    API call carries ``sysparm_display_value=false`` and
    ``sysparm_exclude_reference_link=true`` per the page Quirks.
    """
    raise NotImplementedError(
        "Live ServiceNow ingestion runs on Databricks via the SDK / dlt "
        "REST source declared in src/connectors/servicenow/resources/job.yml"
    )


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for ServiceNow.

    State-carried ``extra`` keys: ``base_url``, ``username``, ``password``,
    ``catalog``, optional ``tables`` (defaults to the primary CI table),
    optional ``bronze_table_prefix`` override. The DAB job driver
    populates these from bundle variables and the secret scope; the
    connector NEVER reads ``os.environ`` directly per REQ-ING-AUTH.
    """
    extra = state.get("extra") or {}
    base_url = extra.get("base_url")
    username = extra.get("username")
    password = extra.get("password")
    catalog = extra.get("catalog")
    if not base_url or not username or not password or not catalog:
        raise ValueError(
            "servicenow.ingest_contract requires state['extra'] with "
            "base_url, username, password, catalog"
        )
    tables = extra.get("tables") or ("cmdb_ci_business_app",)
    bronze_table_prefix = extra.get("bronze_table_prefix") or f"{catalog}.bronze_servicenow"
    spark = extra.get("spark")

    run_ingest_pipeline(
        spark,
        base_url=base_url,
        username=username,
        password=password,
        tables=tables,
        bronze_table_prefix=bronze_table_prefix,
        run_id=run_id,
        hwm_value=state.get("hwm_value"),
    )
    return {
        "run_id": run_id,
        "source": "servicenow",
        "record_count": 0,
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{bronze_table_prefix}.cmdb_ci_business_app",
    }
