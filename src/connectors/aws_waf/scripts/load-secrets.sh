#!/usr/bin/env bash
# Populate AWS WAF connector secrets into the mvp-connectors scope.
#
# AWS WAF is a log-stream connector: the autoloader reads gzipped JSON
# records that Kinesis Firehose delivers from the operator's WebACLs to
# an S3 bucket. The connector needs AWS credentials with `s3:GetObject`
# on the log bucket; we pack them as a single JSON-shaped secret so the
# bronze pipeline can read them with one secret lookup.
#
# Reads from environment variables:
#   AWS_ACCESS_KEY_ID      — programmatic access key for S3 reads
#   AWS_SECRET_ACCESS_KEY  — paired secret key
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"

SCOPE="mvp-connectors"
KEY="aws_waf_credentials"

PAYLOAD=$(printf '{"access_key_id":"%s","secret_access_key":"%s"}' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY")

databricks secrets put-secret "$SCOPE" "$KEY" --string-value "$PAYLOAD"

echo "OK: aws_waf secrets loaded into scope $SCOPE (key: $KEY)"
