# Dependency-Track connector — source-system runtime (reference-only)

This Terraform module wires the Dependency-Track connector into the operator's environment by **referencing** (not creating) the source-side Dependency-Track instance and the Databricks-side Bronze schema and API-key secret. The Dependency-Track tenant itself is operator-provisioned.

**It is optional.** The Dependency-Track connector itself only needs a host, an API key in the Databricks secret scope, and the Unity Catalog Bronze schema. Operators with an existing Dependency-Track tenant and a populated secret scope can skip this module and feed values directly into the connector job's bundle variables.

## When to apply

Apply this module if you want a Terraform-level proof at plan time that:

- the Bronze Unity Catalog schema (`${catalog}.bronze_dependency_track`) exists, and
- the Databricks secret holding the Dependency-Track API key is reachable in the configured scope and key.

Skip this module if you prefer to validate those preconditions out-of-band (e.g. via a CI smoke test).

## Prerequisites

- **Dependency-Track instance**, version 4.10 or newer. Easiest provisioning paths:
  - Run the [community docker image](https://docs.dependencytrack.org/getting-started/deploy-docker/) on a dev VPC. The compose stack ships with a default admin account; rotate it immediately.
  - Or point at an existing operator-run instance; only the host (FQDN, no protocol) and an API key are needed.
- **API key** with read access to projects, components, and findings.
  - In the Dependency-Track UI, go to **Administration → Access Management → Teams**.
  - Either select the built-in `Automation` team or create a dedicated team for the connector.
  - Assign at minimum the `VIEW_PORTFOLIO` and `VIEW_VULNERABILITY` permissions.
  - Generate / copy the team's API key.
- **Unity Catalog schema** `${catalog}.bronze_dependency_track` must exist before `terraform apply`. The platform-wide UC bootstrap (`databricks bundle run uc-schema-bootstrap --target dev`) creates it.
- **Databricks CLI** authenticated against the target workspace (this is what `scripts/load-secrets.sh` and `terraform`'s `databricks` provider both consume).

## Setup

```bash
# 1. Load the API key into the Databricks secret scope. The default scope
#    is `mvp-connectors`; the default key is `dependency_track_apikey`.
export DT_APIKEY="<paste-team-api-key>"
./src/connectors/dependency_track/scripts/load-secrets.sh

# 2. Apply the runtime — this resolves the bronze schema and the secret
#    reference, surfacing them as outputs.
cd src/connectors/dependency_track/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

A minimal `terraform.tfvars`:

```hcl
catalog               = "appsec_dev"
dependency_track_host = "dt.example.com"
# dependency_track_apikey_secret_scope and dependency_track_apikey_secret_key
# fall through to defaults (mvp-connectors / dependency_track_apikey).
```

## Operator-supplied inputs

### Required

| Variable | Description |
|---|---|
| `catalog` | Unity Catalog catalog name (e.g. `appsec_dev`). The Bronze schema `${catalog}.bronze_dependency_track` must already exist. |
| `dependency_track_host` | Dependency-Track instance host. FQDN with no protocol, e.g. `dt.example.com`. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `dependency_track_apikey_secret_scope` | Databricks secret scope holding the API key. | `mvp-connectors` |
| `dependency_track_apikey_secret_key` | Secret-key under the scope holding the API key. | `dependency_track_apikey` |

## Outputs

`bronze_schema_full_name` — fully qualified `catalog.schema` name (`${catalog}.bronze_dependency_track`); feed into the connector job's catalog/schema variables. `dependency_track_host` — echoed for parity. `dependency_track_apikey_secret_scope`, `dependency_track_apikey_secret_key` — echoed for downstream `databricks secrets get-secret` calls.

## Teardown

```bash
cd src/connectors/dependency_track/runtime
terraform destroy
```

> **Caveat:** this module references but does not own the Bronze schema or the API-key secret. `terraform destroy` removes only the references from local state. To actually delete the schema or rotate the secret, drop the schema via SQL (`DROP SCHEMA IF EXISTS ${catalog}.bronze_dependency_track CASCADE`) and delete the secret via `databricks secrets delete-secret <scope> <key>`. The Dependency-Track instance itself is operator-owned and not touched by Terraform.

## Independence

This module references only operator-supplied inputs and the Databricks provider API. It does not depend on any other connector's runtime — per the redesign's no-inter-connector-dependency rule.

This module is intended to be used as a **root** module, not a child module. It declares its own `databricks` provider block via `versions.tf`; using it via `module "..."` from a parent module will collide with the parent's providers.
