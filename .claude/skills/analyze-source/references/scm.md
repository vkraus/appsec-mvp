# analyze-source — SCM reference

Facts the analyze-source skill needs to write a complete Reference section for an SCM source.

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

From `mkdocs/docs/platform/reference/catalog.md`. SCM sources are dual-role: they emit repository / pull-request / branch-policy entities AND, where the platform hosts native scanners (Dependabot, GitHub code scanning, GitHub Secret Scanning), they emit findings.

- Always apply (entity role): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Apply only when the SCM source is configured as a finding-emitting integration (platform-native scanners): `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`.

The traceability matrix's GitHub column shows the full set as `PASS` because the GitHub connector ingests both repositories and platform-native findings. A pure-entity SCM connector would mark severity, status, and dedup as N/A.

## Default severity

N/A for the entity role. For the finding role, severity comes from the platform's native field (`rule.security_severity_level` on GitHub code scanning, `severity` on GitLab) and is normalized to the canonical four-level model (`critical`, `high`, `medium`, `low`) via per-source lookup. The configurable default for unmatched values is `medium` per the canonical mapping.

## Incremental strategy

SCM connectors select from the three-option preference order documented in the SCM capability surface:

1. **Webhook or event-stream delivery** where exposed (preferred). The connector subscribes and materializes events into Bronze in near-real-time.
2. **Native `updated_at` (or equivalent) timestamp** as the high-water mark; persisted to the state table.
3. **Full reload**, reserved for sources exposing neither.

The per-source decision MUST be recorded in the Reference section's Incremental hook fact and reflected in the connector's `config.yml`.

## Deduplication key

For the entity role: not applicable.

For the finding role: the dedup key follows the finding shape — code-level findings (code scanning, secret scanning) reuse the SAST and secrets keys respectively; package-level findings (Dependabot) reuse the SCA key `(repository_id, package_name, cve_id)`. The Reference section's Quirks fact MUST disclose which finding shapes the source emits.

## Target Silver tables

Entity role: `silver.repository`, `silver.pull_request`, `silver.branch_policy` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`.

Finding role: `silver.findings` discriminated by `category` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the GitHub / GitLab platform table).

## Authentication norms

Personal access token (PAT) or OAuth per the SCM capability surface. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. GitHub and GitLab both expose REST and GraphQL surfaces; pick the SDK or dlt path matching the chosen surface and pagination style (cursor-based on GitHub, keyset on GitLab).

## Quirks

- **Dual-role.** A single SCM source can populate entity tables AND `silver.findings`. The Reference section MUST scope each endpoint set explicitly so generate-connector emits distinct mapping blocks.
- **Cursor vs keyset pagination.** GraphQL APIs typically use cursor pagination; REST APIs may use keyset. The Reference section's Pagination fact records the strategy per endpoint.
- **GraphQL availability.** Where a GraphQL surface is available it usually offers tighter field selection and incremental hooks; prefer it over REST for entity-heavy reads when the SDK supports it.
- **Webhook delivery.** Webhook-driven HWM is the preferred mode; the Reference section MUST document the event types subscribed and the replay strategy if the webhook delivery is missed.
- **Platform-native finding shapes.** Dependabot is package-level (SCA shape); code scanning is code-level (SAST shape); secret scanning is code-level secrets shape. The Reference section names the shapes in the Quirks fact.
