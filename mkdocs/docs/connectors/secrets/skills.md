# Secrets skills

Three skills cover the connector lifecycle for Secrets sources. Each carries a Secrets-specific reference; the procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source — Secrets reference

Facts the analyze-source skill needs to write a complete Reference section for a secret-detection source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Secrets sources emit findings but with reduced lifecycle metadata.

- Apply: `REQ-ING-HWM` (full-reload still has an HWM in the form of commit SHA or scan-start timestamp), `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Severity is conventional rather than data-driven: `REQ-TRF-SEV` applies in a degraded form (the lookup table maps detector classes to severity, defaulting to `high`).
- Do not apply: `REQ-TRF-STS` — secret-detection sources do not expose a status / lifecycle vocabulary; the canonical `validity_status` field is populated from the source's verification flag where available, but that is not a status transition graph.
- For CLI-based secret scanners (TruffleHog artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` are N/A — the catalog notes the CLI-artefact ingestion path "has no API auth, pagination, or rate limit." This matches the TruffleHog traceability row.

### Default severity

`high`. The specification maps every secret finding to `severity=high` by default; a per-deployment override at `config/severity/{source}.yml` is permitted for low-entropy detector classes (where false-positive rates are high enough to warrant a downgrade).

The Reference section's Enumerations fact MUST disclose that severity is conventional, not source-derived.

### Incremental strategy

Full-reload only. Per the secrets capability surface, secret-detection sources have no incremental hook; the dominant deployment style is CLI-based, collected from CI/CD pipeline artefacts. The HWM is the commit SHA (CI/CD-step) or scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning).

The Reference section's Incremental hook fact records the full-reload designation explicitly.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the canonical secrets scope.

Both per-commit (CI/CD-step) and host-side periodic-global secret scanning emit records labelled with `(repository_id, commit_sha)` so that Bronze-to-Silver deduplication unifies them without double-counting. The Reference section MUST capture both label sources where the platform supports them.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the code-level finding table). Secret-specific fields populated: `secret_type`, `validity_status` (where the source supports verification).

### Authentication norms

For server-based secret detection (rare): PAT or API-key based, like SAST. For CLI-based secret detection (the dominant style, including TruffleHog): no API auth — access is governed by the artefact store's IAM policy. The Reference section MUST disclose which path the source takes.

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. CLI-based secret scanners use the artefact-collection pattern (the documented exception to the preference order, alongside Semgrep Docker). The Reference section MUST justify the deviation if the CLI path is chosen.

### Quirks

- **Verification semantics.** Where the source supports live credential verification (TruffleHog `Verified` flag, GitHub Secret Scanning `validity`), the result populates the canonical `validity_status` field in Silver. The Reference section MUST disclose verification support and the field name.
- **No status transitions.** Secret findings do not have an open / resolved lifecycle in the source. The Silver `status` field is left null (or set to `open` on first emit) and `REQ-TRF-STS` does not apply.
- **CI/CD-step dominance.** Secret detection is almost exclusively CI/CD-step in practice; every commit is a potential leak. The Reference section's Incremental hook fact records the commit SHA as the operative HWM.
- **Periodic-global host-side scans.** Some platforms (GitHub Secret Scanning) also run periodic-global scans across repository history to catch historical leaks. Both outputs are labelled with `(repository_id, commit_sha)` so dedup unifies them.
- **Detector-class severity overrides.** The `config/severity/{source}.yml` lookup may downgrade specific detector classes (low-entropy patterns, deprecated detectors) below the default `high`. Document the policy in the Quirks fact.

*Rendered from `.claude/skills/analyze-source/references/secrets.md`. Source-of-truth lives in the skill file.*

## generate-connector — Secrets reference

Facts the generate-connector skill needs to emit a secret-detection connector module. Secrets sources emit findings with reduced lifecycle metadata.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM` (full-reload still has an HWM in the form of commit SHA / scan-start timestamp), `REQ-TRF-MAP`, `REQ-TRF-SEV` (degraded — see Default severity), `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Do NOT bind `REQ-TRF-STS` — secret-detection sources do not expose a status / lifecycle vocabulary. The generated `transform.py` MUST NOT include status-transition logic.
- For CLI-based scanners (TruffleHog artefacts — the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A per the catalog. Do NOT bind these three.

### Default severity

`high`, hard-coded. The `mapping.yml` finding block sets severity to a literal `high` constant — it does NOT reference a lookup-driven source field (this is the documented degraded form):

```yaml
severity:
  literal: high
```

The `config/severity/{source}.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# default high; per-deployment override permitted for low-entropy detector classes
```

The lookup is consulted only when an operator deploys a per-detector override; the default code path uses the literal `high` from `mapping.yml`.

### Incremental strategy

Full-reload only. Encode in `config.yml`:

- HWM is the commit SHA (CI/CD-step deployments — every commit is a potential leak) or the scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning).
- No record-level update column — the source has none.
- The HWM advances on each full pull; replays of historical scans re-emit the same `(repository_id, commit_sha)` rows for dedup-time unification.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["commit_sha"], row["secret_type"], row["file_path"])
```

Both per-commit (CI/CD-step) and host-side periodic-global secret scanning emit records labelled with `(repository_id, commit_sha)` — Bronze-to-Silver dedup unifies them on the four-tuple without double-counting.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "secrets"` literally and project the secret-specific fields:

- `secret_type` — the detector class label (TruffleHog `DetectorName`).
- `validity_status` — derived from the source's verification flag where present (TruffleHog `Verified` + `VerificationError`); null where the source does not verify.

The status field is NOT projected — secrets emit no lifecycle.

### Authentication norms

- **CLI-based** (the dominant style — TruffleHog, gitleaks): no API auth. Access is governed by the artefact bucket's IAM policy. `config.yml` encodes the bucket prefix; `ingest.py` uses the autoloader / cloud-storage helpers in `src/platform/`.
- **Server-based** (rare): PAT or API-key, as for SAST. `ingest.py` reads credentials via the helper in `src/platform/`.

The connector page identifies which path the source takes; emit the matching auth code (or its absence).

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **CLI-based secret scanners are the documented exception** (alongside Semgrep Docker per `CLAUDE.md`). Emit a CLI-artefact ingest path — autoloader-style on the object-storage prefix, or `httpx` against a cloud-storage API. Justify the deviation in a top-of-file comment in `ingest.py`.
- Server-based scanners use the SDK or dlt path.

### Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** For TruffleHog and similar scanners, drop the raw secret value before Bronze-to-Silver — keep only `Redacted`. This is mandatory, not configurable. Encode the projection in `mapping.yml` to exclude raw fields explicitly; an optional Unity Catalog column-level access policy on Bronze is the deployment-time enforcement.
- **Verification semantics.** Where the source supports live credential verification, populate `validity_status` from the verification flag in `mapping.yml`. Document the source field name (e.g. `Verified` for TruffleHog) in a transform-level comment.
- **No status transitions.** `REQ-TRF-STS` is N/A; do not generate status-transition code or status-lookup references. The Silver `status` field is left null (or set to `open` on first emit) — encode the constant in `mapping.yml`, NOT a lookup.
- **CI/CD-step dominance.** Secret detection is almost exclusively CI/CD-step in practice; the `config.yml` HWM shape is the commit SHA. Periodic-global host-side scans (GitHub Secret Scanning) use scan-start timestamp; both shapes co-exist on the four-tuple dedup key.
- **Detector-class severity overrides.** The optional `config/severity/{source}.yml` deployment override may downgrade specific detector classes (low-entropy patterns, deprecated detectors) below the default `high`. The override path is opt-in; the default code path uses the `mapping.yml` literal.

*Rendered from `.claude/skills/generate-connector/references/secrets.md`. Source-of-truth lives in the skill file.*

## validate-implementation — Secrets reference

Facts the validate-implementation skill needs to populate the Validation table for a secret-detection connector. Secrets sources emit findings with reduced lifecycle metadata; severity is conventional and status is N/A.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The TruffleHog column of the traceability matrix is the documented intended profile (the source is documented but not built in the MVP, so cells currently read `N/A` across the matrix; the MVP-built profile would be the set below).

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV` — degraded: severity is conventional (`high`), not data-driven from a source field
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-HWM` — N/A: full reload only. The secrets capability surface at `mkdocs/docs/connectors/secrets/index.md` § "Capability surface" states "Such tooling has no incremental hook and SHALL be treated under the full-reload strategy." There is no record-level update column to advance.
- `REQ-TRF-STS` — N/A: secret-detection sources do not expose a status / lifecycle vocabulary. No status transitions exist to normalize.

For CLI-based secret scanners (TruffleHog artefacts — the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are also N/A — quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this fuller N/A profile when validating a CLI-only connector.

Note the discrepancy with the task spec's summary table (which lists `HWM` under "applies"): the catalog matrix and the secrets capability surface are authoritative, and both treat full reload as having no record-level HWM. The plan's `REQ-ING-HWM` could be read as the commit-SHA / scan-start-timestamp HWM for full-reload bootstrapping; if the connector encodes a commit-SHA HWM in `config.yml`, bind a test asserting commit-SHA advancement and mark `REQ-ING-HWM` as `PASS`. Otherwise mark it `N/A` with the rationale above.

### Default severity

`high`, conventional. Per `mkdocs/docs/connectors/secrets/index.md` § "Capability surface": "The specification maps every secret finding to `severity=high` by default; a per-deployment override is permitted for low-entropy detector classes." The `REQ-TRF-SEV` test asserts the literal `high` constant in `mapping.yml` (or — when an override lookup is deployed — the override's severity coverage with the documented data-quality warning).

### Incremental strategy

Full reload per `mkdocs/docs/connectors/secrets/index.md` § "Capability surface". The HWM is the commit SHA (CI/CD-step) or scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning). The test suite either binds `REQ-ING-HWM` against commit-SHA advancement or marks it `N/A` per the discussion in Applicable REQ-IDs.

### Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/connectors/secrets/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Per-commit and host-side periodic scans both label records with `(repository_id, commit_sha)`; the dedup test verifies unification without double-counting.

### Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test verifies the discriminator literal alongside the secret-specific fields (`secret_type`, `validity_status`).

### Authentication norms

CLI-based (the dominant style): no API auth — access governed by the artefact bucket's IAM policy. Server-based (rare): PAT or API-key. The test suite binds `REQ-ING-AUTH` only when the connector takes the server-based path; CLI-only variants mark it `N/A`.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CLI-based secret scanners are the documented exception per `CLAUDE.md` ("Ingestion tooling preference order") alongside Semgrep Docker. The validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

### Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** `REQ-TRF-MAP` asserts that raw secret values are dropped before Bronze-to-Silver — the projection in `mapping.yml` excludes raw fields explicitly. The test fails if a raw field is present in Silver.
- **Verification semantics.** Where the source supports verification, `REQ-TRF-MAP` asserts that `validity_status` is populated from the source's verification flag (e.g. TruffleHog `Verified`). Sources without verification leave the field null.
- **No status transitions.** `REQ-TRF-STS` is N/A; no test is bound. The Silver `status` field is left null (or set to `open` on first emit) — this constant is asserted under `REQ-TRF-MAP`, not under the omitted `REQ-TRF-STS`.
- **CI/CD-step dominance.** The connector's HWM shape is the commit SHA in practice. The test suite reflects that in the `REQ-ING-HWM` (or its absence) per the discussion above.
- **Detector-class severity overrides.** When a per-deployment override at `config/severity/{source}.yml` is deployed, `REQ-TRF-SEV` asserts the override's coverage and the data-quality fallback. The default code path uses the `mapping.yml` literal `high` and asserts that constant.

*Rendered from `.claude/skills/validate-implementation/references/secrets.md`. Source-of-truth lives in the skill file.*
