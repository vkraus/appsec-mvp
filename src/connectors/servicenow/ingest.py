"""ServiceNow ingestion — Lakeflow Connect managed.

Live ingestion of ``cmdb_ci_business_app`` and related CI tables is owned by
the Databricks Lakeflow Connect ServiceNow managed connector, declared in
``src/connectors/servicenow/resources/pipeline.yml``. This module exists only
to satisfy the framework's per-source ``ingest(run_id, state) -> batch``
contract: it is never invoked in the live path.

The Bronze→Silver transform runs as a separate downstream task — see
``src/connectors/servicenow/transform.py`` and ``resources/job.yml``
(transform-only single task).

Per ``operational.yml.databricks_runtime.ingestion_path = lakeflow_connect``,
the four-skill chain emits this file in its thin form (no helpers, no live
HTTP path). See the LFC managed-source catalogue in
``.claude/skills/analyze-source/SKILL.md``.
"""

from __future__ import annotations

from src.platform.contract import BatchDescriptor, ConnectorState


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for ServiceNow.

    Validates ``state['extra']`` for the standard ServiceNow credential set so
    that a misconfigured DAB job fails fast rather than entering the live
    ingestion path with empty credentials. The wrapper itself never performs
    HTTP — Lakeflow Connect owns that.

    State-carried ``extra`` keys: ``base_url``, ``username``, ``password``,
    ``catalog``. The DAB job driver populates these from bundle variables and
    the secret scope; the connector NEVER reads ``os.environ`` directly per
    REQ-ING-AUTH.

    Raises:
        ValueError: when any required ``state['extra']`` field is missing.
        RuntimeError: always, when called past credential validation. Live
            ingestion is owned by Lakeflow Connect; calling this function
            in the live path is a misconfiguration.
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
    raise RuntimeError(
        "Lakeflow Connect owns servicenow ingestion; this wrapper is never "
        "invoked. See src/connectors/servicenow/resources/pipeline.yml."
    )
