# Project layout

The platform repository keeps connector modules, analytics computations, and configuration separate so each surface is discoverable and editable without cross-cutting reads.

## Top-level structure

```
repo/
├── databricks.yml                  # bundle root: targets, variables, include glob
├── conftest.py                     # global pytest configuration
├── src/
│   ├── platform/                   # framework primitives (HTTP, pagination, HWM,
│   │   │                           # severity/status normalization, dedup)
│   │   ├── resources/              # platform.yml (catalog + silver schema),
│   │   │                           # bootstrap-job.yml (one-off silver_tables.sql)
│   │   ├── sql/                    # silver_tables.sql
│   │   └── tests/                  # platform-level framework tests
│   ├── connectors/
│   │   └── github/                 # one module per source
│   │       ├── ingest.py           # implements ingest(run_id, state) -> batch
│   │       ├── transform.py        # implements transform(bronze_df) -> silver_df
│   │       ├── mapping.yml         # bronze-to-silver column expressions
│   │       ├── config.yml          # endpoints, pagination, HWM column
│   │       ├── severity.yml        # native-severity → canonical-severity lookup
│   │       ├── status.yml          # native-status → canonical-status lookup
│   │       ├── resources/          # per-connector DAB fragments
│   │       │   ├── schemas.yml     # bronze_<source>, silver_<source> UC schemas
│   │       │   ├── job.yml         # two-task ingest → transform job
│   │       │   ├── volumes.yml     # (scanners only) external volumes for artifacts
│   │       │   ├── connection.yml  # (Lakeflow connectors only) UC connection
│   │       │   └── pipeline.yml    # (Lakeflow connectors only) ingestion pipeline
│   │       └── tests/              # co-located tests + fixtures for this connector
│   │           ├── test_ingest.py
│   │           ├── test_transform.py
│   │           └── fixtures/       # per-endpoint JSON fixtures
│   └── analytics/                  # gold-layer scaffolding (future work)
│       ├── resources/              # schemas.yml (gold), job.yml
│       └── sql/
```

`databricks.yml` includes `src/**/resources/*.yml`, so any new component that follows the same `<component>/resources/*.yml` shape is picked up automatically; there is no top-level `resources/` directory.

## Per-connector module layout

Every connector module under `src/connectors/{source}/` carries the same six artifacts plus a `tests/` subfolder, so adding a source is a fill-in-the-blanks exercise:

- **`ingest.py`** — implements the connector contract against the source API. Takes `(run_id, state)`, returns a batch of bronze records.
- **`transform.py`** — maps bronze records to the target silver entity or finding table.
- **`mapping.yml`** — declares bronze-to-silver column expressions and references severity and status lookups.
- **`config.yml`** — records source-specific parameters: base URL and endpoints, pagination strategy, high-water-mark column, and target bronze table.
- **`severity.yml`** — native-severity → canonical-severity lookup, tunable without touching pipeline code.
- **`status.yml`** — native-status → canonical-status lookup, same shape as severity.yml.

The co-located `tests/` subfolder carries the fixtures and assertions for the connector — running `pytest src/connectors/{source}/tests/` exercises that connector in isolation.

## Configuration separation

Severity and status lookups live alongside each connector at `src/connectors/{source}/severity.yml` and `src/connectors/{source}/status.yml` so tuning them does not require touching pipeline code. Secrets (API tokens, service account credentials) are stored in the platform's secret scope and referenced by name in pipeline code; they never appear in source files or bundle configuration.
