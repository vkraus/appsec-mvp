# SCA skills

Four skills cover the connector lifecycle for SCA sources. Each carries a reference specific to SCA. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: SCA reference

Facts the analyze-source skill needs to write a complete Reference section for an SCA source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SCA sources emit findings keyed by dependency.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SCA (Dependency-Track structure).
- For CLI-based SCA (package manager audit artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A. Same rationale as the SAST path for CLI artefacts.

### Default severity

`medium`. Source severity vocabularies extend up to five CVSS-aligned labels (`None`, `Low`, `Medium`, `High`, `Critical`) and some tools add a sixth `UNASSIGNED` or informational level. Lookup tables for each source at `src/connectors/{source}/severity.yml` map each value to the documented four level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data quality warning.

### Incremental strategy

Selection depends on the deployment style per the SCA capability scope:

- **Server-based SCA** (Dependency-Track) exposes paginated REST APIs with update timestamp HWM columns. This is the default mode.
- **CLI-based SCA** (package manager audits invoked in CI/CD) has no incremental hook. Treat under the full reload strategy with the commit SHA or scan start timestamp as the HWM.
- **SCA integrated into the platform** (Dependabot in GitHub) shares the auth, pagination, and incremental hook of the host SCM platform (typically webhook or `updated_at`).

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the documented SCA scope.

The Resource schema excerpt of the Reference section MUST therefore extract `package_name`, `package_version`, `ecosystem`, `cve_id`, and (where present) `purl`.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the finding table at package level).

### Authentication norms

PAT or API key based, as for SAST. SCA integrated into the platform inherits the auth of the host SCM platform (PAT or OAuth). The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SCA REST APIs work cleanly with dlt for paginated reads. CLI-based SCA uses the artefact collection pattern documented for SAST.

### Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The connector reads the source-supplied advisory linkage. Cross-source enrichment happens in Silver, not at ingestion.
- **Data centered on SBOM.** Many SCA tools are driven by SBOM (CycloneDX or SPDX). The Reference section MUST disclose whether the source emits SBOM-style outputs or finding records, since the consumed field map differs.
- **PURL availability.** Where the source emits a Package URL (`purl`), capture it. `package_name`, `package_version`, and `ecosystem` are all derivable from it for Silver normalization.
- **Operational pattern axis.** Same CI/CD step vs periodic global split as SAST. CI/CD step SCA (Dependabot alerts on PRs, Semgrep Supply Chain in pipelines) scopes findings to the scanned commit. Periodic global SCA (Dependency-Track scanning enrolled SBOMs on a schedule) scopes findings to the full SBOM inventory at scan time. Reconcile duplicates via the SCA dedup key.
- **Severity scale variation.** Some tools emit numeric CVSS scores instead of (or alongside) named labels. The Reference section MUST disclose whether the connector consumes the named label, the numeric score, or derives one from the other.

*Rendered from `.claude/skills/analyze-source/references/sca.md`. Source of truth lives in the skill file.*

## provision-source: SCA reference

Facts the provision-source skill needs to emit the source-side runtime for an SCA source. SCA tenants (Dependency-Track community-edition v4.10+ via docker on the user's dev VPC, or an existing user-run tenant) are user-provisioned out of band. The runtime is therefore a **references-only** Terraform module: it pins providers, declares user inputs, and uses `data` blocks to fail fast at plan time if the Databricks-side preconditions are missing.

### Runtime shape

`runtime_provisioner: terraform-references-only`. Provider stack: `databricks/databricks` only. There are no `resource` blocks — the runtime references but does not create the SCA tenant, the Bronze schema, or the API-key secret. The plan-time validation comes from two `data` blocks:

- `data "databricks_schema" "bronze_{source}"` — proves `${var.catalog}.bronze_{source}` exists. Created out of band by the platform-wide UC bootstrap (`databricks bundle run uc-schema-bootstrap`).
- `data "databricks_secret" "{source}_apikey"` — proves the `scope`+`key` pair exists. Populated by `scripts/load-secrets.sh`.

If either is missing at `terraform plan`, apply fails fast with a clear error before the connector job runs.

### `operational.yml.source_runtime` fields

Required: `runtime_provisioner` (always `terraform-references-only` for SCA), `tenant_host_var_name` (default `{source}_host`), `apikey_secret_scope_var_name`, `apikey_secret_key_var_name`, `bronze_schema_name` (default `bronze_{source}`), `catalog_var_name` (default `catalog`). Optional with category defaults: `tenant_host_format` (`FQDN no protocol`), `apikey_secret_scope_default` (`mvp-connectors`), `apikey_secret_key_default` (`{source}_api_key`), `terraform_required_version` (`>= 1.7`).

### Variables exposed

Required: `catalog`, `{source}_host`. Optional with defaults: `{source}_apikey_secret_scope` (`mvp-connectors`), `{source}_apikey_secret_key` (`{source}_api_key`).

### Outputs

`bronze_schema_full_name` (= `${var.catalog}.bronze_{source}`), `{source}_host`, `{source}_apikey_secret_scope`, `{source}_apikey_secret_key` — all useful for downstream `databricks secrets get-secret` calls and for the connector job's catalog/schema variables.

No `runtime/files/*` sidecars. There is nothing to overlay — the runtime only references existing Databricks objects.

### `runtime/install.sh` shape

`terraform init` + `terraform apply -auto-approve` wrapper, with TF_VAR exports for `CATALOG` (e.g. `appsec_dev`) and `{SOURCE_UPPER}_HOST` (FQDN, no protocol). Optional overrides: `{SOURCE_UPPER}_APIKEY_SECRET_SCOPE` and `{SOURCE_UPPER}_APIKEY_SECRET_KEY`.

Prerequisites: the Bronze schema must exist (`databricks bundle run uc-schema-bootstrap --target dev`); the API-key secret must be loaded (`bash scripts/load-secrets.sh`); the Databricks CLI must be authenticated.

### Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`. Body explains that the module is a references-only validation step (it does not provision an SCA tenant — that is user-provisioned via the community docker image, an existing tenant, or vendor SaaS), with the apply command as a one-liner against `catalog=appsec_dev` and `{source}_host={source}.example.com`. Notes that defaults for `{source}_apikey_secret_scope` and `{source}_apikey_secret_key` match the layout `scripts/load-secrets.sh` writes into; operators with a different secret layout override them. Operators who validate Databricks preconditions out of band (e.g. via a CI smoke test) skip the runtime entirely and proceed to **Secrets**.

### Teardown caveat (carried into the page)

The runtime references but does not own the Bronze schema or the API-key secret. `terraform destroy` removes only the references from local state — to actually delete the schema or rotate the secret, drop the schema via SQL (`DROP SCHEMA IF EXISTS ${catalog}.bronze_{source} CASCADE`) and delete the secret via `databricks secrets delete-secret <scope> <key>`. The SCA tenant is owned by the user and is never touched by Terraform.

*Rendered from `.claude/skills/provision-source/references/sca.md`. Source of truth lives in the skill file.*

## generate-connector: SCA reference

Facts the generate-connector skill needs to emit an SCA connector module. SCA sources emit package level findings keyed by dependency.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SCA (Dependency-Track structure, full ten REQ-IDs apply): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SCA (package manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. Same rationale as the SAST path for CLI artefacts. Do NOT bind these three.
- SCA integrated into the platform (Dependabot in GitHub) inherits the auth, pagination, and rate limit code of the host SCM connector. Bind only the transform, DQ, and dedup REQ-IDs locally.

### Default severity

`medium`. Generate `src/connectors/{source}/severity.yml` covering the documented source vocabulary (typically five CVSS-aligned labels: `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) mapped to the documented four level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: src/connectors/{source}/severity.yml
```

Where the source emits a numeric CVSS score instead of (or alongside) a label, encode the derivation rule in `mapping.yml` (e.g. `>= 9.0 to critical`, `>= 7.0 to high`, etc.) and document it in the connector page Quirks.

### Incremental strategy

Selection depends on deployment style. Encode in `config.yml`:

- **Server-based** (Dependency-Track): paginated REST APIs with update timestamp HWM columns. Default mode.
- **CLI-based**: full reload from CI/CD pipeline artefact storage. HWM is the commit SHA or scan start timestamp.
- **Integrated into the platform** (Dependabot): inherit the webhook or `updated_at` hook of the SCM platform.

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["package_name"], row["cve_id"])
```

The transform MUST also project `package_version`, `ecosystem`, and (where present) `purl`. The lookup table fields drive Silver normalization, but `cve_id` is the dedup anchor across SCA tools.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sca"` literally. SCA does NOT write to `silver.dependencies`. That table is fed by SBOM enrichment paths, not the dedup pipeline for findings.

### Authentication norms

PAT or API key based, as for SAST. SCA integrated into the platform inherits the auth of the host SCM connector (PAT or OAuth). `ingest.py` reads credentials via the helper in `src/platform/`. `config.yml` references the secret scope key names only.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt.

- Server-based SCA REST APIs work cleanly with dlt for paginated reads.
- CLI-based SCA uses the artefact collection pattern documented for SAST. Autoloader-style ingestion from the artefact prefix.
- SCA integrated into the platform shares the helpers of the host SCM connector.

### Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The transform reads the source-supplied advisory linkage directly into `cve_id`. Cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages, NOT here. Do NOT call NVD inline in `transform.py` for this connector.
- **Data centered on SBOM.** Sources driven by SBOM (CycloneDX, SPDX) emit records for each component. The connector flattens to finding rows in `transform.py`. The connector page identifies the format flavour.
- **PURL availability.** Where the source emits a Package URL (`purl`), project it. `package_name`, `package_version`, and `ecosystem` are all derivable from it, but the source-side fields are preferred when present.
- **Operational pattern axis.** Same CI/CD step vs periodic global split as SAST. The HWM structure in `config.yml` changes between modes. Encode explicitly.
- **Severity scale variation.** Numeric CVSS vs named labels. The severity lookup or the derivation rule in `mapping.yml` MUST cover the chosen format. Do not leave gaps.

### Databricks-side production-shape

In addition to the eight-file core, generate-connector emits the **Databricks-side production-shape** for SCA connectors. The skill reads `operational.yml.databricks_runtime` to interpolate the templates.

The SCA `databricks_runtime` schema (reverse-engineered from the Dependency-Track follower) covers thirteen fields: `secret_scope`, `bronze_schema`, `bronze_tables`, `envelope_table` (companion to the dlt-managed flattened bronze table), `cron_schedule` (default `0 0 * * * ?` — hourly), `uc_catalog_var`, `job_name` (kebab-case, e.g. `dependency-track-connector`), `default_target`, `default_catalog`, `secret_env_vars` (e.g. `DT_APIKEY → dependency_track_api_key`), `tool_source_label`, `entry_wrappers` (`false` for server-based SCA — the dlt path runs in-notebook from `ingest.py` without widget wrappers), `extra_install_env_vars` (e.g. `DT_HOST` passed as a Terraform var, not a secret).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from `databricks_runtime.secret_env_vars`. The host is supplied via the `{source}_host` Terraform variable (provision-source's territory), not via the secret scope; the script only loads the API key.
- **`scripts/install.sh`** — minimal three-step shape (load-secrets → `databricks bundle run {job_name}` → echo verify). The verify step is documented in the runbook rather than embedded in the script.
- **Top-level `install.sh`** — orchestrator chaining `runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy`. SCA source-side runtime varies (Dependency-Track self-hosted on K8s vs SaaS), driven by the operator's tenant choice.
- **`sql/<envelope>.sql`** — REQUIRED for SCA. **`CREATE TABLE`** (not `VIEW`, unlike CMDB) — dlt manages a separate flattened bronze table; the envelope is a companion table preserving the standard §2.2.2 metadata (`raw_payload`, `vuln_id_native`, `attributed_on`, `ingested_at`, `run_id`) so downstream consumers can replay the original API response without re-fetching from the source.
- **No `*_entry.py` wrappers** — `entry_wrappers=false` for server-based SCA. The dlt REST source runs in-notebook from `ingest.py`. Generate-connector emits `*_entry.py` only when `entry_wrappers=true` is explicitly set (e.g. when wiring a platform-integrated SCA that piggy-backs on an SCM source's entry wrappers).
- **`resources/` extras** — alongside `resources/{source}-job.yml` (hourly cron), SCA emits `resources/schemas.yml` (bronze only — no silver schema). `resources/connection.yml`, `resources/pipeline.yml`, and `resources/volumes.yml` are all N/A: SCA authenticates via API key through `dbutils.secrets`, runs dlt-in-notebook (not Lakeflow Connect), and is server-based with no artefact bucket.
- **Connector page §4–§7 templates** — §Secrets (table mapping `secret_key` ↔ `env_var` with the host-via-Terraform-var disclaimer), §Run the job (notebook job named `{job_name}` running on the configured cron with two tasks — `ingest` REST/dlt → Bronze and `transform` Bronze → silver.findings), §Verify (Bronze counts plus a `tool_source` AND `category='sca'` filtered Silver count grouped by `severity_canonical`), and §Troubleshooting (`401 Unauthorized` with the API-key-scope hint, 0-rows-after-success with the classifier-filter check, severity-defaulting-to-medium with the lookup-extension path).

*Rendered from `.claude/skills/generate-connector/references/sca.md`. Source of truth lives in the skill file.*

## validate-implementation: SCA reference

Facts the validate-implementation skill needs to populate the Validation table for an SCA connector. SCA sources emit findings keyed on dependencies. The full ten REQ-IDs apply for server-based deployments.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". Server-based SCA (Dependency-Track structure) tracks the same row pattern as SAST.

Apply (all ten, the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

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

CLI-based SCA (package manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. Same rationale as the SAST path for CLI artefacts, quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this N/A profile when validating a CLI-only connector.

SCA integrated into the platform (Dependabot in GitHub) inherits the auth, pagination, and rate limit code of the host SCM connector. The SCA test suite binds only the transform, DQ, and dedup REQ-IDs locally.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/sca/index.md` § "Capability scope". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented source vocabulary (typically `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) and asserting that undocumented values fall through with a data quality warning per the catalog requirement text.

### Incremental strategy

Per `mkdocs/docs/connectors/sca/index.md` § "Capability scope": server-based uses paginated REST APIs with update timestamp HWM columns. CLI-based uses commit SHA or scan start timestamp under full reload. Integrated into the platform inherits the hook of the SCM platform. The test suite asserts HWM resume behaviour under `REQ-ING-HWM` against the chosen mode of the connector.

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/connectors/sca/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. SCA does NOT write to `silver.dependencies` (that table is fed by SBOM enrichment paths, not the dedup pipeline for findings). The test suite verifies the connector targets `silver.findings` only under `REQ-TRF-MAP`.

### Authentication norms

PAT or API key per `mkdocs/docs/connectors/sca/index.md` § "Capability scope". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based and platform-integrated variants omit or inherit this test as documented above.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt. The validation suite verifies pagination and rate limit behaviour under `REQ-ING-PAG` and `REQ-ING-RL` against whichever tool the connector chose.

### Quirks

- **CVE correlation.** `REQ-TRF-MAP` asserts that the source-supplied advisory linkage is read directly into `cve_id`. Cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages and is NOT asserted by the test suite for each connector.
- **Data centered on SBOM.** Sources driven by SBOM emit records for each component. The connector flattens to finding rows. `REQ-TRF-MAP` covers the flattening assertion.
- **PURL availability.** Where the source emits a `purl`, `REQ-TRF-MAP` asserts the field is projected. `package_name`, `package_version`, `ecosystem` are derivable from PURL, but the source-side fields are preferred and asserted under the same REQ-ID.
- **Operational pattern axis.** Same CI/CD step vs periodic global split as SAST. `REQ-ING-HWM` exercises the chosen mode.
- **Severity scale variation.** Numeric CVSS vs named labels. `REQ-TRF-SEV` asserts coverage over the chosen format with no gaps.

*Rendered from `.claude/skills/validate-implementation/references/sca.md`. Source of truth lives in the skill file.*
