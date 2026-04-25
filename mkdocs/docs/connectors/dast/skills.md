# DAST skills

Three skills cover the connector lifecycle for DAST sources. Each carries a DAST-specific reference; the procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source — DAST reference

Facts the analyze-source skill needs to write a complete Reference section for a DAST source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. DAST sources emit findings against deployed targets.

- Apply for server-based DAST (the OWASP ZAP shape in the traceability matrix): `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST, `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A — the catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit" because the connector reads scan reports rather than driving the live API for finding retrieval. The ZAP traceability row marks these three as N/A.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

### Default severity

`medium`. DAST severity vocabularies are shorter than SAST (typically four levels, for example `Informational`, `Low`, `Medium`, `High`). Per-source lookup tables at `config/severity/{source}.yml` map each value to the canonical four-level model. Undocumented values fall through to `medium` and trigger a data-quality warning.

### Incremental strategy

Scan-report-based, NOT record-level `updated_at`. Per the DAST capability surface, the incremental strategy is one ingestion per scan completion, with full reload within a scan's scope:

- **Server-based tools** (ZAP daemon / API): the **scan ID** is the high-water mark; the connector orchestrates scans per deployment and reads alerts back after scan completion.
- **CI/CD-step tools** (`zap-baseline.py`): the **artefact file** (object-storage prefix or pipeline artefact) is the high-water mark.

Findings from prior scans remain queryable for audit. The Reference section's Incremental hook fact MUST disclose this scan-scoped HWM model — it is the single biggest deviation from SAST / SCA.

### Deduplication key

`(target, alert_id, uri_path)` per the DAST capability surface, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`.

- `target` identifies the scanned deployment (host, base URL).
- `alert_id` is the scanner-internal rule identifier.
- `uri_path` disambiguates multiple hits of the same rule across paths of the same target.

The Reference section's Resource schema excerpt MUST extract these three fields.

### Target Silver tables

`silver.findings` discriminated by `category="dast"`. Application linkage requires resolving `target` against `silver.deployments`; unmatched URLs are emitted for inventory-gap analysis. The Reference section MUST document this resolution requirement so generate-connector wires the Bronze-to-Silver join correctly.

### Authentication norms

Style-dependent per the DAST capability surface:

- **Server-based**: API key (for example, the ZAP API key supplied via `X-ZAP-API-Key` header, configured at daemon startup).
- **CI/CD-step**: no native authentication on the output files; access is governed by the object-storage bucket's IAM policy.

The Reference section MUST disclose the auth path matching the deployment style.

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. DAST scan-report ingestion is typically artefact-driven (autoloader-style on the object-storage prefix) rather than API-driven; the artefact-collection pattern is the documented exception to the preference order.

### Quirks

- **Target vs file.** DAST findings reference a URL rather than a repository file. Application linkage requires resolving `target` against `silver.deployments` at transform time, not at ingestion. The Reference section's Quirks fact MUST disclose this.
- **Inventory-gap analysis.** Unmatched targets (URLs with no matching deployment record) are emitted for inventory-gap analysis rather than dropped — this is a deliberate completeness signal, not a DQ failure.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope; the connector MUST treat scans as the unit of incremental work, not individual findings. Mid-scan record updates are not exposed.
- **No record-level `updated_at`.** This is the key DAST quirk versus SAST / SCA. The Reference section's Incremental hook fact records this absence and the scan-ID / artefact-file HWM in its place.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them; the Reference section MUST disclose which mode the connector operates in.

*Rendered from `.claude/skills/analyze-source/references/dast.md`. Source-of-truth lives in the skill file.*

## generate-connector — DAST reference

Facts the generate-connector skill needs to emit a DAST connector module. DAST sources emit findings against deployed targets; the HWM is scan-scoped, not record-level.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST consuming scan reports rather than the live API, `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — the catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The ZAP traceability row marks these three N/A. Do NOT bind them in this case.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

### Default severity

`medium`. Generate `config/severity/{source}.yml` covering the documented vocabulary (typically four levels: `Informational`, `Low`, `Medium`, `High`) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

### Incremental strategy

Scan-id-based, NOT record-level `updated_at`. Encode in `config.yml` under a `hwm_kind: scan_id` knob (or `hwm_kind: artefact_prefix` for CLI variants):

- **Server-based** (ZAP daemon / API): the scan ID is the high-water mark. The connector orchestrates scans per deployment and reads alerts back after scan completion. Encode the scan-orchestration mode (`scan-and-read` vs `read-only`) explicitly in `config.yml`.
- **CI/CD-step** (e.g. `zap-baseline.py`): the artefact file (object-storage prefix or pipeline artefact) is the high-water mark. Encode the prefix and report format (JSON / SARIF) in `config.yml`.

The `src/common/` HWM helpers expose a `scan_id` mode in addition to the column-based default; use it.

### Deduplication key

`(target, alert_id, uri_path)` per the DAST capability surface, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["target"], row["alert_id"], row["uri_path"])
```

- `target` — the scanned deployment (host, base URL).
- `alert_id` — the scanner-internal rule identifier.
- `uri_path` — disambiguates multiple hits of the same rule across paths of the same target.

### Target Silver tables

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

### Authentication norms

Style-dependent:

- **Server-based**: API key (e.g. `X-ZAP-API-Key` header for ZAP). `ingest.py` reads it via the helper in `src/common/`; `config.yml` references the secret-scope key name.
- **CI/CD-step / CLI-artefact**: no native auth on output files; access governed by object-storage IAM. `ingest.py` uses the autoloader / cloud-storage helpers; no auth code emitted.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **DAST scan-report ingestion is typically artefact-driven** — autoloader-style on the object-storage prefix is the canonical pattern. This is the documented exception to the preference order; justify in a top-of-file comment in `ingest.py`.
- Server-based DAST consuming a live API uses the SDK or dlt path.

### Quirks

- **Target vs file.** DAST findings reference a URL, not a repository file. The transform-time join against `silver.deployments` is mandatory; do NOT attempt application linkage at ingest. The generator MUST wire the join (see Target Silver tables above).
- **Inventory-gap analysis.** Unmatched targets are emitted unchanged — this is intentional. Do NOT generate filter logic that drops them.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. The connector treats scans as the unit of incremental work — record-level updates within a scan are not exposed by the source, so the transform MUST NOT attempt them.
- **No record-level `updated_at`.** This is the headline DAST quirk. The HWM is `scan_id` (or artefact filename) — encode it explicitly; do not fall back to a column-based HWM.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them. Encode the chosen mode in `config.yml`; emit the orchestration helpers from `src/common/` in `ingest.py` only when the source is in scan-and-read mode.

*Rendered from `.claude/skills/generate-connector/references/dast.md`. Source-of-truth lives in the skill file.*

## validate-implementation — DAST reference

Facts the validate-implementation skill needs to populate the Validation table for a DAST connector. DAST sources emit findings against deployed targets; the HWM is scan-scoped, not record-level. The CLI-artefact ingestion path is the documented N/A profile for the auth / pagination / rate-limit REQ-IDs.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The OWASP ZAP column of the traceability matrix is the authoritative per-source row for this category — `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` read `N/A`; the rest read `PASS`.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS`
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-AUTH` — N/A: quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit."
- `REQ-ING-PAG` — N/A: same rationale.
- `REQ-ING-RL` — N/A: same rationale.

For server-based DAST consuming a live API (rather than scan-report artefacts), the same N/A profile applies because the connector's incremental work is scan-scoped — there is no API pagination across findings within a scan, and rate limits do not bind on scan-report reads. If a deployment exercises a paginated live-API surface, bind tests for the affected REQ-IDs and mark them `PASS`; otherwise retain the catalog's N/A profile.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/dast/index.md` § "Capability surface". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented vocabulary (typically `Informational`, `Low`, `Medium`, `High`) and asserting that undocumented values fall through with a data-quality warning per the catalog requirement text.

### Incremental strategy

Scan-id-based, NOT record-level `updated_at`, per `mkdocs/docs/connectors/dast/index.md` § "Capability surface". The connector encodes `hwm_kind: scan_id` (server-based) or `hwm_kind: artefact_prefix` (CI/CD CLI). The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the chosen mode — record-level resume is NOT exercised because the source does not expose it.

### Deduplication key

`(target, alert_id, uri_path)` per `mkdocs/docs/connectors/dast/index.md` § "Canonical mapping contribution" (Silver finding scope `(application_id, target, alert_id)`). The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

### Target Silver tables

`silver.findings` discriminated by `category="dast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test additionally verifies the join against `silver.deployments` to resolve `target` into `application_id`; unmatched targets are NOT dropped (the test asserts they pass through unchanged for inventory-gap analysis, per `mkdocs/docs/connectors/dast/index.md` § "Capability surface": "Unmatched URLs are emitted for inventory-gap analysis.").

### Authentication norms

Style-dependent per `mkdocs/docs/connectors/dast/index.md` § "Capability surface": server-based uses an API key (e.g. `X-ZAP-API-Key` header); CI/CD-step / CLI-artefact has no native auth (object-storage IAM governs access). The test suite omits `REQ-ING-AUTH` for CLI-artefact connectors per the catalog's documented N/A profile.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. DAST scan-report ingestion is typically artefact-driven (autoloader-style on the object-storage prefix) — this is the documented exception. The validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

### Quirks

- **Target vs file.** `REQ-TRF-MAP` asserts the transform-time join against `silver.deployments`. Application linkage at ingest is forbidden; the test fails if an `application_id` is resolved before transform.
- **Inventory-gap analysis.** The `REQ-TRF-MAP` (or a dedicated `REQ-DQ`) test asserts that unmatched targets are emitted unchanged. Filter logic that drops them is a `FAIL`.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. `REQ-DEDUP` asserts that re-emission across scans collapses through the dedup key without double-counting.
- **No record-level `updated_at`.** This is the headline DAST quirk. `REQ-ING-HWM` exercises `scan_id` (or `artefact_prefix`) advancement, NOT a column-based HWM.
- **Scan orchestration vs report collection.** Server-based scan-and-read mode exercises `REQ-ING-HWM` against scan-id advancement plus the orchestration helpers; report-only mode binds the same REQ-ID against the artefact-prefix HWM.

*Rendered from `.claude/skills/validate-implementation/references/dast.md`. Source-of-truth lives in the skill file.*
