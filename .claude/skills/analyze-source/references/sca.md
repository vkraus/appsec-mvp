# analyze-source — SCA reference

Facts the analyze-source skill needs to write a complete Reference section for an SCA source.

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

From `mkdocs/docs/platform/reference/catalog.md`. SCA sources emit findings keyed by dependency.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SCA (Dependency-Track shape).
- For CLI-based SCA (package-manager audit artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A — same rationale as the CLI-artefact SAST path.

## Default severity

`medium`. Source severity vocabularies extend up to five CVSS-aligned labels (`None`, `Low`, `Medium`, `High`, `Critical`) and some tools add a sixth `UNASSIGNED` or informational level. Per-source lookup tables at `config/severity/{source}.yml` map each value to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data-quality warning.

## Incremental strategy

Selection depends on the deployment style per the SCA capability surface:

- **Server-based SCA** (Dependency-Track) exposes paginated REST APIs with update-timestamp HWM columns; this is the default mode.
- **CLI-based SCA** (package-manager audits invoked in CI/CD) has no incremental hook; treat under the full-reload strategy with the commit SHA or scan-start timestamp as the HWM.
- **Platform-integrated SCA** (Dependabot in GitHub) shares the host SCM platform's auth, pagination, and incremental hook (typically webhook or `updated_at`).

## Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the canonical SCA scope.

The Reference section's Resource schema excerpt MUST therefore extract `package_name`, `package_version`, `ecosystem`, `cve_id`, and (where present) `purl`.

## Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the package-level finding table).

## Authentication norms

PAT or API-key based, as for SAST. Platform-integrated SCA inherits the host SCM platform's auth (PAT or OAuth). The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SCA REST APIs work cleanly with dlt for paginated reads. CLI-based SCA uses the artefact-collection pattern documented for SAST.

## Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The connector reads the source-supplied advisory linkage; cross-source enrichment happens in Silver, not at ingestion.
- **SBOM-centric data.** Many SCA tools are SBOM-driven (CycloneDX or SPDX). The Reference section MUST disclose whether the source emits SBOM-style outputs or per-finding records, since the consumed-field map differs.
- **PURL availability.** Where the source emits a Package URL (`purl`), capture it — `package_name`, `package_version`, and `ecosystem` are all derivable from it for Silver normalization.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. CI/CD-step SCA (Dependabot alerts on PRs, Semgrep Supply Chain in pipelines) scopes findings to the scanned commit; periodic-global SCA (Dependency-Track scanning enrolled SBOMs on a schedule) scopes findings to the full SBOM inventory at scan time. Reconcile duplicates via the SCA dedup key.
- **Severity scale variation.** Some tools emit numeric CVSS scores instead of (or alongside) named labels. The Reference section MUST disclose whether the connector consumes the named label, the numeric score, or derives one from the other.

## Lakeflow Connect availability

No source in the sca category appears in the analyze-source LFC managed-source catalogue today. Resolution: category-canonical default applies — `sdk_dlt` for REST/SDK sources (the standard ingestion-tooling preference for this category).
