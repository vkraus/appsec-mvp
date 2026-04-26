#!/usr/bin/env bash
# Populate github connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   GITHUB_PAT  — fine-grained PAT or classic PAT with read access to the
#                 target organization's repositories plus the Code scanning,
#                 Secret scanning, and Dependabot alerts read permissions
#                 (classic PAT scopes: `repo` + `security_events`).
#   GITHUB_ORG  — GitHub organization login (the slug in https://github.com/<org>).
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${GITHUB_PAT:?GITHUB_PAT is required}"
: "${GITHUB_ORG:?GITHUB_ORG is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" github_token --string-value "$GITHUB_PAT"
databricks secrets put-secret "$SCOPE" github_org   --string-value "$GITHUB_ORG"

echo "OK: github secrets loaded into scope $SCOPE"
