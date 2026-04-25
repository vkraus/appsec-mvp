# SCM skills

Three skills cover the connector lifecycle for SCM sources. Each carries an SCM specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: SCM reference

Facts the analyze-source skill needs to write a complete Reference section for an SCM source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SCM sources are dual role. They emit repository / pull request / branch policy entities AND, where the platform hosts native scanners (Dependabot, GitHub code scanning, GitHub Secret Scanning), they emit findings.

- Always apply (entity role): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Apply only when the SCM source is configured as a finding emitting integration (platform native scanners): `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`.

The GitHub column of the traceability matrix shows the full set as `PASS` because the GitHub connector ingests both repositories and platform native findings. A pure entity SCM connector would mark severity, status, and dedup as N/A.

### Default severity

N/A for the entity role. For the finding role, severity comes from the native field of the platform (`rule.security_severity_level` on GitHub code scanning, `severity` on GitLab) and is normalized to the standard four level model (`critical`, `high`, `medium`, `low`) via lookup for each source. The configurable default for unmatched values is `medium` per the standard mapping.

### Incremental strategy

SCM connectors select from the three option preference order documented in the SCM capability contract:

1. **Webhook or event stream delivery** where exposed (preferred). The connector subscribes and materializes events into Bronze in near real time.
2. **Native `updated_at` (or equivalent) timestamp** as the high water mark, persisted to the state table.
3. **Full reload**, reserved for sources exposing neither.

The decision for each source MUST be recorded in the Incremental hook fact in the Reference section and reflected in the `config.yml` for the connector.

### Deduplication key

For the entity role: not applicable.

For the finding role: the dedup key follows the finding structure. Code level findings (code scanning, secret scanning) reuse the SAST and secrets keys respectively. Package level findings (Dependabot) reuse the SCA key `(repository_id, package_name, cve_id)`. The Quirks fact in the Reference section MUST disclose which finding structures the source emits.

### Target Silver tables

Entity role: `silver.repositories`, `silver.pull_requests`, `silver.branch_policies` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`.

Finding role: `silver.findings` discriminated by `category` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the GitHub / GitLab platform table).

### Authentication norms

Personal access token (PAT) or OAuth per the SCM capability contract. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion tooling preference

Standard preference order applies: Lakeflow Connect, then Databricks SDK, then dlt. GitHub and GitLab both expose REST and GraphQL APIs. Pick the SDK or dlt path matching the chosen API and pagination style (cursor based on GitHub, keyset on GitLab).

### Quirks

- **Dual role.** A single SCM source can populate entity tables AND `silver.findings`. The Reference section MUST scope each endpoint set explicitly so generate-connector emits distinct mapping blocks.
- **Cursor vs keyset pagination.** GraphQL APIs typically use cursor pagination. REST APIs may use keyset. The Pagination fact in the Reference section records the strategy per endpoint.
- **GraphQL availability.** Where a GraphQL API is available it usually offers tighter field selection and incremental hooks. Prefer it over REST for entity heavy reads when the SDK supports it.
- **Webhook delivery.** Webhook driven HWM is the preferred mode. The Reference section MUST document the event types subscribed and the replay strategy if the webhook delivery is missed.
- **Platform native finding structures.** Dependabot is package level (SCA structure). Code scanning is code level (SAST structure). Secret scanning is code level secrets structure. The Reference section names the structures in the Quirks fact.

*Rendered from `.claude/skills/analyze-source/references/scm.md`. Source of truth lives in the skill file.*

## generate-connector: SCM reference

Facts the generate-connector skill needs to emit an SCM connector module. SCM sources are dual role: entities (always) plus platform native findings (where the platform hosts native scanners such as Dependabot, code scanning, secret scanning).

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Always bind (entity role): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Bind only when the SCM source is configured as a finding emitting integration (platform native scanners such as Dependabot, code scanning, secret scanning): `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`.
- Pure entity SCM connectors (no platform native findings consumed) MUST NOT bind the three finding only REQ-IDs.

### Default severity

For the entity role: N/A. Entity rows have no `severity` column.

For the finding role: derived from the native field of the platform (`rule.security_severity_level` for GitHub code scanning, `severity` for GitLab) and normalized via `src/connectors/{source}/severity.yml` to the standard four level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium`. The lookup file MUST cover every source value documented in the connector page.

### Incremental strategy

Three option preference order. Encode the chosen option in `config.yml`:

1. **Webhook / event stream** (preferred where exposed). The connector materialises events into Bronze in near real time. Emit subscription configuration, not polling.
2. **Native `updated_at` (or equivalent) column** as the high water mark, persisted via `src/platform/` HWM helpers.
3. **Full reload**, reserved for sources exposing neither.

The selected mode MUST match the Incremental hook fact on the connector page.

### Deduplication key

For the entity role: not applicable. Entity dedup uses the natural key column at Bronze to Silver upsert. No `dedup_links` rows are emitted.

For the finding role: encode the dedup key tuple by finding structure (the source typically emits multiple structures simultaneously):

- Code scanning (SAST structure): `(repository_id, file_path, rule_id)`.
- Secret scanning (secrets structure): `(repository_id, commit_sha, secret_type, file_path)`.
- Dependabot (SCA structure): `(repository_id, package_name, cve_id)`.

`transform.py` MUST branch on the finding structure discriminator (the connector reads which scanner produced the row) and emit `dedup_links` rows keyed by the matching tuple. The Quirks section of the connector page identifies which structures the source emits.

### Target Silver tables

Authoritative names per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- Entity role: `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. (`silver.commits` and `silver.teams` may also be populated where the source exposes them.)
- Finding role: `silver.findings` (single union table) discriminated by `category` per the matching scanner structure (`sast`, `sca`, `secrets`).

The `mapping.yml` file MUST contain TWO top level blocks when the source emits both entities and findings:

```yaml
entities:
  # repository, pull_request, branch_policy field projections
findings:
  # platform-native finding field projections, discriminated by category
```

Pure entity sources omit the `findings` block.

### Authentication norms

Personal access token (PAT) or OAuth. `ingest.py` reads credentials via `src/platform/` from the secret scope. `config.yml` references the secret scope key names only. For OAuth deployments, encode the token refresh callback in the helper, not inline.

### Ingestion tooling preference

Per the standard order with one practical split:

- **Entities**: Lakeflow Connect first where a managed GitHub / GitLab connector exists. SDK / dlt fall back otherwise.
- **Findings**: Databricks SDK is the preferred path. GitHub and GitLab finding APIs (Dependabot alerts, code scanning alerts, secret scanning alerts) are SDK covered and require finer pagination control than Lakeflow Connect typically exposes.

Justify the chosen tool with a one line comment at the top of `ingest.py`.

### Quirks

- **Two `mapping.yml` blocks.** A single SCM source typically populates entity tables AND `silver.findings`. Emit two clearly delimited blocks. Do NOT collapse them. Pure entity sources emit only the entity block.
- **Plural Silver names are authoritative.** `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. Singular forms are wrong.
- **Cursor vs keyset pagination.** GraphQL APIs typically use cursor pagination. REST APIs may use keyset. Encode the pagination strategy per endpoint in `config.yml`. `src/platform/` exposes both helpers.
- **Webhook replay.** When webhook delivery is the chosen incremental hook, `config.yml` MUST also encode a fallback polling window (typically 24h) so missed deliveries are recovered on the next scheduled run.
- **Finding structure branch.** `transform.py` MUST handle each structure (code scanning, secret scanning, Dependabot) with the matching dedup key tuple. Mis-branching corrupts `dedup_links`.

*Rendered from `.claude/skills/generate-connector/references/scm.md`. Source of truth lives in the skill file.*

## validate-implementation: SCM reference

Facts the validate-implementation skill needs to populate the Validation table for an SCM connector. SCM sources are dual role: entities (always) plus platform native findings (where the platform hosts native scanners). All ten REQ-IDs apply.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The GitHub column of the traceability matrix is the authoritative row for this category. Every cell is `PASS`.

Apply (all ten. The test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

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

Mark `N/A`: none.

For pure entity SCM sources (no platform native findings consumed), the three finding only REQ-IDs (`REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`) do not bind to entity structure tests, but the reference SCM connector (GitHub) consumes platform native findings (Dependabot, code scanning, secret scanning), so the full ten apply. If validating a pure entity variant, mark the finding only REQ-IDs `N/A` with the rationale "pure entity SCM source. No platform native findings consumed".

### Default severity

For the finding role: `medium` configurable default per `mkdocs/docs/connectors/scm/index.md` § "Capability surface" (inherits the generic lookup model for each tool). The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering every documented source value (e.g. `low`, `medium`, `high`, `critical` for GitHub code scanning).

For the entity role: N/A. Entity rows have no `severity` column.

### Incremental strategy

Three option preference order per `mkdocs/docs/connectors/scm/index.md` § "Capability surface": webhook, then native `updated_at`, then full reload. The test suite asserts HWM resume bound to `REQ-ING-HWM` against whichever mode the connector selected. Webhook deployments additionally assert the fallback polling window.

### Deduplication key

Per finding structure, per `mkdocs/docs/connectors/scm/index.md`: code scanning `(repository_id, file_path, rule_id)`; secret scanning `(repository_id, commit_sha, secret_type, file_path)`; Dependabot `(repository_id, package_name, cve_id)`. The test suite asserts `dedup_links` linkage in `test_dedup_links` per structure, bound to `REQ-DEDUP`. Mis-branching across structures is itself a `FAIL`.

### Target Silver tables

Authoritative per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- Entity role: `silver.repositories`, `silver.pull_requests`, `silver.branch_policies` (also `silver.commits` and `silver.teams` where the source exposes them).
- Finding role: `silver.findings` discriminated by `category` (`sast`, `sca`, `secrets`).

The `REQ-TRF-MAP` assertions in the test suite cover both blocks of `mapping.yml` (entities and findings).

### Authentication norms

PAT or OAuth per `mkdocs/docs/connectors/scm/index.md` § "Capability surface". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

### Ingestion tooling preference

Per the standard order with the practical split documented in the generate-connector SCM reference: Lakeflow Connect for entities; Databricks SDK for findings. The test suite indirectly verifies the pagination and rate limit behaviour of the chosen tool through `REQ-ING-PAG` and `REQ-ING-RL`.

### Quirks

- **Two `mapping.yml` blocks.** Entity and finding blocks are tested separately. `REQ-TRF-MAP` covers both. The dual structure coverage is mandatory for finding emitting SCM sources.
- **Plural Silver names are authoritative.** `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. Tests assert against the plural names.
- **Cursor vs keyset pagination.** GraphQL cursor pagination and REST keyset pagination are both exercised by `REQ-ING-PAG` per endpoint. The test suite covers each style the source uses.
- **Webhook replay.** Webhook mode connectors include a fallback polling window assertion under `REQ-ING-HWM`.
- **Finding structure branch.** The `REQ-DEDUP` test exercises every emitted structure (code scanning, secret scanning, Dependabot). Mis-branched dedup keys are flagged as `FAIL`.

*Rendered from `.claude/skills/validate-implementation/references/scm.md`. Source of truth lives in the skill file.*
