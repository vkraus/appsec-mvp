# ServiceNow connector: source system runtime (optional)

This Terraform module seeds **demo CMDB business app records** in the ServiceNow tenant of the user via the ServiceNow REST API. The ServiceNow connector then ingests those records (the documented CMDB representation of business applications and their repository links).

**It is optional.** The ServiceNow connector itself only needs a ServiceNow URL and service account credentials. Users with a populated CMDB skip this module entirely.

## When to apply

Apply this module if you want appsec-mvp to populate your ServiceNow tenant with demo business app records. Skip if your CMDB is already populated. Wire the existing instance URL and service account credentials into the ServiceNow connector secrets directly.

## What it creates

- Two `cmdb_ci_business_app` records: `AppSec Demo Frontend` (criticality `2 - high`) and `AppSec Demo Backend` (criticality `1 - critical`). POSTed to `/api/now/table/cmdb_ci_business_app`.
- One `cmdb_ci_appl` record per entry in `var.seed_repo_names` (default 3), POSTed to `/api/now/table/cmdb_ci_appl`. The first two repos are children of `AppSec Demo Frontend`. The third (if present) is a child of `AppSec Demo Backend`.
- One `cmdb_rel_ci` row per `cmdb_ci_appl` record, linking each application CI to its parent business app via the `Depends on::Used by` relationship.

The runtime is pure HTTP. No AWS, no Kubernetes, no IRSA, no IAM. It uses HTTP Basic auth (`var.admin_username` and `var.admin_password`) on every call. Reads (sys_id lookups) go through the `http` provider. Writes (POSTs to the table API) go through `terraform_data` and `local-exec curl` because the ServiceNow table API does not have a first class Terraform provider. `curl` is the native pattern for seeding records.

> **Apply prerequisites:** the `local-exec` provisioners shell out to `bash`, `curl`, and `jq`. All three must be on the PATH of the user at apply time. On Windows hosts, run from WSL or Git Bash.

## User supplied inputs

### Required

| Variable | Description |
|---|---|
| `instance_url` | ServiceNow instance URL (e.g. `https://devXXXXX.service-now.com`). Must include the scheme. |
| `admin_username` | ServiceNow service account username with write access to the `cmdb_ci_business_app`, `cmdb_ci_appl`, and `cmdb_rel_ci` tables. |
| `admin_password` | Service account password (sensitive). |

### Optional

| Variable | Description | Default |
|---|---|---|
| `github_org` | GitHub org that owns the seeded repos. The source module declared this variable but did not consume it in the CMDB record bodies. Preserved for forward compatibility. | `appsec-mvp-demo` |
| `seed_repo_names` | List of repo names to seed as CMDB application records. The first two become children of `AppSec Demo Frontend`. The third (if present) becomes a child of `AppSec Demo Backend`. | `["BenchmarkJava", "BenchmarkPython", "juice-shop"]` |
| `project_prefix` | Tag and name prefix retained for parity with the other connector runtimes. Not currently consumed. CMDB record names are hardcoded. | `appsec-mvp` |

> **Note on `seed_repo_names` default:** the values match the seeded repos of the github runtime **by coincidence**, not by Terraform import. The two runtimes are independent. There is no module level reference between them, per the no inter connector dependency rule of the redesign. If you change the names in one runtime, change them in the other. Otherwise the cross-source `silver.app_repo_mapping` join in analytics will not resolve.

## Apply

```bash
cd src/connectors/servicenow/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Users write their own `terraform.tfvars`. The legacy `infra/terraform/terraform.tfvars.example` can serve as a starting reference for the ServiceNow credentials block.

> **Note:** the apply is not idempotent against an already populated CMDB. Re-running `terraform apply` against the same tenant will not re-POST records whose `triggers_replace` keys are unchanged (Terraform skips them), but it also does not detect drift if records were deleted or edited in the ServiceNow UI between applies. The `data "http"` sys_id lookup will surface a stale state. If the seeded records were modified manually, taint the relevant `terraform_data.business_app` and `terraform_data.app_ci` resources before re-applying.

## Outputs

`business_app_sysids`. Map of seeded business app names (`AppSec Demo Frontend`, `AppSec Demo Backend`) to their ServiceNow `sys_id` values, as returned by the table API lookup that runs after the POST. Useful for wiring downstream automation that needs to reference the seeded records.

## Teardown

```bash
cd src/connectors/servicenow/runtime
terraform destroy
```

> **Caveats:** the `terraform_data` resources do not have `destroy`-time provisioners. Terraform removes them from state on destroy, but the underlying CMDB records in ServiceNow remain. Clean them up via the ServiceNow UI (or a custom DELETE script against `/api/now/table/cmdb_ci_business_app/{sys_id}` and `/api/now/table/cmdb_ci_appl/{sys_id}`) if you need a clean tenant. This matches the behavior of the source module.

## Independence

This module references only user supplied inputs and the ServiceNow REST API. It does not depend on the runtime of any other connector, per the no inter connector dependency rule of the redesign. The cross-runtime reference that previously came from `github_seed.seed_repo_names` (in the pre-redesign root module under `infra/terraform/main.tf`) becomes the user supplied `var.seed_repo_names`. Specifically, the `seed_repo_names` default is **hardcoded demo data** that matches the github runtime defaults by coincidence. There is no Terraform level import.

This module is intended to be used as a **root** module, not a child module. It declares its own provider block(s). Using it via `module "..."` from a parent module will collide with the providers of the parent.
