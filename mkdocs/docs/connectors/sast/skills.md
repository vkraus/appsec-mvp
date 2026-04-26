# SAST skills

Four skills cover the connector lifecycle for SAST sources. Each carries a SAST-specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: SAST reference

Facts the analyze-source skill needs to write a complete Reference section for a SAST source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SAST sources emit findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SAST (per the SonarQube and Semgrep traceability rows).
- For CLI-based SAST (artefact ingestion), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A. The catalog notes the CLI-artefact ingestion path "has no API auth, pagination, or rate limit." The Reference section MUST disclose this if the source is CLI-based.

### Default severity

`medium`. Source severity vocabularies have three to five levels with overlapping but non-identical names. Per-source lookup tables at `src/connectors/{source}/severity.yml` map each value to the standardized four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data-quality warning.

### Incremental strategy

Selection depends on the deployment style documented in the SAST capability scope:

- **Server-based tools** carry an update-timestamp column usable as a high-water mark; this is the default mode.
- **CLI-based tools** (including container-hosted CLIs such as Semgrep in Docker) emit JSON or SARIF artefacts and have no server-side incremental hook. Treat these under the full-reload strategy with the commit SHA or scan-start timestamp as the HWM.
- **Platform-integrated scanners** (SAST hosted inside the SCM platform) share the incremental hook of the host platform, typically webhook or `updated_at`.

### Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the standard SAST scope.

The Resource schema excerpt of the Reference section MUST therefore extract `repository_id`, `file_path`, `rule_id`, and the source-side `source_finding_id` building blocks (for example SonarQube `key`; Semgrep `id` / `check_id`+`path`+`line`).

### Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the code-level finding table).

### Authentication norms

PAT or API-key based across all three deployment styles per the SAST capability scope. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SAST is well-served by the SDK or dlt path. CLI-based SAST is the documented exception. Patterns using `httpx`, `requests`, or artefact-collection are permitted because none of the three preferred tools cover the CI-artefact contract.

### Quirks

- **Operational pattern axis.** SAST tools split orthogonally on CI/CD-step (per-commit, scoped to the run) vs periodic-global (scheduled, scoped to the codebase). The Quirks fact in the Reference section MUST disclose which mode the source operates in. The incremental key for the connector changes between modes (commit SHA / run ID for CI/CD-step; updated-since timestamp for periodic-global).
- **CWE category.** Most SAST tools emit a CWE identifier alongside the rule ID; record it in the Resource schema excerpt for downstream classification work.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The Reference section MUST list every documented source severity value to support REQ-TRF-SEV coverage.
- **CLI-artefact path.** Where a SAST tool runs as a CI/CD CLI (Semgrep Docker, container-hosted CLIs), document the artefact location (pipeline artifact, mounted volume, object-storage prefix), the SARIF / JSON format flavour, and any container-runtime quirks.
- **Rule-pack drift.** Rule IDs change across rule-pack versions. The Quirks fact in the Reference section should note whether the source provides rule-stability guarantees.

*Rendered from `.claude/skills/analyze-source/references/sast.md`. Source-of-truth lives in the skill file.*

## provision-source: SAST reference

Facts the provision-source skill needs to emit the source-side runtime for a SAST source. SAST splits into two sub-shapes that drive a single auto-deriver decision: presence of `helm_release` selects server-based; presence of `kubernetes_cron_job_v1` + IRSA selects CLI-artefact.

### Sub-shape A: server-based (SonarQube pattern)

`runtime_provisioner: terraform-aws-eks-helm`. Provider stack: `aws` + `kubernetes` + `helm` + `random`. The runtime deploys the SAST server as a Helm release on an existing EKS cluster (typical chart: `https://SonarSource.github.io/helm-chart-sonarqube`, version `10.6.1+2742`) in a dedicated namespace, exposed via a LoadBalancer Service on port `9000`. Helm timeout is 900s — SonarQube startup is slow.

The runtime optionally provisions a dedicated **RDS Postgres** backing store (default `db.t3.small`, 20 GiB, Postgres 15, encrypted at rest, no PITR backups) when `var.rds_endpoint` is empty. When the operator points at an existing Postgres, the RDS resources are skipped. The runtime also emits a 40-character random `{source}_project_token` value for use as a long-lived analysis token (the Helm chart does not support declarative token creation; the operator registers the token against the running server post-apply via `POST /api/user_tokens/generate`).

Required `operational.yml.source_runtime` fields when server: `runtime_provisioner`, `aws_region_var_name`, `eks_cluster_name_var_name`, `helm_chart_repository`, `helm_chart_name`, `helm_chart_version_default`, `admin_password_var_name`. Optional with category defaults: namespace (e.g. `sonarqube`), service port (`9000`), Helm timeout (`900`s), and a full set of RDS tunables (`rds_engine_version_default`, `rds_instance_class_default`, `rds_allocated_storage_default`, `rds_db_name_default`, `rds_username_default`, `rds_parameter_group_family_default`).

Outputs: `{source}_url`, `{source}_namespace`, `{source}_db_secret_name`, `{source}_project_token` (sensitive), and (when the module created the RDS) `rds_endpoint`, `rds_db_name`, `rds_username`, `rds_password` (sensitive).

> **Destroy caveat (carried into the page):** RDS is created with `skip_final_snapshot = true` and `deletion_protection = false`, with `backup_retention_period = 0`. Running `terraform destroy` permanently loses all SAST data. Take a manual snapshot first if needed.

No `runtime/files/*` sidecars by default. If an operator wants a custom Helm `values.yaml` overlay, it lives at `runtime/files/values.yaml` and the runtime merges it via `values = [yamlencode({...}), file("${path.module}/files/values.yaml")]` — the skill emits the reference but never the file body.

### Sub-shape B: CLI-artefact (Semgrep pattern)

`runtime_provisioner: terraform-aws-eks-cronjob`. Provider stack: `aws` + `kubernetes`. The runtime deploys an EKS CronJob (default schedule `0 */6 * * *` — every 6 hours) that periodically clones a list of git repos, runs `{source} scan --json`, and uploads JSON findings to an S3 artefact bucket via **IRSA** (IAM-role-for-service-account) with permissions `s3:PutObject` + `s3:GetObject` + `s3:ListBucket` on `var.artifact_bucket`.

Required fields when CLI-artefact: `runtime_provisioner`, `aws_region_var_name`, `eks_cluster_name_var_name`, `eks_oidc_provider_arn_var_name`, `artifact_bucket_var_name`, `scanner_image_default` (e.g. `returntocorp/semgrep:latest`), `scan_script_path`, `irsa_service_account_name`, `env_secret_keys` (default `["ARTIFACT_BUCKET", "SCANNER_REPO_LIST", "AWS_REGION", "GH_PAT"]`), `clone_token_var_name`. Optional: `cron_schedule_default`, `repo_urls_default` (default `["owasp/juice-shop"]`), `irsa_s3_actions`.

One operator-authored sidecar: `runtime/files/{source}-scan.sh` — the driver script loaded into a ConfigMap and mounted into the CronJob pod at `/scripts/scan.sh`. The script `git clone`s each repo in `$SCANNER_REPO_LIST`, runs the scanner with `--json`, and uploads to `s3://${ARTIFACT_BUCKET}/periodic/{source}/<repo>/<timestamp>.json`. Cloning uses `https://x-access-token:${GH_PAT}@github.com/${slug}.git`. Operator-authored — the skill emits the `file("${path.module}/files/{source}-scan.sh")` reference but never the script body.

Outputs: `{source}_namespace`, `{source}_cronjob_name`, `{source}_irsa_role_arn`, `{source}_env_secret_name`.

### `runtime/install.sh` shape

Both sub-shapes share the standard `terraform init` + `terraform apply -auto-approve` wrapper. Server-based requires `AWS_REGION`, `AWS_*` credentials, `EKS_CLUSTER_NAME`, `{SOURCE_UPPER}_ADMIN_PASSWORD`, with optional `RDS_ENDPOINT` / `RDS_USERNAME` / `RDS_PASSWORD` / `VPC_*` for the existing-Postgres path. CLI-artefact requires `EKS_CLUSTER_OIDC_PROVIDER_ARN`, `ARTIFACT_BUCKET`, and `GITHUB_PAT_FOR_CLONE` in addition to the AWS+EKS basics.

### Page §Source provisioning section template

For server-based: a paragraph documenting the Helm release + optional RDS provisioning, the security/destroy caveat, the required runtime inputs at a glance, the apply command, and the Helm-chart-does-not-support-declarative-tokens callout describing the post-apply `POST /api/user_tokens/generate` step that registers the random token from the runtime output against the running server.

For CLI-artefact: a paragraph documenting the EKS CronJob + IRSA + S3 path, required runtime inputs (`aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `eks_cluster_name`, `eks_cluster_oidc_provider_arn`, `artifact_bucket`, `github_pat_for_clone`), and a callout that `runtime/files/{source}-scan.sh` is operator-authored — operators must inspect and customise it before apply (the default expects `org/repo` slugs and clones via GitHub HTTPS with PAT). After apply, verify the CronJob is scheduled with `kubectl -n {namespace} get cronjob`. The first scan runs at the next cron tick.

*Rendered from `.claude/skills/provision-source/references/sast.md`. Source of truth lives in the skill file.*

## generate-connector: SAST reference

Facts the generate-connector skill needs to emit a SAST connector module. SAST sources emit code-level findings.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SAST (full ten REQ-IDs apply per the SonarQube and Semgrep traceability rows): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. The catalog notes the CLI-artefact path "has no API auth, pagination, or rate limit." Do NOT bind these three.
- Platform-integrated SAST (hosted inside the SCM platform): inherits the auth, pagination, and rate-limit code from the SCM connector. Bind only the transform / DQ / dedup REQ-IDs locally and document the inherited bindings in a comment.

### Default severity

`medium`. Generate `src/connectors/{source}/severity.yml` covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) mapped to the standardized four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` with a data-quality warning per the helper in `src/platform/`.

The `mapping.yml` `severity` field references the lookup file by path, NOT a hard-coded value:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: src/connectors/{source}/severity.yml
```

### Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based**: native update-timestamp HWM column (e.g. `updated_at`, `creationDate`, `last_scan_finished_at`). Default mode.
- **CLI-based**: full-reload from object-storage prefix or pipeline artefact; HWM is the commit SHA or scan-start timestamp recorded in the artefact filename.
- **Platform-integrated**: inherit the webhook or `updated_at` hook from the SCM platform.

### Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py` when building `dedup_links` rows:

```python
dedup_key = (row["repository_id"], row["file_path"], row["rule_id"])
```

The transform MUST also project `source_finding_id` (the source-side stable identifier: SonarQube `key`; Semgrep `id` for Cloud or `check_id`+`path`+`line` for CLI) for cross-run linkage.

### Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sast"` literally.

### Authentication norms

PAT or API-key based across all three deployment styles. `ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names only. For CLI-based connectors, no API auth applies. IAM on the artefact bucket governs access.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SAST is well-served by the SDK or dlt path (paginated REST).
- **CLI-based SAST is the documented exception**. Emit a CLI-artefact ingest path (e.g. `httpx` for cloud-storage APIs, or autoloader on the object-storage prefix) and justify the deviation in a top-of-file comment in `ingest.py`. This is one of the two CLI-artefact exceptions called out in `CLAUDE.md` (alongside secrets / Semgrep Docker).
- Platform-integrated SAST shares the pagination and auth helpers of the host SCM connector (note this in the top-of-file comment).

### Quirks

- **Operational pattern axis.** The HWM structure in `config.yml` changes between CI/CD-step (commit SHA / run ID) and periodic-global (updated-since timestamp) modes. Encode the chosen mode explicitly; do not leave it inferred.
- **CWE category.** Project the source CWE identifier alongside `rule_id` in `mapping.yml`; downstream classification depends on it.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The severity lookup MUST be exhaustive over the documented vocabulary; no gaps.
- **CLI-artefact path.** When the source is CLI-based, `config.yml` encodes the object-storage prefix (or pipeline-artefact pattern) and the SARIF / JSON format flavour. `ingest.py` uses autoloader-style ingestion via `src/platform/` helpers.
- **Rule-pack drift.** Rule IDs may shift across rule-pack versions; the dedup key embeds `rule_id` as-is. Document any source-side stability guarantees in a transform-level comment.

### Databricks-side production-shape

In addition to the eight-file core, generate-connector emits the **Databricks-side production-shape** for SAST connectors. The skill reads `operational.yml.databricks_runtime` to interpolate the templates.

The SAST `databricks_runtime` schema covers sixteen fields (twelve always-required plus four CLI-only) and is conditional on `deployment_style` (`server` or `cli_artefact`): `secret_scope`, `bronze_schema`, `bronze_tables`, `cron_schedule` (default `0 */30 * * * ?` — every 30 min for server-based; `0 */15 * * * ?` for CLI-artefact), `uc_catalog_var`, `job_name`, `default_target`, `default_catalog`, `secret_env_vars` (server: API token; CLI: artefact-bucket pointers), `tool_source_label`, `entry_wrappers` (`true` for SonarQube — emits notebook-shaped widget+secret-fetch wrappers; `false` for Semgrep), `extra_install_env_vars`. CLI-artefact-only: `bronze_volume`, `bronze_volume_storage_location`, `cli_artefact_prefixes` (e.g. `[periodic/semgrep/, cicd/semgrep/]`).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from `databricks_runtime.secret_env_vars`. For server-based deployments these are API-token entries (e.g. `SONARQUBE_URL → sonarqube_url`, `SONARQUBE_TOKEN → sonarqube_token`); for CLI-artefact deployments they are artefact-bucket pointers + optional AWS credentials (e.g. `ARTIFACT_BUCKET → semgrep_artifact_bucket`, `SEMGREP_PREFIX → semgrep_artifact_prefix`).
- **`scripts/install.sh`** — three-step end-to-end installer (load-secrets → `databricks bundle run {job_name}` → verify). Verify counts rows in each `bronze_tables` entry plus `silver.findings WHERE tool_source = '{tool_source_label}'`. Server-based deployments also enforce `extra_install_env_vars` (e.g. `SONARQUBE_HOST` alias and `SONARQUBE_ORG`).
- **Top-level `install.sh`** — orchestrator chaining `runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy`. SAST source-side runtime varies by deployment style (Helm chart for SonarQube, EKS CronJob for Semgrep).
- **`*_entry.py` notebook wrappers** — emitted **for server-based SAST** (`entry_wrappers=true`) using the SCM-shaped template (widgets + `dbutils.secrets` fetch + delegation to `src.connectors.{source}.{ingest,transform}`). The current SonarQube wrappers are scaffolding only; generate-connector emits functional wrappers, not the scaffolding shape. **N/A for CLI-artefact SAST** — Auto Loader on a UC Volume is the ingest path; `resources/job.yml` points directly at `../ingest.py`.
- **`sql/<envelope>.sql`** — N/A for SAST. Neither follower emits a `sql/` directory; bronze tables are populated directly by `ingest.py` (server) or Auto Loader (CLI). Framework metadata columns are projected inline.
- **`resources/` extras** — alongside `resources/{source}-job.yml`, SAST emits `resources/schemas.yml` (bronze only — no silver schema, unlike CMDB). CLI-artefact additionally emits `resources/volumes.yml` (REQUIRED — UC Volume of type `EXTERNAL` backing the artefact prefix at `bronze_volume_storage_location`). `resources/connection.yml` and `resources/pipeline.yml` are N/A for both sub-shapes — SAST authenticates via PAT through `dbutils.secrets`, not a UC connection, and uses the notebook-job pattern, not Lakeflow Connect.
- **Connector page §4–§7 templates** — §Secrets (table mapping `secret_key` ↔ `env_var` plus the `extra_install_env_vars` block), §Run the job (CLI-artefact path documents the operator-authored runner that drops `--json` artefacts under the configured prefix(es) before the Databricks job runs; server-based path documents the source-side scan step), §Verify (Bronze counts plus a `tool_source` filtered Silver count and severity-canonical aggregation), and §Troubleshooting category-aware entries.

*Rendered from `.claude/skills/generate-connector/references/sast.md`. Source-of-truth lives in the skill file.*

## validate-implementation: SAST reference

Facts the validate-implementation skill needs to populate the Validation table for a SAST connector. SAST sources emit code-level findings; the full ten REQ-IDs apply for server-based deployments.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The SonarQube and Semgrep columns of the traceability matrix are the authoritative per-source rows for this category. Every cell is `PASS`.

Apply (all ten; the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS`
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`: none for the server-based deployment style.

CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. Quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The same rationale applies to CLI-based SAST. Apply this N/A profile when validating a CLI-only connector.

Platform-integrated SAST (hosted inside the SCM platform): inherits the auth, pagination, and rate-limit code from the SCM connector. The SAST test suite binds only the transform / DQ / dedup REQ-IDs locally. The inherited bindings are documented in a comment, not retested.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/sast/index.md` § "Capability scope". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) and asserting that undocumented values fall through to the configured default with a data-quality warning per the catalog requirement text.

### Incremental strategy

Per `mkdocs/docs/connectors/sast/index.md` § "Capability scope": server-based uses native update-timestamp HWM; CLI-based uses commit SHA or scan-start timestamp under full reload. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against whichever mode the connector selected.

### Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/connectors/sast/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Mis-keyed `dedup_links` rows are flagged as `FAIL`.

### Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` assertions in the test suite verify the discriminator literal alongside the field projections.

### Authentication norms

PAT or API-key per `mkdocs/docs/connectors/sast/index.md` § "Capability scope". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based connectors omit this test (the path has no API auth).

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CLI-based SAST is the documented exception per `CLAUDE.md` ("Ingestion tooling preference order"). The validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

### Quirks

- **Operational pattern axis.** CI/CD-step (commit SHA / run ID) vs periodic-global (updated-since timestamp) modes are exercised by the same `REQ-ING-HWM` test against the chosen mode for the connector. The mode is fixed at `config.yml` time, not at test time.
- **CWE category projection.** `REQ-TRF-MAP` asserts that the source CWE identifier is projected alongside `rule_id`.
- **Severity vocabulary breadth.** `REQ-TRF-SEV` asserts coverage over the FULL documented vocabulary (BLOCKER…INFO, CRITICAL…LOW, or numeric scales). Gaps fail the test.
- **CLI-artefact path.** When the source is CLI-based, the auth / pagination / RL tests are absent (REQ-IDs marked `N/A`). The table summary cites the "no API auth, pagination, or rate limit" rationale from the catalog.
- **Rule-pack drift.** `REQ-DEDUP` asserts that `rule_id` is preserved as-is in the dedup key; rule-pack version drift is documented in a transform-level comment, not asserted by the test.

*Rendered from `.claude/skills/validate-implementation/references/sast.md`. Source-of-truth lives in the skill file.*
