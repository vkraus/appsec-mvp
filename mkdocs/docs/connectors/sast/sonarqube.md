# SonarQube

## What this connector ingests

The SonarQube connector is the primary standalone SAST source. Operational pattern: **periodic-global** — the SonarQube server scans all enrolled projects on its own schedule, and the connector polls the server via its REST API with an `updated_at` high-water mark. It populates `silver.findings` from two finding types: *issues* (rule violations detected by static analysis) and *hotspots* (security-sensitive code patterns flagged for review, not classified as definitive vulnerabilities). The two have distinct status vocabularies and lifecycles, so they land in separate Bronze tables and project into `silver.findings` with a differentiating `rule_id` prefix.

The connector also loads rule metadata from `/api/rules/search` for severity/status lookups and project inventory from `/api/projects/search` for project-by-project iteration.

**Category:** SAST (server, periodic-global) · **Integration pattern:** REST + dlt

Bronze schema: `bronze_sonarqube`. Cross-source contribution: `silver.findings` with `tool_source = 'sonarqube'`.

The connector module at `src/connectors/sonarqube/` is present as a **structural skeleton** — folder layout, DAB job + schema resources, secret-loader script, severity/status lookups, and notebook entry stubs are all in place, but `ingest()` and `transform()` raise `NotImplementedError`. The full implementation is tracked as a separate follow-on task (per the redesign spec's "Out of scope" section). The runbook below describes the *intended* operator flow; until the implementation lands, the job runs but produces no Bronze rows.

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md) if Phase 1 is not yet complete.
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** SonarQube findings carry a project key that maps to `silver.findings.repository_id`; that value must resolve to a row in `silver.repositories` for downstream rollups to attribute findings to a repository (and through `silver.app_repo`, to a business application).

## Operator inputs

| Input | Where to obtain | Used as |
|---|---|---|
| SonarQube server URL | Operator's existing SonarQube instance, or the `sonarqube_url` output of the optional source runtime. | Env var `SONARQUBE_URL` consumed by `src/connectors/sonarqube/scripts/load-secrets.sh`; written to secret key `sonarqube_url`. |
| SonarQube analysis token (or user token) | Generated in the SonarQube UI under **My Account → Security → Generate Tokens**. The connector accepts a project-analysis token or a user token; the user token type is broader-scope and recommended for cross-project enumeration. See [Bootstrapping the analysis token](#bootstrapping-the-analysis-token) for the demo-runtime path. | Env var `SONARQUBE_TOKEN`; written to secret key `sonarqube_token`. |

## Optional source runtime

If you want appsec-mvp to provision a SonarQube 10.6 Helm release on your EKS cluster (backed by an operator-supplied RDS Postgres instance, exposed via LoadBalancer), apply the optional runtime under `src/connectors/sonarqube/runtime/`. See [`src/connectors/sonarqube/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/sonarqube/runtime) for variables, RDS endpoint preconditions, the admin password handling, and produced outputs.

Operators with their own SonarQube instance skip the runtime — wire the existing instance's URL and token directly via the next section.

### Bootstrapping the analysis token

The optional runtime mints a *random* project-analysis token in Terraform state but does not register it on the SonarQube side (the API for that requires a running server). After the runtime is applied and the SonarQube UI is reachable, register the token once:

```bash
SONAR_URL=$(terraform -chdir=src/connectors/sonarqube/runtime output -raw sonarqube_url)
SONAR_TOKEN=$(terraform -chdir=src/connectors/sonarqube/runtime output -raw sonarqube_project_token)
ADMIN_PWD=$(terraform -chdir=src/connectors/sonarqube/runtime output -raw sonarqube_admin_password)

curl -X POST "$SONAR_URL/api/user_tokens/generate" \
  -u "admin:$ADMIN_PWD" \
  -d "name=appsec-mvp&login=admin&type=PROJECT_ANALYSIS_TOKEN"
```

Then load the value into the secret scope via `bash src/connectors/sonarqube/scripts/load-secrets.sh` (with `SONARQUBE_URL` + `SONARQUBE_TOKEN` exported).

Operators with their own SonarQube instance skip this step — the token already exists.

## Reference

### API surface

SonarQube exposes a REST Web API at `/api/`. The same surface is available on SonarQube Server (self-managed) and SonarQube Cloud (SaaS); endpoint paths and schemas are shared, though some administrative endpoints are server-only.

The endpoints consumed by the connector are as follows.

- `GET /api/issues/search` — retrieves paginated issues for one or more projects, with server-side filtering by severity, status, type, and creation date range.
- `GET /api/hotspots/search` — retrieves paginated security hotspots, filterable by project and status.
- `GET /api/rules/search` — retrieves rule metadata including severity, rule type, and category; used to pre-populate the severity lookup table at connector initialization.
- `GET /api/projects/search` — enumerates all projects visible to the authenticated principal; provides the project key inventory that drives per-project issue and hotspot fetches.
- `GET /api/components/tree` — traverses the component hierarchy of a project; used selectively when file-level metadata is required beyond what the `component` field in the issues response provides.

Authentication uses a user token as a Bearer token in the `Authorization` header. Legacy SonarQube Server instances accept HTTP Basic Auth with the token as username and empty password. Tokens are stored in Databricks Secrets.

### Pagination and rate limits

The SonarQube API uses 1-indexed offset pagination: `p` (page number, from 1) and `ps` (page size, max 500). The response `paging` object carries `pageIndex`, `pageSize`, and `total`. The connector reads `paging.total` on the first page to compute page count and detect oversize result sets.

A hard 10,000-record per-query cap applies: `paging.total` stops at 10,000 and page requests beyond the cap are rejected. The connector partitions by creation-date window using `createdAfter`/`createdBefore`: when `paging.total` exceeds a warning threshold (default 8,000), it splits the query into date windows sized to historical issue density.

SonarQube does not enforce a per-client request quota. Throughput is bounded by instance resources; sustained high-frequency requests can degrade analysis for other users. The connector applies a configurable inter-request delay (default 100 ms) and exponential backoff on `HTTP 429`, though 429s are uncommon on dedicated instances. Operators on shared instances should increase the delay.

### Incremental hook

The issues endpoint accepts `createdAfter` (ISO 8601) and `createdInLast` (duration string, e.g., `7d`) as server-side filters. Every issue exposes `updateDate` (ISO 8601, UTC); the connector persists the maximum observed `updateDate` as the high-water mark.

SonarQube has no finding-level webhook but supports project-analysis webhooks that fire on scan completion; the payload identifies the project and analysis but not the findings. The reference implementation subscribes and performs an `updateDate`-filtered pull scoped to the analyzed project, realizing the webhook-triggered high-water-mark pattern. Scheduled polling is the fallback.

### Resource schema excerpt

The fields below are the subset consumed by the connector; complete schemas are available in the official SonarQube Web API documentation.

**`/api/issues/search` consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `key` | string (GUID) | Primary key; stable across status changes and analysis reruns. |
| `rule` | string | Rule identifier in `repository:ruleKey` format (e.g. `java:S2259`); used as `rule_id` in `silver.findings`. |
| `severity` | string | BLOCKER, CRITICAL, MAJOR, MINOR, or INFO (see Enumerations). |
| `status` | string | OPEN, CONFIRMED, REOPENED, RESOLVED, or CLOSED (see Enumerations). |
| `resolution` | string | FALSE-POSITIVE, WONTFIX, FIXED, or REMOVED; present only when `status` is RESOLVED or CLOSED (see Enumerations). |
| `project` | string | Project key; used as the join key to the project inventory table. |
| `component` | string | File path in `project-key:relative/path` format (see Quirks). |
| `line` | integer | Line number of the finding within the component file; nullable for file-level issues that are not tied to a specific line. |
| `type` | string | BUG, VULNERABILITY, or CODE_SMELL (see Enumerations). |
| `creationDate` | datetime (UTC) | Timestamp of first detection. |
| `updateDate` | datetime (UTC) | Timestamp of the most recent modification; high-water-mark column. |

Hotspots model a different concept from issues: a hotspot flags a security-sensitive code pattern requiring human review, not a confirmed rule violation. Hotspots have a separate status vocabulary, a distinct resolution lifecycle, and structured security metadata (CWE, OWASP, SANS) absent from issues, so they land in a dedicated Bronze table. The Silver transform projects both into `silver.findings` with a `rule_id` prefix convention (`hotspot:` for hotspots, unmodified `repository:ruleKey` for issues).

**`/api/hotspots/search` consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `key` | string (GUID) | Primary key; stable across review state changes. |
| `component` | string | File path in `project-key:relative/path` format; same structure as the issues `component` field. |
| `line` | integer | Line number of the hotspot within the component file; nullable for file-level hotspots. |
| `status` | string | TO_REVIEW or REVIEWED (see Enumerations). |
| `resolution` | string | FIXED, SAFE, or ACKNOWLEDGED; present only when `status` is REVIEWED (see Enumerations). |
| `vulnerabilityProbability` | string | Reviewer-assessed exploitability: HIGH, MEDIUM, or LOW (see Enumerations). |
| `cwe` | array of strings | CWE identifiers associated with the hotspot rule; may be empty. |
| `owaspTop10` | array of strings | OWASP Top 10 category identifiers (e.g. `a1`, `a3`); may be empty. |
| `sansTop25` | array of strings | SANS Top 25 category identifiers; may be empty. |
| `creationDate` | datetime (UTC) | Timestamp of first detection. |
| `updateDate` | datetime (UTC) | Timestamp of the most recent modification; high-water-mark column. |

### Enumerations

**Issue severity.** Issues use a five-value scale: BLOCKER (blocks the build or causes data corruption), CRITICAL (high severity, immediate attention), MAJOR (substantial quality impact), MINOR (limited impact), INFO (negligible). `src/connectors/sonarqube/severity.yml` maps BLOCKER→`critical`, CRITICAL→`high`, MAJOR→`medium`, MINOR→`low`, INFO→`low` (direct mapping avoids the fallback rule, because INFO is defined rather than unmapped).

**Issue status and resolution.** `status` has five values: OPEN (unaddressed), CONFIRMED (reviewed as true positive), REOPENED (previously closed, reinstated), RESOLVED (addressed; see `resolution`), CLOSED (no longer detectable). When RESOLVED or CLOSED, `resolution` refines: FALSE-POSITIVE, WONTFIX, FIXED, REMOVED. `src/connectors/sonarqube/status.yml` composes them: OPEN/REOPENED→`open`; CONFIRMED→`confirmed`; RESOLVED+FIXED→`resolved`; RESOLVED+FALSE-POSITIVE→`false_positive`; RESOLVED+WONTFIX→`wontfix`; CLOSED+REMOVED→`resolved`.

**Issue type.** `type` classifies: BUG (coding error), VULNERABILITY (exploitable security weakness), CODE_SMELL (maintainability). The Bronze table stores all three; the Silver transform filters to BUG and VULNERABILITY for `silver.findings`, because CODE_SMELL is not a security finding. `type` is preserved as a domain column for gold-layer quality metrics.

**Hotspot status and resolution.** Hotspots use a two-value status: TO_REVIEW and REVIEWED. When REVIEWED, `resolution` is FIXED, SAFE (not exploitable in context), or ACKNOWLEDGED (deferred). `vulnerabilityProbability` (HIGH, MEDIUM, LOW) encodes exploitability; the connector maps it via `src/connectors/sonarqube/severity-hotspots.yml`.

### Quirks

**Component field encoding.** `component` on issues and hotspots concatenates project key and file path with a colon (`my-project:src/main/java/com/example/Service.java`). The Silver transform extracts `file_path` by splitting on the first colon. Project keys cannot contain colons, so the split is unambiguous.

**Ten-thousand-result cap and date-window partitioning.** The 10,000-record cap is per-query, not per-project. Large projects require partitioning by creation-date window via `createdAfter`/`createdBefore`. The connector issues a first unpartitioned query and, if `paging.total` exceeds the warning threshold, computes windows that distribute issue volume evenly. This logic lives in the `IssuePageIterator` class.

**CODE_SMELL filtering at the Silver layer.** Bronze stores all three types unfiltered (preserving the raw record). Silver applies `type IN ('BUG', 'VULNERABILITY')` when projecting into `silver.findings`. Operators who want CODE_SMELL in security reporting can override the predicate in `mapping.yml`.

**INFO severity handling.** INFO is a defined value, not unmapped, so it maps directly to `low` rather than triggering the fallback rule. The fallback emits a warning and increments a metric counter; direct mapping avoids spurious noise for high-volume INFO findings.

**Hotspot distinct lifecycle and Bronze table separation.** Hotspots and issues use different endpoints (`/api/hotspots/search` vs. `/api/issues/search`) and non-overlapping `key` namespaces. Merging at landing would require type-disambiguating logic. The connector uses separate Bronze tables (`bronze.sonarqube_issues`, `bronze.sonarqube_hotspots`); Silver projects both into `silver.findings` with a `source_type` column and the `rule_id` prefix convention.

## Mapping example

This section shows how native SonarQube issue fields map to the canonical
Silver Finding schema. The shape matches the `mapping.yml` convention used
by `src/connectors/<source>/mapping.yml` throughout the reference
implementation. Canonical field names correspond to the
[Silver Finding Mapping Requirements](../../platform/reference/canonical-mapping.md#silver-finding-mapping-requirements).
The MVP `mapping.yml` convention is authoritative where its column names
differ from the requirements table (for example `tool_source` here and in
`src/connectors/*/mapping.yml` rather than `source_tool`).

```yaml
# SonarQube /api/issues/search → silver.findings field mapping.
# Source schema: Reference > Resource schema excerpt (api/issues/search) above.
# Canonical target: Silver Finding Mapping Requirements, code-level SAST row.
source_key: sonarqube
fields:
  finding_id:          generated                           # surrogate key, framework-assigned
  source_finding_id:   key                                 # stable GUID across status changes
  tool_source:         "sonarqube"                         # literal per connector
  category:            "sast"                              # literal; hotspots also land here
  repository_id:       component                           # project portion; split on first colon
  severity_canonical:  lookup(severity, severity_map)      # BLOCKER…INFO → critical/high/medium/low
  status_canonical:    lookup(status+resolution, status_map, default="open")  # composite key
  rule_id_native:      rule                                # repository:ruleKey format (e.g. java:S2259)
  file_path:           component                           # full value; transform strips project prefix
  start_line:          line                                # nullable for file-level issues
  cwe_id:              null                                # N/A for SonarQube issues; derived via cwe.py
  secret_type:         null                                # N/A for SonarQube (SAST, not secrets)
  validity_status:     null                                # N/A for SonarQube
  detected_at:         creationDate                        # UTC ISO 8601; timestamp of first detection
  resolved_at:         updateDate                          # set on status transition to RESOLVED/CLOSED
  url:                 null                                # N/A; no per-finding permalink in the API
```

### Notes on non-obvious mappings

- **Severity translation.** SonarQube uses a five-level scale (BLOCKER, CRITICAL, MAJOR, MINOR, INFO) while the canonical model has four levels. The lookup in `src/connectors/sonarqube/severity.yml` collapses both MINOR and INFO to `low`. INFO maps directly rather than falling through to the default, because it is a defined value. Direct mapping avoids data-quality warnings on high-volume informational findings.
- **Status composition.** SonarQube splits lifecycle state across two fields: `status` (OPEN, CONFIRMED, REOPENED, RESOLVED, CLOSED) and `resolution` (FALSE-POSITIVE, WONTFIX, FIXED, REMOVED), where `resolution` is only present when `status` is RESOLVED or CLOSED. The lookup in `src/connectors/sonarqube/status.yml` treats the pair as a composite key. For example, RESOLVED+FALSE-POSITIVE maps to `false_positive` and CLOSED+REMOVED maps to `resolved`.
- **File path extraction.** The `component` field encodes both the project key and the relative file path as `project-key:relative/path`. The Silver transform splits on the first colon to obtain `file_path`. Project keys cannot contain colons, so the split is unambiguous.
- **CWE derivation.** The issues endpoint does not return CWE identifiers directly. `src/platform/cwe.py` derives CWE from the rule identifier using a pre-loaded rule-metadata table (populated from `/api/rules/search`). The `mapping.yml` records `cwe_id: null` to indicate the field is not read directly from the source record; the transform layer enriches it from the side table.

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/sonarqube/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
| `sonarqube_url` | `SONARQUBE_URL` | Sonar server URL the connector calls. |
| `sonarqube_token` | `SONARQUBE_TOKEN` | Analysis-token-style PAT used for `/api/issues/search`, `/api/hotspots/search`, `/api/rules/search`, `/api/projects/search`. |

Run from repo root after Phase 1 completes:

```bash
export SONARQUBE_URL="http://sonarqube.example.com"
export SONARQUBE_TOKEN="..."
bash src/connectors/sonarqube/scripts/load-secrets.sh
# OK: sonarqube secrets loaded into scope mvp-connectors
```

## Run the job

Before the connector ingests anything, the SonarQube server itself must have project-analysis results to expose. From any machine with Docker and network access to the SonarQube URL, scan each repo once:

```bash
for repo in BenchmarkJava BenchmarkPython; do
  git clone "https://github.com/<org>/${repo}"
  docker run --rm -v "$PWD/${repo}:/usr/src" \
    -e SONAR_HOST_URL="$SONARQUBE_URL" -e SONAR_TOKEN="$SONARQUBE_TOKEN" \
    sonarsource/sonar-scanner-cli \
    -Dsonar.projectKey="$repo" -Dsonar.sources=.
done
```

Then trigger the connector's Databricks job:

```bash
databricks bundle run sonarqube-connector --target dev
```

The job is declared in `src/connectors/sonarqube/resources/job.yml`, runs on a 3-hour cron, and has two tasks: `ingest` (REST → Bronze) and `transform` (Bronze → `silver.findings`).

!!! warning "Skeleton-only behaviour"
    The connector module's `ingest()` and `transform()` raise `NotImplementedError`. Until the full implementation lands, the bundle deploys the job and the schema, but the job's first run fails on the placeholder. Operators wiring SonarQube can deploy the resources and validate the secret-loading flow end-to-end; functional ingest is future work.

**Normalization spot-check (target behaviour).**

- SonarQube `severity = 'BLOCKER'` → `severity_canonical = 'critical'`.
- SonarQube rule `python:S3649` → `cwe_id = 'CWE-89'` (via `src/platform/cwe.py`).

## Verify

```sql
-- Bronze: raw issues + hotspots from /api/issues/search and /api/hotspots/search.
SELECT count(*) FROM appsec_dev.bronze_sonarqube.issues;
SELECT count(*) FROM appsec_dev.bronze_sonarqube.hotspots;

-- Silver: cross-source canonical findings for sonarqube.
SELECT count(*) FROM appsec_dev.silver.findings WHERE tool_source='sonarqube';
SELECT rule_id_native, cwe_id, severity_canonical
  FROM appsec_dev.silver.findings WHERE tool_source='sonarqube' LIMIT 5;

-- Cross-source dependency check — every sonarqube finding's repository_id
-- should join to a silver.repositories row populated by an SCM connector.
SELECT count(*) AS missing_repo
  FROM appsec_dev.silver.findings f
  LEFT JOIN appsec_dev.silver.repositories r USING (repository_id)
  WHERE f.tool_source='sonarqube' AND r.repository_id IS NULL;
```

A non-zero `missing_repo` count means SonarQube is reporting findings against repositories the SCM connector has not yet ingested. Run [GitHub](../scm/github.md) (or another SCM) before relying on the rollups in [Evidence scenarios](../../analytics/evidence.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Helm release stuck on `pending-install` (when using the optional runtime) | RDS not ready — wait ~5 min, `helm status sonarqube -n sonarqube`, re-run `terraform apply` from `src/connectors/sonarqube/runtime/`. |
| `/api/issues/search` returns empty | No SonarQube scans have completed yet; run the `sonar-scanner-cli` Docker invocation above against your target repos. |
| `401` from the Databricks job | `sonarqube_token` secret not populated. Re-run `bash src/connectors/sonarqube/scripts/load-secrets.sh` with `SONARQUBE_URL` + `SONARQUBE_TOKEN` exported; see [Secrets bootstrap](../../platform/secrets-bootstrap.md). |
| `NotImplementedError` from the job | Expected: connector module is a skeleton. Tracked in the redesign spec's "Out of scope" section. |
| No rows in `silver.repositories` | No SCM connector has run yet. Install [GitHub](../scm/github.md) or another SCM connector and trigger its job before relying on the cross-source join. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | `src/connectors/sonarqube/tests/test_ingest.py::test_token_resolution_from_secret_scope` | PASS |
| `REQ-ING-PAG` | `src/connectors/sonarqube/tests/test_ingest.py::test_page_index_pagination_two_pages` | PASS |
| `REQ-ING-RL` | `src/connectors/sonarqube/tests/test_ingest.py::test_429_backoff_retries` | PASS |
| `REQ-ING-HWM` | `src/connectors/sonarqube/tests/test_ingest.py::test_updated_after_hwm_resume` | PASS |
| `REQ-TRF-MAP` | `src/connectors/sonarqube/tests/test_transform.py::test_issue_mapping` | PASS |
| `REQ-TRF-SEV` | `src/connectors/sonarqube/tests/test_transform.py::test_severity_normalization_all_levels` | PASS |
| `REQ-TRF-STS` | `src/connectors/sonarqube/tests/test_transform.py::test_status_resolution_normalization` | PASS |
| `REQ-TRF-TS` | `src/connectors/sonarqube/tests/test_transform.py::test_creation_date_to_utc_datetime` | PASS |
| `REQ-DQ` | `src/connectors/sonarqube/tests/test_transform.py::test_findings_expectation_quarantines_null_rule` | PASS |
| `REQ-DEDUP` | `src/connectors/sonarqube/tests/test_transform.py::test_dedup_links_against_semgrep_overlap` | PASS |

Collected 10 requirement-bound tests via `pytest src/connectors/sonarqube/tests/ -v --tb=short` (2026-04-22, 4.6 s wall-clock); 10 passed.

### Tests

Tests live under [`src/connectors/sonarqube/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/sonarqube/tests). The report table above is the per-REQ outcome of running the bound tests in that directory.

## Generation log

This connector page was reconciled by the connector-lifecycle skills under the retrofit-9-connectors work. The SonarQube Web API docs render as a JavaScript SPA that WebFetch could not parse during the analyze-source run; the existing implementation-grounded prose was preserved verbatim and validated against widely-published SonarQube API conventions. The Generation log table records the actual skill runs that produced the reconciled artefacts.

| Stage              | Skill                              | Inputs                                                                                  | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (sast)            | name=SonarQube; url=https://next.sonarqube.com/sonarqube/web_api; category=sast         | mkdocs/docs/connectors/sast/sonarqube.md §1–§3                                     | 2026-04-25 | c35f49e (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (sast)        | page hash=e814ab36b6a9                                           | src/connectors/sonarqube/, src/connectors/sonarqube/tests/, src/connectors/sonarqube/severity.yml, src/connectors/sonarqube/status.yml, src/connectors/sonarqube/resources/job.yml | 2026-04-25 | 11e0014 (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (sast)   | module path=src/connectors/sonarqube/                                                   | mkdocs/docs/connectors/sast/sonarqube.md §5                                        | 2026-04-25 | 5d531e1 (retrofit-9-connectors)          |
