# Project layout

The platform repository keeps connector modules, analytics computations, and
configuration separate so each surface is discoverable and editable without
cross-cutting reads. Per the Databricks-centric redesign, every component
co-locates its source code, configs, tests, DAB resources, runtime
infrastructure, and secret-loading scripts under one folder, so adding a
source is a fill-in-the-blanks exercise.

## Top-level structure

```
repo/
├── databricks.yml                  # bundle root: targets, variables, include glob
├── conftest.py                     # global pytest configuration
├── pyproject.toml                  # python package definition
├── src/
│   ├── platform/                   # framework primitives + cross-cutting platform layer
│   │   ├── bronze.py               # HTTP client, pagination, HWM
│   │   ├── silver.py               # canonical mapping engine
│   │   ├── severity.py             # severity normalization
│   │   ├── status.py               # status normalization
│   │   ├── dedup.py                # cross-tool deduplication
│   │   ├── resources/              # platform.yml (catalog + silver schema),
│   │   │                           #   bootstrap-job.yml (one-off silver_tables.sql)
│   │   ├── scripts/                # bootstrap.sh — cross-cutting Databricks objects
│   │   ├── sql/                    # silver_tables.sql
│   │   └── tests/                  # platform-level framework tests
│   ├── connectors/
│   │   └── <source>/               # one module per source (github, servicenow, ...)
│   │       ├── ingest.py           # implements ingest(run_id, state) -> batch
│   │       ├── ingest_entry.py     # databricks notebook entry-point for ingest
│   │       ├── transform.py        # implements transform(bronze_df) -> silver_df
│   │       ├── transform_entry.py  # databricks notebook entry-point for transform
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
│   │       ├── scripts/            # load-secrets.sh — per-connector secret loader
│   │       ├── runtime/            # (optional) Terraform/Helm to stand up source system
│   │       ├── sql/                # (some connectors only) per-connector SQL views
│   │       └── tests/              # co-located tests + fixtures for this connector
│   │           ├── test_ingest.py
│   │           ├── test_transform.py
│   │           └── fixtures/       # per-endpoint JSON fixtures
│   └── analytics/                  # gold-layer scaffolding (future work)
│       ├── resources/              # schemas.yml (gold), job.yml
│       └── sql/                    # gold-layer SQL (placeholder until analytics lands)
├── examples/
│   └── end-to-end-demo/            # cross-scanner CI workflow + ordered apply recipe
└── mkdocs/                         # docs site (this site)
    ├── mkdocs.yml
    └── docs/
```

`databricks.yml` includes `src/platform/resources/*.yml`,
`src/connectors/*/resources/*.yml`, and `src/analytics/resources/*.yml`, so
any new component that follows the same `<component>/resources/*.yml` shape
is picked up automatically. There is no top-level `resources/` directory and
no top-level `infra/` directory — both are obsolete artifacts of earlier
revisions.

!!! note "Platform-name disambiguation"
    The folder `src/platform/` holds the **Python framework library**
    (HTTP client, pagination, severity/status normalization, dedup) plus
    cross-cutting Databricks resources. The phrase **"setup platform"** in
    the operator docs ([Setup platform](../index.md)) is a different sense
    of the word — it refers to the workspace-bootstrap operator phase, not
    to this Python module. Both senses appear throughout the docs.

## Per-connector module layout

Every connector module under `src/connectors/<source>/` is self-contained.
The mandatory artifacts:

- **`ingest.py` / `ingest_entry.py`** — implements the connector contract
  against the source API and the Databricks notebook entry-point.
- **`transform.py` / `transform_entry.py`** — maps bronze records to the
  target silver entity or finding table.
- **`mapping.yml`** — declarative bronze-to-silver column expressions,
  references severity and status lookups.
- **`config.yml`** — base URL, endpoints, pagination strategy, HWM column,
  target Bronze table.
- **`severity.yml`** — native-severity → canonical-severity lookup, tunable
  without touching pipeline code.
- **`status.yml`** — native-status → canonical-status lookup.
- **`resources/`** — DAB fragments registered automatically via the include
  glob. Schemas + a job for batch-style connectors; schemas + volumes for
  artifact-path scanners; schemas + connection + pipeline for Lakeflow
  Connect connectors (servicenow).
- **`scripts/load-secrets.sh`** — per-connector secret loader. Reads env
  vars documented on the connector's runbook page; writes only the keys
  that connector reads into the `mvp-connectors` scope.
- **`tests/`** — co-located tests and fixtures.

Optional artifacts (per connector):

- **`runtime/`** — Terraform / Kubernetes manifests that stand up the
  *source system* (e.g. SonarQube Helm release, Semgrep CronJob, ZAP
  daemon) on the operator's existing AWS account. Documented at
  `src/connectors/<source>/runtime/README.md`. Optional — operators with an
  existing source-system deployment skip the runtime entirely.
- **`sql/`** — per-connector SQL views (e.g. ServiceNow's CMDB-envelope
  view).

## Configuration separation

Severity and status lookups live alongside each connector at
`src/connectors/<source>/severity.yml` and `src/connectors/<source>/status.yml`
so tuning them does not require touching pipeline code. Secrets (API tokens,
service account credentials) are stored in the `mvp-connectors` Databricks
secret scope and referenced by name in pipeline code; they never appear in
source files or bundle configuration.

## Tests

Tests are co-located under each component's `tests/` subfolder:

- `src/platform/tests/` — framework-contract tests (HTTP client,
  pagination, HWM, severity, status, dedup).
- `src/connectors/<source>/tests/` — per-connector ingest + transform tests
  and fixtures.

Running `pytest src/connectors/<source>/tests/` exercises one connector in
isolation; running `pytest` from the repo root runs the full suite.

## DAB resource registration

The bundle root globs `src/**/resources/*.yml`, so adding a new connector or
extending an existing one is a matter of dropping new fragment YAML under
the appropriate `<component>/resources/` directory. The fragment is picked
up on the next `databricks bundle deploy`. There is no central registry to
update and no top-level orchestration to wire — each component declares its
own resources and the include glob does the rest.
