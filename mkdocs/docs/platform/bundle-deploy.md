# Bundle deploy

Deploy the Databricks Asset Bundle (DAB) defined at the repository root.
This is **step 2 of the four-step Phase 1 platform flow**:
[Prerequisites](prerequisites.md), then **Bundle deploy**, then
[Secrets bootstrap](secrets-bootstrap.md), then
[Platform bootstrap job](platform-bootstrap-job.md).

The bundle is the single source of truth for every Databricks resource the
platform owns. A clean checkout against an empty workspace ends with a
deployable bundle: catalog, schemas, jobs, pipelines, volumes, and
connections all created, none yet running.

## Inputs this step consumes

From [Prerequisites](prerequisites.md):

- `DATABRICKS_HOST`: workspace URL (env var; resolved by `${env.DATABRICKS_HOST}` in `databricks.yml`).
- `DATABRICKS_TOKEN`: workspace PAT (env var read by the Databricks CLI).
- `WAREHOUSE_ID`: SQL warehouse ID for the platform bootstrap job (passed via `--var`).
- `ARTIFACT_BUCKET`: S3 bucket name for scanner artifacts (passed via `--var`).
- ServiceNow connection params (passed via `--var`, only if the servicenow connector is in scope):
  `servicenow_host`, `servicenow_username`, `servicenow_password`.

The `databricks.yml` file in the bundle declares these as DAB variables. Any unset
variable forces the user to supply it on the command line. The deploy
fails fast rather than silently using a default.

## Targets

Three targets are pre-defined in `databricks.yml`:

| Target | Mode | Catalog | When to use |
|---|---|---|---|
| `dev` (default) | development | `appsec_dev` | First-time setup, day-to-day iteration. |
| `staging` | production | `appsec_staging` | Optional pre-prod target, deployed under `/Shared/appsec-staging`. |
| `prod` | production | `appsec_prod` | Production deployment under `/Shared/appsec`. |

The redesigned bundle does not auto-create the workspace, the catalog, or the
SQL warehouse. Those live in [Prerequisites](prerequisites.md). It creates
only the resources listed below within an existing workspace.

## Deploy

From a clean checkout, with the env vars from [Prerequisites](prerequisites.md)
exported:

```bash
# Validate the bundle resolves and the YAML is well-formed.
databricks bundle validate \
  --target dev \
  --var "warehouse_id=${WAREHOUSE_ID}" \
  --var "artifact_bucket=${ARTIFACT_BUCKET}"

# Deploy. First run creates the catalog, schemas, jobs, pipelines, volumes,
# connection. Subsequent runs reconcile any drift.
databricks bundle deploy \
  --target dev \
  --var "warehouse_id=${WAREHOUSE_ID}" \
  --var "artifact_bucket=${ARTIFACT_BUCKET}"
```

If you intend to deploy the Lakeflow pipeline and UC connection for the servicenow connector, also pass:

```bash
  --var "servicenow_host=${SERVICENOW_HOST}" \
  --var "servicenow_username=${SERVICENOW_USERNAME}" \
  --var "servicenow_password=${SERVICENOW_PASSWORD}"
```

Subsequent connector deploys can reuse the same command. The bundle is
declarative and idempotent.

## Resources the bundle creates

The DAB include glob (`src/platform/resources/*.yml`,
`src/connectors/*/resources/*.yml`, `src/analytics/resources/*.yml`) picks up
fragments from each component automatically. After `databricks bundle deploy`
the workspace contains:

### Platform layer (`src/platform/resources/`)

| Resource | Type | Purpose |
|---|---|---|
| `appsec` | catalog | Unity Catalog (`appsec_dev`, `appsec_staging`, or `appsec_prod`) for Bronze, Silver, and Gold. |
| `silver` | schema | Cross-source standard Silver: `findings`, `hwm`, `repositories`, `app_repo`. |
| `platform-bootstrap` | job | One-task SQL job that runs `src/platform/sql/silver_tables.sql` against the SQL warehouse. User runs it once after secrets are loaded. See [Platform bootstrap job](platform-bootstrap-job.md). |

### Connector layers (`src/connectors/<source>/resources/`)

| Connector | Resources | Notes |
|---|---|---|
| **github** | `bronze_github` schema, `silver_github` schema, `github-connector` job. | Two-task job (ingest then transform), scheduled every 15 minutes. |
| **servicenow** | `bronze_servicenow` schema, `silver_servicenow` schema, `servicenow` connection, `servicenow_ingest` Lakeflow pipeline. | Lakeflow Connect ingestion of `cmdb_ci_business_app` and `cmdb_rel_ci`, daily cron. The connection consumes `servicenow_host`, `servicenow_username`, and `servicenow_password` DAB variables. |
| **sonarqube** | `bronze_sonarqube` schema, `sonarqube-connector` job. | Two-task job (ingest then transform). The connector module is a structural skeleton (`ingest()` and `transform()` raise `NotImplementedError`). |
| **semgrep** | `bronze_semgrep` schema, `semgrep_artifacts` external volume (S3-backed). | Reads scan artifacts from `s3://${artifact_bucket}/semgrep/` via the volume. No job. Connector ingest entry-points are scaffolded but not wired. |
| **owasp_zap** | `bronze_owasp_zap` schema, `zap_artifacts` external volume (S3-backed). | Same structure as semgrep. Reads artifacts from `s3://${artifact_bucket}/zap/`. |

### Analytics layer (`src/analytics/resources/`)

| Resource | Type | Purpose |
|---|---|---|
| `gold` | schema | Cross-source analytics outputs (owned by analytics). |
| `analytics` | job | Placeholder job pointing at `src/analytics/sql/gold_findings_summary_placeholder.sql`. Full analytics implementation is future work. |

The total resource count after a clean `bundle deploy` against `dev` is
roughly: 1 catalog, 9 schemas, 2 volumes, 1 connection, 1 pipeline, 4 jobs.

## Verify

```bash
# List the bundle deployments in the workspace.
databricks bundle summary --target dev

# Confirm catalog and schemas exist.
databricks catalogs get appsec_dev
databricks schemas list appsec_dev

# Confirm jobs are visible.
databricks jobs list --output JSON | jq '.jobs[] | select(.settings.name | startswith("github") or startswith("sonarqube") or startswith("platform-bootstrap")) | .settings.name'

# Confirm the servicenow Lakeflow pipeline is registered (only if --var
# servicenow_* values were supplied).
databricks pipelines list-pipelines | grep servicenow_ingest
```

The jobs and pipeline are present but **not yet runnable**: silver tables
have not been created (the platform bootstrap job hasn't run) and secrets
for each source are not in the secret scope. Those land in the next two steps.

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `Error: variable "warehouse_id" has not been assigned a value` | Missing `--var "warehouse_id=..."` on the deploy command. | Re-run with the variable. The bundle deliberately has no default to force user awareness. |
| `INVALID_PARAMETER_VALUE: Catalog 'appsec_dev' already exists with a different owner` | Catalog created by a previous attempt under a different principal. | Drop the catalog (`databricks catalogs delete appsec_dev --force`) and redeploy, or change the `catalog` variable for this target. |
| `PERMISSION_DENIED: Cannot create catalog` | The user behind the PAT lacks the `CREATE CATALOG` privilege on the metastore. | Have a metastore admin grant `CREATE CATALOG` to the deploying principal, or switch to an admin PAT for first-time setup. |
| `INVALID_PARAMETER_VALUE: Connection 'servicenow' could not be created: authentication failed` | `servicenow_*` variables wrong. | Re-validate against the ServiceNow tenant: `curl -u $USER:$PASS https://$HOST/api/now/table/cmdb_ci_business_app?sysparm_limit=1`. Re-deploy with corrected values. |
| `Volume external storage location 's3://.../semgrep/' is not found` | UC external location not yet created. Runs before `src/platform/scripts/bootstrap.sh`. | Run [Secrets bootstrap](secrets-bootstrap.md), then re-deploy. The external location is created by the bootstrap script. Re-deploys are idempotent. |

## Next

Run [Secrets bootstrap](secrets-bootstrap.md) to create the cross-cutting
secret scope, storage credential, and external location, then load
secrets for each connector.
