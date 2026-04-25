# generate-connector — SCM reference

Facts the generate-connector skill needs to emit an SCM connector module. SCM sources are dual-role: entities (always) plus platform-native findings (where the platform hosts native scanners — Dependabot, code scanning, secret scanning).

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

- Always bind (entity role): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Bind only when the SCM source is configured as a finding-emitting integration (platform-native scanners — Dependabot, code scanning, secret scanning): `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`.
- Pure-entity SCM connectors (no platform-native findings consumed) MUST NOT bind the three finding-only REQ-IDs.

## Default severity

For the entity role: N/A — entity rows have no `severity` column.

For the finding role: derived from the platform's native field (`rule.security_severity_level` for GitHub code scanning, `severity` for GitLab) and normalized via `config/severity/{source}.yml` to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium`. The lookup file MUST cover every source value documented in the connector page.

## Incremental strategy

Three-option preference order; encode the chosen option in `config.yml`:

1. **Webhook / event-stream** (preferred where exposed). The connector materialises events into Bronze in near-real-time. Emit subscription configuration, not polling.
2. **Native `updated_at` (or equivalent) column** as the high-water mark, persisted via `src/platform/` HWM helpers.
3. **Full reload**, reserved for sources exposing neither.

The selected mode MUST match the connector page's Incremental hook fact.

## Deduplication key

For the entity role: not applicable. Entity dedup uses the natural-key column at Bronze-to-Silver upsert; no `dedup_links` rows are emitted.

For the finding role: encode the dedup-key tuple by finding shape (the source typically emits multiple shapes simultaneously):

- Code scanning (SAST shape): `(repository_id, file_path, rule_id)`.
- Secret scanning (secrets shape): `(repository_id, commit_sha, secret_type, file_path)`.
- Dependabot (SCA shape): `(repository_id, package_name, cve_id)`.

`transform.py` MUST branch on the finding-shape discriminator (the connector reads which scanner produced the row) and emit `dedup_links` rows keyed by the matching tuple. The Quirks section of the connector page identifies which shapes the source emits.

## Target Silver tables

Authoritative names per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- Entity role: `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. (`silver.commits` and `silver.teams` may also be populated where the source exposes them.)
- Finding role: `silver.findings` (single union table) discriminated by `category` per the matching scanner shape (`sast`, `sca`, `secrets`).

The `mapping.yml` file MUST contain TWO top-level blocks when the source emits both entities and findings:

```yaml
entities:
  # repository, pull_request, branch_policy field projections
findings:
  # platform-native finding field projections, discriminated by category
```

Pure-entity sources omit the `findings` block.

## Authentication norms

Personal access token (PAT) or OAuth. `ingest.py` reads credentials via `src/platform/` from the secret scope; `config.yml` references the secret-scope key names only. For OAuth deployments, encode the token-refresh callback in the helper, not inline.

## Ingestion-tooling preference

Per the standard order with one practical split:

- **Entities**: Lakeflow Connect first where a managed GitHub / GitLab connector exists; SDK / dlt fall back otherwise.
- **Findings**: Databricks SDK is the preferred path — GitHub and GitLab finding APIs (Dependabot alerts, code scanning alerts, secret scanning alerts) are SDK-covered and require finer pagination control than Lakeflow Connect typically exposes.

Justify the chosen tool with a one-line comment at the top of `ingest.py`.

## Quirks

- **Two `mapping.yml` blocks.** A single SCM source typically populates entity tables AND `silver.findings`. Emit two clearly delimited blocks; do NOT collapse them. Pure-entity sources emit only the entity block.
- **Plural Silver names are authoritative.** `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. Singular forms are wrong.
- **Cursor vs keyset pagination.** GraphQL APIs typically use cursor pagination; REST APIs may use keyset. Encode the pagination strategy per endpoint in `config.yml`; `src/platform/` exposes both helpers.
- **Webhook replay.** When webhook delivery is the chosen incremental hook, `config.yml` MUST also encode a fallback polling window (typically 24h) so missed deliveries are recovered on the next scheduled run.
- **Finding-shape branch.** `transform.py` MUST handle each shape (code-scanning, secret-scanning, Dependabot) with the matching dedup-key tuple. Mis-branching corrupts `dedup_links`.
