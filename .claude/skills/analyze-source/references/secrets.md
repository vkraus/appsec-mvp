# analyze-source — Secrets reference

Facts the analyze-source skill needs to write a complete Reference section for a secret-detection source.

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

From `mkdocs/docs/platform/reference/catalog.md`. Secrets sources emit findings but with reduced lifecycle metadata.

- Apply: `REQ-ING-HWM` (full-reload still has an HWM in the form of commit SHA or scan-start timestamp), `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Severity is conventional rather than data-driven: `REQ-TRF-SEV` applies in a degraded form (the lookup table maps detector classes to severity, defaulting to `high`).
- Do not apply: `REQ-TRF-STS` — secret-detection sources do not expose a status / lifecycle vocabulary; the canonical `validity_status` field is populated from the source's verification flag where available, but that is not a status transition graph.
- For CLI-based secret scanners (TruffleHog artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` are N/A — the catalog notes the CLI-artefact ingestion path "has no API auth, pagination, or rate limit." This matches the TruffleHog traceability row.

## Default severity

`high`. The specification maps every secret finding to `severity=high` by default; a per-deployment override at `config/severity/{source}.yml` is permitted for low-entropy detector classes (where false-positive rates are high enough to warrant a downgrade).

The Reference section's Enumerations fact MUST disclose that severity is conventional, not source-derived.

## Incremental strategy

Full-reload only. Per the secrets capability surface, secret-detection sources have no incremental hook; the dominant deployment style is CLI-based, collected from CI/CD pipeline artefacts. The HWM is the commit SHA (CI/CD-step) or scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning).

The Reference section's Incremental hook fact records the full-reload designation explicitly.

## Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the canonical secrets scope.

Both per-commit (CI/CD-step) and host-side periodic-global secret scanning emit records labelled with `(repository_id, commit_sha)` so that Bronze-to-Silver deduplication unifies them without double-counting. The Reference section MUST capture both label sources where the platform supports them.

## Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the code-level finding table). Secret-specific fields populated: `secret_type`, `validity_status` (where the source supports verification).

## Authentication norms

For server-based secret detection (rare): PAT or API-key based, like SAST. For CLI-based secret detection (the dominant style, including TruffleHog): no API auth — access is governed by the artefact store's IAM policy. The Reference section MUST disclose which path the source takes.

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. CLI-based secret scanners use the artefact-collection pattern (the documented exception to the preference order, alongside Semgrep Docker). The Reference section MUST justify the deviation if the CLI path is chosen.

## Quirks

- **Verification semantics.** Where the source supports live credential verification (TruffleHog `Verified` flag, GitHub Secret Scanning `validity`), the result populates the canonical `validity_status` field in Silver. The Reference section MUST disclose verification support and the field name.
- **No status transitions.** Secret findings do not have an open / resolved lifecycle in the source. The Silver `status` field is left null (or set to `open` on first emit) and `REQ-TRF-STS` does not apply.
- **CI/CD-step dominance.** Secret detection is almost exclusively CI/CD-step in practice; every commit is a potential leak. The Reference section's Incremental hook fact records the commit SHA as the operative HWM.
- **Periodic-global host-side scans.** Some platforms (GitHub Secret Scanning) also run periodic-global scans across repository history to catch historical leaks. Both outputs are labelled with `(repository_id, commit_sha)` so dedup unifies them.
- **Detector-class severity overrides.** The `config/severity/{source}.yml` lookup may downgrade specific detector classes (low-entropy patterns, deprecated detectors) below the default `high`. Document the policy in the Quirks fact.
