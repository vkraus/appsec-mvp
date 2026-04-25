variable "catalog" {
  description = "Unity Catalog name where the AWS WAF bronze schema lives."
  type        = string
}

variable "aws_region" {
  description = "AWS region of the WAF/Firehose deployment"
  type        = string
  default     = "us-east-1"
}

variable "aws_waf_account_id" {
  description = "AWS account ID hosting the WebACLs"
  type        = string
}

variable "aws_waf_log_bucket_arn" {
  description = "ARN of the S3 bucket Firehose writes WAF logs to"
  type        = string
}

# Note: secret values for the AWS WAF connector live in the Databricks
# `mvp-connectors` scope under keys `waf_log_bucket` (log-stream mode) and
# `aws_waf_iam_role_arn` (SDK fallback mode), loaded by
# `src/connectors/aws_waf/scripts/load-secrets.sh`. They do NOT flow through
# this terraform module — main.tf only manages the S3 bucket policy. Keeping
# secret values out of terraform state is intentional.
