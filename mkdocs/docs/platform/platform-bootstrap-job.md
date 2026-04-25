# Platform bootstrap job

Apply the cross-source canonical silver-table DDL. This is **step 4 of the
four-step Phase 1 platform flow**: [Prerequisites](prerequisites.md) →
[Bundle deploy](bundle-deploy.md) →
[Secrets bootstrap](secrets-bootstrap.md) → **Platform bootstrap job**.

The DDL lives at `src/platform/sql/silver_tables.sql`. It defines the
canonical Silver tables every connector reads or writes:

- `silver.findings` — the cross-scanner findings table.
- `silver.hwm` — high-water-mark state for incremental ingestion.
- `silver.repositories` — canonical repository entity (populated by SCM connectors).
- `silver.app_repo` — application-to-repository mapping (populated by the CMDB connector).

The job is intentionally separate from `databricks bundle deploy` because
DAB has no native `tables` resource type — we can't declare a table inline
in `databricks.yml`. A SQL job pointed at the warehouse is the canonical
path for one-shot DDL application.

## Inputs this step consumes

From earlier Phase 1 steps:

- The `platform-bootstrap` job has been deployed by [Bundle deploy](bundle-deploy.md).
- `WAREHOUSE_ID` (passed at deploy time as `--var "warehouse_id=..."`) is the SQL warehouse ID the job targets.
- The catalog (e.g. `appsec_dev`) and `silver` schema exist (created by the platform DAB layer in [Bundle deploy](bundle-deploy.md)).
- The `mvp-connectors` secret scope exists (created by [Secrets bootstrap](secrets-bootstrap.md)). The job itself doesn't read secrets, but per-connector ingest jobs that run against these tables will, so it is convenient to keep the order.

## Run the job

```bash
databricks bundle run platform-bootstrap --target dev
```

The job runs the SQL script on the warehouse. Expected duration: under 30
seconds — these are `CREATE TABLE IF NOT EXISTS` statements against an empty
or already-bootstrapped Silver schema.

The job has no schedule. Operators run it once after the catalog is created.
Re-running is safe — every statement uses `IF NOT EXISTS` and the file is
otherwise additive only.

## Verify

```bash
# From a SQL editor or via `databricks sql query`:
SHOW TABLES IN appsec_dev.silver;
```

Expected rows: `findings`, `hwm`, `repositories`, `app_repo`.

```sql
-- All four are empty after bootstrap; connectors populate them on their
-- first runs.
SELECT count(*) FROM appsec_dev.silver.findings;       -- 0
SELECT count(*) FROM appsec_dev.silver.repositories;   -- 0
SELECT count(*) FROM appsec_dev.silver.app_repo;       -- 0
SELECT count(*) FROM appsec_dev.silver.hwm;            -- 0
```

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `Job 'platform-bootstrap' is not deployed in the current target` | Bundle deploy didn't pick up `src/platform/resources/bootstrap-job.yml`. | Re-run [Bundle deploy](bundle-deploy.md); confirm the include glob in `databricks.yml` is unchanged. |
| `Cluster <warehouse-id> not found` | `WAREHOUSE_ID` passed at deploy time was wrong. | Re-deploy with the correct warehouse ID from Admin Settings → SQL Warehouses → `<warehouse>` → `Workspace ID`. |
| `Schema 'silver' not found in catalog 'appsec_dev'` | Catalog or schema not yet created — bundle deploy didn't apply the platform layer. | Re-run [Bundle deploy](bundle-deploy.md). |
| `Table already exists with a different schema` | A previous attempt created `silver.findings` with different columns. | Drop the offending table (`DROP TABLE appsec_dev.silver.findings`) and re-run the job. The redesign DDL is the authoritative shape. |

## Note on connector-side population

`silver.repositories` and `silver.app_repo` define the canonical schema
required by the SCM-first data dependency. Connector-side write logic for
both tables is intentionally deferred — see the redesign spec's "Out of
scope" section. Until the GitHub transform is extended to populate
`silver.repositories` and the ServiceNow transform is migrated to
`silver.app_repo`, both tables exist but stay empty.

This is by design: the platform layer establishes the target shape so
downstream analytics can compile against it; the connector follow-on work
fills the data path.

## Phase 1 complete

After this step succeeds, the platform is ready to install connectors.
Proceed to [Install connectors](../connectors/index.md) and start with the
[SCM category](../connectors/scm/index.md) — SCM connectors run first because
they populate `silver.repositories`, which every other connector's findings
reference.
