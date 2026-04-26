# Online tables

Online Tables are Databricks-managed row-store replicas of Unity Catalog
Delta tables. They sit on the OLTP side of the analytics layer and are
served via Databricks SQL serverless at sub-50 ms primary-key lookup
latency. The MVP declares two: one backs the security-score endpoint,
one backs the pre-merge gate.

## What Online Tables are

A regular UC Delta table is optimised for wide aggregations against
columnar files on object storage. That is the right shape for analyst
queries — but it is the wrong shape for "give me the row for this PK
right now" calls from a Slack bot, an IDE plugin, or a CI/CD gate. An
Online Table is a synchronised replica of a Delta table in a row-store
backend that Databricks hosts and manages: you declare a source table
and the PK columns, and Databricks keeps the replica in sync.

Reads happen through a Databricks SQL serverless warehouse using the
same SQL dialect; the difference is purely in cost and latency. Range
scans by PK return in milliseconds rather than seconds.

The two Online Tables in this MVP are declared in
`src/analytics/resources/online_tables.yml` and provisioned automatically
by `databricks bundle deploy`. The `gold_online` and `silver_online` UC
schemas that hold them are declared in
`src/analytics/resources/online_schemas.yml`.

## The two Online Tables in this MVP

### `gold_online.app_risk_posture`

Backs the `GET /v1/score` endpoint of the analytics App.

| Field | Value |
|---|---|
| Source table | `gold.app_risk_posture_daily` |
| Primary key | `(application_id, severity_canonical, snapshot_date)` |
| Refresh mode | `run_continuously` (~5-min lag) |
| Typical query | Latest posture for one `application_id` |

```sql
SELECT severity_canonical, open_count, snapshot_date
FROM gold_online.app_risk_posture
WHERE application_id = ?
  AND snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM gold_online.app_risk_posture
    WHERE application_id = ?
  );
```

This is the exact query the App runs in
`src/analytics/app/queries.py::fetch_score` to build the score response.

### `silver_online.app_repo_findings`

Backs the `POST /v1/precommit` endpoint of the analytics App. The CI/CD
caller passes a list of candidate `finding_id`s; the App fetches their
severities by PK lookup against this Online Table.

| Field | Value |
|---|---|
| Source table | `gold.app_repo_findings_open` (a Gold view, not a materialised table) |
| Primary key | `finding_id` |
| Refresh mode | `run_continuously` (~5-min lag) |
| Typical query | Bulk fetch by `finding_id IN (…)` |

```sql
SELECT finding_id, severity_canonical, repository_id, application_id
FROM silver_online.app_repo_findings
WHERE finding_id IN (?, ?, ?);
```

The view this Online Table syncs from already filters to
`status_canonical = 'open'`, so the App does not need to re-filter.

## Refresh mode

Both Online Tables use `run_continuously: {}` in
`online_tables.yml`. Databricks streams change data from the source
Delta table into the row-store replica with a typical lag of about five
minutes. The lag is measured from when the source Delta table is
written, not from when the upstream Silver ingest completed — so the
end-to-end freshness is bounded by the Gold refresh cadence (daily
05:00 UTC) plus the Online Table sync lag (~5 min).

The full bundle declaration:

```yaml
resources:
  online_tables:
    app_risk_posture:
      name: ${var.catalog}.gold_online.app_risk_posture
      spec:
        source_table_full_name: ${var.catalog}.gold.app_risk_posture_daily
        primary_key_columns: [application_id, severity_canonical, snapshot_date]
        run_continuously: {}
    app_repo_findings:
      name: ${var.catalog}.silver_online.app_repo_findings
      spec:
        source_table_full_name: ${var.catalog}.gold.app_repo_findings_open
        primary_key_columns: [finding_id]
        run_continuously: {}
```

## Operator runbook

### Provision

The Online Tables and their schemas are part of the Databricks Asset
Bundle. Deploying the bundle creates them along with the analytics job:

```bash
databricks bundle deploy --target dev
```

### Verify

In the Databricks workspace, open Catalog Explorer and navigate to:

- `<catalog>.gold_online.app_risk_posture`
- `<catalog>.silver_online.app_repo_findings`

Each should show:

- A green "Online" badge with the most recent sync timestamp.
- A row count consistent with the source table (count parity is checked
  on every continuous-sync flush).
- The declared primary key columns flagged as PK in the schema view.

If the Online badge reads "Provisioning…" for more than 10 minutes after
the first deploy, check the Databricks workspace audit log under the
Online Tables service for region or quota errors.

### Force a re-sync

Continuous mode normally needs no manual intervention. If the operator
needs to force a sync (for example after a bulk Silver re-ingest):

```bash
databricks online-tables refresh \
  --name <catalog>.gold_online.app_risk_posture
```

The CLI returns a sync identifier; tail the workspace UI for status.

## Query pattern

The App opens a Databricks SQL serverless connection per request via
`databricks.sql.connect`, parameterised from environment variables:

```python
from databricks import sql

with sql.connect(
    server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
    http_path=os.environ["DATABRICKS_HTTP_PATH"],
    access_token=os.environ["DATABRICKS_TOKEN"],
) as conn, conn.cursor() as cursor:
    cursor.execute(
        """
        SELECT severity_canonical, open_count, snapshot_date
        FROM gold_online.app_risk_posture
        WHERE application_id = ?
          AND snapshot_date = (
            SELECT MAX(snapshot_date)
            FROM gold_online.app_risk_posture
            WHERE application_id = ?
          )
        """,
        (app_id, app_id),
    )
    rows = cursor.fetchall()
```

The serverless endpoint URL is taken from the workspace's SQL warehouse
list; PAT-based auth is the MVP's mechanism. Direct Databricks SQL
queries against an Online Table have the same dialect as queries
against a Delta table — only the latency differs.

The App owns this connection lifecycle on behalf of every caller; SOC
analysts and tool integrators call the App's HTTP endpoints rather than
opening SQL connections themselves. That keeps connection pooling, env
var management, and policy logic in one place.

## Failure mode and fallback

Online Tables are region-dependent. If the workspace's region does not
support Online Tables, deployment of `online_tables.yml` will fail with
a region-not-supported error.

Fallback path: the same SQL query works against the underlying Delta
table directly through a Databricks SQL serverless warehouse. The App's
`fetch_score` and `fetch_findings` helpers can be repointed to the
underlying tables (`gold.app_risk_posture_daily` and
`gold.app_repo_findings_open`) by changing the `FROM` clauses; the
schemas and column names are identical because the Online Tables are
straight replicas. Latency degrades from sub-50 ms to roughly 200 ms p99
for the score endpoint, and to roughly 500 ms p99 for the bulk
finding-id lookup. Functionally, the App continues to work.

This fallback is also the right choice during local development against
a dev workspace where the operator does not want to pay for the Online
Tables sync — the App does not need code changes, only an env var (or a
config flag in a future iteration) to flip the source table name.
