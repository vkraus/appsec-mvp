#!/usr/bin/env bash
# End-to-end installer for the SonarQube connector.
#
# Runs after Phase 1 (catalog + secret scope + bundle deploy). It:
#   1. Loads SONARQUBE_HOST + SONARQUBE_TOKEN into the mvp-connectors scope.
#   2. Triggers the sonarqube-connector job in the dev target.
#   3. Prints the Silver-layer verification query the user should run.
#
# Required environment variables:
#   SONARQUBE_HOST   — sonarcloud.io OR self-hosted Sonar host (no scheme).
#   SONARQUBE_ORG    — SonarCloud organization key. Read by the job at runtime.
#   SONARQUBE_TOKEN  — User token with Browse + Execute Analysis on All Projects.

set -euo pipefail

: "${SONARQUBE_HOST:?SONARQUBE_HOST is required (e.g. sonarcloud.io)}"
: "${SONARQUBE_ORG:?SONARQUBE_ORG is required (SonarCloud organization key)}"
: "${SONARQUBE_TOKEN:?SONARQUBE_TOKEN is required (user token)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Step 1/3: Loading secrets into mvp-connectors..."
SONARQUBE_URL="$SONARQUBE_HOST" \
  bash "$SCRIPT_DIR/load-secrets.sh"

echo "Step 2/3: Triggering sonarqube-connector job (target=dev)..."
databricks bundle run sonarqube-connector --target dev

echo "Step 3/3: Verifying rows..."
echo "  Run the following from a Databricks SQL editor or via the CLI:"
echo
echo "    SELECT count(*) FROM appsec_dev.bronze_sonarqube.issues;"
echo "    SELECT severity_canonical, count(*) FROM appsec_dev.silver.findings"
echo "      WHERE source_tool = 'sonarqube' GROUP BY severity_canonical;"
echo
echo "OK: SonarQube connector install complete."
