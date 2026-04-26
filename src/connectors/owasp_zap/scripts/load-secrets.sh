#!/usr/bin/env bash
# Populate owasp_zap connector secrets into the mvp-connectors scope.
#
# OWASP ZAP is a HYBRID DAST connector with two ingestion paths:
#   - CI/CD-step artefact path: pipelines run zap-baseline.py /
#     zap-full-scan.py / zap-api-scan.py and write JSON reports to an
#     object-storage prefix (cicd/zap/<run>/...). Access to those files
#     is governed by bucket IAM — there is no native authentication on
#     the report files themselves. The CI/CD-step path requires no
#     dedicated secret beyond the workspace's storage credential, but
#     this loader still writes the daemon-path secrets so an operator
#     can switch to scan-and-read mode without re-running setup.
#   - On-demand server (daemon) path: the connector drives scans against
#     a long-lived ZAP daemon REST API. Authentication is the apikey
#     query parameter, configured at daemon startup with -config
#     api.key=<KEY>. ZAP rejects requests with a missing or wrong key.
#
# Reads from environment variables:
#   ZAP_URL      — daemon-path ZAP API base URL (e.g. http://zap.svc.cluster.local:8080).
#   ZAP_API_KEY  — daemon-path API key matching the daemon's -config api.key.
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${ZAP_URL:?ZAP_URL is required}"
: "${ZAP_API_KEY:?ZAP_API_KEY is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" zap_url --string-value "$ZAP_URL"
databricks secrets put-secret "$SCOPE" zap_api_key --string-value "$ZAP_API_KEY"

echo "OK: owasp_zap secrets loaded into scope $SCOPE"
