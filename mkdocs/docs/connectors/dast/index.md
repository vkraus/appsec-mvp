# DAST connectors

DAST connectors ingest dynamic-scan findings against deployed services.

## Capability surface

DAST sources emit findings scoped to a target URL, application, or API endpoint rather than to a source file. The canonical key is `(target, alert_id, uri_path)`: `target` identifies the scanned deployment (host, base URL), `alert_id` is the scanner-internal rule identifier, and `uri_path` disambiguates multiple hits of the same rule across paths of the same target. Severity vocabularies are shorter than SAST (typically four levels, for example `Informational`, `Low`, `Medium`, `High`), and the specification requires per-tool lookup tables mapping each source value to the canonical four-level severity.

Two deployment styles recur:

- **Server-based tools** run as a long-lived daemon (for example, the ZAP daemon or the ZAP API) driven by the connector against target URLs drawn from the application inventory; the connector orchestrates scans per deployment and reads alerts back after scan completion.
- **CI/CD-step tools** run the scanner CLI inside a pipeline (for example, `zap-baseline.py` in a GitHub Actions step) against the freshly-deployed application and emit JSON or SARIF output to an artifact store or object-storage prefix collected by the connector.

The incremental strategy is scan-report-based: one ingestion per scan completion, with full reload within a scan's scope. Unlike SAST, there is no server-side `updated_at` incremental column on individual findings — the scan ID (server-based) or artifact file (CI/CD-step) is the high-water mark, and findings from prior scans remain queryable for audit.

Authentication differs by style. Server-based tools use an API key (for example, the ZAP API key supplied via `X-ZAP-API-Key` header, configured at daemon startup). CI/CD-step output files have no native authentication; access is governed by the object-storage bucket's IAM policy.

DAST findings reference a URL rather than a repository file, so application linkage requires resolving `target` against the deployment inventory (`silver.deployments`). Unmatched URLs are emitted for inventory-gap analysis.

## Canonical mapping contribution

DAST sources populate the Silver `finding` table scoped by `(application_id, target, alert_id)`. See [Canonical mapping](../../platform/reference/canonical-mapping.md).

## Skills

Three skills cover the connector lifecycle for DAST sources, with category-specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [OWASP ZAP](owasp-zap.md) — reference implementation.
