"""ServiceNow connector module (CMDB, entity-only).

Reads ServiceNow Table API records from ``cmdb_ci_business_app`` and
related CI tables to populate the Silver entity tables — ``silver.applications``,
``silver.teams``, and ``silver.app_repo_mapping``. CMDB sources emit no
findings, so severity / status normalisation are N/A and ``dedup_links``
is not produced.

See ``mkdocs/docs/connectors/cmdb/servicenow.md`` for the reference profile
and the per-REQ traceability binding for this connector.
"""
