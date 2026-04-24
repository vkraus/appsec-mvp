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
