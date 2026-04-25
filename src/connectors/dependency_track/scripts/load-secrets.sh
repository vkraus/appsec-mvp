#!/usr/bin/env bash
# Populate Dependency-Track connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   DT_APIKEY  — Dependency-Track team API key (X-Api-Key header value).
#                Generate via Administration -> Access Management -> Teams
#                -> Automation in the Dependency-Track UI; assign at minimum
#                VIEW_PORTFOLIO and VIEW_VULNERABILITY permissions.
#
# The Dependency-Track host is supplied via the `dependency_track_host`
# terraform variable (user runbook in runtime/README.md), not via the
# secret scope, so this script only loads the API key.
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${DT_APIKEY:?DT_APIKEY is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" dependency_track_api_key --string-value "$DT_APIKEY"

echo "OK: dependency_track secrets loaded into scope $SCOPE"
