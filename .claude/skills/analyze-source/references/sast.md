# analyze-source — SAST reference

Facts the analyze-source skill needs to write a complete Reference section for a SAST source.

## Contents
- Applicable REQ-IDs
- Default severity
- Incremental strategy
- Deduplication key
- Target Silver tables
- Authentication norms
- Ingestion-tooling preference
- Quirks

## Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SAST sources emit findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SAST (per the SonarQube and Semgrep traceability rows).
- For CLI-based SAST (artefact ingestion), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A — the catalog notes the CLI-artefact ingestion path "has no API auth, pagination, or rate limit." The Reference section MUST disclose this if the source is CLI-based.

## Default severity

`medium`. Source severity vocabularies have three to five levels with overlapping but non-identical names; per-source lookup tables at `config/severity/{source}.yml` map each value to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data-quality warning.

## Incremental strategy

Selection depends on the deployment style documented in the SAST capability surface:

- **Server-based tools** carry an update-timestamp column usable as a high-water mark; this is the default mode.
- **CLI-based tools** (including container-hosted CLIs such as Semgrep in Docker) emit JSON or SARIF artefacts and have no server-side incremental hook. Treat these under the full-reload strategy with the commit SHA or scan-start timestamp as the HWM.
- **Platform-integrated scanners** (SAST hosted inside the SCM platform) share the host platform's incremental hook — typically webhook or `updated_at`.

## Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the canonical SAST scope.

The Reference section's Resource schema excerpt MUST therefore extract `repository_id`, `file_path`, `rule_id`, and the source-side `source_finding_id` building blocks (for example SonarQube `key`; Semgrep `id` / `check_id`+`path`+`line`).

## Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the code-level finding table).

## Authentication norms

PAT or API-key based across all three deployment styles per the SAST capability surface. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SAST is well-served by the SDK or dlt path. CLI-based SAST is the documented exception — `httpx` / `requests` / artefact-collection patterns are permitted because none of the three preferred tools cover the CI-artefact contract.

## Quirks

- **Operational pattern axis.** SAST tools split orthogonally on CI/CD-step (per-commit, scoped to the run) vs periodic-global (scheduled, scoped to the codebase). The Reference section's Quirks fact MUST disclose which mode the source operates in; the connector's incremental key changes between modes (commit SHA / run ID for CI/CD-step; updated-since timestamp for periodic-global).
- **CWE category.** Most SAST tools emit a CWE identifier alongside the rule ID; record it in the Resource schema excerpt for downstream classification work.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The Reference section MUST list every documented source severity value to support REQ-TRF-SEV coverage.
- **CLI-artefact path.** Where a SAST tool runs as a CI/CD CLI (Semgrep Docker, container-hosted CLIs), document the artefact location (pipeline artifact, mounted volume, object-storage prefix), the SARIF / JSON format flavour, and any container-runtime quirks.
- **Rule-pack drift.** Rule IDs change across rule-pack versions; the Reference section's Quirks fact should note whether the source provides rule-stability guarantees.
