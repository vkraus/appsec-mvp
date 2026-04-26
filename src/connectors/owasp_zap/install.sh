#!/usr/bin/env bash
# Top-level orchestrator for the owasp_zap connector.
#
# Chain: runtime/install.sh → scripts/load-secrets.sh → databricks bundle deploy → scripts/install.sh.
#
# DAST source-side runtime applies only to the daemon path: the
# `runtime/` Terraform module deploys an OWASP ZAP daemon container on
# an existing EKS cluster (see runtime/README.md). The CI/CD-step
# artefact path needs no source-side provisioning — operators wire
# zap-baseline.py / zap-full-scan.py into their own CI pipeline and
# write JSON reports to the configured bucket prefix.
#
# Pass --skip-runtime when:
#   - You already have a ZAP daemon running and only need the
#     Databricks-side wiring.
#   - You only operate the CI/CD-step artefact path (no daemon at all).
set -euo pipefail

SKIP_RUNTIME=0
for arg in "$@"; do
  case "$arg" in
    --skip-runtime) SKIP_RUNTIME=1 ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

if [[ "$SKIP_RUNTIME" -eq 0 && -x "${SCRIPT_DIR}/runtime/install.sh" ]]; then
  echo "Step 1/3: Provisioning ZAP daemon source runtime..."
  bash "${SCRIPT_DIR}/runtime/install.sh"
elif [[ "$SKIP_RUNTIME" -eq 0 ]]; then
  echo "Step 1/3: runtime/install.sh not found or not executable."
  echo "  Run provision-source first to emit it, OR pass --skip-runtime"
  echo "  if you already operate a ZAP daemon (or only the CI/CD-step path)."
  exit 1
else
  echo "Step 1/3: Skipping ZAP daemon source runtime (--skip-runtime)."
fi

echo "Step 2/3: Deploying the Databricks bundle..."
databricks bundle deploy --target "${DATABRICKS_TARGET:-dev}"

echo "Step 3/3: Loading secrets and running the connector job..."
bash "${SCRIPT_DIR}/scripts/install.sh"

echo "OK: owasp_zap connector installed."
