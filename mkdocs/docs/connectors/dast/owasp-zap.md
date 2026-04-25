# OWASP ZAP

## What this connector ingests

OWASP ZAP is the reference DAST source in the framework. Operational pattern: **on demand scan lifecycle**. Each spider, active, or passive scan is a discrete job, orchestrated by the connector against target URLs drawn from the application inventory and read back as alert sets after scan completion. The connector populates `silver.findings` from the ZAP alerts API, with findings linked to applications via target URL resolved in reverse against `silver.deployments`.

**Category:** DAST · **Integration pattern:** SDK (python-owasp-zap-v2.4) for the on demand path. Artifact path for the CI/CD step path.

Bronze schema: `bronze_owasp_zap` with the `zap_artifacts` external volume reading from `s3://${ARTIFACT_BUCKET}/zap/`. Cross-source contribution: `silver.findings` with `tool_source = 'owasp_zap'` and `file_path = NULL` (URL based findings).

The MVP connector implements the CI/CD step artifact path mode. The bronze reader ingests JSON alert dumps written under the `zap/` S3 prefix, tagged with `trigger_context = 'cicd'`. The on demand SDK driven path against a long-lived ZAP daemon is documented under Reference as intended scope and is scaffolded in `src/connectors/owasp_zap/ingest.py`, but is not wired into the MVP ingest run.

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, the `silver` schema, and the UC external location pointing at `s3://${ARTIFACT_BUCKET}/` (created by [Secrets bootstrap](../../platform/secrets-bootstrap.md)) must exist. See [Setup platform](../../platform/index.md) if Phase 1 is not yet complete.
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** ZAP findings carry a target URL rather than a repository directly. The documented join goes URL to `silver.deployments` to application to `silver.app_repo` to `silver.repositories`. Without an SCM connector first, the cross-source rollups in [Evidence scenarios](../../analytics/evidence.md) cannot resolve.

## User inputs

| Input | Where to obtain | Used as |
|---|---|---|
| ZAP daemon URL | Running ZAP instance of the user, or the `zap_url` output of the optional source runtime. | Env var `ZAP_URL` consumed by `src/connectors/owasp_zap/scripts/load-secrets.sh`. Written to secret key `zap_url`. |
| ZAP API key | The 40 character value configured at daemon startup via `-config api.key=<value>`. The optional runtime mints a random key and stores it in a Kubernetes secret. | Env var `ZAP_API_KEY`. Written to secret key `zap_api_key`. |
| Artifact bucket | Same `ARTIFACT_BUCKET` registered in [Secrets bootstrap](../../platform/secrets-bootstrap.md). The storage location of the `zap_artifacts` volume reads `s3://${var.artifact_bucket}/zap/`. | DAB var `artifact_bucket` at `bundle deploy`. |

## Reference

### API

ZAP exposes a REST API on the daemon host (default port 8080) at `/JSON/<component>/<view|action>/<operation>/`. Relevant components for the connector: `spider` (crawl target), `ascan` (active scan), `pscan` (passive scan configuration), `core` (alerts, messages, sessions), and `alert` (alert details). Authentication uses a pre-shared API key supplied via `X-ZAP-API-Key` header or `apikey` query parameter, configured at daemon startup with `-config api.key=<value>`. Responses are JSON. XML and HAR formats are also supported for alerts.

### Pagination and rate limits

Alert retrieval endpoints (`/JSON/core/view/alerts/` and `/JSON/alert/view/alertsByRisk/`) accept `start` and `count` offset parameters. The connector iterates with a fixed `count=500` until an empty response. The daemon has no enforced request rate limit beyond host resources. The connector self-regulates concurrent scans via `ascan.setOptionMaxScansInUI` to bound daemon load.

### Incremental hook

ZAP alerts are scoped to a scan. The connector uses the numeric scan `scanId` as the high-water mark per target URL. After a scan completes (`/JSON/ascan/view/status/` returns `100`), the connector retrieves all alerts associated with that scan and records the scan ID in the HWM state table. Subsequent runs trigger a new scan. Alerts from prior scans remain queryable for audit. No server-side `updated_at` incremental mode exists.

### Resource schema excerpt

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Alert identifier unique within the ZAP session. |
| `pluginId` | string | ZAP rule identifier. Used as `rule_id` in `silver.findings`. |
| `name` | string | Human readable rule name. |
| `risk` | string | Risk level: `Informational`, `Low`, `Medium`, `High`. |
| `confidence` | string | Scanner confidence: `False Positive`, `Low`, `Medium`, `High`, `Confirmed`. |
| `url` | string | Target URL where the finding was observed. Joins to `silver.deployments` for application linkage. |
| `param` | string | Request parameter or location exercised. |
| `attack` | string | Attack payload sent. |
| `evidence` | string | Response snippet that matched the rule. |
| `cweid` | integer | CWE identifier. |
| `wascid` | integer | WASC threat classification. |
| `solution` | string | Remediation guidance. |
| `description` | string | Finding description. |

### Enumerations

**Risk levels (4).** `Informational`, `Low`, `Medium`, `High`. Mapped to documented severity: `Informational` to `info`, `Low` to `low`, `Medium` to `medium`, `High` to `high`. No direct `critical` equivalent. Promotion to `critical` is driven by CWE class and KEV overlap in the documented mapping.

**Confidence.** `False Positive`, `Low`, `Medium`, `High`, `Confirmed`. Preserved verbatim in Bronze. Records with `False Positive` confidence are retained for audit and excluded from the gold active threat view.

### Quirks

**URL based findings require deployment metadata for application linkage.** Unlike SAST, ZAP findings reference a URL, not a repository. The documented join resolves `url` against `silver.deployments` (host, path prefix) to recover the owning application. Unmatched URLs are emitted as `orphaned_dast_findings` for inventory gap analysis.

**Scans are expensive. Orchestration is per deployment, not per commit.** Active scans measured in minutes to hours preclude invocation on each commit. The reference implementation schedules ZAP scans on deployment events (new environment, release promotion) or nightly against staging environments, not on every commit.

## Optional source runtime

If you want appsec-mvp to deploy a long-lived ZAP daemon on your EKS cluster (exposed via LoadBalancer with a randomly generated 40 character API key), apply the optional runtime under `src/connectors/owasp_zap/runtime/`. See [`src/connectors/owasp_zap/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/owasp_zap/runtime) for variables and the public LB security note (the upstream demo configuration whitelists all caller IPs against the ZAP API and relies on the API key for access control. Production deployments should harden this).

Users with their own ZAP instance skip the runtime. Wire the URL and API key of the existing daemon directly via the next section.

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/owasp_zap/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
| `zap_url` | `ZAP_URL` | Public URL of the ZAP daemon (e.g. `http://lb-host:8080`). |
| `zap_api_key` | `ZAP_API_KEY` | 40 character API key configured on the daemon at startup. |

Run from repo root after Phase 1 completes:

```bash
export ZAP_URL="http://zap.example.com:8080"
export ZAP_API_KEY="..."
bash src/connectors/owasp_zap/scripts/load-secrets.sh
# OK: owasp_zap secrets loaded into scope mvp-connectors
```

## Run the job

The OWASP ZAP connector ingests scan artifacts from the `zap_artifacts` external volume. The volume points at `s3://${var.artifact_bucket}/zap/` and is created by `bundle deploy` (declared in `src/connectors/owasp_zap/resources/volumes.yml`).

Like semgrep, this connector currently has **no scheduled job**. The bundle deploys the bronze schema and volume so the ingest path exists, but the connector ingest entry point is scaffolded as a notebook stub. The on demand SDK path is also a stub.

Once the job resource lands, the one-shot orchestration wrapper is:

```bash
bash src/connectors/owasp_zap/scripts/install.sh
```

To populate Bronze in the meantime, ensure scan artifacts land in the prefix of the volume.

**On demand path** (against an user running ZAP daemon and live target):

```bash
TARGET="http://my-target-app.example.com"
# Start a spider+active-scan; then pull alerts.
curl "$ZAP_URL/JSON/spider/action/scan/?apikey=$ZAP_API_KEY&url=$TARGET"
sleep 180
curl "$ZAP_URL/JSON/alert/view/alerts/?apikey=$ZAP_API_KEY" > zap-alerts.json
# Upload zap-alerts.json to s3://<bucket>/zap/ondemand/<scan-id>/
```

**CI/CD step path:** the cross-scanner workflow at `examples/end-to-end-demo/.github/workflows/scan.yml` includes a ZAP baseline step that runs `zap-baseline.py` against a freshly deployed app and uploads results to `s3://<bucket>/zap/cicd/`. Push to a repo whose pipeline includes that step.

**Normalization spot check (target behaviour).**

- ZAP `risk = 'High'` maps to `severity_canonical = 'high'`.
- ZAP `cweid = '79'` maps to `cwe_id = 'CWE-79'`.

## Verify

```sql
-- Inspect raw scan artifacts via the volume.
LIST '/Volumes/appsec_dev/bronze_owasp_zap/zap_artifacts/';

-- Once the silver transform lands, the URL-based finding shape:
SELECT count(*) FROM appsec_dev.silver.findings
  WHERE tool_source='owasp_zap';

SELECT trigger_context, url, rule_id_native, severity_canonical, file_path
  FROM appsec_dev.silver.findings WHERE tool_source='owasp_zap' LIMIT 10;

-- Cross-source dependency check — every owasp_zap finding's repository_id
-- (resolved from URL via silver.deployments) should join to silver.repositories.
SELECT count(*) AS missing_repo
  FROM appsec_dev.silver.findings f
  LEFT JOIN appsec_dev.silver.repositories r USING (repository_id)
  WHERE f.tool_source='owasp_zap' AND r.repository_id IS NULL;
```

Expected: `file_path IS NULL` and `url` populated for every ZAP row. This is the structure variety claim for the [variety in finding structure evidence scenario](../../analytics/evidence.md#evidence-3-variety-in-finding-structure).

A non-zero `missing_repo` count means the URL to repository resolution for ZAP didn't complete. Typically because the SCM connector hasn't run, or because the URL doesn't appear in `silver.deployments`. Run [GitHub](../scm/github.md) (or another SCM) before relying on the rollups.

## Troubleshooting

| Symptom | Fix |
|---|---|
| ZAP API `403 Forbidden` | `zap_api_key` secret value doesn't match the `api.key` of the daemon. If using the optional runtime, the value is in the `zap-api-key` Kubernetes secret. `kubectl -n zap get secret zap-api-key -o jsonpath='{.data.ZAP_API_KEY}' \| base64 -d`. Re-load via `bash src/connectors/owasp_zap/scripts/load-secrets.sh`. |
| Scan never completes | Target app not reachable from the ZAP daemon. Confirm the URL responds: `curl -fsSL "$TARGET" \| head`. |
| Empty `zap/cicd/` prefix | GitHub Actions workflow failed. Inspect the run in the GitHub UI. |
| `file_path` populated (not NULL) | Transform bug. The ZAP mapping must leave `file_path` NULL. See `src/connectors/owasp_zap/mapping.yml`. |
| No rows in `silver.repositories` | No SCM connector has run yet. Install [GitHub](../scm/github.md) or another SCM connector and trigger its job before relying on the cross-source join. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | n/a | N/A |
| `REQ-ING-PAG` | n/a | N/A |
| `REQ-ING-RL` | n/a | N/A |
| `REQ-ING-HWM` | `src/connectors/owasp_zap/tests/test_transform.py::test_hwm_kind_artefact_prefix` | PASS |
| `REQ-TRF-MAP` | `src/connectors/owasp_zap/tests/test_transform.py::test_alert_mapping` | PASS |
| `REQ-TRF-SEV` | `src/connectors/owasp_zap/tests/test_transform.py::test_severity_normalization_all_four_levels` | PASS |
| `REQ-TRF-STS` | `src/connectors/owasp_zap/tests/test_transform.py::test_status_always_open` | PASS |
| `REQ-TRF-TS` | `src/connectors/owasp_zap/tests/test_transform.py::test_first_seen_at_is_utc_aware` | PASS |
| `REQ-DQ` | `src/connectors/owasp_zap/tests/test_transform.py::test_findings_expectation_quarantines_malformed` | PASS |
| `REQ-DEDUP` | `src/connectors/owasp_zap/tests/test_transform.py::test_dedup_key_tuple_matches_mapping_yml` | PASS |

Collected 14 requirement-bound tests via `pytest src/connectors/owasp_zap/tests/ -v --tb=short` (2026-04-25, 21.5 s wall-clock). 14 passed; 3 are marked `N/A` because the CLI artifact ingestion path has no API auth, pagination, or upstream rate limit.

### Tests

Tests live under [`src/connectors/owasp_zap/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/owasp_zap/tests). The report table above is the outcome for each REQ from running the bound tests in that directory.

## Generation log

This connector page was reconciled by the connector lifecycle skills under the retrofit-9-connectors work. The Reference and Validation sections preserve the original implementation grounded prose, and the Generation log table records the actual skill runs that produced the reconciled artefacts.

| Stage              | Skill                              | Inputs                                                                | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (dast)            | name=OWASP ZAP; url=https://www.zaproxy.org/docs/api/; category=dast  | mkdocs/docs/connectors/dast/owasp-zap.md §1–§3                                     | 2026-04-25 | 662ee6a (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (dast)        | page hash=ed67875c66f7                                           | src/connectors/owasp_zap/, src/connectors/owasp_zap/tests/, src/connectors/owasp_zap/severity.yml, src/connectors/owasp_zap/status.yml, src/connectors/owasp_zap/resources/job.yml | 2026-04-25 | 24c745f (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (dast)   | module path=src/connectors/owasp_zap/                                 | mkdocs/docs/connectors/dast/owasp-zap.md §5                                        | 2026-04-25 | daa6d83 (production-shape-b)             |
