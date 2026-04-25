#!/usr/bin/env bash
# Populate sonarqube connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   SONARQUBE_URL
#   SONARQUBE_TOKEN
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${SONARQUBE_URL:?SONARQUBE_URL is required}"
: "${SONARQUBE_TOKEN:?SONARQUBE_TOKEN is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" sonarqube_url --string-value "$SONARQUBE_URL"
databricks secrets put-secret "$SCOPE" sonarqube_token --string-value "$SONARQUBE_TOKEN"

echo "OK: sonarqube secrets loaded into scope $SCOPE"
