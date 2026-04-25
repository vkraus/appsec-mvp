#!/usr/bin/env bash
# Populate GitLab connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   GITLAB_BASE_URL  — base URL of the GitLab API (e.g. https://gitlab.com)
#   GITLAB_TOKEN     — group access token or personal access token with
#                      `read_api` and `read_repository` scopes; on Ultimate,
#                      additionally with `read_api` against the security
#                      project for the Vulnerabilities API.
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${GITLAB_BASE_URL:?GITLAB_BASE_URL is required}"
: "${GITLAB_TOKEN:?GITLAB_TOKEN is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" gitlab_base_url --string-value "$GITLAB_BASE_URL"
databricks secrets put-secret "$SCOPE" gitlab_token    --string-value "$GITLAB_TOKEN"

echo "OK: gitlab secrets loaded into scope $SCOPE"
