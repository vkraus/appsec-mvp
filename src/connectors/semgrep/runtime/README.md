# Semgrep connector: source system runtime (optional)

This Terraform module deploys the **Semgrep CronJob** that periodically clones a list of git repositories, runs `semgrep scan`, and writes JSON findings to an user supplied S3 bucket. The Semgrep connector then ingests those findings from S3.

**It is optional.** The Semgrep connector itself only needs an S3 prefix to read findings from. Users with their own Semgrep deployment skip this module entirely.

## When to apply

Apply this module if you want appsec-mvp to provision a periodic Semgrep scan runner on your EKS cluster. Skip it if you already have Semgrep wired up. Feed the bucket and prefix where your existing scanner writes findings directly into the secrets of the connector.

## What it creates

- A `semgrep` Kubernetes namespace and service account on your EKS cluster, with an IRSA annotation pointing at the IAM role this module mints.
- An IAM role assumable by the `semgrep` service account via IRSA, granted `s3:PutObject`, `s3:GetObject`, and `s3:ListBucket` on `var.artifact_bucket` and its objects (mirrors the source `module "semgrep_irsa"` and `aws_iam_policy.artifact_bucket_write` from `aws-foundation`).
- A ConfigMap holding the bundled `semgrep-scan.sh` driver script.
- A Secret holding the runtime env vars (`ARTIFACT_BUCKET`, `SEMGREP_REPO_LIST`, `AWS_REGION`, `GH_PAT`).
- A CronJob that runs the script on a fixed schedule (default: every 6 hours, configurable via `var.cron_schedule`).

## User supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region of the EKS cluster and the artifact S3 bucket. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the CronJob runs. Must be in `var.aws_region`. |
| `eks_cluster_oidc_provider_arn` | ARN of the IAM OIDC provider associated with the cluster (output by your EKS module as `oidc_provider_arn`). Required to mint the IRSA trust policy. Must reference the same cluster as `eks_cluster_name`. |
| `artifact_bucket` | S3 bucket name where the CronJob writes findings JSON. The IRSA role is granted `s3:PutObject`, `s3:GetObject`, and `s3:ListBucket` on this bucket and its objects. |

> **Tip:** for hand rolled EKS clusters, the OIDC provider ARN is the `.arn` attribute of an `aws_iam_openid_connect_provider` resource (Terraform) or visible in the EKS console under "Configuration → OpenID Connect provider URL".

### Optional

| Variable | Description | Default |
|---|---|---|
| `repo_urls` | List of repositories the CronJob clones and scans. The bundled script expects `org/repo` slugs (clones via `https://x-access-token:${GH_PAT}@github.com/${slug}.git`). Override the script for arbitrary git URLs. | `["owasp/juice-shop"]` |
| `github_pat_for_clone` | GitHub PAT used by `semgrep-scan.sh` to clone the repos (sensitive). Required even for public repos because the script always injects the token into the clone URL. | `""` |
| `project_prefix` | Tag and name prefix for AWS resources (IAM role name, IAM policy name, tags). | `appsec-mvp` |
| `namespace_name` | Kubernetes namespace name. | `semgrep` |
| `semgrep_image` | Container image used by the CronJob. Captured as a variable for reproducibility. The source module hard coded the latest tag. | `returntocorp/semgrep:latest` |
| `cron_schedule` | Cron schedule for the CronJob. | `0 */6 * * *` (every 6h) |

## Apply

```bash
cd src/connectors/semgrep/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Users write their own `terraform.tfvars`. The legacy `infra/terraform/terraform.tfvars.example` can serve as a starting reference for the AWS credentials block.

## Outputs

`semgrep_namespace`, `semgrep_cronjob_name`, `semgrep_irsa_role_arn`, `semgrep_env_secret_name`. Useful as inputs for connector wiring (e.g. surfacing the bucket prefix into the Semgrep connector secrets) and for `kubectl` debugging.

## Teardown

```bash
cd src/connectors/semgrep/runtime
terraform destroy
```

Caveats:

- If a Semgrep pod is mid scan when destroy runs, it gets terminated. The working directory of the partial scan is in an `emptyDir` volume and is lost. If you care about the in-flight findings, wait for the most recent Job of the CronJob to complete before destroying.
- The IRSA role only has permissions on `arn:aws:s3:::${var.artifact_bucket}` and `${var.artifact_bucket}/*`. After teardown, previously uploaded findings remain in the bucket. Delete them manually if you no longer need them. The bucket itself is **not** managed by this module.

## Independence

This module references only user supplied inputs and the AWS and Kubernetes provider APIs. It does not depend on the runtime of any other connector, per the no inter connector dependency rule of the redesign. Cross-runtime references that previously came from `aws-foundation` outputs (`eks_cluster_name`, `eks_cluster_oidc_provider_arn`, `artifact_bucket`) become user supplied variables. The repo list (previously sourced from `github_seed.seed_repo_names`) becomes the `repo_urls` variable.

This module is intended to be used as a **root** module, not a child module. It declares its own `aws` and `kubernetes` provider blocks. Using it via `module "..."` from a parent module will collide with the providers of the parent.
