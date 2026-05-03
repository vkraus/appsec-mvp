# Product Documentation Site

MkDocs Material site for the Application Security Data Platform — the product documentation that accompanies the master's thesis *A Data Integration Framework for Enterprise Application Security*.

Serves as the thesis's **Requirements Specification attachment**: the content previously drafted as Appendix A has moved here so it can be browsed, searched, and linked by tool rather than printed.

## Structure

- [docs/requirements/](docs/requirements/) — Requirements specification (per-category capability surface, canonical mapping requirements, per-source reference, requirement catalog with traceability).
- [docs/functional-spec/](docs/functional-spec/) — Functional specification (Claude Code skill catalog that operationalizes the spec).
- [docs/design/](docs/design/) — Implementation design (architecture, modules, pipelines) — complements the thesis Framework chapter.
- [docs/tests/](docs/tests/) — Test reference: traceability between `REQ-*` identifiers and `tests/` suites.

## Local preview

```bash
cd mkdocs
pip install -r requirements.txt
mkdocs serve
```

Site is served at <http://127.0.0.1:8000>.

## Build

```bash
cd mkdocs
mkdocs build          # output in site/
```

## Deployment

Published to GitHub Pages via [.github/workflows/build.yml](../.github/workflows/build.yml) on every push to `main`. The same workflow ships `appsec-mvp.zip` (source) and `appsec-mvp-docs.zip` (rendered site) — both uploaded as workflow artifacts and copied into the published site at `/appsec-mvp.zip` and `/appsec-mvp-docs.zip`.
