# App-repo linker

The app-repo linker populates [`silver.app_repo_mapping`](reference/catalog.md) by extracting a 5-digit business application code from each repository's `full_name` and joining it to `silver.applications.app_code`. It is the SCM-naming-convention path; a parallel `cmdb_rel_ci`-derived path is planned and will write into the same table with a different `link_source` value.

## What it does

For every row in `silver.repositories`, the linker:

1. Searches `full_name` for a bounded 5-digit token using the regex below (the lookarounds prevent partial matches inside longer alphanumeric runs):

   ```text
   (?<![A-Za-z0-9])(\d{5})(?![A-Za-z0-9])
   ```

2. If exactly one or more 5-digit tokens are present, takes the **first** match.
3. Looks the matched code up in `silver.applications.app_code`.
4. If a match is found, writes one row to `silver.app_repo_mapping` per matching application:

| Column | Value |
|---|---|
| `application_id` | `silver.applications.application_id` of the matched app (the ServiceNow `sys_id`) |
| `repository_id` | `silver.repositories.repository_id` |
| `link_source` | `"name_match"` |
| `linked_at` | The job run timestamp (UTC) |

5. If a code is extracted but does not resolve in `silver.applications`, the row is dropped silently. The job logs `app_repo_link: unmatched code <code> for repo <repo_id>` at INFO level and increments an `unknown_code` counter at job end.
6. If no 5-digit token is found in `full_name`, the row is silently skipped (counted in `no_code`).

## Where the 5-digit code lives in CMDB

The ServiceNow connector projects `cmdb_ci_business_app.u_app_id` to `silver.applications.app_code`. Only values matching `^\d{5}$` exactly survive — empty strings, non-digit characters, and 4- or 6-digit values all coerce to `NULL`. Applications with `app_code = NULL` cannot be linked by name; they remain reachable via the existing `u_repository_id` path on the ServiceNow transform (see [the ServiceNow connector page](../connectors/cmdb/servicenow.md)).

## How to run it

The linker is exposed as a single DAB job, `app-repo-link`. It has no schedule — run it on-demand after the upstream connectors have populated their silver tables:

```bash
databricks bundle deploy --target dev
databricks bundle run app-repo-link --target dev
```

The job takes one parameter, `target_catalog`, which defaults to `${var.catalog}` (resolved at deploy time per the bundle target — `appsec_dev`, `appsec_staging`, or `appsec_prod`). Override at run time with `--params target_catalog=appsec_staging` if needed.

## Idempotency

The linker writes via `MERGE INTO silver.app_repo_mapping` keyed on `(application_id, repository_id, link_source)`. Re-runs:

- Update `linked_at` on rows whose key already exists.
- Insert rows whose key is new.
- Do **not** delete rows that have disappeared from the upstream join (e.g. a repository renamed away from a 5-digit code). Removal is reserved for a future reconciliation pass once the `cmdb_rel_ci` signal lands.

## Coexistence with other signals

`silver.app_repo_mapping` is keyed by `(application_id, repository_id, link_source)`, so multiple signals can produce the same `(application_id, repository_id)` pair without conflict:

| `link_source` | Source | Status (2026-04-26) |
|---|---|---|
| `name_match` | This linker — repo name carries 5-digit code | implemented |
| `cmdb_rel_ci` | ServiceNow `cmdb_rel_ci` graph | planned |
| `u_repository_id` | ServiceNow custom column on the business-app record | partially implemented (`normalise_app_repo_link` projects it; the silver write is not yet wired) |

A consolidated `silver.app_repo_mapping_resolved` view that collapses these signals with a precedence policy is planned but out of scope for this work.

## Troubleshooting

### Many `unknown_code` warnings in the job log

This means repositories carry 5-digit tokens that have no matching `app_code` in `silver.applications`. Check three places, in order:

1. **CMDB hygiene.** The `u_app_id` column may be unpopulated on real business-app records. Query:

   ```sql
   SELECT COUNT(*), COUNT(app_code), COUNT(*) - COUNT(app_code) AS missing_app_code
   FROM silver.applications;
   ```

   If `missing_app_code` is high, the fix is in ServiceNow — populate `u_app_id` on the relevant business-app records.

2. **Repository naming.** Some 5-digit tokens may be coincidental (a port number, a year, a JIRA ticket reference). The first-match-wins rule means the linker sees those first when they precede the real code. The fix is in the SCM — rename the repository so the application code is the only 5-digit token.

3. **Stale silver.applications.** The linker reads whatever is in `silver.applications` at job-run time. If the ServiceNow connector hasn't run since `u_app_id` was populated upstream, the linker won't see it yet. Re-run the ServiceNow connector job, then re-run the linker.

### Zero matches across the board

Most likely cause: `silver.applications` is empty (the ServiceNow connector hasn't been deployed and run yet, or its silver write isn't wired). Confirm with `SELECT COUNT(*) FROM silver.applications`. The linker correctly returns zero rows in this case — there is no error to fix on the linker side.

### `MERGE INTO` failing with column-not-found

The `link_source` column was added by [src/platform/sql/silver_tables.sql](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql) via `ALTER TABLE ADD COLUMNS IF NOT EXISTS`. If `MERGE` reports the column missing, the platform-bootstrap job hasn't been re-run since the column was added. Run:

```bash
databricks bundle run platform-bootstrap --target dev
```

then re-run `app-repo-link`.

## Reference

- Implementation: [`src/platform/app_repo_link.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/app_repo_link.py)
- Notebook entry: [`src/platform/app_repo_link_entry.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/app_repo_link_entry.py)
- DAB job: [`src/platform/resources/app_repo_link_job.yml`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/resources/app_repo_link_job.yml)
- Tests: [`src/platform/tests/test_app_repo_link.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/tests/test_app_repo_link.py)
- REQ catalog: [REQ catalog](reference/catalog.md)
