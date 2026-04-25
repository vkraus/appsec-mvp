# provision-source — waf reference

WAF connectors follow a **bucket-policy-only** runtime shape (canonical follower: `aws_waf`, `src/connectors/aws_waf/runtime/`). The user provisions the WebACL, the Kinesis Firehose delivery stream, and the destination S3 bucket out of band; the runtime wires those external resources into the connector by:

1. Attaching an S3 bucket policy that grants `firehose.amazonaws.com` write access to the user-supplied bucket, scoped via `aws:SourceAccount = var.aws_waf_account_id`.
2. Surfacing the bronze schema name and bucket ARN as outputs for the connector pipeline to consume.

It does **not** create the WebACL, the Firehose delivery stream, or the S3 bucket. Provider stack: `hashicorp/aws` + `databricks/databricks` (the latter for `versions.tf` parity, but currently unused — kept for forward-compatibility if a future revision adds UC Volume / external location bindings).

## operational.yml.source_runtime schema

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-aws-bucket-policy`) | yes | `terraform-aws-bucket-policy` | constant per category — WAF runtime is bucket-policy-only |
| `catalog_var_name` | string | yes | `catalog` | `runtime/variables.tf` first variable |
| `bronze_schema_name` | string | yes | `bronze_aws_waf` | `runtime/outputs.tf` `output "bronze_schema_full_name"` template literal |
| `aws_region_var_name` | string | yes | `aws_region` | `runtime/variables.tf` |
| `aws_region_default` | string | no | `us-east-1` | `runtime/variables.tf` `variable "aws_region" { default = ... }` |
| `aws_account_id_var_name` | string | yes | `aws_waf_account_id` | `runtime/variables.tf` |
| `log_bucket_arn_var_name` | string | yes | `aws_waf_log_bucket_arn` | `runtime/variables.tf` |
| `firehose_service_principal` | string | no | `firehose.amazonaws.com` | `runtime/main.tf` `aws_s3_bucket_policy.waf_logs_firehose` Principal |
| `firehose_actions` | list[string] | no | `["s3:PutObject", "s3:PutObjectAcl"]` | `runtime/main.tf` `aws_s3_bucket_policy.waf_logs_firehose` Action |
| `bucket_policy_sid` | string | no | `AllowFirehoseWrite` | `runtime/main.tf` `aws_s3_bucket_policy.waf_logs_firehose` Sid |
| `secret_keys_external` | list[string] | no | `["waf_log_bucket", "aws_waf_iam_role_arn"]` | `runtime/variables.tf` comment block (loaded by scripts/load-secrets.sh, NOT by terraform) |
| `sample_artefact_path` | string | no | `runtime/files/sample.json` | presence of `runtime/files/sample.json` in canonical follower |
| `terraform_required_version` | string | no | `>= 1.5` | `runtime/versions.tf` |

## Terraform shape

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = { source = "databricks/databricks", version = ">= 1.40" }
    aws        = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}
```

**Provider configuration** (`runtime/main.tf`):

```hcl
provider "aws" {
  region = var.aws_region
}
```

(No explicit `databricks` provider block — Databricks credentials are picked up from `DATABRICKS_HOST` + `DATABRICKS_TOKEN` env vars or `~/.databrickscfg` profile.)

**Modules referenced:** none.

**Resources / data sources:**

- `data "aws_s3_bucket" "waf_logs"` — references the user-supplied bucket (does NOT create it). Bucket name is parsed out of the ARN via `element(split(":::", var.aws_waf_log_bucket_arn), 1)`.
- `aws_s3_bucket_policy.waf_logs_firehose` — bucket policy granting `firehose.amazonaws.com` `s3:PutObject` + `s3:PutObjectAcl` on `${var.aws_waf_log_bucket_arn}/*`, conditioned on `aws:SourceAccount = var.aws_waf_account_id`.

**Variables exposed:**

| Name | Type | Sensitive | Required | Default |
|---|---|---|---|---|
| `catalog` | string | no | yes | — |
| `aws_region` | string | no | no | `us-east-1` |
| `aws_waf_account_id` | string | no | yes | — |
| `aws_waf_log_bucket_arn` | string | no | yes | — |

> **Security note (intentional design):** secret values for the WAF connector (`waf_log_bucket`, `aws_waf_iam_role_arn`) live in the Databricks `mvp-connectors` scope and are loaded by `scripts/load-secrets.sh`. They do NOT flow through this Terraform module — `main.tf` only manages the S3 bucket policy. Keeping secret values out of Terraform state is intentional.

**Outputs:**

| Name | Description |
|---|---|
| `bronze_schema_full_name` | `${var.catalog}.bronze_aws_waf` — three-level Bronze schema name |
| `s3_bucket_arn` | echo of the user-supplied bucket ARN |

## runtime/files/* conventions

One operator-authored sidecar:

- `runtime/files/sample.json` — sanitised representative WAFv2 log record. Each S3 object delivered by Firehose contains one or more records in this form, separated by newlines (typically gzipped). The bronze envelope (`sql/event_envelope.sql`) lands the raw payload as a string and extracts the WebACL ID at ingest time for joinability.

The skill emits a runtime/README.md reference to `runtime/files/sample.json` but never generates the file content. Operator authors it from a real (sanitised) Firehose-delivered record.

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Sub-shape: terraform-aws-bucket-policy.
#
# This runtime DOES NOT create the WebACL, the Firehose delivery stream,
# or the destination S3 bucket. Those are user prerequisites. What it
# DOES create is the S3 bucket policy that grants the Firehose service
# principal write access to the bucket, scoped by aws:SourceAccount.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG                 — Unity Catalog name (e.g. appsec_mvp)
#   AWS_WAF_ACCOUNT_ID      — AWS account ID hosting the WebACLs and Firehose
#   AWS_WAF_LOG_BUCKET_ARN  — ARN of the destination S3 bucket
#                             (e.g. arn:aws:s3:::my-org-waf-logs)
#
# Optional:
#   AWS_REGION              — default: {aws_region_default}
#
# Prerequisites:
#   - WAFv2 enabled in $AWS_WAF_ACCOUNT_ID, fronting CloudFront, ALB, or APIGW.
#   - WebACL configured with logging enabled, sending logs via Kinesis
#     Firehose to the target S3 bucket.
#   - The target bucket exists and is owned by the user (in the same
#     account as the Firehose).
#   - AWS credentials usable from terraform with permissions to attach an
#     S3 bucket policy on the target bucket.
#   - For runtime ingestion: AWS credentials with `s3:GetObject` on the
#     log bucket loaded into the Databricks `mvp-connectors` scope via
#     `bash ../scripts/load-secrets.sh`.
#
# Idempotent: re-runs reconcile the bucket policy.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_mvp)}"
: "${AWS_WAF_ACCOUNT_ID:?AWS_WAF_ACCOUNT_ID is required}"
: "${AWS_WAF_LOG_BUCKET_ARN:?AWS_WAF_LOG_BUCKET_ARN is required (e.g. arn:aws:s3:::my-org-waf-logs)}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_aws_waf_account_id="${AWS_WAF_ACCOUNT_ID}"
export TF_VAR_aws_waf_log_bucket_arn="${AWS_WAF_LOG_BUCKET_ARN}"
[[ -n "${AWS_REGION:-}" ]] && export TF_VAR_aws_region="${AWS_REGION}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} source-side runtime apply complete (bucket policy attached)."
echo "Outputs:"
terraform output
```

## runtime/README.md template

```markdown
# {source} connector, runtime for the source system

This Terraform module wires the **S3 bucket** owned by the user that AWS Kinesis Firehose delivers WAFv2 log records to into the {source} connector. It does **not** create the WebACL, the Firehose delivery stream, or the S3 bucket. Those are user prerequisites. What it *does* create is the S3 bucket policy that grants the Firehose service principal write access to the bucket (scoped to the user's account ID). It also surfaces the bronze schema name and bucket ARN as outputs for the connector pipeline to consume.

## Prerequisites

The user must have:

- An AWS account with WAFv2 enabled, fronting CloudFront, an Application Load Balancer, or API Gateway.
- A WebACL configured with **logging enabled**, sending logs via a **Kinesis Firehose** delivery stream to an S3 bucket.
- The target **S3 bucket** created and owned by the user (in the same account as the Firehose).
- AWS credentials usable from the Databricks workspace with `s3:GetObject` on the log bucket (so the autoloader can read records). Users typically issue an IAM user with a programmatic access key and store the key pair as a Databricks secret.
- The values:
  - `aws_waf_account_id` — the AWS account ID hosting the WebACLs and Firehose.
  - `aws_waf_log_bucket_arn` — the ARN of the target S3 bucket (e.g. `arn:aws:s3:::my-org-waf-logs`).

## Setup

1. Export the AWS credentials the connector pipeline will use to read from S3:

   ```bash
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   ```

2. Load them into the Databricks secret scope:

   ```bash
   bash src/connectors/{source}/scripts/load-secrets.sh
   ```

3. Apply the Terraform module:

   ```bash
   cd src/connectors/{source}/runtime
   terraform init
   terraform apply \
     -var="catalog=appsec_mvp" \
     -var="aws_region={aws_region_default}" \
     -var="aws_waf_account_id=000000000000" \
     -var="aws_waf_log_bucket_arn=arn:aws:s3:::my-org-waf-logs"
   ```

   Users usually wrap the variable values in a `terraform.tfvars` file rather than passing `-var` flags. Or use the bundled `install.sh` wrapper.

## What it creates

- `aws_s3_bucket_policy.waf_logs_firehose` — bucket policy on the user-supplied bucket granting `{firehose_service_principal}` `{firehose_actions joined}`, conditioned on `aws:SourceAccount = var.aws_waf_account_id`.

It also exposes:

- `bronze_schema_full_name`, set to `${var.catalog}.{bronze_schema_name}`. This is the schema where the {source} bronze tables land.
- `s3_bucket_arn`, an echo of the bucket ARN supplied by the user (handy for downstream wiring).

## Sample log record format

A representative sample with a single WAFv2 log payload is at `runtime/files/sample.json`. Each S3 object delivered by Firehose contains one or more records in this form, separated by newlines (typically gzipped). The bronze envelope (`sql/event_envelope.sql`) lands the raw payload as a string and extracts the WebACL ID at ingest time for joinability.

## Inputs supplied by the user

### Required

| Variable | Description |
|---|---|
| `catalog` | Unity Catalog name where the {source} bronze schema lives. |
| `aws_waf_account_id` | AWS account ID hosting the WebACLs. |
| `aws_waf_log_bucket_arn` | ARN of the S3 bucket Firehose writes WAF logs to. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `aws_region` | AWS region of the WAF/Firehose deployment. | `{aws_region_default}` |

> **Note:** secret values for the {source} connector live in the Databricks `mvp-connectors` scope under keys `{secret_keys_external joined}`, loaded by `scripts/load-secrets.sh`. They do NOT flow through this terraform module — `main.tf` only manages the S3 bucket policy. Keeping secret values out of terraform state is intentional.

## Outputs

`bronze_schema_full_name` (= `${catalog}.{bronze_schema_name}`), `s3_bucket_arn`. Useful as inputs to downstream wiring (Lakeflow autoloader pipelines, the bronze envelope SQL).

## Teardown

```bash
cd src/connectors/{source}/runtime
terraform destroy
```

This removes the bucket policy only. The underlying bucket and any log objects already delivered to it are **not** managed by this module. Delete them out of band if no longer needed. The WebACL and Firehose delivery stream are also not managed by this module.

## Independence

This module references only inputs supplied by the user and the AWS provider API. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module. It declares its own `aws` provider block. Using it via `module "..."` from a parent module will collide with the provider of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

The Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) wires the user-owned S3 bucket that Kinesis Firehose delivers WAFv2 log records to into the {source} connector. It **does not** create the WebACL, the Firehose delivery stream, or the destination S3 bucket — those are user prerequisites. What it *does* create is the S3 bucket policy granting `{firehose_service_principal}` `{firehose_actions joined}` on the bucket, scoped via `aws:SourceAccount = var.aws_waf_account_id`.

Required runtime inputs at a glance: `catalog`, `aws_waf_account_id`, `aws_waf_log_bucket_arn`. Optional: `aws_region` (default `{aws_region_default}`).

Apply with:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply \
  -var="catalog=appsec_mvp" \
  -var="aws_waf_account_id=000000000000" \
  -var="aws_waf_log_bucket_arn=arn:aws:s3:::my-org-waf-logs"
```

A sanitised sample of a Firehose-delivered WAFv2 log record lives at [`runtime/files/sample.json`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime/files/sample.json). Each S3 object delivered by Firehose contains one or more records in this form, newline-separated and typically gzipped.

> **Note:** secret values (`{secret_keys_external joined}`) for the {source} connector live in the Databricks `mvp-connectors` scope and are loaded by `scripts/load-secrets.sh`. They do NOT flow through this terraform module — keeping secret values out of terraform state is intentional.

See [`runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list, the WAFv2 / Firehose prerequisites, and the IAM permissions the bucket policy grants.
```
