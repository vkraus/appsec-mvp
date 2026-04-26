# servicenow connector: source system runtime (optional)

This Terraform module seeds **demo CMDB records** in the servicenow tenant of the user via the servicenow REST API. The servicenow connector then ingests those records (the documented CMDB representation of business applications and their repository links).

**It is optional.** The servicenow connector itself only needs a servicenow URL and service-account credentials. Users with a populated CMDB skip this module entirely.

## When to apply

Apply this module if you want appsec-mvp to populate your servicenow tenant with demo records. Skip if your CMDB is already populated. Wire the existing instance URL and service-account credentials into the connector secrets directly.

## What it creates

- 2 `cmdb_ci_business_app` records (e.g. `AppSec Demo Frontend` (criticality `2 - high`) and `AppSec Demo Backend` (criticality `1 - critical`)). POSTed to `/api/now/table/cmdb_ci_business_app`.
- One `cmdb_ci_appl` record per entry in `var.seed_repo_names`. POSTed to `/api/now/table/cmdb_ci_appl`.
- One `cmdb_rel_ci` row per `cmdb_ci_appl` record, linking each application CI to its parent business app via the `Depends on::Used by` relationship.

The runtime is pure HTTP. No AWS, no Kubernetes, no IRSA, no IAM. It uses HTTP Basic auth on every call. Reads (sys_id lookups) go through the `http` provider. Writes go through `terraform_data` + `local-exec curl`.

> **Apply prerequisites:** the `local-exec` provisioners shell out to `bash`, `curl`, and `jq`. All three must be on the PATH of the user at apply time. On Windows hosts, run from WSL or Git Bash.

## User-supplied inputs

### Required

| Variable | Description |
|---|---|
| `instance_url` | servicenow instance URL (e.g. `https://devXXXXX.service-now.com`). Must include the scheme. |
| `admin_username` | Service-account username with write access to the cmdb_ci_business_app, cmdb_ci_appl, cmdb_rel_ci tables. |
| `admin_password` | Service-account password (sensitive). |

### Optional

| Variable | Description | Default |
|---|---|---|
| `github_org` | GitHub org that owns the seeded repos. | `appsec-mvp-demo` |
| `seed_repo_names` | List of repo names to seed. The first two become children of one business app; the third (if present) of the other. | `["BenchmarkJava", "BenchmarkPython", "juice-shop"]` |
| `project_prefix` | Tag and name prefix retained for parity with the other connector runtimes. | `appsec-mvp` |

> **Note on `seed_repo_names` default:** these match the seeded repos of the github runtime by coincidence, not by Terraform import. The runtimes are independent — change one, change the other, or the cross-source `silver.app_repo_mapping` join in analytics will not resolve.

## Apply

```bash
cd src/connectors/servicenow/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or use the bundled `install.sh` wrapper:

```bash
export SERVICENOW_INSTANCE_URL=https://devXXXXX.service-now.com
export SERVICENOW_ADMIN_USERNAME=admin
export SERVICENOW_ADMIN_PASSWORD=...
bash src/connectors/servicenow/runtime/install.sh
```

> **Note:** the apply is not idempotent against an already-populated CMDB. Re-running `terraform apply` against the same tenant will not re-POST records whose `triggers_replace` keys are unchanged, but it also does not detect drift if records were deleted or edited in the UI between applies. Taint the relevant `terraform_data` resources before re-applying if you need a clean re-seed.

## Outputs

`business_app_sysids`. Map of seeded business-app names to their servicenow `sys_id` values.

## Teardown

```bash
cd src/connectors/servicenow/runtime
terraform destroy
```

> **Caveats:** the `terraform_data` resources do not have `destroy`-time provisioners. Terraform removes them from state on destroy, but the underlying CMDB records remain. Clean them up via the servicenow UI or a custom DELETE script if you need a clean tenant.

## Independence

This module references only user-supplied inputs and the servicenow REST API. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own provider block(s). Using it via `module "..."` from a parent module will collide with the providers of the parent.
