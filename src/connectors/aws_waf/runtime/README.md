# AWS WAF connector — source-system runtime

This Terraform module wires the operator-owned **S3 bucket** that AWS Kinesis Firehose delivers WAFv2 log records to into the AWS WAF connector. It does **not** create the WebACL, the Firehose delivery stream, or the S3 bucket — those are operator prerequisites. What it *does* create is the S3 bucket policy that grants the Firehose service principal write access to the bucket (scoped to the operator's account ID), and it surfaces the bronze schema name + bucket ARN as outputs for the connector pipeline to consume.

## Prerequisites

The operator must have:

- An AWS account with WAFv2 enabled, fronting CloudFront, an Application Load Balancer, or API Gateway.
- A WebACL configured with **logging enabled**, sending logs via a **Kinesis Firehose** delivery stream to an S3 bucket.
- The destination **S3 bucket** created and owned by the operator (in the same account as the Firehose).
- AWS credentials usable from the Databricks workspace with `s3:GetObject` on the log bucket (so the autoloader can read records). Operators typically issue an IAM user with a programmatic access key and store the key pair as a Databricks secret.
- The values:
  - `aws_waf_account_id` — the AWS account ID hosting the WebACLs and Firehose.
  - `aws_waf_log_bucket_arn` — the ARN of the destination S3 bucket (e.g. `arn:aws:s3:::my-org-waf-logs`).

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

- `aws_s3_bucket_policy.waf_logs_firehose` — bucket policy on the operator-supplied bucket granting `firehose.amazonaws.com` `s3:PutObject` / `s3:PutObjectAcl`, conditioned on `aws:SourceAccount = var.aws_waf_account_id`.

It also exposes:

- `bronze_schema_full_name` — `${var.catalog}.bronze_aws_waf`, the schema where the AWS WAF bronze tables land.
- `s3_bucket_arn` — echo of the operator-supplied bucket ARN (handy for downstream wiring).

## Sample log record format

A representative single-record sample of the WAFv2 log payload is at `runtime/files/sample.json`. Each Firehose-delivered S3 object contains one or more newline-delimited records of this shape (typically gzipped). The bronze envelope (`sql/event_envelope.sql`) lands the raw payload as a string and extracts the WebACL ID at ingest time for joinability.

## Validation evidence

stub.

## Independence

This module references only operator-supplied inputs and the AWS provider API. It does not depend on any other connector's runtime — per the redesign's no-inter-connector-dependency rule.
