# Databricks app

`appsec-analytics-app` is a small FastAPI service hosted as a Databricks
App. It is the OLTP serving surface for the analytics layer: a security
score lookup for SOC dashboards and Slack bots, and a CI/CD pre-merge
gate that decides whether a candidate set of findings should block a PR.

The App reads from the two
[Online Tables](online-tables.md) — never directly from the Gold or
Silver Delta tables — so latency stays in the sub-second range.

## Purpose

Two OLTP use cases drive the App:

- **Security score lookups.** A SOC dashboard or a Slack `/secscore <app>`
  bot needs the current risk posture for a single application in
  under 50 ms. The App computes a single-number score plus a severity
  breakdown from `gold_online.app_risk_posture`.
- **Pre-merge gate.** A CI/CD pipeline (GitHub Actions, GitLab CI,
  Jenkins) calls the App on every PR with a list of candidate
  finding ids. The App fetches those findings from
  `silver_online.app_repo_findings`, applies the configured policy
  threshold, and returns an allow/block verdict plus the blocking
  findings.

A Databricks SQL serverless endpoint could serve raw queries with no
code, but the pre-merge gate has policy logic that needs to live
somewhere. Co-locating both endpoints in one App means one service to
deploy, monitor, and authenticate.

## Endpoints

### `GET /v1/score?app_id=<id>`

Returns the latest open-finding severity breakdown and a derived score
for one `application_id`. Reads from `gold_online.app_risk_posture`.

**Performance target:** <50 ms p99.

**Request.**

```http
GET /v1/score?app_id=APP-001 HTTP/1.1
```

**Response (200 OK).**

```json
{
  "application_id": "APP-001",
  "score": 23,
  "severity_breakdown": {
    "critical": 2,
    "high": 1,
    "medium": 0,
    "low": 0
  },
  "snapshot_date": "2026-04-25"
}
```

The score is computed in the App from the severity breakdown using the
canonical formula:

```text
score = critical * 10 + high * 3 + medium * 1 + low * 0
```

**Response (404 Not Found).** Returned when no rows exist in
`gold_online.app_risk_posture` for the requested `application_id`. The
caller (Slack bot, dashboard tile) should treat this as "no posture
data yet" rather than an error.

```json
{
  "detail": "No risk-posture rows found for application_id='APP-999'"
}
```

### `POST /v1/precommit?repo=<repo>&pr_id=<pr>`

Evaluates the pre-merge gate for a list of candidate finding ids. The
CI/CD caller passes the ids of findings the PR would introduce; the App
fetches each finding's severity from `silver_online.app_repo_findings`
and applies the configured policy.

**Performance target:** <500 ms p99.

**Request.**

```http
POST /v1/precommit?repo=myorg/web-app&pr_id=1234 HTTP/1.1
Content-Type: application/json

{
  "candidate_finding_ids": [
    "finding-abc123",
    "finding-def456",
    "finding-ghi789"
  ]
}
```

**Response (200 OK, blocked).**

```json
{
  "allow": false,
  "blocking_findings": [
    {
      "finding_id": "finding-abc123",
      "severity_canonical": "critical",
      "repository_id": "myorg/web-app",
      "application_id": "APP-001"
    }
  ],
  "policy_summary": "1 of 3 candidate findings meet or exceed threshold 'high'; block.",
  "repo": "myorg/web-app",
  "pr_id": "1234"
}
```

**Response (200 OK, allowed).**

```json
{
  "allow": true,
  "blocking_findings": [],
  "policy_summary": "No candidate finding meets or exceeds threshold 'high'; allow.",
  "repo": "myorg/web-app",
  "pr_id": "1234"
}
```

**Empty candidate list.** When the body's `candidate_finding_ids` is
empty (or the body is omitted), the App short-circuits with `allow:
true` and a `"No candidate findings supplied; allow."` summary — no SQL
is executed.

**Response (400 Bad Request).** Returned when the request body's
`candidate_finding_ids` is not a list.

## Policy config

Policy lives in `src/analytics/app/policy.yml`. The MVP exposes a single
knob:

```yaml
block_severity_threshold: high  # block if any finding is at or above this severity
```

`block_severity_threshold` accepts one of `info`, `low`, `medium`,
`high`, `critical`. Semantics: a candidate finding **blocks** the PR
when its `severity_canonical` rank is greater than or equal to the
threshold rank, where the rank ordering is the canonical severity
ladder (`info < low < medium < high < critical`).

To override the threshold, edit `policy.yml` and redeploy:

```bash
databricks bundle deploy --target dev
```

A future iteration will load the policy at request time so threshold
changes are live without redeploy. For the MVP, redeploy is the
mechanism.

If `policy.yml` is missing or contains an unrecognised threshold, the
App falls back to `high` (the documented default) and continues serving
traffic — see `src/analytics/app/policy.py::load_policy`.

## Deployment

The App is declared as a Databricks Asset Bundle resource at
`src/analytics/resources/app.yml`:

```yaml
resources:
  apps:
    appsec_analytics_app:
      name: appsec-analytics-app
      description: "OLTP serving for AppSec analytics — security score lookup + CI/CD pre-merge gate"
      source_code_path: ../app
```

Deploy:

```bash
databricks bundle deploy --target dev
```

Smoke-test (this prints the App's URL and runs the configured smoke
endpoint, or opens the App's UI page in the browser depending on
workspace settings):

```bash
databricks apps run appsec-analytics-app
```

A direct curl against the deployed App, replacing `<app-url>` with the
URL printed by `databricks apps`:

```bash
curl -s "<app-url>/v1/score?app_id=APP-001"
```

## Authentication

For the MVP, the App relies on Databricks workspace identity. Callers
must be authenticated to the workspace; the App itself authenticates to
the SQL serverless endpoint with a personal access token (PAT) supplied
via env var. There is no per-caller authn or rate limiting.

External callers — for example a CI/CD runner outside the workspace
needing to call `/v1/precommit` — currently must hold a workspace token.
Bearer-token auth at the App layer (so the App can mint short-lived
tokens for CI/CD callers without giving them workspace tokens) is a
documented future-iteration item.

## Configuration

The App reads its Databricks SQL serverless connection params from three
env vars, set on the App's resource at deploy time:

| Env var | Purpose |
|---|---|
| `DATABRICKS_SERVER_HOSTNAME` | Workspace hostname (e.g. `dbc-xxxx.cloud.databricks.com`). |
| `DATABRICKS_HTTP_PATH` | HTTP path of the serverless SQL warehouse (from the warehouse's connection details page). |
| `DATABRICKS_TOKEN` | PAT with read access to the two Online Tables. |

If any of the three is missing, the App raises `RuntimeError` on the
first request (it does not start a process that cannot serve traffic;
the failure is loud and fast).

`policy.yml` is read from `src/analytics/app/policy.yml` (relative to
the App source directory) on every request — see "Policy config" above.

## Observability

For the MVP, the App logs to stdout via FastAPI's default logger.
Databricks captures App stdout in the Compute logs UI; access via the
App's resource page in the workspace.

A future iteration will add:

- Structured JSON logging keyed on `request_id`.
- Per-endpoint p50/p99 latency metrics emitted to a Databricks system
  table or a workspace-side observability surface.
- Per-caller request counts (once bearer-token auth distinguishes
  callers).

For now, operators tail the Compute logs when investigating; the App's
small surface (two endpoints, one query helper per endpoint) keeps
log-based debugging tractable.
