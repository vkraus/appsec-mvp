# Secrets skills

Four skills cover the connector lifecycle for Secrets sources. Each carries a reference specific to Secrets. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: Secrets reference

Facts the analyze-source skill needs to write a complete Reference section for a secret detection source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Secrets sources emit findings but with reduced lifecycle metadata.

- Apply: `REQ-ING-HWM` (full reload still has an HWM in the form of commit SHA or scan start timestamp), `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Severity is conventional rather than data driven. `REQ-TRF-SEV` applies in a degraded form (the lookup table maps detector classes to severity, defaulting to `high`).
- Do not apply: `REQ-TRF-STS`. Secret detection sources do not expose a status or lifecycle vocabulary. The documented `validity_status` field is populated from the verification flag of the source where available, but that is not a status transition graph.
- For CLI-based secret scanners (TruffleHog artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` are N/A. The catalog notes the CLI artefact ingestion path "has no API auth, pagination, or rate limit." This matches the TruffleHog traceability row.

### Default severity

`high`. The specification maps every secret finding to `severity=high` by default. A deployment level override at `src/connectors/{source}/severity.yml` is permitted for detector classes with low entropy (where false positive rates are high enough to warrant a downgrade).

The Enumerations fact in the Reference section MUST disclose that severity is conventional, not derived from the source.

### Incremental strategy

Full reload only. Per the capability scope for secrets, secret detection sources have no incremental hook. The dominant deployment style is CLI-based, collected from CI/CD pipeline artefacts. The HWM is the commit SHA (CI/CD step) or scan start timestamp (periodic global host side scans like GitHub Secret Scanning).

The Incremental hook fact in the Reference section records the full reload designation explicitly.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the documented secrets scope.

Both commit level (CI/CD step) and host side periodic global secret scanning emit records labelled with `(repository_id, commit_sha)` so that Bronze to Silver deduplication unifies them without double counting. The Reference section MUST capture both label sources where the platform supports them.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the finding table at code level). Secret-specific fields populated: `secret_type`, `validity_status` (where the source supports verification).

### Authentication norms

For server-based secret detection (rare): PAT or API key based, like SAST. For CLI-based secret detection (the dominant style, including TruffleHog): no API auth. Access is governed by the IAM policy of the artefact store. The Reference section MUST disclose which path the source takes.

### Ingestion tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. CLI-based secret scanners use the artefact collection pattern (the documented exception to the preference order, alongside Semgrep Docker). The Reference section MUST justify the deviation if the CLI path is chosen.

### Quirks

- **Verification semantics.** Where the source supports live credential verification (TruffleHog `Verified` flag, GitHub Secret Scanning `validity`), the result populates the documented `validity_status` field in Silver. The Reference section MUST disclose verification support and the field name.
- **No status transitions.** Secret findings do not have an open or resolved lifecycle in the source. The Silver `status` field is left null (or set to `open` on first emit) and `REQ-TRF-STS` does not apply.
- **CI/CD step dominance.** Secret detection is almost exclusively CI/CD step in practice. Every commit is a potential leak. The Incremental hook fact in the Reference section records the commit SHA as the operative HWM.
- **Periodic global host side scans.** Some platforms (GitHub Secret Scanning) also run periodic global scans across repository history to catch historical leaks. Both outputs are labelled with `(repository_id, commit_sha)` so dedup unifies them.
- **Detector class severity overrides.** The `src/connectors/{source}/severity.yml` lookup may downgrade specific detector classes (low entropy patterns, deprecated detectors) below the default `high`. Document the policy in the Quirks fact.

*Rendered from `.claude/skills/analyze-source/references/secrets.md`. Source of truth lives in the skill file.*

## provision-source: Secrets reference

Facts the provision-source skill needs to emit the source-side runtime for a secret detection source. Secrets connectors follow a **CLI-artefact** pattern (canonical follower: TruffleHog). The scanner itself runs on CI/CD runners (or on the operator's existing host scan infrastructure) and emits `--json` line-delimited output; CI uploads those artefacts to a cloud bucket (S3 / ADLS / GCS) **provisioned by the operator in advance**.

### Runtime shape

`runtime_provisioner: terraform-uc-volume`. Provider stack: `databricks/databricks` only. The runtime creates a single resource — a **Unity Catalog Volume** of type `EXTERNAL` at `<catalog>.bronze_{source}.artefacts`, mapped at `var.{source}_artifact_volume_path` — so autoloader-style ingestion can read the JSON into `bronze_{source}.findings`. There is no IAM, no Kubernetes, no compute; the cloud bucket is operator-provisioned out of band.

This is the documented pattern for CLI artefacts (`CLAUDE.md` §"Ingestion tooling preference order"). Scanners with no live API to call use a drop-of-artefacts-backed-by-a-Volume as the native fit.

### `operational.yml.source_runtime` fields

Required: `runtime_provisioner` (always `terraform-uc-volume` for secrets), `catalog_var_name`, `bronze_schema_name` (default `bronze_{source}`), `volume_name` (default `artefacts`), `volume_path_var_name` (default `{source}_artifact_volume_path`), `volume_secret_scope_var_name`, `volume_secret_key_var_name`. Optional with category defaults: `volume_type` (`EXTERNAL`), `bucket_provider_examples` (`["S3", "ADLS", "GCS"]`), `volume_secret_scope_default` (`mvp-connectors`), `volume_secret_key_default` (`{source}_aws_credentials`), `secret_blob_format` (`JSON {access_key_id, secret_access_key}`), `sample_artefact_path` (`runtime/files/sample.json`), `terraform_required_version` (`>= 1.7`).

### Variables exposed

Required: `catalog`, `{source}_artifact_volume_path`. Optional with defaults: `{source}_artifact_volume_secret_scope` (`mvp-connectors`), `{source}_artifact_volume_secret_key` (`{source}_aws_credentials`).

### Outputs

`bronze_schema_full_name` (= `<catalog>.bronze_{source}`), `volume_path` (filesystem-style `/Volumes/<catalog>/bronze_{source}/artefacts`), `volume_full_name` (three-level UC name `<catalog>.bronze_{source}.artefacts`).

### Operator-authored sidecar

One `runtime/files/*` reference: `runtime/files/sample.json` — a sanitised representative record showing the JSON shape the scanner emits (one line per finding). The README references it for downstream contract documentation. The `Raw` field of secret findings is intentionally redacted in the sample; the redaction rule is enforced at Bronze→Silver in the pipeline so the literal value never enters the connector's pipeline. Operator-authored — the skill emits the README reference but never the file body.

### `runtime/install.sh` shape

`terraform init` + `terraform apply -auto-approve` wrapper, with TF_VAR exports for `CATALOG` and `{SOURCE_UPPER}_ARTIFACT_VOLUME_PATH`. Optional overrides: `{SOURCE_UPPER}_ARTIFACT_VOLUME_SECRET_SCOPE` and `{SOURCE_UPPER}_ARTIFACT_VOLUME_SECRET_KEY`.

Prerequisites: the cloud bucket exists and is reachable by the Databricks workspace; the `bronze_{source}` schema exists (declared by the bundle's `resources/schemas.yml`); reader credentials with `s3:GetObject` (or equivalent) on the artefact bucket are loaded into the Databricks secret scope (`bash scripts/load-secrets.sh`); the Databricks CLI is authenticated.

### Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`. Body explains that the module creates a **Unity Catalog `EXTERNAL` Volume** mapped to the cloud bucket where CI/CD runners drop `{source} --json` artefacts, with the explicit caveat that the cloud bucket is **operator-provisioned in advance** (the runtime does not create cloud buckets). Documents the apply command (one-liner against `catalog=appsec_dev` and the `volume_path` var), the optional secret-scope/key overrides, and the CI-side wiring example (S3 `aws s3 cp`). Cross-links to `runtime/files/sample.json` for the artefact format reference.

### Teardown caveat

`terraform destroy` removes the UC Volume only. The underlying cloud bucket and any artefacts already uploaded to it are **not** managed by this module. Delete them out of band if no longer needed.

*Rendered from `.claude/skills/provision-source/references/secrets.md`. Source of truth lives in the skill file.*

## generate-connector: Secrets reference

Facts the generate-connector skill needs to emit a secret detection connector module. Secrets sources emit findings with reduced lifecycle metadata.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM` (full reload still has an HWM in the form of commit SHA or scan start timestamp), `REQ-TRF-MAP`, `REQ-TRF-SEV` (degraded, see Default severity), `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Do NOT bind `REQ-TRF-STS`. Secret detection sources do not expose a status or lifecycle vocabulary. The generated `transform.py` MUST NOT include status transition logic.
- For CLI-based scanners (TruffleHog artefacts, the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A per the catalog. Do NOT bind these three.

### Default severity

`high`, hard coded. The `mapping.yml` finding block sets severity to a literal `high` constant. It does NOT reference a lookup driven source field (this is the documented degraded form):

```yaml
severity:
  literal: high
```

The `src/connectors/{source}/severity.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# default high; per-deployment override permitted for low-entropy detector classes
```

The lookup is consulted only when an user deploys a detector level override. The default code path uses the literal `high` from `mapping.yml`.

### Incremental strategy

Full reload only. Encode in `config.yml`:

- HWM is the commit SHA (CI/CD step deployments, every commit is a potential leak) or the scan start timestamp (periodic global host side scans like GitHub Secret Scanning).
- No record level update column. The source has none.
- The HWM advances on each full pull. Replays of historical scans re-emit the same `(repository_id, commit_sha)` rows for unification at dedup time.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["commit_sha"], row["secret_type"], row["file_path"])
```

Both commit level (CI/CD step) and host side periodic global secret scanning emit records labelled with `(repository_id, commit_sha)`. Bronze to Silver dedup unifies them on the four tuple without double counting.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "secrets"` literally and project the secret-specific fields:

- `secret_type`. The detector class label (TruffleHog `DetectorName`).
- `validity_status`. Derived from the source verification flag where present (TruffleHog `Verified` + `VerificationError`). Null where the source does not verify.

The status field is NOT projected. Secrets emit no lifecycle.

### Authentication norms

- **CLI-based** (the dominant style: TruffleHog, gitleaks): no API auth. Access is governed by the IAM policy of the artefact bucket. `config.yml` encodes the bucket prefix. `ingest.py` uses the autoloader and cloud storage helpers in `src/platform/`.
- **Server-based** (rare): PAT or API key, as for SAST. `ingest.py` reads credentials via the helper in `src/platform/`.

The connector page identifies which path the source takes. Emit the matching auth code (or its absence).

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt.

- **CLI-based secret scanners are the documented exception** (alongside Semgrep Docker per `CLAUDE.md`). Emit a CLI artefact ingest path. Autoloader-style on the object storage prefix, or `httpx` against a cloud storage API. Justify the deviation in a comment at the top of the file in `ingest.py`.
- Server-based scanners use the SDK or dlt path.

### Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** For TruffleHog and similar scanners, drop the raw secret value before Bronze to Silver. Keep only `Redacted`. This is mandatory, not configurable. Encode the projection in `mapping.yml` to exclude raw fields explicitly. An optional Unity Catalog column level access policy on Bronze is the deployment time enforcement.
- **Verification semantics.** Where the source supports live credential verification, populate `validity_status` from the verification flag in `mapping.yml`. Document the source field name (e.g. `Verified` for TruffleHog) in a transform level comment.
- **No status transitions.** `REQ-TRF-STS` is N/A. Do not generate status transition code or status lookup references. The Silver `status` field is left null (or set to `open` on first emit). Encode the constant in `mapping.yml`, NOT a lookup.
- **CI/CD step dominance.** Secret detection is almost exclusively CI/CD step in practice. The HWM structure in `config.yml` is the commit SHA. Periodic global host side scans (GitHub Secret Scanning) use scan start timestamp. Both structures coexist on the four tuple dedup key.
- **Detector class severity overrides.** The optional `src/connectors/{source}/severity.yml` deployment override may downgrade specific detector classes (low entropy patterns, deprecated detectors) below the default `high`. The override path is opt-in. The default code path uses the literal in `mapping.yml`.

### Databricks-side production-shape

In addition to the eight-file core, generate-connector emits the **Databricks-side production-shape** for secrets connectors. The skill reads `operational.yml.databricks_runtime` to interpolate the templates.

The secrets `databricks_runtime` schema (reverse-engineered from the TruffleHog follower) covers fifteen fields: `secret_scope`, `bronze_schema`, `bronze_tables`, `envelope_table` (default `findings` — secrets envelope IS the bronze table; `CREATE TABLE`, not a `VIEW` overlay), `cron_schedule` (default `0 0 * * * ?` — hourly), `uc_catalog_var`, `job_name` (kebab-case), `default_target`, `default_catalog`, `secret_env_vars` (e.g. `TRUFFLEHOG_ARTIFACT_BUCKET → trufflehog_artifact_bucket`, plus a CONDITIONAL `(AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY → trufflehog_aws_credentials)` JSON-encoded blob), `optional_aws_credentials_secret` (`true` for TruffleHog — the CLI-artefact path supports BOTH S3 with credentials and UC Volume without credentials, and `load-secrets.sh` emits a conditional block driven by this flag), `tool_source_label`, `entry_wrappers` (`false` — Auto Loader on the artefact path runs in-notebook), `cli_artefact_prefixes` (default `[trufflehog/]`), `bronze_volume` (optional — TruffleHog uses a bucket-secret pointer instead of a declarative UC Volume).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from `databricks_runtime.secret_env_vars`. Emits a conditional block driven by `optional_aws_credentials_secret`: when both `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are exported (S3 path), it writes a JSON blob `{"access_key_id":"...","secret_access_key":"..."}` to `{source}_aws_credentials`; on UC Volume mode (no AWS creds) it skips that step and emits a clarifying message.
- **`scripts/install.sh`** — minimal three-step shape (load-secrets → `databricks bundle run {job_name}` → echo verify). Pre-conditions documented in the header: Phase 1 platform bootstrap complete, at least one SCM connector run so `silver.repositories` is populated, the artefact-location env var exported, and at least one scanner artefact dropped at the configured location.
- **Top-level `install.sh`** — orchestrator chaining `runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy`. Secrets source-side runtime is typically `hashicorp/aws` (S3 bucket / UC Volume) plus, for some scanners, `hashicorp/kubernetes` (CronJob).
- **`sql/<envelope>.sql`** — REQUIRED. **`CREATE TABLE`** shape: the bronze table itself. Auto Loader reads line-delimited JSON files from the UC Volume (`<catalog>.bronze_{source}.artefacts`) and lands them here with columns `raw_payload`, `artefact_path`, `ingested_at`, `run_id`. The secrets transform projects this table into `silver.findings`, dropping the `Raw` / `RawV2` fields per the redaction rule.
- **No `*_entry.py` wrappers** — `entry_wrappers=false`. The CLI-artefact path uses Auto Loader on the artefact prefix; ingest runs in-notebook from `ingest.py` directly.
- **`resources/` extras** — alongside `resources/{source}-job.yml`, secrets emits `resources/schemas.yml` (bronze only). `resources/connection.yml` is N/A (no API auth). `resources/pipeline.yml` is N/A (notebook job, not Lakeflow Connect). `resources/volumes.yml` is **optional** — emit when `bronze_volume` is set; TruffleHog currently does not emit one (uses a bucket-secret pointer), but peer CLI-artefact connectors (Semgrep) do.
- **Connector page §4–§7 templates** — §Secrets (table mapping `secret_key` ↔ `env_var` plus the conditional `{source}_aws_credentials` row when `optional_aws_credentials_secret=true`), §Run the job (operator drops `--json` artefacts under the configured prefixes, then triggers the bundle run), §Verify (Bronze count plus `tool_source` AND `category='secrets'` filtered Silver count), and §Troubleshooting (no-artefacts-at-prefix, AWS-credential-loading split between S3 and UC Volume modes, raw-field-leak failure mode for the redaction rule).

*Rendered from `.claude/skills/generate-connector/references/secrets.md`. Source of truth lives in the skill file.*

## validate-implementation: Secrets reference

Facts the validate-implementation skill needs to populate the Validation table for a secret detection connector. Secrets sources emit findings with reduced lifecycle metadata. Severity is conventional and status is N/A.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The TruffleHog column of the traceability matrix is the documented intended profile (the source is documented but not built in the MVP, so cells currently read `N/A` across the matrix. The MVP-built profile would be the set below).

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`. Degraded: severity is conventional (`high`), not data driven from a source field.
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-HWM`. N/A: full reload only. The capability scope for secrets at `mkdocs/docs/connectors/secrets/index.md` § "Capability scope" states "Such tooling has no incremental hook and SHALL be treated under the full-reload strategy." There is no record level update column to advance.
- `REQ-TRF-STS`. N/A: secret detection sources do not expose a status or lifecycle vocabulary. No status transitions exist to normalize.

For CLI-based secret scanners (TruffleHog artefacts, the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are also N/A. Quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this fuller N/A profile when validating a CLI-only connector.

Note the discrepancy with the summary table in the task spec (which lists `HWM` under "applies"). The catalog matrix and the secrets capability scope are authoritative, and both treat full reload as having no record level HWM. The `REQ-ING-HWM` from the plan could be read as the commit SHA or scan start timestamp HWM for full reload bootstrapping. If the connector encodes a commit SHA HWM in `config.yml`, bind a test asserting commit SHA advancement and mark `REQ-ING-HWM` as `PASS`. Otherwise mark it `N/A` with the rationale above.

### Default severity

`high`, conventional. Per `mkdocs/docs/connectors/secrets/index.md` § "Capability scope": "The specification maps every secret finding to `severity=high` by default; a per-deployment override is permitted for low-entropy detector classes." The `REQ-TRF-SEV` test asserts the literal `high` constant in `mapping.yml` (or, when an override lookup is deployed, the severity coverage of the override with the documented data quality warning).

### Incremental strategy

Full reload per `mkdocs/docs/connectors/secrets/index.md` § "Capability scope". The HWM is the commit SHA (CI/CD step) or scan start timestamp (periodic global host side scans like GitHub Secret Scanning). The test suite either binds `REQ-ING-HWM` against commit SHA advancement or marks it `N/A` per the discussion in Applicable REQ-IDs.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/connectors/secrets/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Commit level and host side periodic scans both label records with `(repository_id, commit_sha)`. The dedup test verifies unification without double counting.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test verifies the discriminator literal alongside the secret-specific fields (`secret_type`, `validity_status`).

### Authentication norms

CLI-based (the dominant style): no API auth. Access governed by the IAM policy of the artefact bucket. Server-based (rare): PAT or API key. The test suite binds `REQ-ING-AUTH` only when the connector takes the server-based path. CLI-only variants mark it `N/A`.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt. CLI-based secret scanners are the documented exception per `CLAUDE.md` ("Ingestion tooling preference order") alongside Semgrep Docker. The validation suite verifies the deviation through the absence of the auth, pagination, and RL tests rather than asserting a tool choice fact directly.

### Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** `REQ-TRF-MAP` asserts that raw secret values are dropped before Bronze to Silver. The projection in `mapping.yml` excludes raw fields explicitly. The test fails if a raw field is present in Silver.
- **Verification semantics.** Where the source supports verification, `REQ-TRF-MAP` asserts that `validity_status` is populated from the verification flag of the source (e.g. TruffleHog `Verified`). Sources without verification leave the field null.
- **No status transitions.** `REQ-TRF-STS` is N/A. No test is bound. The Silver `status` field is left null (or set to `open` on first emit). This constant is asserted under `REQ-TRF-MAP`, not under the omitted `REQ-TRF-STS`.
- **CI/CD step dominance.** The HWM structure of the connector is the commit SHA in practice. The test suite reflects that in `REQ-ING-HWM` (or its absence) per the discussion above.
- **Detector class severity overrides.** When a deployment level override at `src/connectors/{source}/severity.yml` is deployed, `REQ-TRF-SEV` asserts the coverage of the override and the data quality fallback. The default code path uses the `mapping.yml` literal `high` and asserts that constant.

*Rendered from `.claude/skills/validate-implementation/references/secrets.md`. Source of truth lives in the skill file.*
