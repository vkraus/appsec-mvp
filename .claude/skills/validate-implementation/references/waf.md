# validate-implementation — WAF reference

Facts the validate-implementation skill needs to populate the Validation table for a WAF connector. WAF sources emit append-only edge-event records — event-shaped, not finding-shaped. Status and dedup are N/A; severity is derived from action plus rule-group category.

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
- `REQ-TRF-TS`
- `REQ-DQ`

Mark `N/A`:

- `REQ-ING-PAG` — N/A: log-stream consumption (the preferred mode per `mkdocs/docs/connectors/waf/index.md` § "Capability surface": "The connector specification SHALL prefer log-stream consumption over sampled SDK calls") has no API pagination. Apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests` fallback); otherwise mark `N/A` with the rationale "log-stream mode has no API pagination".
- `REQ-ING-RL` — N/A: same rationale; log-stream consumption has no API rate limit. Apply only when the SDK fallback is in use.
- `REQ-TRF-STS` — N/A: WAF events are append-only block / allow / count records with no lifecycle state. Quoted from `mkdocs/docs/connectors/waf/index.md` § "Capability surface": WAF events are an "append-only" edge-event stream.
- `REQ-DEDUP` — N/A in the canonical sense: append-only event stream with no cross-tool overlap. The `mkdocs/docs/platform/reference/canonical-mapping.md` does not list a `dedup_links` tuple for WAF in the current MVP scope. Replay-window deduplication on `(timestamp, rule_id, source_ip, request_id)` is internal to the connector and is asserted under `REQ-DQ`, not `REQ-DEDUP`.

## Default severity

`medium` configurable default; severity is **derived** from `action` plus rule-group category, not source-supplied. Per `mkdocs/docs/connectors/waf/index.md` § "Capability surface": "Severity is not a first-class field on a WAF event; the canonical severity is derived from the action and rule-group category per a per-source lookup table." The `REQ-TRF-SEV` test asserts the action-keyed lookup covers every documented action (`block`, `allow`, `count`, `challenge`, `captcha`) and that undocumented actions fall through to `medium` with a data-quality warning.

## Incremental strategy

Timestamp-based HWM over the log stream per `mkdocs/docs/connectors/waf/index.md` § "Capability surface". The connector records the last event-time ingested per WebACL or rule group and advances forward each run. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the timestamp advancement; SDK-fallback mode preserves `Weight` and is also asserted under `REQ-ING-HWM` plus `REQ-TRF-MAP`.

## Deduplication key

Per `mkdocs/docs/platform/reference/canonical-mapping.md`: not currently specified for WAF — append-only event log; cross-tool overlap not yet defined in MVP scope. `REQ-DEDUP` is N/A.

For replay-window deduplication (within-source, recovering re-delivered events), the connector uses `(timestamp, rule_id, source_ip, request_id)` per `mkdocs/docs/connectors/waf/index.md` § "Capability surface" — but this is asserted under `REQ-DQ` (a Lakeflow expectation that quarantines duplicate replay events), NOT under `REQ-DEDUP`. The test suite does NOT emit `dedup_links` rows for WAF.

## Target Silver tables

`silver.waf_events` (plural) per the WAF capability surface at `mkdocs/docs/connectors/waf/index.md` and the WAF references in the analyze-source / generate-connector skills. The `REQ-TRF-MAP` test asserts the connector targets `silver.waf_events`, NOT `silver.findings` — this is the headline schema deviation for WAF. The `REQ-TRF-MAP` test additionally verifies the join against `silver.deployments` to resolve the WebACL ARN into `application_id`.

Note: `silver.waf_events` is not listed in `mkdocs/docs/platform/reference/silver-table-ownership.md` — that file enumerates the MVP-canonical tables, and WAF is documented but not built in the MVP. The plural name follows the pattern of every other entity table on that page (`applications`, `repositories`, `findings`).

## Authentication norms

Account-scoped, NOT per-tenant, per `mkdocs/docs/connectors/waf/index.md` § "Capability surface". Cloud-native WAFs use IAM role or access key; on-prem appliances use a service credential bound to the log-aggregation tier. The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. Autoloader-style ingestion from the Firehose-to-S3 prefix (AWS WAF) fits the Lakeflow Connect / SDK envelope; no CLI-artefact deviation is needed. The validation suite verifies pagination and rate-limit absence under the N/A markings rather than asserting a tool-choice fact directly.

## Quirks

- **Event-shaped, not finding-shaped.** `REQ-TRF-MAP` asserts the connector targets `silver.waf_events`, not `silver.findings`. The test fails if `silver.findings` rows are emitted.
- **Severity is derived.** `REQ-TRF-SEV` asserts the lookup is action-keyed, not severity-keyed. A severity-keyed lookup that mirrors a source severity field is a `FAIL`.
- **Sampling weight preserved.** Where the SDK sampled-request fallback is in use, `REQ-TRF-MAP` asserts the `Weight` field is projected into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** `REQ-TRF-MAP` asserts the WebACL ARN → `silver.deployments` join at transform time (mirrors the DAST `target` join in shape).
- **Append-only stream.** No status lifecycle; `REQ-TRF-STS` is N/A; no `status` field is projected. The `config/status/{source}.yml` lookup contains `# N/A — WAF events are append-only; no status lifecycle` per the generate-connector WAF reference.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. `REQ-TRF-SEV` asserts coverage over the full action vocabulary the source emits.
- **Log-stream over SDK.** `REQ-ING-PAG` and `REQ-ING-RL` are bound only when the SDK fallback is in use. Log-stream-only deployments mark them `N/A` with the rationale "log-stream mode has no API pagination/rate limit".

## sdk-branch validation note

Sources on the `sdk` branch (per `databricks_runtime.ingestion_path == sdk` + `python_sdk_module`, e.g. AWS WAF on boto3 sampled-request mode) keep `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM` PASS — the framework concerns are still exercised, but via library mocks (e.g. `MagicMock` on the boto3 wafv2 client) rather than HTTP mocks. No N/A overrides for the `sdk` branch. The N/A markings in this file's "## Applicable REQ-IDs" subsection apply only to the `artifact_path` (log-stream) branch.
