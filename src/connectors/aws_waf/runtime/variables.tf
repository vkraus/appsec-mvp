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

variable "aws_waf_credential_secret_scope" {
  description = "Databricks secret scope holding AWS WAF credentials."
  type        = string
  default     = "mvp-connectors"
}

variable "aws_waf_credential_secret_key" {
  description = "Databricks secret key holding AWS WAF credentials."
  type        = string
  default     = "aws_waf_credentials"
}
