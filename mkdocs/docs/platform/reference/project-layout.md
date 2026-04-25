# Project layout

The platform repository keeps connector modules, analytics computations, and configuration separate so each surface is discoverable and editable without cross-cutting reads.

## Top-level structure

```
repo/
├── databricks.yml              # bundle root: targets, jobs, pipelines
├── resources/                  # per-job and per-pipeline bundle fragments
├── src/
│   ├── connectors/
│   │   └── github/             # one module per source
│   │       ├── ingest.py       # implements ingest(run_id, state) -> batch
│   │       ├── transform.py    # implements transform(bronze_df) -> silver_df
│   │       ├── mapping.yml     # bronze-to-silver column expressions
│   │       ├── config.yml      # endpoints, pagination, HWM column
│   │       ├── severity.yml    # native-severity → canonical-severity lookup
│   │       └── status.yml      # native-status → canonical-status lookup
│   ├── analytics/              # silver-to-gold computations, grouped by gold table
│   └── common/                 # shared auth, pagination, normalization helpers
└── tests/
    └── connectors/
        └── github/
            ├── test_ingest.py
            ├── test_transform.py
            └── fixtures/       # per-endpoint JSON fixtures
```

## Per-connector module layout

Every connector module under `src/connectors/{source}/` carries the same four artifacts, so adding a source is a fill-in-the-blanks exercise:

- **`ingest.py`** — implements the connector contract against the source API. Takes `(run_id, state)`, returns a batch of bronze records.
- **`transform.py`** — maps bronze records to the target silver entity or finding table.
- **`mapping.yml`** — declares bronze-to-silver column expressions and references severity and status lookups.
- **`config.yml`** — records source-specific parameters: base URL and endpoints, pagination strategy, high-water-mark column, and target bronze table.

A co-located `src/connectors/{source}/tests/` subfolder carries the fixtures and assertions for the connector.

## Configuration separation

Severity and status lookups live alongside each connector at `src/connectors/{source}/severity.yml` and `src/connectors/{source}/status.yml` so tuning them does not require touching pipeline code. Secrets (API tokens, service account credentials) are stored in the platform's secret scope and referenced by name in pipeline code; they never appear in source files or bundle configuration.
