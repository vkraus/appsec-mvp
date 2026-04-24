---
name: analyze-source
description: Use when analyzing a data source (REST, GraphQL, SDK, or CLI) for the AppSec connector framework — for example SAST tools (SonarQube, Semgrep), SCA tools (Dependency-Track), secret scanners (TruffleHog), DAST scanners (OWASP ZAP), WAF (AWS WAF), SCM platforms (GitHub, GitLab), or CMDB systems (ServiceNow). Produces a per-connector documentation page following the framework's six-section template.
---

# analyze-source

## Overview

This skill produces a six-section per-connector documentation page from a source's official API documentation. The page lives at `mkdocs/docs/connectors/<category>/<source-slug>.md` and feeds the downstream `generate-connector` and `validate-implementation` skills. The Reference section captures the seven API facts the framework needs to mechanically derive a connector module; the Provenance section opens the lifecycle audit trail that the next two skills extend.

This skill is the analysis stage. It does not write any Python, YAML, or test code; it only writes Markdown. Category-specific facts (applicable REQ-IDs, default severity, HWM preference, dedup key shape, target Silver tables, auth norms, ingestion-tooling preference, quirks) live in `references/<category>.md` and MUST be read for the source's category before drafting Reference.

## Inputs

- **Source name** and homepage URL.
- **Official API documentation URL** (fetched via WebFetch).
- **AppSec category** — one of `cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, `waf`. Determines which `references/<category>.md` to load and the output directory.
- **Optional**: live API credentials for fixture generation. Skip if unavailable.

## Output

A single Markdown page emitted at `mkdocs/docs/connectors/<category>/<source-slug>.md` where `<category>` matches the input and `<source-slug>` is a kebab-case slug of the source name. The page has six top-level sections:

1. **Overview** — what this connector does, its role in the platform, and which Silver table(s) it populates. For sources outside MVP scope, include the `!!! info "Not in MVP scope"` admonition.
2. **Prerequisites** — how to set up the external service and extract credentials (API keys, OAuth apps, PATs).
3. **Reference** — the seven API facts (see Procedure step 7).
4. **Setup** — configuration, bundle deployment, first-run commands. Stub with `!!! info "Not implemented in MVP"` if out-of-scope.
5. **Validation** — always stubbed on first emit with `!!! info "Pending validation"`; `validate-implementation` populates this later.
6. **Provenance** — a Markdown table with three rows. Row 1 is filled by this skill (see Provenance row template below). Rows 2 and 3 are placeholders marked `(pending)` for `generate-connector` and `validate-implementation` to fill in.

## Procedure

1. Fetch the source's API documentation via WebFetch from the input URL. Cache the fetched content for citations.
2. Identify the authentication mechanism the source supports; cross-check against the category's auth norm in `references/<category>.md`. If the source supports multiple auth modes, select the one matching the category convention.
3. Enumerate the endpoints required to populate the Silver tables assigned to the source's category. Cross-reference the Silver Table Ownership table at `mkdocs/docs/platform/reference/catalog.md` and the canonical schemas at `mkdocs/docs/platform/reference/canonical-mapping.md`.
4. Select the incremental strategy per the preference order in `references/<category>.md` (typical order: webhook > native HWM column > full reload; some categories override).
5. Extract a consumed-field schema excerpt — only fields the connector actually reads — matching the canonical Silver fields from `mkdocs/docs/platform/reference/canonical-mapping.md` (entities or findings schema, whichever applies to the category).
6. Produce severity and status lookup proposals per the canonical enumeration models at `mkdocs/docs/platform/reference/canonical-mapping.md`. For categories where severity or status do not apply (CMDB, secrets-status), record the N/A explicitly.
7. Document quirks: deviations from category norms, format surprises, per-source handling policies. Cross-check `references/<category>.md` for category quirks the source may inherit.
8. Stub the Provenance section with the row for this skill (date, inputs, outputs, skill repo ref via `git rev-parse --short HEAD`); leave rows for `generate-connector` and `validate-implementation` marked `(pending)`.
9. Read `references/<category>.md` for category-specific facts that influence the Reference section's seven API facts — applicable REQ-IDs, default severity, HWM preference, dedup key shape, target Silver tables, auth norms, ingestion-tooling preference, quirks.
10. Assemble the six-section Markdown page and emit to the output path.

The seven API facts captured under Reference are:

- **API surface** — REST / GraphQL / SDK / CLI; endpoints consumed; authentication mechanisms.
- **Pagination and rate limits** — strategy and quotas.
- **Incremental hook** — webhook, native HWM column, scan-id, or full reload (per `references/<category>.md`).
- **Resource schema excerpt** — Markdown table with columns Field / Type / Meaning, scoped to fields the connector reads.
- **Enumerations** — severity and status mappings against the canonical models.
- **Quirks** — deviations from category norms; format surprises.

Authentication is folded into the API surface fact; that is six visible facts but the framework documentation calls it seven. Preserve the seven-fact wording when writing Reference, matching the existing baselines.

## Invariants

- Every official documentation URL used MUST be cited inline or in a References list at the bottom of the page. No fabricated facts: every claim about the source's API MUST be traceable to fetched documentation or to `references/<category>.md`.
- The severity and status lookups MUST cover every documented source value; undocumented values default to the configured fallback with a data-quality warning noted inline.
- The page slug and category directory MUST match the AppSec category input exactly; do not invent a new category.
- The Provenance table MUST have row 1 populated; rows 2 and 3 MUST exist with the `(pending)` marker so downstream skills have a target to overwrite.
- Output is Markdown only. Do not write Python, YAML, or test files in this skill.

Category-specific invariants (applicable REQ-IDs, default severity convention, HWM preference, dedup key shape, target Silver tables, auth norms, ingestion-tooling preference, category quirks) live in `references/<category>.md`. Read the file matching the input category before drafting Reference.

## Provenance row template

Append exactly one row to the Provenance table for this skill's invocation. Use this row shape verbatim, replacing the bracketed placeholders with the four data cells:

```
| Source analysis | analyze-source ({category}) | name={source}; url={doc_url}; category={category} | mkdocs/docs/connectors/{category}/{slug}.md §1–§3 | {YYYY-MM-DD} | {git_short_sha} ({branch}) |
```

- `{category}` — the AppSec category input (`cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, or `waf`).
- `{source}` — the source name input.
- `{doc_url}` — the official API documentation URL input.
- `{slug}` — the kebab-case slug used in the output filename.
- `{YYYY-MM-DD}` — the run date in ISO format.
- `{git_short_sha}` — output of `git rev-parse --short HEAD` on the skill's repo.
- `{branch}` — output of `git rev-parse --abbrev-ref HEAD`.

Rows 2 and 3 of the Provenance table must be present and marked `(pending)` so that `generate-connector` and `validate-implementation` can overwrite them on their respective runs. The standard placeholder rows are:

```
| Implementation | generate-connector ({category}) | (pending) | (pending) | (pending) | (pending) |
| Validation | validate-implementation ({category}) | (pending) | (pending) | (pending) | (pending) |
```
