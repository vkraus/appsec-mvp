# GitLab

## Overview

The GitLab connector plays a dual SCM and integrated-security role analogous to GitHub, but reflects GitLab's architecture. As SCM source it populates `silver.repositories` from `/projects`, `silver.commits` from the per-project commits endpoint, `silver.pull_requests` from merge requests, and `silver.branch_policies` from protected branches. GitLab Secure — available on the Ultimate tier for both SaaS and self-managed — embeds SAST, Secret Detection, and Dependency Scanning in the CI pipeline and exposes results through a Vulnerabilities API. On Ultimate, the connector additionally writes into `silver.findings` with three category values (`sast`, `secret`, `sca`) from a single source. Without Ultimate, the same findings are available in SARIF or GitLab JSON format as CI pipeline artifacts, retrievable via the jobs artifacts endpoint.

**Category:** SCM + platform-integrated SAST / SCA · **Integration pattern:** SDK (python-gitlab)

!!! info "Not in MVP scope"
    A reference GitLab connector is not part of the MVP. The
    Reference section below documents the intended integration per
    the SCM category capability surface so a connector can be
    generated when the source is needed; Setup and Validation
    remain stubbed until that work is scheduled.

## Prerequisites

Platform-level prerequisites (AWS, Databricks workspace, Terraform tooling) are covered once in [Platform → Prerequisites](../../platform/prerequisites.md). The GitLab-specific handoffs required before a connector can be generated and deployed are:

- **GitLab tenancy.** Identify the target GitLab tenancy: SaaS (`gitlab.com`) or a self-managed instance reachable from the Databricks workspace VPC. Capture the base URL (`https://gitlab.com` or the self-managed equivalent) as `gitlab_base_url` in `terraform.tfvars`. The REST API is rooted at `{base_url}/api/v4` per the GitLab REST API documentation.
- **Top-level group.** Nominate the top-level group whose subgroups and projects the connector will ingest. Capture the group path as `gitlab_group` in `terraform.tfvars`. Group-level credentials and webhooks are configured against this group.
- **Credential provisioning.** Provision a credential per the SCM auth norm. Group access tokens are preferred for org-wide ingestion on SaaS because they are group-scoped without being tied to a personal account; on self-managed instances a service account with the Reporter role on all target groups is recommended. Required scopes for the SCM subset: `read_api` and `read_repository`. For the finding role on Ultimate, add `read_api` against the security project. Credentials are stored in the `mvp-connectors` Databricks Secret scope under the `gitlab_token` key.
- **Tier check.** Confirm the GitLab tier (Free, Premium, Ultimate). The Vulnerabilities API and Security Dashboard require Ultimate. On lower tiers the finding role is delivered through CI pipeline artifacts (SARIF or GitLab JSON) — operators set `gitlab_finding_path = "artifacts"` in `terraform.tfvars` so the generator emits the artifact-walking ingestion path. The default value `vulnerabilities_api` assumes Ultimate.
- **Webhook endpoint (optional).** Webhook-based incremental ingestion is the preferred strategy. When enabled, configure a group-level webhook pointing at the Databricks workspace's webhook receiver endpoint and subscribe to Push, Merge Request, Pipeline, Job, and (on Ultimate) Vulnerability events. The connector falls back to the `updated_at` polling high-water mark when no webhook is configured.

## Reference

### API surface

GitLab exposes a REST API at `/api/v4` and a GraphQL API at `/api/graphql`. The connector uses REST exclusively because the security-findings endpoints are not yet fully represented in GraphQL and REST offers richer server-side filtering.

- `GET /api/v4/projects` — enumerate all projects (repositories) visible to the authenticated principal; filtered by `membership=true` for organization-scoped ingestion.
- `GET /api/v4/projects/{id}/repository/commits` — commit history with author metadata and timestamps for a given project.
- `GET /api/v4/projects/{id}/merge_requests` — merge requests with state, merge metadata, and source and target branch references.
- `GET /api/v4/projects/{id}/protected_branches` — protected branch configurations, including the access levels required to push and merge.
- `GET /api/v4/projects/{id}/vulnerabilities` — security findings aggregated across all scanner types; requires GitLab Ultimate.
- `GET /api/v4/projects/{id}/jobs/{job_id}/artifacts` — retrieves CI pipeline artifact archives; used to extract SARIF or GitLab JSON scanner reports on non-Ultimate tiers.

Authentication uses a personal, project, or group access token, or OAuth 2.0. Group access tokens are preferred for org-wide ingestion on SaaS because they are group-scoped without being tied to a personal account. On self-managed instances, a service account with the Reporter role on all target groups is recommended. Credentials are stored in Databricks Secrets and resolved at runtime per `REQ-ING-AUTH`.

### Pagination and rate limits

GitLab supports two pagination strategies. Offset pagination (the default) uses `page` and `per_page` and returns `X-Total-Pages` and `X-Total` headers. Keyset pagination, activated by `pagination=keyset` with `order_by` and `sort`, returns an opaque cursor in the `Link: <url>; rel="next"` header that the connector follows until absent. Keyset is required for collections exceeding 10,000 records, since GitLab refuses offset requests beyond that on SaaS.

The connector uses keyset pagination by default and falls back to offset only for endpoints without keyset support. `per_page` is set to 100 (the maximum permitted by the REST API) to minimize round trips.

GitLab.com enforces a default 2,000 requests/minute/user. Sub-limits apply to search and raw blob endpoints. Self-managed instances expose configurable limits. The connector reads `RateLimit-Remaining` and `RateLimit-Reset` to pace requests, pauses when below threshold, and applies exponential backoff on `HTTP 429` up to the limit configured in the connector-job template.

### Incremental hook

The `updated_at` field (ISO 8601 with UTC offset) is present on projects, merge requests, issues, and vulnerabilities. The connector records the maximum `updated_at` observed and supplies it as a server-side filter on the next run (e.g., `updated_after` on merge requests and vulnerabilities).

GitLab's webhook system is the primary incremental mechanism where available. Project- or group-level webhooks deliver Push, Merge Request, Issue, Pipeline, Job, Deployment, and (on Ultimate) Vulnerability events. Webhooks are preferred per the SCM capability surface; the `updated_at` high-water mark is the polling fallback and the mechanism used for backfills.

GitLab's `updated_at` is always UTC, so no time-zone normalization is needed.

### Resource schema excerpt

The fields below are the subset consumed by the connector; complete schemas are in the GitLab REST API and Security documentation.

*GitLab `/api/v4/projects` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Numeric project identifier; stable across renames; used as `natural_key` in `silver.repositories`. |
| `path_with_namespace` | string | Human-readable `group/subgroup/project` path; stored as a domain column alongside the integer `id`. |
| `default_branch` | string | Name of the default branch; used to scope protected-branch reads. |
| `visibility` | string | `public`, `internal`, or `private` (see Enumerations). |
| `archived` | boolean | Whether the project has been archived; archived projects are excluded from active-finding computations. |
| `last_activity_at` | datetime (UTC) | Timestamp of the most recent activity on the project; used for staleness detection at the gold layer. |
| `created_at` | datetime (UTC) | Project creation timestamp. |

*GitLab `/api/v4/projects/{id}/repository/commits` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Full SHA-1 commit hash; primary key in `silver.commits`. |
| `short_id` | string | Abbreviated SHA (8 characters); stored for display purposes in reporting outputs. |
| `title` | string | First line of the commit message; used as the commit summary in gold-layer views. |
| `authored_date` | datetime (UTC) | Authoring timestamp; used as the commit's canonical timestamp in `silver.commits`. |
| `committer_date` | datetime (UTC) | Committer timestamp; may differ from `authored_date` for rebased or amended commits. |
| `author_name` | string | Committer display name as recorded in the `git` commit object. |
| `author_email` | string | Committer email address; used to resolve `author_name` to a GitLab user identity where possible. |

*GitLab `/api/v4/projects/{id}/merge_requests` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `iid` | integer | Merge request number within the project; maps to `pull_request.number` in `silver.pull_requests`. |
| `state` | string | Lifecycle state: `opened`, `closed`, or `merged` (see Enumerations). |
| `merged_at` | datetime (UTC) | Merge timestamp; null when the merge request was closed without merging. |
| `created_at` | datetime (UTC) | Creation timestamp. |
| `updated_at` | datetime (UTC) | High-water-mark column for merge-request incremental ingestion. |
| `sha` | string | SHA of the head commit on the source branch at the time of last update. |
| `source_branch` | string | Name of the source (feature) branch. |
| `target_branch` | string | Name of the target branch; used to identify merge requests targeting the default branch. |
| `author.username` | string | GitLab username of the merge request author. |

*GitLab `/api/v4/projects/{id}/vulnerabilities` consumed fields (Ultimate tier only)*

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Vulnerability identifier; primary key across all GitLab security findings for this project. |
| `name` | string | Human-readable vulnerability title as assigned by the scanner rule. |
| `severity` | string | Severity level: `info`, `unknown`, `low`, `medium`, `high`, or `critical` (see Enumerations). |
| `state` | string | Lifecycle state: `detected`, `confirmed`, `dismissed`, or `resolved` (see Enumerations). |
| `report_type` | string | Scanner category that produced the finding (see Enumerations). |
| `confidence` | string | Scanner-assigned confidence in the finding accuracy (see Enumerations). |
| `location.file` | string | Repository-relative file path where the vulnerability was identified; nullable for non-code findings. |
| `location.start_line` | integer | Line number of the vulnerability in the identified file; nullable for non-code findings. |
| `cve` | string | CVE identifier when the finding is linked to a published advisory; the primary join key to the vulnerability-enrichment layer. |
| `identifiers` | array of objects | Structured list of scanner-specific identifiers (e.g. CVE, CWE, OSVDB); the connector extracts the first CVE entry for `cve` when the top-level `cve` field is absent. |
| `created_at` | datetime (UTC) | Timestamp of first detection. |
| `updated_at` | datetime (UTC) | High-water-mark column; updated on every state change. |

### Enumerations

**Vulnerability severity.** `severity` uses six values: `info`, `unknown`, `low`, `medium`, `high`, `critical`. `info` and `unknown` do not map to the framework's four-level canonical scale; both resolve to the connector-configured default severity. `config/severity/gitlab.yml` documents this mapping and must be reviewed per deployment.

**Vulnerability state.** `state` takes `detected` (identified, unreviewed), `confirmed` (true positive), `dismissed` (suppressed without remediation), and `resolved` (remediated). The connector maps these via `config/status/gitlab.yml`.

**Report type.** `report_type` identifies the scanner category: `sast`, `dependency_scanning`, `container_scanning`, `dast`, `secret_detection`, `coverage_fuzzing`, `api_fuzzing`, `cluster_image_scanning`. The connector maps `report_type` to the canonical `category` column in `silver.findings`: `sast`→`sast`, `secret_detection`→`secret`, `dependency_scanning`→`sca`, `dast`→`dast`, `container_scanning`→`container`. Other report types land with `report_type` preserved as a domain column and the nearest canonical `category`.

**Confidence.** `confidence` encodes the scanner's accuracy assessment: `ignore`, `unknown`, `experimental`, `low`, `medium`, `high`, `confirmed`. The connector preserves it verbatim as a domain column; gold-layer risk scoring may use it as a weighting factor.

**Protected-branch access levels.** `protected_branches` returns `allowed_to_push` and `allowed_to_merge` arrays with `access_level` integers: 0 (No access), 30 (Developer), 40 (Maintainer), 60 (Admin). These are translated to the canonical policy vocabulary in the Bronze-to-Silver transform.

### Quirks

**Ultimate-tier requirement for the Vulnerabilities API.** `/projects/{id}/vulnerabilities` and the Security Dashboard require GitLab Ultimate. On lower tiers, findings must be retrieved from CI pipeline artifacts (SARIF or GitLab JSON) via `/projects/{id}/jobs/{job_id}/artifacts`, requiring the connector to enumerate pipeline runs, identify security-producing jobs, and fetch and parse each artifact. This pipeline-level path is documented in the connector's `README` and is selected via the `gitlab_finding_path` Terraform variable.

**Severity fallback for `info` and `unknown`.** `info` (informational, no exploitability) and `unknown` (undetermined) have no canonical four-level equivalent. Both resolve to the connector-configured default. Operators should set this to `low` in `config/severity/gitlab.yml` unless policy dictates otherwise.

**Merge request versus pull request terminology.** GitLab's *merge request* is GitHub's *pull request*. The silver schema uses `pull_requests` uniformly; the connector maps `iid` to `pull_request.number` and records `gitlab` in `source` for platform filtering.

**Integer `id` versus `path_with_namespace`.** GitLab projects are addressable by stable integer `id` and mutable `path_with_namespace` (`group/subgroup/project`). Renaming or moving a project changes the path but not the id. The framework uses `id` as `natural_key` for `silver.repositories` and stores `path_with_namespace` as a domain column for display.

**Mixed finding shapes from a single source.** The Vulnerabilities API emits SAST (code-level), Secret Detection (code-level secrets), Dependency Scanning (package-level / SCA), DAST, and Container Scanning findings interleaved on the same endpoint. Per the SCM capability surface's dual-role guidance, the connector emits distinct dedup keys per shape: `(repository_id, file_path, start_line, rule_id)` for SAST and Secret Detection, and `(repository_id, package_name, cve_id)` for Dependency Scanning. The discriminator is `report_type`.

**Keyset pagination cursor opacity.** GitLab's keyset cursors are opaque and not interchangeable across `order_by` choices. The connector records the `order_by`/`sort` pair alongside the cursor in the high-water-mark state so a configuration change forces a fresh paginate-from-start rather than reusing an incompatible cursor.

## Setup

!!! info "Not implemented in MVP"
    A reference GitLab connector is not part of the MVP. The Reference
    section above documents the intended integration so the
    `generate-connector` skill can emit a connector module when the
    source is scheduled for inclusion. This section will be filled
    in by `generate-connector` at that point.

## Validation

!!! info "Pending validation"
    No validation report has been produced for this connector yet.
    The `validate-implementation` skill populates this section once
    the connector module exists and its requirement-bound tests run
    against the framework.

## Generation log

This connector page is produced by the connector-lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (scm)             | name=GitLab; url=https://docs.gitlab.com/ee/api/; category=scm        | mkdocs/docs/connectors/scm/gitlab.md §1–§3                                         | 2026-04-25 | 2fa3e2d (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (scm)         | page hash=9220324a3e40                                                | src/connectors/gitlab/, tests/connectors/gitlab/, config/severity/gitlab.yml, config/status/gitlab.yml, resources/gitlab-job.yml | 2026-04-25 | 783dbc1 (retrofit-9-connectors)          |
| Validation         | `validate-implementation` (scm)    | (pending)                                                             | (pending)                                                                          | (pending)  | (pending)                                |
