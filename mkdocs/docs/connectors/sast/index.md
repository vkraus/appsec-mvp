# SAST connectors

SAST connectors ingest static-analysis findings keyed by repository, file, and rule.

## Capability surface

SAST sources emit findings keyed by repository, file path, line number, rule identifier, and optional CWE category. Severity scales range from three to five levels, with overlapping but non-identical vocabularies; the specification requires per-tool lookup tables mapping each source value to the canonical four-level severity.

Three deployment styles recur:

- **Server-based tools** expose paginated REST APIs and carry an update-timestamp column usable as a high-water mark.
- **CLI-based tools** (including container-hosted CLI deployments such as Semgrep running in a Docker container inside the CI/CD pipeline or as a long-running service) emit JSON or SARIF output to files collected from pipeline artifacts, mounted volumes, or object storage; they have no server-side incremental hook and **SHALL** be treated under the full-reload strategy, with the commit SHA or scan-start timestamp as the high-water mark.
- **Platform-integrated scanners** (where SAST ships inside the host SCM platform) expose findings through the host platform's API, sharing authentication and pagination with the SCM connector.

Authentication across all three styles is PAT or API-key based.

SAST tools also split on an orthogonal axis — **operational pattern** — that the specification tracks independently of integration technology:

- **CI/CD-step scanners** run per commit or per pull request inside a pipeline and emit findings scoped to that run; coverage depends on which repositories have functioning CI/CD, and the connector's natural incremental key is the commit SHA or run identifier per repository.
- **Periodic-global scanners** run on a schedule against an enrolled project inventory and emit findings scoped to the full codebase at scan time; coverage is guaranteed across enrolled projects regardless of CI/CD activity, and the connector's incremental key is an updated-since timestamp.

Most SAST tools operate in one mode (Semgrep Docker-hosted: CI/CD-step; SonarQube server: periodic-global), though some deployments run the same tool in both.

## Canonical mapping contribution

SAST sources populate the Silver `finding` table scoped by `(repository_id, file_path, rule_id)`. See [Canonical mapping](../../platform/reference/canonical-mapping.md).

## Skills

Three skills cover the connector lifecycle for SAST sources, with category-specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [SonarQube](sonarqube.md) — reference implementation (periodic-global server).
- [Semgrep](semgrep.md) — reference implementation (CI/CD-step CLI).
