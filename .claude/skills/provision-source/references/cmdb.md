# provision-source — cmdb reference

CMDB sources are SaaS tenants. The runtime emits an optional Terraform module that **seeds demo CMDB records** in the user's tenant via the source's REST API. There is no AWS, no Kubernetes, no IRSA — pure HTTP. Users with a populated CMDB skip the runtime.

The canonical CMDB follower is `servicenow` (see `git show a086f9d:src/connectors/servicenow/runtime/`). The provider stack is `hashicorp/http` only. Mutating writes (POSTs to the table API) go through `terraform_data` + `local-exec curl` because the ServiceNow / generic-CMDB table API does not have a first-class Terraform provider.

## operational.yml.source_runtime schema

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-saas-seed`) | yes | `terraform-saas-seed` | constant per category — CMDB has no AWS/k8s shape |
| `instance_url_var_name` | string | yes | `instance_url` | `runtime/variables.tf` first variable name |
| `admin_username_var_name` | string | yes | `admin_username` | `runtime/variables.tf` second variable name |
| `admin_password_var_name` | string | yes | `admin_password` | `runtime/variables.tf` third variable name (sensitive) |
| `seed_repo_names_default` | list[string] | no | `["BenchmarkJava", "BenchmarkPython", "juice-shop"]` | `runtime/variables.tf` `variable "seed_repo_names" { default = ... }` |
| `github_org_default` | string | no | `appsec-mvp-demo` | `runtime/variables.tf` `variable "github_org" { default = ... }` |
| `project_prefix_default` | string | no | `appsec-mvp` | `runtime/variables.tf` `variable "project_prefix" { default = ... }` |
| `business_apps` | list[object{name,criticality,repo_indices}] | no | servicenow defaults (Frontend / Backend split, indices `[0,1]` and `[2]`) | `runtime/main.tf` `locals.business_apps` |
| `table_endpoints` | list[string] | no | `["cmdb_ci_business_app", "cmdb_ci_appl", "cmdb_rel_ci"]` | `runtime/main.tf` `local-exec curl` URL patterns |
| `relationship_type` | string | no | `"Depends on::Used by"` | `runtime/main.tf` `terraform_data.app_ci` body |
| `apply_prerequisites` | list[string] | no | `["bash", "curl", "jq"]` | `runtime/README.md` "Apply prerequisites" callout |
| `terraform_required_version` | string | no | `>= 1.7` | `runtime/versions.tf` `required_version` |

## Terraform shape

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    http = { source = "hashicorp/http", version = "~> 3.4" }
  }
}
```

Note: no provider block in `main.tf` — the `http` provider needs no configuration. All mutating writes are via `terraform_data` + `local-exec curl`.

**Modules referenced:** none — all logic is inline.

**Variables exposed** (`runtime/variables.tf`):

| Name | Type | Sensitive | Required | Default |
|---|---|---|---|---|
| `instance_url` | string | no | yes | — |
| `admin_username` | string | no | yes | — |
| `admin_password` | string | yes | yes | — |
| `github_org` | string | no | no | `appsec-mvp-demo` |
| `seed_repo_names` | list(string) | no | no | `["BenchmarkJava", "BenchmarkPython", "juice-shop"]` |
| `project_prefix` | string | no | no | `appsec-mvp` |

**Outputs** (`runtime/outputs.tf`):

| Name | Description |
|---|---|
| `business_app_sysids` | Map of seeded business-app names to ServiceNow `sys_id` values (looked up via `data "http"` after the POST). |

## runtime/files/* conventions

CMDB seeders typically have **no `runtime/files/*` sidecars** — the seeded records are constructed inline in `main.tf` from `var.seed_repo_names` and the hardcoded business-app spec. If a future CMDB connector needs richer record bodies (custom CI types with templated payloads), the operator-authored sidecars would live at:

- `runtime/files/<table>/<record-template>.json` — payload templates, referenced from `main.tf` via `file("${path.module}/files/<table>/<name>.json")`.

The skill emits the `file(...)` reference but never the file content. Operator authors them out of band.

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Provisions seed CMDB records in the {source} tenant via the REST
# table API. Wraps `terraform init` + `terraform apply` against
# src/connectors/{source}/runtime/.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   {source_upper}_INSTANCE_URL   — tenant URL, e.g. https://devXXXXX.service-now.com
#   {source_upper}_ADMIN_USERNAME — service-account user with write access to
#                                   {table_endpoints joined with ", "}
#   {source_upper}_ADMIN_PASSWORD — service-account password (sensitive)
#
# Optional environment variables:
#   SEED_REPO_NAMES   — comma-separated list (default: {seed_repo_names_default joined})
#   PROJECT_PREFIX    — short slug (default: {project_prefix_default})
#
# Apply prerequisites: bash, curl, jq must all be on PATH at apply time.
# On Windows hosts, run from WSL or Git Bash.
#
# Idempotent: re-runs skip records whose triggers_replace keys are unchanged.
# Drift caused by manual edits in the {source} UI is NOT detected — taint
# the relevant terraform_data resources before re-applying if needed.

set -euo pipefail

: "${{source_upper}_INSTANCE_URL:?{source_upper}_INSTANCE_URL is required}"
: "${{source_upper}_ADMIN_USERNAME:?{source_upper}_ADMIN_USERNAME is required}"
: "${{source_upper}_ADMIN_PASSWORD:?{source_upper}_ADMIN_PASSWORD is required}"

for cmd in bash curl jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd not on PATH" >&2; exit 1; }
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

export TF_VAR_instance_url="${{source_upper}_INSTANCE_URL}"
export TF_VAR_admin_username="${{source_upper}_ADMIN_USERNAME}"
export TF_VAR_admin_password="${{source_upper}_ADMIN_PASSWORD}"
[[ -n "${SEED_REPO_NAMES:-}" ]] && export TF_VAR_seed_repo_names="[\"${SEED_REPO_NAMES//,/\",\"}\"]"
[[ -n "${PROJECT_PREFIX:-}" ]] && export TF_VAR_project_prefix="${PROJECT_PREFIX}"

cd "${SCRIPT_DIR}"
terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} CMDB seed apply complete."
echo "Outputs:"
terraform output
```

## runtime/README.md template

```markdown
# {source} connector: source system runtime (optional)

This Terraform module seeds **demo CMDB records** in the {source} tenant of the user via the {source} REST API. The {source} connector then ingests those records (the documented CMDB representation of business applications and their repository links).

**It is optional.** The {source} connector itself only needs a {source} URL and service-account credentials. Users with a populated CMDB skip this module entirely.

## When to apply

Apply this module if you want appsec-mvp to populate your {source} tenant with demo records. Skip if your CMDB is already populated. Wire the existing instance URL and service-account credentials into the connector secrets directly.

## What it creates

- {N} `{primary_table}` records (e.g. `AppSec Demo Frontend` (criticality `2 - high`) and `AppSec Demo Backend` (criticality `1 - critical`)). POSTed to `/api/now/table/{primary_table}`.
- One `{secondary_table}` record per entry in `var.seed_repo_names`. POSTed to `/api/now/table/{secondary_table}`.
- One `{relationship_table}` row per `{secondary_table}` record, linking each application CI to its parent business app via the `{relationship_type}` relationship.

The runtime is pure HTTP. No AWS, no Kubernetes, no IRSA, no IAM. It uses HTTP Basic auth on every call. Reads (sys_id lookups) go through the `http` provider. Writes go through `terraform_data` + `local-exec curl`.

> **Apply prerequisites:** the `local-exec` provisioners shell out to `bash`, `curl`, and `jq`. All three must be on the PATH of the user at apply time. On Windows hosts, run from WSL or Git Bash.

## User-supplied inputs

### Required

| Variable | Description |
|---|---|
| `instance_url` | {source} instance URL (e.g. `https://devXXXXX.service-now.com`). Must include the scheme. |
| `admin_username` | Service-account username with write access to the {table_endpoints joined with ", "} tables. |
| `admin_password` | Service-account password (sensitive). |

### Optional

| Variable | Description | Default |
|---|---|---|
| `github_org` | GitHub org that owns the seeded repos. | `{github_org_default}` |
| `seed_repo_names` | List of repo names to seed. The first two become children of one business app; the third (if present) of the other. | `{seed_repo_names_default}` |
| `project_prefix` | Tag and name prefix retained for parity with the other connector runtimes. | `{project_prefix_default}` |

> **Note on `seed_repo_names` default:** these match the seeded repos of the github runtime by coincidence, not by Terraform import. The runtimes are independent — change one, change the other, or the cross-source `silver.app_repo_mapping` join in analytics will not resolve.

## Apply

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or use the bundled `install.sh` wrapper:

```bash
export {source_upper}_INSTANCE_URL=https://devXXXXX.service-now.com
export {source_upper}_ADMIN_USERNAME=admin
export {source_upper}_ADMIN_PASSWORD=...
bash src/connectors/{source}/runtime/install.sh
```

> **Note:** the apply is not idempotent against an already-populated CMDB. Re-running `terraform apply` against the same tenant will not re-POST records whose `triggers_replace` keys are unchanged, but it also does not detect drift if records were deleted or edited in the UI between applies. Taint the relevant `terraform_data` resources before re-applying if you need a clean re-seed.

## Outputs

`business_app_sysids`. Map of seeded business-app names to their {source} `sys_id` values.

## Teardown

```bash
cd src/connectors/{source}/runtime
terraform destroy
```

> **Caveats:** the `terraform_data` resources do not have `destroy`-time provisioners. Terraform removes them from state on destroy, but the underlying CMDB records remain. Clean them up via the {source} UI or a custom DELETE script if you need a clean tenant.

## Independence

This module references only user-supplied inputs and the {source} REST API. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own provider block(s). Using it via `module "..."` from a parent module will collide with the providers of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

The optional Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) seeds **demo CMDB records** in the {source} tenant via the REST table API. It is **pure HTTP** — no AWS, no Kubernetes, no IAM. Users with an already-populated CMDB skip this entirely.

Required runtime inputs: `instance_url`, `admin_username`, `admin_password`. Optional: `seed_repo_names` (default `{seed_repo_names_default}`), `github_org` (default `{github_org_default}`), `project_prefix` (default `{project_prefix_default}`).

Apply prerequisites: `bash`, `curl`, and `jq` must be on PATH (the `local-exec` provisioners shell out to them). On Windows, run from WSL or Git Bash.

Apply with:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or wrap the apply via the bundled `install.sh`:

```bash
export {source_upper}_INSTANCE_URL=https://devXXXXX.service-now.com
export {source_upper}_ADMIN_USERNAME=admin
export {source_upper}_ADMIN_PASSWORD=...
bash src/connectors/{source}/runtime/install.sh
```

The output `business_app_sysids` echoes the seeded record sys_ids for downstream wiring. See [`src/connectors/{source}/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list and override flags.
```
