# validate-implementation — WAF reference

Facts the validate-implementation skill needs to populate the Validation table for a WAF connector. WAF sources project edge-event records into finding-shape rows on `silver.findings` per the trufflehog convention — severity is derived from `action` via the action-keyed lookup, status is the literal `open`, and `finding_id` is a deterministic SHA-256 hash so re-deliveries collapse at MERGE.

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

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The AWS WAF column of the traceability matrix currently reads `N/A` across the board because the source is documented but not built in the MVP; the MVP-built profile would be the set below.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS` — degraded form: asserts `status_canonical` is the literal `open` on every emitted row and never transitions, per the trufflehog convention.
- `REQ-TRF-TS`
- `REQ-DQ` — also covers the deterministic-`finding_id` replay-deduplication assertion (re-delivered events collapse onto the same `finding_id` at MERGE).

Mark `N/A`:

- `REQ-ING-PAG` — N/A: log-stream consumption (the preferred mode per `mkdocs/docs/connectors/waf/index.md` § "Capability surface": "The connector specification SHALL prefer log-stream consumption over sampled SDK calls") has no API pagination. Apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests` fallback); otherwise mark `N/A` with the rationale "log-stream mode has no API pagination".
- `REQ-ING-RL` — N/A: same rationale; log-stream consumption has no API rate limit. Apply only when the SDK fallback is in use.
- `REQ-DEDUP` — N/A on the catalog matrix: WAF events do not share dedup tuples with SAST/SCA/secrets/DAST findings, so the connector emits no `dedup_links` rows. Replay deduplication is achieved instead by the deterministic `finding_id` SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` plus the Bronze→Silver MERGE — re-delivered events collapse onto the same `finding_id` at MERGE time. That replay assertion is bound under `REQ-DQ`, not `REQ-DEDUP`.

## Default severity

`medium` configurable default; severity is **derived** from the `action` field via an action-keyed lookup, not source-supplied. Per `mkdocs/docs/connectors/waf/index.md` § "Capability surface": "Severity is not a first-class field on a WAF event; the canonical severity is derived from the action via a per-source lookup table." The `REQ-TRF-SEV` test asserts the action-keyed lookup covers every documented action (`block`, `allow`, `count`, `challenge`, `captcha`) and that undocumented actions fall through to `medium` with a data-quality warning.

## Incremental strategy

Timestamp-based HWM over the log stream per `mkdocs/docs/connectors/waf/index.md` § "Capability surface". The connector records the last event-time ingested per WebACL or rule group and advances forward each run. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the timestamp advancement; SDK-fallback mode preserves `Weight` into Bronze and is also asserted under `REQ-ING-HWM` plus `REQ-TRF-MAP`.

## Deduplication key

Per `mkdocs/docs/platform/reference/canonical-mapping.md`: `REQ-DEDUP` is N/A for WAF — WAF events do not share dedup tuples with SAST/SCA/secrets/DAST findings, so no `dedup_links` rows are emitted. Replay deduplication is instead achieved via the deterministic `finding_id` SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` plus the Bronze→Silver MERGE; re-delivered events collapse onto the same `finding_id`. The test suite asserts this collapse under `REQ-DQ`, NOT under `REQ-DEDUP`. The test suite does NOT emit `dedup_links` rows for WAF.

## Target Silver tables

`silver.findings` — the canonical findings table, same target as SAST/SCA/secrets/DAST. The `REQ-TRF-MAP` test asserts the connector targets `silver.findings` with the canonical envelope columns populated; `cwe_id`, `cve_id`, `repository_id`, `file_path`, and `start_line` are null on every emitted row. The headline schema deviation that previously distinguished WAF (a dedicated `silver.waf_events` table) has been collapsed; WAF now matches every other category's `silver.findings` target.

The `REQ-TRF-MAP` test additionally asserts:

- `severity_canonical` is derived from `action` via the action-keyed lookup at `config/severity/{source}.yml`.
- `status_canonical` is the literal `open` on every row (asserted under `REQ-TRF-STS` in degraded form).
- `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` so re-deliveries collapse at MERGE.
- `repository_id` is null on every row (WAF events have no native repository linkage).
- WAF-specific telemetry (`source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, the `action` value itself) is NOT projected onto `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that detail.
- No transform-time join against `silver.deployments` is emitted — application linkage is deferred to Gold-side aggregations, which bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).

## Authentication norms

Account-scoped, NOT per-tenant, per `mkdocs/docs/connectors/waf/index.md` § "Capability surface". Cloud-native WAFs use IAM role or access key; on-prem appliances use a service credential bound to the log-aggregation tier. The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. Autoloader-style ingestion from the Firehose-to-S3 prefix (AWS WAF) fits the Lakeflow Connect / SDK envelope; no CLI-artefact deviation is needed. The validation suite verifies pagination and rate-limit absence under the N/A markings rather than asserting a tool-choice fact directly.

## Quirks

- **Finding-shape on `silver.findings`.** `REQ-TRF-MAP` asserts the connector targets `silver.findings` with the canonical envelope columns populated; `cwe_id`/`cve_id`/`repository_id`/`file_path`/`start_line` are null. The previous `silver.waf_events` schema deviation has been collapsed. The test fails if a dedicated `silver.waf_events` table is targeted.
- **Severity is derived.** `REQ-TRF-SEV` asserts the lookup is action-keyed, not severity-keyed. A severity-keyed lookup that mirrors a source severity field is a `FAIL`.
- **Status is the literal `open`.** `REQ-TRF-STS` (degraded form) asserts `status_canonical` is the literal `open` on every emitted row and never transitions, per the trufflehog convention. The `config/status/{source}.yml` lookup contains a comment to that effect.
- **Deterministic `finding_id`.** `REQ-DQ` asserts `finding_id` is a SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` and that re-delivered events collapse onto the same `finding_id` at the Bronze→Silver MERGE.
- **WAF-only telemetry is dropped.** `REQ-TRF-MAP` asserts `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself are NOT projected onto `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that telemetry.
- **Sampling weight preserved in Bronze only.** Where the SDK sampled-request fallback is in use, `REQ-TRF-MAP` asserts the `Weight` field is projected into Bronze (not onto `silver.findings`). Downstream extrapolation depends on it.
- **Application linkage is deferred.** `REQ-TRF-MAP` asserts `repository_id` is null on every row and that no transform-time join against `silver.deployments` is emitted. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. `REQ-TRF-SEV` asserts coverage over the full action vocabulary the source emits.
- **Log-stream over SDK.** `REQ-ING-PAG` and `REQ-ING-RL` are bound only when the SDK fallback is in use. Log-stream-only deployments mark them `N/A` with the rationale "log-stream mode has no API pagination/rate limit".

## sdk-branch validation note

Sources on the `sdk` branch (per `databricks_runtime.ingestion_path == sdk` + `python_sdk_module`, e.g. AWS WAF on boto3 sampled-request mode) keep `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM` PASS — the framework concerns are still exercised, but via library mocks (e.g. `MagicMock` on the boto3 wafv2 client) rather than HTTP mocks. No N/A overrides for the `sdk` branch. The N/A markings in this file's "## Applicable REQ-IDs" subsection apply only to the `artifact_path` (log-stream) branch.
