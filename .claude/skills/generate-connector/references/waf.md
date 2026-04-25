# generate-connector — WAF reference

Facts the generate-connector skill needs to emit a WAF connector module. WAF sources emit append-only edge-event records — event-shaped, not finding-shaped.

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

- Bind: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests`); for log-stream consumption (the preferred mode), they are N/A.
- Do NOT bind `REQ-TRF-STS` — WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form — the dedup is event-stream replay-window deduplication, not cross-tool finding overlap. Bind a single test asserting the replay-window behaviour.

## Default severity

`medium`. Severity is **derived**, not source-supplied — there is no `severity` field on a WAF event. The canonical severity is computed from `action` (block / allow / count / challenge / captcha) plus rule-group category.

The `config/severity/{source}.yml` lookup is therefore action-keyed, not severity-keyed. Generate the lookup with action-to-severity mappings covering every documented action value (e.g. `block: high`, `count: low`, `allow: low`, `challenge: medium`). The `mapping.yml` severity field references the lookup with `action` as the source path:

```yaml
severity:
  source_path: action
  lookup: config/severity/{source}.yml
```

The configurable default for unmatched actions is `medium` with a data-quality warning.

## Incremental strategy

Timestamp-based HWM over the log stream. Encode in `config.yml`:

- The connector records the last event-time ingested per WebACL or rule group and advances forward on each run.
- For AWS deployments: autoloader-style ingestion from a Firehose-to-S3 prefix or CloudWatch Logs export.
- For on-prem appliances: the same pattern over the forwarded syslog bucket.
- Sampled SDK calls (`GetSampledRequests`) are a **fallback only**. Prefer log-stream consumption — samples lose fidelity under high-volume rules. Where the fallback is used, preserve the statistical sampling weight (`Weight` field) into Bronze for downstream extrapolation.

## Deduplication key

Per canonical mapping: not currently specified for WAF — append-only event log; cross-tool overlap not yet defined. The `mkdocs/docs/platform/reference/canonical-mapping.md` does not list a dedup-key tuple for WAF in the current MVP scope.

For replay-window deduplication (within-source, recovering from re-delivered events), the WAF capability surface uses `(timestamp, rule_id, source_ip, request_id)` per the `analyze-source` WAF reference. Encode this tuple in `transform.py` for replay deduplication only:

```python
replay_dedup_key = (row["timestamp"], row["rule_id"], row["source_ip"], row["request_id"])
```

Do NOT emit `dedup_links` rows — the canonical `dedup_links` table targets cross-tool finding overlap, which WAF does not participate in. Cite `mkdocs/docs/platform/reference/canonical-mapping.md` in a transform-level comment to document the absence.

## Target Silver tables

`silver.waf_events` (plural) per `mkdocs/docs/platform/reference/silver-table-ownership.md` patterns and the WAF capability surface at `mkdocs/docs/connectors/waf/index.md`. The `mapping.yml` block targets `silver.waf_events`, NOT `silver.findings` — this is the headline schema deviation for WAF.

`transform.py` MUST emit a join against `silver.deployments` to resolve the WebACL's associated resource ARN (ALB, CloudFront distribution, API Gateway stage) into `application_id`. The ARN field is encoded in `mapping.yml` and the connector page Resource schema excerpt documents the field name.

## Authentication norms

Account-scoped, NOT per-tenant:

- **Cloud-native WAFs** (AWS WAF, Cloudflare, Azure Front Door WAF): IAM role or access key bound to the cloud account hosting the WebACLs.
- **On-prem appliances** (F5 ASM, Imperva, ModSecurity): service credential bound to the log-aggregation tier.

`ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names. There is no per-application authentication axis; do not generate one.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **AWS WAF**: autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern. This fits the Lakeflow Connect / SDK envelope.
- **SDK-based sampled-request fallback**: permitted only when full-log ingestion is not yet provisioned. Preserve the sampling weight into Bronze.
- The artefact-collection / autoloader pattern is the dominant WAF mode and aligns with Lakeflow Connect; no CLI-artefact deviation is needed.

## Quirks

- **Event-shaped, not finding-shaped.** Each record is a single edge observation, not a triaged vulnerability. The Silver target is `silver.waf_events`, NOT `silver.findings`. Emit the matching schema in `mapping.yml`; do not reuse the finding shape.
- **Severity is derived.** Action plus rule-group category drives canonical severity through the action-keyed lookup. Generate the lookup as action-keyed; do NOT generate a severity-keyed lookup that mirrors a source severity field (there is none).
- **Sampling weight preserved.** Where the source returns statistical samples, project the `Weight` field into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** WebACL ARN → `silver.deployments` join at transform time. Encode the ARN field name in `mapping.yml`; emit the join in `transform.py` (mirrors the DAST `target` join in shape).
- **Append-only stream.** No status lifecycle; do not project a `status` field; do not generate status-transition code. The `config/status/{source}.yml` lookup MUST exist (per the every-connector-has-both-files contract) and contain `# N/A — WAF events are append-only; no status lifecycle`.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The severity lookup MUST cover every action the source emits — exhaustive over the documented vocabulary.
- **Log-stream over SDK.** Prefer log-stream consumption. SDK sampled-request mode is fallback-only; document the deviation in a top-of-file comment in `ingest.py` if used.
