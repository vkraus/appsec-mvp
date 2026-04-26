#!/usr/bin/env bash
# Top-level orchestrator for the semgrep connector.
# Chain: runtime/install.sh -> scripts/load-secrets.sh -> databricks bundle deploy.
# Pass --skip-runtime when the source-side scanner (EKS CronJob writing JSON /
# SARIF artefacts to S3, or an equivalent CI/CD-step pipeline) is already
# provisioned and only the Databricks side needs to be installed.
set -euo pipefail
SKIP_RUNTIME=0
for arg in "$@"; do case "$arg" in --skip-runtime) SKIP_RUNTIME=1 ;; esac; done
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
echo "OK: semgrep connector installed."
