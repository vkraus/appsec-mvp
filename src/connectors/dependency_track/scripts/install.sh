#!/usr/bin/env bash
set -euo pipefail
: "${DT_HOST:?required}"
: "${DT_APIKEY:?required}"

echo "Step 1/3: Loading secrets..."
bash src/connectors/dependency_track/scripts/load-secrets.sh
echo "Step 2/3: Triggering pipeline..."
databricks bundle run dependency_track_ingest --target dev
echo "Step 3/3: Run verification SQL — see runbook"
echo "✓ Dependency-Track connector install complete."
