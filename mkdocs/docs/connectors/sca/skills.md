# SCA skills

Three skills operationalize the connector lifecycle for SCA sources.

!!! info "Specialization pending"
    These skills will be specialized for SCA sources (renamed to
    `analyze-source-sca`, `generate-connector-sca`,
    `validate-implementation-sca`) in a follow-up work item. Until then,
    the category-generic versions below apply.

## `analyze-source`

Source: [`.claude/skills/analyze-source.md`](https://github.com/vkraus/appsec-mvp/blob/main/.claude/skills/analyze-source.md)

````markdown
---
name: analyze-source
description: Use when analyzing a new data source system (REST API, GraphQL, SDK, or CLI) to produce a per-connector page for the docs site. Inputs are source name, homepage URL, API documentation URL, and AppSec category.
---

# analyze-source

Produce a per-connector documentation page for a data source to be integrated into the AppSec data platform framework. The output follows the five-section connector page template used across `mkdocs/docs/connectors/<category>/`.

## Inputs

- Source system name and homepage URL.
- Official API documentation (accessed via WebFetch).
- AppSec category (one of: `cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, `waf`).
- Optional: live API credentials for fixture generation.

## Output

Emit the Markdown page to stdout, ready for inclusion at `mkdocs/docs/connectors/<category>/<source-slug>.md` where `<category>` is one of `cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, `waf` (matching the AppSec category input).

The page has five top-level sections:

1. **Overview** — what this connector does; its role in the platform (which Silver table(s) it populates; any distinguishing capability). For sources not in the MVP, include an admonition:
   ```
   !!! info "Not in MVP scope"
       This connector is documented for future implementation.
   ```
2. **Prerequisites** — how to set up the external service and extract credentials (API keys, OAuth apps, PATs).
3. **Reference** — the seven API facts:
   - API surface (REST / GraphQL / SDK / CLI; endpoints consumed; authentication mechanisms)
   - Pagination and rate limits (strategy and quotas)
   - Incremental hook (selected per the category rules at `platform/reference/canonical-mapping`; preference order: webhook > native HWM column > full reload)
   - Resource schema excerpt (only fields consumed by connectors; Markdown table with columns Field / Type / Meaning)
   - Enumerations (severity and status mappings in terms of the canonical models from `platform/reference/canonical-mapping`)
   - Quirks (deviations from category norms, format surprises, per-source handling policies)
4. **Setup** — configuration, bundle deployment, first-run commands. If the source is not in the MVP, stub this section:
   ```
   !!! info "Not implemented in MVP"
       Setup instructions will be added when this connector is implemented.
   ```
5. **Validation** — implementation report and test outcomes. Always stub on first emit; `validate-implementation` fills this in after the test suite runs:
   ```
   !!! info "Pending validation"
       Run `validate-implementation` after implementing the connector to populate this section.
   ```

## Steps

1. Fetch the source's API documentation via WebFetch.
2. Identify the authentication mechanism supported by the source; select the one matching the category's convention documented at `platform/reference/canonical-mapping`.
3. Enumerate endpoints required to populate the Silver tables assigned to the source's category (cross-reference the Silver Table Ownership table at `platform/reference/catalog`).
4. Select the incremental strategy per the preference order in `platform/reference/canonical-mapping` for this category.
5. Extract consumed-field table entries matching canonical Silver fields from `platform/reference/canonical-mapping` (entities or findings schema, whichever applies to the source's category).
6. Produce severity and status lookup proposals per the canonical enumeration models at `platform/reference/canonical-mapping`.
7. Document quirks (deviations from category norms; format surprises).
8. Assemble the five-section Markdown page and emit to stdout.

## Invariants

- The output must link every official documentation URL used as an inline hyperlink or a References list at the bottom of the page.
- The severity and status lookups must cover every documented source value; undocumented values default to the configured fallback with a data-quality warning noted inline.
- No fabricated fields: every claim about the source's API must be traceable to the fetched documentation.
- The page slug and category directory must match the AppSec category input exactly; do not invent a new category.
````

## `generate-connector`

Source: [`.claude/skills/generate-connector.md`](https://github.com/vkraus/appsec-mvp/blob/main/.claude/skills/generate-connector.md)

````markdown
---
name: generate-connector
description: Use after analyze-source has produced a per-connector page. Generates a connector module conforming to the framework's project structure, connector contract, and canonical mapping requirements. Inputs are the source name, per-connector page, and category.
---

# generate-connector

Generate a connector module implementing the framework contract for a specific source, given the per-connector page produced by `analyze-source`.

## Inputs

- Source name (determines the module path `src/connectors/{source}/`).
- Per-connector page (structured form from `analyze-source`).
- Framework contracts: canonical Silver schemas (entities and findings) and normalization rules from `platform/reference/canonical-mapping`; connector contract from `platform/reference/catalog`.

## Output

A connector module at `src/connectors/{source}/` containing:

- `config.yml` — base URL, endpoints, pagination, HWM column, target Bronze table, credential reference.
- `ingest.py` — implements `ingest(run_id, state) -> batch` per the connector contract in `platform/reference/catalog`.
- `transform.py` — implements `transform(bronze_df) -> silver_df` per the normalization rules in `platform/reference/canonical-mapping`.
- `mapping.yml` — declarative Bronze-to-Silver column expressions referencing `src/connectors/{source}/severity.yml` and `src/connectors/{source}/status.yml`.
- `src/connectors/{source}/severity.yml` and `src/connectors/{source}/status.yml` — per-source lookups covering every source value documented in the connector page.
- `src/connectors/{source}/resources/job.yml` — canonical two-task Lakeflow job bundle fragment.
- `src/connectors/{source}/tests/test_ingest.py` and `test_transform.py` — pytest suite covering every REQ-ID from `platform/reference/catalog` applicable to the connector's category.
- `src/connectors/{source}/tests/fixtures/` — JSON fixtures named `{endpoint}_{scenario}.json`.

## Preconditions

- The per-connector page exists at `mkdocs/docs/connectors/<category>/<source-slug>.md` and has been reviewed for completeness.
- The framework's shared utilities (auth helpers, pagination handlers, normalization helpers under `src/platform/`) are present.

## Steps

1. Read the per-connector page and extract: authentication mechanism, pagination style, HWM column, resource endpoints and fields, severity map, status map, quirks.
2. Emit `config.yml` with the extracted parameters.
3. Select a connector category (LakeFlow Connect / SDK / REST-with-dlt-tool) per the preference order in `platform/reference/catalog` (Lakeflow Connect → SDK → dlt).
4. Emit `ingest.py` against the chosen category. LakeFlow Connect connectors leave the file empty and declare the ingestion resource in the bundle fragment. SDK connectors use the source's SDK. REST-with-dlt-tool connectors compose dlt components.
5. Emit `mapping.yml` with canonical-field → `{source_path, cast, lookup?}` blocks for every canonical Silver field defined in `platform/reference/canonical-mapping` (entities or findings schema, whichever applies).
6. Emit `src/connectors/{source}/severity.yml` and `src/connectors/{source}/status.yml` with every source value covered. For undocumented values, insert the configurable default and a comment flagging the DQ warning path.
7. Emit `transform.py` applying mapping plus normalization rules from `platform/reference/canonical-mapping`.
8. Emit the bundle fragment at `src/connectors/{source}/resources/job.yml` using the canonical two-task shape documented in `platform/reference/catalog`, substituting the source name.
9. Emit the test suite: one test function per REQ-ID applicable to the connector category, each marked with `@pytest.mark.requirement("REQ-...")`. Fixtures follow the `{endpoint}_{scenario}.json` naming convention.
10. Record the invocation — inputs, generated file paths, git commit hash — so that `validate-implementation` can reference it.

## Invariants

- No file is written outside `src/connectors/{source}/`, `src/connectors/{source}/tests/`, or `src/connectors/{source}/resources/job.yml`. The connector generation is self-contained.
- Every REQ-ID applicable to the category (from `platform/reference/catalog`) has at least one bound test function.
- All imports from `src/platform/` reference only functions that already exist in that module; new shared helpers are not introduced by this skill.
````

## `validate-implementation`

Source: [`.claude/skills/validate-implementation.md`](https://github.com/vkraus/appsec-mvp/blob/main/.claude/skills/validate-implementation.md)

````markdown
---
name: validate-implementation
description: Use after generate-connector to run the test suite against a generated connector and populate the Validation section of the connector's page at mkdocs/docs/connectors/<category>/<source>.md. Inputs are the source name, category, and connector module path.
---

# validate-implementation

Run the test suite for a generated connector and populate the **Validation** section of its page at `mkdocs/docs/connectors/<category>/<source>.md`.

## Inputs

- Source name (for path resolution).
- AppSec category (one of: `cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, `waf`).
- Connector module path at `src/connectors/{source}/`.
- Test suite path at `src/connectors/{source}/tests/`.
- Applicable REQ-IDs for the connector's category (looked up from `platform/reference/catalog`).

## Output

- A Markdown table summarizing test outcomes per REQ-ID (pass / fail / missing), ready to replace the stub in the **Validation** section of `mkdocs/docs/connectors/<category>/<source>.md`.
- Optional: a fix list for failing REQ-IDs with pointers to the failing test files.

## Steps

1. Run `pytest src/connectors/{source}/tests/ -v --tb=short` with coverage collection enabled.
2. Collect every test function carrying a `@pytest.mark.requirement("REQ-...")` marker and its outcome (passed / failed / skipped).
3. For each REQ-ID in the category's applicable set (from `platform/reference/catalog`), record: is there a bound test? did it pass? what is the line coverage of the production code invoked by that test?
4. Emit the Markdown table with one row per REQ-ID, using the symbols `PASS`, `FAIL`, or `—` (no bound test).
5. Emit the fix list as plain text: for each failing REQ-ID, the failing test file path and a one-line summary of the failure.
6. Replace the stub admonition in the **Validation** section of `mkdocs/docs/connectors/<category>/<source>.md` with the completed Markdown table and fix list (if any).

## Invariants

- No production code is modified by this skill. It is purely observational.
- Test timeouts are treated as failures, not skips.
- The Validation table always has exactly the REQ-IDs in the category's applicable set as rows, in the order they appear in `platform/reference/catalog`.
````
