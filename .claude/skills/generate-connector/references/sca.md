# generate-connector — SCA reference

> **Ingestion path:** SCA sources resolve to `dlt` (server-based REST: Dependency-Track) or `artifact_path` (CLI package-manager audit). The `lakeflow_connect` branch is documented in `cmdb.md`; templates here cover the non-LFC branches.

Facts the generate-connector skill needs to emit an SCA connector module. SCA sources emit package-level findings keyed by dependency.

## Contents
- Applicable REQ-IDs
- Default severity
- Incremental strategy
- Deduplication key
- Target Silver tables
- Authentication norms
- Ingestion-tooling preference
- Quirks

## Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SCA (Dependency-Track shape; full ten REQ-IDs apply): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SCA (package-manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — same rationale as the CLI-artefact SAST path. Do NOT bind these three.
- Platform-integrated SCA (Dependabot in GitHub) inherits the host SCM connector's auth / pagination / rate-limit code; bind only the transform / DQ / dedup REQ-IDs locally.

## Default severity

`medium`. Generate `config/severity/{source}.yml` covering the documented source vocabulary (typically five CVSS-aligned labels: `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

Where the source emits a numeric CVSS score instead of (or alongside) a label, encode the derivation rule in `mapping.yml` (e.g. `>= 9.0 → critical`, `>= 7.0 → high`, etc.) and document it in the connector page Quirks.

## Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based** (Dependency-Track): paginated REST APIs with update-timestamp HWM columns. Default mode.
- **CLI-based**: full-reload from CI/CD pipeline artefact storage; HWM is the commit SHA or scan-start timestamp.
- **Platform-integrated** (Dependabot): inherit the SCM platform's webhook or `updated_at` hook.

## Deduplication key

The dedup tuple `(repository_id, package_name, cve_id)` matches the SCA capability surface at [`mkdocs/docs/connectors/sca/index.md`](../../../../mkdocs/docs/connectors/sca/index.md) § "Canonical mapping contribution" and is consistent with the canonical Silver Finding shape at [`mkdocs/docs/platform/reference/canonical-mapping.md`](../../../../mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements). Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["package_name"], row["cve_id"])
```

The transform MUST also project `package_version`, `ecosystem`, and (where present) `purl` — the lookup table fields drive Silver normalization but `cve_id` is the dedup-anchor across SCA tools.

## Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sca"` literally. SCA does NOT write to `silver.dependencies`; that table is fed by SBOM enrichment paths, not the per-finding dedup pipeline.

## Authentication norms

PAT or API-key based, as for SAST. Platform-integrated SCA inherits the host SCM connector's auth (PAT or OAuth). `ingest.py` reads credentials via the helper in `src/common/`; `config.yml` references the secret-scope key names only.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SCA REST APIs work cleanly with dlt for paginated reads.
- CLI-based SCA uses the artefact-collection pattern documented for SAST — autoloader-style ingestion from the artefact prefix.
- Platform-integrated SCA shares the host SCM connector's helpers.

## Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The transform reads the source-supplied advisory linkage directly into `cve_id`; cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages, NOT here. Do NOT call NVD inline in this connector's `transform.py`.
- **SBOM-centric data.** SBOM-driven sources (CycloneDX, SPDX) emit per-component records; the connector flattens to per-finding rows in `transform.py`. The connector page identifies the format flavour.
- **PURL availability.** Where the source emits a Package URL (`purl`), project it; `package_name`, `package_version`, and `ecosystem` are all derivable from it but the source-side fields are preferred when present.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. The `config.yml` HWM shape changes between modes; encode explicitly.
- **Severity scale variation.** Numeric CVSS vs named labels — the severity lookup or the `mapping.yml` derivation rule MUST cover the chosen format; do not leave gaps.

## operational.yml.databricks_runtime schema

Reverse-engineered from `src/connectors/dependency_track/...` (live follower; server-based SCA).

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `secret_scope` | string | yes | `mvp-connectors` | `scripts/load-secrets.sh` `SCOPE="mvp-connectors"`. |
| `bronze_schema` | string | yes | `bronze_{source}` | `resources/schemas.yml` `name: bronze_dependency_track`; `sql/sbom_envelope.sql` `${catalog}.bronze_dependency_track.findings_envelope`. |
| `bronze_tables` | list[string] | yes | (none) | `config.yml` `bronze_table: ${catalog}.bronze_dependency_track.findings`. |
| `envelope_table` | string | yes | (none) | `sql/sbom_envelope.sql` `CREATE TABLE … bronze_dependency_track.findings_envelope` — companion table to the dlt-managed bronze table. |
| `cron_schedule` | string | yes | `0 0 * * * ?` (hourly) | `resources/job.yml` `quartz_cron_expression`. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/schemas.yml` `catalog_name`. |
| `job_name` | string | yes | `{source}-connector` (kebab) | `resources/job.yml` `jobs.{job_name}`. dependency_track=`dependency-track-connector`. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `--target dev`. |
| `default_catalog` | string | no | `appsec_dev` | `scripts/install.sh` references `${CATALOG}` if set. |
| `secret_env_vars` | list[{env_var,secret_key}] | yes | (none) | `scripts/load-secrets.sh` put-secret lines. dependency_track: `(DT_APIKEY→dependency_track_api_key)`. |
| `tool_source_label` | string | yes | `{source}` | Verify-step assumption — silver.findings discriminator. |
| `entry_wrappers` | bool | yes | `false` (server SCA) | dependency_track does not emit entry wrappers; `resources/job.yml` `notebook_path: ../ingest.py`. The dlt path runs in-notebook without widget wrappers. |
| `extra_install_env_vars` | list[string] | no | (none) | `scripts/install.sh` extra `: "${VAR:?...}"`. dependency_track adds `DT_HOST` (passed as terraform var, not secret). |

13 fields.

**Judgment call:** SCA `entry_wrappers=false` is the dependency_track shape. Platform-integrated SCA (Dependabot in GitHub) inherits the SCM connector's entry wrappers — encode in `databricks_runtime` only when emitting a stand-alone SCA connector.

## Databricks-side production-shape

### scripts/load-secrets.sh template

Same shape as CMDB/SCM. dependency_track example writes only `dependency_track_api_key` from `DT_APIKEY` (host is a terraform var, not a secret).

### scripts/install.sh template

Minimal three-step shape (load-secrets → bundle run → echo verify). dependency_track current shape:

```bash
#!/usr/bin/env bash
set -euo pipefail
{% for entry in databricks_runtime.secret_env_vars %}
: "${{ '{' }}{{ entry.env_var }}:?required{{ '}' }}"
{% endfor %}
{% for v in databricks_runtime.extra_install_env_vars %}
: "${{ '{' }}{{ v }}:?required{{ '}' }}"
{% endfor %}

echo "Step 1/3: Loading secrets..."
bash src/connectors/{{ source }}/scripts/load-secrets.sh
echo "Step 2/3: Triggering pipeline..."
databricks bundle run {{ databricks_runtime.job_name }} --target {{ databricks_runtime.default_target }}
echo "Step 3/3: Run verification SQL — see runbook"
echo "✓ {{ source | title }} connector install complete."
```

### install.sh (top-level) template

Same chain as CMDB/SCM (`runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy`). SCA source-side runtime varies (Dependency-Track self-hosted on K8s vs SaaS).

### *_entry.py applicability

**N/A for server-based SCA** (dependency_track shape). The dlt REST source runs in-notebook from `ingest.py` without notebook-widget wrappers. Generate-connector should NOT emit `*_entry.py` for SCA unless `databricks_runtime.entry_wrappers=true` is explicitly set (e.g. when wiring a platform-integrated SCA that piggy-backs on an SCM source's entry wrappers).

### sql/<envelope>.sql template

REQUIRED. CREATE TABLE (not VIEW — dlt manages a separate flattened table; envelope is a companion table preserving §2.2.2 metadata).

```sql
-- Bronze envelope for {{ source }} findings.
-- Stores raw vulnerability JSON; transformed to silver.findings (category="sca")
-- via the SCA mapping.
--
-- Companion table to {{ databricks_runtime.uc_catalog_var }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.bronze_tables[0] }}
-- (the dlt-managed flattened bronze table referenced from
-- src/connectors/{{ source }}/ingest.py and config.yml). The envelope
-- preserves the section 2.2.2 raw_payload + run_id + ingested_at metadata
-- so downstream consumers can replay the original API response without
-- re-fetching from {{ source }}.

CREATE TABLE IF NOT EXISTS {{ databricks_runtime.uc_catalog_var }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }} (
  raw_payload STRING,        -- raw JSON from API
  vuln_id_native STRING,     -- vulnerability.vulnId, extracted for joinability
  attributed_on STRING,      -- ISO timestamp from attribution.attributedOn
  ingested_at TIMESTAMP,
  run_id STRING
)
USING DELTA
COMMENT 'Raw {{ source }} finding records; transformed into silver.findings (sca).';
```

### resources/extras (per category)

- `resources/job.yml` (8-file core) with `notebook_path: ../ingest.py` / `../transform.py`. Hourly cron.
- `resources/schemas.yml` — `bronze_{source}` only:

  ```yaml
  resources:
    schemas:
      {{ databricks_runtime.bronze_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.bronze_schema }}
  ```

- `resources/connection.yml` — **N/A** (API key auth via dbutils.secrets).
- `resources/pipeline.yml` — **N/A** (dlt-in-notebook, not Lakeflow Connect).
- `resources/volumes.yml` — **N/A** (server-based; no artefact bucket).

### Page §4–§7 templates

#### §Secrets (page §4)

```markdown
## Secrets

Loaded into the `{{ databricks_runtime.secret_scope }}` secret scope by `src/connectors/{{ source }}/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
{% for entry in databricks_runtime.secret_env_vars %}
| `{{ entry.secret_key }}` | `{{ entry.env_var }}` | <purpose from page §3> |
{% endfor %}

The {{ source }} host is supplied via the `{{ source }}_host` terraform variable (provision-source's territory), not via the secret scope; this script only loads the API key.

```bash
{% for entry in databricks_runtime.secret_env_vars %}
export {{ entry.env_var }}="..."
{% endfor %}
bash src/connectors/{{ source }}/scripts/load-secrets.sh
# Expected: OK: {{ source }} secrets loaded into scope {{ databricks_runtime.secret_scope }}
```
```

#### §Run the job (page §5)

```markdown
## Run the job

The {{ source }} ingestion is a notebook job named `{{ databricks_runtime.job_name }}` (declared in `src/connectors/{{ source }}/resources/job.yml`) and runs on the configured cron once enabled. Trigger an on-demand run:

```bash
databricks bundle run {{ databricks_runtime.job_name }} --target dev
```

For a one-shot orchestration:

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```

The job has two tasks: `ingest` (REST/dlt → Bronze) and `transform` (Bronze → silver.findings).
```

#### §Verify (page §6)

```markdown
## Verify

```sql
{% for tbl in databricks_runtime.bronze_tables %}
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};
{% endfor %}

SELECT severity_canonical, count(*)
  FROM {{ databricks_runtime.default_catalog }}.silver.findings
  WHERE tool_source = '{{ databricks_runtime.tool_source_label }}' AND category = 'sca'
  GROUP BY severity_canonical;
```

Expected: bronze rows after the first scheduled scan; silver rows discriminated by `tool_source` AND `category='sca'`.
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` from the {{ databricks_runtime.job_name }} job | API key wrong scope. Regenerate the team API key with at minimum VIEW_PORTFOLIO + VIEW_VULNERABILITY permissions; re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh`. |
| 0 rows in `{{ databricks_runtime.bronze_tables[0] }}` | The host has no projects matching the classifier filter, OR no recent SBOM uploads. Verify with a direct `curl` against `/api/v1/project`. |
| Severity values all default to `medium` | The CVSS-to-canonical mapping at `src/connectors/{{ source }}/severity.yml` does not cover the source's vocabulary. Inspect raw `severity` values in bronze and extend the lookup. |
```

## Ingestion-path branch: sdk

> **Status: aspirational.** No source in this category currently uses the sdk branch; templates here cover dlt and artifact_path only. Dependency-Track has an "Inofficial" `owasp-dependency-track-client` that does not meet the maintained-SDK bar, so the framework prefers `dlt`. When a future SCA source enters the analyze-source Maintained Python SDK catalogue, this section will gain the per-SDK template.
