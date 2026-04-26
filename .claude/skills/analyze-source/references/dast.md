# analyze-source — DAST reference

Facts the analyze-source skill needs to write a complete Reference section for a DAST source.

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

From `mkdocs/docs/platform/reference/catalog.md`. DAST sources emit findings against deployed targets.

- Apply for server-based DAST (the OWASP ZAP shape in the traceability matrix): `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST, `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A — the catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit" because the connector reads scan reports rather than driving the live API for finding retrieval. The ZAP traceability row marks these three as N/A.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

## Default severity

`medium`. DAST severity vocabularies are shorter than SAST (typically four levels, for example `Informational`, `Low`, `Medium`, `High`). Per-source lookup tables at `config/severity/{source}.yml` map each value to the canonical four-level model. Undocumented values fall through to `medium` and trigger a data-quality warning.

## Incremental strategy

Scan-report-based, NOT record-level `updated_at`. Per the DAST capability surface, the incremental strategy is one ingestion per scan completion, with full reload within a scan's scope:

- **Server-based tools** (ZAP daemon / API): the **scan ID** is the high-water mark; the connector orchestrates scans per deployment and reads alerts back after scan completion.
- **CI/CD-step tools** (`zap-baseline.py`): the **artefact file** (object-storage prefix or pipeline artefact) is the high-water mark.

Findings from prior scans remain queryable for audit. The Reference section's Incremental hook fact MUST disclose this scan-scoped HWM model — it is the single biggest deviation from SAST / SCA.

## Deduplication key

`(target, alert_id, uri_path)` per the DAST capability surface, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`.

- `target` identifies the scanned deployment (host, base URL).
- `alert_id` is the scanner-internal rule identifier.
- `uri_path` disambiguates multiple hits of the same rule across paths of the same target.

The Reference section's Resource schema excerpt MUST extract these three fields.

## Target Silver tables

`silver.findings` discriminated by `category="dast"`. Application linkage requires resolving `target` against `silver.deployments`; unmatched URLs are emitted for inventory-gap analysis. The Reference section MUST document this resolution requirement so generate-connector wires the Bronze-to-Silver join correctly.

## Authentication norms

Style-dependent per the DAST capability surface:

- **Server-based**: API key (for example, the ZAP API key supplied via `X-ZAP-API-Key` header, configured at daemon startup).
- **CI/CD-step**: no native authentication on the output files; access is governed by the object-storage bucket's IAM policy.

The Reference section MUST disclose the auth path matching the deployment style.

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. DAST scan-report ingestion is typically artefact-driven (autoloader-style on the object-storage prefix) rather than API-driven; the artefact-collection pattern is the documented exception to the preference order.

## Quirks

- **Target vs file.** DAST findings reference a URL rather than a repository file. Application linkage requires resolving `target` against `silver.deployments` at transform time, not at ingestion. The Reference section's Quirks fact MUST disclose this.
- **Inventory-gap analysis.** Unmatched targets (URLs with no matching deployment record) are emitted for inventory-gap analysis rather than dropped — this is a deliberate completeness signal, not a DQ failure.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope; the connector MUST treat scans as the unit of incremental work, not individual findings. Mid-scan record updates are not exposed.
- **No record-level `updated_at`.** This is the key DAST quirk versus SAST / SCA. The Reference section's Incremental hook fact records this absence and the scan-ID / artefact-file HWM in its place.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them; the Reference section MUST disclose which mode the connector operates in.

## Lakeflow Connect availability

No source in the dast category appears in the analyze-source LFC managed-source catalogue today. Resolution: category-canonical default applies — `sdk_dlt` for REST/SDK sources; `artifact_path` for CLI-tool / artefact-driven sources (per the documented exception in this file's "## Ingestion-tooling preference" / "## Quirks" sections).
