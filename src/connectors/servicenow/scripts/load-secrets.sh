#!/usr/bin/env bash
# Populate ServiceNow connector secrets into the mvp-connectors scope.
#
# These secrets are also the values the ServiceNow Lakeflow connection
# (declared in src/connectors/servicenow/resources/connection.yml) reads
# at deploy time via DAB variables. Pushing them to the secret scope as
# well lets the connector job use them via dbutils.secrets when reading
# from non-Lakeflow paths (e.g. ad-hoc REST calls).
#
# Reads from environment variables:
#   SERVICENOW_URL       — ServiceNow instance URL (e.g. https://devXXXXX.service-now.com)
#   SERVICENOW_USERNAME  — service-account username
#   SERVICENOW_PASSWORD  — service-account password
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${SERVICENOW_URL:?SERVICENOW_URL is required}"
: "${SERVICENOW_USERNAME:?SERVICENOW_USERNAME is required}"
: "${SERVICENOW_PASSWORD:?SERVICENOW_PASSWORD is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" servicenow_url      --string-value "$SERVICENOW_URL"
databricks secrets put-secret "$SCOPE" servicenow_username --string-value "$SERVICENOW_USERNAME"
databricks secrets put-secret "$SCOPE" servicenow_password --string-value "$SERVICENOW_PASSWORD"

echo "OK: servicenow secrets loaded into scope $SCOPE"
