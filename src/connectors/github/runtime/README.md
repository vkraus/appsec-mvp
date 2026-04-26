# GitHub connector, runtime module

Terraform module that wires the GitHub connector into a Databricks workspace.

This runtime provisions the **end-to-end-demo wiring** on the source side: an ECR repository for Juice Shop image pushes from CI, an IAM role with GitHub-Actions OIDC trust (so CI can push to ECR and deploy to EKS without long-lived AWS keys), an EKS namespace + LoadBalancer Service for the Juice Shop demo target (target for ZAP scans), and overlay files written into the user's Juice Shop fork plus optional Actions variables / secrets for the cross-scanner CI workflow.

It is **optional**. The github connector itself only needs a GitHub org with target repositories the user wants to ingest. Skip this module if you have your own GitHub org with the repositories you would like to scan.

## When to apply

Apply this module if you want appsec-mvp to provision the *demo* GitHub setup on your behalf. Skip it if you already have your own GitHub org wired with the repositories you want to scan and your own CI / EKS / ECR plumbing.

## Prerequisites

- A GitHub account (`github.com` tenant) with an organization the connector will ingest from.
- An AWS account with EKS, ECR, and IAM admin permissions.
- An EKS cluster with the AWS Load Balancer Controller installed (the Juice Shop Service is `type = LoadBalancer`).
- A GitHub Personal Access Token with org + repo admin permissions.
- Three forks already created under `var.github_org` (the runtime references them via `data "github_repository"` rather than creating them):

  - `${var.github_org}/BenchmarkJava` (forked from `OWASP-Benchmark/BenchmarkJava`). Java SAST target.
  - `${var.github_org}/BenchmarkPython` (forked from the upstream Benchmark Python project). Python SAST target.
  - `${var.github_org}/juice-shop` (forked from `juice-shop/juice-shop`). Juice Shop, the DAST target and CI/CD demo subject.

  If any of the three forks are missing under `var.github_org`, `terraform plan` will fail at the data lookup.

## What it provisions

- An ECR repository for Juice Shop image pushes from CI (`aws_ecr_repository.juiceshop`).
- A GitHub Actions OIDC trust + IAM role + role policy (so CI can push to ECR, describe the EKS cluster, and optionally write to an artifact S3 bucket without long-lived AWS keys).
- An EKS access entry granting cluster-admin to the GH-Actions IAM role (so CI can `kubectl apply` the Juice Shop deployment).
- A Juice Shop Kubernetes namespace and LoadBalancer Service (target for ZAP scans). The Juice Shop Deployment itself is applied by the GitHub Actions pipeline; Terraform only reserves the Service so the load-balancer hostname is stable across deploys.
- Two appsec-mvp overlays committed onto the `juice-shop` fork only: `.sonarcloud.properties` (SonarQube project key) and `deploy/juiceshop.yaml` (the Kubernetes manifest the CI workflow `kubectl apply`s).
- Conditional GitHub Actions variables / secrets on the Juice Shop fork, populated only for the cross-scanner end-to-end demo.

It **references** (does not create) three forks under `var.github_org`: `BenchmarkJava` and `BenchmarkPython` as SAST targets, and `juice-shop` as the DAST target and CI/CD demo subject.

It does **not** install the cross-scanner CI workflow (`scan.yml`). That workflow lives under `examples/end-to-end-demo/.github/workflows/scan.yml` and you copy it manually into the `juice-shop` fork if you want the end-to-end demo.

## User-supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region for ECR and IAM. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the Juice Shop namespace lives (supplied by the user). |
| `github_org` | GitHub organization for seed repos. |
| `github_pat` | PAT with org + repo admin permissions (sensitive). |

### Optional (only needed for the cross-scanner end-to-end demo)

These default to empty string. When empty, the corresponding GitHub Actions variable or secret is not created on the Juice Shop seed repo, and the conditional S3 write IAM grant is omitted.

| Variable | Description |
|---|---|
| `project_prefix` | Short slug used to namespace AWS resources (ECR repo name, IAM role name). Defaults to `appsec-mvp`. |
| `juiceshop_namespace` | Kubernetes namespace for the Juice Shop deployment. Defaults to `juiceshop`. |
| `sonarqube_url` | Public SonarQube URL consumed by the cross-scanner CI workflow. |
| `sonarqube_project_token` | SonarQube project analysis token (sensitive). |
| `zap_url` | Public ZAP URL consumed by the cross-scanner CI workflow. |
| `artifact_bucket` | S3 bucket name for CI scan artifact uploads (`${artifact_bucket}/cicd/*`). When set, the GitHub Actions IAM role is granted `s3:PutObject`, `s3:GetObject`, and `s3:ListBucket` on it. |

## Setup

1. Export the credentials into your shell:

   ```bash
   export AWS_REGION=us-east-1
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   export EKS_CLUSTER_NAME=...
   export GITHUB_ORG=...
   export GITHUB_PAT=...
   ```

2. Load secrets into Databricks Secrets:

   ```bash
   bash ../scripts/load-secrets.sh
   ```

3. Apply the terraform module via the bundled `install.sh` wrapper:

   ```bash
   bash install.sh
   ```

   Or invoke terraform directly:

   ```bash
   terraform init
   terraform apply -var-file=terraform.tfvars
   ```

   Users write their own `terraform.tfvars`. The legacy `infra/terraform/terraform.tfvars.example` can serve as a starting reference for the AWS / GitHub credentials block.

## Outputs

- `seed_repo_full_names`, `sast_repo_full_names`, `juice_shop_repo_full_name` — full `org/repo` names of seeded repos. Useful as inputs to `examples/end-to-end-demo/` if you are wiring the full demo.
- `ecr_registry_uri` — ECR registry URI for Juice Shop image pushes.
- `github_actions_role_arn` — IAM role ARN assumed by GitHub Actions via OIDC.
- `github_actions_role_name` — IAM role name (provided so users can attach additional policies via `aws_iam_role_policy_attachment` without re-deriving the name from the ARN).
- `juiceshop_namespace`, `juiceshop_ingress_host` — Kubernetes / LoadBalancer wiring for ZAP scans.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `databricks_secret not found` at pipeline runtime | User did not run `load-secrets.sh`. Re-run after exporting `GITHUB_PAT` and `GITHUB_ORG`. |
| `401 Unauthorized` from GitHub API at runtime | PAT expired or has wrong scopes. Rotate the PAT and re-run `load-secrets.sh`. |
| Empty `bronze_github` schema after pipeline run | Org may be wrong. Verify via `curl -H "Authorization: Bearer $GITHUB_PAT" https://api.github.com/orgs/<org>`. |
| `Schema bronze_github does not exist` | Bundle has not been deployed yet. Run `databricks bundle deploy --target dev` before the first ingest job. |
| `terraform plan` errors at `data "github_repository" ...` | One or more of the three required forks is missing under `var.github_org`. Fork BenchmarkJava, BenchmarkPython, and juice-shop into the org before re-running. |
| `terraform destroy` errors on `aws_eks_access_*` resources | EKS access entries can be order-sensitive (e.g. when the cluster is being torn down out of band). Remove them from state with `terraform state rm` and re-run. |

## Independence

This module references only user-supplied inputs and the GitHub / AWS / Kubernetes provider APIs. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own provider blocks. Using it via `module "..."` from a parent module will collide with the providers of the parent.
