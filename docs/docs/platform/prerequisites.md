# Prerequisites

This page is the only set of steps you perform by hand. Everything else is Terraform.

Read through once before starting — credential extraction is easier if you do it while the signup wizard is fresh.

## Accounts to create

| # | Account | What to capture for Terraform |
|---|---|---|
| 1 | **AWS account** — sign up at [aws.amazon.com](https://aws.amazon.com). After verification, create an IAM user with `AdministratorAccess`; generate an access key. | `aws_access_key_id`, `aws_secret_access_key` |
| 2 | **Databricks workspace on AWS** — create via the AWS Marketplace "Databricks Data Intelligence Platform" listing. Use the AWS account from step 1. After the workspace is up, create a personal access token in **User Settings → Developer → Access Tokens**. Note the Unity Catalog metastore ID (Admin Settings → Metastores). | `databricks_workspace_url`, `databricks_pat`, `databricks_account_id`, `databricks_metastore_id` |
| 3 | **GitHub organization** — create a free organization at [github.com/organizations/new](https://github.com/organizations/new). Generate a PAT with permission to create and manage repositories in the organization (classic: `repo` + `admin:org`; fine-grained: equivalent organization + repository permissions). | `github_org`, `github_pat` |
| 4 | **ServiceNow tenant** — register a [Personal Developer Instance (PDI)](https://developer.servicenow.com/) or use a licensed tenant. Capture the instance URL and an admin credential. | `servicenow_instance_url`, `servicenow_admin_username`, `servicenow_admin_password` |

!!! warning "ServiceNow PDI caveat"
    The operator procedure assumes the ServiceNow tenant supports Databricks Lakeflow Connect. PDIs may or may not expose the necessary interfaces — if the Lakeflow pipeline (Task 15) fails to authenticate, fall back to a licensed tenant.

## Local tooling

Install on your workstation:

| Tool | Minimum version | macOS Homebrew | Windows (winget) |
|---|---|---|---|
| Terraform | 1.7 | `brew install terraform` | `winget install HashiCorp.Terraform` |
| AWS CLI v2 | 2.15 | `brew install awscli` | `winget install Amazon.AWSCLI` |
| kubectl | 1.30 | `brew install kubectl` | `winget install Kubernetes.kubectl` |
| Helm | 3.14 | `brew install helm` | `winget install Helm.Helm` |
| Databricks CLI | 0.240 | `brew install databricks` | `curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh \| sh` |
| git | 2.40 | pre-installed | `winget install Git.Git` |
| jq | 1.6 | `brew install jq` | `winget install stedolan.jq` |

## Credential file

In the Terraform working directory, copy the example tfvars and fill it in:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
```

Use a password manager. `terraform.tfvars` is gitignored — do not commit it.

## Next

Proceed to [Terraform Apply](terraform-apply.md).
