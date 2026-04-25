# generate-connector — CMDB reference

Facts the generate-connector skill needs to emit a CMDB connector module. CMDB sources emit entities, not findings.

## Contents
- Applicable REQ-IDs
- Default severity
- Incremental strategy
- Deduplication key
- Target Silver tables
- Authentication norms
- Ingestion-tooling preference
- Quirks

## Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below; mark each with `@pytest.mark.requirement("REQ-...")`.

- Bind tests for: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Do NOT bind: `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`. The traceability matrix's ServiceNow column marks these three N/A; the test suite MUST omit them.

## Default severity

N/A — CMDB sources emit no findings. The generated `config/severity/{source}.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# N/A — CMDB sources emit no findings
```

No mapping rows. The `mapping.yml` file does not reference this lookup.

## Incremental strategy

Native high-water-mark column (`updated_at`-style; `sys_updated_on` for ServiceNow) per `references/cmdb.md` of `analyze-source`. Encode the column name in `config.yml` under `hwm_column`. The connector reads state from `src/common/` HWM helpers; no scan-id, commit-SHA, or full-reload paths apply.

## Deduplication key

Not applicable. The transform does NOT emit `dedup_links` rows for CMDB; entity dedup is handled by the natural-key column (`sys_id` or equivalent) at Bronze-to-Silver upsert time. Do NOT generate `dedup_links` linkage code in `transform.py`.

## Target Silver tables

Plural names, authoritative per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- `silver.applications`
- `silver.teams`
- `silver.app_repo_mapping`

Emit one Bronze→Silver mapping block per target table in `mapping.yml` (one block can produce multiple Silver rows via per-source projection; or split by source endpoint). Do NOT invent table names — `silver.ownership` is not a thing; ownership lands in `silver.app_repo_mapping`.

The `mapping.yml` shape is entity-only (no `category` discriminator, no severity / status lookup references). Field expressions follow the canonical entity model at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`.

## Authentication norms

Basic-auth service account or OAuth 2.0 client-credentials. Read credentials from the platform secret scope in `ingest.py` via the helper in `src/common/` (NOT inline `os.environ`). The `config.yml` references the secret-scope keys by name only.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CMDB sources are well-served by Lakeflow Connect where a managed connector exists; otherwise the SDK path covers offset-based pagination cleanly. No CLI-artefact override applies. Justify the chosen tool with one comment line at the top of `ingest.py`.

## Quirks

- **Schema-on-read at Bronze.** Custom attributes (e.g. `u_*` columns in ServiceNow) flow through additively without connector changes. Do NOT hard-code a closed schema in `mapping.yml` — the canonical fields project explicitly; everything else falls through to Bronze for downstream use.
- **Reference fields.** Foreign-key attributes (e.g. `owned_by`) are read as opaque strings; do NOT resolve via relationship APIs at ingestion. Resolution lands at transform via Bronze-to-Silver join against `silver.teams`.
- **Display vs raw values.** Configure the source request to return raw values (e.g. `sysparm_display_value=false` for ServiceNow) so IDs stay stable across locale and admin renames.
- **Plural Silver names.** The transform writes to `silver.applications` / `silver.teams` / `silver.app_repo_mapping` — the plurals are authoritative. Singular forms are wrong.
- **High page count.** Offset-based pagination with page sizes in the thousands; `config.yml` page-size knob defaults to 1000 unless the source documents otherwise.
