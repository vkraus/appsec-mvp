# Evidence

Three scenarios that exercise the end-to-end pipeline. Completing all three is your "you're done" signal.

## Evidence 1: Cross-tool deduplication

**Claim:** two independent SAST tools (SonarQube and Semgrep) pointed at the same repository produce overlapping findings that the pipeline deduplicates.

### Setup

You already have SAST target repos (`BenchmarkJava`, `BenchmarkPython`) referenced by the github runtime under `src/connectors/github/runtime/`. These are forks of the OWASP Benchmark projects, which carry a curated catalogue of planted defects (CWE-89, CWE-78, CWE-79, CWE-22 among others). Scan each repo with `sonar-scanner-cli` per the [SonarQube connector page, Run the job](../connectors/sast/sonarqube.md#run-the-job), then wait for the next semgrep CronJob (or trigger one manually per the [Semgrep connector page, Run the job](../connectors/sast/semgrep.md#run-the-job)). Run the ingest jobs for both connectors via `databricks bundle run sonarqube-connector` and `databricks bundle run semgrep-connector`.

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
- `overlap_count ≥ 4`. Sonar and Semgrep both find the same defects at the same locations.
- `deduped_count ≤ sonarqube_count + semgrep_count - overlap_count`.

## Evidence 2: Business application rollup

**Claim:** the linkage from ServiceNow to GitHub joins findings to business applications, answering "which business apps carry critical unresolved SAST findings?".

### Query

```sql
SELECT
  app.name AS business_app,
  count(DISTINCT f.finding_id) AS critical_findings
FROM appsec_dev.silver_servicenow.applications app
JOIN appsec_dev.silver.app_repo_mapping ar USING (application_id)
JOIN appsec_dev.silver.repositories r ON r.repository_id = ar.repository_id
JOIN appsec_dev.silver.findings f ON f.repository_id = r.repository_id
WHERE f.severity_canonical IN ('critical', 'high')
  AND f.status_canonical = 'open'
  AND f.category = 'sast'
GROUP BY app.name
ORDER BY critical_findings DESC;
```

### Expected

Two rows: "AppSec Demo Frontend" and "AppSec Demo Backend", each with a non-zero finding count that matches the planted defects in each linked repo.

## Evidence 3: Variety in finding structure

**Claim:** DAST findings located by URL (`file_path IS NULL`) and SAST findings located by code coexist in the same table.

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
