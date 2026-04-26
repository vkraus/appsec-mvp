# Gold datasets

Six artefacts live under the `gold` UC schema: five materialised Delta
tables and one SQL view. All six are emitted by the `analytics` job
(`src/analytics/resources/job.yml`) as six parallel notebook tasks on a
shared cluster, refreshed daily at 05:00 UTC.

Suppression rules from `silver.suppression_rules` are applied at
aggregation time inside each Gold notebook (see
[Suppression rules](suppression-rules.md)). The `gold.coverage_matrix`
table is the deliberate exception — coverage tracks whether tools ran,
not whether their findings are visible, so suppression must not affect
it.

The full canonical Silver schema that these tables read from is
documented in [Canonical mapping](../platform/reference/canonical-mapping.md).

## `gold.app_risk_posture_daily`

**Question it answers.** "How many open and closed findings sit on each
business application, broken down by severity, as of today?" Used by the
SOC dashboard and as the source of the `gold_online.app_risk_posture`
Online Table that backs the security-score endpoint.

**Schema.**

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `snapshot_date` | DATE | no | The day the snapshot was computed (UTC). |
| `application_id` | STRING | yes | Canonical app id. `__UNMAPPED__` when the finding's `repository_id` is not in `silver.app_repo_mapping`. |
| `severity_canonical` | STRING | yes | One of `critical`, `high`, `medium`, `low`, `info`. |
| `open_count` | INT | no | Findings with `status_canonical = 'open'`. |
| `closed_count` | INT | no | Findings with `status_canonical IN ('resolved', 'wontfix', 'false_positive')`. |

**Refresh cadence.** Daily 05:00 UTC via `analytics-job.yml`. Each run
overwrites the table; the snapshot grain is the day of the run.

**Source Silver tables.** `silver.findings`, `silver.app_repo_mapping`.

**Suppression.** Yes. Applied post-join with `silver.app_repo_mapping`
so rules scoped to `application_id` resolve correctly.

**Example SQL.**

Spot-check a single application:

```sql
SELECT severity_canonical, open_count, closed_count
FROM appsec_dev.gold.app_risk_posture_daily
WHERE application_id = 'APP-001'
  AND snapshot_date = current_date()
ORDER BY array_position(
    array('critical','high','medium','low','info'),
    severity_canonical
);
```

Top 10 apps by critical-plus-high open findings (dashboard widget):

```sql
SELECT
  application_id,
  sum(CASE WHEN severity_canonical IN ('critical','high') THEN open_count ELSE 0 END) AS open_critical_high
FROM appsec_dev.gold.app_risk_posture_daily
WHERE snapshot_date = current_date()
  AND application_id <> '__UNMAPPED__'
GROUP BY application_id
ORDER BY open_critical_high DESC
LIMIT 10;
```

## `gold.mttr_by_source_severity_weekly`

**Question it answers.** "For each tool source and severity, what is the
median and 90th-percentile time-to-remediate, week over week?" Used by
the engineering-leadership scorecard to track program effectiveness.

**Schema.**

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `iso_year` | INT | no | ISO-8601 year of the resolution timestamp. |
| `iso_week` | INT | no | ISO-8601 week of the resolution timestamp. |
| `tool_source` | STRING | no | Source connector (`semgrep`, `sonarqube`, …). |
| `severity_canonical` | STRING | no | One of `critical`, `high`, `medium`, `low`, `info`. |
| `mttr_median_hours` | DOUBLE | no | Median MTTR within the bucket, in hours. |
| `mttr_p90_hours` | DOUBLE | no | 90th-percentile MTTR within the bucket, in hours. |
| `sample_size` | INT | no | Number of resolved findings in the bucket. |

**Refresh cadence.** Daily 05:00 UTC. The table is overwritten; the
weekly grain is in the data, not the refresh frequency. Late-arriving
resolutions update the bucket they belong to on the next daily run.

**Source Silver tables.** `silver.findings` (uses `first_seen_at`,
`last_seen_at`, `status_canonical`).

**Suppression.** Yes. Rules scoped to `application_id` are silently
skipped because the findings DataFrame is not joined with
`silver.app_repo_mapping` for this aggregation.

**Example SQL.**

Latest week's median MTTR per tool, critical findings only:

```sql
SELECT tool_source, mttr_median_hours, sample_size
FROM appsec_dev.gold.mttr_by_source_severity_weekly
WHERE severity_canonical = 'critical'
  AND (iso_year, iso_week) = (
    SELECT max(struct(iso_year, iso_week))
    FROM appsec_dev.gold.mttr_by_source_severity_weekly
  )
ORDER BY mttr_median_hours;
```

Trend over the last 12 weeks (dashboard widget):

```sql
SELECT
  iso_year * 100 + iso_week AS yyyyww,
  tool_source,
  mttr_median_hours
FROM appsec_dev.gold.mttr_by_source_severity_weekly
WHERE severity_canonical IN ('critical','high')
  AND make_date(iso_year, 1, 1) + ((iso_week - 1) * 7) >= current_date() - INTERVAL 84 DAYS
ORDER BY yyyyww, tool_source;
```

## `gold.coverage_matrix`

**Question it answers.** "Which tool categories have actually run against
each repository, and is the most recent run stale?" The operational
counterpart to risk posture — coverage is about whether the tooling
fired at all, regardless of whether it produced findings.

**Schema.**

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `repository_id` | STRING | no | Canonical repository id from `silver.repositories`. |
| `category` | STRING | no | One of `sast`, `sca`, `secrets`, `scm`. |
| `last_scan_at` | TIMESTAMP | yes | Latest `last_seen_at` for any finding from that category against the repo. NULL means the category has never run. |
| `is_stale` | BOOLEAN | no | True if `last_scan_at` is NULL or older than `staleness_threshold_days`. |
| `staleness_threshold_days` | INT | no | The threshold the row was evaluated against (default 30). |

**Refresh cadence.** Daily 05:00 UTC.

**Source Silver tables.** `silver.repositories`, `silver.findings`.

**Suppression.** No — explicitly. Coverage tracks tool runs, not finding
visibility. A muted finding is still evidence that the tool ran. The
`apply_suppression_rules` helper is intentionally not invoked in this
notebook.

**Example SQL.**

Find repositories with stale or missing SAST coverage:

```sql
SELECT repository_id, last_scan_at
FROM appsec_dev.gold.coverage_matrix
WHERE category = 'sast'
  AND is_stale = true
ORDER BY repository_id;
```

Coverage matrix overview (dashboard widget — pivoted view):

```sql
SELECT
  repository_id,
  max(CASE WHEN category = 'sast' THEN NOT is_stale END) AS sast_fresh,
  max(CASE WHEN category = 'sca' THEN NOT is_stale END) AS sca_fresh,
  max(CASE WHEN category = 'secrets' THEN NOT is_stale END) AS secrets_fresh,
  max(CASE WHEN category = 'scm' THEN NOT is_stale END) AS scm_fresh
FROM appsec_dev.gold.coverage_matrix
GROUP BY repository_id
ORDER BY repository_id;
```

## `gold.dedup_link_overlap`

**Question it answers.** "How often do two independent tools find the
same issue, broken down by category?" Validates that the framework's
in-connector deduplication is working as intended and surfaces
candidate consolidations of overlapping tooling.

**Schema.**

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `tool_source_a` | STRING | no | Alphabetically-first tool of the unordered pair. |
| `tool_source_b` | STRING | no | Alphabetically-second tool of the unordered pair. |
| `category` | STRING | no | One of `sast`, `sca`, `secrets`, `dast`. |
| `linked_pair_count` | INT | no | Distinct dedup-tuple values where both tools agreed. |

**Refresh cadence.** Daily 05:00 UTC.

**Source Silver tables.** `silver.findings`. Per-category dedup tuple
matches `src.platform.silver.dedup_findings` — see
[Canonical mapping](../platform/reference/canonical-mapping.md).

**Suppression.** Yes. Applied before the self-join so muted findings
cannot inflate overlap counts.

**Example SQL.**

Largest cross-tool overlaps in SAST:

```sql
SELECT tool_source_a, tool_source_b, linked_pair_count
FROM appsec_dev.gold.dedup_link_overlap
WHERE category = 'sast'
ORDER BY linked_pair_count DESC
LIMIT 5;
```

Overlap by category (hero KPI for the dedup widget):

```sql
SELECT category, sum(linked_pair_count) AS total_overlapping_pairs
FROM appsec_dev.gold.dedup_link_overlap
GROUP BY category
ORDER BY total_overlapping_pairs DESC;
```

## `gold.cwe_owasp_heatmap`

**Question it answers.** "Which OWASP Top 10:2021 categories dominate
each application's open-finding surface, and which CWEs drive each
category?" Used by AppSec engineers to prioritise training and program
investment.

**Schema.**

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `application_id` | STRING | yes | Canonical app id. `__UNMAPPED__` for findings whose repo is not in `silver.app_repo_mapping`. |
| `owasp_category` | STRING | no | One of `A01`–`A10` (OWASP Top 10:2021) or `unmapped` for CWEs not in the OWASP primary mapping. |
| `cwe_id` | STRING | yes | Canonical `CWE-<n>` form, or NULL when the source emitted no CWE. |
| `finding_count` | INT | no | Open findings with the given (application, OWASP category, CWE). |

**Refresh cadence.** Daily 05:00 UTC.

**Source Silver tables.** `silver.findings`, `silver.app_repo_mapping`.

**Suppression.** Yes. Applied post-join with `silver.app_repo_mapping`.
Filtered to `status_canonical = 'open'` so closed findings do not
distort the heatmap.

**Example SQL.**

OWASP profile of a specific application:

```sql
SELECT owasp_category, sum(finding_count) AS findings
FROM appsec_dev.gold.cwe_owasp_heatmap
WHERE application_id = 'APP-001'
  AND owasp_category <> 'unmapped'
GROUP BY owasp_category
ORDER BY owasp_category;
```

Top CWEs program-wide (dashboard widget):

```sql
SELECT cwe_id, owasp_category, sum(finding_count) AS findings
FROM appsec_dev.gold.cwe_owasp_heatmap
WHERE cwe_id IS NOT NULL
  AND application_id <> '__UNMAPPED__'
GROUP BY cwe_id, owasp_category
ORDER BY findings DESC
LIMIT 20;
```

## `gold.app_repo_findings_open` (view)

**Question it answers.** "For a given repository (and optionally a given
PR), what are the open findings the pre-merge gate needs to consider?"
This is the source-of-truth shape that backs the
`silver_online.app_repo_findings` Online Table. Materialising it as a
view rather than a Delta table avoids re-projecting the same Silver
columns for every batch refresh — the Online Table sync handles the
materialisation row-side.

**Definition.**

```sql
CREATE OR REPLACE VIEW gold.app_repo_findings_open AS
SELECT
  f.finding_id,
  f.repository_id,
  m.application_id,
  f.tool_source,
  f.category,
  f.severity_canonical,
  f.cwe_id,
  f.cve_id,
  f.rule_id_native,
  f.file_path,
  f.start_line,
  f.url,
  f.first_seen_at,
  f.last_seen_at
FROM silver.findings f
JOIN silver.app_repo_mapping m
  ON f.repository_id = m.repository_id
WHERE f.status_canonical = 'open'
  AND f.repository_id IS NOT NULL;
```

**Refresh cadence.** Daily 05:00 UTC (the view's CREATE OR REPLACE runs
in the analytics job for idempotency, even though a view does not store
data; downstream Online Table sync continues against the same view
definition). The Online Table replica that consumes this view picks up
new rows continuously with ~5-min lag.

**Source Silver tables.** `silver.findings`, `silver.app_repo_mapping`.

**Suppression.** Not at view definition time — this view is the OLTP
read path for the pre-merge gate, where policy decisions happen at the
App layer. The App applies its own policy threshold; suppression rules
scoped to a finding still appear in the view but the App can be
extended to consult `silver.suppression_rules` if a future operator
needs gate-time muting. For OLAP rollups, suppression is applied in the
five materialised tables above.

**Example SQL.**

All open findings for a repo (smoke test against the underlying view):

```sql
SELECT finding_id, severity_canonical, file_path, start_line
FROM appsec_dev.gold.app_repo_findings_open
WHERE repository_id = 'myorg/web-app'
ORDER BY severity_canonical, file_path;
```

Pre-merge-gate-style lookup (the App does this through Online Tables for
sub-50 ms latency; the view lookup is the ~200 ms fallback):

```sql
SELECT finding_id, severity_canonical
FROM appsec_dev.gold.app_repo_findings_open
WHERE finding_id IN ('finding-123', 'finding-456', 'finding-789');
```
