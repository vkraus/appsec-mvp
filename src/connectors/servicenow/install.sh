#!/usr/bin/env bash
# Top-level orchestrator for the servicenow connector.
#
# Runs in this order:
#   1. src/connectors/servicenow/runtime/install.sh
#      (source-side terraform; emitted by provision-source)
#   2. src/connectors/servicenow/scripts/load-secrets.sh
#      (writes secrets into the mvp-connectors scope)
#   3. databricks bundle deploy --target dev
#      (registers the servicenow UC connection,
#       the bronze_servicenow schema, and the
#       servicenow_ingest Lakeflow pipeline).
#
# Pass --skip-runtime to skip step 1 (use when the source is already provisioned
# or when running on SaaS without a runtime dependency).

set -euo pipefail
SKIP_RUNTIME=0
for arg in "$@"; do
  case "$arg" in --skip-runtime) SKIP_RUNTIME=1 ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

if [[ "$SKIP_RUNTIME" -eq 0 && -x "${SCRIPT_DIR}/runtime/install.sh" ]]; then
  echo "Step 1/3: Provisioning source runtime..."
  bash "${SCRIPT_DIR}/runtime/install.sh"
else
  echo "Step 1/3: Skipping source runtime."
fi

echo "Step 2/3: Loading secrets..."
bash "${SCRIPT_DIR}/scripts/load-secrets.sh"

echo "Step 3/3: Deploying bundle..."
databricks bundle deploy --target "${DATABRICKS_TARGET:-dev}"

echo "OK: servicenow connector installed."
