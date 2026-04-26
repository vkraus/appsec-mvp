# SAST connectors

SAST connectors ingest static analysis findings keyed by repository, file, and rule.

!!! note "SCM first dependency"
    Connectors in this category depend on at least one SCM connector being
    installed first. Their findings reference `silver.repositories.repository_id`
    populated by SCM. Walk the [SCM category](../scm/index.md) before installing
    a SAST connector.

## Capability contract

SAST sources emit findings keyed by repository, file path, line number, rule identifier, and optional CWE category. Severity scales range from three to five levels, with overlapping but non-identical vocabularies. The specification requires lookup tables for each tool mapping each source value to the standardized four level severity.

Three deployment styles recur:

- **Server based tools** expose paginated REST APIs and carry an update timestamp column usable as a high water mark.
- **CLI based tools** (including container hosted CLI deployments such as Semgrep running in a Docker container inside the CI/CD pipeline or as a long running service) emit JSON or SARIF output to files collected from pipeline artifacts, mounted volumes, or object storage. They have no server side incremental hook and **SHALL** be treated under the full reload strategy, with the commit SHA or scan start timestamp as the high water mark.
- **Platform integrated scanners** (where SAST ships inside the host SCM platform) expose findings through the API of the host platform, sharing authentication and pagination with the SCM connector.

Authentication across all three styles is PAT or API key based.

SAST tools also split on an orthogonal axis (the **operational pattern**) that the specification tracks independently of integration technology:

- **CI/CD step scanners** run per commit or per pull request inside a pipeline and emit findings scoped to that run. Coverage depends on which repositories have functioning CI/CD, and the natural incremental key for the connector is the commit SHA or run identifier per repository.
- **Periodic global scanners** run on a schedule against an enrolled project inventory and emit findings scoped to the full codebase at scan time. Coverage is guaranteed across enrolled projects regardless of CI/CD activity, and the incremental key for the connector is an updated since timestamp.

Most SAST tools operate in one mode (Semgrep Docker hosted: CI/CD step; SonarQube server: periodic global), though some deployments run the same tool in both.

## Standardized mapping contribution

SAST sources populate the Silver `finding` table scoped by `(repository_id, file_path, rule_id)`. See [Standardized mapping](../../platform/reference/canonical-mapping.md).

## Skills

Four skills cover the connector lifecycle for SAST sources, with category specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [SonarQube](sonarqube.md): reference implementation (periodic global server).
- [Semgrep](semgrep.md): reference implementation (CI/CD step CLI).
