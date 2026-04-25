# Secrets bootstrap

Create the cross-cutting Databricks objects DAB has no native resource type
for, then optionally load secret values for each connector. This is **step 3 of
the four-step Phase 1 platform flow**: [Prerequisites](prerequisites.md), then
[Bundle deploy](bundle-deploy.md), then **Secrets bootstrap**, then
[Platform bootstrap job](platform-bootstrap-job.md).

The split between platform level secret loading and connector level secret loading is
deliberate: the platform script bootstraps shared infrastructure once, and
each connector ships its own loader so users only configure connectors
they actually use.

## Two scripts, two responsibilities

| Script | Scope | Run | Idempotency |
|---|---|---|---|
| `src/platform/scripts/bootstrap.sh` | **Cross-cutting platform objects.** Creates the secret scope `mvp-connectors`, a UC storage credential, and a UC external location pointing at `s3://${ARTIFACT_BUCKET}/`. No knowledge of any specific connector. | Once per workspace, after [Bundle deploy](bundle-deploy.md). | Yes. Re-runs are safe. Existing objects are skipped. |
| `src/connectors/<source>/scripts/load-secrets.sh` | **Secret values for each connector.** Each connector script writes only the secret keys that connector reads. | Once per connector, before the first run of that connector. | Yes. Re-runs update existing values. |

The platform script does **not** load any secret values for individual connectors. The
user runs whichever connector loaders apply to their deployment.

## Platform bootstrap script

Source: `src/platform/scripts/bootstrap.sh`.

### Inputs (env vars)

| Env var | Purpose |
|---|---|
| `EXTERNAL_LOCATION_ROLE_ARN` | IAM role ARN for the UC external location (provisioned by the user per [Prerequisites, AWS backbone](prerequisites.md#aws-backbone-the-user-brings)). |
| `ARTIFACT_BUCKET` | S3 bucket name (no `s3://` prefix). |
| `CATALOG` | Unity Catalog name (e.g. `appsec_dev`). Used to name the UC objects so they are scoped per target. |

The script `set -u`s on missing variables and fails fast.

### What it creates

| Databricks object | Name | Why |
|---|---|---|
| Secret scope | `mvp-connectors` | Container for every connector secret. All connector code reads from this scope. |
| Storage credential | `${CATALOG}-artifacts` (e.g. `appsec_dev-artifacts`) | Unity Catalog wrapper around the UC IAM role provided by the user. |
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
Next: populate connector secrets via src/connectors/<source>/scripts/load-secrets.sh
Then: databricks bundle run platform-bootstrap   (creates silver tables)
```

Re-running is safe. `RESOURCE_ALREADY_EXISTS` errors on the create calls are
swallowed by the `grep -v` filters in the script.

### Verify

```bash
databricks secrets list-scopes | grep mvp-connectors
databricks unity-catalog storage-credentials get "${CATALOG}-artifacts"
databricks unity-catalog external-locations get "${CATALOG}_artifacts"
```

## Secret loaders for each connector

Each connector under `src/connectors/<source>/scripts/` ships its own
`load-secrets.sh`. The full set:

| Connector | Script | Env vars consumed | Secret keys written |
|---|---|---|---|
| github | `src/connectors/github/scripts/load-secrets.sh` | `GITHUB_PAT`, `GITHUB_ORG` | `github_token`, `github_org` |
| gitlab | `src/connectors/gitlab/scripts/load-secrets.sh` | `GITLAB_BASE_URL`, `GITLAB_TOKEN` | `gitlab_base_url`, `gitlab_token` |
| servicenow | `src/connectors/servicenow/scripts/load-secrets.sh` | `SERVICENOW_URL`, `SERVICENOW_USERNAME`, `SERVICENOW_PASSWORD` | `servicenow_url`, `servicenow_username`, `servicenow_password` |
| sonarqube | `src/connectors/sonarqube/scripts/load-secrets.sh` | `SONARQUBE_URL`, `SONARQUBE_TOKEN` | `sonarqube_url`, `sonarqube_token` |
| semgrep | `src/connectors/semgrep/scripts/load-secrets.sh` | `ARTIFACT_BUCKET`, `SEMGREP_PREFIX` (default `semgrep/`) | `semgrep_artifact_bucket`, `semgrep_artifact_prefix` |
| dependency_track | `src/connectors/dependency_track/scripts/load-secrets.sh` | `DT_APIKEY` | `dependency_track_api_key` |
| trufflehog | `src/connectors/trufflehog/scripts/load-secrets.sh` | `TRUFFLEHOG_ARTIFACT_BUCKET`, optionally `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | `trufflehog_artifact_bucket`, optionally `trufflehog_aws_credentials` (JSON blob `{access_key_id, secret_access_key}`) |
| owasp_zap | `src/connectors/owasp_zap/scripts/load-secrets.sh` | `ZAP_URL`, `ZAP_API_KEY` | `zap_url`, `zap_api_key` |
| aws_waf | `src/connectors/aws_waf/scripts/load-secrets.sh` | `WAF_LOG_BUCKET`, `AWS_WAF_IAM_ROLE_ARN` | `waf_log_bucket`, `aws_waf_iam_role_arn` |

Run each only when you're ready to install that connector. The page for
each connector under [Install connectors](../connectors/index.md) documents the
exact env vars and what each secret value should be.

Example: loading github:

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

## Security posture

Secret handling in the MVP is functional but not yet production-grade. The bullets below mark what the loaders and runbooks already do correctly, and what a production deployment must layer on top before going live with real credentials.

### What the loaders do already

- **No secret values in terraform state.** Connector runtimes (gitlab, dependency_track, trufflehog, aws_waf) declare only the *handles* (`*_secret_scope` / `*_secret_key`) for their secrets in `variables.tf`; the values are loaded directly into the Databricks scope by `load-secrets.sh` and never traverse terraform. Connector runtimes that *do* take credential variables (github, sonarqube, semgrep, owasp_zap — all pass AWS keys to provision EKS/RDS/IAM) mark every credential variable `sensitive = true`, which suppresses plan/apply printing and masks the value in human-readable state output.
- **Single workspace-level scope.** All connector secrets live under one named scope (`mvp-connectors`), making it possible to revoke or audit access in one operation rather than chasing per-connector scopes.
- **Idempotent loaders.** `load-secrets.sh` re-runs overwrite existing values — rotation is just `export NEW_VAL=...; bash load-secrets.sh`, no delete-then-create dance.

### What you must add before production

#### 1. Avoid leaving secret values in your shell history

The runbooks ask you to `export TOKEN_VAR="..."` before running each loader. That `export` line is recorded in `~/.bash_history` (or zsh equivalent) for the lifetime of the shell session and is readable by anything that can read your home directory. Three patterns that don't leave a trace:

```bash
# Read interactively without echo (does not enter history):
read -rs -p "GITHUB_PAT: " GITHUB_PAT && export GITHUB_PAT
bash src/connectors/github/scripts/load-secrets.sh

# Or pipe from a credential manager (1Password CLI shown):
export GITHUB_PAT="$(op read 'op://AppSec/GitHub PAT/credential')"
bash src/connectors/github/scripts/load-secrets.sh

# Or temporarily disable history before the export:
set +o history
export GITHUB_PAT="github_pat_..."
bash src/connectors/github/scripts/load-secrets.sh
set -o history
```

The same applies to the AWS keys exported before applying connector runtimes that need them (github, sonarqube, semgrep, owasp_zap).

#### 2. Don't pass secrets via `bundle deploy --var`

The ServiceNow connector page documents a recovery path where you re-deploy the bundle with `--var "servicenow_password=..."`. That puts the password on the `databricks` CLI command line — visible in `ps aux` to any other user on the same machine, and recorded in shell history. Prefer one of:

- pass via env var: `BUNDLE_VAR_servicenow_password="..." databricks bundle deploy ...`. The Databricks CLI resolves any DAB variable `<name>` from a process env var named `BUNDLE_VAR_<name>`. Env-var passing keeps the value off `argv` (it lives in `/proc/<pid>/environ`, only readable by the same UID) and out of `~/.bash_history`. This is the pattern documented in [Bundle deploy](bundle-deploy.md) for the ServiceNow credentials.
- where the underlying resource type accepts the Databricks secret-reference syntax (`{{secrets/scope/key}}`) — currently job parameters, cluster spark conf, and init scripts — wire the resource directly to the secret without a DAB variable in between. UC connection options (the path used by `servicenow`) do not yet accept this syntax in DAB yaml; the env-var pattern above is the supported workaround there.

#### 3. Configure scope ACLs

Out of the box, only the user who created the scope (and workspace admins) can read its secrets. As soon as you grant another principal `READ` or `MANAGE` on `mvp-connectors`, that principal sees every connector's credentials. Lock the scope down to the connector job's service principal:

```bash
# Find the principal the connector jobs run as:
databricks jobs get <job-id> --output JSON | jq '.run_as'

# Grant READ to that principal only; revoke from the human user who bootstrapped:
databricks secrets put-acl mvp-connectors <service-principal-id> READ
databricks secrets delete-acl mvp-connectors <bootstrap-user-email>
```

If multiple connectors with separate trust boundaries share the workspace (e.g. one connector accesses a high-blast-radius source like ServiceNow), split per-connector scopes (`mvp-github`, `mvp-servicenow`, …) and grant each job's service principal `READ` on only its own scope.

#### 4. Use Databricks audit logs

Workspace audit logs include `secrets.getSecret` events. Stand up a regular review (or a dashboard query) to spot:

- secret reads from principals other than the connector job's service principal,
- bursts of reads outside the connector's scheduled window,
- reads that don't correlate with a connector run.

Enable system-table delivery and query `system.access.audit` directly, or pipe the workspace audit log to your SIEM.

#### 5. Rotate on a defined cadence

Static credentials silently lose blast-radius accountability the longer they live. Recommended cadences for the credential types in the MVP:

| Credential | Rotate every | Rotation procedure |
|---|---|---|
| GitHub PAT (`github_token`) | 90 days, or immediately on suspected compromise | Generate new fine-grained PAT in GitHub UI → re-run `load-secrets.sh` with the new value → revoke old PAT after one successful job run. |
| GitLab PAT (`gitlab_token`) | 90 days | Same flow against GitLab → re-run loader → revoke old. |
| ServiceNow password | per the corporate password policy of the user (typically 90 days) | Rotate in ServiceNow → re-run loader → re-deploy bundle if Lakeflow connection caches the value. |
| SonarQube user token (`sonarqube_token`) | 90 days | Generate new token in SonarQube **My Account → Security** → re-run loader → revoke old. |
| Dependency-Track API key (`dependency_track_api_key`) | 90 days | Generate new key for the connector team in DT → re-run loader → delete old. |
| ZAP API key (`zap_api_key`) | 30 days (especially if the daemon is internet-reachable) | Restart the daemon with `-config api.key=<new>` → re-run loader. |
| AWS access keys (used by github/sonarqube/semgrep/owasp_zap runtimes and trufflehog log-secrets) | 30 days | Generate new key pair in IAM → update terraform `tfvars` → `terraform apply` → re-run loader for trufflehog → deactivate old key after one successful pipeline run. |

#### 6. Plan the migration off long-lived static credentials

The MVP uses long-lived static credentials uniformly (PATs, passwords, AWS access keys). Production deployments should migrate each to its short-lived counterpart:

| Source | MVP credential | Production target |
|---|---|---|
| GitHub | Personal Access Token | GitHub App with installation tokens (1-hour TTL) |
| GitLab | Personal Access Token | GitLab project access token with expiry, or OAuth client credentials |
| ServiceNow | Username + password (Basic auth) | OAuth 2.0 client credentials flow (the connector code already supports it; only the loader is single-credential-style) |
| SonarQube | User token | Project analysis token scoped to the connector's read paths |
| AWS | Access key ID + secret access key | IAM role assumed via STS — either an instance profile on the Databricks workspace AWS service credential, or `AssumeRoleWithWebIdentity` from a workload identity. The trufflehog loader's JSON blob shape (`{access_key_id, secret_access_key}`) becomes a session token after migration. |

These are out of MVP scope but should land before the first real-data run.

#### 7. Loader argv exposure (low-priority)

`load-secrets.sh` invokes `databricks secrets put-secret SCOPE KEY --string-value "$VAR"`, so the secret value briefly appears in `argv` of the `databricks` process and is visible to anything with `ps` access during that window. On a single-user developer machine the risk is negligible. On a shared CI runner or a multi-user dev VM, prefer a stdin-fed loader pattern; track the upgrade as a follow-on.

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `EXTERNAL_LOCATION_ROLE_ARN is required` | Env var not exported. | Export the value from [Prerequisites](prerequisites.md#credential-file). |
| `RESOURCE_ALREADY_EXISTS` (visible in stderr but script continues) | Object already created on a prior run. | Expected. Idempotency is handled by the `grep -v` filter. The script proceeds and reports `OK: platform bootstrap complete`. |
| `PERMISSION_DENIED: Cannot create storage credential` | The deploying principal lacks the `CREATE STORAGE CREDENTIAL` privilege on the metastore. | Have a metastore admin grant the privilege. |
| External location create returns `INVALID_PARAMETER_VALUE: Storage credential references an IAM role that cannot be assumed by Databricks UC` | Trust policy on `EXTERNAL_LOCATION_ROLE_ARN` doesn't allow the UC managed storage principal. | Update the trust policy per [Databricks UC storage credentials docs](https://docs.databricks.com/aws/en/connect/unity-catalog/storage-credentials.html). |
| `databricks secrets list-scopes` shows no `mvp-connectors` scope after the script printed `OK` | Workspace selected by the CLI doesn't match the workspace the script targeted. | Confirm `DATABRICKS_HOST` matches the deployed workspace, then re-run. |

## Next

Run [Platform bootstrap job](platform-bootstrap-job.md) to apply the silver
table DDL.
