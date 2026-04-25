# AWS WAF connector, runtime for the source system

This Terraform module wires the **S3 bucket** owned by the operator that AWS Kinesis Firehose delivers WAFv2 log records to into the AWS WAF connector. It does **not** create the WebACL, the Firehose delivery stream, or the S3 bucket. Those are operator prerequisites. What it *does* create is the S3 bucket policy that grants the Firehose service principal write access to the bucket (scoped to the operator account ID). It also surfaces the bronze schema name and bucket ARN as outputs for the connector pipeline to consume.

## Prerequisites

The operator must have:

- An AWS account with WAFv2 enabled, fronting CloudFront, an Application Load Balancer, or API Gateway.
- A WebACL configured with **logging enabled**, sending logs via a **Kinesis Firehose** delivery stream to an S3 bucket.
- The target **S3 bucket** created and owned by the operator (in the same account as the Firehose).
- AWS credentials usable from the Databricks workspace with `s3:GetObject` on the log bucket (so the autoloader can read records). Operators typically issue an IAM user with a programmatic access key and store the key pair as a Databricks secret.
- The values:
  - `aws_waf_account_id`. The AWS account ID hosting the WebACLs and Firehose.
  - `aws_waf_log_bucket_arn`. The ARN of the target S3 bucket (e.g. `arn:aws:s3:::my-org-waf-logs`).

## Setup

1. Export the AWS credentials the connector pipeline will use to read from S3:

   ```bash
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   ```

2. Load them into the Databricks secret scope:

   ```bash
   bash src/connectors/aws_waf/scripts/load-secrets.sh
   ```

3. Apply the Terraform module:

   ```bash
   cd src/connectors/aws_waf/runtime
   terraform init
   terraform apply \
     -var="catalog=appsec_mvp" \
     -var="aws_region=us-east-1" \
     -var="aws_waf_account_id=000000000000" \
     -var="aws_waf_log_bucket_arn=arn:aws:s3:::my-org-waf-logs"
   ```

   Operators usually wrap the variable values in a `terraform.tfvars` file rather than passing `-var` flags.

## What it creates

- `aws_s3_bucket_policy.waf_logs_firehose`. Bucket policy on the bucket supplied by the operator granting `firehose.amazonaws.com` `s3:PutObject` and `s3:PutObjectAcl`, conditioned on `aws:SourceAccount = var.aws_waf_account_id`.

It also exposes:

- `bronze_schema_full_name`, set to `${var.catalog}.bronze_aws_waf`. This is the schema where the AWS WAF bronze tables land.
- `s3_bucket_arn`, an echo of the bucket ARN supplied by the operator (handy for downstream wiring).

## Sample log record format

A representative sample with a single record of the WAFv2 log payload is at `runtime/files/sample.json`. Each S3 object delivered by Firehose contains one or more records in this form, separated by newlines (typically gzipped). The bronze envelope (`sql/event_envelope.sql`) lands the raw payload as a string and extracts the WebACL ID at ingest time for joinability.

## Validation evidence

stub.

## Independence

This module references only inputs supplied by the operator and the AWS provider API. It does not depend on the runtime of any other connector. This follows the rule from the redesign that connector runtimes must not depend on each other.
