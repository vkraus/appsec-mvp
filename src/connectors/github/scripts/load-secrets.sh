#!/usr/bin/env bash
# Populate GitHub connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   GITHUB_PAT  — fine-grained or classic PAT with repo + org read access
#   GITHUB_ORG  — GitHub organization the connector ingests
#
# The connector code (src/connectors/github/ingest_entry.py) reads keys
# `github_token` and `github_org`, so those are the names we write here.
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${GITHUB_PAT:?GITHUB_PAT is required}"
: "${GITHUB_ORG:?GITHUB_ORG is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" github_token --string-value "$GITHUB_PAT"
databricks secrets put-secret "$SCOPE" github_org   --string-value "$GITHUB_ORG"

echo "OK: github secrets loaded into scope $SCOPE"
