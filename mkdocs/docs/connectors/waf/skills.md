# WAF skills

Three skills cover the connector lifecycle for WAF sources. Each carries a WAF-specific reference; the procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source — WAF reference

Facts the analyze-source skill needs to write a complete Reference section for a WAF source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. WAF sources emit edge-event records treated as findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (for example sampled-request SDK calls); for log-stream consumption (the preferred mode), these are N/A.
- `REQ-TRF-STS` does not apply — WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form — deduplication is event-stream deduplication (replay-window) rather than cross-tool finding overlap.

The AWS WAF traceability row currently shows N/A across the matrix because the source is documented but not built in the MVP. The MVP-built profile would be the set above.

### Default severity

`medium`. Severity is not a first-class field on a WAF event; the canonical severity is **derived** from the action and rule-group category per a per-source lookup table — analogous to the secrets convention but data-driven from action+rule rather than fixed.

The Reference section's Enumerations fact MUST disclose the derivation rule (action + rule-group category → canonical severity) and list every documented action value.

### Incremental strategy

Timestamp-based high-water mark over the log stream. Per the WAF capability surface: the connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run.

For AWS deployments the reference pattern is **Firehose to S3** or **CloudWatch Logs into Bronze** via an autoloader-style ingestion. For on-prem appliances the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example `GetSampledRequests`) are supported as a fallback only — the WAF specification requires the connector to PREFER log-stream consumption over sampled SDK calls because samples lose fidelity under high-volume rules.

### Deduplication key

`(timestamp, rule_id, source_ip, request_id)` per the WAF capability surface, with the Silver event scope `(application_id, rule_id, timestamp)` per `mkdocs/docs/platform/reference/canonical-mapping.md`. Because WAF records are append-only event-shaped data rather than finding-shaped, dedup is replay-window deduplication on the unique tuple, not cross-tool overlap linking.

### Target Silver tables

`silver.waf_events` per the WAF capability surface. Application scoping is derived at transform time from the WebACL's associated resource ARNs (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments`. The Reference section MUST disclose this transform-time join.

### Authentication norms

Account-scoped, NOT per-tenant. Cloud-native WAFs (AWS WAF, Cloudflare, Azure Front Door WAF) authenticate via IAM role or access key bound to the cloud account hosting the WebACLs. On-prem appliances (F5 ASM, Imperva, ModSecurity) authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis.

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. For AWS WAF, autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern — this fits the Lakeflow Connect / SDK envelope. SDK-based sampled-request fallback is permitted only when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into Bronze for downstream extrapolation.

### Quirks

- **Event-shaped, not finding-shaped.** Each record describes a single request observed at the edge, not a triaged vulnerability. The Silver target is `silver.waf_events`, not `silver.findings`. The Reference section's Quirks fact MUST disclose this so generate-connector emits the right schema.
- **Severity is derived.** Severity comes from action + rule-group category, not from a source field. The lookup table is action-keyed, not severity-keyed.
- **Sampling weight.** Where the source returns statistical samples (sampled SDK calls), each record carries a sampling weight that MUST be preserved into Bronze for downstream extrapolation.
- **Application linkage via ARN.** Application scoping uses the WebACL's associated resource ARNs (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments` at transform time. The Reference section MUST capture the ARN field name in the Resource schema excerpt.
- **Append-only stream.** WAF events have no status lifecycle. `REQ-TRF-STS` is N/A. The Silver `status` field is left null.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The Reference section MUST list every action the source emits — this drives the severity-derivation lookup.
- **Log-stream over SDK.** Prefer log-stream consumption over sampled SDK calls; the Reference section's Quirks fact MUST disclose the chosen mode and justify any deviation.

*Rendered from `.claude/skills/analyze-source/references/waf.md`. Source-of-truth lives in the skill file.*

## generate-connector — WAF reference

Facts the generate-connector skill needs to emit a WAF connector module. WAF sources emit append-only edge-event records — event-shaped, not finding-shaped.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests`); for log-stream consumption (the preferred mode), they are N/A.
- Do NOT bind `REQ-TRF-STS` — WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form — the dedup is event-stream replay-window deduplication, not cross-tool finding overlap. Bind a single test asserting the replay-window behaviour.

### Default severity

`medium`. Severity is **derived**, not source-supplied — there is no `severity` field on a WAF event. The canonical severity is computed from `action` (block / allow / count / challenge / captcha) plus rule-group category.

The `src/connectors/{source}/severity.yml` lookup is therefore action-keyed, not severity-keyed. Generate the lookup with action-to-severity mappings covering every documented action value (e.g. `block: high`, `count: low`, `allow: low`, `challenge: medium`). The `mapping.yml` severity field references the lookup with `action` as the source path:

```yaml
severity:
  source_path: action
  lookup: src/connectors/{source}/severity.yml
```

The configurable default for unmatched actions is `medium` with a data-quality warning.

### Incremental strategy

Timestamp-based HWM over the log stream. Encode in `config.yml`:

- The connector records the last event-time ingested per WebACL or rule group and advances forward on each run.
- For AWS deployments: autoloader-style ingestion from a Firehose-to-S3 prefix or CloudWatch Logs export.
- For on-prem appliances: the same pattern over the forwarded syslog bucket.
- Sampled SDK calls (`GetSampledRequests`) are a **fallback only**. Prefer log-stream consumption — samples lose fidelity under high-volume rules. Where the fallback is used, preserve the statistical sampling weight (`Weight` field) into Bronze for downstream extrapolation.

### Deduplication key

Per canonical mapping: not currently specified for WAF — append-only event log; cross-tool overlap not yet defined. The `mkdocs/docs/platform/reference/canonical-mapping.md` does not list a dedup-key tuple for WAF in the current MVP scope.

For replay-window deduplication (within-source, recovering from re-delivered events), the WAF capability surface uses `(timestamp, rule_id, source_ip, request_id)` per the `analyze-source` WAF reference. Encode this tuple in `transform.py` for replay deduplication only:

```python
replay_dedup_key = (row["timestamp"], row["rule_id"], row["source_ip"], row["request_id"])
```

Do NOT emit `dedup_links` rows — the canonical `dedup_links` table targets cross-tool finding overlap, which WAF does not participate in. Cite `mkdocs/docs/platform/reference/canonical-mapping.md` in a transform-level comment to document the absence.

### Target Silver tables

`silver.waf_events` (plural) per `mkdocs/docs/platform/reference/silver-table-ownership.md` patterns and the WAF capability surface at `mkdocs/docs/connectors/waf/index.md`. The `mapping.yml` block targets `silver.waf_events`, NOT `silver.findings` — this is the headline schema deviation for WAF.

`transform.py` MUST emit a join against `silver.deployments` to resolve the WebACL's associated resource ARN (ALB, CloudFront distribution, API Gateway stage) into `application_id`. The ARN field is encoded in `mapping.yml` and the connector page Resource schema excerpt documents the field name.

### Authentication norms

Account-scoped, NOT per-tenant:

- **Cloud-native WAFs** (AWS WAF, Cloudflare, Azure Front Door WAF): IAM role or access key bound to the cloud account hosting the WebACLs.
- **On-prem appliances** (F5 ASM, Imperva, ModSecurity): service credential bound to the log-aggregation tier.

`ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names. There is no per-application authentication axis; do not generate one.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **AWS WAF**: autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern. This fits the Lakeflow Connect / SDK envelope.
- **SDK-based sampled-request fallback**: permitted only when full-log ingestion is not yet provisioned. Preserve the sampling weight into Bronze.
- The artefact-collection / autoloader pattern is the dominant WAF mode and aligns with Lakeflow Connect; no CLI-artefact deviation is needed.

### Quirks

- **Event-shaped, not finding-shaped.** Each record is a single edge observation, not a triaged vulnerability. The Silver target is `silver.waf_events`, NOT `silver.findings`. Emit the matching schema in `mapping.yml`; do not reuse the finding shape.
- **Severity is derived.** Action plus rule-group category drives canonical severity through the action-keyed lookup. Generate the lookup as action-keyed; do NOT generate a severity-keyed lookup that mirrors a source severity field (there is none).
- **Sampling weight preserved.** Where the source returns statistical samples, project the `Weight` field into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** WebACL ARN → `silver.deployments` join at transform time. Encode the ARN field name in `mapping.yml`; emit the join in `transform.py` (mirrors the DAST `target` join in shape).
- **Append-only stream.** No status lifecycle; do not project a `status` field; do not generate status-transition code. The `src/connectors/{source}/status.yml` lookup MUST exist (per the every-connector-has-both-files contract) and contain `# N/A — WAF events are append-only; no status lifecycle`.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The severity lookup MUST cover every action the source emits — exhaustive over the documented vocabulary.
- **Log-stream over SDK.** Prefer log-stream consumption. SDK sampled-request mode is fallback-only; document the deviation in a top-of-file comment in `ingest.py` if used.

*Rendered from `.claude/skills/generate-connector/references/waf.md`. Source-of-truth lives in the skill file.*

## validate-implementation — WAF reference

Facts the validate-implementation skill needs to populate the Validation table for a WAF connector. WAF sources emit append-only edge-event records — event-shaped, not finding-shaped. Status and dedup are N/A; severity is derived from action plus rule-group category.

### Applicable REQ-IDs

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

### Default severity

`medium` configurable default; severity is **derived** from `action` plus rule-group category, not source-supplied. Per `mkdocs/docs/connectors/waf/index.md` § "Capability surface": "Severity is not a first-class field on a WAF event; the canonical severity is derived from the action and rule-group category per a per-source lookup table." The `REQ-TRF-SEV` test asserts the action-keyed lookup covers every documented action (`block`, `allow`, `count`, `challenge`, `captcha`) and that undocumented actions fall through to `medium` with a data-quality warning.

### Incremental strategy

Timestamp-based HWM over the log stream per `mkdocs/docs/connectors/waf/index.md` § "Capability surface". The connector records the last event-time ingested per WebACL or rule group and advances forward each run. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the timestamp advancement; SDK-fallback mode preserves `Weight` and is also asserted under `REQ-ING-HWM` plus `REQ-TRF-MAP`.

### Deduplication key

Per `mkdocs/docs/platform/reference/canonical-mapping.md`: not currently specified for WAF — append-only event log; cross-tool overlap not yet defined in MVP scope. `REQ-DEDUP` is N/A.

For replay-window deduplication (within-source, recovering re-delivered events), the connector uses `(timestamp, rule_id, source_ip, request_id)` per `mkdocs/docs/connectors/waf/index.md` § "Capability surface" — but this is asserted under `REQ-DQ` (a Lakeflow expectation that quarantines duplicate replay events), NOT under `REQ-DEDUP`. The test suite does NOT emit `dedup_links` rows for WAF.

### Target Silver tables

`silver.waf_events` (plural) per the WAF capability surface at `mkdocs/docs/connectors/waf/index.md` and the WAF references in the analyze-source / generate-connector skills. The `REQ-TRF-MAP` test asserts the connector targets `silver.waf_events`, NOT `silver.findings` — this is the headline schema deviation for WAF. The `REQ-TRF-MAP` test additionally verifies the join against `silver.deployments` to resolve the WebACL ARN into `application_id`.

Note: `silver.waf_events` is not listed in `mkdocs/docs/platform/reference/silver-table-ownership.md` — that file enumerates the MVP-canonical tables, and WAF is documented but not built in the MVP. The plural name follows the pattern of every other entity table on that page (`applications`, `repositories`, `findings`).

### Authentication norms

Account-scoped, NOT per-tenant, per `mkdocs/docs/connectors/waf/index.md` § "Capability surface". Cloud-native WAFs use IAM role or access key; on-prem appliances use a service credential bound to the log-aggregation tier. The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. Autoloader-style ingestion from the Firehose-to-S3 prefix (AWS WAF) fits the Lakeflow Connect / SDK envelope; no CLI-artefact deviation is needed. The validation suite verifies pagination and rate-limit absence under the N/A markings rather than asserting a tool-choice fact directly.

### Quirks

- **Event-shaped, not finding-shaped.** `REQ-TRF-MAP` asserts the connector targets `silver.waf_events`, not `silver.findings`. The test fails if `silver.findings` rows are emitted.
- **Severity is derived.** `REQ-TRF-SEV` asserts the lookup is action-keyed, not severity-keyed. A severity-keyed lookup that mirrors a source severity field is a `FAIL`.
- **Sampling weight preserved.** Where the SDK sampled-request fallback is in use, `REQ-TRF-MAP` asserts the `Weight` field is projected into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** `REQ-TRF-MAP` asserts the WebACL ARN → `silver.deployments` join at transform time (mirrors the DAST `target` join in shape).
- **Append-only stream.** No status lifecycle; `REQ-TRF-STS` is N/A; no `status` field is projected. The `src/connectors/{source}/status.yml` lookup contains `# N/A — WAF events are append-only; no status lifecycle` per the generate-connector WAF reference.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. `REQ-TRF-SEV` asserts coverage over the full action vocabulary the source emits.
- **Log-stream over SDK.** `REQ-ING-PAG` and `REQ-ING-RL` are bound only when the SDK fallback is in use. Log-stream-only deployments mark them `N/A` with the rationale "log-stream mode has no API pagination/rate limit".

*Rendered from `.claude/skills/validate-implementation/references/waf.md`. Source-of-truth lives in the skill file.*
