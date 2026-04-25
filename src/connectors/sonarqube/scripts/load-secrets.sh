#!/usr/bin/env bash
# Populate SonarQube connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   SONARQUBE_TOKEN  — SonarQube user token with `Browse projects` and
#                      `Execute analysis` permissions on every project to be
#                      ingested (admin token also acceptable). Generated in the
#                      SonarQube UI under My Account → Security → Generate Tokens.
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${SONARQUBE_TOKEN:?SONARQUBE_TOKEN is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" sonarqube_token --string-value "$SONARQUBE_TOKEN"

echo "OK: sonarqube secrets loaded into scope $SCOPE"
