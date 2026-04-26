# Platform bootstrap job

Apply the cross-source standard silver table DDL. This is **step 4 of the
four-step Phase 1 platform flow**: [Prerequisites](prerequisites.md), then
[Bundle deploy](bundle-deploy.md), then
[Secrets bootstrap](secrets-bootstrap.md), then **Platform bootstrap job**.

The DDL lives at `src/platform/sql/silver_tables.sql`. It defines the
standard Silver tables every connector reads or writes:

- `silver.findings`: the cross-scanner findings table — also the target for AWS WAF, which projects each edge event as one finding row (severity derived from action, status literal `open`, deterministic `finding_id`; the previous `silver.waf_events` carve-out has been collapsed).
- `silver.finding_location`: per-finding code/URL location detail.
- `silver.hwm`: high water mark state for incremental ingestion.
- `silver.repositories`: standard repository entity (populated by SCM connectors).
- `silver.applications`: standard business-application entity, including `app_code` (populated by the CMDB connector).
- `silver.app_repo_mapping`: mapping from application to repository, keyed `(application_id, repository_id, link_source, linked_at)` (populated by the [app-repo linker](app-repo-link.md) and the deferred CMDB-side paths).
- `silver.suppression_rules`: operator-authored finding-suppression entries (analytics-layer concern).

The job is intentionally separate from `databricks bundle deploy` because
DAB has no native `tables` resource type. A table cannot be declared inline
in `databricks.yml`. A SQL job pointed at the warehouse is the established
path for one-shot DDL application.

## Inputs this step consumes

From earlier Phase 1 steps:

- The `platform-bootstrap` job has been deployed by [Bundle deploy](bundle-deploy.md).
- `WAREHOUSE_ID` (passed at deploy time as `--var "warehouse_id=..."`) is the SQL warehouse ID the job targets.
- The catalog (e.g. `appsec_dev`) and `silver` schema exist (created by the platform DAB layer in [Bundle deploy](bundle-deploy.md)).
- The `mvp-connectors` secret scope exists (created by [Secrets bootstrap](secrets-bootstrap.md)). The job itself doesn't read secrets, but ingest jobs for each connector that run against these tables will, so it is convenient to keep the order.

## Run the job

```bash
databricks bundle run platform-bootstrap --target dev
```

The job runs the SQL script on the warehouse. Expected duration: under 30
seconds. These are `CREATE TABLE IF NOT EXISTS` statements against an empty
or already-bootstrapped Silver schema.

The job has no schedule. Operators run it once after the catalog is created.
Re-running is safe. Every statement uses `IF NOT EXISTS` and the file is
otherwise additive only.

## Verify

```bash
# From a SQL editor or via `databricks sql query`:
SHOW TABLES IN appsec_dev.silver;
```

Expected rows: `applications`, `app_repo_mapping`, `finding_location`, `findings`, `hwm`, `repositories`, `suppression_rules`.

```sql
-- Every table is empty after bootstrap; connectors and the app-repo linker
-- populate them on their first runs.
SELECT count(*) FROM appsec_dev.silver.findings;          -- 0
SELECT count(*) FROM appsec_dev.silver.repositories;      -- 0
SELECT count(*) FROM appsec_dev.silver.applications;      -- 0
SELECT count(*) FROM appsec_dev.silver.app_repo_mapping;  -- 0
SELECT count(*) FROM appsec_dev.silver.hwm;               -- 0
```

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `Job 'platform-bootstrap' is not deployed in the current target` | Bundle deploy didn't pick up `src/platform/resources/bootstrap-job.yml`. | Re-run [Bundle deploy](bundle-deploy.md). Confirm the include glob in `databricks.yml` is unchanged. |
| `Cluster <warehouse-id> not found` | `WAREHOUSE_ID` passed at deploy time was wrong. | Re-deploy with the correct warehouse ID from Admin Settings, SQL Warehouses, `<warehouse>`, `Workspace ID`. |
| `Schema 'silver' not found in catalog 'appsec_dev'` | Catalog or schema not yet created. Bundle deploy didn't apply the platform layer. | Re-run [Bundle deploy](bundle-deploy.md). |
| `Table already exists with a different schema` | A previous attempt created `silver.findings` with different columns. | Drop the offending table (`DROP TABLE appsec_dev.silver.findings`) and re-run the job. The redesign DDL is the authoritative schema. |

## Note on connector-side population

`silver.repositories` is populated by the SCM connector transforms (GitHub, GitLab — wider-shape projection still in progress). `silver.applications` is populated by the ServiceNow transform. `silver.app_repo_mapping` is populated by the platform-layer [app-repo linker](app-repo-link.md), which joins `silver.repositories.full_name` to `silver.applications.app_code` on a 5-digit token. The CMDB-side paths (`u_repository_id` on the business-app record, `cmdb_rel_ci` graph rows) are deferred and will land alongside the linker via the `link_source` discriminator column.

This is by design: the platform layer establishes the target schema so downstream analytics can compile against it; the linker fills the application↔repository data path independently of upstream CMDB graph hygiene.

## Phase 1 complete

After this step succeeds, the platform is ready to install connectors.
Proceed to [Install connectors](../connectors/index.md) and start with the
[SCM category](../connectors/scm/index.md). SCM connectors run first because
they populate `silver.repositories`, which findings from every other connector
reference.
