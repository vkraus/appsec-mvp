# Evidence

Three scenarios that exercise the end-to-end pipeline. Completing all three is your "you're done" signal.

## Evidence 1 — Cross-tool deduplication

**Claim:** two independent SAST tools (SonarQube + Semgrep) pointed at the same repository produce overlapping findings that the pipeline deduplicates.

### Setup

You already have the SAST seed repos (`seed-python-a`, `seed-javascript-b`) provisioned by Terraform, with four deliberately-planted vulnerabilities across them (CWE-89, CWE-78, CWE-79, CWE-22). Run the SonarQube scanner workflow in the [SonarQube connector page](../connectors/sast/sonarqube.md#first-run), then wait for the next scheduled Semgrep CronJob (or trigger it manually). Run the ingest jobs for both connectors.

### Query

```sql
WITH raw AS (
  SELECT repository_id, file_path, start_line, cwe_id, tool_source, trigger_context
    FROM appsec_dev.silver.findings
    WHERE tool_source IN ('sonarqube', 'semgrep')
      AND category = 'sast'
)
SELECT
  count(*) FILTER (WHERE tool_source='sonarqube') AS sonarqube_count,
  count(*) FILTER (WHERE tool_source='semgrep')   AS semgrep_count,
  count(DISTINCT (repository_id, file_path, start_line, cwe_id)) AS deduped_count,
  (count(*) - count(DISTINCT (repository_id, file_path, start_line, cwe_id))) AS overlap_count
FROM raw;
```

### Expected

- `sonarqube_count ≥ 4` (four planted defects).
- `semgrep_count ≥ 4` (same four).
- `overlap_count ≥ 4` — Sonar and Semgrep both find the same defects at the same locations.
- `deduped_count ≤ sonarqube_count + semgrep_count - overlap_count`.

## Evidence 2 — Business-application rollup

**Claim:** the ServiceNow→GitHub linkage joins findings to business applications, answering "which business apps carry critical unresolved SAST findings?".

### Query

```sql
SELECT
  app.name AS business_app,
  count(DISTINCT f.finding_id) AS critical_findings
FROM appsec_dev.silver_servicenow.applications app
JOIN appsec_dev.silver.app_repo ar USING (app_id)
JOIN appsec_dev.silver_github.repositories r ON r.repository_id = ar.repository_id
JOIN appsec_dev.silver.findings f ON f.repository_id = r.repository_id
WHERE f.severity_canonical IN ('critical', 'high')
  AND f.status_canonical = 'open'
  AND f.category = 'sast'
GROUP BY app.name
ORDER BY critical_findings DESC;
```

### Expected

Two rows: "AppSec Demo Frontend" and "AppSec Demo Backend", each with a non-zero finding count that matches the planted defects per linked repo.

## Evidence 3 — Finding-shape variety

**Claim:** URL-based DAST findings (`file_path IS NULL`) and code-based SAST findings coexist in the same table.

### Query

```sql
SELECT category,
       count(*)                                AS total,
       count(*) FILTER (WHERE file_path IS NOT NULL) AS code_located,
       count(*) FILTER (WHERE url IS NOT NULL)       AS url_located
FROM appsec_dev.silver.findings
GROUP BY category;
```

### Expected

- `category='sast'` row: `code_located = total`, `url_located = 0`.
- `category='dast'` row: `code_located = 0`,    `url_located = total`.

## Done

If all three expectations hold, you have reproduced the MVP.
