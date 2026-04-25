#!/usr/bin/env bash
# Source-side install for the trufflehog secrets runtime.
#
# Sub-shape: terraform-uc-volume (CLI-artefact + UC Volume).
#
# This runtime DOES NOT provision a cloud bucket. The bucket
# (S3 / ADLS / GCS) where CI runs drop trufflehog `--json` output is
# user-provisioned in advance.
#
# What this runtime creates: a Unity Catalog EXTERNAL Volume mapped to that
# bucket, so autoloader can read the JSON artefacts into
# bronze_trufflehog.findings.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG                              - Unity Catalog name (e.g. appsec_dev)
#   TRUFFLEHOG_ARTIFACT_VOLUME_PATH      - e.g. /Volumes/appsec_dev/bronze_trufflehog/artefacts
#
# Optional:
#   TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE - default: mvp-connectors
#   TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY   - default: trufflehog_aws_credentials
#
# Prerequisites:
#   - The cloud bucket exists and is reachable by the Databricks workspace.
#   - The bronze_trufflehog schema exists (declared by the bundle's
#     resources/schemas.yml; created by `databricks bundle deploy`).
#   - AWS / equivalent credentials with read access to the artefact bucket
#     are loaded into the Databricks secret scope
#     (`bash ../scripts/load-secrets.sh`).
#   - Databricks CLI authenticated.
#
# Idempotent: re-runs reconcile the Volume definition only.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_dev)}"
: "${TRUFFLEHOG_ARTIFACT_VOLUME_PATH:?TRUFFLEHOG_ARTIFACT_VOLUME_PATH is required}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_trufflehog_artifact_volume_path="${TRUFFLEHOG_ARTIFACT_VOLUME_PATH}"
[[ -n "${TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE:-}" ]] && export TF_VAR_trufflehog_artifact_volume_secret_scope="${TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE}"
[[ -n "${TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY:-}" ]] && export TF_VAR_trufflehog_artifact_volume_secret_key="${TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: trufflehog source-side runtime apply complete (UC Volume created)."
echo "Outputs:"
terraform output
