# Secrets skills

Three skills cover the connector lifecycle for Secrets sources. Each carries a reference specific to Secrets. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: Secrets reference

Facts the analyze-source skill needs to write a complete Reference section for a secret detection source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Secrets sources emit findings but with reduced lifecycle metadata.

- Apply: `REQ-ING-HWM` (full reload still has an HWM in the form of commit SHA or scan start timestamp), `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Severity is conventional rather than data driven. `REQ-TRF-SEV` applies in a degraded form (the lookup table maps detector classes to severity, defaulting to `high`).
- Do not apply: `REQ-TRF-STS`. Secret detection sources do not expose a status or lifecycle vocabulary. The documented `validity_status` field is populated from the verification flag of the source where available, but that is not a status transition graph.
- For CLI-based secret scanners (TruffleHog artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` are N/A. The catalog notes the CLI artefact ingestion path "has no API auth, pagination, or rate limit." This matches the TruffleHog traceability row.

### Default severity

`high`. The specification maps every secret finding to `severity=high` by default. A deployment level override at `src/connectors/{source}/severity.yml` is permitted for detector classes with low entropy (where false positive rates are high enough to warrant a downgrade).

The Enumerations fact in the Reference section MUST disclose that severity is conventional, not derived from the source.

### Incremental strategy

Full reload only. Per the capability scope for secrets, secret detection sources have no incremental hook. The dominant deployment style is CLI-based, collected from CI/CD pipeline artefacts. The HWM is the commit SHA (CI/CD step) or scan start timestamp (periodic global host side scans like GitHub Secret Scanning).

The Incremental hook fact in the Reference section records the full reload designation explicitly.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the documented secrets scope.

Both commit level (CI/CD step) and host side periodic global secret scanning emit records labelled with `(repository_id, commit_sha)` so that Bronze to Silver deduplication unifies them without double counting. The Reference section MUST capture both label sources where the platform supports them.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the finding table at code level). Secret-specific fields populated: `secret_type`, `validity_status` (where the source supports verification).

### Authentication norms

For server-based secret detection (rare): PAT or API key based, like SAST. For CLI-based secret detection (the dominant style, including TruffleHog): no API auth. Access is governed by the IAM policy of the artefact store. The Reference section MUST disclose which path the source takes.

### Ingestion tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. CLI-based secret scanners use the artefact collection pattern (the documented exception to the preference order, alongside Semgrep Docker). The Reference section MUST justify the deviation if the CLI path is chosen.

### Quirks

- **Verification semantics.** Where the source supports live credential verification (TruffleHog `Verified` flag, GitHub Secret Scanning `validity`), the result populates the documented `validity_status` field in Silver. The Reference section MUST disclose verification support and the field name.
- **No status transitions.** Secret findings do not have an open or resolved lifecycle in the source. The Silver `status` field is left null (or set to `open` on first emit) and `REQ-TRF-STS` does not apply.
- **CI/CD step dominance.** Secret detection is almost exclusively CI/CD step in practice. Every commit is a potential leak. The Incremental hook fact in the Reference section records the commit SHA as the operative HWM.
- **Periodic global host side scans.** Some platforms (GitHub Secret Scanning) also run periodic global scans across repository history to catch historical leaks. Both outputs are labelled with `(repository_id, commit_sha)` so dedup unifies them.
- **Detector class severity overrides.** The `src/connectors/{source}/severity.yml` lookup may downgrade specific detector classes (low entropy patterns, deprecated detectors) below the default `high`. Document the policy in the Quirks fact.

*Rendered from `.claude/skills/analyze-source/references/secrets.md`. Source of truth lives in the skill file.*

## generate-connector: Secrets reference

Facts the generate-connector skill needs to emit a secret detection connector module. Secrets sources emit findings with reduced lifecycle metadata.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM` (full reload still has an HWM in the form of commit SHA or scan start timestamp), `REQ-TRF-MAP`, `REQ-TRF-SEV` (degraded, see Default severity), `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Do NOT bind `REQ-TRF-STS`. Secret detection sources do not expose a status or lifecycle vocabulary. The generated `transform.py` MUST NOT include status transition logic.
- For CLI-based scanners (TruffleHog artefacts, the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A per the catalog. Do NOT bind these three.

### Default severity

`high`, hard coded. The `mapping.yml` finding block sets severity to a literal `high` constant. It does NOT reference a lookup driven source field (this is the documented degraded form):

```yaml
severity:
  literal: high
```

The `src/connectors/{source}/severity.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# default high; per-deployment override permitted for low-entropy detector classes
```

The lookup is consulted only when an user deploys a detector level override. The default code path uses the literal `high` from `mapping.yml`.

### Incremental strategy

Full reload only. Encode in `config.yml`:

- HWM is the commit SHA (CI/CD step deployments, every commit is a potential leak) or the scan start timestamp (periodic global host side scans like GitHub Secret Scanning).
- No record level update column. The source has none.
- The HWM advances on each full pull. Replays of historical scans re-emit the same `(repository_id, commit_sha)` rows for unification at dedup time.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["commit_sha"], row["secret_type"], row["file_path"])
```

Both commit level (CI/CD step) and host side periodic global secret scanning emit records labelled with `(repository_id, commit_sha)`. Bronze to Silver dedup unifies them on the four tuple without double counting.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "secrets"` literally and project the secret-specific fields:

- `secret_type`. The detector class label (TruffleHog `DetectorName`).
- `validity_status`. Derived from the source verification flag where present (TruffleHog `Verified` + `VerificationError`). Null where the source does not verify.

The status field is NOT projected. Secrets emit no lifecycle.

### Authentication norms

- **CLI-based** (the dominant style: TruffleHog, gitleaks): no API auth. Access is governed by the IAM policy of the artefact bucket. `config.yml` encodes the bucket prefix. `ingest.py` uses the autoloader and cloud storage helpers in `src/platform/`.
- **Server-based** (rare): PAT or API key, as for SAST. `ingest.py` reads credentials via the helper in `src/platform/`.

The connector page identifies which path the source takes. Emit the matching auth code (or its absence).

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt.

- **CLI-based secret scanners are the documented exception** (alongside Semgrep Docker per `CLAUDE.md`). Emit a CLI artefact ingest path. Autoloader-style on the object storage prefix, or `httpx` against a cloud storage API. Justify the deviation in a comment at the top of the file in `ingest.py`.
- Server-based scanners use the SDK or dlt path.

### Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** For TruffleHog and similar scanners, drop the raw secret value before Bronze to Silver. Keep only `Redacted`. This is mandatory, not configurable. Encode the projection in `mapping.yml` to exclude raw fields explicitly. An optional Unity Catalog column level access policy on Bronze is the deployment time enforcement.
- **Verification semantics.** Where the source supports live credential verification, populate `validity_status` from the verification flag in `mapping.yml`. Document the source field name (e.g. `Verified` for TruffleHog) in a transform level comment.
- **No status transitions.** `REQ-TRF-STS` is N/A. Do not generate status transition code or status lookup references. The Silver `status` field is left null (or set to `open` on first emit). Encode the constant in `mapping.yml`, NOT a lookup.
- **CI/CD step dominance.** Secret detection is almost exclusively CI/CD step in practice. The HWM structure in `config.yml` is the commit SHA. Periodic global host side scans (GitHub Secret Scanning) use scan start timestamp. Both structures coexist on the four tuple dedup key.
- **Detector class severity overrides.** The optional `src/connectors/{source}/severity.yml` deployment override may downgrade specific detector classes (low entropy patterns, deprecated detectors) below the default `high`. The override path is opt-in. The default code path uses the literal in `mapping.yml`.

*Rendered from `.claude/skills/generate-connector/references/secrets.md`. Source of truth lives in the skill file.*

## validate-implementation: Secrets reference

Facts the validate-implementation skill needs to populate the Validation table for a secret detection connector. Secrets sources emit findings with reduced lifecycle metadata. Severity is conventional and status is N/A.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The TruffleHog column of the traceability matrix is the documented intended profile (the source is documented but not built in the MVP, so cells currently read `N/A` across the matrix. The MVP-built profile would be the set below).

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`. Degraded: severity is conventional (`high`), not data driven from a source field.
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-HWM`. N/A: full reload only. The capability scope for secrets at `mkdocs/docs/connectors/secrets/index.md` § "Capability scope" states "Such tooling has no incremental hook and SHALL be treated under the full-reload strategy." There is no record level update column to advance.
- `REQ-TRF-STS`. N/A: secret detection sources do not expose a status or lifecycle vocabulary. No status transitions exist to normalize.

For CLI-based secret scanners (TruffleHog artefacts, the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are also N/A. Quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this fuller N/A profile when validating a CLI-only connector.

Note the discrepancy with the summary table in the task spec (which lists `HWM` under "applies"). The catalog matrix and the secrets capability scope are authoritative, and both treat full reload as having no record level HWM. The `REQ-ING-HWM` from the plan could be read as the commit SHA or scan start timestamp HWM for full reload bootstrapping. If the connector encodes a commit SHA HWM in `config.yml`, bind a test asserting commit SHA advancement and mark `REQ-ING-HWM` as `PASS`. Otherwise mark it `N/A` with the rationale above.

### Default severity

`high`, conventional. Per `mkdocs/docs/connectors/secrets/index.md` § "Capability scope": "The specification maps every secret finding to `severity=high` by default; a per-deployment override is permitted for low-entropy detector classes." The `REQ-TRF-SEV` test asserts the literal `high` constant in `mapping.yml` (or, when an override lookup is deployed, the severity coverage of the override with the documented data quality warning).

### Incremental strategy

Full reload per `mkdocs/docs/connectors/secrets/index.md` § "Capability scope". The HWM is the commit SHA (CI/CD step) or scan start timestamp (periodic global host side scans like GitHub Secret Scanning). The test suite either binds `REQ-ING-HWM` against commit SHA advancement or marks it `N/A` per the discussion in Applicable REQ-IDs.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/connectors/secrets/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Commit level and host side periodic scans both label records with `(repository_id, commit_sha)`. The dedup test verifies unification without double counting.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test verifies the discriminator literal alongside the secret-specific fields (`secret_type`, `validity_status`).

### Authentication norms

CLI-based (the dominant style): no API auth. Access governed by the IAM policy of the artefact bucket. Server-based (rare): PAT or API key. The test suite binds `REQ-ING-AUTH` only when the connector takes the server-based path. CLI-only variants mark it `N/A`.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt. CLI-based secret scanners are the documented exception per `CLAUDE.md` ("Ingestion tooling preference order") alongside Semgrep Docker. The validation suite verifies the deviation through the absence of the auth, pagination, and RL tests rather than asserting a tool choice fact directly.

### Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** `REQ-TRF-MAP` asserts that raw secret values are dropped before Bronze to Silver. The projection in `mapping.yml` excludes raw fields explicitly. The test fails if a raw field is present in Silver.
- **Verification semantics.** Where the source supports verification, `REQ-TRF-MAP` asserts that `validity_status` is populated from the verification flag of the source (e.g. TruffleHog `Verified`). Sources without verification leave the field null.
- **No status transitions.** `REQ-TRF-STS` is N/A. No test is bound. The Silver `status` field is left null (or set to `open` on first emit). This constant is asserted under `REQ-TRF-MAP`, not under the omitted `REQ-TRF-STS`.
- **CI/CD step dominance.** The HWM structure of the connector is the commit SHA in practice. The test suite reflects that in `REQ-ING-HWM` (or its absence) per the discussion above.
- **Detector class severity overrides.** When a deployment level override at `src/connectors/{source}/severity.yml` is deployed, `REQ-TRF-SEV` asserts the coverage of the override and the data quality fallback. The default code path uses the `mapping.yml` literal `high` and asserts that constant.

*Rendered from `.claude/skills/validate-implementation/references/secrets.md`. Source of truth lives in the skill file.*
