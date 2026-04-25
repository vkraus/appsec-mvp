# SCA skills

Three skills cover the connector lifecycle for SCA sources. Each carries a SCA-specific reference; the procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source — SCA reference

Facts the analyze-source skill needs to write a complete Reference section for an SCA source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SCA sources emit findings keyed by dependency.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SCA (Dependency-Track shape).
- For CLI-based SCA (package-manager audit artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A — same rationale as the CLI-artefact SAST path.

### Default severity

`medium`. Source severity vocabularies extend up to five CVSS-aligned labels (`None`, `Low`, `Medium`, `High`, `Critical`) and some tools add a sixth `UNASSIGNED` or informational level. Per-source lookup tables at `config/severity/{source}.yml` map each value to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data-quality warning.

### Incremental strategy

Selection depends on the deployment style per the SCA capability surface:

- **Server-based SCA** (Dependency-Track) exposes paginated REST APIs with update-timestamp HWM columns; this is the default mode.
- **CLI-based SCA** (package-manager audits invoked in CI/CD) has no incremental hook; treat under the full-reload strategy with the commit SHA or scan-start timestamp as the HWM.
- **Platform-integrated SCA** (Dependabot in GitHub) shares the host SCM platform's auth, pagination, and incremental hook (typically webhook or `updated_at`).

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the canonical SCA scope.

The Reference section's Resource schema excerpt MUST therefore extract `package_name`, `package_version`, `ecosystem`, `cve_id`, and (where present) `purl`.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the package-level finding table).

### Authentication norms

PAT or API-key based, as for SAST. Platform-integrated SCA inherits the host SCM platform's auth (PAT or OAuth). The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SCA REST APIs work cleanly with dlt for paginated reads. CLI-based SCA uses the artefact-collection pattern documented for SAST.

### Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The connector reads the source-supplied advisory linkage; cross-source enrichment happens in Silver, not at ingestion.
- **SBOM-centric data.** Many SCA tools are SBOM-driven (CycloneDX or SPDX). The Reference section MUST disclose whether the source emits SBOM-style outputs or per-finding records, since the consumed-field map differs.
- **PURL availability.** Where the source emits a Package URL (`purl`), capture it — `package_name`, `package_version`, and `ecosystem` are all derivable from it for Silver normalization.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. CI/CD-step SCA (Dependabot alerts on PRs, Semgrep Supply Chain in pipelines) scopes findings to the scanned commit; periodic-global SCA (Dependency-Track scanning enrolled SBOMs on a schedule) scopes findings to the full SBOM inventory at scan time. Reconcile duplicates via the SCA dedup key.
- **Severity scale variation.** Some tools emit numeric CVSS scores instead of (or alongside) named labels. The Reference section MUST disclose whether the connector consumes the named label, the numeric score, or derives one from the other.

*Rendered from `.claude/skills/analyze-source/references/sca.md`. Source-of-truth lives in the skill file.*

## generate-connector — SCA reference

Facts the generate-connector skill needs to emit an SCA connector module. SCA sources emit package-level findings keyed by dependency.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SCA (Dependency-Track shape; full ten REQ-IDs apply): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SCA (package-manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — same rationale as the CLI-artefact SAST path. Do NOT bind these three.
- Platform-integrated SCA (Dependabot in GitHub) inherits the host SCM connector's auth / pagination / rate-limit code; bind only the transform / DQ / dedup REQ-IDs locally.

### Default severity

`medium`. Generate `config/severity/{source}.yml` covering the documented source vocabulary (typically five CVSS-aligned labels: `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

Where the source emits a numeric CVSS score instead of (or alongside) a label, encode the derivation rule in `mapping.yml` (e.g. `>= 9.0 → critical`, `>= 7.0 → high`, etc.) and document it in the connector page Quirks.

### Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based** (Dependency-Track): paginated REST APIs with update-timestamp HWM columns. Default mode.
- **CLI-based**: full-reload from CI/CD pipeline artefact storage; HWM is the commit SHA or scan-start timestamp.
- **Platform-integrated** (Dependabot): inherit the SCM platform's webhook or `updated_at` hook.

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["package_name"], row["cve_id"])
```

The transform MUST also project `package_version`, `ecosystem`, and (where present) `purl` — the lookup table fields drive Silver normalization but `cve_id` is the dedup-anchor across SCA tools.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sca"` literally. SCA does NOT write to `silver.dependencies`; that table is fed by SBOM enrichment paths, not the per-finding dedup pipeline.

### Authentication norms

PAT or API-key based, as for SAST. Platform-integrated SCA inherits the host SCM connector's auth (PAT or OAuth). `ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names only.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SCA REST APIs work cleanly with dlt for paginated reads.
- CLI-based SCA uses the artefact-collection pattern documented for SAST — autoloader-style ingestion from the artefact prefix.
- Platform-integrated SCA shares the host SCM connector's helpers.

### Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The transform reads the source-supplied advisory linkage directly into `cve_id`; cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages, NOT here. Do NOT call NVD inline in this connector's `transform.py`.
- **SBOM-centric data.** SBOM-driven sources (CycloneDX, SPDX) emit per-component records; the connector flattens to per-finding rows in `transform.py`. The connector page identifies the format flavour.
- **PURL availability.** Where the source emits a Package URL (`purl`), project it; `package_name`, `package_version`, and `ecosystem` are all derivable from it but the source-side fields are preferred when present.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. The `config.yml` HWM shape changes between modes; encode explicitly.
- **Severity scale variation.** Numeric CVSS vs named labels — the severity lookup or the `mapping.yml` derivation rule MUST cover the chosen format; do not leave gaps.

*Rendered from `.claude/skills/generate-connector/references/sca.md`. Source-of-truth lives in the skill file.*

## validate-implementation — SCA reference

Facts the validate-implementation skill needs to populate the Validation table for an SCA connector. SCA sources emit dependency-keyed findings; the full ten REQ-IDs apply for server-based deployments.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". Server-based SCA (Dependency-Track shape) tracks the same row pattern as SAST.

Apply (all ten — the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

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

Mark `N/A`: none for the server-based deployment style.

CLI-based SCA (package-manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — same rationale as the CLI-artefact SAST path quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this N/A profile when validating a CLI-only connector.

Platform-integrated SCA (Dependabot in GitHub) inherits the host SCM connector's auth / pagination / rate-limit code; the SCA test suite binds only the transform / DQ / dedup REQ-IDs locally.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/sca/index.md` § "Capability surface". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented source vocabulary (typically `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) and asserting that undocumented values fall through with a data-quality warning per the catalog requirement text.

### Incremental strategy

Per `mkdocs/docs/connectors/sca/index.md` § "Capability surface": server-based uses paginated REST APIs with update-timestamp HWM columns; CLI-based uses commit SHA or scan-start timestamp under full reload; platform-integrated inherits the SCM platform's hook. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the connector's chosen mode.

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/connectors/sca/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. SCA does NOT write to `silver.dependencies` (that table is fed by SBOM enrichment paths, not the per-finding dedup pipeline); the test suite verifies the connector targets `silver.findings` only under `REQ-TRF-MAP`.

### Authentication norms

PAT or API-key per `mkdocs/docs/connectors/sca/index.md` § "Capability surface". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based and platform-integrated variants omit or inherit this test as documented above.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. The validation suite verifies pagination and rate-limit behaviour under `REQ-ING-PAG` and `REQ-ING-RL` against whichever tool the connector chose.

### Quirks

- **CVE correlation.** `REQ-TRF-MAP` asserts that the source-supplied advisory linkage is read directly into `cve_id`. Cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages and is NOT asserted by the per-connector test suite.
- **SBOM-centric data.** SBOM-driven sources emit per-component records; the connector flattens to per-finding rows. `REQ-TRF-MAP` covers the flattening assertion.
- **PURL availability.** Where the source emits a `purl`, `REQ-TRF-MAP` asserts the field is projected. `package_name`, `package_version`, `ecosystem` are derivable from PURL but the source-side fields are preferred and asserted under the same REQ-ID.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. `REQ-ING-HWM` exercises the chosen mode.
- **Severity scale variation.** Numeric CVSS vs named labels — `REQ-TRF-SEV` asserts coverage over the chosen format with no gaps.

*Rendered from `.claude/skills/validate-implementation/references/sca.md`. Source-of-truth lives in the skill file.*
