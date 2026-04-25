# Install connectors

Connectors ingest from AppSec source systems into the Bronze layer of the platform,
then transform into the standard Silver entities and findings.
This is **Phase 2 of the install flow**. It follows
[Setup platform](../platform/index.md) (catalog, schemas, jobs, secret
scope) and feeds [Build analytics](../analytics/index.md) (gold
aggregations, dashboards).

## Adoption order

**SCM connectors must be installed first.** They are the source of truth
for `silver.repositories`, the cross source standard repository entity.
The findings from every non-SCM connector carry a `repository_id` that must
resolve to a row populated by an SCM connector. Without that data, the
cross source rollups in [Evidence scenarios](../analytics/evidence.md)
cannot resolve.

Walk the categories in this order. Each category page repeats the
SCM first dependency note for context:

1. **[SCM](scm/index.md)**: repositories, pull requests, branch policies (GitHub, GitLab). **Install first.** Populates `silver.repositories`.
2. **[CMDB](cmdb/index.md)**: authoritative application inventory and team ownership (ServiceNow). Populates `silver.app_repo`, joining business applications to repositories.
3. **[SAST](sast/index.md)**: static analysis findings keyed by file and rule (SonarQube, Semgrep).
4. **[SCA](sca/index.md)**: dependency keyed findings with CVE correlation (Dependency-Track).
5. **[Secrets](secrets/index.md)**: credential leak detections from pipelines and history (TruffleHog).
6. **[DAST](dast/index.md)**: dynamic scans against deployed services (OWASP ZAP).
7. **[WAF](waf/index.md)**: edge layer block events and rule logs (AWS WAF).

For first time setup, start with the [SCM category](scm/index.md) and pick
either GitHub or GitLab. Each category page documents the shared capability
contract (authentication, pagination, incremental strategy) and lists the
Claude Code skills for the category.

## How connectors are produced

Connectors in this framework are produced by three category aware skills: `analyze-source`, `generate-connector`, and `validate-implementation`. See [Connector skills](../platform/reference/connector-skills.md) for the standard statement of the contract, the procedural body of each skill, and the connector generation aggregator.

## What each connector page contains

Every connector runbook follows the same eight section structure:

1. **What this connector ingests**: source data and resulting Bronze /
   Silver tables.
2. **Dependencies**: explicit data level dependencies, restated on every
   page (Phase 1 plus SCM first).
3. **Operator inputs**: URLs, tokens, credentials with where to obtain
   each.
4. **Optional source runtime**: when to apply
   `src/connectors/<source>/runtime/` and when to skip.
5. **Secrets**: exact keys in the `mvp-connectors` scope and how to load
   them.
6. **Run the job**: `databricks bundle run <source>-connector` (or the
   pipeline name for ServiceNow).
7. **Verify**: SQL queries against Bronze and Silver, including the
   cross source dependency check.
8. **Troubleshooting**: known failure modes including "no rows in
   `silver.repositories`" for non-SCM connectors.

The structure is self sustained. An operator wiring only one connector can
finish its runbook from that one page, with cross-references only to
deeper architectural context (Reference pages, the spec).
