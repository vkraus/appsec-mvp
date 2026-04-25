# Semgrep

## What this connector ingests

The Semgrep connector is the CI/CD-step SAST source. Operational pattern: **CI/CD-step + periodic-global, both via the CLI**. The Semgrep CLI runs inside Docker containers — either as a Kubernetes (EKS) `CronJob` scheduled against an enrolled repository inventory, or as a step in a GitHub Actions workflow on every commit / pull request — and emits its findings as JSON or SARIF v2.1.0 documents to an object-storage bucket. The connector reads those artefacts; it does **not** invoke `semgrep` itself and it does **not** call the Semgrep AppSec Platform Cloud API. It populates `silver.findings` from a single Bronze table `bronze_semgrep.findings` whose rows carry a `trigger_context` discriminator distinguishing the two artefact lanes.

**Category:** SAST (CLI, CI/CD-step + periodic-global) · **Integration pattern:** Artefact path (S3 prefixes consumed by an Auto Loader–driven pipeline)

Bronze schema: `bronze_semgrep`. Cross-source contribution: `silver.findings` with `tool_source = 'semgrep'`.

!!! info "CLI / Docker artefact path, not Semgrep Cloud"
    This connector targets the open-source Semgrep CLI documented at
    [semgrep.dev/docs/cli-reference](https://semgrep.dev/docs/cli-reference)
    running in a container (no login, no `semgrep ci --config p/...` against a
    Semgrep AppSec Platform account). The Semgrep AppSec Platform REST API
    (`https://semgrep.dev/api/v1/...`) is **out of scope** for this connector.
    If a deployment switches to Semgrep AppSec Platform, a separate connector
    must be generated against that API surface.

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md) if Phase 1 is not yet complete.
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** Semgrep findings are keyed by `(repository_id, file_path, rule_id)` per the [SAST dedup contract](../../platform/reference/canonical-mapping.md#silver-finding-mapping-requirements). The `repository_id` is derived from the artefact's S3 key (which encodes the repository slug) and must resolve to a row in `silver.repositories` for downstream rollups to attribute findings to a repository (and through `silver.app_repo_mapping`, to a business application).

## Reference

### API surface

Semgrep is a CLI tool with **no HTTP API**. The connector ingests JSON / SARIF artefacts that two Docker-hosted invocations write to S3. It does not invoke `semgrep` itself.

The two upstream invocations are:

- **Periodic-global lane.** A Kubernetes (EKS) `CronJob` runs the Semgrep Docker image (`returntocorp/semgrep`) on a schedule against a checked-out repository inventory, writing one artefact per (repository, scan-start-timestamp) under the S3 prefix `s3://<bucket>/periodic/semgrep/<repo>/<YYYYMMDDTHHMMSSZ>.{json,sarif}`.
- **CI/CD-step lane.** A GitHub Actions workflow runs the same image as a job step on every commit / pull request, writing one artefact per (repository, commit-SHA) under the S3 prefix `s3://<bucket>/cicd/semgrep/<repo>/<commit-sha>.{json,sarif}`.

Both lanes invoke the Semgrep CLI in the same documented form ([semgrep.dev/docs/cli-reference](https://semgrep.dev/docs/cli-reference)):

```
semgrep scan --config <ruleset> --json --json-output=/out/results.json [path]
# or
semgrep scan --config <ruleset> --sarif --sarif-output=/out/results.sarif [path]
```

`--json` emits the Semgrep-native JSON schema documented in the [JSON and SARIF fields](https://semgrep.dev/docs/semgrep-appsec-platform/json-and-sarif) reference. `--sarif` emits the OASIS [Static Analysis Results Interchange Format (SARIF) v2.1.0 Plus Errata 01](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) (28 August 2023) — the same standard used by GitHub code-scanning. The connector accepts both flavours and dispatches on the file extension; Bronze stores the raw envelope verbatim.

**No authentication.** The local Semgrep CLI requires no token and does not authenticate to any Semgrep service for the local scan path. The CLI reference notes that running `semgrep scan` against a local codebase is "suitable if you want to scan your codebase for security issues without requiring a Semgrep account." The only credentials in this connector are the AWS reader credentials for the S3 artefact bucket, resolved from the platform secret scope per `REQ-ING-AUTH`'s general posture — but **`REQ-ING-AUTH` itself does not apply** to the Semgrep API surface, because there is no Semgrep API to authenticate against. The catalog at [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md) marks `REQ-ING-AUTH` `N/A` on the Semgrep row alongside `REQ-ING-PAG` and `REQ-ING-RL`, with the rationale that "the CLI artifact ingestion path has no API auth, pagination, or rate limit."

### Pagination and rate limits

Pagination does not apply. Each artefact is a single self-contained JSON or SARIF document; the connector parses it as one unit. There is no `next` cursor, page-index, or `Link`-header iteration. `REQ-ING-PAG` is **N/A** for the CLI-artefact path.

Rate limits do not apply. The connector reads from S3 (subject to S3's own per-account quotas, not a per-client tool quota); it does not call any Semgrep service. `REQ-ING-RL` is **N/A** for the CLI-artefact path.

### Incremental hook

**Full reload with a per-lane HWM key.** Semgrep has no server-side incremental endpoint. Per `references/sast.md` for CLI-based SAST, the connector treats each artefact as a complete scan and stores a per-lane high-water mark used purely as an optimisation for which artefacts to read on the next run:

| Lane | `trigger_context` | HWM strategy |
|---|---|---|
| `cicd/semgrep/` | `cicd` | `commit_sha` (the most recent commit SHA per repository for which an artefact has landed) |
| `periodic/semgrep/` | `periodic` | `scan_start_timestamp` (the most recent scan-start ISO 8601 UTC per repository for which an artefact has landed) |

The Bronze→Silver dedup key `(repository_id, file_path, rule_id)` per the [SAST dedup contract](../../platform/reference/canonical-mapping.md#silver-finding-mapping-requirements) enforces idempotence regardless of which artefacts get reread; the HWMs are recorded in `state.hwm` for cadence observability and to bound the Auto Loader read window. Because the CLI emits no native HWM column, `REQ-ING-HWM` is asserted at the lane / artefact-key level, not at the record level.

### Resource schema excerpt

Semgrep emits one finding object per match. The fields below are the subset consumed by the connector. Two flavours are documented because both `--json` and `--sarif` artefacts are accepted; the transform projects both into `silver.findings` through `mapping.yml` keyed by detected file extension.

**Semgrep `--json` output consumed fields** (per [JSON and SARIF fields](https://semgrep.dev/docs/semgrep-appsec-platform/json-and-sarif))

| Field | Type | Meaning |
|---|---|---|
| `check_id` | string | Rule identifier (e.g. `python.lang.security.audit.dangerous-subprocess-use.dangerous-subprocess-use`). Used as `rule_id` in `silver.findings`. |
| `path` | string | Repository-relative file path containing the finding. Used as `file_path` in `silver.findings`. |
| `start.line` | integer | Line number of the finding within `path`. |
| `start.col` | integer | Column at the match start. Retained in Bronze for triage. |
| `end.line` | integer | Line number where the match ends. Retained in Bronze. |
| `end.col` | integer | Column at the match end. Retained in Bronze. |
| `extra.message` | string | Human-readable rule message. Used as `message` in `silver.findings`. |
| `extra.severity` | string | Severity level: `ERROR`, `WARNING`, or `INFO` (see Enumerations). |
| `extra.metadata.cwe` | array of strings | CWE identifiers associated with the rule (e.g. `"CWE-78: Improper Neutralization..."`). First element extracted as `cwe_id` in `silver.findings`. |
| `extra.metadata.owasp` | array of strings | OWASP Top 10 references (e.g. `"A03:2021 — Injection"`). Retained in Bronze. |
| `extra.metadata.category` | string | Rule category (e.g. `security`, `correctness`). Retained in Bronze. |
| `extra.metadata.references` | array of strings | External documentation links for the rule. Retained in Bronze. |
| `extra.metadata.vulnerability_class` | array of strings | Attack-class label assigned by the rule author. Retained in Bronze. |
| `extra.metadata.technology` | array of strings | Frameworks / technologies the rule applies to. Retained in Bronze. |

**Semgrep `--sarif` output consumed fields** (per OASIS [SARIF v2.1.0 Plus Errata 01](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html))

| Field | Type | Meaning |
|---|---|---|
| `runs[].results[].ruleId` | string | SARIF rule identifier — same value Semgrep uses for `check_id` in the JSON flavour. Used as `rule_id`. |
| `runs[].results[].ruleIndex` | integer | Index into `runs[].tool.driver.rules[]` for rule metadata lookup. |
| `runs[].results[].level` | string | SARIF severity: `none`, `note`, `warning`, or `error` (see Enumerations). |
| `runs[].results[].message.text` | string | Finding message. Used as `message`. |
| `runs[].results[].locations[].physicalLocation.artifactLocation.uri` | string | Repository-relative file path. Used as `file_path`. |
| `runs[].results[].locations[].physicalLocation.region.startLine` | integer | Line number of the finding. |
| `runs[].results[].locations[].physicalLocation.region.startColumn` | integer | Column at the match start. Retained in Bronze. |
| `runs[].tool.driver.rules[].id` | string | Rule identifier for the corresponding `ruleIndex`. |
| `runs[].tool.driver.rules[].properties.tags` | array of strings | Rule tags including CWE / OWASP labels embedded by Semgrep. Source of `cwe_id`. |

The artefact's S3 key contributes two fields not present in the document body itself: the `<repo>` segment maps to `repository_id` (joined to `silver.repositories`), and the trailing segment (commit SHA for `cicd/`, scan-start timestamp for `periodic/`) populates the per-lane HWM column.

### Enumerations

**Severity vocabulary (JSON flavour).** Semgrep's `--json` output uses a three-value scale documented in the CLI reference: `INFO`, `WARNING`, `ERROR`. `src/connectors/semgrep/severity.yml` maps `ERROR`→`high`, `WARNING`→`medium`, `INFO`→`low`. Per the canonical four-level model (`critical`, `high`, `medium`, `low`), Semgrep does not emit a value that maps to `critical` — operators may override this in deployment-specific overlays, but the reference mapping treats Semgrep's top severity as `high` to match the documented vocabulary.

**Severity vocabulary (SARIF flavour).** Semgrep's `--sarif` output uses the SARIF `result.level` enumeration: `none`, `note`, `warning`, `error`. The same `severity.yml` covers these values: `error`→`high`, `warning`→`medium`, `note`→`low`, `none`→`low`. Both vocabularies must be present in the lookup table because the same connector ingests both artefact flavours.

**No status vocabulary.** Semgrep CLI does not expose a finding lifecycle (open / resolved / triaged) in the artefact. Each scan is a fresh capture of "what the rules currently match against this code." The connector sets `status = open` on first emit; transitions are not modelled by this connector. `REQ-TRF-STS` applies but the lookup table has a single literal mapping rather than a vocabulary table.

### Quirks

**No API, no pagination, no rate limit.** This is the SAST CLI-artefact posture documented in `references/sast.md`. `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` are recorded as `N/A` on the catalog matrix at [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md), and §5 of this page reflects the same.

**Two artefact prefixes, one Bronze table, distinguished by `trigger_context`.** The connector unifies the periodic-global and CI/CD-step lanes by landing both into `bronze_semgrep.findings` with a `trigger_context` column whose value is `periodic` or `cicd`. The Auto Loader pipeline configures two `cloudFiles.includeExistingFiles` source paths (`s3://<bucket>/periodic/semgrep/` and `s3://<bucket>/cicd/semgrep/`) and tags each row with the lane it came from. Downstream queries filter by `trigger_context` for lane-specific reporting, or aggregate over both for total coverage.

**Ingestion-tooling preference does not apply.** The standard preference order (Lakeflow Connect → Databricks SDK → dlt) does not apply because Semgrep has no API and emits no streamable feed; the artefacts are blobs in object storage. Per the architectural rules at `CLAUDE.md` and the SAST capability contract at [`mkdocs/docs/connectors/sast/index.md`](index.md), CLI-artefact connectors are the documented exception alongside TruffleHog and use Auto Loader against the configured S3 prefixes.

**HWM key differs by lane.** CI/CD-step artefacts are keyed by commit SHA (one artefact per commit per repository); periodic-global artefacts are keyed by scan-start timestamp (one artefact per scheduled run per repository). The `state.hwm` table carries one row per `(repository_id, trigger_context)` pair, with the value column holding either a hex SHA or an ISO 8601 timestamp. Auto Loader's checkpointing handles file-level idempotence; the per-lane HWM is operator-facing observability.

**JSON and SARIF coexist.** The connector accepts artefacts in either flavour and routes by file extension. The two flavours carry equivalent core fields (rule ID, file path, line, message, severity) under different names; `mapping.yml` codifies the equivalence so a deployment switching from one flavour to the other does not require connector changes.

**No `severity = critical` from native Semgrep.** Semgrep's documented severity vocabulary tops out at `ERROR` / `error`, which the reference mapping treats as `high`. Deployments needing a `critical` tier (e.g. for rules in a "block-the-build" ruleset) must apply per-rule overrides via `severity.yml` rather than expecting Semgrep to emit a `critical` value natively.

**CWE extraction is opportunistic.** Not every Semgrep rule carries `extra.metadata.cwe` (or SARIF `properties.tags` with CWE labels). When absent, `silver.findings.cwe_id` is `null`. Operators who need full CWE coverage must use a ruleset that consistently tags CWE on its rules (the `p/security-audit` and `p/owasp-top-ten` packs do; many community rules do not).

**Rule-pack drift.** Rule IDs (`check_id`) change across rule-pack versions. The connector retains the `check_id` verbatim and surfaces version drift downstream — Silver records carry the `check_id` as authored at scan time. Cross-time analytics that need stable rule grouping should join on `cwe_id` plus `vulnerability_class` rather than on `rule_id`.

## Setup

!!! info "Setup runbook pending"
    The end-to-end Setup runbook (artefact-bucket secrets, Auto Loader pipeline
    deployment, EKS `CronJob` and GitHub Actions workflow templates, sample
    artefact upload, verification queries, troubleshooting) is populated by
    `generate-connector` after this analysis page lands. Until then, the high-
    level shape is: load the artefact-bucket name and AWS reader credentials
    into the `mvp-connectors` secret scope; `databricks bundle deploy` the
    Semgrep job; drop a sample `--json` or `--sarif` artefact under the
    appropriate prefix; trigger the job.

## Validation

!!! info "Pending validation"
    The Implementation report (per-REQ PASS / FAIL / N/A table, bound test
    paths, pytest summary) is populated by `validate-implementation` after the
    connector module is generated. `REQ-ING-AUTH`, `REQ-ING-PAG`, and
    `REQ-ING-RL` are expected to be marked `N/A` per the CLI-artefact posture
    documented in §3 above and in
    [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md).

## Generation log

This connector page is produced by the connector lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                              | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (sast)            | name=Semgrep; url=https://semgrep.dev/docs/cli-reference (+ SARIF v2.1.0 spec at https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html); category=sast | mkdocs/docs/connectors/sast/semgrep.md §1–§3                                       | 2026-04-25 | 3cd1028 (regenerate-4-originals)         |
| Module generation | `generate-connector` (sast) | page hash=866cfaf193ed | src/connectors/semgrep/__init__.py, src/connectors/semgrep/config.yml, src/connectors/semgrep/ingest.py, src/connectors/semgrep/transform.py, src/connectors/semgrep/mapping.yml, src/connectors/semgrep/severity.yml, src/connectors/semgrep/status.yml, src/connectors/semgrep/resources/job.yml, src/connectors/semgrep/tests/__init__.py, src/connectors/semgrep/tests/test_ingest.py, src/connectors/semgrep/tests/test_transform.py, src/connectors/semgrep/tests/fixtures/cicd_scan.json, src/connectors/semgrep/tests/fixtures/periodic_scan.sarif, src/connectors/semgrep/tests/fixtures/prefix_routing.json, src/connectors/semgrep/tests/fixtures/mixed_severity.json | 2026-04-25 | 76c543e (regenerate-4-originals) |
| Validation         | `validate-implementation` (sast)   | (pending)                                                                           | (pending)                                                                          | (pending)  | (pending)                                |

## References

- Semgrep CLI reference — [https://semgrep.dev/docs/cli-reference](https://semgrep.dev/docs/cli-reference)
- Semgrep JSON and SARIF fields reference — [https://semgrep.dev/docs/semgrep-appsec-platform/json-and-sarif](https://semgrep.dev/docs/semgrep-appsec-platform/json-and-sarif)
- OASIS Static Analysis Results Interchange Format (SARIF) Version 2.1.0 Plus Errata 01 (28 August 2023) — [https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html)
- Category contract — [SAST connectors](index.md)
- Category-specific facts (REQ-IDs, dedup key, HWM, ingestion-tooling preference, quirks) — `references/sast.md` in the analyze-source skill
- Canonical Silver Finding mapping (code-level) — [`mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`](../../platform/reference/canonical-mapping.md#silver-finding-mapping-requirements)
- REQ catalog and per-source traceability matrix — [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md)
