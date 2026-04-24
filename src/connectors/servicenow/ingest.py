"""ServiceNow ingestion.

Per thesis section 2.4.1, ingestion is delegated to Lakeflow Connect. The
pipeline is declared in ``mvp/resources/servicenow-pipeline.yml`` as a
Databricks Asset Bundle ``pipelines`` resource. The wrapper below exists
only to surface the framework contract at the Python call-site.
"""
from __future__ import annotations

from src.common.contract import BatchDescriptor, ConnectorState


def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper. The Lakeflow Connect pipeline does the work.

    State carries the target Unity Catalog under ``extra["catalog"]``, populated
    by the DAB job driver from the ``target_catalog`` job parameter (resolved
    to ``${var.catalog}`` at deploy time per thesis section 2.3.2). The
    BatchDescriptor ``bronze_table`` is composed against that catalog.
    """
    extra = state.get("extra") or {}
    catalog = extra.get("catalog")
    if not catalog:
        raise ValueError("servicenow.ingest requires state['extra']['catalog']")

    return {
        "run_id": run_id,
        "source": "servicenow",
        "record_count": 0,
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{catalog}.bronze_servicenow.business_applications",
    }
