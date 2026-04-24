# Application Security Data Platform

Product documentation for the application security data integration framework and its Databricks reference implementation.

## Adoption path

1. **[Platform](platform/)** — Databricks workspace, prerequisites, terraform apply, Bronze/Silver/Gold architecture.
2. **[Connectors](connectors/)** — one section per AppSec category (CMDB → SCM → SAST → SCA → Secrets → DAST → WAF), with a self-contained page per connector covering prerequisites, reference, setup, and validation.
3. **[Analytics](analytics/)** — Gold datasets, evidence scenarios, dashboards, and the tests traceability index.

## Source repositories

The MVP codebase backing this documentation lives at <https://github.com/vkraus/appsec-mvp>:

- `src/` — Databricks reference implementation (connector library + per-source connectors).
- `tests/` — `pytest` suites with `REQ-*` markers referenced by [Analytics → Tests & traceability](analytics/tests.md).
- `config/` — severity and status normalization lookup tables.
- `resources/` — Databricks Asset Bundle (DAB) job definitions.
- `infra/terraform/` — AWS / Databricks / scanner provisioning.

This documentation site is published from <https://github.com/vkraus/appsec-docs>.

## Conventions

- **SHALL** marks mandatory requirements. **SHOULD** marks recommended practices.
- Schema excerpts list only fields consumed by the reference implementation's connectors; the full field catalog is in each source's official documentation.
- Code spans like `config.yml` and `REQ-CONN-001` are clickable where they resolve to a file or anchor.
