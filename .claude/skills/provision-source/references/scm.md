# provision-source — scm reference

SCM connectors split into two sub-shapes:

1. **References-only** (gitlab follower, `src/connectors/gitlab/runtime/`). The SCM tenant + target group/org are user-provisioned out of band (gitlab.com SaaS or self-hosted). The runtime contains no `resource` blocks — it pins providers, declares user inputs, and exports the Bronze schema name + tenant host as outputs for downstream bundle resolution. This is the default shape for SCM connectors that follow the "the user already has a tenant" pattern.

2. **Full provisioning** (github at `a086f9d:src/connectors/github/runtime/`). Provisions ECR + IAM + GitHub-Actions OIDC trust + EKS namespace + Juice Shop overlay files in a fork repo + cross-scanner CI variables. This is the heavyweight shape used when the runtime owns the cross-scanner end-to-end demo wiring.

The auto-deriver chooses the sub-shape based on whether `var.eks_cluster_name` / `aws_*` variables exist in the canonical `runtime/variables.tf` (full-provisioning) or whether only `var.catalog` + `var.{source}_token_secret_*` exist (references-only).

## operational.yml.source_runtime schema

Common fields (both sub-shapes):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-references-only`, `terraform-aws-github`) | yes | — | inferred from variable set: AWS+GitHub vars present → `terraform-aws-github`; only catalog+secret-key vars → `terraform-references-only` |
| `tenant_host` | string | yes | gitlab: `gitlab.com`; github: `github.com` | `runtime/variables.tf` `variable "{source}_host" { default = ... }` (or implicit "github.com" when omitted) |
| `target_namespace_id` | string | yes (gitlab) / no (github org-wide) | — | `runtime/variables.tf` `variable "gitlab_group_id"` / `variable "github_org"` |
| `token_secret_scope` | string | no | `mvp-connectors` | `runtime/variables.tf` `variable "{source}_token_secret_scope" { default = ... }` |
| `token_secret_key` | string | no | gitlab: `gitlab_token`; github: `github_pat` | `runtime/variables.tf` `variable "{source}_token_secret_key" { default = ... }` |
| `bronze_schema_name` | string | yes | `bronze_{source}` | `runtime/outputs.tf` `output "bronze_schema_full_name"` template literal |
| `catalog_var_name` | string | yes | `catalog` | `runtime/variables.tf` first variable name |
| `terraform_required_version` | string | no | `>= 1.7` | `runtime/versions.tf` |

Additional fields when `runtime_provisioner = terraform-aws-github` (github full-provisioning):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `aws_region` | string | yes | — | `runtime/variables.tf` `variable "aws_region"` (no default; user-supplied) |
| `eks_cluster_name_var_name` | string | yes | `eks_cluster_name` | `runtime/variables.tf` |
| `project_prefix_default` | string | no | `appsec-mvp` | `runtime/variables.tf` `variable "project_prefix" { default = ... }` |
| `juice_shop_namespace_default` | string | no | `juiceshop` | `runtime/variables.tf` `variable "juiceshop_namespace" { default = ... }` |
| `ecr_repo_name` | string | no | `${project_prefix}/juiceshop` | `runtime/main.tf` `aws_ecr_repository.juiceshop.name` |
| `oidc_audience` | string | no | `sts.amazonaws.com` | `runtime/main.tf` `aws_iam_openid_connect_provider.github` |
| `juice_shop_overlay_files` | list[string] | no | `[".sonarcloud.properties", "deploy/juiceshop.yaml"]` | `runtime/main.tf` `local.juice_shop_overlay_files` toset |
| `seed_repo_names_data_sources` | list[string] | no | `["BenchmarkJava", "BenchmarkPython", "juice-shop"]` | `runtime/main.tf` `data "github_repository"` blocks |
| `optional_cross_scanner_vars` | list[string] | no | `["sonarqube_url", "sonarqube_project_token", "zap_url", "artifact_bucket"]` | `runtime/variables.tf` optional cross-scanner block |

## Terraform shape

### Sub-shape A: references-only (gitlab pattern)

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

**Variables:** `catalog`, `{source}_host` (default `gitlab.com`), `{source}_group_id` / `{source}_org`, `{source}_token_secret_scope` (default `mvp-connectors`), `{source}_token_secret_key` (default `gitlab_token`).

**Outputs:** `bronze_schema_full_name` (= `${var.catalog}.bronze_{source}`), `{source}_host` (echoed).

**No resource blocks.** The `main.tf` is a comment-only file documenting why the runtime is structurally empty.

### Sub-shape B: full-provisioning (github pattern)

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.0" }
    github     = { source = "integrations/github", version = "~> 6.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
    tls        = { source = "hashicorp/tls", version = "~> 4.0" }
  }
}
```

**Modules referenced:** none — all resources are inline (no community-module pinning).

**Variables exposed:**

| Name | Type | Sensitive | Required | Default |
|---|---|---|---|---|
| `aws_region` | string | no | yes | — |
| `aws_access_key_id` | string | yes | yes | — |
| `aws_secret_access_key` | string | yes | yes | — |
| `project_prefix` | string | no | no | `appsec-mvp` |
| `eks_cluster_name` | string | no | yes | — |
| `github_org` | string | no | yes | — |
| `github_pat` | string | yes | yes | — |
| `juiceshop_namespace` | string | no | no | `juiceshop` |
| `sonarqube_url` | string | no | no | `""` |
| `sonarqube_project_token` | string | yes | no | `""` |
| `zap_url` | string | no | no | `""` |
| `artifact_bucket` | string | no | no | `""` |

**Resources created:**
- `aws_ecr_repository.juiceshop` — ECR for Juice Shop image pushes from CI.
- `aws_iam_openid_connect_provider.github` + `aws_iam_role.github_actions` + `aws_iam_role_policy.github_actions` — GitHub-Actions OIDC trust + IAM role for ECR push + EKS describe + (conditional) S3 artifact PUT.
- `aws_eks_access_entry.github_actions` + `aws_eks_access_policy_association.github_actions` — Cluster-admin via EKS access entries.
- `kubernetes_namespace.juiceshop` + `kubernetes_service.juiceshop` (`type = LoadBalancer`) — Juice Shop namespace and stable LB hostname (Deployment itself is applied by GH Actions).
- `data.github_repository.{benchmark_java,benchmark_python,juice_shop}` — referenced fork repos (not created).
- `github_repository_file.juice_shop_overlays` — overlays from `${path.module}/files/juice-shop/*` written into the Juice Shop fork.
- `github_actions_variable.juiceshop_vars` (conditional per-key) + `github_actions_secret.juiceshop_sonar_token` (conditional).

**Outputs:** `seed_repo_full_names`, `sast_repo_full_names`, `juice_shop_repo_full_name`, `ecr_registry_uri`, `github_actions_role_arn`, `github_actions_role_name`, `juiceshop_namespace`, `juiceshop_ingress_host`.

## runtime/files/* conventions

Sub-shape A (references-only): **no `runtime/files/*`** — nothing to overlay.

Sub-shape B (full-provisioning): operator-authored sidecars referenced by `main.tf` via `file("${path.module}/files/...")`:

- `runtime/files/juice-shop/.sonarcloud.properties` — SonarCloud project bind.
- `runtime/files/juice-shop/deploy/juiceshop.yaml` — Kubernetes Deployment manifest applied by the CI workflow (via `kubectl apply`); the runtime's `kubernetes_service.juiceshop` only reserves the LB hostname.
- `runtime/files/juice-shop/README.md` — operator notes for the Juice Shop fork.
- `runtime/files/benchmark-java/README.md`, `runtime/files/benchmark-python/README.md` — operator notes for the SAST target forks.

The skill emits `file(...)` references for every entry in `juice_shop_overlay_files`; it never emits the file contents. Operator authors them out of band (typically by checking out the originals from `git show a086f9d -- src/connectors/github/runtime/files/`).

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Wraps `terraform init` + `terraform apply` against
# src/connectors/{source}/runtime/.
#
# Sub-shape: {runtime_provisioner}
{if runtime_provisioner == terraform-references-only}
# This runtime is references-only — it pins providers, declares user inputs,
# and exports the Bronze schema name + {source} host as outputs. It does NOT
# provision a {source} tenant, group, or projects. The {source} tenant is
# user-provisioned out of band.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG                 — Unity Catalog name (e.g. appsec_dev)
#   {source_upper}_GROUP_ID — numeric {source} group/org ID
#
# Optional:
#   {source_upper}_HOST     — tenant host (default: {tenant_host})
{else if runtime_provisioner == terraform-aws-github}
# This runtime provisions:
#   - ECR repository for image pushes
#   - GitHub-Actions OIDC trust + IAM role
#   - EKS access entry granting cluster-admin to the GH-Actions role
#   - Juice Shop namespace + LoadBalancer Service (target for ZAP)
#   - GitHub repo overlays + Actions variables/secrets in the Juice Shop fork
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION                — AWS region for ECR + IAM
#   AWS_ACCESS_KEY_ID         — AWS access key (sensitive)
#   AWS_SECRET_ACCESS_KEY     — AWS secret key (sensitive)
#   EKS_CLUSTER_NAME          — EKS cluster (must be in $AWS_REGION)
#   GITHUB_ORG                — GitHub org owning the seeded repos
#   GITHUB_PAT                — GitHub PAT with org+repo admin (sensitive)
#
# Optional cross-scanner CI inputs (left empty when not running end-to-end demo):
#   SONARQUBE_URL, SONARQUBE_PROJECT_TOKEN, ZAP_URL, ARTIFACT_BUCKET
{end}
#
# Idempotent: re-runs reconcile state with the {source} side.

set -euo pipefail

{if runtime_provisioner == terraform-references-only}
: "${CATALOG:?CATALOG is required (e.g. appsec_dev)}"
: "${{source_upper}_GROUP_ID:?{source_upper}_GROUP_ID is required (numeric)}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_{source}_group_id="${{source_upper}_GROUP_ID}"
[[ -n "${{source_upper}_HOST:-}" ]] && export TF_VAR_{source}_host="${{source_upper}_HOST}"
{else if runtime_provisioner == terraform-aws-github}
: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"
: "${GITHUB_ORG:?GITHUB_ORG is required}"
: "${GITHUB_PAT:?GITHUB_PAT is required}"

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
export TF_VAR_github_org="${GITHUB_ORG}"
export TF_VAR_github_pat="${GITHUB_PAT}"
[[ -n "${SONARQUBE_URL:-}" ]] && export TF_VAR_sonarqube_url="${SONARQUBE_URL}"
[[ -n "${SONARQUBE_PROJECT_TOKEN:-}" ]] && export TF_VAR_sonarqube_project_token="${SONARQUBE_PROJECT_TOKEN}"
[[ -n "${ZAP_URL:-}" ]] && export TF_VAR_zap_url="${ZAP_URL}"
[[ -n "${ARTIFACT_BUCKET:-}" ]] && export TF_VAR_artifact_bucket="${ARTIFACT_BUCKET}"
{end}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} source-side runtime apply complete."
echo "Outputs:"
terraform output
```

## runtime/README.md template

```markdown
# {source} connector, runtime module

Terraform module that wires the {source} connector into a Databricks workspace.

{if runtime_provisioner == terraform-references-only}
Unlike the runtime for the github connector (which provisions ECR, IAM, and an EKS namespace for the end-to-end demo), the {source} connector has no resources to manage on the source side. The {source} tenant and target group are provisioned by the user out of band. This module exists for structural parity. It pins providers, declares user inputs, and exports the published Bronze schema name and {source} host so downstream bundle resources can resolve them from terraform state.
{else if runtime_provisioner == terraform-aws-github}
This runtime provisions ECR, IAM (with GitHub-Actions OIDC trust), an EKS namespace + LoadBalancer Service for the Juice Shop demo target, and writes overlay files into the user's Juice Shop fork.
{end}

## Prerequisites

- A {source} account ({tenant_host} tenant or self-hosted {source} >= recent-version).
{if runtime_provisioner == terraform-references-only}
- A group/org under your account that the connector will ingest from.
- A Personal Access Token with read scopes; recommended expiry is 90 days.
- The Unity Catalog catalog (e.g. `appsec_dev`) and the `{bronze_schema_name}` schema managed by the bundle, declared in `src/connectors/{source}/resources/schemas.yml`. Apply `databricks bundle deploy` once before the first connector run.
{else}
- An AWS account with EKS, ECR, and IAM admin permissions.
- An EKS cluster with the AWS Load Balancer Controller installed (the Juice Shop Service is `type = LoadBalancer`).
- A GitHub PAT with org + repo admin permissions.
- Forked repositories in your GitHub org for the SAST/DAST targets.
{end}

## Setup

1. Export the credentials into your shell:

   ```bash
   {if runtime_provisioner == terraform-references-only}
   export {source_upper}_TOKEN="<your-PAT>"
   {else}
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   export GITHUB_PAT=...
   {end}
   ```

2. Load secrets into Databricks Secrets:

   ```bash
   bash ../scripts/load-secrets.sh
   ```

3. Apply the terraform module:

   ```bash
   terraform init
   {if runtime_provisioner == terraform-references-only}
   terraform apply \
     -var "catalog=appsec_dev" \
     -var "{source}_group_id=<your-group-id>"
   {else}
   terraform apply -var-file=terraform.tfvars
   {end}
   ```

   Or use the bundled `install.sh` wrapper.

## Outputs

{if runtime_provisioner == terraform-references-only}
- `bronze_schema_full_name` — `catalog.{bronze_schema_name}`. Downstream bundle jobs reference this as the ingestion target.
- `{source}_host` — Echoed back for downstream bundle resolution.
{else}
- `seed_repo_full_names`, `sast_repo_full_names`, `juice_shop_repo_full_name` — full names of seeded repos.
- `ecr_registry_uri` — ECR registry for Juice Shop image pushes.
- `github_actions_role_arn` — IAM role assumed by GH-Actions via OIDC.
- `juiceshop_namespace`, `juiceshop_ingress_host` — Kubernetes / LoadBalancer wiring for ZAP scans.
{end}

## Troubleshooting

| Symptom | Fix |
|---|---|
| `databricks_secret not found` at pipeline runtime | User did not run `load-secrets.sh`. Re-run after exporting the token. |
| `401 Unauthorized` from {source} API at runtime | Token expired or has wrong scopes. Rotate the PAT and re-run `load-secrets.sh`. |
| Empty `{bronze_schema_name}` schema after pipeline run | Group/org ID may be wrong. Verify via `curl -H "PRIVATE-TOKEN: $TOKEN" https://{tenant_host}/api/v4/groups/<id>`. |
| `Schema {bronze_schema_name} does not exist` | Bundle has not been deployed yet. Run `databricks bundle deploy --target dev` before the first ingest job. |

## Independence

This module references only user-supplied inputs and the {source} / AWS / Kubernetes provider APIs. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own provider blocks. Using it via `module "..."` from a parent module will collide with the providers of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

{if runtime_provisioner == terraform-references-only}
The optional runtime under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) is a **references-only** Terraform module: it pins providers, declares the user inputs (`catalog`, `{source}_group_id`, `{source}_host`, `{source}_token_secret_scope`, `{source}_token_secret_key`), and exports the Bronze schema name and {source} host as outputs for downstream bundle resolution. **It does not provision a {source} tenant, group, projects, or seed data** — the {source} side is user-provisioned (the {source} Terraform provider supports group and project creation, but the MVP runtime intentionally stops short of that to avoid leaking demo data into the user's account).

Apply only if you want the structural-parity outputs registered in your terraform state:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply \
  -var "catalog=appsec_dev" \
  -var "{source}_group_id=$GROUP_ID"
```
{else if runtime_provisioner == terraform-aws-github}
The Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) provisions the **end-to-end-demo wiring** on the source side: ECR for Juice Shop image pushes, an IAM role with GitHub-Actions OIDC trust, an EKS namespace + LoadBalancer Service (target for ZAP), overlay files written into the Juice Shop fork, and Actions variables/secrets in the fork repo. Users with their own SCM tenant + CI wiring skip this entirely.

Required runtime inputs at a glance: `aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `eks_cluster_name`, `github_org`, `github_pat`. Optional cross-scanner inputs (left empty when not running end-to-end demo): `sonarqube_url`, `sonarqube_project_token`, `zap_url`, `artifact_bucket`.

Apply with:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```
{end}

See [`src/connectors/{source}/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list and override flags. Users with an existing {source} setup skip this step entirely and proceed to **Secrets**.
```
