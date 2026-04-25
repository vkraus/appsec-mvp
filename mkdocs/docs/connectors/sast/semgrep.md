# Semgrep

## Overview

Semgrep is the primary standalone SAST tool in the reference implementation. Operational pattern: **CI/CD-step** in Docker-hosted mode (per-commit or per-CI/CD-run scans, commit SHA as high-water mark); **periodic-global** in Cloud Platform mode (server-side `updated_at` polling). The reference implementation targets the free open-source Semgrep engine running in a long-lived Docker container, which is the free-tier path most enterprises will actually run. Findings populate `silver.findings`.

Two modes are supported. In the canonical **Docker-hosted mode** the Semgrep CLI runs inside a container deployed either as a CI/CD step or as a long-running service; the container writes JSON or SARIF scan artifacts to a known output location (a mounted volume, an artifact store, or a lightweight HTTP fetcher layered on top of the container), and the connector collects them on a schedule. In **Cloud Platform mode** the connector authenticates to Semgrep Cloud Platform and pulls findings via its REST API. Cloud Platform is optional and adds persistent finding state, triage history, and SCA findings; it requires a paid subscription. Organizations with only the free tier use Docker-hosted mode exclusively and rely on Bronze-to-Silver deduplication to reconstruct finding continuity across scans.

**Category:** SAST (Cloud server + Docker CLI; CI/CD-step) · **Integration pattern:** REST + dlt (Cloud); artifact path (Docker)

The MVP connector implements the Docker-hosted artifact-path mode only: the bronze reader ingests JSON scan outputs written by an EKS CronJob (periodic) and by the Juice Shop GitHub Actions pipeline (CI/CD-step) under two S3 prefixes, distinguished by `trigger_context`. Cloud Platform mode is documented under Reference as intended scope but is not implemented in the MVP.

## Prerequisites

Platform-level prerequisites (AWS, Databricks workspace, Terraform tooling) are covered once in [Platform → Prerequisites](../../platform/prerequisites.md). The Semgrep-specific handoffs required before `terraform apply` are:

- **Shared artifact bucket.** Terraform provisions a single S3 bucket that receives Semgrep scan artifacts under two prefixes: `periodic/semgrep/` (written by the EKS CronJob) and `cicd/semgrep/` (written by the Juice Shop GitHub Actions pipeline). Both land in the same bronze table distinguished by `trigger_context`.
- **Periodic scanner on EKS.** Terraform deploys a Semgrep namespace on the EKS cluster with a CronJob (fires every 6 hours) and an IRSA role granting the pod S3 write access. Requires a `GH_PAT` in the `semgrep-env` secret with read access to the SAST seed repos so the pod can `git clone` before scanning.
- **CI/CD-step integration.** The Juice Shop repo's `.github/workflows/cicd.yml` runs `semgrep scan` on each push and uploads results to S3 via an OIDC-assumed role. Terraform creates the trust policy binding GitHub Actions to the artifact bucket ARN.
- **Credential provisioning.** The `mvp-connectors` Databricks secret scope holds the shared credentials used by the Databricks ingest job to read the S3 artifact bucket.

## Reference

### API surface

In **Docker-hosted mode** the connector makes no network calls to a Semgrep-operated API. The container is built from the upstream `returntocorp/semgrep` image and invoked as `semgrep scan --json` or `semgrep scan --sarif` (SARIF 2.1.0). Scan artifacts are written to a known output location: a volume mounted at `/out`, an object-storage bucket, or a sidecar HTTP server exposing a `GET /scans/{id}/results` endpoint on top of the container's writable filesystem. The connector's "API surface" at this point is the artifact-retrieval mechanism chosen by the deployment; the reference implementation treats volume-mounted filesystem collection (indexed by scan timestamp) as the default. The reference implementation defaults to JSON because it is Semgrep's native format and exposes metadata fields (`metadata.cwe`, `metadata.owasp`) sometimes dropped in the SARIF translation.

In **Cloud Platform mode** the API is at `https://semgrep.dev/api/v1`. Authentication uses a deployment-scoped API token as a Bearer value; the token is stored in Databricks Secrets. All findings endpoints require the deployment slug as a path parameter.

- `GET /deployments` — enumerates the deployments accessible to the authenticated token; the connector reads the slug from the response to validate that the configured deployment name matches the token's scope.
- `GET /deployments/{slug}/projects` — lists all projects (repositories) enrolled in the deployment; provides the project inventory that drives per-project filtering in subsequent calls.
- `GET /deployments/{slug}/findings` — retrieves SAST findings across the deployment, with server-side filtering by project, severity, triage state, and date range.
- `GET /deployments/{slug}/sca` — retrieves SCA findings (dependency vulnerabilities) detected by the Semgrep Supply Chain scanner; writes into `silver.findings` with `category = 'sca'` (alongside the `sast` records produced by the main findings endpoint).

### Pagination and rate limits

Docker-hosted mode has no API pagination and no server-side rate limit. Scan throughput is bounded by container CPU allocation and repository size; large monorepos scale horizontally by running multiple container replicas across the repository inventory. The connector iterates the artifact directory (or object-storage prefix, or HTTP result index) and processes each scan artifact independently.

The Cloud Platform API uses cursor-based pagination. Requests take `page` and `page_size`; responses expose `hasNextPage` and the cursor to pass as `page` on the next request. The connector advances until `hasNextPage` is false.

> **Verify:** Confirm the exact pagination parameter names for the Semgrep Cloud Platform API (`page` and `page_size` vs. `cursor` and `after` vs. another scheme); the pagination interface may have changed since the source documentation was written.

Cloud Platform rate limits vary by subscription tier and are not published as a single figure. The connector records `X-RateLimit-Remaining`/`X-RateLimit-Reset` where present and applies exponential backoff with jitter on HTTP 429. The initial backfill is the only sustained high-throughput window; incremental runs consume far fewer requests.

> **Verify:** Confirm that the Semgrep Cloud Platform API returns `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers on rate-limited responses; the exact header names should be verified against the current Cloud Platform API reference.

### Incremental hook

Docker-hosted mode is stateless: each `semgrep scan` invocation is a complete snapshot with no reference to prior scans. The connector treats every scan artifact as a full-reload input and uses the artifact's commit SHA (for CI/CD-step deployments) or scan-start timestamp (for long-running service deployments) as the high-water mark for incremental ingestion. Bronze-to-Silver deduplication via the SAST dedup key `(repository_id, file_path, rule_id, line_number)` reconstructs finding continuity across scans. This is the same full-reload-with-commit-SHA pattern used for TruffleHog.

The Cloud Platform findings endpoint supports `since_date` (ISO 8601), restricting results to findings first seen or modified after that date. Each finding carries `first_seen_scan_id` and `updated_at` (most recent state change). The connector records the maximum `updated_at` per run and supplies it as `since_date` on the next. No webhook is exposed by the Cloud Platform API at the time of writing, so scheduled `updated_at`-filtered polling is the canonical Cloud Platform incremental strategy. The webhook-preferred rule falls through to high-water-mark polling, which is adequate given per-scan cadence.

> **Verify:** Confirm that no webhook or event-streaming interface is available on the Semgrep Cloud Platform API at the time of publication; the product roadmap may have introduced an event notification mechanism after the documentation entry was written.

### Resource schema excerpt

The fields below are the subset consumed by the connector; complete schemas are in the upstream Semgrep documentation.

**Semgrep Cloud Platform `/deployments/{slug}/findings` consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Finding identifier; stable within the deployment; primary key in `bronze.semgrep_findings`. |
| `rule_name` | string | Semgrep rule identifier (e.g. `p/semgrep-misconfig` for a registry rule or the relative path for a custom rule); used as `rule_id` in `silver.findings`. |
| `severity` | string | Cloud Platform severity vocabulary: `high`, `medium`, `low`, `info`, or `experiment` (see Enumerations). |
| `state` | string | Lifecycle state of the finding within the platform (see Enumerations). |
| `repository.name` | string | Repository name as enrolled in the deployment; used to join to `silver.repositories`. |
| `repository.url` | string | Repository URL; stored as a domain column for cross-source join resolution. |
| `location.file_path` | string | Repository-relative path to the file containing the finding. |
| `location.line` | integer | Line number of the finding within the file. |
| `location.column` | integer | Column number of the finding; preserved for precision tooling integrations. |
| `first_seen_scan_id` | string | Identifier of the scan in which the finding was first detected; used to reconstruct scan history. |
| `triage_state` | string | Triage disposition applied by a human reviewer (see Enumerations). |
| `confidence` | string | Scanner-assigned confidence level: `high`, `medium`, or `low` (see Enumerations). |
| `categories` | array of strings | Semantic categories assigned by the rule author (e.g. `security`, `correctness`); stored in `raw_metadata` for gold-layer filtering. |

The CLI JSON output (`semgrep scan --json`) uses a different top-level structure from the Cloud Platform response. The connector maps CLI fields to the same Bronze schema so that Bronze-to-Silver operates uniformly regardless of mode.

**Semgrep CLI JSON output consumed fields (alternative ingestion path)**

| Field | Type | Meaning |
|---|---|---|
| `results[].check_id` | string | Rule identifier; maps to `rule_id` in `silver.findings`, equivalent to `rule_name` in Cloud mode. |
| `results[].path` | string | Repository-relative file path; maps to `location.file_path`. |
| `results[].start.line` | integer | Start line of the finding; maps to `location.line`. |
| `results[].end.line` | integer | End line of the matched code region; stored as a domain column for display purposes. |
| `results[].extra.severity` | string | CLI severity vocabulary: `INFO`, `WARNING`, or `ERROR` (see Enumerations). |
| `results[].extra.metadata.cwe` | array of strings | CWE identifiers associated with the rule; the connector stores the first element as `cwe_id` and the remainder in `raw_metadata`. |
| `results[].extra.metadata.owasp` | array of strings | OWASP category identifiers; handled identically to `metadata.cwe`. |
| `results[].extra.metadata.confidence` | string | Scanner-assigned confidence; maps to `confidence` in the Bronze schema. |
| `results[].extra.lines` | string | The matched source code snippet; stored in `raw_metadata` for triage tooling. |

### Enumerations

**Severity vocabularies.** Cloud Platform and CLI use distinct severity vocabularies that cannot be unified without loss. Cloud Platform: `high`, `medium`, `low`, `info`, `experiment`. CLI: `ERROR`, `WARNING`, `INFO`. The reference implementation maintains `config/severity/semgrep-cloud.yml` and `config/severity/semgrep-cli.yml`, selected by the connector's `deployment_mode`. Two files keep each vocabulary independently reviewable and avoid conditional branching.

> **Verify:** Confirm the complete Cloud Platform severity vocabulary (`high`, `medium`, `low`, `info`, `experiment`) against the current Semgrep Cloud Platform API documentation; the `experiment` value in particular may be a transitional label that has been retired or renamed.

**Finding state.** Cloud Platform findings have a `state` field with documented values `open` (active, unaddressed) and `removed` (no longer detected, typically due to code change). The connector maps these via `config/status/semgrep.yml`.

> **Verify:** Confirm the full enumeration of the `state` field on Cloud Platform findings; additional lifecycle values (e.g., `fixed`) may exist in the current API that are not reflected here.

**Triage state.** `triage_state` records reviewer disposition: `untriaged`, `ignored` (suppressed without remediation), `muted` (temporarily suppressed, typically via source annotation), `reviewing`, `fixed`. The connector preserves it as a domain column; gold-layer scoring may weight by it.

> **Verify:** Confirm the complete `triage_state` enumeration (`untriaged`, `ignored`, `muted`, `reviewing`, `fixed`) against the current Semgrep Cloud Platform API documentation; the exact set of values may differ on newer API versions.

**Confidence.** Both modes expose `high`/`medium`/`low`. The confidence vocabulary is consistent across modes and shares a single lookup reference.

### Quirks

**CLI mode is stateless.** Each `semgrep scan` is a complete snapshot with no cross-invocation identifier equivalent to the Cloud Platform's integer `id`. Cross-scan deduplication is the connector's responsibility, using the SAST key (`repository_id, file_path, rule_id, line_number`).

**Divergent severity vocabularies.** The Cloud Platform five-level and CLI three-level scales share no common token. Merging into a single lookup would require mode-conditional branching, which the framework avoids by keeping mapping files declarative. The two-file approach (`semgrep-cloud.yml`, `semgrep-cli.yml`) is selected at runtime via `deployment_mode`.

**Stable rule identifiers.** Registry rules use `p/<registry-id>` (e.g., `p/semgrep-misconfig`); custom rules use the relative file path to the rule definition. Both forms are used verbatim as `rule_id` without normalization, because they are globally unique within a deployment.

> **Verify:** Confirm that Semgrep registry rule identifiers consistently use the `p/<registry-id>` prefix format and that custom rule identifiers use the relative file path; the exact format may differ for rules installed from private registries or rule packs.

## Setup

### Configuration

Terraform provisions the Semgrep integration automatically:

- Semgrep namespace on EKS with a CronJob (`*/6 hours`).
- IRSA role granting the Semgrep pod S3 write access.
- Juice Shop repo's `.github/workflows/cicd.yml` with a Semgrep step + S3 upload.
- Shared artifact bucket and the `mvp-connectors` secret scope.
- Scheduled `mvp-semgrep` Databricks job.

### Bundle deployment

The Semgrep Databricks job is created by `terraform apply` in `infra/terraform`. See [Platform → Terraform apply](../../platform/terraform-apply.md) for the full apply order.

### First run

**Periodic:** wait for the next CronJob firing, or force one:

```bash
kubectl -n semgrep create job --from=cronjob/semgrep-periodic semgrep-manual-1
kubectl -n semgrep logs -f job/semgrep-manual-1
```

**CI/CD-step:** push a commit (or empty commit) to the Juice Shop repo:

```bash
git clone "https://github.com/<org>/juiceshop" && cd juiceshop
git commit --allow-empty -m "trigger cicd"
git push
```

Watch the workflow in GitHub Actions UI; ~6 minutes end-to-end.

Then trigger the Databricks ingest:

```bash
JOB_ID=$(terraform -chdir=infra/terraform output -json connector_job_ids | jq -r '.semgrep')
databricks jobs run-now --job-id "$JOB_ID"
```

Observe bronze → silver:

```sql
-- Periodic
SELECT count(*) FROM appsec_dev.silver.findings
  WHERE tool_source='semgrep' AND trigger_context='periodic';

-- CI/CD-step
SELECT count(*) FROM appsec_dev.silver.findings
  WHERE tool_source='semgrep' AND trigger_context='cicd';

-- Both contexts, same rule on same line — the cross-context dedup surface
SELECT trigger_context, count(*)
  FROM appsec_dev.silver.findings
  WHERE tool_source='semgrep' GROUP BY trigger_context;
```

**Role in the evidence story.** Dedup partner B for the [cross-tool deduplication evidence](../../analytics/evidence.md#evidence-1-cross-tool-deduplication) *and* the CI/CD-step exemplar for operational-pattern coverage. Runs in **two modes** simultaneously:

1. **Periodic-global** — an EKS CronJob scans all registered seed repos every 6 hours, writing results to `s3://<bucket>/periodic/semgrep/`.
2. **CI/CD-step** — the Juice Shop GitHub Actions pipeline runs `semgrep scan` on each push, writing results to `s3://<bucket>/cicd/semgrep/`.

Both paths land in the same `silver.findings` table under `tool_source='semgrep'`, distinguished by `trigger_context`.

**Normalization spot-check.**

- Semgrep CLI `severity = 'ERROR'` → `severity_canonical = 'high'` (via `config/severity/semgrep-cli.yml`).
- Semgrep `extra.metadata.cwe = ['CWE-89']` → `cwe_id = 'CWE-89'`.

**Troubleshooting.**

| Symptom | Fix |
|---|---|
| Periodic pod `CrashLoopBackoff` | Inspect logs; most commonly `git clone` fails — verify `GH_PAT` in the `semgrep-env` secret has read access to the seed repos. |
| CI/CD step `AccessDenied` on S3 upload | GitHub Actions OIDC role not trusted for the artifact bucket — check `aws_iam_role_policy.github_actions` resource Region allowlist for the S3 bucket ARN. |
| 0 rows in bronze after successful runs | Bronze reader only scans `periodic/semgrep/` + `cicd/semgrep/` — make sure the script is writing under those exact prefixes. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | — | N/A (CLI-artefact path — "no API auth, pagination, or rate limit" per catalog) |
| `REQ-ING-PAG` | — | N/A (CLI-artefact path — "no API auth, pagination, or rate limit" per catalog) |
| `REQ-ING-RL` | — | N/A (CLI-artefact path — "no API auth, pagination, or rate limit" per catalog) |
| `REQ-ING-HWM` | `tests/connectors/semgrep/test_prefix_reader.py::test_classify_prefix[periodic/...]`, `::test_classify_prefix[cicd/...]`, `::test_classify_prefix_rejects_unknown` | PASS |
| `REQ-TRF-MAP` | — | (pending) — transform stub; bound test pending real transform implementation |
| `REQ-TRF-SEV` | — | (pending) — transform stub; bound test pending real transform implementation |
| `REQ-TRF-STS` | — | (pending) — transform stub; bound test pending real transform implementation |
| `REQ-TRF-TS` | — | (pending) — transform stub; bound test pending real transform implementation |
| `REQ-DQ` | — | (pending) — transform stub; bound test pending real transform implementation |
| `REQ-DEDUP` | — | (pending) — transform stub; bound test pending real transform implementation |
| `REQ-FW-CONTRACT` | `tests/connectors/semgrep/test_contract_wrappers.py::test_ingest_wrapper_has_contract_signature`, `::test_transform_wrapper_has_contract_signature` | PASS |
| `REQ-FW-BRONZE-ENVELOPE` | `tests/connectors/semgrep/test_contract_wrappers.py::test_run_ingest_pipeline_accepts_run_id_kwarg` | PASS |

Collected 6 requirement-bound tests via `pytest tests/connectors/semgrep/ -v --tb=short` (2026-04-25, 0.29 s wall-clock); 6 passed; 3 marked N/A (CLI-artefact path — no API auth, pagination, or rate limit per `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix"); 6 marked (pending) because the transform implementation is deferred — aspirational REQ bindings (`REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`) are documented under §4 Future Work and will be bound once the real transform ships. Phase 2 retrofit deliberately did not add aspirational tests for unimplemented transform code.

### Tests

Tests live under [`tests/connectors/semgrep/`](https://github.com/vkraus/appsec-mvp/tree/main/tests/connectors/semgrep). The report table above is the per-REQ outcome of running the bound tests in that directory.

## Generation log

This connector page was reconciled by the connector-lifecycle skills under the retrofit-9-connectors work; the Reference and Validation sections preserve the original implementation-grounded prose, and the Generation log table records the actual skill runs that produced the reconciled artefacts.

| Stage              | Skill                              | Inputs                                                                | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (sast)            | name=Semgrep; url=https://semgrep.dev/api/v1/docs; category=sast      | mkdocs/docs/connectors/sast/semgrep.md §1–§3                                       | 2026-04-25 | d47eb26 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (sast)        | page hash=72c0eb36b9f8                                           | src/connectors/semgrep/, tests/connectors/semgrep/, config/severity/semgrep.yml, config/status/semgrep.yml, resources/semgrep-job.yml | 2026-04-25 | 15935ca (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (sast)   | module path=src/connectors/semgrep/                                   | mkdocs/docs/connectors/sast/semgrep.md §5                                          | 2026-04-25 | ef600a8 (retrofit-9-connectors)          |
