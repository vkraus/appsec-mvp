---
name: provision-source
description: Use after analyze-source to provision the source-side infrastructure for an AppSec connector — emits Terraform (main, variables, outputs, versions), a per-runtime README, and an install.sh that runs `terraform apply`, plus the connector page §Source provisioning section, conforming to the framework's source-provisioning contract for the source's category (cmdb, scm, sast, sca, secrets, dast, or waf).
---

# provision-source

## Overview

This skill emits the source-side provisioning artifacts for a single source: the Terraform configuration that stands up the source's data path (e.g. an EKS CronJob for Semgrep, AWS WAF + Firehose-to-S3 for AWS WAF, a GitHub Actions workflow snippet for the CI/CD-step path, or a no-op smoke-test for SaaS-only CMDB sources), a per-runtime operator README, an `install.sh` that runs `terraform apply` against this `runtime/`, and the connector page's §Source provisioning section. The skill is read-only over the connector page produced by `analyze-source`; it modifies only the source-side `runtime/` subtree and the page §Source provisioning section + Implementation log row 2.

This skill does NOT emit the contents of `runtime/files/*`. Bulky operator-authored sidecars (demo target forks, scan helper scripts, IaC fixtures) live there and are authored directly by the operator. The skill emits REFERENCES to those paths in `runtime/main.tf` (e.g. as `local_file` data sources, `kubernetes_config_map` `data` blocks, or via `var.demo_target_paths`-style variables) but never their bodies. Category-specific facts that drive emit (Terraform shape, install.sh shape, runtime/files/* conventions, `operational.yml.source_runtime` schema, page §Source provisioning template) live in `references/<category>.md` and MUST be read for the source's category before any file is written.

## Inputs

- **Source name** — determines the runtime path `src/connectors/{source}/runtime/`.
- **Per-connector page path** — `mkdocs/docs/connectors/{category}/{slug}.md` produced by `analyze-source`.
- **AppSec category** — one of `cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, `waf`. Determines which `references/<category>.md` to load and the page path.
- **operational.yml path** — `src/connectors/{source}/operational.yml`. The skill reads the `source_runtime:` sub-block; required fields per category are listed in `references/<category>.md`.

Preconditions:

- The connector page exists at `mkdocs/docs/connectors/{category}/{slug}.md` with Reference §3 populated and an Implementation log table whose row 2 is marked `(pending)`.
- `operational.yml` exists at the path with the `source_runtime:` sub-block populated. The skill HALTS if `operational.yml` is missing or any required-by-category `source_runtime:` field is absent. Halt-don't-partial-emit: no runtime/ file is written when inputs are incomplete.

## Output

- `src/connectors/{source}/runtime/main.tf` — Terraform configuration with provider declarations and per-category resources (interpolated from `operational.yml.source_runtime` values; `runtime/files/*` paths referenced via `local_file` data sources or variables).
- `src/connectors/{source}/runtime/variables.tf` — Terraform variable declarations for every value that varies per-deployment.
- `src/connectors/{source}/runtime/outputs.tf` — Terraform outputs (e.g. S3 bucket ARN, CronJob name, IAM role ARN) consumed by the Databricks-side install phase.
- `src/connectors/{source}/runtime/versions.tf` — Terraform and provider version pinning per category template.
- `src/connectors/{source}/runtime/README.md` — per-runtime operator README explaining what this `runtime/` provisions, the variables to set, and how to invoke `runtime/install.sh`.
- `src/connectors/{source}/runtime/install.sh` — runs `terraform apply` against this `runtime/`. For categories where the source is a SaaS with no infrastructure to provision (e.g. CMDB / ServiceNow), `runtime/install.sh` may be a no-op or a smoke-test script per `references/<category>.md`.
- Connector page §Source provisioning section — operator-facing source-provisioning runbook for this category, referencing `runtime/install.sh` and any `runtime/files/*` operator-authored sidecars.
- Implementation log row 2 — overwrite the `(pending)` placeholder for `provision-source` per the row template below.

## Procedure

1. **Read `references/<category>.md` for category-specific facts** — `operational.yml.source_runtime` schema (which fields are required), Terraform shape (provider, modules, variables exposed, outputs), `runtime/files/*` conventions (which sidecar paths apply for the category and how `main.tf` references them), `runtime/install.sh` shape, `runtime/README.md` template, and the page §Source provisioning section template.
2. Read `src/connectors/{source}/operational.yml` and extract the `source_runtime:` sub-block. HALT if `operational.yml` is missing or if any `source_runtime:` field marked required-by-category is missing — do not partial-emit.
3. Read connector page §3 Reference to extract any source-side facts the page documents (e.g. authentication mechanism that informs Terraform IAM, S3 prefix structure, webhook endpoint shape). Do not modify the page §3 content.
4. Emit `src/connectors/{source}/runtime/main.tf` from the category template, interpolating values from `operational.yml.source_runtime`. Emit references to `runtime/files/*` paths declared in the operational.yml's `demo_target_paths`-style fields via `local_file` data sources or Terraform variables — do NOT generate the file contents.
5. Emit `src/connectors/{source}/runtime/variables.tf`, `runtime/outputs.tf`, `runtime/versions.tf` per the category template.
6. Emit `src/connectors/{source}/runtime/README.md` from the category README template, listing the variables to set and the invocation command for `runtime/install.sh`.
7. Emit `src/connectors/{source}/runtime/install.sh` per the category shape (typical: `cd "$(dirname "$0")" && terraform init && terraform apply -auto-approve`). For SaaS-only categories where there is no infrastructure to provision, emit the no-op or smoke-test variant per `references/<category>.md`.
8. Update the connector page §Source provisioning section: replace the section body (or insert the section if absent) with the operator-facing source-provisioning runbook for this category, referencing `runtime/install.sh` and any `runtime/files/*` operator-authored sidecars.
9. Update the connector page's Implementation log row 2: overwrite the `(pending)` placeholder for `provision-source` using the row template below. Run date in ISO format; `git rev-parse --short HEAD` for the skill repo ref; `git rev-parse --abbrev-ref HEAD` for the branch.

## Invariants

- No file is written outside `src/connectors/{source}/runtime/`, the connector page §Source provisioning section, and the Implementation log row 2 cell. The source-provisioning emit is self-contained.
- `src/connectors/{source}/runtime/files/*` is NEVER modified by this skill — it is operator-authored sidecar territory. The skill emits REFERENCES to those paths in `runtime/main.tf` (via `local_file` data sources, `kubernetes_config_map` `data` blocks, or `var.demo_target_paths`-style variables) but does NOT generate the file contents.
- Shared files (`databricks.yml`, `mkdocs/mkdocs.yml`, `pyproject.toml`, the aggregator at `mkdocs/docs/platform/reference/connector-skills.md`, the catalog at `mkdocs/docs/platform/reference/catalog.md`) are NEVER touched by this skill.
- `src/connectors/{source}/operational.yml` is NEVER modified. If the file is missing or any required-by-category `source_runtime:` field is absent, halt and report. Do not partial-emit any `runtime/` file.
- The connector page sections owned by other skills are NEVER touched: §1–§3 (analyze-source), §4–§7 / §Run-the-job / §Verify / §Troubleshooting (generate-connector), §5 Validation (validate-implementation). Only the §Source provisioning section and Implementation log row 2 are written.
- For SaaS-only categories where there is no infrastructure to provision, `runtime/install.sh` is still emitted (as a no-op or smoke-test) so the top-level `install.sh` chain emitted by `generate-connector` can call it unconditionally.

Category-specific invariants (`operational.yml.source_runtime` schema, Terraform shape, `runtime/files/*` conventions, `runtime/install.sh` shape, `runtime/README.md` template, page §Source provisioning section template) live in `references/<category>.md`. Read the file matching the input category before emitting any file.

## Implementation log row template

Overwrite the `(pending)` placeholder for `provision-source` (row 2) in the connector page's Implementation log table. Use this row shape verbatim, replacing the bracketed placeholders with the four data cells:

```
| Source provisioning | provision-source ({category}) | source_runtime fields=<comma-separated list> | src/connectors/{source}/runtime/, mkdocs/docs/connectors/{category}/{slug}.md §Source provisioning | {YYYY-MM-DD} | {git_short_sha} ({branch}) |
```

- `{category}` — the AppSec category input (`cmdb`, `scm`, `sast`, `sca`, `secrets`, `dast`, or `waf`).
- `<comma-separated list>` — the names of every `source_runtime:` field actually read from `operational.yml` during this run (e.g. `cloud_provider, account_id, region, cluster_name, demo_target_paths`). Drives the audit trail for which inputs pinned this emit.
- `{source}` — the source name input.
- `{slug}` — the kebab-case slug used in the connector page filename.
- `{YYYY-MM-DD}` — the run date in ISO format.
- `{git_short_sha}` — output of `git rev-parse --short HEAD` on the skill's repo.
- `{branch}` — output of `git rev-parse --abbrev-ref HEAD`.

Rows 1 (`analyze-source`), 3 (`generate-connector`), and 4 (`validate-implementation`) MUST remain untouched.
