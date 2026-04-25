# Prerequisites

This page lists every input supplied by the user that the four-step Phase 1 platform
flow consumes. Walk it once before starting setup. The pages for each step
([Bundle deploy](bundle-deploy.md), [Secrets bootstrap](secrets-bootstrap.md),
[Platform bootstrap job](platform-bootstrap-job.md)) reference the values
captured here verbatim.

The redesign moves the framework off `terraform apply` as the magic step.
Cloud and source-system infrastructure (VPC, EKS, S3, ECR, the connector
source systems themselves) is no longer provisioned by this repository.
Users bring their own cloud backbone and stand up source systems either
manually or via the optional runtimes for each connector under
`src/connectors/<source>/runtime/`. The four-step Phase 1 only touches
Databricks objects and the AWS resources supplied by the user that
Unity Catalog needs to read scanner artifacts.

## Accounts to create

| # | Account | What to capture |
|---|---|---|
| 1 | **AWS account** with sufficient privilege to create the VPC, EKS cluster, S3 bucket, ECR repository, and IAM roles listed under "AWS backbone" below. | AWS account ID, plus IAM credentials with the requisite permissions. |
| 2 | **Databricks workspace on AWS** with a Unity Catalog metastore attached. Workspace creation is a generic Databricks setup step (manual via the account console or automated via the official `aws-workspace-basic` Terraform module). The user picks a path. After the workspace is up, create a personal access token in **User Settings, Developer, Access Tokens** and note the SQL warehouse ID for the platform bootstrap job (Admin Settings, SQL Warehouses). | `DATABRICKS_HOST` (workspace URL), `DATABRICKS_TOKEN` (PAT), `warehouse_id`. |
| 3 | **Accounts for each source** for the connectors the user plans to install. Each connector page under [Install connectors](../connectors/index.md) lists the specific account, URL, and credential it requires (e.g. GitHub organization plus PAT for the github connector, ServiceNow tenant plus service account credentials for the servicenow connector). | Tokens and URLs for each connector (recorded in [Secrets bootstrap](secrets-bootstrap.md) when running `load-secrets.sh` for each connector). |

!!! note "Creating the Databricks workspace"
    Workspace provisioning is the same across every Databricks deployment
    and adds no value to reproduce here. Pick whichever path suits you:

    - **Manual (account console)**: follow the Databricks guide
      [Create a classic workspace](https://docs.databricks.com/aws/en/admin/workspace/create-workspace).
      ~1 hour end-to-end including the cross-account IAM role and root S3
      bucket.
    - **Automated (Terraform)**: copy the official
      [`aws-workspace-basic`](https://github.com/databricks/terraform-databricks-examples/tree/main/modules/aws-workspace-basic)
      module from `databricks/terraform-databricks-examples`. Requires an
      account admin OAuth M2M service principal.

    Either path produces the workspace URL plus PAT in the right-hand column.

## AWS backbone the user brings

The platform DAB itself does not provision AWS infrastructure. The user
stands up the following resources out-of-band before running [Bundle deploy](bundle-deploy.md):

| Resource | Why the platform needs it | Captured as |
|---|---|---|
| **VPC** with public and private subnets in one AWS region. | Hosts the EKS cluster the optional connector runtimes deploy into. Also lets Databricks reach source systems running on EKS over private networking when the workspace is configured for VPC peering. | User records VPC ID and subnet IDs for use by the connector runtimes only. The platform DAB does not read these values. |
| **EKS cluster** with a managed node group (~3 × `t3.medium` or larger). | Hosts the optional connector runtimes (SonarQube Helm release, Semgrep CronJob, ZAP daemon, Juice Shop demo target). | Cluster name and region, plus OIDC provider ARN for runtimes that use IRSA. |
| **S3 artifact bucket** in the same region as EKS. | Receives scan artifacts written by the Semgrep CronJob and the ZAP CI step. Exposed into Unity Catalog as an external location so the connector ingest jobs can read them as Delta-readable paths. | `ARTIFACT_BUCKET` env var (consumed by `src/platform/scripts/bootstrap.sh`). |
| **ECR repository** in the same region. | Hosts container images pushed from Juice Shop CI in the cross-scanner end-to-end demo. Required only if the user runs the demo path of the github runtime. | ECR registry URI (consumed by the github runtime, not the platform DAB). |
| **IAM role for IRSA** (semgrep CronJob), assumable by the `semgrep` Kubernetes service account, granted `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on `ARTIFACT_BUCKET`. | Lets the Semgrep CronJob write scan results to the artifact bucket without long-lived AWS keys. Required only if the user runs the semgrep runtime. | Role ARN (consumed by the semgrep runtime, not the platform DAB). |
| **IAM role for the UC external location**, assumable by the Databricks Unity Catalog managed storage principal, granted `s3:GetObject`, `s3:ListBucket`, `s3:PutObject` on `ARTIFACT_BUCKET`. The trust policy must follow the [Databricks UC storage credential trust policy](https://docs.databricks.com/aws/en/connect/unity-catalog/storage-credentials.html). | Lets Unity Catalog read scanner artifacts from the bucket as a UC external location. The platform bootstrap script creates the storage credential and external location pointing at this role. | `EXTERNAL_LOCATION_ROLE_ARN` env var (consumed by `src/platform/scripts/bootstrap.sh`). |

Provision these via your existing IaC tooling or by hand. The redesigned
platform DAB has no opinions about how. It only reads the bucket name and
IAM role ARN. (The repository previously shipped an `infra/terraform/`
module that did this provisioning. That module was removed in the
Databricks-centric redesign and users are expected to bring their own
backbone.)

## Local tooling

Install on your workstation. All steps below assume a Unix style shell
(macOS, Linux, WSL, Git Bash on Windows):

| Tool | Minimum version | macOS Homebrew | Windows (winget) |
|---|---|---|---|
| Databricks CLI | 0.240 | `brew install databricks` | `curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh \| sh` |
| AWS CLI v2 | 2.15 | `brew install awscli` | `winget install Amazon.AWSCLI` |
| Terraform | 1.7 (only if running connector runtimes) | `brew install terraform` | `winget install HashiCorp.Terraform` |
| kubectl | 1.30 (only for runtimes that deploy to EKS) | `brew install kubectl` | `winget install Kubernetes.kubectl` |
| Helm | 3.14 (only for runtimes that install Helm charts) | `brew install helm` | `winget install Helm.Helm` |
| git | 2.40 | pre-installed | `winget install Git.Git` |
| jq | 1.6 | `brew install jq` | `winget install stedolan.jq` |

The Databricks CLI and AWS CLI are required for every user. Terraform,
kubectl, and Helm are required only if the user opts into the
connector runtimes. Connectors that consume an existing source system
(your own GitHub org, ServiceNow tenant, SonarQube instance) skip those
runtimes entirely.

## Credential file

The Databricks CLI reads `DATABRICKS_HOST` and `DATABRICKS_TOKEN` from the
environment, an `~/.databrickscfg` profile, or a `.env` file the user
sources before each session. Pick whichever fits your secrets management.
The repository ships no `terraform.tfvars` and no `.env.example`. The bundle
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

`databricks bundle deploy` reads `DATABRICKS_HOST` and `DATABRICKS_TOKEN`.
`src/platform/scripts/bootstrap.sh` reads `EXTERNAL_LOCATION_ROLE_ARN`,
`ARTIFACT_BUCKET`, and `CATALOG`. Secret loaders for each connector read whichever
env vars their connector documents.

## Next

Proceed to [Bundle deploy](bundle-deploy.md) to deploy the DAB into the
workspace, then [Secrets bootstrap](secrets-bootstrap.md) to load the
cross-cutting platform secrets, then [Platform bootstrap job](platform-bootstrap-job.md)
to apply the silver table DDL.
