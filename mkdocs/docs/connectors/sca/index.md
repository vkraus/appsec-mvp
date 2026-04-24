# SCA connectors

SCA connectors ingest dependency-keyed findings with CVE correlation.

## Capability surface

SCA sources emit dependency-keyed findings: package name, installed version, ecosystem, CVE identifier, and optional PURL. Severity vocabularies extend up to five CVSS-aligned labels (`None`, `Low`, `Medium`, `High`, `Critical`), with some tools adding a sixth for unassigned or informational findings; the specification requires per-tool severity lookup tables to the canonical four-level scale as for SAST.

SCA data is frequently SBOM-centric (CycloneDX or SPDX) and correlated against external advisory sources (NVD, GHSA). Server-based SCA tools expose paginated REST APIs with update-timestamp high-water-mark columns; authentication is PAT or API-key based, as for SAST. CLI-based SCA tools (for example, package-manager audit commands invoked in CI/CD) have no incremental hook and **SHALL** be treated under the full-reload strategy. Platform-integrated SCA (where SCA is hosted in the SCM platform) shares the host platform's authentication and pagination.

The CI/CD-step vs. periodic-global axis applies identically here: CI/CD-step SCA (package-manager audits, Semgrep Supply Chain in pipeline, Dependabot alerts attached to pull requests) produces findings scoped to the scanned commit; periodic-global SCA (Dependency-Track server scanning all enrolled SBOMs on a schedule) produces findings scoped to the full SBOM inventory at scan time. A deployment may run both and reconcile duplicates via the SCA dedup key `(repository_id, package_name, cve_id)`.

## Canonical mapping contribution

SCA sources populate the Silver `finding` table with SCA dedup key `(repository_id, package_name, cve_id)`. See [Canonical mapping](../../platform/reference/canonical-mapping.md).

## Skills

Three category-specialized skills cover the connector lifecycle for SCA sources: `analyze-source-sca`, `generate-connector-sca`, `validate-implementation-sca`. See [Skills](skills.md) for the current unspecialized baselines.

## Connectors in this category

- [Dependency-Track](dependency-track.md) — intended integration (no MVP implementation).
