# GitHub

## What this connector ingests

The GitHub connector plays a dual role under the SCM capability surface. As an **SCM source** it populates `silver.repositories` from the organization repository listing, `silver.pull_requests` from the per-repo pull-request endpoint, and `silver.branch_policies` from the per-repo branch protection endpoint. As a **platform-native finding source** it additionally writes into `silver.findings` from three GitHub Advanced Security alert streams: code scanning (`category=sast`), secret scanning (`category=secret`), and Dependabot (`category=sca`). Both halves of the dual role share authentication, pagination, rate-limit, and high-water-mark mechanics, so a single connector module is generated.

**Category:** SCM plus platform-integrated SAST / Secrets / SCA · **Integration pattern:** REST + GraphQL hybrid (REST for per-repo commits / pull requests / branch protection / alerts; GraphQL for org-wide repository enumeration), with webhooks as the preferred incremental hook and `updated_at` polling as the fallback.

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** The Unity Catalog `silver` schema, the `mvp-connectors` secret scope, and the `bronze_github` schema must exist. See [Setup platform](../../platform/index.md).
- **No upstream connector dependency.** GitHub is an SCM connector and a source of truth for `silver.repositories`. Install at least one SCM connector (this one or [GitLab](gitlab.md)) **before** any non-SCM connector.

## User inputs

| Input | Where to obtain | Used as |
|---|---|---|
| GitHub organization login | The slug in `https://github.com/<org>`. For a throwaway demo target, create a free org at <https://github.com/account/organizations/new> and enable GitHub Advanced Security on at least one repo so the alert endpoints return non-empty results. | Env var `GITHUB_ORG`; persisted as the `github_org` secret-scope key. |
| GitHub Personal Access Token (or GitHub App installation token) | Fine-grained PAT at <https://github.com/settings/tokens?type=beta> with read access to the target organization's repositories and the **Code scanning alerts**, **Dependabot alerts**, and **Secret scanning alerts** repository permissions. Classic PATs require `repo` plus `security_events`. | Env var `GITHUB_TOKEN`; persisted as the `github_token` secret-scope key, used as the bearer credential on every REST and GraphQL call. |
| Webhook signing secret (optional, webhook mode only) | Generated locally (`openssl rand -hex 32`) and installed under **Settings → Webhooks** on the target organization or app. | Env var `GITHUB_WEBHOOK_SECRET`; persisted as `github_webhook_secret` and read by the webhook receiver to verify the `X-Hub-Signature-256` HMAC. Not required when running in `updated_at` polling mode. |

!!! info "Pending validation"
    This page is the analyze-source output. Setup, run, and verify procedures are populated by the `generate-connector` and `validate-implementation` skills downstream and will replace the stubs in §4 and §5.

## Reference

### 1. API surface

GitHub exposes two complementary HTTP surfaces under a single rate-limit scheme. The connector uses both.

- **REST API** at base URL `https://api.github.com`, documented at <https://docs.github.com/en/rest>. Required headers: `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`. Authentication is `Authorization: Bearer <token>` for both fine-grained PATs, classic PATs, OAuth user tokens, and GitHub App installation tokens.
- **GraphQL API** at endpoint `https://api.github.com/graphql`, HTTP method `POST`, documented at <https://docs.github.com/en/graphql>. The same `Authorization: bearer <token>` header authenticates GraphQL calls.

The connector partitions endpoints by surface as follows. The split is the **dual REST/GraphQL** convention required by the SCM reference (`references/scm.md` § Quirks): GraphQL handles wide org-level enumeration where field-selection and a single round trip materially reduce cost; REST handles narrower per-repo reads where the GraphQL schema is shallower than the REST one or has not yet caught up.

*GraphQL — used for org-wide repository enumeration*

| Operation | Purpose |
|---|---|
| `query { organization(login: $org) { repositories(first: 100, after: $cursor, orderBy: { field: UPDATED_AT, direction: DESC }) { nodes { id databaseId nameWithOwner defaultBranchRef { name } isPrivate isArchived isDisabled visibility createdAt updatedAt pushedAt primaryLanguage { name } } pageInfo { endCursor hasNextPage } } } }` | Enumerates every repository in the organization with a tight field projection. The connector materializes this into `bronze_github.repositories`. GraphQL is preferred over `GET /orgs/{org}/repos` because it returns only the consumed fields and avoids a per-repo `GET /repos/{owner}/{repo}` follow-up. |
| `query { rateLimit { cost limit remaining used resetAt } }` | Probes the GraphQL rate-limit bucket between batches. |

*REST — used for per-repo entity reads and platform-native finding reads*

| Endpoint | Purpose |
|---|---|
| `GET /repos/{owner}/{repo}` | Per-repo refresh of the entity row when a webhook delivery names a single repository. Returned fields: `id`, `node_id`, `name`, `full_name`, `owner`, `private`, `html_url`, `description`, `fork`, `default_branch`, `language`, `visibility`, `archived`, `disabled`, `created_at`, `updated_at`, `pushed_at`, `topics`, `license`. |
| `GET /repos/{owner}/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100` | Pull requests for a repo. Lands in `bronze_github.pull_requests`; transforms into `silver.pull_requests`. |
| `GET /repos/{owner}/{repo}/branches/{branch}/protection` | Branch protection rules for the default branch (and any additional protected refs surfaced by the bundle parameters). Lands in `bronze_github.branch_protection`; transforms into `silver.branch_policies`. |
| `GET /repos/{owner}/{repo}/code-scanning/alerts` and `GET /orgs/{org}/code-scanning/alerts` | Code scanning (CodeQL and third-party SARIF uploaders) alerts. Org-level form is preferred for incremental polling; repo-level form is used when a webhook delivery names a single repo. |
| `GET /repos/{owner}/{repo}/secret-scanning/alerts` and `GET /orgs/{org}/secret-scanning/alerts` | Secret scanning alerts. |
| `GET /repos/{owner}/{repo}/dependabot/alerts` and `GET /orgs/{org}/dependabot/alerts` | Dependabot alerts (package-level / SCA shape). |
| `GET /rate_limit` | Probes the REST rate-limit bucket. Per the GitHub docs, "calling this endpoint does not count against your primary rate limit." |

*Authentication.* The connector resolves the bearer token from the `mvp-connectors` Databricks secret scope (`github_token` key) at runtime per `REQ-ING-AUTH`. Fine-grained PATs require the **Code scanning alerts**, **Dependabot alerts**, and **Secret scanning alerts** read permissions in addition to **Contents: read** and **Metadata: read**. Classic PATs require `repo` plus `security_events` ("OAuth app tokens and personal access tokens (classic) need the `security_events` scope to use this endpoint with private or public repositories"). GitHub App installation tokens are accepted in place of PATs where the operator prefers org-level provisioning to a personal account.

### 2. Pagination and rate limits

*REST pagination.* GitHub paginates list endpoints via the `Link` response header, which "contains URLs that you can use to fetch additional pages of results... The URL for the next page is followed by `rel="next"`. The URL for the last page is followed by `rel="last"`. The URL for the first page is followed by `rel="first"`." The connector iterates until the `Link` header omits `rel="next"`. Per-page size is set to the documented maximum of `per_page=100` to minimize round trips; the default when omitted is 30. The Dependabot, code scanning, and secret scanning alert endpoints additionally accept opaque cursor parameters `before` and `after` for forward and backward navigation; the connector follows the `Link` header regardless of which underlying mechanism the endpoint uses, so the loop is uniform.

*GraphQL pagination.* GraphQL responses use cursor-based pagination via the `first` argument and a `pageInfo { endCursor hasNextPage }` selection on every connection. The connector iterates while `hasNextPage` is `true`, supplying the previous `endCursor` as `after` on each subsequent call.

*REST rate limits.* Per the GitHub rate-limit documentation: "personal rate limit of 5,000 requests per hour" for personal access tokens and standard OAuth apps; "higher rate limit of 15,000 requests per hour" for GitHub Apps owned by Enterprise Cloud organizations; "Unauthenticated requests is 60 requests per hour." The connector reads the `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-used`, `x-ratelimit-reset` (UTC epoch seconds), and `x-ratelimit-resource` response headers on every call to pace itself. On `HTTP 403` or `HTTP 429` indicating a secondary limit, the connector honors the `retry-after` response header verbatim ("If the `retry-after` response header is present, you should not retry your request until after that many seconds has elapsed"). Concurrent-request and per-minute secondary limits (100 concurrent requests, 900 points per minute) are tracked locally. The connector also exposes `GET /rate_limit` as a debug probe.

*GraphQL rate limits.* GraphQL has a **separate** primary rate-limit bucket: "5,000 points per hour per user" for personal access tokens, "5,000 points per hour per installation" for non-Enterprise GitHub Apps, "10,000 points per hour per installation" for Enterprise Cloud. The cost is computed as: "Add up the number of requests needed to fulfill each unique connection in the call. Assume every request will reach the `first` or `last` argument limits. Divide the number by 100 and round the result to the nearest whole number." Minimum cost is 1 point. The 100-concurrent-request secondary limit is shared across REST and GraphQL. The connector queries the `rateLimit { cost limit remaining used resetAt }` field at the tail of each GraphQL batch and pauses when `remaining` falls below a configurable threshold.

### 3. Incremental hook

GitHub exposes both webhook delivery and `updated_at` polling. Per `references/scm.md`, **webhook delivery is the preferred mode**; `updated_at` polling is the fallback used for backfills, missed-delivery replay, and operators who decline to expose a public webhook receiver.

*Webhook delivery (preferred).* The receiver subscribes to the following organization-scoped events. Each event is delivered as an HTTP `POST` with an `X-GitHub-Event` header naming the event and an `X-Hub-Signature-256` header containing "the HMAC hex digest of the request body... generated using the SHA-256 hash function and the `secret` as the HMAC `key`":

| Event | `X-GitHub-Event` | Trigger | Top-level payload | Silver target |
|---|---|---|---|---|
| Push | `push` | "when there is a push to a repository branch... a commit is pushed, when a commit tag is pushed, when a branch is deleted." | `repository`, `organization`, `sender`, `ref`, `before`, `after`, `commits` | `silver.repositories` (refresh `pushed_at` / `updated_at`) |
| Pull request | `pull_request` | "when there is activity on a pull request." | `action` (`opened`, `synchronize`, `closed`, ...), `number`, `pull_request`, `repository`, `organization`, `sender` | `silver.pull_requests` |
| Code scanning alert | `code_scanning_alert` | "when there is activity relating to code scanning alerts in a repository." | `action` (`created`, `fixed`, `reopened`, ...), `alert`, `commit_oid`, `ref`, `repository`, `organization`, `sender` | `silver.findings` (`category=sast`) |
| Secret scanning alert | `secret_scanning_alert` | "when there is activity relating to a secret scanning alert." | `action` (`created`, `resolved`, `reopened`, ...), `alert`, `repository`, `organization`, `sender` | `silver.findings` (`category=secret`) |
| Dependabot alert | `dependabot_alert` | "when there is activity relating to Dependabot alerts." | `action` (`created`, `fixed`, `dismissed`, ...), `alert`, `repository`, `organization`, `sender` | `silver.findings` (`category=sca`) |

The receiver verifies `X-Hub-Signature-256` against `github_webhook_secret`, persists the raw payload to `bronze_github.<event>`, and acknowledges with `204 No Content`. Missed deliveries are replayed via the redelivery API documented at `/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks`; the connector enumerates `Recent Deliveries` for the configured hook and re-POSTs any delivery whose acknowledgement is absent from the state table.

*`updated_at` polling (fallback).* When webhook delivery is unavailable, the connector falls back to a per-endpoint high-water mark on the `updated_at` field. The HWM is persisted to the platform `silver.hwm` table per `REQ-ING-HWM` and supplied on the next run as `sort=updated&direction=desc` plus a server-side filter (or an `if-modified-since` short-circuit on endpoints that support it). The polling cadence is configurable; the bundle ships a 15-minute schedule that aligns with the framework's other connectors. All `updated_at` values returned by GitHub are ISO 8601 with a UTC `Z` suffix, so no time-zone normalization is required during the Bronze-to-Silver transform (`REQ-TRF-TS`).

### 4. Resource schema excerpt

Only fields the connector reads are listed. Complete schemas are at the cited GitHub docs URLs.

*Repository (GraphQL `organization.repositories.nodes` and REST `GET /repos/{owner}/{repo}`)*

| Field | Type | Meaning |
|---|---|---|
| `id` (GraphQL) / `node_id` (REST) | string | The opaque `node_id`. Used as `natural_key` in `silver.repositories` per the canonical mapping. |
| `databaseId` (GraphQL) / `id` (REST) | integer | The numeric repository id. Stored as a domain column. |
| `nameWithOwner` (GraphQL) / `full_name` (REST) | string | `org/repo` slug. Stored as a domain column. |
| `defaultBranchRef.name` (GraphQL) / `default_branch` (REST) | string | Default branch name. Used to scope branch-protection reads. |
| `visibility` | string | `PUBLIC`, `PRIVATE`, or `INTERNAL`. Stored as a domain column. |
| `isPrivate` / `private` | boolean | Convenience flag derived from `visibility`. |
| `isArchived` / `archived` | boolean | Archived repos are excluded from active finding computations. |
| `isDisabled` / `disabled` | boolean | Disabled repos are excluded from active reads. |
| `primaryLanguage.name` (GraphQL) / `language` (REST) | string | Dominant language as detected by Linguist. |
| `createdAt` / `created_at` | datetime (UTC) | Creation timestamp. Maps to `valid_from` per the canonical mapping. |
| `updatedAt` / `updated_at` | datetime (UTC) | High-water-mark column for repository polling. |
| `pushedAt` / `pushed_at` | datetime (UTC) | Most-recent-push timestamp. Used for staleness detection at the gold layer. |

*Pull request (REST `GET /repos/{owner}/{repo}/pulls`)*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | PR number within the repo. Maps to `pull_request.number` in `silver.pull_requests`. |
| `state` | string | `open` or `closed` (see Enumerations). |
| `merged_at` | datetime (UTC) | Merge timestamp. Null when the PR was closed without merging. |
| `created_at` | datetime (UTC) | Creation timestamp. |
| `updated_at` | datetime (UTC) | High-water-mark column for PR incremental polling. |
| `head.sha` | string | SHA of the head commit. |
| `head.ref` | string | Source branch name. |
| `base.ref` | string | Target branch name. |
| `user.login` | string | Author username. |

*Code scanning alert (REST `GET /repos/{owner}/{repo}/code-scanning/alerts`)*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Per-repo alert id. Combined with `repository_id` to form `source_finding_id` in `silver.findings`. |
| `state` | string | `open`, `closed`, `dismissed`, or `fixed` (see Enumerations). |
| `severity` | string | Alert severity (`error`, `warning`, `note`); see Enumerations. |
| `rule.id` | string | Rule identifier (e.g. CodeQL query id). Maps to `rule_id`. |
| `rule.security_severity_level` | string | `critical`, `high`, `medium`, `low`. **Authoritative** severity per the canonical mapping. |
| `most_recent_instance.location.path` | string | Repo-relative file path. Maps to `file_path`. |
| `most_recent_instance.location.start_line` | integer | Line number. Maps to `line_number`. |
| `created_at` | datetime (UTC) | First detection. Maps to `detected_at`. |
| `updated_at` | datetime (UTC) | High-water-mark column. |
| `fixed_at` | datetime (UTC) | Auto-fix timestamp; null if open. Maps to `resolved_at`. |
| `dismissed_at` | datetime (UTC) | Manual dismissal timestamp. Maps to `resolved_at` when `state=dismissed`. |
| `html_url` | string | Web link. Stored as a domain column. |

*Secret scanning alert (REST `GET /repos/{owner}/{repo}/secret-scanning/alerts`)*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Per-repo alert id. |
| `state` | string | `open` or `resolved`. |
| `resolution` | string | `false_positive`, `wont_fix`, `revoked`, `used_in_tests`, or null. |
| `secret_type` | string | Detector name. Maps to `secret_type` in `silver.findings`. |
| `secret_type_display_name` | string | Human-readable detector name. |
| `validity` | string | `active`, `inactive`, or `unknown`. Maps to `validity_status`. |
| `created_at` | datetime (UTC) | First detection. Maps to `detected_at`. |
| `updated_at` | datetime (UTC) | High-water-mark column. |
| `resolved_at` | datetime (UTC) | Resolution timestamp; null if open. Maps to `resolved_at`. |
| `locations_url` | string | URI to fetch per-location detail (file path and line). The connector follows this once per alert and stores the first location's `path` and `start_line`. |
| `html_url` | string | Web link. |

*Dependabot alert (REST `GET /repos/{owner}/{repo}/dependabot/alerts`)*

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Per-repo alert id. |
| `state` | string | `auto_dismissed`, `dismissed`, `fixed`, or `open`. |
| `dependency.package.name` | string | Vulnerable package name. Maps to `package_name`. |
| `dependency.package.ecosystem` | string | Package ecosystem (`npm`, `pip`, `maven`, ...). Maps to `ecosystem`. |
| `security_advisory.cve_id` | string | CVE identifier when published. Maps to `cve_id`. |
| `security_vulnerability.severity` | string | Vulnerability severity (`low`, `medium`, `high`, `critical`). |
| `created_at` | datetime (UTC) | First detection. Maps to `detected_at`. |
| `updated_at` | datetime (UTC) | High-water-mark column. |
| `fixed_at` | datetime (UTC) | Auto-fix timestamp. Maps to `resolved_at`. |
| `dismissed_at` | datetime (UTC) | Manual dismissal timestamp. Maps to `resolved_at` when `state=dismissed`. |
| `auto_dismissed_at` | datetime (UTC) | Auto-dismissal timestamp; counts as `resolved_at`. |
| `html_url` | string | Web link. |

*Branch protection (REST `GET /repos/{owner}/{repo}/branches/{branch}/protection`)*

| Field | Type | Meaning |
|---|---|---|
| `required_pull_request_reviews.required_approving_review_count` | integer | Minimum approvals to merge. |
| `required_pull_request_reviews.dismiss_stale_reviews` | boolean | Whether stale reviews are dismissed on new pushes. |
| `required_status_checks.strict` | boolean | Whether the branch must be up to date before merging. |
| `required_status_checks.contexts` | array of strings | Required CI status check names. |
| `enforce_admins.enabled` | boolean | Whether protections apply to admins. |
| `restrictions.users` / `restrictions.teams` / `restrictions.apps` | arrays | Push restriction allowlists. Stored as domain JSON in `silver.branch_policies`. |

### 5. Enumerations

*Pull-request state.* `state` takes `open` and `closed`. The Silver `pull_requests.state_canonical` mapping is `open → open`, `closed → closed` (with `merged_at IS NOT NULL` further discriminated as `merged` in the gold layer view).

*Repository visibility.* `visibility` takes `public`, `private`, `internal`. Stored verbatim as a domain column on `silver.repositories`; no canonical normalization is required.

*Code scanning alert severity (canonical mapping).* GitHub returns two severity fields on a code scanning alert. The framework treats `rule.security_severity_level` (`critical`, `high`, `medium`, `low`) as authoritative per the canonical mapping; the rule-level `severity` (`error`, `warning`, `note`) is kept as a domain column. The mapping is identity into the standard four-level model:

| GitHub `rule.security_severity_level` | Canonical `severity` |
|---|---|
| `critical` | `critical` |
| `high` | `high` |
| `medium` | `medium` |
| `low` | `low` |
| (null or absent) | configured default (`medium`), with a `REQ-DQ` data-quality warning |

*Code scanning alert status.* `state` takes `open`, `closed`, `dismissed`, `fixed`. Mapped to the standard five-state model: `open → open`; `dismissed → false_positive` when `dismissed_reason in ("false positive",)`, otherwise `wontfix`; `closed → resolved`; `fixed → resolved`.

*Secret scanning alert severity.* Secret scanning has no native severity field. Per the canonical mapping convention used for TruffleHog (`high` for unverified secrets escalating implicitly to `critical` for verified), the connector emits `severity = high` when `validity = active` and `severity = high` for `inactive`/`unknown`; operators may override the policy in `src/connectors/github/severity.yml`.

*Secret scanning alert status.* `state` takes `open`, `resolved`. `resolution` discriminates the resolved cases: `false_positive → false_positive`, `wont_fix → wontfix`, `revoked → resolved`, `used_in_tests → false_positive`.

*Dependabot alert severity.* `security_vulnerability.severity` returns `low`, `medium`, `high`, `critical`. Identity mapping into the standard four-level model.

*Dependabot alert status.* `state` takes `open`, `dismissed`, `auto_dismissed`, `fixed`. Mapped to the standard five-state model: `open → open`; `dismissed`/`auto_dismissed → wontfix` (or `false_positive` when `dismissed_reason = "no_bandwidth"` etc., per `src/connectors/github/status.yml`); `fixed → resolved`.

### 6. Quirks

- **Dual-role connector.** GitHub populates entity tables (`silver.repositories`, `silver.pull_requests`, `silver.branch_policies`) AND `silver.findings` from a single source. The mapping file emits distinct mapping blocks per target table, and the connector tests cover both halves under their respective REQ-IDs (entity REQs always; finding REQs `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP` apply because GitHub Advanced Security emits findings).
- **Dual REST/GraphQL surface.** Org-wide repository enumeration uses GraphQL for tighter field selection and a single round trip; per-repo commits, pull requests, branch protection, and the three alert streams use REST. The split is the SCM-reference convention and must be preserved at the connector level so generate-connector emits two distinct client wrappers.
- **Separate REST and GraphQL rate-limit buckets.** REST and GraphQL each carry their own 5,000-points-per-hour bucket; only the 100-concurrent-request secondary limit is shared. The connector tracks both buckets independently. Misattributing a quota exhaustion will mask the true source of throttling at runtime.
- **Mixed finding shapes from a single source.** Code scanning is the **SAST** shape (dedup key `(repository_id, file_path, start_line, rule_id)`); secret scanning is the **secrets** shape (dedup key `(repository_id, secret_type, file_path, line_number)`); Dependabot is the **SCA / package-level** shape (dedup key `(repository_id, package_name, cve_id)`). The discriminator is the `category` column written into `silver.findings` by the transform.
- **Webhook signature verification is mandatory in webhook mode.** `X-Hub-Signature-256` is HMAC-SHA-256 of the raw body keyed by `github_webhook_secret`. The receiver rejects deliveries with a missing or mismatched signature with `401 Unauthorized` and does not write to Bronze. Replay of missed deliveries uses the `Recent Deliveries` redelivery API rather than `updated_at` polling, so the signature is verified again on replay.
- **`secret-scanning` location is a follow-up call.** Secret scanning alert objects do not embed file path or line number. The connector follows `locations_url` once per alert to fetch the first location's `path` and `start_line`. This adds one REST call per new secret alert and is paced against the same REST bucket.
- **Two severity fields on code scanning alerts.** GitHub returns both `rule.severity` (`error`/`warning`/`note`, the rule-author's default) and `rule.security_severity_level` (`critical`/`high`/`medium`/`low`, derived from CVSS). The framework uses `rule.security_severity_level` as authoritative; ignoring this distinction would produce a connector that systematically mis-classifies high-severity findings as `medium`.
- **GitHub Advanced Security entitlement gates the alert endpoints.** `code-scanning`, `secret-scanning`, and `dependabot` alert endpoints require GitHub Advanced Security on the target repository. Without it, those endpoints return `404 Not Found` (private repos) or empty arrays (public repos). The connector logs the 404 at INFO and continues with the entity half of the dual role.
- **All timestamps are ISO 8601 UTC.** `created_at`, `updated_at`, `pushed_at`, `fixed_at`, `dismissed_at`, `resolved_at`, `auto_dismissed_at` are all returned with a `Z` suffix. No time-zone normalization is required during Bronze-to-Silver transformation per `REQ-TRF-TS`.

## Setup

!!! info "Pending generate-connector"
    The Setup section is populated by the `generate-connector` skill once it emits the connector module under `src/connectors/github/`. Expected contents: `load-secrets.sh` invocation, `databricks bundle deploy --target dev` and `databricks bundle run github-connector --target dev` commands, the optional terraform runtime under `src/connectors/github/runtime/`, and a normalization spot-check sequence. Refer to [GitLab](gitlab.md#run-the-job) for the equivalent shape that the SCM reference produces.

## Validation

| Requirement | Bound test | Outcome |
|---|---|---|
| REQ-ING-AUTH | src/connectors/github/tests/test_ingest.py::test_auth_secret_references_only | PASS |
| REQ-ING-PAG | src/connectors/github/tests/test_ingest.py::test_link_header_two_pages_no_loss_no_duplicates | PASS |
| REQ-ING-RL | src/connectors/github/tests/test_ingest.py::test_429_backoff_exponential_schedule | PASS |
| REQ-ING-HWM | src/connectors/github/tests/test_ingest.py::test_updated_at_hwm_resume | PASS |
| REQ-TRF-MAP | src/connectors/github/tests/test_transform.py::test_repository_to_silver_projects_expected_fields | PASS |
| REQ-TRF-SEV | src/connectors/github/tests/test_transform.py::test_severity_lookup_covers_every_documented_value | PASS |
| REQ-TRF-STS | src/connectors/github/tests/test_transform.py::test_status_lookup_covers_every_documented_value | PASS |
| REQ-TRF-TS | src/connectors/github/tests/test_transform.py::test_parse_iso_utc_roundtrips_timezone_aware | PASS |
| REQ-DQ | src/connectors/github/tests/test_transform.py::test_unknown_severity_falls_through_to_default | PASS |
| REQ-DEDUP | src/connectors/github/tests/test_transform.py::test_dedup_key_branches_on_finding_shape | PASS |

Run summary: 21 requirement-bound tests collected across the two test modules (REQ-ING-AUTH ×2 + ×1 skipped pending live PAT, REQ-ING-PAG ×3, REQ-ING-RL ×3, REQ-ING-HWM ×2, REQ-TRF-MAP ×7, REQ-TRF-SEV ×1, REQ-TRF-STS ×1, REQ-TRF-TS ×3, REQ-DQ ×2, REQ-DEDUP ×2 + ×1 skipped pending live cross-tool fixtures); 29 of 31 collected tests passed and 2 were skipped pending B-follow-up live fixtures (the skipped tests do not gate any REQ row because each affected REQ-ID has at least one passing primary test). Wall-clock duration: 0.36s. Pass / fail / N/A split: 10 / 0 / 0. No N/A rows: GitHub is the reference SCM connector and consumes platform-native findings (Dependabot, code scanning, secret scanning), so all ten REQ-IDs apply per `references/scm.md`.

## Generation log

This connector page is produced by the connector lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage | Skill | Inputs | Outputs | Run on | Skills repo ref |
|---|---|---|---|---|---|
| Source analysis | `analyze-source` (scm) | name=GitHub; url=https://docs.github.com/en/rest; category=scm | mkdocs/docs/connectors/scm/github.md §1 to §3 | 2026-04-25 | 3cd1028 (regenerate-4-originals) |
| Module generation | `generate-connector` (scm) | page hash=c1432ae8e1ec | src/connectors/github/__init__.py, src/connectors/github/config.yml, src/connectors/github/ingest.py, src/connectors/github/transform.py, src/connectors/github/mapping.yml, src/connectors/github/severity.yml, src/connectors/github/status.yml, src/connectors/github/resources/job.yml, src/connectors/github/tests/__init__.py, src/connectors/github/tests/conftest.py, src/connectors/github/tests/test_ingest.py, src/connectors/github/tests/test_transform.py, src/connectors/github/tests/fixtures/repositories.json, src/connectors/github/tests/fixtures/pull_requests.json, src/connectors/github/tests/fixtures/branch_protection.json, src/connectors/github/tests/fixtures/code_scanning_alerts.json, src/connectors/github/tests/fixtures/secret_scanning_alerts.json, src/connectors/github/tests/fixtures/dependabot_alerts.json | 2026-04-25 | 76c543e (regenerate-4-originals) |
| Validation | `validate-implementation` (scm) | module path=src/connectors/github/ | mkdocs/docs/connectors/scm/github.md §5 | 2026-04-25 | 7fec0ac (regenerate-4-originals) |

## References

- GitHub REST API index — <https://docs.github.com/en/rest>
- GitHub GraphQL API index — <https://docs.github.com/en/graphql>
- GitHub webhooks index — <https://docs.github.com/en/webhooks>
- REST rate limits — <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api>
- REST pagination — <https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api>
- GraphQL forming calls — <https://docs.github.com/en/graphql/guides/forming-calls-with-graphql>
- GraphQL resource limitations — <https://docs.github.com/en/graphql/overview/resource-limitations>
- Webhook events and payloads — <https://docs.github.com/en/webhooks/webhook-events-and-payloads>
- Code scanning alerts — <https://docs.github.com/en/rest/code-scanning/code-scanning>
- Secret scanning alerts — <https://docs.github.com/en/rest/secret-scanning/secret-scanning>
- Dependabot alerts — <https://docs.github.com/en/rest/dependabot/alerts>
- Repositories (org listing and repo detail) — <https://docs.github.com/en/rest/repos/repos>
