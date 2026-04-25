---
name: generate-connector
description: Use after analyze-source to generate a connector module — config.yml, ingest.py, transform.py, mapping.yml, severity/status lookups, bundle fragment, and pytest suite — under src/connectors/{source}/, conforming to the framework's connector contract for the source's AppSec category (cmdb, scm, sast, sca, secrets, dast, or waf).
---

# generate-connector

## Overview

This skill emits the eight-file connector module for a single source given a reviewed per-connector page. Category-specific facts that drive code emission (target Silver tables, dedup-key tuple, ingestion-tooling preference overrides, mapping.yml shape, applicable REQ-IDs to bind tests against, category quirks) live in `references/<category>.md` and MUST be read for the source's category before any file is written.

## Inputs

- **Source name** — determines the module path `src/connectors/{source}/` and the lookup filenames `config/severity/{source}.yml`, `config/status/{source}.yml`.
- **Per-connector page path** — `mkdocs/docs/connectors/{category}/{slug}.md` produced by `analyze-source`.
- **AppSec category** — one of `cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, `waf`. Determines which `references/<category>.md` to load.

Preconditions:

- The per-connector page exists at `mkdocs/docs/connectors/{category}/{slug}.md` and has been reviewed for completeness (Reference section populated; Generation log row 1 filled by `analyze-source`).
- The framework's shared utilities at `src/common/` are intact (HTTP client, pagination, HWM state, severity/status normalization, dedup helpers).

## Output

A connector module composed of exactly the following eight files (per the baseline procedure at `mkdocs/docs/connectors/sast/skills.md` § "## generate-connector"):

- `src/connectors/{source}/config.yml` — base URL, endpoints, pagination, HWM column (or scan-id / commit-SHA / artefact-prefix per category override), target Bronze table, credential reference.
- `src/connectors/{source}/ingest.py` — implements `ingest(run_id, state) -> batch` per the connector contract in `mkdocs/docs/platform/reference/catalog.md`.
- `src/connectors/{source}/transform.py` — implements `transform(bronze_df) -> silver_df` per the normalization rules in `mkdocs/docs/platform/reference/canonical-mapping.md`.
- `src/connectors/{source}/mapping.yml` — declarative Bronze-to-Silver column expressions referencing the severity and status lookups by file path.
- `config/severity/{source}.yml` — per-source severity lookup. For categories where severity is N/A or conventional, see `references/<category>.md`.
- `config/status/{source}.yml` — per-source status lookup. For categories where status is N/A, see `references/<category>.md`.
- `resources/{source}-job.yml` — canonical two-task Lakeflow job bundle fragment per the template at `mkdocs/docs/platform/reference/connector-job-template.md`.
- `tests/connectors/{source}/` — pytest suite (`test_ingest.py`, `test_transform.py`, `fixtures/{endpoint}_{scenario}.json`) with one test function per applicable REQ-ID, each marked with `@pytest.mark.requirement("REQ-...")`.

## Procedure

1. **Read `references/<category>.md` for category-specific facts** — target Silver tables, dedup key tuple to encode in transform/dedup logic, ingestion-tooling preference overrides (CLI-artefact exceptions for SAST CLI, secrets CLI, DAST CLI), `mapping.yml` shape for this category (entity-only, finding-only, dual entity+finding for SCM, or event-shape for WAF), applicable REQ-IDs to bind tests against, and category quirks affecting code emission.
2. Read the per-connector page and extract the seven API facts captured by `analyze-source`: authentication mechanism, pagination style, incremental hook (HWM column / webhook / scan-id / artefact prefix / full reload), endpoints, consumed-field schema, severity vocabulary, status vocabulary, quirks.
3. Emit `src/connectors/{source}/config.yml` with the extracted parameters. Use the HWM shape per the category reference (record-level `updated_at` for SAST/SCA/CMDB/SCM; scan-id for DAST server; commit-SHA or scan-start timestamp for full-reload categories — secrets, CLI-artefact paths).
4. Select the ingestion tooling per the preference order in `references/<category>.md` (typical: Lakeflow Connect → Databricks SDK → dlt; CLI-artefact path is the documented exception for SAST CLI, secrets CLI, and DAST CLI). Emit `src/connectors/{source}/ingest.py` against the chosen tool.
5. Emit `src/connectors/{source}/mapping.yml` with the shape required by the category reference: entity-only block (CMDB), finding-only block (SAST / SCA / secrets / DAST), dual entity+finding blocks (SCM), or event-shape block targeting `silver.waf_events` (WAF). Reference the severity and status lookup files by path.
6. Emit `config/severity/{source}.yml` and `config/status/{source}.yml`. Cover every documented source value with a configurable default (`medium` for severity unless the category reference overrides) and a comment flagging the data-quality warning path. For CMDB, both files exist but contain `# N/A — CMDB sources emit no findings`. For secrets, severity is hard-coded `high` in `mapping.yml`; the lookup file exists with the comment `# default high; per-deployment override permitted for low-entropy detector classes`, and the status file is N/A. For WAF, status is N/A; severity is action-keyed (derived from the `action` field plus rule-group category).
7. Emit `src/connectors/{source}/transform.py` applying the mapping plus the normalization rules from `mkdocs/docs/platform/reference/canonical-mapping.md`. For categories with a finding shape, encode the dedup-key tuple given in `references/<category>.md` literally (it drives `dedup_links` linkage in the transform). For DAST, emit the target → `silver.deployments` join. For SCA, emit the CVE-correlation step.
8. Emit the bundle fragment at `resources/{source}-job.yml` using the canonical two-task shape from `mkdocs/docs/platform/reference/connector-job-template.md`, substituting the source name.
9. Emit the test suite at `tests/connectors/{source}/`: one test function per REQ-ID applicable to the category (per `references/<category>.md`), each marked with `@pytest.mark.requirement("REQ-...")`. Fixtures named `{endpoint}_{scenario}.json` under `tests/connectors/{source}/fixtures/`. Tests cover the framework contract from `src/common/`; pure-Python only — no local `SparkSession`.
10. Record the invocation: list the generated file paths, run `git rev-parse --short HEAD` for the skill repo ref, and compute `sha256sum mkdocs/docs/connectors/{category}/{slug}.md` for the page hash that pins this generation to a specific page revision.
11. Update the connector page's Generation log section: fill in row 2 (`generate-connector`) with the run date, inputs (page hash via `sha256sum mkdocs/docs/connectors/{category}/{slug}.md`), outputs (the eight-file list above), and the skill repo ref via `git rev-parse --short HEAD`. Mark row 3 unchanged (`(pending)`) so `validate-implementation` has a target to overwrite.

## Invariants

- No file is written outside `src/connectors/{source}/`, `tests/connectors/{source}/`, `config/severity/{source}.yml`, `config/status/{source}.yml`, or `resources/{source}-job.yml`. The connector generation is self-contained.
- Both `config/severity/{source}.yml` and `config/status/{source}.yml` exist for every connector — even for categories where one or both are N/A. The N/A files carry an explanatory comment per `references/<category>.md`.
- All imports in `ingest.py` and `transform.py` reference only functions that already exist in `src/common/`. New shared helpers are NOT introduced by this skill; if a missing helper is identified, halt and report the gap rather than adding it inline.
- Every REQ-ID applicable to the category (per `references/<category>.md`) has at least one bound test function carrying `@pytest.mark.requirement("REQ-...")`. REQ-IDs marked N/A for the category are not bound.
- The Generation log section of `mkdocs/docs/connectors/{category}/{slug}.md` has row 2 filled and row 3 still marked `(pending)` after this skill runs. Row 1 (set by `analyze-source`) is not modified.
- Output is code, configuration, and test fixtures only — plus the single-line Generation log row update on the connector page. No new Markdown files are created.
- Shared files (`databricks.yml`, `mkdocs/mkdocs.yml`, `pyproject.toml`) are NEVER touched by this skill. Required shared-file additions — for example, including a new `resources/<source>-job.yml` in `databricks.yml` — are reported in the run output for the controller to wire up sequentially in a separate consolidation step.

Category-specific invariants (target Silver tables, dedup-key tuple, ingestion-tooling override, severity / status lookup shape, mapping.yml shape, applicable REQ-IDs, category quirks affecting code emission) live in `references/<category>.md`. Read the file matching the input category before emitting any file.

## Generation log row template

Append exactly one row to the connector page's Generation log table, overwriting the `(pending)` placeholder for `generate-connector`. Use this row shape verbatim, replacing the bracketed placeholders:

```
| Module generation | generate-connector ({category}) | page hash={sha256_of_page} | src/connectors/{source}/, tests/connectors/{source}/, config/severity/{source}.yml, config/status/{source}.yml | {YYYY-MM-DD} | {git_short_sha} ({branch}) |
```

- `{category}` — the AppSec category input (`cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, or `waf`).
- `{sha256_of_page}` — output of `sha256sum mkdocs/docs/connectors/{category}/{slug}.md` (the full hex digest pins this generation to the page revision read at step 2).
- `{source}` — the source name input.
- `{YYYY-MM-DD}` — the run date in ISO format.
- `{git_short_sha}` — output of `git rev-parse --short HEAD` on the skill's repo.
- `{branch}` — output of `git rev-parse --abbrev-ref HEAD`.

Row 3 (`validate-implementation`) MUST remain marked `(pending)` so the next skill has a target to overwrite.
