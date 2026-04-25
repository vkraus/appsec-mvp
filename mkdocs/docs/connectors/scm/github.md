# GitHub

## Overview

The GitHub connector plays a dual role. As an SCM source it populates `silver.repositories`, `silver.commits`, `silver.pull_requests`, and `silver.branch_policies`, providing repository and development-process metadata used to attribute findings to teams. As host of the GitHub Advanced Security (GHAS) suite it also writes into `silver.findings` with three category values: `sast` (from Code Scanning), `secret` (from Secret Scanning), and `sca` (from Dependabot). When GHAS is enabled, GitHub is both the SCM source and the primary SAST, secret-detection, and SCA source for platform-hosted repositories.

**Category:** SCM + platform-integrated SAST / SCA / secrets · **Integration pattern:** SDK (PyGithub)

The MVP connector ingests the SCM subset only (repositories, commits, pull requests, branch policies); GHAS integration (Code Scanning, Secret Scanning, Dependabot) is documented under Reference as intended scope but is not implemented in the MVP.

## Prerequisites

Platform-level prerequisites (AWS, Databricks workspace, Terraform tooling) are covered once in [Platform → Prerequisites](../../platform/prerequisites.md). The GitHub-specific handoffs required before `terraform apply` are:

- **GitHub organization.** Create or nominate a GitHub organization into which Terraform will provision the three seed repos (`seed-python-a`, `seed-javascript-b`, `juiceshop`). Capture the organization slug as `github_org` in `terraform.tfvars`.
- **Credential provisioning.** Provision a Personal Access Token (classic or fine-grained) or a GitHub App installation for the target organization. PAT scopes required for the MVP: `repo` (full control of private repositories) and `read:org` (read organization membership). GitHub App installations are preferred for organization-wide ingestion because they raise the rate-limit allowance to 15,000 requests/hour and decouple credentials from a personal account; the App's private key is stored in Databricks Secrets. The PAT value is stored in the `mvp-connectors` secret scope under the `github_pat` key.
- **Webhook endpoint (optional).** Webhook-based incremental ingestion is the preferred strategy. When enabled, configure an organization-level webhook pointing at the Databricks workspace's webhook receiver endpoint and subscribe to `push` and `pull_request` events for the SCM-only MVP. The MVP falls back to the `updated_at` polling high-water-mark when no webhook is configured.

## Reference

### API surface

GitHub exposes two APIs. The REST API (v3) at `https://api.github.com` provides resource-oriented endpoints covering every platform object and uses HTTP link-header pagination. The GraphQL API (v4) at `https://api.github.com/graphql` supports selective field retrieval and cursor-based pagination, and is efficient for bulk metadata reads where REST would require one request per repository.

The connector uses GraphQL for organization-wide repository enumeration and REST for all other operations, because the security-findings endpoints (`code-scanning/alerts`, `secret-scanning/alerts`, `dependabot/alerts`) are not yet in the GraphQL schema.

- `GET /orgs/{org}/repos` — enumerate all repositories in the organization; used for the initial discovery pass before per-repository fetches.
- `GET /repos/{owner}/{repo}/commits` — commit history with author and timestamp metadata.
- `GET /repos/{owner}/{repo}/pulls` — pull requests with state, merge metadata, and head/base references.
- `GET /repos/{owner}/{repo}/branches/{branch}/protection` — branch-protection rules for the repository default branch.
- `GET /repos/{owner}/{repo}/code-scanning/alerts` — SAST findings from CodeQL and third-party scanners integrated via GHAS.
- `GET /repos/{owner}/{repo}/secret-scanning/alerts` — secret-detection findings from GHAS Secret Scanning.
- `GET /repos/{owner}/{repo}/dependabot/alerts` — SCA findings from Dependabot.

Authentication uses a GitHub App installation token, providing organization-level access without tying credentials to a personal account. The connector exchanges a signed JWT for a short-lived installation token at runtime; the private key is stored in Databricks Secrets. PAT-based and OAuth-based authentication are also supported for environments without a GitHub App.

### Pagination and rate limits

The REST API uses link-header pagination: each response includes a `Link` header with `rel="next"` and `rel="last"` relations; the connector follows `next` until absent. The GraphQL API uses connection-style cursor pagination: each connection exposes `pageInfo` with `endCursor` (pass as `after`) and `hasNextPage`. The connector advances until `hasNextPage` is false.

The primary authenticated rate limit is 5,000 requests/hour for PAT and OAuth tokens. GitHub App installation tokens receive a higher allowance of 15,000 requests/hour for an organization of standard size, making App authentication the preferred approach for bulk ingestion.

Secondary rate limits constrain concurrent request rates and burst traffic, particularly on search and code-scanning endpoints. The connector reads `X-RateLimit-Remaining`, `X-RateLimit-Reset` (Unix timestamp), and `Retry-After` (seconds, returned with `HTTP 429` or `HTTP 403`) to pace requests. When `X-RateLimit-Remaining` drops below a configurable threshold the connector pauses; when `Retry-After` is present it waits the prescribed interval.

### Incremental hook

GitHub offers two incremental hooks. Every relevant resource carries an ISO 8601 UTC `updated_at` timestamp usable as a polling high-water mark. The REST alerts endpoints accept an `updated_after` query parameter for server-side filtering.

Webhook events are the primary mechanism where delivery is operational: `push`/`pull_request` for SCM data, and `code_scanning_alert`/`secret_scanning_alert`/`dependabot_alert` for findings. Webhooks are preferred; the `updated_at` high-water-mark serves as the polling fallback and for backfills.

GitHub's `updated_at` timestamps are always UTC, so no time-zone normalization is required.

### Resource schema excerpt

The fields below are the subset consumed by the connector.

*GitHub `/repos` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Numeric repository identifier; stable across renames. |
| `node_id` | string | GraphQL global node identifier; used when switching between REST and GraphQL contexts. |
| `full_name` | string | Canonical `owner/repo` path; becomes the join key to other tables. |
| `default_branch` | string | Name of the default branch; used to scope branch-protection reads. |
| `visibility` | string | `public`, `private`, or `internal` (see Enumerations). |
| `language` | string | Primary programming language as detected by GitHub Linguist; nullable. |
| `pushed_at` | datetime (UTC) | Timestamp of the most recent push; used for staleness detection. |
| `updated_at` | datetime (UTC) | High-water-mark column for repository metadata incremental ingestion. |

*GitHub `/commits` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sha` | string | Full SHA-1 commit hash; primary key in `silver.commits`. |
| `commit.author.date` | datetime (UTC) | Authoring timestamp; used as the commit's canonical timestamp. |
| `commit.message` | string | Full commit message; truncated at transform to 512 characters for storage efficiency. |
| `author.login` | string | GitHub username of the author; nullable when the committer email is not associated with a GitHub account. |
| `parents` | array of objects | Array of parent commit SHAs; length greater than one indicates a merge commit. |

*GitHub `/pulls` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Pull request number within the repository; part of the composite primary key with `full_name`. |
| `state` | string | `open` or `closed` (see Enumerations). |
| `merged_at` | datetime (UTC) | Merge timestamp; null when the pull request was closed without merging. |
| `created_at` | datetime (UTC) | Creation timestamp. |
| `updated_at` | datetime (UTC) | High-water-mark column for pull-request incremental ingestion. |
| `head.sha` | string | SHA of the head commit on the source branch at the time of last update. |
| `base.ref` | string | Target branch name; used to identify pull requests targeting the default branch. |
| `user.login` | string | GitHub username of the pull request author. |

*GitHub `code-scanning/alerts` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Alert number within the repository; part of the composite primary key with `full_name`. |
| `state` | string | `open`, `dismissed`, or `fixed` (see Enumerations). |
| `rule.id` | string | Rule identifier, tool-specific (e.g. `js/sql-injection` for CodeQL). |
| `rule.severity` | string | CodeQL interpretive severity: `none`, `note`, `warning`, or `error` (see Enumerations). |
| `rule.security_severity_level` | string | Security-oriented severity: `low`, `medium`, `high`, or `critical`; present only for security rules (see Enumerations). |
| `most_recent_instance.location.path` | string | Repository-relative file path of the most recent finding instance. |
| `most_recent_instance.location.start_line` | integer | Line number of the most recent finding instance. |
| `tool.name` | string | Scanning tool that produced the alert (e.g. `CodeQL` or a third-party tool registered via GHAS). |
| `created_at` | datetime (UTC) | Timestamp of first detection. |
| `updated_at` | datetime (UTC) | High-water-mark column; updated on every state change. |

*GitHub `secret-scanning/alerts` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Alert number within the repository; part of the composite primary key with `full_name`. |
| `state` | string | `open` or `resolved` (see Enumerations). |
| `secret_type` | string | Machine-readable secret type identifier (e.g. `github_personal_access_token`); used for classification in `silver.findings`. |
| `secret_type_display_name` | string | Human-readable label for the secret type; stored alongside `secret_type` for reporting. |
| `validity` | string | Whether the secret is confirmed to be active, inactive, or in an unknown state (see Enumerations). |
| `resolved_at` | datetime (UTC) | Timestamp of resolution; null when the alert is still open. |
| `created_at` | datetime (UTC) | Timestamp of first detection. |
| `updated_at` | datetime (UTC) | High-water-mark column; updated on every state change. |

*GitHub `dependabot/alerts` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Alert number within the repository; part of the composite primary key with `full_name`. |
| `state` | string | `open`, `fixed`, `dismissed`, or `auto_dismissed` (see Enumerations). |
| `dependency.package.name` | string | Name of the vulnerable dependency package. |
| `dependency.package.ecosystem` | string | Package ecosystem (e.g. `npm`, `pip`, `maven`); preserved as `ecosystem` in `silver.findings`. |
| `dependency.manifest_path` | string | Repository-relative path to the manifest file (e.g. `package-lock.json`) that declares the dependency. |
| `security_advisory.cve_id` | string | CVE identifier; the primary join key to the vulnerability-enrichment layer. |
| `security_advisory.severity` | string | Severity level: `low`, `medium`, `high`, or `critical` (see Enumerations). |
| `created_at` | datetime (UTC) | Timestamp of first detection. |
| `updated_at` | datetime (UTC) | High-water-mark column; updated on every state change. |

### Enumerations

**Code-scanning alert state.** `state` takes `open` (detected, unaddressed), `dismissed` (acknowledged with a dismissal reason, code not fixed), and `fixed` (code corrected and finding no longer appears). The connector maps all three to `silver.findings.status`, where the canonical vocabulary resolves them.

**Code-scanning severity.** `rule.severity` encodes the rule's interpretive level: `none`, `note`, `warning`, `error` (CodeQL-specific; reflects review importance, not security risk). `rule.security_severity_level`, present only on security rules, uses `low`, `medium`, `high`, `critical`. `config/severity/github.yml` uses `security_severity_level` when present, with `rule.severity` as fallback.

**Secret-scanning alert state.** `state` is binary: `open` or `resolved` (dismissed or secret revoked). `validity` provides an extra signal for supported secret types: `active` (GitHub verified with the provider), `inactive` (revoked or expired), `unknown` (provider does not support validity checks). `validity` is preserved in `silver.findings.validity_status` and feeds gold-layer risk scoring.

**Dependabot alert state.** `state` takes `open` (vulnerable dependency present), `fixed` (updated to a safe version), `dismissed` (analyst-suppressed), and `auto_dismissed` (closed automatically, e.g. unreachable code path). `security_advisory.severity` uses the same four-level vocabulary as code-scanning `rule.security_severity_level`, so a single canonical severity lookup applies.

### Quirks

**Dual severity fields on code-scanning alerts.** Alerts carry `rule.severity` (`none`, `note`, `warning`, `error`) and `rule.security_severity_level` (`low`, `medium`, `high`, `critical`; security rules only). The two use different vocabularies for different purposes. `config/severity/github.yml` gives precedence to `security_severity_level` when present, falling back to `rule.severity`, so that non-security rules still receive a canonical severity rather than being dropped.

**Dependabot ecosystem values.** `dependency.package.ecosystem` uses package-manager identifiers: `npm`, `pip`, `maven`, `rubygems`, `cargo`, `nuget`, `composer`, `go`, `actions`, `docker`. These are not part of the canonical schema but matter for triage. The connector preserves them verbatim in `silver.findings.ecosystem` so gold-layer queries can filter by ecosystem.

**Webhook and REST payload divergence.** Webhook payloads and REST responses share logical fields but differ structurally: webhooks include envelope fields (`action`, `installation`, `repository`) and may nest the resource differently. The connector normalizes both to a single Bronze schema per entity at landing via the shared Bronze-landing function.

**GraphQL for organization-wide metadata, REST for alerts.** GraphQL's `viewer.organization.repositories` connection retrieves all repository metadata in a small number of paginated requests with only the required fields. The three GHAS alerts endpoints are not in the GraphQL schema and must be consumed via REST.

**Per-repository authorization for code-scanning endpoints.** The code-scanning alerts endpoint enforces repository-level authorization even for org-scoped tokens. A token lacking the `security_events` scope for a repository gets `HTTP 403` for that repository only. The connector walks repositories, fetches alerts per repository, and logs and skips `403` responses rather than failing the entire run.

## Setup

### Configuration

Terraform provisions the GitHub integration automatically:

- Three seed repos in your GitHub org (`seed-python-a`, `seed-javascript-b`, `juiceshop`).
- `mvp-connectors` secret scope keys: `github_org`, `github_pat`.
- Scheduled `mvp-github` Databricks job (every 3 hours).

### Bundle deployment

The GitHub Databricks job is created by `terraform apply` in `infra/terraform`. See [Platform → Terraform apply](../../platform/terraform-apply.md) for the full apply order.

### First run

```bash
JOB_ID=$(terraform -chdir=infra/terraform output -json connector_job_ids | jq -r '.github')
databricks jobs run-now --job-id "$JOB_ID"
```

Observe bronze → silver:

```sql
SELECT count(*) FROM appsec_dev.bronze_github.repositories;       -- expect 3
SELECT count(*) FROM appsec_dev.silver_github.repositories;       -- expect 3
SELECT full_name, default_branch FROM appsec_dev.silver_github.repositories;
```

**Role in the evidence story.** Supplies `silver.repositories` and `silver.commits`, which the Semgrep and SonarQube connectors join against to attach findings to repositories. Also the source-of-truth for `silver.app_repo_mapping` repository IDs referenced by ServiceNow.

**Normalization spot-check.** GitHub `full_name = "<org>/seed-python-a"` is used verbatim as `silver.repositories.full_name`; `id` (integer) is stringified into `repository_id`.

**Troubleshooting.**

| Symptom | Fix |
|---|---|
| `401 Bad credentials` | PAT expired or scope-insufficient. Rotate, update tfvars, `terraform apply`. |
| Rate-limit 403 | PyGithub respects `X-RateLimit-Reset`; subsequent runs recover. Raise job schedule interval if chronic. |
| Missing repos | Confirm `github_repository.seed` and `github_repository.juiceshop` were created — check `terraform state list \| grep github_repository`. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | `tests/connectors/github/test_ingest.py::test_ingest_resolves_token_from_state_and_rejects_missing_secret` | PASS |
| `REQ-ING-PAG` | `tests/connectors/github/test_ingest.py::test_fetch_org_repositories_yields_raw_data_per_repo` | PASS |
| `REQ-ING-RL` | `tests/connectors/github/test_ingest.py::test_github_client_configures_retry_policy` | PASS |
| `REQ-ING-HWM` | `tests/connectors/github/test_ingest.py::test_fetch_repo_commits_passes_since_as_datetime` | PASS |
| `REQ-TRF-MAP` | `tests/connectors/github/test_transform.py::test_repositories_to_silver` | PASS |
| `REQ-TRF-SEV` | — | N/A |
| `REQ-TRF-STS` | — | N/A |
| `REQ-TRF-TS` | `tests/connectors/github/test_transform.py::test_repositories_updated_at_is_utc_datetime` | PASS |
| `REQ-DQ` | `tests/connectors/github/test_transform.py::test_repositories_missing_full_name_raises` | PASS |
| `REQ-DEDUP` | — | N/A |

Collected 7 requirement-bound tests via `py -3.11 -m pytest tests/connectors/github/ -v --tb=short` (2026-04-25, 12.65 s wall-clock); 7 passed, 0 failed, 3 N/A. N/A rationale: GitHub Advanced Security integration not implemented in MVP — entity-only role, so the finding-only REQ-IDs `REQ-TRF-SEV`, `REQ-TRF-STS`, and `REQ-DEDUP` do not bind to entity-shape tests.

### Tests

Tests live under [`tests/connectors/github/`](https://github.com/vkraus/appsec-mvp/tree/main/tests/connectors/github). The report table above is the per-REQ outcome of running the bound tests in that directory.

## Generation log

This connector page was reconciled by the connector-lifecycle skills under the retrofit-9-connectors work; the Reference and Validation sections preserve the original implementation-grounded prose, and the Generation log table records the actual skill runs that produced the reconciled artefacts.

| Stage              | Skill                              | Inputs                                                                | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (scm)             | name=GitHub; url=https://docs.github.com/en/rest; category=scm        | mkdocs/docs/connectors/scm/github.md §1–§3                                         | 2026-04-25 | 7ab1cb8 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (scm)         | page hash=ff7421072eb3                                           | src/connectors/github/, tests/connectors/github/, config/severity/github.yml, config/status/github.yml, resources/github-job.yml | 2026-04-25 | 5e5d96f (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (scm)    | module path=src/connectors/github/                                    | mkdocs/docs/connectors/scm/github.md §5                                            | 2026-04-25 | aadd4ef (retrofit-9-connectors)  |
