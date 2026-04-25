#!/usr/bin/env bash
# Populate OWASP ZAP connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   ZAP_URL      — public URL of the ZAP daemon (e.g. http://lb-host:8080)
#   ZAP_API_KEY  — 40-char API key configured on the daemon
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${ZAP_URL:?ZAP_URL is required}"
: "${ZAP_API_KEY:?ZAP_API_KEY is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" zap_url     --string-value "$ZAP_URL"
databricks secrets put-secret "$SCOPE" zap_api_key --string-value "$ZAP_API_KEY"

echo "OK: owasp_zap secrets loaded into scope $SCOPE"
