# SAST skills

Three skills cover the connector lifecycle for SAST sources. Each carries a SAST-specific reference; the procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source — SAST reference

Facts the analyze-source skill needs to write a complete Reference section for a SAST source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SAST sources emit findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SAST (per the SonarQube and Semgrep traceability rows).
- For CLI-based SAST (artefact ingestion), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A — the catalog notes the CLI-artefact ingestion path "has no API auth, pagination, or rate limit." The Reference section MUST disclose this if the source is CLI-based.

### Default severity

`medium`. Source severity vocabularies have three to five levels with overlapping but non-identical names; per-source lookup tables at `src/connectors/{source}/severity.yml` map each value to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data-quality warning.

### Incremental strategy

Selection depends on the deployment style documented in the SAST capability surface:

- **Server-based tools** carry an update-timestamp column usable as a high-water mark; this is the default mode.
- **CLI-based tools** (including container-hosted CLIs such as Semgrep in Docker) emit JSON or SARIF artefacts and have no server-side incremental hook. Treat these under the full-reload strategy with the commit SHA or scan-start timestamp as the HWM.
- **Platform-integrated scanners** (SAST hosted inside the SCM platform) share the host platform's incremental hook — typically webhook or `updated_at`.

### Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the canonical SAST scope.

The Reference section's Resource schema excerpt MUST therefore extract `repository_id`, `file_path`, `rule_id`, and the source-side `source_finding_id` building blocks (for example SonarQube `key`; Semgrep `id` / `check_id`+`path`+`line`).

### Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the code-level finding table).

### Authentication norms

PAT or API-key based across all three deployment styles per the SAST capability surface. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SAST is well-served by the SDK or dlt path. CLI-based SAST is the documented exception — `httpx` / `requests` / artefact-collection patterns are permitted because none of the three preferred tools cover the CI-artefact contract.

### Quirks

- **Operational pattern axis.** SAST tools split orthogonally on CI/CD-step (per-commit, scoped to the run) vs periodic-global (scheduled, scoped to the codebase). The Reference section's Quirks fact MUST disclose which mode the source operates in; the connector's incremental key changes between modes (commit SHA / run ID for CI/CD-step; updated-since timestamp for periodic-global).
- **CWE category.** Most SAST tools emit a CWE identifier alongside the rule ID; record it in the Resource schema excerpt for downstream classification work.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The Reference section MUST list every documented source severity value to support REQ-TRF-SEV coverage.
- **CLI-artefact path.** Where a SAST tool runs as a CI/CD CLI (Semgrep Docker, container-hosted CLIs), document the artefact location (pipeline artifact, mounted volume, object-storage prefix), the SARIF / JSON format flavour, and any container-runtime quirks.
- **Rule-pack drift.** Rule IDs change across rule-pack versions; the Reference section's Quirks fact should note whether the source provides rule-stability guarantees.

*Rendered from `.claude/skills/analyze-source/references/sast.md`. Source-of-truth lives in the skill file.*

## generate-connector — SAST reference

Facts the generate-connector skill needs to emit a SAST connector module. SAST sources emit code-level findings.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SAST (full ten REQ-IDs apply per the SonarQube and Semgrep traceability rows): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — the catalog notes the CLI-artefact path "has no API auth, pagination, or rate limit." Do NOT bind these three.
- Platform-integrated SAST (hosted inside the SCM platform): inherits the SCM connector's auth, pagination, and rate-limit code; bind only the transform / DQ / dedup REQ-IDs locally and document the inherited bindings in a comment.

### Default severity

`medium`. Generate `src/connectors/{source}/severity.yml` covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` with a data-quality warning per the helper in `src/platform/`.

The `mapping.yml` `severity` field references the lookup file by path, NOT a hard-coded value:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: src/connectors/{source}/severity.yml
```

### Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based**: native update-timestamp HWM column (e.g. `updated_at`, `creationDate`, `last_scan_finished_at`). Default mode.
- **CLI-based**: full-reload from object-storage prefix or pipeline artefact; HWM is the commit SHA or scan-start timestamp recorded in the artefact filename.
- **Platform-integrated**: inherit the SCM platform's webhook or `updated_at` hook.

### Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py` when building `dedup_links` rows:

```python
dedup_key = (row["repository_id"], row["file_path"], row["rule_id"])
```

The transform MUST also project `source_finding_id` (the source-side stable identifier — SonarQube `key`; Semgrep `id` for Cloud or `check_id`+`path`+`line` for CLI) for cross-run linkage.

### Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sast"` literally.

### Authentication norms

PAT or API-key based across all three deployment styles. `ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names only. For CLI-based connectors, no API auth applies — IAM on the artefact bucket governs access.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SAST is well-served by the SDK or dlt path (paginated REST).
- **CLI-based SAST is the documented exception** — emit a CLI-artefact ingest path (e.g. `httpx` for cloud-storage APIs, or autoloader on the object-storage prefix) and justify the deviation in a top-of-file comment in `ingest.py`. This is one of the two CLI-artefact exceptions called out in `CLAUDE.md` (alongside secrets / Semgrep Docker).
- Platform-integrated SAST shares the host SCM connector's pagination/auth helpers (note this in the top-of-file comment).

### Quirks

- **Operational pattern axis.** The `config.yml` HWM shape changes between CI/CD-step (commit SHA / run ID) and periodic-global (updated-since timestamp) modes. Encode the chosen mode explicitly; do not leave it inferred.
- **CWE category.** Project the source's CWE identifier alongside `rule_id` in `mapping.yml`; downstream classification depends on it.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The severity lookup MUST be exhaustive over the documented vocabulary; no gaps.
- **CLI-artefact path.** When the source is CLI-based, `config.yml` encodes the object-storage prefix (or pipeline-artefact pattern) and the SARIF / JSON format flavour; `ingest.py` uses autoloader-style ingestion via `src/platform/` helpers.
- **Rule-pack drift.** Rule IDs may shift across rule-pack versions; the dedup key embeds `rule_id` as-is. Document any source-side stability guarantees in a transform-level comment.

*Rendered from `.claude/skills/generate-connector/references/sast.md`. Source-of-truth lives in the skill file.*

## validate-implementation — SAST reference

Facts the validate-implementation skill needs to populate the Validation table for a SAST connector. SAST sources emit code-level findings; the full ten REQ-IDs apply for server-based deployments.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The SonarQube and Semgrep columns of the traceability matrix are the authoritative per-source rows for this category — every cell is `PASS`.

Apply (all ten — the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS`
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`: none for the server-based deployment style.

CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The same rationale applies to CLI-based SAST. Apply this N/A profile when validating a CLI-only connector.

Platform-integrated SAST (hosted inside the SCM platform): inherits the SCM connector's auth, pagination, and rate-limit code; the SAST test suite binds only the transform / DQ / dedup REQ-IDs locally. The inherited bindings are documented in a comment, not retested.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/sast/index.md` § "Capability surface". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) and asserting that undocumented values fall through to the configured default with a data-quality warning per the catalog requirement text.

### Incremental strategy

Per `mkdocs/docs/connectors/sast/index.md` § "Capability surface": server-based uses native update-timestamp HWM; CLI-based uses commit SHA or scan-start timestamp under full reload. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against whichever mode the connector selected.

### Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/connectors/sast/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Mis-keyed `dedup_links` rows are flagged as `FAIL`.

### Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The test suite's `REQ-TRF-MAP` assertions verify the discriminator literal alongside the field projections.

### Authentication norms

PAT or API-key per `mkdocs/docs/connectors/sast/index.md` § "Capability surface". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based connectors omit this test (the path has no API auth).

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CLI-based SAST is the documented exception per `CLAUDE.md` ("Ingestion tooling preference order"); the validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

### Quirks

- **Operational pattern axis.** CI/CD-step (commit SHA / run ID) vs periodic-global (updated-since timestamp) modes are exercised by the same `REQ-ING-HWM` test against the connector's chosen mode. The mode is fixed at `config.yml` time, not at test time.
- **CWE category projection.** `REQ-TRF-MAP` asserts that the source's CWE identifier is projected alongside `rule_id`.
- **Severity vocabulary breadth.** `REQ-TRF-SEV` asserts coverage over the FULL documented vocabulary (BLOCKER…INFO, CRITICAL…LOW, or numeric scales). Gaps fail the test.
- **CLI-artefact path.** When the source is CLI-based, the auth / pagination / RL tests are absent (REQ-IDs marked `N/A`); the table summary cites the catalog's "no API auth, pagination, or rate limit" rationale.
- **Rule-pack drift.** `REQ-DEDUP` asserts that `rule_id` is preserved as-is in the dedup key; rule-pack version drift is documented in a transform-level comment, not asserted by the test.

*Rendered from `.claude/skills/validate-implementation/references/sast.md`. Source-of-truth lives in the skill file.*
