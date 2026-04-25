# TruffleHog

!!! info "Placeholder, not implemented in MVP"
    A reference TruffleHog connector is not part of the MVP. This page is
    a scaffolding placeholder framing the intended runbook structure. The
    Reference section below documents the integration per the category
    capability scope. Follow the [Secrets skills](skills.md) to generate
    the connector when needed.

## What this connector ingests

TruffleHog is the dedicated secret detection tool. Operational pattern: **CI/CD step**. Each `trufflehog` invocation is a complete scan scoped to a commit range, and the connector uses the latest scanned commit SHA for each repository as the high-water mark (`--since-commit`). The connector invokes the TruffleHog CLI against each enrolled repository and parses its line-delimited JSON output to populate `silver.findings`. The distinguishing capability of TruffleHog is live credential verification. With `--results=verified,unknown`, the tool validates each detected secret against the authentication endpoint of the provider and emits a `Verified` boolean. This boolean is the primary signal for the documented `validity_status` column.

**Category:** Secrets (CLI, CI/CD step) · **Integration pattern:** Artifact path (output from CI/CD step into a Databricks Volume)

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md).
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** TruffleHog findings are keyed by `(repository_id, commit_sha, secret_type, file_path)`. `repository_id` must resolve to a row in `silver.repositories` for downstream rollups to attribute findings to a repository (and through `silver.app_repo`, to a business application).

## Reference

### API

TruffleHog is a CLI tool with no HTTP API. The connector ingests the JSON artefacts that CI/CD step invocations write to a Databricks Volume. It does not invoke `trufflehog` itself. The standard CI/CD invocation is:

```
trufflehog <source-kind> <source-args> --json [--results=verified,unknown] [--since-commit=<sha>]
```

Relevant source kinds: `git`, `github`, `gitlab`, `filesystem`, `docker`, `s3`, `gcs`, `circleci`, `travisci`, `jenkins`, `postman`, `elasticsearch`, `stdin`, `huggingface`. Authentication for the target source (SSH key, GitHub PAT, AWS credentials) is provided via flags or environment variables specific to each source kind. TruffleHog itself needs no separate authentication. `REQ-ING-AUTH` is N/A for this connector per the capability scope for secrets (CLI artefact ingestion path).

Exit codes: `0` on clean run with no results, `1` on tool error, `183` on results found when `--fail` is set. The connector treats the presence of the artefact in the volume as the success signal. Exit codes are recorded in CI/CD logs for operability but are not consumed by the ingestion path.

### Pagination and rate limits

Pagination does not apply. The invocation streams line-delimited JSON to standard output, captured to a single artefact per (repository, commit) pair. The connector parses each object as it arrives. `REQ-ING-PAG` and `REQ-ING-RL` are N/A for the CLI artefact path.

Rate limits apply to the upstream source where TruffleHog calls a verification endpoint. For the `github` kind and for verifier calls against provider APIs, the runner pays the upstream rate limit cost during the scan, not the connector. For `s3`, the CI/CD step sets `--concurrency` (default 12) conservatively to stay within account quotas. Git and filesystem kinds are local and have no network constraints.

### Incremental hook

Full reload. TruffleHog has no general purpose incremental mode and the capability scope for secrets designates secret detection sources as full reload only. Each invocation is a complete scan. The `git` kind accepts `--since-commit` to restrict the scan to commits after a checkpoint. The connector records the most recent commit SHA in `state.hwm` and supplies it as `--since-commit` on the next CI/CD run as an optimisation, not a contract. The Bronze to Silver dedup key `(repository_id, commit_sha, secret_type, file_path)` enforces idempotence regardless of `--since-commit`.

`filesystem`, `docker`, and `s3` kinds have no equivalent flag. Each invocation rescans the full target. The connector stores a synthetic timestamp of the last full scan for cadence observability only.

### Resource schema excerpt

TruffleHog emits one JSON object per line. The fields below are the subset consumed in `git` source mode.

**TruffleHog JSON output consumed fields (`git` source kind)**

| Field | Type | Meaning |
|---|---|---|
| `DetectorName` | string | Detector that matched the secret (e.g. `AWS`, `GitHub`, `SlackWebhook`). Used as `rule_id` in `silver.findings`. |
| `DetectorType` | integer | Numeric detector code assigned by TruffleHog. Preserved in Bronze as a domain column. |
| `DecoderName` | string | Encoding decoder that produced the candidate (e.g. `PLAIN`, `BASE64`). Retained in Bronze for triage. |
| `Verified` | boolean | `true` if live verification confirmed the secret is active against the authentication endpoint of its provider. |
| `VerificationError` | string | Error message emitted when verification was attempted but did not return a definitive result. Null when verification succeeded or was not attempted. |
| `Raw` | string | The raw matched secret value. See Quirks for the mandatory handling policy for this field. |
| `RawV2` | string | Normalised secret value, implementation specific to each detector. Subject to the same handling policy as `Raw`. |
| `Redacted` | string | Redacted form of the secret suitable for logging. Retained in Silver. |
| `ExtraData` | object | Detector specific enrichment (e.g. AWS account ID, ARN, IAM user). Flattened into Bronze domain columns. |
| `SourceID` | integer | Numeric source identifier assigned by TruffleHog at scan time. Retained in Bronze for trace. |
| `SourceType` | integer | Numeric source kind code (e.g. `16` for `git`). Used to dispatch source kind specific extraction. |
| `SourceName` | string | Human readable scan label (e.g. `trufflehog - git`). Retained in Bronze. |
| `SourceMetadata.Data.Git.commit` | string | Commit SHA in which the secret was introduced. |
| `SourceMetadata.Data.Git.file` | string | Repository-relative file path containing the secret. |
| `SourceMetadata.Data.Git.line` | integer | Line number within the file. |
| `SourceMetadata.Data.Git.email` | string | Email address of the commit author. |
| `SourceMetadata.Data.Git.timestamp` | datetime | Commit timestamp. Normalised to UTC at the Bronze to Silver transform. |
| `SourceMetadata.Data.Git.repository` | string | Repository URL. Used to join to `silver.repositories`. |

`SourceMetadata.Data` is source kind specific. The `Git` structure above is the primary variant. Filesystem, GitHub, and S3 scans use leaf structures `Filesystem`, `Github`, `S3`. The connector has source kind specific extraction logic dispatched on `SourceType`.

### Enumerations

**Severity is conventional, not source derived.** TruffleHog emits no severity field. Per the capability scope for secrets, every TruffleHog finding is mapped to `severity=high` by default in `src/connectors/trufflehog/severity.yml`. Deployment level overrides are permitted for detector classes with low entropy (e.g. `GenericApiKey` to `medium`).

**No status vocabulary.** TruffleHog does not expose an open or resolved lifecycle. `REQ-TRF-STS` does not apply. The documented `status` field is set to `open` on first emit and not transitioned by this connector.

**`validity_status` derives from verification flags.** The `Verified` boolean and `VerificationError` string from TruffleHog populate the documented `validity_status` column:

| Source signal | Canonical `validity_status` |
|---|---|
| `Verified=true` | `active` |
| `Verified=false`, empty `VerificationError` | `inactive` |
| `Verified=false`, non-empty `VerificationError` | `unknown` |
| `--no-verification` was set | `unknown` (verification not attempted) |

The `unknown` category matters. It covers secrets on isolated networks or against deprecated provider APIs and must not be conflated with `inactive`.

**`DetectorName`.** TruffleHog ships over 800 detectors covering AWS, GitHub, GitLab, Slack webhooks, Stripe, JIRA, Postgres, MongoDB, and hundreds more. The connector stores `DetectorName` verbatim in Bronze and maps it to `secret_type` without normalisation. The full detector list lives in the TruffleHog repository under `pkg/detectors/`.

### Quirks

**CLI artefact ingestion deviates from the standard preference order.** The category preference (Lakeflow Connect > Databricks SDK > dlt) does not apply because TruffleHog is a binary that runs on CI/CD runners, not a server with an API. The connector reads `--json` artefacts from a Databricks Volume. This is the documented exception alongside Semgrep Docker.

**No severity field. All findings mapped to `high` by convention.** TruffleHog emits no severity. The reference implementation maps every finding to `severity=high` on the premise that a committed secret is a critical exposure regardless of detector. The default is in `src/connectors/trufflehog/severity.yml` and is overridable per deployment.

**`Raw` and `RawV2` must not enter the Silver layer.** The connector drops `Raw` and `RawV2` before Bronze to Silver, keeping only `Redacted`. This is mandatory, not configurable. For deployments needing raw values for automated remediation, the reference implementation provides an optional Unity Catalog column level access policy on the Bronze `Raw`/`RawV2` columns restricted to the `secrets_raw_reader` group.

**Commit level deduplication preserves the audit trail.** The same secret may appear across multiple commits (committed, partially removed, re-introduced). The dedup key `(repository_id, commit_sha, secret_type, file_path)` retains one record per commit rather than collapsing by secret value, preserving audit trails for compliance incident timelines. Queries at gold layer can derive a view deduplicated by value. Both commit level (CI/CD step) and host side periodic global scans (e.g. backfill runs) emit records with `(repository_id, commit_sha)` so dedup unifies them without double counting.

**`DetectorName` substitutes for `rule_id`.** TruffleHog has no rule identifier concept. The connector maps `DetectorName` to `rule_id` in `silver.findings`. The substitution is lossless since `DetectorName` is a stable, versioned identifier in the registry of TruffleHog.

**`--results=verified,unknown` is recommended.** `--only-verified` reduces false positives but silently discards secrets the verifier cannot reach (isolated networks, deprecated provider APIs). The reference implementation uses `--results=verified,unknown` to retain confirmed (`Verified=true`) and undeterminable (non-empty `VerificationError`) findings, leaving filtering to Silver. Definitively `inactive` findings (`Verified=false`, no error) are retained in Bronze for audit but excluded from the gold layer active threat view by default.

## User inputs

TruffleHog is a CLI scanner, not a server. The user (typically CI/CD) runs `trufflehog ... --json` and drops the line-delimited JSON artefacts in either an S3 bucket or a Databricks Unity Catalog Volume. The connector ingests those artefacts; it does not invoke `trufflehog` itself.

| Input | Where to obtain | Used as |
|---|---|---|
| TruffleHog artefact bucket / volume path | Choice of an existing S3 bucket the user controls **or** a Databricks UC Volume managed by this connector. For demos, use the UC Volume `/Volumes/appsec_dev/bronze_trufflehog/artefacts` provisioned by the optional source runtime below. | Env var `TRUFFLEHOG_ARTIFACT_BUCKET` consumed by `src/connectors/trufflehog/scripts/load-secrets.sh`. Also passed as terraform var `trufflehog_artifact_volume_path` if the source runtime is applied. |
| AWS credentials for the artefact bucket reader | Required only if the artefact location is S3: an IAM user or role with `s3:GetObject` and `s3:ListBucket` on the bucket. **Not needed** if using a Databricks UC Volume (Databricks-internal storage, authenticated by the workspace). | Env vars `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` exported before running `load-secrets.sh`; packed by the script as JSON `{access_key_id, secret_access_key}` into secret-scope key `trufflehog_aws_credentials`. |
| At least one TruffleHog `--json` scan artefact | Run TruffleHog locally to seed the location: `docker run --rm -v $(pwd):/repo trufflesecurity/trufflehog:latest filesystem /repo --json > scan.json`. Then upload via `databricks fs cp scan.json dbfs:/Volumes/appsec_dev/bronze_trufflehog/artefacts/` (UC Volume) or `aws s3 cp scan.json s3://<bucket>/trufflehog/<repo>/$(date -u +%FT%TZ).json` (S3). For continuous scans, configure a GitHub Actions workflow to run TruffleHog on every push and upload the artefact. | The connector has nothing to ingest until at least one artefact lands at the configured location. |

!!! warning "Repository identity must already exist in `silver.repositories`"
    TruffleHog findings are keyed by `(repository_id, commit_sha, secret_type, file_path)`. The `repository_id` derives from `SourceMetadata.Data.Git.repository` and must resolve to a row populated by an SCM connector. Install [GitHub](../scm/github.md) (or another SCM) first, otherwise findings will land in Bronze but fail to attribute in Silver/Gold rollups.

## Optional source runtime

`src/connectors/trufflehog/runtime/` provisions a Unity Catalog **External Volume** named `artefacts` under `<catalog>.bronze_trufflehog`, mapped onto a cloud bucket (S3 / ADLS / GCS) the user provisions in advance. The runtime declares a single `databricks_volume` resource. No IAM, no compute, no Kubernetes.

Apply the runtime if you do **not** already have an S3 bucket configured for TruffleHog artefacts (the typical demo path). Skip it if you have an existing bucket: set `TRUFFLEHOG_ARTIFACT_BUCKET` directly to the `s3://...` URI and proceed to Secrets.

```bash
# 1. Export AWS reader credentials (skip for UC-Volume-only deployments).
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export TRUFFLEHOG_ARTIFACT_BUCKET="/Volumes/appsec_dev/bronze_trufflehog/artefacts"

# 2. Load secrets (writes the bucket / path into the mvp-connectors scope; also
#    writes the AWS-creds JSON blob if those env vars are set).
bash src/connectors/trufflehog/scripts/load-secrets.sh

# 3. Apply the runtime (creates the UC Volume that maps to the bucket).
cd src/connectors/trufflehog/runtime
terraform init
terraform apply \
  -var "catalog=appsec_dev" \
  -var "trufflehog_artifact_volume_path=/Volumes/appsec_dev/bronze_trufflehog/artefacts"
cd -
```

The runtime exposes three outputs (`bronze_schema_full_name`, `volume_path`, `volume_full_name`) you can wire into downstream `GRANT` statements. See [`src/connectors/trufflehog/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/trufflehog/runtime) for variable reference and teardown notes (`terraform destroy` removes the UC Volume only; the underlying cloud bucket and any artefacts already uploaded are not managed by this module).

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/trufflehog/scripts/load-secrets.sh`:

| Secret key | Source env var(s) | Purpose |
|---|---|---|
| `trufflehog_artifact_bucket` | `TRUFFLEHOG_ARTIFACT_BUCKET` | S3 URI or UC Volume path the autoloader pipeline reads from. |
| `trufflehog_aws_credentials` | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | JSON-packed reader credentials for the S3 bucket. **Skip both env vars if the artefact location is a UC Volume** — the workspace-internal credential is sufficient. |

Run from repo root after Phase 1 completes:

```bash
export TRUFFLEHOG_ARTIFACT_BUCKET="/Volumes/appsec_dev/bronze_trufflehog/artefacts"
# Skip the next two lines if using a UC Volume only (no S3).
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."

bash src/connectors/trufflehog/scripts/load-secrets.sh
# Expected: OK: trufflehog secrets loaded into scope mvp-connectors
```

The script is idempotent: re-runs replace the existing values. Rotating credentials is `export ...; bash ... load-secrets.sh; databricks bundle deploy --target dev` so the pipeline picks up the new secret on its next run.

## Run the job

The TruffleHog ingestion is a notebook job named `trufflehog-connector` (declared in `src/connectors/trufflehog/resources/job.yml`). It runs hourly on its built-in schedule once deployed. Trigger an on-demand run:

```bash
databricks bundle run trufflehog-connector --target dev
```

The pipeline reads new line-delimited JSON files from the configured artefact location autoloader-style (one file per scan) and lands them into `bronze_trufflehog.findings` (envelope schema in `src/connectors/trufflehog/sql/artefact_envelope.sql`). The follow-on `transform` task projects the envelope into `silver.findings`, dropping `Raw` and `RawV2` per the redaction rule.

Wait approximately 2 minutes after dropping a sample artefact before checking Bronze. Job status is visible under **Workflows → Jobs → trufflehog-connector** in the Databricks UI.

For a fully scripted install (load-secrets + run), use the orchestrator:

```bash
bash src/connectors/trufflehog/scripts/install.sh
```

## Verify

```sql
-- Bronze: raw envelope rows landed by the autoloader (one per artefact).
SELECT count(*) FROM appsec_dev.bronze_trufflehog.findings;

-- Silver: per-finding projection. Includes the detector breakdown.
SELECT secret_type, count(*)
  FROM appsec_dev.silver.findings
 WHERE tool_source = 'trufflehog'
 GROUP BY secret_type
 ORDER BY 2 DESC;

-- Severity is hard-coded high for every TruffleHog finding (REQ-TRF-SEV).
-- This count should equal the silver count above.
SELECT count(*)
  FROM appsec_dev.silver.findings
 WHERE tool_source = 'trufflehog'
   AND severity_canonical = 'high';

-- Validity status derives from Verified / VerificationError. Spot-check the mix.
SELECT validity_status, count(*)
  FROM appsec_dev.silver.findings
 WHERE tool_source = 'trufflehog'
 GROUP BY validity_status;
```

Expected: bronze count equals the number of artefact files dropped at the location; silver count equals the number of TruffleHog finding lines across those files (no filtering occurs between Bronze and Silver for secrets); every silver row has `severity_canonical = 'high'` (literal mapping). For the sanitised reference record at `runtime/files/sample.json`, expect one bronze envelope row and one silver finding row with `validity_status = 'active'` (because `Verified=true`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| 0 rows in `bronze_trufflehog.findings` after a run | Either no artefacts have been dropped at the configured location, or the autoloader checkpoint is stale. List the location: `databricks fs ls dbfs:/Volumes/appsec_dev/bronze_trufflehog/artefacts/`. If files are present but bronze is empty, re-run with a full refresh: `databricks bundle run trufflehog-connector --target dev --refresh-all`. |
| AWS auth error in the ingest task log (`AccessDenied`, `InvalidAccessKeyId`) | The reader credentials in the secret scope are missing or expired. Re-export `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, re-run `bash src/connectors/trufflehog/scripts/load-secrets.sh`, then re-deploy the bundle (`databricks bundle deploy --target dev`) so the job picks up the rotated secret on its next run. |
| `validity_status` always null in silver | Older TruffleHog versions (< 3.50) emit no `Verified` field. Upgrade the CI/CD scanner to `>= 3.50` and re-scan; also confirm the scan was invoked with `--results=verified,unknown` rather than `--no-verification`. |
| Silver rows have `repository_id` but no matching row in `silver.repositories` | Install at least one SCM connector and run it before the cross-source join can resolve. See [GitHub](../scm/github.md) or the [SCM category](../scm/index.md). |
| Optional runtime: `terraform apply` fails with `schema not found: bronze_trufflehog` | The connector bundle declares the schema (`src/connectors/trufflehog/resources/schemas.yml`). Run `databricks bundle deploy --target dev` first, then re-apply the runtime — or apply both in the same operator session. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | n/a | N/A |
| `REQ-ING-PAG` | n/a | N/A |
| `REQ-ING-RL` | n/a | N/A |
| `REQ-ING-HWM` | n/a | N/A |
| `REQ-TRF-MAP` | `src/connectors/trufflehog/tests/test_transform.py::test_record_to_silver_projects_every_consumed_field` | PASS |
| `REQ-TRF-SEV` | `src/connectors/trufflehog/tests/test_transform.py::test_severity_is_hard_coded_high` | PASS |
| `REQ-TRF-STS` | n/a | N/A |
| `REQ-TRF-TS` | `src/connectors/trufflehog/tests/test_transform.py::test_source_timestamp_is_preserved_from_git_leaf` | PASS |
| `REQ-DQ` | `src/connectors/trufflehog/tests/test_transform.py::test_missing_git_metadata_produces_well_formed_row` | PASS |
| `REQ-DEDUP` | `src/connectors/trufflehog/tests/test_transform.py::test_dedup_key_is_four_tuple_per_secrets_reference` | PASS |

Collected 26 requirement-bound tests via `pytest src/connectors/trufflehog/tests/ -v --tb=short` (2026-04-25, 0.31 s wall-clock); 26 passed, 0 failed, 4 skipped as documentation markers for the N/A rows. Five requirements are marked N/A: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` because the CLI artefact ingestion path has no API auth, pagination, or upstream rate limit (quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix"); `REQ-ING-HWM` because TruffleHog is full reload only per the capability scope for secrets and the commit SHA lives in the artefact key rather than as a record level HWM column; `REQ-TRF-STS` because secret detection sources expose no lifecycle vocabulary to normalise (references/secrets.md § Quirks).

### Tests

Tests live under [`src/connectors/trufflehog/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/trufflehog/tests). The report table above is the outcome for each REQ.

## Generation log

This connector page is produced by the connector lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                              | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (secrets)         | name=TruffleHog; url=https://github.com/trufflesecurity/trufflehog; category=secrets | mkdocs/docs/connectors/secrets/trufflehog.md §1–§3                                 | 2026-04-25 | 5b7fa80 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (secrets)     | page hash=5fc403d47499                                                              | src/connectors/trufflehog/, src/connectors/trufflehog/tests/, src/connectors/trufflehog/severity.yml, src/connectors/trufflehog/status.yml, src/connectors/trufflehog/resources/job.yml | 2026-04-25 | 61e9510 (retrofit-9-connectors)          |
| Validation         | `validate-implementation` (secrets)| module path=src/connectors/trufflehog/                                              | mkdocs/docs/connectors/secrets/trufflehog.md §5                                    | 2026-04-25 | 12f656a (retrofit-9-connectors)          |
