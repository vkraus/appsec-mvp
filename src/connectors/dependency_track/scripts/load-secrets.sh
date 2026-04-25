#!/usr/bin/env bash
# Populate Dependency-Track connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   DEPENDENCY_TRACK_URL      — base URL of the Dependency-Track API
#                               (e.g. https://dependency-track.example.internal)
#   DEPENDENCY_TRACK_API_KEY  — team API key (X-Api-Key header value)
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${DEPENDENCY_TRACK_URL:?DEPENDENCY_TRACK_URL is required}"
: "${DEPENDENCY_TRACK_API_KEY:?DEPENDENCY_TRACK_API_KEY is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" dependency_track_url      --string-value "$DEPENDENCY_TRACK_URL"
databricks secrets put-secret "$SCOPE" dependency_track_api_key  --string-value "$DEPENDENCY_TRACK_API_KEY"

echo "OK: dependency_track secrets loaded into scope $SCOPE"
