# Secrets bootstrap

Create the cross-cutting Databricks objects DAB has no native resource type
for, then optionally load per-connector secret values. This is **step 3 of
the four-step Phase 1 platform flow**: [Prerequisites](prerequisites.md) →
[Bundle deploy](bundle-deploy.md) → **Secrets bootstrap** →
[Platform bootstrap job](platform-bootstrap-job.md).

The split between platform-level and per-connector secret loading is
deliberate: the platform script bootstraps shared infrastructure once, and
each connector ships its own loader so operators only configure connectors
they actually use.

## Two scripts, two responsibilities

| Script | Scope | Run | Idempotency |
|---|---|---|---|
| `src/platform/scripts/bootstrap.sh` | **Cross-cutting platform objects.** Creates the secret scope `mvp-connectors`, a UC storage credential, and a UC external location pointing at `s3://${ARTIFACT_BUCKET}/`. No connector-specific knowledge. | Once per workspace, after [Bundle deploy](bundle-deploy.md). | Yes — re-runs are safe; existing objects are skipped. |
| `src/connectors/<source>/scripts/load-secrets.sh` | **Per-connector secret values.** Each connector script writes only the secret keys that connector reads. | Once per connector, before that connector's first run. | Yes — re-runs update existing values. |

The platform script does **not** load any per-connector secret values. The
operator runs whichever connector loaders apply to their deployment.

## Platform bootstrap script

Source: `src/platform/scripts/bootstrap.sh`.

### Inputs (env vars)

| Env var | Purpose |
|---|---|
| `EXTERNAL_LOCATION_ROLE_ARN` | IAM role ARN for the UC external location (operator-provisioned per [Prerequisites → AWS backbone](prerequisites.md#aws-backbone-the-operator-brings)). |
| `ARTIFACT_BUCKET` | S3 bucket name (no `s3://` prefix). |
| `CATALOG` | Unity Catalog name (e.g. `appsec_dev`). Used to name the UC objects so they are scoped per-target. |

The script `set -u`s on missing variables and fails fast.

### What it creates

| Databricks object | Name | Why |
|---|---|---|
| Secret scope | `mvp-connectors` | Container for every per-connector secret. All connector code reads from this scope. |
| Storage credential | `${CATALOG}-artifacts` (e.g. `appsec_dev-artifacts`) | Unity Catalog wrapper around the operator's UC IAM role. |
| External location | `${CATALOG}_artifacts` | UC pointer to `s3://${ARTIFACT_BUCKET}/` using the storage credential. The semgrep and owasp_zap connectors create external volumes inside this location. |

### Run

```bash
# From repo root, with env vars from Prerequisites already exported:
export EXTERNAL_LOCATION_ROLE_ARN="arn:aws:iam::123456789012:role/uc-external-location"
export ARTIFACT_BUCKET="my-appsec-mvp-artifacts"
export CATALOG="appsec_dev"

bash src/platform/scripts/bootstrap.sh
```

Expected output:

```
==> Creating secret scope: mvp-connectors
==> Creating storage credential: appsec_dev-artifacts
==> Creating external location: appsec_dev_artifacts
OK: platform bootstrap complete.
Next: populate per-connector secrets via src/connectors/<source>/scripts/load-secrets.sh
Then: databricks bundle run platform-bootstrap   (creates silver tables)
```

Re-running is safe — `RESOURCE_ALREADY_EXISTS` errors on the create calls are
swallowed by the script's `grep -v` filters.

### Verify

```bash
databricks secrets list-scopes | grep mvp-connectors
databricks unity-catalog storage-credentials get "${CATALOG}-artifacts"
databricks unity-catalog external-locations get "${CATALOG}_artifacts"
```

## Per-connector secret loaders

Each connector under `src/connectors/<source>/scripts/` ships its own
`load-secrets.sh`. The full set:

| Connector | Script | Env vars consumed | Secret keys written |
|---|---|---|---|
| github | `src/connectors/github/scripts/load-secrets.sh` | `GITHUB_PAT`, `GITHUB_ORG` | `github_token`, `github_org` |
| servicenow | `src/connectors/servicenow/scripts/load-secrets.sh` | `SERVICENOW_URL`, `SERVICENOW_USERNAME`, `SERVICENOW_PASSWORD` | `servicenow_url`, `servicenow_username`, `servicenow_password` |
| sonarqube | `src/connectors/sonarqube/scripts/load-secrets.sh` | `SONARQUBE_URL`, `SONARQUBE_TOKEN` | `sonarqube_url`, `sonarqube_token` |
| semgrep | `src/connectors/semgrep/scripts/load-secrets.sh` | `ARTIFACT_BUCKET`, `SEMGREP_PREFIX` (default `semgrep/`) | `semgrep_artifact_bucket`, `semgrep_artifact_prefix` |
| owasp_zap | `src/connectors/owasp_zap/scripts/load-secrets.sh` | `ZAP_URL`, `ZAP_API_KEY` | `zap_url`, `zap_api_key` |

Run each only when you're ready to install that connector. The connector's
own page under [Install connectors](../connectors/index.md) documents the
exact env vars and what each secret value should be.

Example — loading github:

```bash
export GITHUB_PAT="github_pat_..."
export GITHUB_ORG="my-org"
bash src/connectors/github/scripts/load-secrets.sh
# OK: github secrets loaded into scope mvp-connectors
```

### Verify

```bash
databricks secrets list-secrets mvp-connectors
```

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `EXTERNAL_LOCATION_ROLE_ARN is required` | Env var not exported. | Export the value from [Prerequisites](prerequisites.md#credential-file). |
| `RESOURCE_ALREADY_EXISTS` (visible in stderr but script continues) | Object already created on a prior run. | Expected. Idempotency is handled by the `grep -v` filter; the script proceeds and reports `OK: platform bootstrap complete`. |
| `PERMISSION_DENIED: Cannot create storage credential` | The deploying principal lacks the `CREATE STORAGE CREDENTIAL` privilege on the metastore. | Have a metastore admin grant the privilege. |
| External location create returns `INVALID_PARAMETER_VALUE: Storage credential references an IAM role that cannot be assumed by Databricks UC` | Trust policy on `EXTERNAL_LOCATION_ROLE_ARN` doesn't allow the UC managed-storage principal. | Update the trust policy per [Databricks UC storage credentials docs](https://docs.databricks.com/aws/en/connect/unity-catalog/storage-credentials.html). |
| `databricks secrets list-scopes` shows no `mvp-connectors` scope after the script printed `OK` | Workspace selected by the CLI doesn't match the workspace the script targeted. | Confirm `DATABRICKS_HOST` matches the deployed workspace; re-run. |

## Next

Run [Platform bootstrap job](platform-bootstrap-job.md) to apply the silver
table DDL.
