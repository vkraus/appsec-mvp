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
│   │       └── config.yml      # endpoints, pagination, HWM column
│   ├── analytics/              # silver-to-gold computations, grouped by gold table
│   └── common/                 # shared auth, pagination, normalization helpers
├── config/
│   ├── severity/               # per-source severity lookups (one YAML per source)
│   └── status/                 # per-source status lookups (one YAML per source)
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

A co-located `tests/connectors/{source}/` subfolder carries the fixtures and assertions for the connector.

## Configuration separation

Severity and status lookups live at `config/severity/{source}.yml` and `config/status/{source}.yml` so tuning them does not require touching pipeline code. Secrets (API tokens, service account credentials) are stored in the platform's secret scope and referenced by name in pipeline code; they never appear in source files or bundle configuration.
