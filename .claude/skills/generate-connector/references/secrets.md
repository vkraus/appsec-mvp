# generate-connector — Secrets reference

Facts the generate-connector skill needs to emit a secret-detection connector module. Secrets sources emit findings with reduced lifecycle metadata.

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

- Bind: `REQ-ING-HWM` (full-reload still has an HWM in the form of commit SHA / scan-start timestamp), `REQ-TRF-MAP`, `REQ-TRF-SEV` (degraded — see Default severity), `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Do NOT bind `REQ-TRF-STS` — secret-detection sources do not expose a status / lifecycle vocabulary. The generated `transform.py` MUST NOT include status-transition logic.
- For CLI-based scanners (TruffleHog artefacts — the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A per the catalog. Do NOT bind these three.

## Default severity

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

## Incremental strategy

Full-reload only. Encode in `config.yml`:

- HWM is the commit SHA (CI/CD-step deployments — every commit is a potential leak) or the scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning).
- No record-level update column — the source has none.
- The HWM advances on each full pull; replays of historical scans re-emit the same `(repository_id, commit_sha)` rows for dedup-time unification.

## Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["commit_sha"], row["secret_type"], row["file_path"])
```

Both per-commit (CI/CD-step) and host-side periodic-global secret scanning emit records labelled with `(repository_id, commit_sha)` — Bronze-to-Silver dedup unifies them on the four-tuple without double-counting.

## Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "secrets"` literally and project the secret-specific fields:

- `secret_type` — the detector class label (TruffleHog `DetectorName`).
- `validity_status` — derived from the source's verification flag where present (TruffleHog `Verified` + `VerificationError`); null where the source does not verify.

The status field is NOT projected — secrets emit no lifecycle.

## Authentication norms

- **CLI-based** (the dominant style — TruffleHog, gitleaks): no API auth. Access is governed by the artefact bucket's IAM policy. `config.yml` encodes the bucket prefix; `ingest.py` uses the autoloader / cloud-storage helpers in `src/platform/`.
- **Server-based** (rare): PAT or API-key, as for SAST. `ingest.py` reads credentials via the helper in `src/platform/`.

The connector page identifies which path the source takes; emit the matching auth code (or its absence).

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **CLI-based secret scanners are the documented exception** (alongside Semgrep Docker per `CLAUDE.md`). Emit a CLI-artefact ingest path — autoloader-style on the object-storage prefix, or `httpx` against a cloud-storage API. Justify the deviation in a top-of-file comment in `ingest.py`.
- Server-based scanners use the SDK or dlt path.

## Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** For TruffleHog and similar scanners, drop the raw secret value before Bronze-to-Silver — keep only `Redacted`. This is mandatory, not configurable. Encode the projection in `mapping.yml` to exclude raw fields explicitly; an optional Unity Catalog column-level access policy on Bronze is the deployment-time enforcement.
- **Verification semantics.** Where the source supports live credential verification, populate `validity_status` from the verification flag in `mapping.yml`. Document the source field name (e.g. `Verified` for TruffleHog) in a transform-level comment.
- **No status transitions.** `REQ-TRF-STS` is N/A; do not generate status-transition code or status-lookup references. The Silver `status` field is left null (or set to `open` on first emit) — encode the constant in `mapping.yml`, NOT a lookup.
- **CI/CD-step dominance.** Secret detection is almost exclusively CI/CD-step in practice; the `config.yml` HWM shape is the commit SHA. Periodic-global host-side scans (GitHub Secret Scanning) use scan-start timestamp; both shapes co-exist on the four-tuple dedup key.
- **Detector-class severity overrides.** The optional `config/severity/{source}.yml` deployment override may downgrade specific detector classes (low-entropy patterns, deprecated detectors) below the default `high`. The override path is opt-in; the default code path uses the `mapping.yml` literal.
