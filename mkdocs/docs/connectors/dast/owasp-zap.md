# OWASP ZAP

## 1. Overview

OWASP ZAP (Zed Attack Proxy) is the reference DAST source for the platform. It is a hybrid connector: the same logical source serves two operationally distinct ingestion paths, both of which land into `bronze_owasp_zap` and project into `silver.findings` discriminated by `category="dast"`.

- **CI/CD artefact path.** `zap-baseline.py` (and its siblings `zap-full-scan.py` and `zap-api-scan.py`) run inside CI/CD pipelines against freshly deployed applications and emit JSON or SARIF reports. Pipelines push those reports to an object-storage prefix (`cicd/zap/<pipeline-run>/...`); the connector autoloads from that prefix.
- **On-demand server path.** The ZAP daemon exposes a REST API ([`https://www.zaproxy.org/docs/api/`](https://www.zaproxy.org/docs/api/)). The connector drives scans against targets drawn from `silver.deployments`, polls for completion, and reads alerts back via `/JSON/alert/view/alerts/`.

**Category:** DAST (hybrid — server + CI/CD step) · **Integration patterns:** Artefact path (Autoloader on object storage) and REST/daemon (scan orchestration).

Bronze schema: `bronze_owasp_zap`. Cross-source contribution: `silver.findings` with `tool_source = 'owasp_zap'` and `category = 'dast'`. Application linkage is resolved at transform time by joining `target` (the scanned URL) against `silver.deployments`; unmatched URLs are emitted for inventory-gap analysis rather than dropped.

OWASP ZAP is in MVP scope: it is the reference DAST connector listed in the traceability matrix at [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md).

## 2. Prerequisites

The two ingestion paths have different prerequisites; both can coexist on the same connector instance.

**CI/CD artefact path.**

- A CI/CD pipeline running `zap-baseline.py`, `zap-full-scan.py`, or `zap-api-scan.py` against the deployed application. See [`https://www.zaproxy.org/docs/docker/baseline-scan/`](https://www.zaproxy.org/docs/docker/baseline-scan/).
- An object-storage bucket (S3 or equivalent) with a prefix the pipeline writes JSON/SARIF reports to: `cicd/zap/<pipeline-run-id>/<scan>.json`. The connector reads from this prefix via Auto Loader.
- The Databricks workspace must have an instance profile (or storage credential) with `s3:ListBucket` and `s3:GetObject` on the bucket and prefix. No native authentication exists on the report files themselves; access is governed by the bucket IAM policy.

**On-demand server path.**

- A reachable ZAP daemon (`zap.sh -daemon -host 0.0.0.0 -port 8080 -config api.key=<KEY>`) on a host the Databricks workspace can route to. Default listen port is `8080`; configurable via `-port`.
- An API key, configured at daemon startup via `-config api.key=<KEY>`. The key is required on every API request as the `apikey` query parameter; ZAP rejects requests with a missing or wrong key. This is the documented anti-CSRF defence in [`https://www.zaproxy.org/docs/api/`](https://www.zaproxy.org/docs/api/) ("used to prevent malicious sites from accessing ZAP APIs").
- A target inventory: `silver.deployments` populated with the URLs the connector should scan. Unmatched scan results land in the inventory-gap table.

Secrets land in the `mvp-connectors` Databricks secret scope; the loader script and key names are documented in §4 (Setup).

## 3. Reference

### API surface

OWASP ZAP exposes two ingestion-bearing surfaces that the connector consumes.

**Server-based REST API** ([docs](https://www.zaproxy.org/docs/api/)). The ZAP daemon serves a REST API at `http://<host>:<port>/<format>/<component>/<operation>/<operation-name>/`, where `<format>` is one of `JSON`, `XML`, `HTML`, or `OTHER`. The connector uses `JSON`. Endpoints consumed:

- `GET /JSON/spider/action/scan/?url=<target>&apikey=<key>` — kicks off a spider crawl. Returns `{"scan": "<scanId>"}` (the scan ID is a small non-negative integer assigned per ZAP process).
- `GET /JSON/spider/view/status/?scanId=<id>&apikey=<key>` — returns spider progress as a percentage (`0`–`100`). The connector polls until `100`.
- `GET /JSON/ascan/action/scan/?url=<target>&apikey=<key>` — kicks off an active scan. Returns `{"scan": "<scanId>"}`.
- `GET /JSON/ascan/view/status/?scanId=<id>&apikey=<key>` — returns active-scan progress as a percentage. The connector polls until `100`.
- `GET /JSON/alert/view/alerts/?baseurl=<target>&start=<offset>&count=<limit>&apikey=<key>` — returns alerts (findings) recorded for `baseurl`. Both passive and active scan results are consolidated here.
- `GET /JSON/alert/view/alertsSummary/?baseurl=<target>&apikey=<key>` — returns a count summary by risk level. Used for sanity-checking the paged alert pulls.
- `GET /JSON/core/view/sites/?apikey=<key>` — enumerates the sites ZAP has seen during scans.
- `GET /JSON/core/view/version/?apikey=<key>` — returns the ZAP version. Used at connector startup for compatibility checks.

Authentication: the API key is supplied as the `apikey` query parameter on every request, configured at daemon startup with `-config api.key=<KEY>`. ZAP does not support OAuth, basic auth, or per-user tokens for its API; the single shared key is the documented mechanism.

**CI/CD artefact path** ([docs](https://www.zaproxy.org/docs/automate/) and [`https://www.zaproxy.org/docs/docker/baseline-scan/`](https://www.zaproxy.org/docs/docker/baseline-scan/)). The packaged scans `zap-baseline.py`, `zap-full-scan.py`, and `zap-api-scan.py` run inside CI/CD pipelines (typically as Docker containers via `softwaresecurityproject/zap-stable` or via the GitHub Actions wrappers). They emit reports via the following flags:

- `-J <file>` — JSON report (the format the connector consumes).
- `-r <file>` — HTML report (operator artefact, not parsed).
- `-x <file>` — XML report (not parsed).
- `-w <file>` — Markdown report (not parsed).

Exit codes per the ZAP baseline-scan documentation: `0` success, `1` "At least 1 FAIL", `2` "At least one WARN and no FAILs", `3` any other failure. The connector treats the presence of the JSON artefact in the bucket prefix as the success signal; CI/CD-side exit-code handling is out of band. There is no native authentication on the report files; access is governed by the object-storage bucket's IAM policy. `REQ-ING-AUTH` is N/A for the artefact path.

### Pagination and rate limits

**Server-based path.** The `/JSON/alert/view/alerts/` endpoint supports offset/limit pagination via `start` and `count` query parameters and a `baseurl` filter. The connector iterates with `start=0, count=N` and increments `start` by `count` until a short page (or empty response) is returned. The reference value for `count` is `5000` (matching the example in [the ZAP API docs](https://www.zaproxy.org/docs/api/)). ZAP does not enforce a documented per-client rate limit; throughput is bounded by daemon and host resources. The connector applies a configurable inter-request delay (default 100 ms) between paged requests and exponential backoff on transient HTTP errors. `REQ-ING-PAG` and `REQ-ING-RL` apply to the server path.

**CI/CD artefact path.** Pagination does not apply: each pipeline run produces one JSON report file. Auto Loader streams new files as they appear under the prefix. Rate limits do not apply. `REQ-ING-PAG` and `REQ-ING-RL` are N/A for the artefact path, consistent with the catalog row at [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md), which marks both N/A for ZAP.

### Incremental hook

The hybrid connector tracks two distinct high-water marks, one per path. The catalog's `REQ-ING-HWM` row applies to both.

- **`hwm_kind: scan_id`** for the **on-demand server path.** The connector records the largest numeric `scanId` it has read alerts for, scoped to each `(target, scan_kind)` pair where `scan_kind` is `spider` or `ascan`. Subsequent runs orchestrate a fresh scan, capture the new `scanId` from `/JSON/spider/action/scan/` or `/JSON/ascan/action/scan/`, poll status to completion, then read alerts back. ZAP `scanId` values are non-negative integers monotonically assigned per daemon process; the connector treats a daemon restart as an HWM reset and re-scans from `scanId=0`.
- **`hwm_kind: artefact_prefix`** for the **CI/CD artefact path.** The connector records the most recently ingested object key under `cicd/zap/`. Auto Loader's checkpoint-driven discovery is the primary mechanism; the recorded key is a secondary signal used for backfill auditing.

ZAP exposes no record-level `updateDate` or `updated_at` field on alerts — this is the canonical DAST quirk called out in the [DAST capability scope](index.md). Each scan re-emits the full finding set within its scope; the connector treats scans as the unit of incremental work, not individual findings.

### Resource schema excerpt

The fields below are the subset the connector consumes; the JSON shape is shared between the REST `/JSON/alert/view/alerts/` response and the `site.alerts[]` array in `zap-baseline.py` JSON reports.

**ZAP alert object — consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `pluginId` | string (numeric) | Stable scanner-internal rule identifier (e.g. `10038` for CSP header missing). Maps to `alert_id` in the dedup key and `rule_id` in `silver.findings`. |
| `alert` / `name` | string | Human-readable rule name (e.g. `Content Security Policy (CSP) Header Not Set`). The JSON-report flavour uses `name`; the REST-API flavour uses both — the connector reads `name` first and falls back to `alert`. |
| `risk` | string | Severity label, one of `Informational`, `Low`, `Medium`, `High` (see Enumerations). |
| `confidence` | string | Reviewer-assessed confidence: `False Positive`, `Low`, `Medium`, `High`, `Confirmed`. Preserved as a domain column in Bronze. |
| `uri` | string | Full URI where the alert fired. The connector splits this into `target` (scheme + host + port) and `uri_path` (path + query) for the dedup key. |
| `param` | string | Request parameter that triggered the alert; nullable. |
| `attack` | string | Attack payload ZAP injected; nullable. |
| `evidence` | string | Response substring confirming the issue; nullable. |
| `description` | string | Long-form rule description. |
| `solution` | string | Suggested remediation. |
| `reference` | string | URLs / CWE / WASC references (newline-separated). |
| `cweid` | string (numeric) | CWE identifier; `-1` if not mapped. |
| `wascid` | string (numeric) | WASC threat-classification identifier; `-1` if not mapped. |
| `sourceid` | string (numeric) | Source classification (passive vs active scan origin). |

The dedup key per the [DAST category reference](../../../.claude/skills/analyze-source/references/dast.md) is `(target, alert_id, uri_path)`, derived from `uri` (split) and `pluginId`. Application linkage resolves `target` against `silver.deployments` at transform time.

### Enumerations

**Severity.** ZAP risk has four documented levels — `Informational`, `Low`, `Medium`, `High`. The proposed lookup at `src/connectors/owasp_zap/severity.yml` maps `High → high`, `Medium → medium`, `Low → low`, `Informational → low` (collapsed to `low` because the canonical model has no `info` level). Per `references/dast.md`, undocumented values fall through to `medium` and trigger a data-quality warning; ZAP itself is unlikely to emit values outside the four documented levels.

**Status.** ZAP alerts have no native lifecycle state. Each scan is a complete re-detection: an alert that re-appears in the next scan is treated as `open`; one that disappears is implicitly `resolved` by absence. The proposed lookup at `src/connectors/owasp_zap/status.yml` therefore maps every ingested alert to canonical `open`; transition to `resolved` is computed at the Silver layer by comparing successive scans for the same `(target, alert_id, uri_path)` triple. `confidence` (`False Positive`, `Low`, `Medium`, `High`, `Confirmed`) is preserved as a domain column but is not folded into `status_canonical` — operators may surface it via a `gold` view if needed.

**Note on no-status sources.** Status normalization (`REQ-TRF-STS`) is exercised here because the Silver-layer status derivation is part of the transform; the catalog matrix row at [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md) marks ZAP `REQ-TRF-STS = PASS`.

### Quirks

- **Hybrid HWM split (`hwm_kind: artefact_prefix` vs `scan_id`).** This connector is the only DAST source in MVP scope that maintains two concurrent HWM kinds. The connector module's `state.hwm` schema discriminates by `path` (`cicd_artefact` or `daemon`) so the two paths advance independently. Operators should not assume a single monotonic scan ordering across both paths.
- **`scan_orchestration_mode`: scan-and-read vs read-only.** The server path operates in **scan-and-read** mode: the connector both starts ZAP scans (`/JSON/{spider,ascan}/action/scan/`) and reads their alerts (`/JSON/alert/view/alerts/`). The CI/CD artefact path operates in **read-only** mode: scans are started by the pipeline, and the connector only reads the resulting JSON reports. The connector's `config.yml` exposes `scan_orchestration_mode: scan_and_read | read_only` per path so an operator can disable scan orchestration in environments where ZAP scans are scheduled externally. This split is the load-bearing operational distinction between the two paths.
- **No record-level `updateDate`.** Per `references/dast.md`, this is the canonical DAST deviation from SAST/SCA. ZAP has no per-finding modification timestamp; each scan re-emits the full finding set. The connector treats scans as the unit of incremental work, never individual findings.
- **Target vs file.** ZAP findings reference a URL, not a repository file. Application linkage resolves `target` against `silver.deployments` at transform time, not at ingest. Unmatched targets are emitted for inventory-gap analysis (a deliberate completeness signal, not a DQ failure).
- **Daemon-process-scoped scan IDs.** Numeric `scanId` is monotonic only within a single ZAP daemon process. A daemon restart resets the counter; the connector's HWM bookkeeping records the daemon endpoint identity alongside the `scanId` so that a restart triggers a re-scan rather than an incorrect "we've already seen this" skip.
- **API key as query parameter.** Unlike most SAST/SCA APIs that use bearer tokens in the `Authorization` header, ZAP's `apikey` is a query-string parameter. The connector MUST scrub the `apikey` from any logged URL; the secret scrubber covers this case explicitly.
- **Alert `alert` vs `name` field duplication.** The REST API and JSON-report flavours of the alert object inconsistently populate `alert` vs `name`. The connector reads `name` first, then `alert`, then falls back to `pluginId` for safety.
- **`cweid` / `wascid` `-1` sentinel.** Both fields use `-1` (as a string) when unmapped. The transform converts `-1` to `NULL` before writing to Silver.

## 4. Setup

!!! info "Pending implementation details"
    Setup commands, secret-loader script invocation, bundle deployment, and first-run validation are populated by `generate-connector` in Phase 2. The eventual content covers loading `owasp_zap_url`, `owasp_zap_apikey`, and `owasp_zap_artefact_bucket` into the `mvp-connectors` secret scope; deploying the `owasp-zap-connector` job from `src/connectors/owasp_zap/resources/job.yml` via `databricks bundle deploy --target dev`; and running the connector against the seed deployment inventory.

## 5. Validation

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | — | N/A |
| `REQ-ING-PAG` | — | N/A |
| `REQ-ING-RL` | — | N/A |
| `REQ-ING-HWM` | `src/connectors/owasp_zap/tests/test_ingest.py::test_scan_id_hwm_round_trip` | PASS |
| `REQ-TRF-MAP` | `src/connectors/owasp_zap/tests/test_transform.py::test_alert_mapping` | PASS |
| `REQ-TRF-SEV` | `src/connectors/owasp_zap/tests/test_transform.py::test_severity_normalization_all_four_levels` | PASS |
| `REQ-TRF-STS` | `src/connectors/owasp_zap/tests/test_transform.py::test_status_always_open` | PASS |
| `REQ-TRF-TS` | `src/connectors/owasp_zap/tests/test_transform.py::test_first_seen_at_is_utc_aware` | PASS |
| `REQ-DQ` | `src/connectors/owasp_zap/tests/test_transform.py::test_findings_expectation_quarantines_malformed` | PASS |
| `REQ-DEDUP` | `src/connectors/owasp_zap/tests/test_transform.py::test_dedup_key_tuple_matches_mapping_yml` | PASS |

Validation summary: 19 requirement-bound tests collected across the seven applicable REQ-IDs (additional tests bind multiply to `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, and `REQ-DEDUP`); 7 PASS, 0 FAIL, 3 N/A. Wall-clock duration: 49.92 s (37 tests collected in the full suite, 33 passed, 4 skipped — 3 of which carry `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` markers and contribute the N/A rows; the fourth is a live-only ZAP-daemon connectivity test, not requirement-bound). N/A rationale per `references/dast.md`: the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit — `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` are recorded N/A on the matrix row even though the daemon path can exercise them, because the matrix outcome reflects the documented CI/CD-artefact path.

## 6. Generation log

| Stage | Skill | Inputs | Outputs | Run on | Skills repo ref |
|---|---|---|---|---|---|
| Source analysis | `analyze-source` (dast) | name=OWASP ZAP; url=https://www.zaproxy.org/docs/api/; category=dast | mkdocs/docs/connectors/dast/owasp-zap.md §1–§3 | 2026-04-25 | 3cd1028 (regenerate-4-originals) |
| Module generation | `generate-connector` (dast) | page hash=0a7a007c142c | src/connectors/owasp_zap/, src/connectors/owasp_zap/tests/, src/connectors/owasp_zap/severity.yml, src/connectors/owasp_zap/status.yml, src/connectors/owasp_zap/resources/job.yml | 2026-04-25 | 76c543e (regenerate-4-originals) |
| Validation | `validate-implementation` (dast) | module path=src/connectors/owasp_zap/ | mkdocs/docs/connectors/dast/owasp-zap.md §5 | 2026-04-25 | 7fec0ac (regenerate-4-originals) |

## References

- OWASP ZAP API documentation — [https://www.zaproxy.org/docs/api/](https://www.zaproxy.org/docs/api/)
- OWASP ZAP automation overview — [https://www.zaproxy.org/docs/automate/](https://www.zaproxy.org/docs/automate/)
- ZAP Baseline scan reference — [https://www.zaproxy.org/docs/docker/baseline-scan/](https://www.zaproxy.org/docs/docker/baseline-scan/)
- DAST category reference (in-repo) — `.claude/skills/analyze-source/references/dast.md`
- Canonical mapping requirements — [`mkdocs/docs/platform/reference/canonical-mapping.md`](../../platform/reference/canonical-mapping.md)
- Requirement catalog and traceability matrix — [`mkdocs/docs/platform/reference/catalog.md`](../../platform/reference/catalog.md)
