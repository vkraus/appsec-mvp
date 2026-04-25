# provision-source — sca reference

SCA connectors follow a **references-only** runtime shape (canonical follower: `dependency_track`, `src/connectors/dependency_track/runtime/`). The SCA tenant itself (Dependency-Track community-edition v4.10+ via docker on the user's dev VPC, or an existing user-run tenant) is user-provisioned out of band.

The runtime references — but does not create — the Bronze schema and the Databricks secret holding the API key. The presence-check via `data "databricks_schema"` and `data "databricks_secret"` resources at plan time fails fast if either is missing, surfacing a clear error before the connector job runs. Provider stack: `databricks/databricks` only.

## operational.yml.source_runtime schema

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-references-only`) | yes | `terraform-references-only` | constant per category — SCA runtime is references-only |
| `tenant_host_var_name` | string | yes | `{source}_host` | `runtime/variables.tf` second variable name (after `catalog`) |
| `tenant_host_format` | string | no | `FQDN no protocol` | `runtime/variables.tf` `variable "{source}_host" { description }` |
| `apikey_secret_scope_var_name` | string | yes | `{source}_apikey_secret_scope` | `runtime/variables.tf` |
| `apikey_secret_scope_default` | string | no | `mvp-connectors` | `runtime/variables.tf` `variable "{source}_apikey_secret_scope" { default = ... }` |
| `apikey_secret_key_var_name` | string | yes | `{source}_apikey_secret_key` | `runtime/variables.tf` |
| `apikey_secret_key_default` | string | no | `{source}_api_key` | `runtime/variables.tf` `variable "{source}_apikey_secret_key" { default = ... }` |
| `bronze_schema_name` | string | yes | `bronze_{source}` | `runtime/main.tf` `data "databricks_schema"` name template |
| `catalog_var_name` | string | yes | `catalog` | `runtime/variables.tf` |
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

**Resources / data sources:**
- `data "databricks_schema" "bronze_{source}"` — proves `${var.catalog}.bronze_{source}` exists at plan time. Created out of band by the platform-wide UC bootstrap (`databricks bundle run uc-schema-bootstrap`).
- `data "databricks_secret" "{source}_apikey"` — proves the `scope`+`key` pair exists. Populated by `scripts/load-secrets.sh`.

**No `resource` blocks.** The runtime is purely a plan-time presence check.

**Variables exposed:**

| Name | Type | Sensitive | Required | Default |
|---|---|---|---|---|
| `catalog` | string | no | yes | — |
| `{source}_host` | string | no | yes | — |
| `{source}_apikey_secret_scope` | string | no | no | `mvp-connectors` |
| `{source}_apikey_secret_key` | string | no | no | `{source}_api_key` |

**Outputs:**

| Name | Description |
|---|---|
| `bronze_schema_full_name` | `${var.catalog}.bronze_{source}` — three-level Bronze schema name |
| `{source}_host` | echoed for downstream wiring |
| `{source}_apikey_secret_scope` | echoed for downstream `databricks secrets get-secret` calls |
| `{source}_apikey_secret_key` | echoed for downstream `databricks secrets get-secret` calls |

## runtime/files/* conventions

SCA runtimes have **no `runtime/files/*` sidecars**. There is nothing to overlay — the runtime only references existing Databricks objects.

If a future SCA connector needs a sample finding fixture for the page (e.g. `runtime/files/sample.json`), the operator authors it directly. The skill emits no references to such files unless the schema is extended.

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Sub-shape: terraform-references-only.
# This runtime DOES NOT provision a {source} tenant. The {source} instance
# (community-edition v4.10+ via docker on a dev VPC, or an existing
# user-run tenant) is user-provisioned out of band.
#
# What this script does:
#   1. Verifies the Bronze schema (${CATALOG}.bronze_{source}) exists.
#   2. Verifies the API-key Databricks secret is reachable.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG               — Unity Catalog name (e.g. appsec_dev)
#   {source_upper}_HOST   — instance host (FQDN, no protocol, e.g. dt.example.com)
#
# Optional:
#   {source_upper}_APIKEY_SECRET_SCOPE — default: {apikey_secret_scope_default}
#   {source_upper}_APIKEY_SECRET_KEY   — default: {apikey_secret_key_default}
#
# Prerequisites:
#   - The catalog and `{bronze_schema_name}` schema must exist
#     (`databricks bundle run uc-schema-bootstrap --target dev`).
#   - The API-key secret must be loaded (`bash ../scripts/load-secrets.sh`).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or
#     a configured `~/.databrickscfg` profile).
#
# Idempotent: re-runs simply re-resolve the data sources.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_dev)}"
: "${{source_upper}_HOST:?{source_upper}_HOST is required (FQDN, no protocol)}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_{source}_host="${{source_upper}_HOST}"
[[ -n "${{source_upper}_APIKEY_SECRET_SCOPE:-}" ]] && export TF_VAR_{source}_apikey_secret_scope="${{source_upper}_APIKEY_SECRET_SCOPE}"
[[ -n "${{source_upper}_APIKEY_SECRET_KEY:-}" ]] && export TF_VAR_{source}_apikey_secret_key="${{source_upper}_APIKEY_SECRET_KEY}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} source-side runtime apply complete (references-only)."
echo "Outputs:"
terraform output
```

## runtime/README.md template

```markdown
# {source} connector, runtime for the source system (reference only)

This Terraform module wires the {source} connector into the user's environment by **referencing** (not creating) the {source} instance on the source side and the Bronze schema and API-key secret on the Databricks side. The {source} tenant itself is provisioned by the user.

**It is optional.** The {source} connector itself only needs a host, an API key in the Databricks secret scope, and the Unity Catalog Bronze schema. Users with an existing tenant and a populated secret scope can skip this module and feed values directly into the bundle variables of the connector job.

## When to apply

Apply this module if you want a proof at the Terraform plan stage that:

- the Bronze Unity Catalog schema (`${catalog}.{bronze_schema_name}`) exists, and
- the Databricks secret holding the API key is reachable in the configured scope and key.

Skip this module if you prefer to validate those preconditions out of band (e.g. via a CI smoke test).

## Prerequisites

- **{source} instance**, version 4.10 or newer (or current vendor minimum). Easiest provisioning paths:
  - Run the community docker image on a dev VPC. Rotate any default admin credentials immediately.
  - Or point at an existing instance run by the user. Only the host and an API key are needed.
- **API key** with read access to projects, components, and findings (or vendor-equivalent).
- **Unity Catalog schema** `${catalog}.{bronze_schema_name}` must exist before `terraform apply`. The platform-wide UC bootstrap creates it.
- **Databricks CLI** authenticated against the target workspace.

## Setup

```bash
# 1. Load the API key into the Databricks secret scope. The default scope
#    is `{apikey_secret_scope_default}`; the default key is
#    `{apikey_secret_key_default}`.
export {source_upper}_APIKEY="<paste-team-api-key>"
./src/connectors/{source}/scripts/load-secrets.sh

# 2. Apply the runtime.
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

A minimal `terraform.tfvars`:

```hcl
catalog        = "appsec_dev"
{source}_host  = "{source}.example.com"
# {source}_apikey_secret_scope and {source}_apikey_secret_key fall through
# to defaults ({apikey_secret_scope_default} / {apikey_secret_key_default}).
```

Or use the bundled `install.sh` wrapper.

## Inputs supplied by the user

### Required

| Variable | Description |
|---|---|
| `catalog` | Unity Catalog catalog name (e.g. `appsec_dev`). The Bronze schema `${catalog}.{bronze_schema_name}` must already exist. |
| `{source}_host` | {source} instance host. FQDN with no protocol. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `{source}_apikey_secret_scope` | Databricks secret scope holding the API key. | `{apikey_secret_scope_default}` |
| `{source}_apikey_secret_key` | Secret key under the scope. | `{apikey_secret_key_default}` |

## Outputs

`bronze_schema_full_name` (= `${catalog}.{bronze_schema_name}`), `{source}_host`, `{source}_apikey_secret_scope`, `{source}_apikey_secret_key`. Useful for downstream `databricks secrets get-secret` calls and for the connector job's catalog/schema variables.

## Teardown

```bash
cd src/connectors/{source}/runtime
terraform destroy
```

> **Caveat:** this module references but does not own the Bronze schema or the API-key secret. `terraform destroy` removes only the references from local state. To actually delete the schema or rotate the secret, drop the schema via SQL (`DROP SCHEMA IF EXISTS ${catalog}.{bronze_schema_name} CASCADE`) and delete the secret via `databricks secrets delete-secret <scope> <key>`. The {source} instance itself is owned by the user and not touched by Terraform.

## Independence

This module references only user-supplied inputs and the Databricks provider API. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own `databricks` provider via `versions.tf`. Using it via `module "..."` from a parent module will collide with the providers of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

The optional Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) is a **references-only** module: it pins the `databricks/databricks` provider, declares the user inputs (`catalog`, `{source}_host`, `{source}_apikey_secret_scope`, `{source}_apikey_secret_key`), and uses `data "databricks_schema"` + `data "databricks_secret"` to fail fast at plan time if the Bronze schema or API-key secret is missing. **It does not provision a {source} tenant** — that is user-provisioned via the community docker image, an existing tenant, or vendor SaaS.

Apply only if you want plan-time validation of the Databricks-side preconditions:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply \
  -var "catalog=appsec_dev" \
  -var "{source}_host={source}.example.com"
```

Defaults for `{source}_apikey_secret_scope` (`{apikey_secret_scope_default}`) and `{source}_apikey_secret_key` (`{apikey_secret_key_default}`) match the layout the bundled `scripts/load-secrets.sh` writes into. Override only if your org uses a different secret layout.

See [`src/connectors/{source}/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list. Users who validate Databricks preconditions out of band (e.g. via a CI smoke test) skip this step entirely and proceed to **Secrets**.
```
