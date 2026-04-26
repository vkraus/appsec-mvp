# Dashboards

A single Databricks SQL dashboard wires the [Gold tables](gold-datasets.md)
into a six-widget overview. The widgets cover the headline KPI plus one
view per Gold table. Each widget is a saved Databricks SQL query that
the operator imports once and adds to a dashboard.

## How to import

For each widget below:

1. Open Databricks SQL in the workspace.
2. New query → paste the SQL block → save it under the suggested name.
3. Open (or create) the **AppSec Overview** dashboard.
4. Add a visualisation, point it at the saved query, and pick the chart
   type called out in the widget's description.

All queries are parameterised on the catalog name. Replace `appsec_dev`
with the target catalog (`appsec_staging`, `appsec_prod`) when wiring
the dashboard for a non-dev environment.

## Widgets

### 1. Hero KPI — Open critical+high findings, today

Single-number tile. Shows the program's headline number: the count of
open findings at severity critical or high across all applications, as
of the latest snapshot. Use a Counter / Big Number visualisation.

Sources `gold.app_risk_posture_daily`.

```sql
-- saved as: appsec_kpi_open_critical_high_today
SELECT
  sum(open_count) AS open_critical_high
FROM appsec_dev.gold.app_risk_posture_daily
WHERE snapshot_date = current_date()
  AND severity_canonical IN ('critical', 'high')
  AND application_id <> '__UNMAPPED__';
```

### 2. Top apps by open critical+high findings

Bar chart showing the ten applications carrying the largest
critical-plus-high open finding load. Drives prioritisation
conversations.

Sources `gold.app_risk_posture_daily`.

```sql
-- saved as: appsec_top_apps_critical_high
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

### 3. MTTR trend — last 12 ISO weeks

Line chart per `tool_source`, x-axis = ISO week, y-axis = median MTTR
in hours, filtered to critical and high severities. Shows whether the
remediation cadence is improving over time.

Sources `gold.mttr_by_source_severity_weekly`.

```sql
-- saved as: appsec_mttr_trend_critical_high_12w
SELECT
  iso_year * 100 + iso_week AS yyyyww,
  tool_source,
  mttr_median_hours
FROM appsec_dev.gold.mttr_by_source_severity_weekly
WHERE severity_canonical IN ('critical', 'high')
  AND make_date(iso_year, 1, 1) + ((iso_week - 1) * 7) >= current_date() - INTERVAL 84 DAYS
ORDER BY yyyyww, tool_source;
```

### 4. Coverage heatmap — repo × tool category

Heatmap (or pivot table) showing per-repository freshness across the
four canonical tool categories (`sast`, `sca`, `secrets`, `scm`). A
cell value of `true` means the category is fresh (ran within
`staleness_threshold_days`); `false` means stale or never-ran.

Sources `gold.coverage_matrix`.

```sql
-- saved as: appsec_coverage_pivot
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

### 5. Cross-tool overlap by category

Stacked bar chart, one bar per category, segments coloured by
`(tool_source_a, tool_source_b)` pair. Validates that independent tools
in the same category are finding the same issues.

Sources `gold.dedup_link_overlap`.

```sql
-- saved as: appsec_dedup_overlap_by_category
SELECT
  category,
  concat(tool_source_a, ' x ', tool_source_b) AS tool_pair,
  linked_pair_count
FROM appsec_dev.gold.dedup_link_overlap
ORDER BY category, linked_pair_count DESC;
```

### 6. OWASP Top 10 surface — finding count by category

Bar chart, one bar per OWASP Top 10:2021 category, height = total open
finding count program-wide. Rolls up the heatmap to a program view.

Sources `gold.cwe_owasp_heatmap`.

```sql
-- saved as: appsec_owasp_program_view
SELECT
  owasp_category,
  sum(finding_count) AS findings
FROM appsec_dev.gold.cwe_owasp_heatmap
WHERE owasp_category <> 'unmapped'
  AND application_id <> '__UNMAPPED__'
GROUP BY owasp_category
ORDER BY owasp_category;
```

## Refresh

The dashboard reads the Gold tables, which are refreshed daily at
05:00 UTC by the analytics job. Set the dashboard's auto-refresh
interval to one hour or longer; sub-hourly polling against tables that
update once a day adds load without freshness benefit.

For real-time consumers (Slack bots, IDE plugins, the CI/CD pre-merge
gate), do **not** wire them to this dashboard. They should call the
[Databricks app](databricks-app.md) directly — the App reads the
[Online Tables](online-tables.md) replicas at sub-50 ms latency rather
than re-running a SQL warehouse query per call.
