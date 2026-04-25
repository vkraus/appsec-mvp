# Semgrep

## What this connector ingests

Semgrep is the primary standalone SAST tool in the reference implementation. Operational pattern: **CI/CD-step** in Docker-hosted mode (per-commit or per-CI/CD-run scans, commit SHA as high-water mark); **periodic-global** in Cloud Platform mode (server-side `updated_at` polling). The reference implementation targets the free open-source Semgrep engine running in a long-lived Docker container, which is the free-tier path most enterprises will actually run. Findings populate `silver.findings`.

Two modes are supported. In the recommended **Docker-hosted mode** the Semgrep CLI runs inside a container deployed either as a CI/CD step or as a long-running service. The container writes JSON or SARIF scan artifacts to a known output location (a mounted volume, an artifact store, or a lightweight HTTP fetcher layered on top of the container), and the connector collects them on a schedule. In **Cloud Platform mode** the connector authenticates to Semgrep Cloud Platform and pulls findings via its REST API.

**Category:** SAST (Cloud server + Docker CLI; CI/CD-step) · **Integration pattern:** REST + dlt (Cloud); artifact path (Docker)

Bronze schema: `bronze_semgrep` with the `semgrep_artifacts` external volume reading from `s3://${ARTIFACT_BUCKET}/semgrep/`. Cross-source contribution: `silver.findings` with `tool_source = 'semgrep'`.

The MVP connector implements the Docker-hosted artifact-path mode only: the bronze reader ingests JSON scan outputs written under the `semgrep/` S3 prefix, distinguished by `trigger_context` (e.g. `periodic` vs `cicd`). Cloud Platform mode is documented under Reference as intended scope but is not implemented in the MVP.

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, the `silver` schema, and the UC external location pointing at `s3://${ARTIFACT_BUCKET}/` (created by [Secrets bootstrap](../../platform/secrets-bootstrap.md)) must exist. See [Setup platform](../../platform/index.md) if Phase 1 is not yet complete.
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** Semgrep findings are keyed by `(repository_id, file_path, rule_id)`; the `repository_id` value must resolve to a row in `silver.repositories` for downstream rollups to attribute findings to a repository (and through `silver.app_repo_mapping`, to a business application).

## User inputs

| Input | Where to obtain | Used as |
|---|---|---|
| Artifact bucket name | The S3 bucket the user created in [Prerequisites → AWS backbone](../../platform/prerequisites.md#aws-backbone-the-user-brings) and registered as a UC external location in [Secrets bootstrap](../../platform/secrets-bootstrap.md). | Env var `ARTIFACT_BUCKET` consumed by `src/connectors/semgrep/scripts/load-secrets.sh`; written to secret key `semgrep_artifact_bucket`. Also passed to `bundle deploy` as DAB var `artifact_bucket` so the `storage_location` of the volume resolves. |
| S3 prefix | Convention: `semgrep/`. The optional runtime writes under this prefix; CI/CD-step uploads should use the same prefix (or a sub-prefix). | Env var `SEMGREP_PREFIX` (default `semgrep/`); written to secret key `semgrep_artifact_prefix`. |

## Reference

### API scope

In **Docker-hosted mode** the connector makes no network calls to a Semgrep-operated API. The container is built from the upstream `returntocorp/semgrep` image and invoked as `semgrep scan --json` or `semgrep scan --sarif` (SARIF 2.1.0). Scan artifacts are written to a known output location: a volume mounted at `/out`, an object-storage bucket, or a sidecar HTTP server exposing a `GET /scans/{id}/results` endpoint on top of the writable filesystem of the container. The connector "API contract" at this point is the artifact-retrieval mechanism chosen by the deployment. The reference implementation treats volume-mounted filesystem collection (indexed by scan timestamp) as the default. The reference implementation defaults to JSON because it is the native format of Semgrep and exposes metadata fields (`metadata.cwe`, `metadata.owasp`) sometimes dropped in the SARIF translation.

In **Cloud Platform mode** the API is at `https://semgrep.dev/api/v1`. Authentication uses a deployment-scoped API token as a Bearer value. The token is stored in Databricks Secrets. All findings endpoints require the deployment slug as a path parameter.

- `GET /deployments`: enumerates the deployments accessible to the authenticated token. The connector reads the slug from the response to validate that the configured deployment name matches the scope of the token.
- `GET /deployments/{slug}/projects`: lists all projects (repositories) enrolled in the deployment. Provides the project inventory that drives per-project filtering in subsequent calls.
- `GET /deployments/{slug}/findings`: retrieves SAST findings across the deployment, with server-side filtering by project, severity, triage state, and date range.
- `GET /deployments/{slug}/sca`: retrieves SCA findings (dependency vulnerabilities) detected by the Semgrep Supply Chain scanner. Writes into `silver.findings` with `category = 'sca'` (alongside the `sast` records produced by the main findings endpoint).

### Pagination and rate limits

Docker-hosted mode has no API pagination and no server-side rate limit. Scan throughput is bounded by container CPU allocation and repository size; large monorepos scale horizontally by running multiple container replicas across the repository inventory. The connector iterates the artifact directory (or object-storage prefix, or HTTP result index) and processes each scan artifact independently.

The Cloud Platform API uses cursor-based pagination. Requests take `page` and `page_size`; responses expose `hasNextPage` and the cursor to pass as `page` on the next request. The connector advances until `hasNextPage` is false.

> **Verify:** Confirm the exact pagination parameter names for the Semgrep Cloud Platform API (`page` and `page_size` vs. `cursor` and `after` vs. another scheme); the pagination interface may have changed since the source documentation was written.

Cloud Platform rate limits vary by subscription tier and are not published as a single figure. The connector records `X-RateLimit-Remaining`/`X-RateLimit-Reset` where present and applies exponential backoff with jitter on HTTP 429. The initial backfill is the only sustained high-throughput window; incremental runs consume far fewer requests.

> **Verify:** Confirm that the Semgrep Cloud Platform API returns `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers on rate-limited responses; the exact header names should be verified against the current Cloud Platform API reference.

### Incremental hook

Docker-hosted mode is stateless: each `semgrep scan` invocation is a complete snapshot with no reference to prior scans. The connector treats every scan artifact as a full-reload input and uses the commit SHA of the artifact (for CI/CD-step deployments) or scan-start timestamp (for long-running service deployments) as the high-water mark for incremental ingestion. Bronze-to-Silver deduplication via the SAST dedup key `(repository_id, file_path, rule_id, line_number)` reconstructs finding continuity across scans. This is the same full-reload-with-commit-SHA pattern used for TruffleHog.

The Cloud Platform findings endpoint supports `since_date` (ISO 8601), restricting results to findings first seen or modified after that date. Each finding carries `first_seen_scan_id` and `updated_at` (most recent state change). The connector records the maximum `updated_at` per run and supplies it as `since_date` on the next. No webhook is exposed by the Cloud Platform API at the time of writing, so scheduled `updated_at`-filtered polling is the recommended Cloud Platform incremental strategy. The webhook-preferred rule falls through to high-water-mark polling, which is adequate given per-scan cadence.

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

**Severity vocabularies.** Cloud Platform and CLI use distinct severity vocabularies that cannot be unified without loss. Cloud Platform: `high`, `medium`, `low`, `info`, `experiment`. CLI: `ERROR`, `WARNING`, `INFO`. The reference implementation maintains `src/connectors/semgrep/severity-cloud.yml` and `src/connectors/semgrep/severity-cli.yml`, selected by the connector setting `deployment_mode`. Two files keep each vocabulary independently reviewable and avoid conditional branching.

> **Verify:** Confirm the complete Cloud Platform severity vocabulary (`high`, `medium`, `low`, `info`, `experiment`) against the current Semgrep Cloud Platform API documentation; the `experiment` value in particular may be a transitional label that has been retired or renamed.

**Finding state.** Cloud Platform findings have a `state` field with documented values `open` (active, unaddressed) and `removed` (no longer detected, typically due to code change). The connector maps these via `src/connectors/semgrep/status.yml`.

> **Verify:** Confirm the full enumeration of the `state` field on Cloud Platform findings; additional lifecycle values (e.g., `fixed`) may exist in the current API that are not reflected here.

**Triage state.** `triage_state` records reviewer disposition: `untriaged`, `ignored` (suppressed without remediation), `muted` (temporarily suppressed, typically via source annotation), `reviewing`, `fixed`. The connector preserves it as a domain column; gold-layer scoring may weight by it.

> **Verify:** Confirm the complete `triage_state` enumeration (`untriaged`, `ignored`, `muted`, `reviewing`, `fixed`) against the current Semgrep Cloud Platform API documentation; the exact set of values may differ on newer API versions.

**Confidence.** Both modes expose `high`/`medium`/`low`. The confidence vocabulary is consistent across modes and shares a single lookup reference.

### Quirks

**CLI mode is stateless.** Each `semgrep scan` is a complete snapshot with no cross-invocation identifier equivalent to the integer `id` from Cloud Platform. Cross-scan deduplication is the responsibility of the connector, using the SAST key (`repository_id, file_path, rule_id, line_number`).

**Divergent severity vocabularies.** The Cloud Platform five-level and CLI three-level scales share no common token. Merging into a single lookup would require mode-conditional branching, which the framework avoids by keeping mapping files declarative. The two-file approach (`semgrep-cloud.yml`, `semgrep-cli.yml`) is selected at runtime via `deployment_mode`.

**Stable rule identifiers.** Registry rules use `p/<registry-id>` (e.g., `p/semgrep-misconfig`); custom rules use the relative file path to the rule definition. Both forms are used verbatim as `rule_id` without normalization, because they are globally unique within a deployment.

> **Verify:** Confirm that Semgrep registry rule identifiers consistently use the `p/<registry-id>` prefix format and that custom rule identifiers use the relative file path; the exact format may differ for rules installed from private registries or rule packs.

## Optional source runtime

If you want appsec-mvp to run Semgrep on your EKS cluster as a periodic CronJob (clones a list of repos, runs `semgrep scan`, writes JSON findings to the artifact S3 bucket via IRSA), apply the optional runtime under `src/connectors/semgrep/runtime/`. See [`src/connectors/semgrep/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/semgrep/runtime) for variables (cluster, OIDC provider ARN, repo list, GitHub PAT for cloning), CronJob schedule, and IRSA setup.

Users with their own Semgrep deployment skip the runtime. Point any scanner that writes JSON results into `s3://${ARTIFACT_BUCKET}/semgrep/` (same prefix the connector reads from) and the connector picks them up.

For CI/CD-step usage, the cross-scanner workflow at `examples/end-to-end-demo/.github/workflows/scan.yml` shows a Semgrep step that uploads to `s3://<bucket>/cicd/semgrep/`. The end-to-end demo writes under `cicd/semgrep/`; periodic runners write under `periodic/semgrep/`. Both prefixes are subdirectories of the `semgrep/` root for this connector and are picked up by the same volume.

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/semgrep/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
| `semgrep_artifact_bucket` | `ARTIFACT_BUCKET` | S3 bucket name (no `s3://` prefix). |
| `semgrep_artifact_prefix` | `SEMGREP_PREFIX` (default `semgrep/`) | Prefix within the bucket the connector reads. |

Run from repo root after Phase 1 completes:

```bash
export ARTIFACT_BUCKET="my-appsec-mvp-artifacts"
# SEMGREP_PREFIX defaults to "semgrep/"; override only if non-default.
bash src/connectors/semgrep/scripts/load-secrets.sh
# OK: semgrep secrets loaded into scope mvp-connectors
```

## Run the job

The semgrep connector ingests scan artifacts from the `semgrep_artifacts` external volume. The volume points at `s3://${var.artifact_bucket}/semgrep/` and is created by `bundle deploy` (declared in `src/connectors/semgrep/resources/volumes.yml`).

This connector currently has **no scheduled job**. The bundle deploys the bronze schema and volume so the ingest path exists, but the connector ingest entry-point is scaffolded as a notebook stub. Once a job resource is added under `src/connectors/semgrep/resources/`, run it via:

```bash
databricks bundle run semgrep-connector --target dev
```

For a one-shot orchestration (load secrets + run + verify counts), use the wrapper:

```bash
bash src/connectors/semgrep/scripts/install.sh
```

To populate Bronze in the meantime, ensure scan artifacts land in the volume prefix:

**Periodic (optional runtime):** wait for the next CronJob firing, or force one:

```bash
kubectl -n semgrep create job --from=cronjob/semgrep-periodic semgrep-manual-1
kubectl -n semgrep logs -f job/semgrep-manual-1
```

**CI/CD-step:** push to a repository whose pipeline includes the Semgrep step from `examples/end-to-end-demo/.github/workflows/scan.yml`. Watch the workflow in the GitHub Actions UI; ~6 minutes end-to-end.

**Normalization spot-check (target behaviour).**

- Semgrep CLI `severity = 'ERROR'` → `severity_canonical = 'high'` (via `src/connectors/semgrep/severity-cli.yml`).
- Semgrep `extra.metadata.cwe = ['CWE-89']` → `cwe_id = 'CWE-89'`.

## Verify

```sql
-- Inspect raw scan artifacts via the volume.
LIST '/Volumes/appsec_dev/bronze_semgrep/semgrep_artifacts/';

-- Periodic vs CI/CD-step contexts (once the silver transform lands).
SELECT trigger_context, count(*)
  FROM appsec_dev.silver.findings
  WHERE tool_source='semgrep'
  GROUP BY trigger_context;

-- Cross-source dependency check — every semgrep finding's repository_id
-- should join to a silver.repositories row populated by an SCM connector.
SELECT count(*) AS missing_repo
  FROM appsec_dev.silver.findings f
  LEFT JOIN appsec_dev.silver.repositories r USING (repository_id)
  WHERE f.tool_source='semgrep' AND r.repository_id IS NULL;
```

A non-zero `missing_repo` count means Semgrep reports findings for repositories the SCM connector has not yet ingested. Run [GitHub](../scm/github.md) (or another SCM) before relying on the rollups in [Evidence scenarios](../../analytics/evidence.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `LIST` against the volume returns empty | No scan artifacts have landed under the S3 prefix of the volume yet. Trigger a scan via the optional runtime CronJob, or push a commit to a repo whose CI pipeline uploads to `s3://<bucket>/semgrep/cicd/`. |
| Periodic pod `CrashLoopBackoff` (optional runtime) | Inspect logs; most commonly `git clone` fails. Verify `GH_PAT` (`github_pat_for_clone`) in the runtime secret has read access to the target repos. |
| CI/CD-step `AccessDenied` on S3 upload | GitHub Actions OIDC role not trusted for the artifact bucket. Verify the trust policy binds the workflow repo and branch to a role with `s3:PutObject` on the bucket ARN. See the github runtime `optional` variable wiring at [`src/connectors/github/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/github/runtime). |
| Volume create fails on `bundle deploy` | UC external location not yet created. Run [Secrets bootstrap](../../platform/secrets-bootstrap.md) first, then re-deploy. |
| No rows in `silver.repositories` | No SCM connector has run yet. Install [GitHub](../scm/github.md) or another SCM connector and trigger its job before relying on the cross-source join. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | _(N/A — CLI-artefact connector reads S3 prefix; no API auth at the connector layer)_ | N/A |
| `REQ-ING-PAG` | _(N/A — autoloader-style prefix walk; no cursor/keyset pagination)_ | N/A |
| `REQ-ING-RL` | _(N/A — no upstream API to rate-limit; only S3 GET concurrency)_ | N/A |
| `REQ-ING-HWM` | _(N/A — Lakeflow Auto Loader manages high-water-mark via checkpoint location)_ | N/A |
| `REQ-FW-CONTRACT` | `src/connectors/semgrep/tests/test_contract_wrappers.py::test_ingest_wrapper_has_contract_signature` | PASS |
| `REQ-FW-BRONZE-ENVELOPE` | `src/connectors/semgrep/tests/test_contract_wrappers.py::test_run_ingest_pipeline_accepts_run_id_kwarg` | PASS |
| `REQ-TRF-MAP` | `src/connectors/semgrep/tests/test_transform.py::test_finding_mapping` | PASS |
| `REQ-TRF-SEV` | `src/connectors/semgrep/tests/test_transform.py::test_severity_normalization_all_levels` | PASS |
| `REQ-TRF-STS` | `src/connectors/semgrep/tests/test_transform.py::test_status_defaults_to_open_for_cli` | PASS |
| `REQ-TRF-TS` | `src/connectors/semgrep/tests/test_transform.py::test_seen_at_is_utc_datetime` | PASS |
| `REQ-DQ` | `src/connectors/semgrep/tests/test_transform.py::test_findings_expectation_quarantines_null_check_id` | PASS |
| `REQ-DEDUP` | `src/connectors/semgrep/tests/test_transform.py::test_dedup_links_against_sonarqube_overlap` | PASS |

Collected 8 requirement-bound tests via `pytest src/connectors/semgrep/tests/ -v --tb=short`. The four ingest-side REQs do not apply: Semgrep findings arrive as CLI `--json` artefacts on S3, so authentication, pagination, rate-limiting, and high-water-mark are properties of the artefact pipeline (CronJob / CI step) and Lakeflow Auto Loader, not the connector itself.

### Tests

Tests live under [`src/connectors/semgrep/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/semgrep/tests). The report table above is the per-REQ outcome of running the bound tests in that directory.

## Generation log

This connector page was reconciled by the connector-lifecycle skills under the retrofit-9-connectors work; the Reference and Validation sections preserve the original implementation-grounded prose, and the Generation log table records the actual skill runs that produced the reconciled artefacts.

| Stage              | Skill                              | Inputs                                                                | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (sast)            | name=Semgrep; url=https://semgrep.dev/api/v1/docs; category=sast      | mkdocs/docs/connectors/sast/semgrep.md §1–§3                                       | 2026-04-25 | d47eb26 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (sast)        | page hash=72c0eb36b9f8                                           | src/connectors/semgrep/, src/connectors/semgrep/tests/, src/connectors/semgrep/severity.yml, src/connectors/semgrep/status.yml, src/connectors/semgrep/resources/job.yml | 2026-04-25 | 15935ca (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (sast)   | module path=src/connectors/semgrep/                                   | mkdocs/docs/connectors/sast/semgrep.md §5                                          | 2026-04-25 | fa314d2 (production-shape-b)             |
