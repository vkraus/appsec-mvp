# generate-connector — SCA reference

Facts the generate-connector skill needs to emit an SCA connector module. SCA sources emit package-level findings keyed by dependency.

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

- Server-based SCA (Dependency-Track shape; full ten REQ-IDs apply): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SCA (package-manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — same rationale as the CLI-artefact SAST path. Do NOT bind these three.
- Platform-integrated SCA (Dependabot in GitHub) inherits the host SCM connector's auth / pagination / rate-limit code; bind only the transform / DQ / dedup REQ-IDs locally.

## Default severity

`medium`. Generate `config/severity/{source}.yml` covering the documented source vocabulary (typically five CVSS-aligned labels: `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

Where the source emits a numeric CVSS score instead of (or alongside) a label, encode the derivation rule in `mapping.yml` (e.g. `>= 9.0 → critical`, `>= 7.0 → high`, etc.) and document it in the connector page Quirks.

## Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based** (Dependency-Track): paginated REST APIs with update-timestamp HWM columns. Default mode.
- **CLI-based**: full-reload from CI/CD pipeline artefact storage; HWM is the commit SHA or scan-start timestamp.
- **Platform-integrated** (Dependabot): inherit the SCM platform's webhook or `updated_at` hook.

## Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["package_name"], row["cve_id"])
```

The transform MUST also project `package_version`, `ecosystem`, and (where present) `purl` — the lookup table fields drive Silver normalization but `cve_id` is the dedup-anchor across SCA tools.

## Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sca"` literally. SCA does NOT write to `silver.dependencies`; that table is fed by SBOM enrichment paths, not the per-finding dedup pipeline.

## Authentication norms

PAT or API-key based, as for SAST. Platform-integrated SCA inherits the host SCM connector's auth (PAT or OAuth). `ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names only.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SCA REST APIs work cleanly with dlt for paginated reads.
- CLI-based SCA uses the artefact-collection pattern documented for SAST — autoloader-style ingestion from the artefact prefix.
- Platform-integrated SCA shares the host SCM connector's helpers.

## Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The transform reads the source-supplied advisory linkage directly into `cve_id`; cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages, NOT here. Do NOT call NVD inline in this connector's `transform.py`.
- **SBOM-centric data.** SBOM-driven sources (CycloneDX, SPDX) emit per-component records; the connector flattens to per-finding rows in `transform.py`. The connector page identifies the format flavour.
- **PURL availability.** Where the source emits a Package URL (`purl`), project it; `package_name`, `package_version`, and `ecosystem` are all derivable from it but the source-side fields are preferred when present.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. The `config.yml` HWM shape changes between modes; encode explicitly.
- **Severity scale variation.** Numeric CVSS vs named labels — the severity lookup or the `mapping.yml` derivation rule MUST cover the chosen format; do not leave gaps.
