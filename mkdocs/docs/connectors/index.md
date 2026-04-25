# Connectors

Connectors ingest from AppSec source systems into the platform's Bronze layer, then transform into the canonical Silver entities and findings. Wire them in the order below — downstream categories depend on upstream ones.

## Adoption order

1. **[CMDB](cmdb/)** — authoritative application inventory and team ownership (ServiceNow).
2. **[SCM](scm/)** — repositories, pull requests, and branch policies used to attribute findings (GitHub, GitLab).
3. **[SAST](sast/)** — static analysis findings keyed by file and rule (SonarQube, Semgrep).
4. **[SCA](sca/)** — dependency-keyed findings with CVE correlation (Dependency-Track).
5. **[Secrets](secrets/)** — credential-leak detections from pipelines and history (TruffleHog).
6. **[DAST](dast/)** — dynamic scans against deployed services (OWASP ZAP).
7. **[WAF](waf/)** — edge-layer block events and rule logs (AWS WAF).

Each category page documents the shared capability surface — authentication, pagination, incremental strategy — and lists the category's Claude Code skills.

## How connectors are produced

Connectors in this framework are produced by three category-aware skills: `analyze-source`, `generate-connector`, and `validate-implementation` (see [Connector skills](../platform/reference/connector-skills.md) for procedures and the per-connector generation aggregator). The four connectors implemented in the MVP were authored prior to skill formalization but conform to the same contract; the connector-lifecycle skills produce all subsequent connectors. Each connector page includes a Provenance section recording the skill version (git ref), inputs, and outputs of its generation.
