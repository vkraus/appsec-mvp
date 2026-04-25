"""OWASP ZAP connector (DAST category).

Hybrid DAST source. The same logical connector serves two operationally
distinct ingestion paths, both of which land in ``bronze_owasp_zap`` and
project into ``silver.findings`` discriminated by ``category="dast"``:

- **CI/CD-step artefact path** (``hwm_kind: artefact_prefix``). ``zap-baseline.py``
  / ``zap-full-scan.py`` / ``zap-api-scan.py`` runs inside CI/CD pipelines
  emit JSON or SARIF reports under ``s3://<bucket>/cicd/zap/<run-id>/...``;
  the connector autoloads from that prefix.
- **On-demand server path** (``hwm_kind: scan_id``). The ZAP daemon REST
  API is driven via scan-and-read orchestration: spider/ascan are kicked
  off per target drawn from ``silver.deployments``; alerts are read back
  via ``/JSON/alert/view/alerts/`` once scan status reaches ``100``.

Application linkage resolves at transform time by joining ``target``
(scanned URL) against ``silver.deployments``; unmatched targets are
emitted unchanged for inventory-gap analysis (a deliberate completeness
signal — NOT a data-quality failure).

See ``mkdocs/docs/connectors/dast/owasp-zap.md`` for the reference
profile and ``.claude/skills/generate-connector/references/dast.md``
for the category contract.
"""
