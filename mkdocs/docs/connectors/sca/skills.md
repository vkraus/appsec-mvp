# SCA skills

Three skills cover the connector lifecycle for SCA sources. Each carries a reference specific to SCA. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: SCA reference

Facts the analyze-source skill needs to write a complete Reference section for an SCA source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. SCA sources emit findings keyed by dependency.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- All ten REQ-IDs apply for server-based SCA (Dependency-Track structure).
- For CLI-based SCA (package manager audit artefacts), `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A. Same rationale as the SAST path for CLI artefacts.

### Default severity

`medium`. Source severity vocabularies extend up to five CVSS-aligned labels (`None`, `Low`, `Medium`, `High`, `Critical`) and some tools add a sixth `UNASSIGNED` or informational level. Lookup tables for each source at `src/connectors/{source}/severity.yml` map each value to the documented four level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` and trigger a data quality warning.

### Incremental strategy

Selection depends on the deployment style per the SCA capability scope:

- **Server-based SCA** (Dependency-Track) exposes paginated REST APIs with update timestamp HWM columns. This is the default mode.
- **CLI-based SCA** (package manager audits invoked in CI/CD) has no incremental hook. Treat under the full reload strategy with the commit SHA or scan start timestamp as the HWM.
- **SCA integrated into the platform** (Dependabot in GitHub) shares the auth, pagination, and incremental hook of the host SCM platform (typically webhook or `updated_at`).

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. This is the documented SCA scope.

The Resource schema excerpt of the Reference section MUST therefore extract `package_name`, `package_version`, `ecosystem`, `cve_id`, and (where present) `purl`.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements` (the finding table at package level).

### Authentication norms

PAT or API key based, as for SAST. SCA integrated into the platform inherits the auth of the host SCM platform (PAT or OAuth). The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. Server-based SCA REST APIs work cleanly with dlt for paginated reads. CLI-based SCA uses the artefact collection pattern documented for SAST.

### Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The connector reads the source-supplied advisory linkage. Cross-source enrichment happens in Silver, not at ingestion.
- **Data centered on SBOM.** Many SCA tools are driven by SBOM (CycloneDX or SPDX). The Reference section MUST disclose whether the source emits SBOM-style outputs or finding records, since the consumed field map differs.
- **PURL availability.** Where the source emits a Package URL (`purl`), capture it. `package_name`, `package_version`, and `ecosystem` are all derivable from it for Silver normalization.
- **Operational pattern axis.** Same CI/CD step vs periodic global split as SAST. CI/CD step SCA (Dependabot alerts on PRs, Semgrep Supply Chain in pipelines) scopes findings to the scanned commit. Periodic global SCA (Dependency-Track scanning enrolled SBOMs on a schedule) scopes findings to the full SBOM inventory at scan time. Reconcile duplicates via the SCA dedup key.
- **Severity scale variation.** Some tools emit numeric CVSS scores instead of (or alongside) named labels. The Reference section MUST disclose whether the connector consumes the named label, the numeric score, or derives one from the other.

*Rendered from `.claude/skills/analyze-source/references/sca.md`. Source of truth lives in the skill file.*

## generate-connector: SCA reference

Facts the generate-connector skill needs to emit an SCA connector module. SCA sources emit package level findings keyed by dependency.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Server-based SCA (Dependency-Track structure, full ten REQ-IDs apply): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SCA (package manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. Same rationale as the SAST path for CLI artefacts. Do NOT bind these three.
- SCA integrated into the platform (Dependabot in GitHub) inherits the auth, pagination, and rate limit code of the host SCM connector. Bind only the transform, DQ, and dedup REQ-IDs locally.

### Default severity

`medium`. Generate `src/connectors/{source}/severity.yml` covering the documented source vocabulary (typically five CVSS-aligned labels: `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) mapped to the documented four level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: src/connectors/{source}/severity.yml
```

Where the source emits a numeric CVSS score instead of (or alongside) a label, encode the derivation rule in `mapping.yml` (e.g. `>= 9.0 to critical`, `>= 7.0 to high`, etc.) and document it in the connector page Quirks.

### Incremental strategy

Selection depends on deployment style. Encode in `config.yml`:

- **Server-based** (Dependency-Track): paginated REST APIs with update timestamp HWM columns. Default mode.
- **CLI-based**: full reload from CI/CD pipeline artefact storage. HWM is the commit SHA or scan start timestamp.
- **Integrated into the platform** (Dependabot): inherit the webhook or `updated_at` hook of the SCM platform.

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["package_name"], row["cve_id"])
```

The transform MUST also project `package_version`, `ecosystem`, and (where present) `purl`. The lookup table fields drive Silver normalization, but `cve_id` is the dedup anchor across SCA tools.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sca"` literally. SCA does NOT write to `silver.dependencies`. That table is fed by SBOM enrichment paths, not the dedup pipeline for findings.

### Authentication norms

PAT or API key based, as for SAST. SCA integrated into the platform inherits the auth of the host SCM connector (PAT or OAuth). `ingest.py` reads credentials via the helper in `src/platform/`. `config.yml` references the secret scope key names only.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt.

- Server-based SCA REST APIs work cleanly with dlt for paginated reads.
- CLI-based SCA uses the artefact collection pattern documented for SAST. Autoloader-style ingestion from the artefact prefix.
- SCA integrated into the platform shares the helpers of the host SCM connector.

### Quirks

- **CVE correlation.** SCA findings reference external advisory sources (NVD, GHSA). The transform reads the source-supplied advisory linkage directly into `cve_id`. Cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages, NOT here. Do NOT call NVD inline in `transform.py` for this connector.
- **Data centered on SBOM.** Sources driven by SBOM (CycloneDX, SPDX) emit records for each component. The connector flattens to finding rows in `transform.py`. The connector page identifies the format flavour.
- **PURL availability.** Where the source emits a Package URL (`purl`), project it. `package_name`, `package_version`, and `ecosystem` are all derivable from it, but the source-side fields are preferred when present.
- **Operational pattern axis.** Same CI/CD step vs periodic global split as SAST. The HWM structure in `config.yml` changes between modes. Encode explicitly.
- **Severity scale variation.** Numeric CVSS vs named labels. The severity lookup or the derivation rule in `mapping.yml` MUST cover the chosen format. Do not leave gaps.

*Rendered from `.claude/skills/generate-connector/references/sca.md`. Source of truth lives in the skill file.*

## validate-implementation: SCA reference

Facts the validate-implementation skill needs to populate the Validation table for an SCA connector. SCA sources emit findings keyed on dependencies. The full ten REQ-IDs apply for server-based deployments.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". Server-based SCA (Dependency-Track structure) tracks the same row pattern as SAST.

Apply (all ten, the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

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

CLI-based SCA (package manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. Same rationale as the SAST path for CLI artefacts, quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this N/A profile when validating a CLI-only connector.

SCA integrated into the platform (Dependabot in GitHub) inherits the auth, pagination, and rate limit code of the host SCM connector. The SCA test suite binds only the transform, DQ, and dedup REQ-IDs locally.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/sca/index.md` § "Capability scope". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented source vocabulary (typically `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) and asserting that undocumented values fall through with a data quality warning per the catalog requirement text.

### Incremental strategy

Per `mkdocs/docs/connectors/sca/index.md` § "Capability scope": server-based uses paginated REST APIs with update timestamp HWM columns. CLI-based uses commit SHA or scan start timestamp under full reload. Integrated into the platform inherits the hook of the SCM platform. The test suite asserts HWM resume behaviour under `REQ-ING-HWM` against the chosen mode of the connector.

### Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/connectors/sca/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

### Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. SCA does NOT write to `silver.dependencies` (that table is fed by SBOM enrichment paths, not the dedup pipeline for findings). The test suite verifies the connector targets `silver.findings` only under `REQ-TRF-MAP`.

### Authentication norms

PAT or API key per `mkdocs/docs/connectors/sca/index.md` § "Capability scope". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based and platform-integrated variants omit or inherit this test as documented above.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt. The validation suite verifies pagination and rate limit behaviour under `REQ-ING-PAG` and `REQ-ING-RL` against whichever tool the connector chose.

### Quirks

- **CVE correlation.** `REQ-TRF-MAP` asserts that the source-supplied advisory linkage is read directly into `cve_id`. Cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages and is NOT asserted by the test suite for each connector.
- **Data centered on SBOM.** Sources driven by SBOM emit records for each component. The connector flattens to finding rows. `REQ-TRF-MAP` covers the flattening assertion.
- **PURL availability.** Where the source emits a `purl`, `REQ-TRF-MAP` asserts the field is projected. `package_name`, `package_version`, `ecosystem` are derivable from PURL, but the source-side fields are preferred and asserted under the same REQ-ID.
- **Operational pattern axis.** Same CI/CD step vs periodic global split as SAST. `REQ-ING-HWM` exercises the chosen mode.
- **Severity scale variation.** Numeric CVSS vs named labels. `REQ-TRF-SEV` asserts coverage over the chosen format with no gaps.

*Rendered from `.claude/skills/validate-implementation/references/sca.md`. Source of truth lives in the skill file.*
