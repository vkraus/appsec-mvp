# OWASP ZAP

## Overview

OWASP ZAP is the reference DAST source in the framework. Operational pattern: **on-demand scan-lifecycle** — each spider, active, or passive scan is a discrete job, orchestrated by the connector against target URLs drawn from the application inventory and read back as alert sets after scan completion. The connector populates `silver.findings` from the ZAP alerts API, with findings linked to applications via target URL reverse-resolved against `silver.deployments`.

**Category:** DAST · **Integration pattern:** SDK (python-owasp-zap-v2.4) for the on-demand path; artifact path for the CI/CD-step path.

The MVP connector implements the CI/CD-step artifact-path mode only: the bronze reader ingests JSON alert dumps written by the Juice Shop GitHub Actions pipeline under `s3://<bucket>/cicd/zap/`, tagged with `trigger_context = 'cicd'`. The on-demand SDK-driven path against a long-lived ZAP daemon is documented under Reference as intended scope and is scaffolded in `src/connectors/owasp_zap/ingest.py`, but is not wired into the MVP ingest run.

## Prerequisites

Platform-level prerequisites (AWS, Databricks workspace, Terraform tooling) are covered once in [Platform → Prerequisites](../../platform/prerequisites.md). The OWASP ZAP-specific handoffs required before `terraform apply` are:

- **Long-lived ZAP daemon.** Terraform provisions a ZAP daemon Deployment in the `zap` namespace, exposed via LoadBalancer (see `terraform output zap_url`).
- **Credentials.** The `mvp-connectors` Databricks secret scope holds the `zap_url` and `zap_api_key` keys used by the connector.
- **CI/CD-step integration.** The Juice Shop repo's `.github/workflows/cicd.yml` runs a ZAP baseline step (`zap-baseline.py`) against the freshly-deployed app and uploads results to `s3://<bucket>/cicd/zap/` via the same OIDC-assumed role used by the Semgrep CI/CD step.
- **Scheduled job.** A scheduled `mvp-owasp-zap` Databricks job is created by Terraform to drive ingestion.

## Reference

### API surface

ZAP exposes a REST API on the daemon host (default port 8080) at `/JSON/<component>/<view|action>/<operation>/`. Relevant components for the connector: `spider` (crawl target), `ascan` (active scan), `pscan` (passive scan configuration), `core` (alerts, messages, sessions), and `alert` (alert details). Authentication uses a pre-shared API key supplied via `X-ZAP-API-Key` header or `apikey` query parameter, configured at daemon startup with `-config api.key=<value>`. Responses are JSON; XML and HAR formats are also supported for alerts.

### Pagination and rate limits

Alert retrieval endpoints (`/JSON/core/view/alerts/` and `/JSON/alert/view/alertsByRisk/`) accept `start` and `count` offset parameters. The connector iterates with a fixed `count=500` until an empty response. The daemon has no enforced request-rate limit beyond host resources; the connector self-regulates concurrent scans via `ascan.setOptionMaxScansInUI` to bound daemon load.

### Incremental hook

ZAP alerts are scan-scoped. The connector uses the numeric scan `scanId` as the high-water mark per target URL: after a scan completes (`/JSON/ascan/view/status/` returns `100`), the connector retrieves all alerts associated with that scan and records the scan ID in the HWM state table. Subsequent runs trigger a new scan; alerts from prior scans remain queryable for audit. No server-side `updated_at` incremental mode exists.

### Resource schema excerpt

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Alert identifier unique within the ZAP session. |
| `pluginId` | string | ZAP rule identifier; used as `rule_id` in `silver.findings`. |
| `name` | string | Human-readable rule name. |
| `risk` | string | Risk level: `Informational`, `Low`, `Medium`, `High`. |
| `confidence` | string | Scanner confidence: `False Positive`, `Low`, `Medium`, `High`, `Confirmed`. |
| `url` | string | Target URL where the finding was observed; joins to `silver.deployments` for application linkage. |
| `param` | string | Request parameter or location exercised. |
| `attack` | string | Attack payload sent. |
| `evidence` | string | Response snippet that matched the rule. |
| `cweid` | integer | CWE identifier. |
| `wascid` | integer | WASC threat classification. |
| `solution` | string | Remediation guidance. |
| `description` | string | Finding description. |

### Enumerations

**Risk levels (4).** `Informational`, `Low`, `Medium`, `High`. Mapped to canonical severity: `Informational` → `info`, `Low` → `low`, `Medium` → `medium`, `High` → `high`. No direct `critical` equivalent; promotion to `critical` is driven by CWE class and KEV overlap in the canonical mapping.

**Confidence.** `False Positive`, `Low`, `Medium`, `High`, `Confirmed`. Preserved verbatim in Bronze. Records with `False Positive` confidence are retained for audit and excluded from the gold active-threat view.

### Quirks

**URL-based findings require deployment metadata for application linkage.** Unlike SAST, ZAP findings reference a URL, not a repository. The canonical join resolves `url` against `silver.deployments` (host, path prefix) to recover the owning application; unmatched URLs are emitted as `orphaned_dast_findings` for inventory-gap analysis.

**Scans are expensive; orchestration is per-deployment, not per-commit.** Active scans measured in minutes-to-hours preclude per-commit invocation. The reference implementation schedules ZAP scans on deployment events (new environment, release promotion) or nightly against staging environments, not on every commit.

## Setup

### Configuration

Terraform provisions the OWASP ZAP integration automatically:

- Long-lived ZAP daemon Deployment in the `zap` namespace, exposed via LoadBalancer (see `terraform output zap_url`).
- `mvp-connectors` secret scope keys: `zap_url`, `zap_api_key`.
- Juice Shop `.github/workflows/cicd.yml` includes a ZAP baseline step that uploads to `s3://<bucket>/cicd/zap/`.
- Scheduled `mvp-owasp-zap` Databricks job.

### Bundle deployment

The OWASP ZAP Databricks job is created by `terraform apply` in `infra/terraform`. See [Platform → Bundle deploy](../../platform/bundle-deploy.md) for the full apply order.

### First run

**On-demand path** (against an already-deployed Juice Shop):

```bash
ZAP_URL=$(terraform -chdir=infra/terraform output -raw zap_url)
ZAP_KEY=$(terraform -chdir=infra/terraform output -raw zap_api_key)
TARGET="http://$(terraform -chdir=infra/terraform output -raw juiceshop_ingress_host)"

# Start a spider+active-scan; then pull alerts.
curl "$ZAP_URL/JSON/spider/action/scan/?apikey=$ZAP_KEY&url=$TARGET"
sleep 180
curl "$ZAP_URL/JSON/alert/view/alerts/?apikey=$ZAP_KEY" > zap-alerts.json
```

**CI/CD-step path:** push to Juice Shop triggers the workflow, which runs ZAP baseline and uploads to `s3://<bucket>/cicd/zap/` (same trigger as Semgrep CI/CD).

Then trigger the Databricks ingest:

```bash
JOB_ID=$(terraform -chdir=infra/terraform output -json connector_job_ids | jq -r '.owasp_zap')
databricks jobs run-now --job-id "$JOB_ID"
```

Before expecting DAST rows, confirm Juice Shop is live:

```bash
HOST=$(terraform -chdir=infra/terraform output -raw juiceshop_ingress_host)
curl -fsSL "http://$HOST/" | grep -i 'juice'
```

If the hostname is still `pending`, the LoadBalancer hasn't provisioned yet — wait and re-check.

Observe bronze → silver:

```sql
SELECT count(*) FROM appsec_dev.silver.findings
  WHERE tool_source='owasp_zap';

SELECT trigger_context, url, rule_id_native, severity_canonical, file_path
  FROM appsec_dev.silver.findings WHERE tool_source='owasp_zap' LIMIT 10;
```

Expected: `file_path IS NULL` and `url` populated for every row. This is the shape-variety claim for the [finding-shape variety evidence scenario](../../analytics/evidence.md#evidence-3-finding-shape-variety).

**Role in the evidence story.** Supplies the **finding-shape variety** evidence for the [finding-shape variety scenario](../../analytics/evidence.md#evidence-3-finding-shape-variety) — URL-based findings with `file_path = NULL` flowing through the same Silver→Gold pipeline as the code-level SAST findings. Additionally demonstrates the CI/CD-step pattern: the Juice Shop pipeline runs `zap-baseline.py` against the freshly-deployed app.

**Normalization spot-check.**

- ZAP `risk = 'High'` → `severity_canonical = 'high'`.
- ZAP `cweid = '79'` → `cwe_id = 'CWE-79'`.

**Troubleshooting.**

| Symptom | Fix |
|---|---|
| ZAP API `403 Forbidden` | `api.key` mismatch — rotate `random_password.zap_api_key` via `terraform taint`/`apply`. |
| Scan never completes | Juice Shop deployment not yet running — the CI/CD pipeline must complete before scheduling scans. |
| Empty `cicd/zap/` prefix | GitHub Actions workflow failed — inspect the GitHub Actions run. |
| `file_path` populated (not NULL) | Transform bug — ZAP mapping must leave `file_path` NULL. See `src/connectors/owasp_zap/mapping.yml`. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | — | N/A |
| `REQ-ING-PAG` | — | N/A |
| `REQ-ING-RL` | — | N/A |
| `REQ-ING-HWM` | `src/connectors/owasp_zap/tests/test_ingest.py::test_s3_marker_resume_after_last_processed_key` | PASS |
| `REQ-TRF-MAP` | `src/connectors/owasp_zap/tests/test_transform.py::test_zap_alert_mapping` | PASS |
| `REQ-TRF-SEV` | `src/connectors/owasp_zap/tests/test_transform.py::test_risk_to_severity_normalization` | PASS |
| `REQ-TRF-STS` | `src/connectors/owasp_zap/tests/test_transform.py::test_confidence_to_status_normalization` | PASS |
| `REQ-TRF-TS` | `src/connectors/owasp_zap/tests/test_transform.py::test_scan_timestamp_to_utc_datetime` | PASS |
| `REQ-DQ` | `src/connectors/owasp_zap/tests/test_transform.py::test_findings_expectation_quarantines_null_url` | PASS |
| `REQ-DEDUP` | `src/connectors/owasp_zap/tests/test_transform.py::test_dedup_links_against_dast_overlap` | PASS |

Collected 7 requirement-bound tests via `pytest src/connectors/owasp_zap/tests/ -v --tb=short` (2026-04-22, 2.9 s wall-clock); 7 passed, 3 marked `N/A` because the CLI-artifact ingestion path has no API auth, pagination, or upstream rate limit.

### Tests

Tests live under [`src/connectors/owasp_zap/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/owasp_zap/tests). The report table above is the per-REQ outcome of running the bound tests in that directory.
