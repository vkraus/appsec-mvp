# Connector job template

Every connector instantiates the same Lakeflow Job shape: a two-task DAG where an ingest task produces bronze records and a transform task consumes them to produce silver. The transform task declares a hard dependency on the ingest task, so a failed ingest short-circuits the job without leaving silver partially refreshed.

## Bundle fragment

`src/connectors/<source>/resources/job.yml`:

```yaml
variables:
  source:
    description: Source name, used throughout resource naming (e.g. github, servicenow).
  target_catalog:
    description: Unity Catalog catalog name for the target environment (e.g. dev, prod).
  reset_hwm:
    description: When true, forces high-water-mark re-initialisation on the next run. Use for manual backfills only.
    default: "false"
  schedule_cron:
    description: Quartz cron expression driving scheduled runs.

resources:
  jobs:
    connector_${var.source}:
      name: connector_${var.source}
      tasks:
        - task_key: ingest
          notebook_task:
            notebook_path: ../ingest_entry.py
            base_parameters:
              target_catalog: ${var.target_catalog}
              reset_hwm: ${var.reset_hwm}
          job_cluster_key: ingest_cluster
          max_retries: 3
          min_retry_interval_millis: 30000
        - task_key: transform
          depends_on:
            - task_key: ingest
          notebook_task:
            notebook_path: ../transform_entry.py
            base_parameters:
              target_catalog: ${var.target_catalog}
          job_cluster_key: transform_cluster
          max_retries: 3
      schedule:
        quartz_cron_expression: ${var.schedule_cron}
```

## Parameters

- **`var.source`** — source name, used throughout resource naming (e.g. `github`, `servicenow`).
- **`var.target_catalog`**: Unity Catalog catalog name for the target environment. Each deployment target supplies its own catalog (e.g. `dev`, `prod`). Passed as `target_catalog` to both the ingest and transform tasks.
- **`var.reset_hwm`**: boolean flag (default `false`). Set to `true` to force high-water-mark re-initialisation on the next run. Intended for manual backfills only. Passed as `reset_hwm` to the ingest task.
- **`var.schedule_cron`** — the quartz cron expression driving scheduled runs. Source characteristics govern the cadence: high-change sources (SCM platforms, active scanners) run hourly; stable sources (CMDB application inventory) run daily.

## Retry configuration

Retry configuration is identical across connectors: three attempts, capped exponential backoff via `min_retry_interval_millis: 30000`. This isolates transient source faults from pipeline faults. If retries exhaust, the task fails and downstream tasks in the same job do not execute.

## Credentials

Each new connector substitutes the source name and credential reference; credentials come from the platform secret scope, never from the bundle fragment itself.
