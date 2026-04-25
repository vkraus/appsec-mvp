output "bronze_schema_full_name" {
  description = "Fully-qualified Unity Catalog schema name where AWS WAF bronze tables land."
  value       = "${var.catalog}.bronze_aws_waf"
}

output "s3_bucket_arn" {
  description = "Echo of the operator-supplied S3 bucket ARN holding Firehose-delivered WAF logs."
  value       = var.aws_waf_log_bucket_arn
}
