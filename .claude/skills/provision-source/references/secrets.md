# provision-source — secrets reference

Secrets connectors follow a **CLI-artefact** runtime shape (canonical follower: `trufflehog`, `src/connectors/trufflehog/runtime/`). The scanner itself runs on CI/CD runners (or operator-existing host scan infra) and emits `--json` line-delimited output; CI uploads those artefacts to a cloud bucket (S3 / ADLS / GCS).

The runtime creates a **Unity Catalog Volume** of type `EXTERNAL` mapped to that bucket, so autoloader-style ingestion can read the JSON into `bronze_{source}.findings`. The underlying cloud bucket is **operator-provisioned in advance** (the runtime does NOT create cloud buckets). Provider stack: `databricks/databricks` only.

This is the documented pattern for CLI artefacts (CLAUDE.md §"Ingestion tooling preference order"). Scanners with no live API to call use a drop-of-artefacts-backed-by-a-Volume as the native fit.

## operational.yml.source_runtime schema

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-uc-volume`) | yes | `terraform-uc-volume` | constant per category — secrets uses CLI-artefact + UC Volume |
| `catalog_var_name` | string | yes | `catalog` | `runtime/variables.tf` first variable |
| `bronze_schema_name` | string | yes | `bronze_{source}` | `runtime/main.tf` `databricks_volume.{source}_artefacts.schema_name` |
| `volume_name` | string | yes | `artefacts` | `runtime/main.tf` `databricks_volume.{source}_artefacts.name` |
| `volume_type` | string | no | `EXTERNAL` | `runtime/main.tf` `databricks_volume.{source}_artefacts.volume_type` |
| `volume_path_var_name` | string | yes | `{source}_artifact_volume_path` | `runtime/variables.tf` |
| `bucket_provider_examples` | list[string] | no | `["S3", "ADLS", "GCS"]` | `runtime/variables.tf` description text |
| `volume_secret_scope_var_name` | string | yes | `{source}_artifact_volume_secret_scope` | `runtime/variables.tf` |
| `volume_secret_scope_default` | string | no | `mvp-connectors` | `runtime/variables.tf` `variable "...secret_scope" { default = ... }` |
| `volume_secret_key_var_name` | string | yes | `{source}_artifact_volume_secret_key` | `runtime/variables.tf` |
| `volume_secret_key_default` | string | no | `{source}_aws_credentials` | `runtime/variables.tf` `variable "...secret_key" { default = ... }` |
| `secret_blob_format` | string | no | `JSON {access_key_id, secret_access_key}` | `runtime/variables.tf` description of secret_key |
| `sample_artefact_path` | string | no | `runtime/files/sample.json` | presence of `runtime/files/sample.json` in canonical follower |
| `terraform_required_version` | string | no | `>= 1.7` | `runtime/versions.tf` |

## Terraform shape

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    databricks = { source = "databricks/databricks", version = "~> 1.50" }
  }
}
```

**Modules referenced:** none.

**Resources created:**

- `databricks_volume.{source}_artefacts` — UC Volume of type `EXTERNAL` mapped at `var.{source}_artifact_volume_path`. Lives at `<catalog>.bronze_{source}.artefacts`. Comment field documents the autoloader-style ingestion contract.

That is the only resource. **No IAM, no Kubernetes, no compute.** The cloud bucket itself is user-provisioned in advance — this runtime does not create cloud buckets.

**Variables exposed:**

| Name | Type | Sensitive | Required | Default |
|---|---|---|---|---|
| `catalog` | string | no | yes | — |
| `{source}_artifact_volume_path` | string | no | yes | — |
| `{source}_artifact_volume_secret_scope` | string | no | no | `mvp-connectors` |
| `{source}_artifact_volume_secret_key` | string | no | no | `{source}_aws_credentials` |

**Outputs:**

| Name | Description |
|---|---|
| `bronze_schema_full_name` | `<catalog>.bronze_{source}` — three-level Bronze schema name |
| `volume_path` | filesystem-style path of the UC Volume (`/Volumes/<catalog>/bronze_{source}/artefacts`) |
| `volume_full_name` | three-level UC name (`<catalog>.bronze_{source}.artefacts`) |

## runtime/files/* conventions

One operator-authored sidecar per secrets connector:

- `runtime/files/sample.json` — sanitised reference record showing the JSON shape the scanner emits (one line per finding). The README references this for downstream contract documentation. The `Raw` field of secret findings is intentionally redacted in the sample; the redaction rule is enforced at Bronze→Silver in the pipeline so the literal value never enters the connector's pipeline.

The skill emits a runtime/README.md reference to `runtime/files/sample.json` but never generates the file content. Operator authors it from a real (sanitised) scan output.

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Sub-shape: terraform-uc-volume (CLI-artefact + UC Volume).
#
# This runtime DOES NOT provision a cloud bucket. The bucket
# (S3 / ADLS / GCS) where CI runs drop {source} `--json` output is
# user-provisioned in advance.
#
# What this runtime creates: a Unity Catalog EXTERNAL Volume mapped to that
# bucket, so autoloader can read the JSON artefacts into
# bronze_{source}.findings.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG                                — Unity Catalog name (e.g. appsec_dev)
#   {source_upper}_ARTIFACT_VOLUME_PATH    — e.g. /Volumes/appsec_dev/bronze_{source}/artefacts
#
# Optional:
#   {source_upper}_ARTIFACT_VOLUME_SECRET_SCOPE — default: {volume_secret_scope_default}
#   {source_upper}_ARTIFACT_VOLUME_SECRET_KEY   — default: {volume_secret_key_default}
#
# Prerequisites:
#   - The cloud bucket exists and is reachable by the Databricks workspace.
#   - The bronze_{source} schema exists (declared by the bundle's
#     resources/schemas.yml; created by `databricks bundle deploy`).
#   - AWS / equivalent credentials with read access to the artefact bucket
#     are loaded into the Databricks secret scope
#     (`bash ../scripts/load-secrets.sh`).
#   - Databricks CLI authenticated.
#
# Idempotent: re-runs reconcile the Volume definition only.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_dev)}"
: "${{source_upper}_ARTIFACT_VOLUME_PATH:?{source_upper}_ARTIFACT_VOLUME_PATH is required}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_{source}_artifact_volume_path="${{source_upper}_ARTIFACT_VOLUME_PATH}"
[[ -n "${{source_upper}_ARTIFACT_VOLUME_SECRET_SCOPE:-}" ]] && export TF_VAR_{source}_artifact_volume_secret_scope="${{source_upper}_ARTIFACT_VOLUME_SECRET_SCOPE}"
[[ -n "${{source_upper}_ARTIFACT_VOLUME_SECRET_KEY:-}" ]] && export TF_VAR_{source}_artifact_volume_secret_key="${{source_upper}_ARTIFACT_VOLUME_SECRET_KEY}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} source-side runtime apply complete (UC Volume created)."
echo "Outputs:"
terraform output
```

## runtime/README.md template

```markdown
# {source} connector, runtime for the source system

This Terraform module provisions the **Unity Catalog Volume** that the {source} connector reads from. {source} itself is a CLI scanner that runs on CI/CD runners (or on the existing host scan infrastructure of the user) and emits JSON with one record per line. The user's CI uploads those artefacts to a cloud bucket (S3, ADLS, or GCS). This module creates the UC Volume that maps onto that bucket so autoloader can ingest the JSON into `{bronze_schema_name}.findings`.

It is the documented pattern for CLI artefacts (CLAUDE.md §"Ingestion tooling preference order"). {source} has no live API to call, so a drop of artefacts backed by a Volume is the native fit.

## Prerequisites

- A cloud storage bucket (S3, ADLS, or GCS) where CI runs drop {source} `--json` output. **Provisioned by the user in advance**. This module does not create cloud buckets.
- AWS credentials (or equivalent for ADLS or GCS) with read access to the bucket. Loaded into a Databricks secret scope via `scripts/load-secrets.sh` so Databricks Connect or autoloader can authenticate to the bucket.
- The `{bronze_schema_name}` schema in Unity Catalog. Declared by the Databricks Asset Bundle for this connector (`src/connectors/{source}/resources/schemas.yml`) and applied alongside the rest of the bundle. Apply that before this runtime, or in the same bundle deploy.

## What it creates

- A `databricks_volume` named `{volume_name}` of type `{volume_type}` under `<catalog>.{bronze_schema_name}`, with `storage_location = var.{source}_artifact_volume_path`. That is the only resource. No IAM, no Kubernetes, no compute.

## Setup

1. Export the credentials for the artefact bucket reader:

   ```bash
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   ```

2. Load them into the Databricks secret scope (idempotent — re-runs replace the value):

   ```bash
   bash src/connectors/{source}/scripts/load-secrets.sh
   ```

   The script writes a single JSON blob `{access_key_id, secret_access_key}` to scope `{volume_secret_scope_default}`, key `{volume_secret_key_default}`. Override scope or key via the `{source_upper}_ARTIFACT_VOLUME_SECRET_SCOPE` and `{source_upper}_ARTIFACT_VOLUME_SECRET_KEY` env vars.

3. Apply the runtime:

   ```bash
   cd src/connectors/{source}/runtime
   terraform init
   terraform apply \
     -var "catalog=appsec_dev" \
     -var "{source}_artifact_volume_path=/Volumes/appsec_dev/{bronze_schema_name}/{volume_name}"
   ```

   Or use the bundled `install.sh` wrapper.

4. Apply the bundle for this connector (`databricks bundle deploy --target dev`). This creates the bronze schema (if not already present) and the ingestion job that reads from the Volume.

## CI integration

The user's CI configures {source} to dump JSON to the artefact bucket. Example (S3):

```bash
{source} git --json https://github.com/<org>/<repo> > out.json
aws s3 cp out.json s3://<bucket>/{source}/<repo>/$(date -u +%FT%TZ).json
```

The expected output structure is one {source} finding per line. See `runtime/files/sample.json` for a sanitised reference record. Sensitive fields (`Raw` for secret findings) are intentionally redacted there; the redaction rule is enforced at Bronze→Silver in this connector's pipeline and the literal value never enters the pipeline.

## Inputs supplied by the user

### Required

| Variable | Description |
|---|---|
| `catalog` | Unity Catalog name. The Volume is created in `<catalog>.{bronze_schema_name}.{volume_name}`. |
| `{source}_artifact_volume_path` | UC Volume path in filesystem style (e.g. `/Volumes/appsec_dev/{bronze_schema_name}/{volume_name}`). The underlying cloud bucket must be provisioned in advance. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `{source}_artifact_volume_secret_scope` | Databricks secret scope holding the credentials of the reader for the artefact bucket. | `{volume_secret_scope_default}` |
| `{source}_artifact_volume_secret_key` | Secret key under that scope. The script loads a JSON blob `{secret_blob_format}`. | `{volume_secret_key_default}` |

## Outputs

`bronze_schema_full_name`, `volume_path`, and `volume_full_name`. Useful as inputs to downstream wiring (Lakeflow autoloader pipelines, `GRANT` statements, the Bronze→Silver job).

## Teardown

```bash
cd src/connectors/{source}/runtime
terraform destroy
```

This removes the UC Volume only. The underlying cloud bucket and any artefacts already uploaded to it are **not** managed by this module. Delete them out of band if no longer needed.

## Independence

This module references only inputs supplied by the user and the Databricks provider. It does not depend on the runtime of any other connector. The bronze schema it references is declared by this connector's bundle (`resources/schemas.yml`), not by the runtime of another connector.

This module is intended to be used as a **root** module. It declares its own `databricks` provider via `versions.tf`. Using it via `module "..."` from a parent module will collide with the providers of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

The Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) creates a **Unity Catalog `EXTERNAL` Volume** mapped to the cloud bucket where CI/CD runners drop `{source} --json` artefacts. The cloud bucket itself (S3 / ADLS / GCS) is **user-provisioned in advance**; the runtime does not create cloud buckets.

This is the canonical CLI-artefact pattern (CLAUDE.md §"Ingestion tooling preference order"): {source} has no live API, so the connector ingests via autoloader from a UC Volume backed by a drop bucket.

Required runtime inputs at a glance: `catalog`, `{source}_artifact_volume_path` (e.g. `/Volumes/appsec_dev/{bronze_schema_name}/{volume_name}`).

Apply with:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply \
  -var "catalog=appsec_dev" \
  -var "{source}_artifact_volume_path=/Volumes/appsec_dev/{bronze_schema_name}/{volume_name}"
```

Override `{source}_artifact_volume_secret_scope` / `{source}_artifact_volume_secret_key` only if your org uses a Databricks secret layout different from the defaults (`{volume_secret_scope_default}` / `{volume_secret_key_default}`).

The CI-side wiring is operator-authored. Example (S3):

```bash
{source} git --json https://github.com/<org>/<repo> > out.json
aws s3 cp out.json s3://<bucket>/{source}/<repo>/$(date -u +%FT%TZ).json
```

A sanitised sample artefact lives at [`runtime/files/sample.json`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime/files/sample.json). See [`runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list and override flags.
```
