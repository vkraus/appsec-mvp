# Prerequisites

This page lists every operator-supplied input the four-step Phase 1 platform
flow consumes. Walk it once before starting setup — the per-step pages
([Bundle deploy](bundle-deploy.md), [Secrets bootstrap](secrets-bootstrap.md),
[Platform bootstrap job](platform-bootstrap-job.md)) reference the values
captured here verbatim.

The redesign moves the framework off `terraform apply` as the magic step.
Cloud and source-system infrastructure (VPC, EKS, S3, ECR, the connector
source systems themselves) is no longer provisioned by this repository.
Operators bring their own cloud backbone and stand up source systems either
manually or via the optional per-connector runtimes under
`src/connectors/<source>/runtime/`. The four-step Phase 1 only touches
Databricks objects and the operator-supplied AWS resources Unity Catalog
needs to read scanner artifacts.

## Accounts to create

| # | Account | What to capture |
|---|---|---|
| 1 | **AWS account** with sufficient privilege to create the VPC, EKS cluster, S3 bucket, ECR repository, and IAM roles listed under "AWS backbone" below. | AWS account ID; IAM credentials with the requisite permissions. |
| 2 | **Databricks workspace on AWS** with a Unity Catalog metastore attached. Workspace creation is a generic Databricks setup step (manual via the account console or automated via the official `aws-workspace-basic` Terraform module); the operator picks a path. After the workspace is up, create a personal access token in **User Settings → Developer → Access Tokens** and note the SQL warehouse ID for the platform-bootstrap job (Admin Settings → SQL Warehouses). | `DATABRICKS_HOST` (workspace URL), `DATABRICKS_TOKEN` (PAT), `warehouse_id`. |
| 3 | **Per-source accounts** for the connectors the operator plans to install. Each connector page under [Install connectors](../connectors/index.md) lists the specific account, URL, and credential it requires (e.g. GitHub organization + PAT for the github connector; ServiceNow tenant + service-account credentials for the servicenow connector). | Per-connector tokens / URLs (recorded in [Secrets bootstrap](secrets-bootstrap.md) when running each connector's `load-secrets.sh`). |

!!! note "Creating the Databricks workspace"
    Workspace provisioning is the same across every Databricks deployment
    and adds no value to reproduce here. Pick whichever path suits you:

    - **Manual (account console)** — follow the Databricks guide
      [Create a classic workspace](https://docs.databricks.com/aws/en/admin/workspace/create-workspace).
      ~1 hour end-to-end including the cross-account IAM role and root S3
      bucket.
    - **Automated (Terraform)** — copy the official
      [`aws-workspace-basic`](https://github.com/databricks/terraform-databricks-examples/tree/main/modules/aws-workspace-basic)
      module from `databricks/terraform-databricks-examples`. Requires an
      account-admin OAuth M2M service principal.

    Either path produces the workspace URL + PAT in the right-hand column.

## AWS backbone the operator brings

The platform DAB itself does not provision AWS infrastructure. The operator
stands up the following resources out-of-band before running [Bundle deploy](bundle-deploy.md):

| Resource | Why the platform needs it | Captured as |
|---|---|---|
| **VPC** with public + private subnets in one AWS region. | Hosts the EKS cluster the optional per-connector runtimes deploy into; also lets Databricks reach source systems running on EKS over private networking when the workspace is configured for VPC peering. | Operator records VPC ID + subnet IDs for use by the per-connector runtimes only — the platform DAB does not read these values. |
| **EKS cluster** with a managed node group (~3 × `t3.medium` or larger). | Hosts the optional connector runtimes (SonarQube Helm release, Semgrep CronJob, ZAP daemon, Juice Shop demo target). | Cluster name + region; OIDC provider ARN for IRSA-using runtimes. |
| **S3 artifact bucket** in the same region as EKS. | Receives scan artifacts written by the Semgrep CronJob and the ZAP CI step; surfaced into Unity Catalog as an external location so the connector ingest jobs can read them as Delta-readable paths. | `ARTIFACT_BUCKET` env var (consumed by `src/platform/scripts/bootstrap.sh`). |
| **ECR repository** in the same region. | Hosts container images pushed from Juice Shop CI in the cross-scanner end-to-end demo. Required only if the operator runs the github runtime's demo path. | ECR registry URI (consumed by the github runtime, not the platform DAB). |
| **IAM role for IRSA** (semgrep CronJob) — assumable by the `semgrep` Kubernetes service account, granted `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on `ARTIFACT_BUCKET`. | Lets the Semgrep CronJob write scan results to the artifact bucket without long-lived AWS keys. Required only if the operator runs the semgrep runtime. | Role ARN (consumed by the semgrep runtime, not the platform DAB). |
| **IAM role for the UC external location** — assumable by the Databricks Unity Catalog managed-storage principal, granted `s3:GetObject`, `s3:ListBucket`, `s3:PutObject` on `ARTIFACT_BUCKET`. The trust policy must follow the [Databricks UC storage credential trust policy](https://docs.databricks.com/aws/en/connect/unity-catalog/storage-credentials.html). | Lets Unity Catalog read scanner artifacts from the bucket as a UC external location. The platform bootstrap script creates the storage credential + external location pointing at this role. | `EXTERNAL_LOCATION_ROLE_ARN` env var (consumed by `src/platform/scripts/bootstrap.sh`). |

Provision these via your existing IaC tooling, by copying the legacy
`infra/terraform/modules/aws-foundation/` outputs into your own module, or by
hand. The redesigned platform DAB has no opinions about how — it only reads
the bucket name and IAM role ARN.

## Local tooling

Install on your workstation. All steps below assume a Unix-style shell
(macOS, Linux, WSL, Git Bash on Windows):

| Tool | Minimum version | macOS Homebrew | Windows (winget) |
|---|---|---|---|
| Databricks CLI | 0.240 | `brew install databricks` | `curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh \| sh` |
| AWS CLI v2 | 2.15 | `brew install awscli` | `winget install Amazon.AWSCLI` |
| Terraform | 1.7 (only if running per-connector runtimes) | `brew install terraform` | `winget install HashiCorp.Terraform` |
| kubectl | 1.30 (only for runtimes that deploy to EKS) | `brew install kubectl` | `winget install Kubernetes.kubectl` |
| Helm | 3.14 (only for runtimes that install Helm charts) | `brew install helm` | `winget install Helm.Helm` |
| git | 2.40 | pre-installed | `winget install Git.Git` |
| jq | 1.6 | `brew install jq` | `winget install stedolan.jq` |

The Databricks CLI and AWS CLI are required for every operator. Terraform,
kubectl, and Helm are required only if the operator opts into the
per-connector runtimes — connectors that consume an existing source system
(operator's own GitHub org, ServiceNow tenant, SonarQube instance) skip those
runtimes entirely.

## Credential file

The Databricks CLI reads `DATABRICKS_HOST` and `DATABRICKS_TOKEN` from the
environment, an `~/.databrickscfg` profile, or a `.env` file the operator
sources before each session. Pick whichever fits your secrets management.
The repository ships no `terraform.tfvars` and no `.env.example` — the bundle
reads everything via DAB variables passed on the command line at deploy time
or via environment variables resolved through `${env.DATABRICKS_HOST}` and
similar.

A minimal session bootstrap:

```bash
export DATABRICKS_HOST="https://<workspace>.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-east-1"

# Captured from the AWS backbone above:
export ARTIFACT_BUCKET="my-appsec-mvp-artifacts"
export EXTERNAL_LOCATION_ROLE_ARN="arn:aws:iam::123456789012:role/uc-external-location"

# Captured from the Databricks workspace:
export CATALOG="appsec_dev"
export WAREHOUSE_ID="abcd1234..."
```

`databricks bundle deploy` reads `DATABRICKS_HOST` / `DATABRICKS_TOKEN`;
`src/platform/scripts/bootstrap.sh` reads `EXTERNAL_LOCATION_ROLE_ARN`,
`ARTIFACT_BUCKET`, `CATALOG`. Per-connector secret loaders read whichever
env vars their connector documents.

## Next

Proceed to [Bundle deploy](bundle-deploy.md) to deploy the DAB into the
workspace, then [Secrets bootstrap](secrets-bootstrap.md) to load the
cross-cutting platform secrets, then [Platform bootstrap job](platform-bootstrap-job.md)
to apply the silver-table DDL.
