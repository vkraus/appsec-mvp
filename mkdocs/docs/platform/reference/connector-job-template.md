# Connector job template

Every batch style connector instantiates the same Lakeflow Job structure. It is a two task DAG where an ingest task produces bronze records and a transform task consumes them to produce silver. The transform task declares a hard dependency on the ingest task, so a failed ingest short circuits the job without leaving silver partially refreshed. Lakeflow Connect connectors (e.g. ServiceNow) substitute a pipeline resource declared in `src/connectors/<source>/resources/pipeline.yml` for this job structure.

## Bundle fragment

`src/connectors/<source>/resources/job.yml`:

```yaml
resources:
  jobs:
    <source>-connector:
      name: <source>-connector
      parameters:
        - name: source_name
          default: "<source>"
        - name: target_catalog
          default: "${var.catalog}"
        - name: hwm_reset
          default: "false"
      schedule:
        quartz_cron_expression: "0 */15 * * * ?"
        timezone_id: "UTC"
      tasks:
        - task_key: ingest
          notebook_task:
            notebook_path: ../ingest_entry.py
          job_cluster_key: shared
          max_retries: 3
          min_retry_interval_millis: 2000
          retry_on_timeout: true
        - task_key: transform
          depends_on:
            - task_key: ingest
          notebook_task:
            notebook_path: ../transform_entry.py
          job_cluster_key: shared
          max_retries: 3
          min_retry_interval_millis: 2000
          retry_on_timeout: true
      job_clusters:
        - job_cluster_key: shared
          new_cluster:
            spark_version: "14.3.x-scala2.12"
            node_type_id: Standard_DS3_v2
            num_workers: 1
```

## Parameters

- **`source_name`**: connector source name, used throughout resource naming (e.g. `github`, `sonarqube`).
- **`target_catalog`**: Unity Catalog catalog name for the target environment. Each deployment target supplies its own catalog via `var.catalog` at the bundle root (e.g. `appsec_dev`, `appsec_prod`). Passed as `target_catalog` to both the ingest and transform tasks.
- **`hwm_reset`**: boolean flag (default `"false"`). Set to `"true"` to force high water mark re-initialisation on the next run. Intended for manual backfills only.
- **`quartz_cron_expression`**: the quartz cron expression driving scheduled runs. Source characteristics govern the cadence. High change sources (SCM platforms, active scanners) run every 15 minutes (github) or every 3 hours (sonarqube). Stable sources (CMDB application inventory) run daily.

## Retry configuration

Retry configuration is identical across connectors: three attempts (`max_retries: 3`), with `min_retry_interval_millis` set per the expected transient failure profile of the source (typically `2000`). This isolates transient source faults from pipeline faults. If retries exhaust, the task fails and downstream tasks in the same job do not execute.

## Credentials

Each new connector substitutes the source name and credential reference. Credentials come from the `mvp-connectors` Databricks secret scope, never from the bundle fragment itself. Secret loading for each connector happens via `src/connectors/<source>/scripts/load-secrets.sh`. See [Secrets bootstrap](../secrets-bootstrap.md).
