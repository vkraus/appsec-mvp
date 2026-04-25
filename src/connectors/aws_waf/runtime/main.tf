# AWS WAF connector — log-stream consumption from S3.
# User provisions the WebACL + Firehose + S3 bucket externally;
# this module wires the S3 bucket policy to allow Firehose write
# (assuming Firehose runs in the same account) and registers the
# autoloader-friendly bucket prefix in the bronze schema.

provider "aws" {
  region = var.aws_region
}

# Reference (do NOT create) the user-supplied bucket.
data "aws_s3_bucket" "waf_logs" {
  bucket = element(split(":::", var.aws_waf_log_bucket_arn), 1)
}

# Bucket policy granting Firehose service write access.
resource "aws_s3_bucket_policy" "waf_logs_firehose" {
  bucket = data.aws_s3_bucket.waf_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowFirehoseWrite"
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
      Action    = ["s3:PutObject", "s3:PutObjectAcl"]
      Resource  = "${var.aws_waf_log_bucket_arn}/*"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = var.aws_waf_account_id
        }
      }
    }]
  })
}
