# TruffleHog

!!! info "Placeholder — not implemented in MVP"
    A reference TruffleHog connector is not part of the MVP. This page is
    a scaffolding placeholder framing the intended runbook structure; the
    Reference section below documents the integration per the category
    capability surface. Follow the [Secrets skills](skills.md) to generate
    the connector when needed.

## What this connector ingests

TruffleHog is the dedicated secret-detection tool. Operational pattern: **CI/CD-step** — each `trufflehog` invocation is a complete scan scoped to a commit range, and the connector uses the latest scanned commit SHA per repository as the high-water mark (`--since-commit`). The connector invokes the TruffleHog CLI against each enrolled repository and parses its line-delimited JSON output to populate `silver.findings`. TruffleHog's distinguishing capability is live credential verification: with `--results=verified,unknown`, the tool validates each detected secret against the provider's authentication endpoint and emits a `Verified` boolean. This boolean is the primary signal for the canonical `validity_status` column.

**Category:** Secrets (CLI; CI/CD-step) · **Integration pattern:** Artifact path (CI/CD-step output → Databricks Volume)

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md).
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** TruffleHog findings are keyed by `(repository_id, commit_sha, secret_type, file_path)`; `repository_id` must resolve to a row in `silver.repositories` for downstream rollups to attribute findings to a repository (and through `silver.app_repo`, to a business application).

## Reference

### API surface

TruffleHog is a CLI tool with no HTTP API. The connector ingests the JSON artefacts that CI/CD-step invocations write to a Databricks Volume; it does not invoke `trufflehog` itself. The canonical CI/CD invocation is:

```
trufflehog <source-kind> <source-args> --json [--results=verified,unknown] [--since-commit=<sha>]
```

Relevant source kinds: `git`, `github`, `gitlab`, `filesystem`, `docker`, `s3`, `gcs`, `circleci`, `travisci`, `jenkins`, `postman`, `elasticsearch`, `stdin`, `huggingface`. Authentication for the target source (SSH key, GitHub PAT, AWS credentials) is provided via source-kind-specific flags or environment variables. TruffleHog itself needs no separate authentication — `REQ-ING-AUTH` is N/A for this connector per the secrets capability surface (CLI-artefact ingestion path).

Exit codes: `0` on clean run with no results, `1` on tool error, `183` on results found when `--fail` is set. The connector treats the artefact's presence in the volume as the success signal; exit codes are recorded in CI/CD logs for operability but are not consumed by the ingestion path.

### Pagination and rate limits

Pagination does not apply: the invocation streams line-delimited JSON to standard output, captured to a single artefact per (repository, commit) pair. The connector parses each object as it arrives. `REQ-ING-PAG` and `REQ-ING-RL` are N/A for the CLI-artefact path.

Rate limits apply to the upstream source where TruffleHog calls a verification endpoint. For the `github` kind and for verifier calls against provider APIs, the runner pays the upstream rate-limit cost during the scan, not the connector. For `s3`, the CI/CD step sets `--concurrency` (default 12) conservatively to stay within account quotas. Git and filesystem kinds are local and have no network constraints.

### Incremental hook

Full reload — TruffleHog has no general-purpose incremental mode and the secrets capability surface designates secret-detection sources as full-reload-only. Each invocation is a complete scan. The `git` kind accepts `--since-commit` to restrict the scan to commits after a checkpoint; the connector records the most recent commit SHA in `state.hwm` and supplies it as `--since-commit` on the next CI/CD run as an optimisation, not a contract. The Bronze-to-Silver dedup key `(repository_id, commit_sha, secret_type, file_path)` enforces idempotence regardless of `--since-commit`.

`filesystem`, `docker`, and `s3` kinds have no equivalent flag: each invocation rescans the full target. The connector stores a synthetic last-full-scan timestamp for cadence observability only.

### Resource schema excerpt

TruffleHog emits one JSON object per line. The fields below are the subset consumed in `git` source mode.

**TruffleHog JSON output consumed fields (`git` source kind)**

| Field | Type | Meaning |
|---|---|---|
| `DetectorName` | string | Detector that matched the secret (e.g. `AWS`, `GitHub`, `SlackWebhook`); used as `rule_id` in `silver.findings`. |
| `DetectorType` | integer | Numeric detector code assigned by TruffleHog; preserved in Bronze as a domain column. |
| `DecoderName` | string | Encoding decoder that produced the candidate (e.g. `PLAIN`, `BASE64`); retained in Bronze for triage. |
| `Verified` | boolean | `true` if live verification confirmed the secret is active against its provider's authentication endpoint. |
| `VerificationError` | string | Error message emitted when verification was attempted but did not return a definitive result; null when verification succeeded or was not attempted. |
| `Raw` | string | The raw matched secret value; see Quirks for the mandatory handling policy for this field. |
| `RawV2` | string | Normalised secret value, implementation-specific to each detector; subject to the same handling policy as `Raw`. |
| `Redacted` | string | Redacted form of the secret suitable for logging; retained in Silver. |
| `ExtraData` | object | Detector-specific enrichment (e.g. AWS account ID, ARN, IAM user); flattened into Bronze domain columns. |
| `SourceID` | integer | Numeric source identifier assigned by TruffleHog at scan time; retained in Bronze for trace. |
| `SourceType` | integer | Numeric source-kind code (e.g. `16` for `git`); used to dispatch source-kind-specific extraction. |
| `SourceName` | string | Human-readable scan label (e.g. `trufflehog - git`); retained in Bronze. |
| `SourceMetadata.Data.Git.commit` | string | Commit SHA in which the secret was introduced. |
| `SourceMetadata.Data.Git.file` | string | Repository-relative file path containing the secret. |
| `SourceMetadata.Data.Git.line` | integer | Line number within the file. |
| `SourceMetadata.Data.Git.email` | string | Email address of the commit author. |
| `SourceMetadata.Data.Git.timestamp` | datetime | Commit timestamp; normalised to UTC at the Bronze-to-Silver transform. |
| `SourceMetadata.Data.Git.repository` | string | Repository URL; used to join to `silver.repositories`. |

`SourceMetadata.Data` is source-kind-specific. The `Git` shape above is the primary variant. Filesystem, GitHub, and S3 scans use leaf structures `Filesystem`, `Github`, `S3`; the connector has source-kind-specific extraction logic dispatched on `SourceType`.

### Enumerations

**Severity is conventional, not source-derived.** TruffleHog emits no severity field. Per the secrets capability surface, every TruffleHog finding is mapped to `severity=high` by default in `src/connectors/trufflehog/severity.yml`. Per-deployment overrides are permitted for low-entropy detector classes (e.g. `GenericApiKey` → `medium`).

**No status vocabulary.** TruffleHog does not expose an open / resolved lifecycle. `REQ-TRF-STS` does not apply; the canonical `status` field is set to `open` on first emit and not transitioned by this connector.

**`validity_status` derives from verification flags.** TruffleHog's `Verified` boolean and `VerificationError` string populate the canonical `validity_status` column:

| Source signal | Canonical `validity_status` |
|---|---|
| `Verified=true` | `active` |
| `Verified=false`, empty `VerificationError` | `inactive` |
| `Verified=false`, non-empty `VerificationError` | `unknown` |
| `--no-verification` was set | `unknown` (verification not attempted) |

The `unknown` category matters: it covers secrets on isolated networks or against deprecated provider APIs and must not be conflated with `inactive`.

**`DetectorName`.** TruffleHog ships over 800 detectors covering AWS, GitHub, GitLab, Slack webhooks, Stripe, JIRA, Postgres, MongoDB, and hundreds more. The connector stores `DetectorName` verbatim in Bronze and maps it to `secret_type` without normalisation. The full detector list lives in the TruffleHog repository under `pkg/detectors/`.

### Quirks

**CLI-artefact ingestion deviates from the standard preference order.** The category preference (Lakeflow Connect > Databricks SDK > dlt) does not apply because TruffleHog is a binary that runs on CI/CD runners, not a server with an API. The connector reads `--json` artefacts from a Databricks Volume; this is the documented exception alongside Semgrep Docker.

**No severity field; all findings mapped to `high` by convention.** TruffleHog emits no severity. The reference implementation maps every finding to `severity=high` on the premise that a committed secret is a critical exposure regardless of detector. The default is in `src/connectors/trufflehog/severity.yml` and is overridable per deployment.

**`Raw` and `RawV2` must not enter the Silver layer.** The connector drops `Raw` and `RawV2` before Bronze-to-Silver, keeping only `Redacted`. This is mandatory, not configurable. For deployments needing raw values for automated remediation, the reference implementation provides an optional Unity Catalog column-level access policy on the Bronze `Raw`/`RawV2` columns restricted to the `secrets_raw_reader` group.

**Per-commit deduplication preserves the audit trail.** The same secret may appear across multiple commits (committed, partially removed, re-introduced). The dedup key `(repository_id, commit_sha, secret_type, file_path)` retains one record per commit rather than collapsing by secret value, preserving audit trails for compliance incident timelines. Gold-layer queries can derive a by-value deduplicated view. Both per-commit (CI/CD-step) and host-side periodic-global scans (e.g. backfill runs) emit records with `(repository_id, commit_sha)` so dedup unifies them without double-counting.

**`DetectorName` substitutes for `rule_id`.** TruffleHog has no rule-identifier concept. The connector maps `DetectorName` to `rule_id` in `silver.findings`. The substitution is lossless since `DetectorName` is a stable, versioned identifier in TruffleHog's registry.

**`--results=verified,unknown` is recommended.** `--only-verified` reduces false positives but silently discards secrets the verifier cannot reach (isolated networks, deprecated provider APIs). The reference implementation uses `--results=verified,unknown` to retain confirmed (`Verified=true`) and undeterminable (non-empty `VerificationError`) findings, leaving filtering to Silver. Definitively `inactive` findings (`Verified=false`, no error) are retained in Bronze for audit but excluded from the gold-layer active-threat view by default.

## Setup

!!! info "Not implemented in MVP"
    See the Overview admonition. Setup steps will be populated by
    `generate-connector` (secrets) and `validate-implementation`
    (secrets) when the connector module is produced.

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | — | N/A |
| `REQ-ING-PAG` | — | N/A |
| `REQ-ING-RL` | — | N/A |
| `REQ-ING-HWM` | — | N/A |
| `REQ-TRF-MAP` | `src/connectors/trufflehog/test_transform.py::test_record_to_silver_projects_every_consumed_field` | PASS |
| `REQ-TRF-SEV` | `src/connectors/trufflehog/test_transform.py::test_severity_is_hard_coded_high` | PASS |
| `REQ-TRF-STS` | — | N/A |
| `REQ-TRF-TS` | `src/connectors/trufflehog/test_transform.py::test_source_timestamp_is_preserved_from_git_leaf` | PASS |
| `REQ-DQ` | `src/connectors/trufflehog/test_transform.py::test_missing_git_metadata_produces_well_formed_row` | PASS |
| `REQ-DEDUP` | `src/connectors/trufflehog/test_transform.py::test_dedup_key_is_four_tuple_per_secrets_reference` | PASS |

Collected 26 requirement-bound tests via `pytest src/connectors/trufflehog/tests/ -v --tb=short` (2026-04-25, 0.31 s wall-clock); 26 passed, 0 failed, 4 skipped as documentation markers for the N/A rows. Five requirements are marked N/A: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` because the CLI-artefact ingestion path has no API auth, pagination, or upstream rate limit (quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix"); `REQ-ING-HWM` because TruffleHog is full-reload only per the secrets capability surface and the commit SHA lives in the artefact key rather than as a record-level HWM column; `REQ-TRF-STS` because secret-detection sources expose no lifecycle vocabulary to normalise (references/secrets.md § Quirks).

### Tests

Tests live under [`src/connectors/trufflehog/`](https://github.com/vkraus/appsec-mvp/tree/main/tests/connectors/trufflehog). The report table above is the per-REQ outcome.

## Generation log

This connector page is produced by the connector-lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                              | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (secrets)         | name=TruffleHog; url=https://github.com/trufflesecurity/trufflehog; category=secrets | mkdocs/docs/connectors/secrets/trufflehog.md §1–§3                                 | 2026-04-25 | 5b7fa80 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (secrets)     | page hash=5fc403d47499                                                              | src/connectors/trufflehog/, src/connectors/trufflehog/tests/, src/connectors/trufflehog/severity.yml, src/connectors/trufflehog/status.yml, src/connectors/trufflehog/resources/job.yml | 2026-04-25 | 61e9510 (retrofit-9-connectors)          |
| Validation         | `validate-implementation` (secrets)| module path=src/connectors/trufflehog/                                              | mkdocs/docs/connectors/secrets/trufflehog.md §5                                    | 2026-04-25 | 12f656a (retrofit-9-connectors)          |
