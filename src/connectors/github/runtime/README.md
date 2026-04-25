# GitHub connector — source-system runtime (optional)

This Terraform module sets up the **GitHub side** of the github connector's source data: a GitHub organization populated with demo repositories and a Juice Shop fork, plus the AWS infrastructure that the demo CI workflow needs (ECR for image pushes, GitHub Actions OIDC IAM role, Juice Shop k8s namespace).

**It is optional.** The github connector itself only needs a GitHub org with target repositories the operator wants to ingest — it doesn't require these specific demo repos.

## When to apply

Apply this module if you want appsec-mvp to provision the *demo* GitHub setup on your behalf. Skip it if you have your own GitHub org with the repositories you'd like to scan.

## What it creates

- 3 demo repositories (`seed-python-a`, `seed-javascript-b`, `juiceshop`) — two contain deliberately-vulnerable code for SAST scans; the third is a Juice Shop fork (DAST target).
- An ECR repository for Juice Shop image pushes from CI.
- A GitHub Actions OIDC trust + IAM role (so CI can push to ECR / deploy to EKS without long-lived AWS keys).
- A Juice Shop Kubernetes namespace and LoadBalancer Service (target for ZAP scans).

It does **not** install the cross-scanner CI workflow (`scan.yml`). That workflow lives under `examples/end-to-end-demo/.github/workflows/scan.yml` and you copy it manually into the seeded Juice Shop repo if you want the end-to-end demo.

The Juice Shop Kubernetes manifest at `files/juiceshop/deploy/juiceshop.yaml` is committed verbatim into the seeded `juiceshop` repo by `github_repository_file.juiceshop_files`; the `scan.yml` CI workflow then `kubectl apply`s it during the deploy step.

## Operator-supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region for ECR + IAM. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the Juice Shop namespace lives (operator-supplied). |
| `github_org` | GitHub organization for seed repos. |
| `github_pat` | PAT with org + repo admin permissions (sensitive). |

### Optional (only needed for the cross-scanner end-to-end demo)

These default to empty string. When empty, the corresponding GitHub Actions variable / secret is not created on the Juice Shop seed repo, and the conditional S3-write IAM grant is omitted.

| Variable | Description |
|---|---|
| `sonarqube_url` | Public SonarQube URL consumed by the cross-scanner CI workflow. |
| `sonarqube_project_token` | SonarQube project analysis token (sensitive). |
| `zap_url` | Public ZAP URL consumed by the cross-scanner CI workflow. |
| `artifact_bucket` | S3 bucket name for CI scan-artifact uploads (`${artifact_bucket}/cicd/*`). When set, the GitHub Actions IAM role is granted `s3:PutObject` / `s3:GetObject` / `s3:ListBucket` on it. |

## Apply

```bash
cd src/connectors/github/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Operators write their own `terraform.tfvars`. The legacy `infra/terraform/terraform.tfvars.example` can serve as a starting reference for the AWS / GitHub credentials block.

## Outputs

`seed_repo_names`, `ecr_registry_uri`, `github_actions_role_arn`, `github_actions_role_name`, `juiceshop_namespace`, `juiceshop_ingress_host` — useful as inputs to `examples/end-to-end-demo/` if you're wiring the full demo. `github_actions_role_name` is provided so operators can attach additional IAM policies via `aws_iam_role_policy_attachment` without re-deriving the name from the ARN.

## Teardown

```bash
cd src/connectors/github/runtime
terraform destroy
```

Caveat: EKS access entries can be order-sensitive. If `terraform destroy` errors on the `aws_eks_access_*` resources (e.g. because the cluster is being torn down out-of-band), remove them from state with `terraform state rm` and re-run.

## Independence

This module references only operator-supplied inputs and the GitHub / AWS / Kubernetes provider APIs. It does not depend on any other connector's runtime — per the redesign's no-inter-connector-dependency rule.
