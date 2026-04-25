# generate-connector — DAST reference

Facts the generate-connector skill needs to emit a DAST connector module. DAST sources emit findings against deployed targets; the HWM is scan-scoped, not record-level.

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

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST consuming scan reports rather than the live API, `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — the catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The ZAP traceability row marks these three N/A. Do NOT bind them in this case.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

## Default severity

`medium`. Generate `config/severity/{source}.yml` covering the documented vocabulary (typically four levels: `Informational`, `Low`, `Medium`, `High`) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

## Incremental strategy

Scan-id-based, NOT record-level `updated_at`. Encode in `config.yml` under a `hwm_kind: scan_id` knob (or `hwm_kind: artefact_prefix` for CLI variants):

- **Server-based** (ZAP daemon / API): the scan ID is the high-water mark. The connector orchestrates scans per deployment and reads alerts back after scan completion. Encode the scan-orchestration mode (`scan-and-read` vs `read-only`) explicitly in `config.yml`.
- **CI/CD-step** (e.g. `zap-baseline.py`): the artefact file (object-storage prefix or pipeline artefact) is the high-water mark. Encode the prefix and report format (JSON / SARIF) in `config.yml`.

The `src/platform/` HWM helpers expose a `scan_id` mode in addition to the column-based default; use it.

## Deduplication key

`(target, alert_id, uri_path)` per the DAST capability surface, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["target"], row["alert_id"], row["uri_path"])
```

- `target` — the scanned deployment (host, base URL).
- `alert_id` — the scanner-internal rule identifier.
- `uri_path` — disambiguates multiple hits of the same rule across paths of the same target.

## Target Silver tables

`silver.findings` discriminated by `category="dast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "dast"` literally.

`transform.py` MUST emit a join against `silver.deployments` to resolve `target` (URL, host, port, path-prefix) into `application_id`. Unmatched targets are emitted unchanged for inventory-gap analysis (this is a deliberate completeness signal — do NOT drop rows; do NOT raise a DQ failure on the unmatched path). Code shape:

```python
silver_df = bronze_df.join(
    spark.table("silver.deployments"),
    on=match_target_expr,
    how="left",
)
```

The exact match expression depends on the source's `target` shape; the connector page documents it. Generate the join, do not stub it.

## Authentication norms

Style-dependent:

- **Server-based**: API key (e.g. `X-ZAP-API-Key` header for ZAP). `ingest.py` reads it via the helper in `src/platform/`; `config.yml` references the secret-scope key name.
- **CI/CD-step / CLI-artefact**: no native auth on output files; access governed by object-storage IAM. `ingest.py` uses the autoloader / cloud-storage helpers; no auth code emitted.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **DAST scan-report ingestion is typically artefact-driven** — autoloader-style on the object-storage prefix is the canonical pattern. This is the documented exception to the preference order; justify in a top-of-file comment in `ingest.py`.
- Server-based DAST consuming a live API uses the SDK or dlt path.

## Quirks

- **Target vs file.** DAST findings reference a URL, not a repository file. The transform-time join against `silver.deployments` is mandatory; do NOT attempt application linkage at ingest. The generator MUST wire the join (see Target Silver tables above).
- **Inventory-gap analysis.** Unmatched targets are emitted unchanged — this is intentional. Do NOT generate filter logic that drops them.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. The connector treats scans as the unit of incremental work — record-level updates within a scan are not exposed by the source, so the transform MUST NOT attempt them.
- **No record-level `updated_at`.** This is the headline DAST quirk. The HWM is `scan_id` (or artefact filename) — encode it explicitly; do not fall back to a column-based HWM.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them. Encode the chosen mode in `config.yml`; emit the orchestration helpers from `src/platform/` in `ingest.py` only when the source is in scan-and-read mode.
