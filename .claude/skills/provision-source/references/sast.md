# provision-source — sast reference

SAST connectors split into two sub-shapes:

1. **Server-based** (sonarqube follower, `src/connectors/sonarqube/runtime/`). Deploys a SonarQube Helm release on EKS, optionally provisions a dedicated RDS Postgres backing store, exposes the Sonar UI via a LoadBalancer Service. Provider stack: `aws` + `kubernetes` + `helm` + `random`. Users on SonarCloud skip the runtime entirely.

2. **CLI-artefact** (semgrep follower at `a086f9d:src/connectors/semgrep/runtime/`). Deploys a Semgrep CronJob on EKS that periodically clones a list of git repositories, runs `semgrep scan`, and writes JSON findings to an S3 artifact bucket via IRSA. Provider stack: `aws` + `kubernetes`. Users with an existing scanner skip the runtime.

The auto-deriver chooses the sub-shape based on whether `runtime/main.tf` contains `helm_release` (server-based) or `kubernetes_cron_job_v1` + IRSA resources (CLI-artefact).

## operational.yml.source_runtime schema

Common fields (both sub-shapes — both shapes use AWS+EKS):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-aws-eks-helm`, `terraform-aws-eks-cronjob`) | yes | — | inferred from `runtime/main.tf`: presence of `helm_release` → `terraform-aws-eks-helm`; presence of `kubernetes_cron_job_v1` → `terraform-aws-eks-cronjob` |
| `aws_region_var_name` | string | yes | `aws_region` | `runtime/variables.tf` |
| `eks_cluster_name_var_name` | string | yes | `eks_cluster_name` | `runtime/variables.tf` |
| `project_prefix_default` | string | no | `appsec-mvp` | `runtime/variables.tf` `variable "project_prefix" { default = ... }` |
| `namespace_default` | string | no | sonarqube: `sonarqube`; semgrep: `semgrep` | `runtime/variables.tf` `variable "{source}_namespace" / "namespace_name" { default = ... }` |
| `terraform_required_version` | string | no | `>= 1.7` | `runtime/versions.tf` |

Additional fields when `runtime_provisioner = terraform-aws-eks-helm` (sonarqube server-based):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `helm_chart_repository` | string | yes | `https://SonarSource.github.io/helm-chart-sonarqube` | `runtime/main.tf` `helm_release.{source}.repository` |
| `helm_chart_name` | string | yes | `sonarqube` | `runtime/main.tf` `helm_release.{source}.chart` |
| `helm_chart_version_default` | string | yes | `10.6.1+2742` | `runtime/variables.tf` `variable "{source}_chart_version" { default = ... }` |
| `service_port` | number | no | `9000` | `runtime/main.tf` exposed port (or `data.kubernetes_service` lookup) |
| `helm_timeout_seconds` | number | no | `900` | `runtime/main.tf` `helm_release.{source}.timeout` |
| `admin_password_var_name` | string | yes | `{source}_admin_password` | `runtime/variables.tf` (sensitive) |
| `rds_engine_version_default` | string | no | `15` | `runtime/variables.tf` `variable "rds_engine_version"` |
| `rds_instance_class_default` | string | no | `db.t3.small` | `runtime/variables.tf` `variable "rds_instance_class"` |
| `rds_allocated_storage_default` | number | no | `20` | `runtime/variables.tf` `variable "rds_allocated_storage"` |
| `rds_db_name_default` | string | no | `sonar` | `runtime/variables.tf` `variable "rds_db_name"` |
| `rds_username_default` | string | no | `sonar` | `runtime/variables.tf` `variable "rds_username"` |
| `rds_parameter_group_family_default` | string | no | `postgres15` | `runtime/variables.tf` `variable "rds_parameter_group_family"` |
| `rds_optional` | bool | no | `true` | conditional creation gated on `var.rds_endpoint == ""` in `runtime/main.tf` `locals.create_rds` |
| `analysis_token_length` | number | no | `40` | `runtime/main.tf` `random_password.{source}_token.length` |

Additional fields when `runtime_provisioner = terraform-aws-eks-cronjob` (semgrep CLI-artefact):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `eks_oidc_provider_arn_var_name` | string | yes | `eks_cluster_oidc_provider_arn` | `runtime/variables.tf` |
| `artifact_bucket_var_name` | string | yes | `artifact_bucket` | `runtime/variables.tf` |
| `cron_schedule_default` | string | no | `0 */6 * * *` | `runtime/variables.tf` `variable "cron_schedule" { default = ... }` |
| `scanner_image_default` | string | yes | `returntocorp/semgrep:latest` | `runtime/variables.tf` `variable "{source}_image" { default = ... }` |
| `repo_urls_default` | list[string] | no | `["owasp/juice-shop"]` | `runtime/variables.tf` `variable "repo_urls" { default = ... }` |
| `scan_script_path` | string | yes | `files/{source}-scan.sh` | `runtime/main.tf` `kubernetes_config_map` `data["scan.sh"] = file(...)` |
| `irsa_s3_actions` | list[string] | no | `["s3:PutObject", "s3:GetObject", "s3:ListBucket"]` | `runtime/main.tf` `data.aws_iam_policy_document.irsa_policy` |
| `irsa_service_account_name` | string | yes | `{source}` | `runtime/main.tf` `kubernetes_service_account` metadata.name |
| `env_secret_keys` | list[string] | yes | `["ARTIFACT_BUCKET", "SCANNER_REPO_LIST", "AWS_REGION", "GH_PAT"]` | `runtime/main.tf` `kubernetes_secret.{source}_env.data` keys |
| `clone_token_var_name` | string | yes | `github_pat_for_clone` | `runtime/variables.tf` (sensitive) |

## Terraform shape

### Sub-shape A: server-based (sonarqube pattern)

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
    helm       = { source = "hashicorp/helm", version = "~> 2.13" }
    random     = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
```

**Modules referenced:** none — RDS + subnet group + security group + parameter group are inline (deliberately free of community-module pinning).

**Resources (server-based):**
- `data.aws_eks_cluster` + `data.aws_eks_cluster_auth` — EKS auth handoff for the kubernetes/helm providers.
- `terraform_data.input_validation` — preconditions enforcing the `rds_endpoint` cross-variable contract.
- (Conditional) `random_password.rds`, `aws_db_subnet_group.{source}`, `aws_security_group.rds`, `aws_db_parameter_group.{source}`, `aws_db_instance.{source}` — RDS provisioning when `var.rds_endpoint == ""`.
- `kubernetes_namespace.{source}`, `kubernetes_secret.{source}_db` (JDBC), `helm_release.{source}` (timeout 900s), `data.kubernetes_service.{source}` — the Sonar Helm release.
- `random_password.{source}_token` — long-lived analysis token (the Helm chart does not support declarative token creation).

**Outputs:** `{source}_url` (LoadBalancer hostname:port), `{source}_namespace`, `{source}_db_secret_name`, `{source}_project_token` (sensitive), `rds_endpoint`, `rds_db_name`, `rds_username`, `rds_password` (sensitive).

### Sub-shape B: CLI-artefact (semgrep pattern)

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
  }
}
```

**Modules referenced:** none — IRSA is inlined as raw IAM resources rather than the community `terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks` module.

**Resources (CLI-artefact):**
- `data.aws_eks_cluster` + `data.aws_eks_cluster_auth` — EKS auth handoff.
- `terraform_data.input_validation` — preconditions on `artifact_bucket`, `repo_urls`, `eks_cluster_oidc_provider_arn`, `github_pat_for_clone`.
- `data.aws_iam_policy_document.irsa_assume` + `aws_iam_role.{source}` + `data.aws_iam_policy_document.irsa_policy` + `aws_iam_role_policy.{source}` — IRSA trust + S3 PutObject/GetObject/ListBucket policy on the artifact bucket.
- `kubernetes_namespace.{source}`, `kubernetes_service_account.{source}` (with IRSA annotation), `kubernetes_config_map.{source}_script` (loads `files/{source}-scan.sh`), `kubernetes_secret.{source}_env`, `kubernetes_cron_job_v1.{source}`.

**Outputs:** `{source}_namespace`, `{source}_cronjob_name`, `{source}_irsa_role_arn`, `{source}_env_secret_name`.

## runtime/files/* conventions

Sub-shape A (server-based, sonarqube): **no `runtime/files/*`** by default — Helm chart drives all configuration via `values = [yamlencode({...})]`. If an operator wants a custom Helm `values.yaml` overlay, it would live at `runtime/files/values.yaml` and be merged via `values = [yamlencode({...}), file("${path.module}/files/values.yaml")]`. The skill emits the `file(...)` reference but never the content.

Sub-shape B (CLI-artefact, semgrep): one operator-authored sidecar:

- `runtime/files/{source}-scan.sh` — driver script loaded into the ConfigMap and mounted into the CronJob pod at `/scripts/scan.sh`. Performs `git clone` of each repo in `$SCANNER_REPO_LIST`, runs `semgrep scan --json`, uploads JSON to `s3://${ARTIFACT_BUCKET}/periodic/{source}/<repo>/<timestamp>.json`. The script enforces `${GH_PAT:?set GH_PAT}` and clones via `https://x-access-token:${GH_PAT}@github.com/${slug}.git`. Operator-authored — the skill emits the `file("${path.module}/files/{source}-scan.sh")` reference but never the script content.

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Sub-shape: {runtime_provisioner}
#
# Wraps `terraform init` + `terraform apply` against
# src/connectors/{source}/runtime/.
{if runtime_provisioner == terraform-aws-eks-helm}
#
# This runtime deploys {source} as a Helm release on EKS, optionally with a
# dedicated RDS Postgres backing store, exposed via a LoadBalancer Service.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION                — must match the region of $EKS_CLUSTER_NAME
#   AWS_ACCESS_KEY_ID         — sensitive
#   AWS_SECRET_ACCESS_KEY     — sensitive
#   EKS_CLUSTER_NAME          — EKS cluster where {source} is installed
#   {source_upper}_ADMIN_PASSWORD — initial admin web-UI password (sensitive)
#
# Optional (when this module creates the RDS backing store, i.e. RDS_ENDPOINT empty):
#   VPC_ID, VPC_SUBNET_IDS (comma-sep), VPC_CIDR_BLOCK
# Optional (when targeting an existing Postgres):
#   RDS_ENDPOINT, RDS_USERNAME, RDS_PASSWORD
{else if runtime_provisioner == terraform-aws-eks-cronjob}
#
# This runtime deploys a {source} CronJob on EKS that periodically clones a
# list of git repos, runs the bundled scan script, and writes JSON findings
# to an S3 artifact bucket via IRSA.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION                       — must match the region of $EKS_CLUSTER_NAME
#   AWS_ACCESS_KEY_ID                — sensitive
#   AWS_SECRET_ACCESS_KEY            — sensitive
#   EKS_CLUSTER_NAME                 — EKS cluster where the CronJob runs
#   EKS_CLUSTER_OIDC_PROVIDER_ARN    — for the IRSA trust policy
#   ARTIFACT_BUCKET                  — S3 bucket name for JSON output
#   GITHUB_PAT_FOR_CLONE             — PAT for cloning target repos (sensitive)
#
# Optional:
#   REPO_URLS                  — comma-separated org/repo slugs (default: {repo_urls_default})
#   CRON_SCHEDULE              — default: {cron_schedule_default}
{end}
#
# Idempotent: re-runs reconcile state with the AWS / EKS side.

set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"
{if runtime_provisioner == terraform-aws-eks-helm}
: "${{source_upper}_ADMIN_PASSWORD:?{source_upper}_ADMIN_PASSWORD is required}"
{else if runtime_provisioner == terraform-aws-eks-cronjob}
: "${EKS_CLUSTER_OIDC_PROVIDER_ARN:?EKS_CLUSTER_OIDC_PROVIDER_ARN is required}"
: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
: "${GITHUB_PAT_FOR_CLONE:?GITHUB_PAT_FOR_CLONE is required}"
{end}

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
{if runtime_provisioner == terraform-aws-eks-helm}
export TF_VAR_{source}_admin_password="${{source_upper}_ADMIN_PASSWORD}"
[[ -n "${RDS_ENDPOINT:-}" ]] && export TF_VAR_rds_endpoint="${RDS_ENDPOINT}"
[[ -n "${RDS_USERNAME:-}" ]] && export TF_VAR_rds_username="${RDS_USERNAME}"
[[ -n "${RDS_PASSWORD:-}" ]] && export TF_VAR_rds_password="${RDS_PASSWORD}"
[[ -n "${VPC_ID:-}" ]] && export TF_VAR_vpc_id="${VPC_ID}"
[[ -n "${VPC_SUBNET_IDS:-}" ]] && export TF_VAR_vpc_subnet_ids="[\"${VPC_SUBNET_IDS//,/\",\"}\"]"
[[ -n "${VPC_CIDR_BLOCK:-}" ]] && export TF_VAR_vpc_cidr_block="${VPC_CIDR_BLOCK}"
{else if runtime_provisioner == terraform-aws-eks-cronjob}
export TF_VAR_eks_cluster_oidc_provider_arn="${EKS_CLUSTER_OIDC_PROVIDER_ARN}"
export TF_VAR_artifact_bucket="${ARTIFACT_BUCKET}"
export TF_VAR_github_pat_for_clone="${GITHUB_PAT_FOR_CLONE}"
[[ -n "${REPO_URLS:-}" ]] && export TF_VAR_repo_urls="[\"${REPO_URLS//,/\",\"}\"]"
[[ -n "${CRON_SCHEDULE:-}" ]] && export TF_VAR_cron_schedule="${CRON_SCHEDULE}"
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
# {source} connector: source system runtime (optional)

{if runtime_provisioner == terraform-aws-eks-helm}
This Terraform module deploys the **{source} server** that the {source} connector ingests from. It runs {source} on the user-supplied EKS cluster and either creates a dedicated RDS Postgres database for the backing store or uses a user-supplied one.
{else if runtime_provisioner == terraform-aws-eks-cronjob}
This Terraform module deploys the **{source} CronJob** that periodically clones a list of git repositories, runs `{source} scan`, and writes JSON findings to a user-supplied S3 bucket. The {source} connector then ingests those findings from S3.
{end}

**It is optional.** The {source} connector itself only needs {if helm}a server URL and analysis token{else}an S3 prefix to read findings from{end}. Users with their own {source} deployment skip this module entirely.

## When to apply

Apply this module if you want appsec-mvp to provision {source} end-to-end. Skip it if you have your own {source} tenant.

## What it creates

{if runtime_provisioner == terraform-aws-eks-helm}
- A {source} Helm release in the `{namespace_default}` Kubernetes namespace, exposed via a LoadBalancer Service on port {service_port}.
- A `{source}-db` Kubernetes Secret holding the JDBC connection string.
- (Optional, when `rds_endpoint` is empty) A dedicated RDS Postgres instance ({rds_instance_class_default}, {rds_allocated_storage_default} GiB, Postgres {rds_engine_version_default}, encrypted at rest, no PITR backups), a custom DB parameter group ({rds_parameter_group_family_default}), DB subnet group, security group on port 5432, and a random 32-character password.
- A {analysis_token_length}-character random opaque value emitted as `{source}_project_token` for use as the project analysis token (the Helm chart does not support declarative token creation).
{else if runtime_provisioner == terraform-aws-eks-cronjob}
- A `{namespace_default}` Kubernetes namespace and service account on your EKS cluster, with an IRSA annotation pointing at the IAM role this module mints.
- An IAM role assumable by the `{irsa_service_account_name}` service account via IRSA, granted `{irsa_s3_actions joined}` on `var.artifact_bucket`.
- A ConfigMap holding the bundled `{source}-scan.sh` driver script.
- A Secret holding the runtime env vars: {env_secret_keys joined}.
- A CronJob that runs the script on a fixed schedule (default: `{cron_schedule_default}`).
{end}

## User-supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region of the EKS cluster. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where {source} runs. |
{if helm}
| `{source}_admin_password` | Initial admin web-UI password (sensitive). |
{else}
| `eks_cluster_oidc_provider_arn` | ARN of the IAM OIDC provider associated with the cluster. Required for the IRSA trust policy. |
| `artifact_bucket` | S3 bucket name where the CronJob writes findings JSON. |
{end}

### Optional

(See `variables.tf` for the full list including {if helm}RDS tunables, namespace, chart version{else}repo list, scanner image, cron schedule, GitHub PAT for cloning{end}.)

## Apply

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or use the bundled `install.sh` wrapper.

## Outputs

{if helm}
`{source}_url`, `{source}_namespace`, `{source}_project_token` (sensitive), `rds_endpoint`, `rds_db_name`, `rds_username`, `rds_password` (sensitive).
{else}
`{source}_namespace`, `{source}_cronjob_name`, `{source}_irsa_role_arn`, `{source}_env_secret_name`.
{end}

## Teardown

```bash
cd src/connectors/{source}/runtime
terraform destroy
```

{if helm}
> **Warning:** RDS is created with `skip_final_snapshot = true` and `deletion_protection = false`, with `backup_retention_period = 0`. Running `terraform destroy` permanently loses all {source} data. Take a manual snapshot first if needed.
{else}
> **Caveat:** if a scan pod is mid-scan when destroy runs, it gets terminated and the in-flight findings in the `emptyDir` volume are lost. Wait for the most recent Job to complete before destroying. The IRSA role only has permissions on `var.artifact_bucket` and `${var.artifact_bucket}/*`; previously uploaded findings remain in the bucket after teardown.
{end}

## Independence

This module references only user-supplied inputs and the AWS, Kubernetes{if helm}, and Helm{end} provider APIs. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own provider blocks. Using it via `module "..."` from a parent module will collide with the providers of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

{if runtime_provisioner == terraform-aws-eks-helm}
The Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) provisions **{source} Server** as a Helm release on an existing EKS cluster, optionally backed by an RDS Postgres {rds_engine_version_default} instance ({rds_instance_class_default}, {rds_allocated_storage_default} GiB, encrypted at rest), and exposed via a LoadBalancer Service on port {service_port}. Users on the SaaS edition skip this entirely. Users wanting self-hosted apply the runtime — see [`src/connectors/{source}/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list, the RDS endpoint precondition, and the generated outputs.

Required runtime inputs at a glance: `aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `eks_cluster_name`, `{source}_admin_password`, plus `vpc_id` / `vpc_subnet_ids` / `vpc_cidr_block` when the module creates its own RDS.
{else if runtime_provisioner == terraform-aws-eks-cronjob}
The Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) provisions a periodic **{source} CronJob** on an existing EKS cluster. The CronJob clones a configurable list of git repos, runs `{source} scan`, and uploads JSON findings to an S3 artifact bucket via IRSA. Users with an existing {source} deployment skip this entirely.

Required runtime inputs at a glance: `aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `eks_cluster_name`, `eks_cluster_oidc_provider_arn`, `artifact_bucket`, `github_pat_for_clone`. Optional: `repo_urls` (default `{repo_urls_default}`), `cron_schedule` (default `{cron_schedule_default}`), `{source}_image` (default `{scanner_image_default}`).

The bundled driver script `runtime/files/{source}-scan.sh` is operator-authored. Inspect and customise before apply (the default expects `org/repo` slugs and clones via `https://x-access-token:${GH_PAT}@github.com/...`; users with non-GitHub hosts must replace the script).
{end}

Apply with:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

{if helm}
The Helm chart does not support declarative token creation, so the module emits a random `{source}_project_token` value that you register against the running {source} via `POST /api/user_tokens/generate` after `terraform apply` completes. Once registered, feed the host and registered token into the next section as `{source_upper}_HOST` / `{source_upper}_TOKEN`.
{else}
After apply, verify the CronJob is scheduled with `kubectl -n {namespace_default} get cronjob`. The first scan runs at the next cron tick (default every 6 hours).
{end}
```
