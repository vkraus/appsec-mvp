# GitHub connector — source-system runtime (optional)

This Terraform module sets up the **GitHub side** of the github connector's source data: a GitHub organization populated with demo repositories and a Juice Shop fork, plus the AWS infrastructure that the demo CI workflow needs (ECR for image pushes, GitHub Actions OIDC IAM role, Juice Shop k8s namespace).

**It is optional.** The github connector itself only needs a GitHub org with target repositories the operator wants to ingest — it doesn't require these specific demo repos.

## When to apply

Apply this module if you want appsec-mvp to provision the *demo* GitHub setup on your behalf. Skip it if you have your own GitHub org with the repositories you'd like to scan.

## What it creates

- 3 demo repositories (`appsec-seed-a`, `appsec-seed-b`, `juiceshop`) — two contain deliberately-vulnerable code for SAST scans; the third is a Juice Shop fork (DAST target).
- An ECR repository for Juice Shop image pushes from CI.
- A GitHub Actions OIDC trust + IAM role (so CI can push to ECR / deploy to EKS without long-lived AWS keys).
- A Juice Shop Kubernetes namespace and LoadBalancer Service (target for ZAP scans).

It does **not** install the cross-scanner CI workflow (`scan.yml`). That workflow lives under `examples/end-to-end-demo/.github/workflows/scan.yml` and you copy it manually into the seeded Juice Shop repo if you want the end-to-end demo.

## Operator-supplied inputs

| Variable | Description |
|---|---|
| `aws_region` | AWS region for ECR + IAM. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the Juice Shop namespace lives (operator-supplied). |
| `github_org` | GitHub organization for seed repos. |
| `github_pat` | PAT with org + repo admin permissions (sensitive). |
| `sonarqube_url`, `sonarqube_token`, `zap_url` | (Optional) URLs/tokens for cross-scanner CI; leave empty if not using `examples/end-to-end-demo/`. |

## Apply

```bash
cd src/connectors/github/runtime
terraform init
terraform apply
```

## Outputs

`seed_repo_names`, `ecr_registry_uri`, `github_actions_role_arn`, `juiceshop_namespace`, `juiceshop_ingress_host` — useful as inputs to `examples/end-to-end-demo/` if you're wiring the full demo.

## Independence

This module references only operator-supplied inputs and the GitHub / AWS / Kubernetes provider APIs. It does not depend on any other connector's runtime — per the redesign's no-inter-connector-dependency rule.
