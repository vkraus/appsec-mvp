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
- **operational.yml path** — `src/connectors/{source}/operational.yml`. The skill reads the `databricks_runtime:` sub-block. The schema for that sub-block is per-category and is defined in `references/<category>.md`. When the file is missing or any required-by-category field of `databricks_runtime:` is absent, the skill uses `AskUserQuestion` to gather missing values directly from the user, writes them to `operational.yml.databricks_runtime`, and proceeds. Halting is a fallback only when `AskUserQuestion` is unavailable (headless / unattended run, tool not loaded, or error result); the halt output then lists every missing field so the controller can gather them and re-run the skill once the file is complete.

Preconditions:

- The per-connector page exists at `mkdocs/docs/connectors/{category}/{slug}.md` and has been reviewed for completeness (Reference section populated; Implementation log row 1 filled by `analyze-source`, row 2 filled by `provision-source`).
- The framework's shared utilities at `src/common/` are intact (HTTP client, pagination, HWM state, severity/status normalization, dedup helpers).
- `src/connectors/{source}/operational.yml` is interactively bootstrapped or completed when missing fields exist. If the file is absent, the skill creates it with the two top-level keys `source_runtime:` and `databricks_runtime:` empty, then proceeds to gather each required `databricks_runtime:` field. For every field declared required in `references/<category>.md`, the skill issues an `AskUserQuestion` call. The question text is composed from the schema's "Field" + "Type" + a one-line description; the option list offers (a) the schema's recommended default — labelled "(Recommended)" — when one is declared, (b) "Use a placeholder for deploy-time fill" which writes the literal string `<your-{field-name}>`, and (c) the auto "Other" option for free-text input. Up to 4 questions are batched into a single `AskUserQuestion` call (the tool's per-call max). Each answer is written to `operational.yml.databricks_runtime.<field>`, preserving file structure and any comments adjacent to existing fields. The skill never overwrites an already-populated field and never touches the `source_runtime:` sub-block (that is `provision-source`'s territory). Halt-on-missing remains as a fallback when `AskUserQuestion` is unavailable (headless / unattended run, tool not loaded, or error result); the halt output lists every missing field so the controller can populate them and re-run.

## Output

A connector module composed of the eight-file core (per the baseline procedure at `mkdocs/docs/connectors/sast/skills.md` § "## generate-connector") PLUS the Databricks-side production-shape extras driven by `operational.yml.databricks_runtime` and the per-category templates in `references/<category>.md`.

**Eight-file core (always emitted):**

- `src/connectors/{source}/config.yml` — base URL, endpoints, pagination, HWM column (or scan-id / commit-SHA / artefact-prefix per category override), target Bronze table, credential reference.
- `src/connectors/{source}/ingest.py` — implements `ingest(run_id, state) -> batch` per the connector contract in `mkdocs/docs/platform/reference/catalog.md`.
- `src/connectors/{source}/transform.py` — implements `transform(bronze_df) -> silver_df` per the normalization rules in `mkdocs/docs/platform/reference/canonical-mapping.md`.
- `src/connectors/{source}/mapping.yml` — declarative Bronze-to-Silver column expressions referencing the severity and status lookups by file path.
- `config/severity/{source}.yml` — per-source severity lookup. For categories where severity is N/A or conventional, see `references/<category>.md`.
- `config/status/{source}.yml` — per-source status lookup. For categories where status is N/A, see `references/<category>.md`.
- `resources/{source}-job.yml` — canonical two-task Lakeflow job bundle fragment per the template at `mkdocs/docs/platform/reference/connector-job-template.md`.
- `tests/connectors/{source}/` — pytest suite (`test_ingest.py`, `test_transform.py`, `fixtures/{endpoint}_{scenario}.json`) with one test function per applicable REQ-ID, each marked with `@pytest.mark.requirement("REQ-...")`.

**Databricks-side production-shape (emitted in addition to the eight-file core, per category templates in `references/<category>.md`):**

- `src/connectors/{source}/scripts/load-secrets.sh` — secret-loading script derived from `config.yml`'s `*_secret` references and `operational.yml.databricks_runtime.secret_scope`. Writes each secret value into the named Databricks Secret scope via `databricks secrets put-secret`.
- `src/connectors/{source}/scripts/install.sh` — Databricks-side install phase: invokes `scripts/load-secrets.sh` and then runs `databricks bundle deploy --target dev`. Picks up `resources/*.yml` via the existing glob include in `databricks.yml`.
- `src/connectors/{source}/install.sh` — top-level orchestrator. Calls `runtime/install.sh` (provided by the upstream `provision-source` skill) FIRST, then `scripts/install.sh`. Supports a `--skip-runtime` flag for users who already have the source-side running.
- `src/connectors/{source}/ingest_entry.py` — Lakeflow job entry wrapper. Emitted only where the category requires a job-entry wrapper (per `references/<category>.md`).
- `src/connectors/{source}/transform_entry.py` — Lakeflow job entry wrapper for transform. Emitted only where the category requires it (per `references/<category>.md`).
- `src/connectors/{source}/sql/<envelope>.sql` — UC bronze schema bootstrap. Envelope name and column list derived from `config.yml`'s `bronze_table`. Emitted only where the category requires explicit DDL bootstrap (per `references/<category>.md`).
- `src/connectors/{source}/resources/{schemas,volumes,connection,pipeline}.yml` — additional DAB resource fragments. Per category; not all categories use all four (e.g. `secrets` uses `volumes.yml` for the UC Volume backing TruffleHog artefacts, `scm` may use `connection.yml` for webhook ingestion, etc.). The exact subset is specified in `references/<category>.md`.
- `mkdocs/docs/connectors/{category}/{slug}.md` §4 Setup, §Run-the-job, §Verify, §Troubleshooting — operator-facing runbook sections inserted into the connector page from per-category templates in `references/<category>.md`. The §1–§3 (Reference) and §Source provisioning sections are NOT modified — they belong to `analyze-source` and `provision-source` respectively.
- `mkdocs/docs/connectors/{category}/{slug}.md` Implementation log row 3 (`generate-connector`) — overwritten with the row template below. Note: row 3 of the new 4-row Implementation log schema (was row 2 of the old 3-row schema, before `provision-source` was inserted as row 2).

## Procedure

1. **Read `references/<category>.md` for category-specific facts** — target Silver tables, dedup key tuple to encode in transform/dedup logic, ingestion-tooling preference overrides (CLI-artefact exceptions for SAST CLI, secrets CLI, DAST CLI), `mapping.yml` shape for this category (entity-only, finding-only, dual entity+finding for SCM, or event-shape for WAF), applicable REQ-IDs to bind tests against, category quirks affecting code emission, the `operational.yml.databricks_runtime` schema (which fields are required for this category), and the per-category Databricks-side production-shape templates (`scripts/`, `*_entry.py`, `sql/`, `resources/{schemas,volumes,connection,pipeline}.yml`, page §4–§7).
2. **Read `src/connectors/{source}/operational.yml.databricks_runtime:` sub-block and interactively gather any missing required fields.** Parse the `databricks_runtime:` sub-block. Cross-check every field declared `required` in the category schema. If `operational.yml` is missing, create it with the two top-level keys (`source_runtime:`, `databricks_runtime:`) empty before continuing. For each missing required field, invoke `AskUserQuestion` — batching up to 4 questions per call (the tool's max). Each question presents the schema's declared default (when one exists) as a "(Recommended)" option, "Use a placeholder for deploy-time fill" (writes the literal string `<your-{field-name}>`) for fields the operator typically supplies at deploy time, and the auto "Other" option for free-text input. Write each answer back to `operational.yml.databricks_runtime.<field>`, preserving structure and adjacent comments; never touch the `source_runtime:` sub-block. Re-validate the `databricks_runtime:` sub-block; if any required field is still missing AND `AskUserQuestion` is unavailable (headless / unattended run, tool not loaded, or error result), halt and report the structured list of missing fields (`<field>: <description>` per row) without partial-emitting any file. Otherwise proceed to step 3.
3. Read the per-connector page and extract the seven API facts captured by `analyze-source`: authentication mechanism, pagination style, incremental hook (HWM column / webhook / scan-id / artefact prefix / full reload), endpoints, consumed-field schema, severity vocabulary, status vocabulary, quirks.
4. Emit `src/connectors/{source}/config.yml` with the extracted parameters. Use the HWM shape per the category reference (record-level `updated_at` for SAST/SCA/CMDB/SCM; scan-id for DAST server; commit-SHA or scan-start timestamp for full-reload categories — secrets, CLI-artefact paths). Wire `bronze_table` from `operational.yml.databricks_runtime.bronze_table`; wire any `*_secret` references to the per-source `secret_scope` value.
5. Select the ingestion tooling per the preference order in `references/<category>.md` (typical: Lakeflow Connect → Databricks SDK → dlt; CLI-artefact path is the documented exception for SAST CLI, secrets CLI, and DAST CLI). Emit `src/connectors/{source}/ingest.py` against the chosen tool.
6. Emit `src/connectors/{source}/mapping.yml` with the shape required by the category reference: entity-only block (CMDB), finding-only block (SAST / SCA / secrets / DAST), dual entity+finding blocks (SCM), or event-shape block targeting `silver.waf_events` (WAF). Reference the severity and status lookup files by path.
7. Emit `config/severity/{source}.yml` and `config/status/{source}.yml`. Cover every documented source value with a configurable default (`medium` for severity unless the category reference overrides) and a comment flagging the data-quality warning path. For CMDB, both files exist but contain `# N/A — CMDB sources emit no findings`. For secrets, severity is hard-coded `high` in `mapping.yml`; the lookup file exists with the comment `# default high; per-deployment override permitted for low-entropy detector classes`, and the status file is N/A. For WAF, status is N/A; severity is action-keyed (derived from the `action` field plus rule-group category).
8. Emit `src/connectors/{source}/transform.py` applying the mapping plus the normalization rules from `mkdocs/docs/platform/reference/canonical-mapping.md`. For categories with a finding shape, encode the dedup-key tuple given in `references/<category>.md` literally (it drives `dedup_links` linkage in the transform). For DAST, emit the target → `silver.deployments` join. For SCA, emit the CVE-correlation step.
9. Emit the bundle fragment at `resources/{source}-job.yml` using the canonical two-task shape from `mkdocs/docs/platform/reference/connector-job-template.md`, substituting the source name and interpolating `cron_schedule` / `uc_catalog` from `operational.yml.databricks_runtime`.
10. Emit the test suite at `tests/connectors/{source}/`: one test function per REQ-ID applicable to the category (per `references/<category>.md`), each marked with `@pytest.mark.requirement("REQ-...")`. Fixtures named `{endpoint}_{scenario}.json` under `tests/connectors/{source}/fixtures/`. Tests cover the framework contract from `src/common/`; pure-Python only — no local `SparkSession`.
11. **Emit `src/connectors/{source}/scripts/load-secrets.sh`** from the category template. Iterate over every `*_secret` reference declared in `config.yml` and emit one `databricks secrets put-secret <scope> <key>` invocation per secret, where `<scope>` is `operational.yml.databricks_runtime.secret_scope`.
12. **Emit `src/connectors/{source}/scripts/install.sh`** (Databricks-side install phase): invokes `scripts/load-secrets.sh`, then runs `databricks bundle deploy --target dev`.
13. **Emit `src/connectors/{source}/install.sh`** (top-level orchestrator): calls `runtime/install.sh` first (provisioned by the upstream `provision-source` skill — REFERENCE only; do not generate that file), then `scripts/install.sh`. Honour a `--skip-runtime` flag for users with a pre-existing source-side.
14. **Emit `src/connectors/{source}/ingest_entry.py` and/or `transform_entry.py`** where the category reference requires job-entry wrappers (e.g. Lakeflow pipelines). Skip whichever the category does not require.
15. **Emit `src/connectors/{source}/sql/<envelope>.sql`** where the category reference requires explicit UC bronze schema bootstrap. Envelope name and column list are derived from `config.yml`'s `bronze_table` and the per-category bronze shape.
16. **Emit `src/connectors/{source}/resources/{schemas,volumes,connection,pipeline}.yml`** — the subset required by the category, per `references/<category>.md`. Interpolate `uc_catalog`, `bronze_volume`, `lakeflow_pipeline_name`, etc. from `operational.yml.databricks_runtime`.
17. **Insert the connector page §4 Setup, §Run-the-job, §Verify, §Troubleshooting sections** from the per-category templates in `references/<category>.md`. Interpolate per-source values (`secret_scope`, `bronze_table`, `cron_schedule`, etc.) from `operational.yml.databricks_runtime`. Do NOT modify §1–§3 (Reference) or §Source provisioning — those belong to `analyze-source` and `provision-source` respectively.
18. Record the invocation: list the generated file paths, run `git rev-parse --short HEAD` for the skill repo ref, and compute `sha256sum mkdocs/docs/connectors/{category}/{slug}.md` for the page hash that pins this generation to a specific page revision.
19. **Update the connector page's Implementation log section: fill in row 3 (`generate-connector`)** with the run date, inputs (page hash via `sha256sum mkdocs/docs/connectors/{category}/{slug}.md`), outputs (the full file set listed in the row template below), and the skill repo ref via `git rev-parse --short HEAD`. Row 1 (`analyze-source`), row 2 (`provision-source`), and row 4 (`validate-implementation`) MUST remain untouched. Row 4 stays marked `(pending)` so `validate-implementation` has a target to overwrite.

## Invariants

- No file is written outside `src/connectors/{source}/` (excluding the `runtime/` subtree — see next invariant), `tests/connectors/{source}/`, `config/severity/{source}.yml`, `config/status/{source}.yml`, `resources/{source}-job.yml`, or the connector page's §4 Setup / §Run-the-job / §Verify / §Troubleshooting + Implementation log row 3 sections. The connector generation is otherwise self-contained.
- The skill DOES NOT emit anywhere under `src/connectors/{source}/runtime/`. That path is `provision-source`'s territory (a separate skill). If the per-category template appears to require a `runtime/*` write, that is a bug in the template — halt and report.
- The top-level `src/connectors/{source}/install.sh` REFERENCES `src/connectors/{source}/runtime/install.sh` (emitted by `provision-source`) but does NOT generate it. The reference is a shell invocation — at run time, if `runtime/install.sh` is absent and `--skip-runtime` was not passed, the orchestrator fails fast with a pointer to running `provision-source` first.
- If `src/connectors/{source}/operational.yml` is missing OR has missing required-by-category fields under `databricks_runtime:`, the skill FIRST attempts to gather the missing values via `AskUserQuestion` (batched up to 4 per call) and writes them back to `operational.yml.databricks_runtime.<field>`. Only when `AskUserQuestion` is unavailable (headless / unattended run, tool not loaded, or error result) does the skill fall back to halting and reporting the list of missing fields. Do NOT partial-emit in the halt fallback. The controller is then expected to gather the missing fields, write `operational.yml`, and re-run.
- The skill creates `operational.yml` when missing AND ASKS the user — via `AskUserQuestion` — for each required `databricks_runtime:` field. It does NOT autogenerate field values or use defaults that aren't declared in `references/<category>.md`. Fields the user populates already (or fields under `source_runtime:`, which is `provision-source`'s territory) are NEVER overwritten or touched by this skill.
- Both `config/severity/{source}.yml` and `config/status/{source}.yml` exist for every connector — even for categories where one or both are N/A. The N/A files carry an explanatory comment per `references/<category>.md`.
- All imports in `ingest.py` and `transform.py` reference only functions that already exist in `src/common/`. New shared helpers are NOT introduced by this skill; if a missing helper is identified, halt and report the gap rather than adding it inline.
- Every REQ-ID applicable to the category (per `references/<category>.md`) has at least one bound test function carrying `@pytest.mark.requirement("REQ-...")`. REQ-IDs marked N/A for the category are not bound.
- The Implementation log section of `mkdocs/docs/connectors/{category}/{slug}.md` has row 3 filled by this skill. Row 1 (`analyze-source`), row 2 (`provision-source`), and row 4 (`validate-implementation`) MUST remain untouched. Row 4 stays marked `(pending)` so `validate-implementation` has a target to overwrite.
- The connector page's §1–§3 (Reference) and §Source provisioning sections are NOT modified by this skill. The skill only inserts/updates §4 Setup, §Run-the-job, §Verify, §Troubleshooting and Implementation log row 3.
- Output is code, configuration, shell scripts, SQL DDL, DAB resource fragments, and test fixtures — plus the page §4–§7 sections and the single-line Implementation log row 3 update. No new top-level Markdown files are created.
- Shared files (`databricks.yml`, `mkdocs/mkdocs.yml`, `pyproject.toml`) are NEVER touched by this skill. Required shared-file additions — for example, including a new `resources/<source>-job.yml` in `databricks.yml` — are reported in the run output for the controller to wire up sequentially in a separate consolidation step.

Category-specific invariants (target Silver tables, dedup-key tuple, ingestion-tooling override, severity / status lookup shape, mapping.yml shape, applicable REQ-IDs, category quirks affecting code emission) live in `references/<category>.md`. Read the file matching the input category before emitting any file.

## Implementation log row template

Overwrite row 3 (`generate-connector`) of the connector page's 4-row Implementation log table — replacing the `(pending)` placeholder set by `analyze-source`. The 4-row schema is:

| # | Skill | Owner |
|---|---|---|
| 1 | `analyze-source` | filled upstream by `analyze-source` — DO NOT modify |
| 2 | `provision-source` | filled upstream by `provision-source` — DO NOT modify |
| 3 | `generate-connector` | **this skill writes here** |
| 4 | `validate-implementation` | left as `(pending)` — `validate-implementation` overwrites later |

Use this row shape verbatim, replacing the bracketed placeholders:

```
| Module generation | generate-connector ({category}) | page hash={sha256_of_page}, operational.yml.databricks_runtime fields=<comma-separated list of fields read> | src/connectors/{source}/{config.yml,ingest.py,transform.py,mapping.yml}, config/{severity,status}/{source}.yml, resources/{source}-job.yml, tests/connectors/{source}/, src/connectors/{source}/scripts/{load-secrets.sh,install.sh}, src/connectors/{source}/install.sh, src/connectors/{source}/{ingest_entry.py,transform_entry.py} (where applicable), src/connectors/{source}/sql/<envelope>.sql (where applicable), src/connectors/{source}/resources/{schemas,volumes,connection,pipeline}.yml (per category), mkdocs/docs/connectors/{category}/{slug}.md §4 Setup / §Run-the-job / §Verify / §Troubleshooting | {YYYY-MM-DD} | {git_short_sha} ({branch}) |
```

- `{category}` — the AppSec category input (`cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, or `waf`).
- `{sha256_of_page}` — output of `sha256sum mkdocs/docs/connectors/{category}/{slug}.md` (the full hex digest pins this generation to the page revision read at step 3).
- `{source}` — the source name input.
- `{YYYY-MM-DD}` — the run date in ISO format.
- `{git_short_sha}` — output of `git rev-parse --short HEAD` on the skill's repo.
- `{branch}` — output of `git rev-parse --abbrev-ref HEAD`.

Per-category trimming: omit Outputs cell entries that the category does not emit (e.g. CMDB has no `*_entry.py`; secrets uses `volumes.yml` but not `connection.yml`; etc., per `references/<category>.md`). The cell must accurately reflect what was actually written.

Row 4 (`validate-implementation`) MUST remain marked `(pending)` so the next skill has a target to overwrite. Rows 1 (`analyze-source`) and 2 (`provision-source`) MUST remain untouched.
