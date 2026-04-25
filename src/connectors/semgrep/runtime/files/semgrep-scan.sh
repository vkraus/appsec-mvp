#!/usr/bin/env bash
set -euo pipefail

# Periodic Semgrep scan driver. Pulls the list of registered repositories from
# a ConfigMap ($SEMGREP_REPO_LIST), clones each, scans it, and uploads the JSON
# result to s3://$ARTIFACT_BUCKET/periodic/semgrep/<repo>/<timestamp>.json.
# trigger_context is written into the artifact metadata so the Semgrep connector
# can tag bronze rows correctly.

: "${SEMGREP_REPO_LIST:?set SEMGREP_REPO_LIST}"
: "${ARTIFACT_BUCKET:?set ARTIFACT_BUCKET}"
: "${GH_PAT:?set GH_PAT}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORKDIR="$(mktemp -d)"
cd "$WORKDIR"

while IFS= read -r repo; do
  [ -z "$repo" ] && continue
  echo "scanning: $repo"
  rm -rf src
  git clone --depth 1 "https://x-access-token:${GH_PAT}@github.com/${repo}.git" src
  semgrep scan --config=auto --json --output="result.json" src || true
  aws s3 cp result.json \
    "s3://${ARTIFACT_BUCKET}/periodic/semgrep/${repo//\//_}/${TS}.json" \
    --metadata "trigger_context=periodic,repo=${repo},scanned_at=${TS}"
done < <(echo "$SEMGREP_REPO_LIST" | tr ',' '\n')
