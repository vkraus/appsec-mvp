# generate-connector — SAST reference

Facts the generate-connector skill needs to emit a SAST connector module. SAST sources emit code-level findings.

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

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SAST (full ten REQ-IDs apply per the SonarQube and Semgrep traceability rows): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — the catalog notes the CLI-artefact path "has no API auth, pagination, or rate limit." Do NOT bind these three.
- Platform-integrated SAST (hosted inside the SCM platform): inherits the SCM connector's auth, pagination, and rate-limit code; bind only the transform / DQ / dedup REQ-IDs locally and document the inherited bindings in a comment.

## Default severity

`medium`. Generate `config/severity/{source}.yml` covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` with a data-quality warning per the helper in `src/platform/`.

The `mapping.yml` `severity` field references the lookup file by path, NOT a hard-coded value:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

## Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based**: native update-timestamp HWM column (e.g. `updated_at`, `creationDate`, `last_scan_finished_at`). Default mode.
- **CLI-based**: full-reload from object-storage prefix or pipeline artefact; HWM is the commit SHA or scan-start timestamp recorded in the artefact filename.
- **Platform-integrated**: inherit the SCM platform's webhook or `updated_at` hook.

## Deduplication key

The dedup tuple `(repository_id, file_path, rule_id)` matches the SAST capability surface at [`mkdocs/docs/connectors/sast/index.md`](../../../../mkdocs/docs/connectors/sast/index.md) § "Canonical mapping contribution" and is consistent with the canonical Silver Finding shape at [`mkdocs/docs/platform/reference/canonical-mapping.md`](../../../../mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements). Encode this tuple literally in `transform.py` when building `dedup_links` rows:

```python
dedup_key = (row["repository_id"], row["file_path"], row["rule_id"])
```

The transform MUST also project `source_finding_id` (the source-side stable identifier — SonarQube `key`; Semgrep `id` for Cloud or `check_id`+`path`+`line` for CLI) for cross-run linkage.

## Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sast"` literally.

## Authentication norms

PAT or API-key based across all three deployment styles. `ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names only. For CLI-based connectors, no API auth applies — IAM on the artefact bucket governs access.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SAST is well-served by the SDK or dlt path (paginated REST).
- **CLI-based SAST is the documented exception** — emit a CLI-artefact ingest path (e.g. `httpx` for cloud-storage APIs, or autoloader on the object-storage prefix) and justify the deviation in a top-of-file comment in `ingest.py`. This is one of the two CLI-artefact exceptions called out in `CLAUDE.md` (alongside secrets / Semgrep Docker).
- Platform-integrated SAST shares the host SCM connector's pagination/auth helpers (note this in the top-of-file comment).

## Quirks

- **Operational pattern axis.** The `config.yml` HWM shape changes between CI/CD-step (commit SHA / run ID) and periodic-global (updated-since timestamp) modes. Encode the chosen mode explicitly; do not leave it inferred.
- **CWE category.** Project the source's CWE identifier alongside `rule_id` in `mapping.yml`; downstream classification depends on it.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The severity lookup MUST be exhaustive over the documented vocabulary; no gaps.
- **CLI-artefact path.** When the source is CLI-based, `config.yml` encodes the object-storage prefix (or pipeline-artefact pattern) and the SARIF / JSON format flavour; `ingest.py` uses autoloader-style ingestion via `src/platform/` helpers.
- **Rule-pack drift.** Rule IDs may shift across rule-pack versions; the dedup key embeds `rule_id` as-is. Document any source-side stability guarantees in a transform-level comment.
