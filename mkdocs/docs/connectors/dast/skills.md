# DAST skills

Four skills cover the connector lifecycle for DAST sources. Each carries a DAST-specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: DAST reference

Facts the analyze-source skill needs to write a complete Reference section for a DAST source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. DAST sources emit findings against deployed targets.

- Apply for server-based DAST (the OWASP ZAP profile in the traceability matrix): `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST, `REQ-ING-AUTH`, `REQ-ING-PAG`, and `REQ-ING-RL` may be N/A. The catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit" because the connector reads scan reports rather than driving the live API for finding retrieval. The ZAP traceability row marks these three as N/A.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

### Default severity

`medium`. DAST severity vocabularies are shorter than SAST (typically four levels, for example `Informational`, `Low`, `Medium`, `High`). Per-source lookup tables at `src/connectors/{source}/severity.yml` map each value to the standardized four-level model. Undocumented values fall through to `medium` and trigger a data-quality warning.

### Incremental strategy

Scan-report-based, NOT record-level `updated_at`. Per the DAST capability scope, the incremental strategy is one ingestion per scan completion, with full reload within the scope of a scan:

- **Server-based tools** (ZAP daemon / API): the **scan ID** is the high-water mark. The connector orchestrates scans per deployment and reads alerts back after scan completion.
- **CI/CD-step tools** (`zap-baseline.py`): the **artefact file** (object-storage prefix or pipeline artefact) is the high-water mark.

Findings from prior scans remain queryable for audit. The Incremental hook fact in the Reference section MUST disclose this scan-scoped HWM model. It is the single biggest deviation from SAST / SCA.

### Deduplication key

`(target, alert_id, uri_path)` per the DAST capability scope, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`.

- `target` identifies the scanned deployment (host, base URL).
- `alert_id` is the scanner-internal rule identifier.
- `uri_path` disambiguates multiple hits of the same rule across paths of the same target.

The Resource schema excerpt of the Reference section MUST extract these three fields.

### Target Silver tables

`silver.findings` discriminated by `category="dast"`. Application linkage requires resolving `target` against `silver.deployments`. Unmatched URLs are emitted for inventory-gap analysis. The Reference section MUST document this resolution requirement so generate-connector wires the Bronze-to-Silver join correctly.

### Authentication norms

Style-dependent per the DAST capability scope:

- **Server-based**: API key (for example, the ZAP API key supplied via `X-ZAP-API-Key` header, configured at daemon startup).
- **CI/CD-step**: no native authentication on the output files. Access is governed by the IAM policy on the object-storage bucket.

The Reference section MUST disclose the auth path matching the deployment style.

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. DAST scan-report ingestion is typically artefact-driven (autoloader-style on the object-storage prefix) rather than API-driven. The artefact-collection pattern is the documented exception to the preference order.

### Quirks

- **Target vs file.** DAST findings reference a URL rather than a repository file. Application linkage requires resolving `target` against `silver.deployments` at transform time, not at ingestion. The Quirks fact in the Reference section MUST disclose this.
- **Inventory-gap analysis.** Unmatched targets (URLs with no matching deployment record) are emitted for inventory-gap analysis rather than dropped. This is a deliberate completeness signal, not a DQ failure.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. The connector MUST treat scans as the unit of incremental work, not individual findings. Mid-scan record updates are not exposed.
- **No record-level `updated_at`.** This is the key DAST quirk versus SAST / SCA. The Incremental hook fact in the Reference section records this absence and the scan-ID / artefact-file HWM in its place.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them. The Reference section MUST disclose which mode the connector operates in.

*Rendered from `.claude/skills/analyze-source/references/dast.md`. Source-of-truth lives in the skill file.*

## provision-source: DAST reference

Facts the provision-source skill needs to emit the source-side runtime for a DAST source. DAST splits into two sub-shapes that drive a single auto-deriver decision: presence of `kubernetes_deployment` in `runtime/main.tf` selects daemon, presence of only a `terraform_data` no-op selects CI/CD-step.

### Sub-shape A: daemon (server-based, OWASP ZAP pattern)

`runtime_provisioner: terraform-aws-eks-daemon`. Provider stack: `aws` + `kubernetes` + `random`. The runtime deploys a long-lived scanner daemon on an existing EKS cluster as a `Deployment` (`replicas = 1`) with a `LoadBalancer` Service exposing the daemon publicly on `var.service_port`. The daemon's REST API is gated by a 40-character random API key generated by `random_password` and surfaced into the pod via a Kubernetes Secret bound to an env var (default `ZAP_API_KEY`).

Required `operational.yml.source_runtime` fields when daemon: `runtime_provisioner`, `aws_region_var_name`, `eks_cluster_name_var_name`, `daemon_image_default` (e.g. `owasp/zap2docker-stable:2.14.0`), `daemon_command` (full daemon argv with `api.key=$(ZAP_API_KEY)` and `api.addrs.addr.{name,regex}=...`), `api_key_secret_name`, `api_key_env_var_name`. Optional with category defaults: `project_prefix_default`, `namespace_default` (e.g. `zap`), `service_port_default` (`8080`), `container_port` (`8080`), `api_key_length` (`40`).

Outputs: `{source}_namespace`, `{source}_url` (may report `http://pending:...` on first apply while AWS provisions the ELB — re-run apply once the LoadBalancer hostname resolves), `{source}_api_key` (sensitive), `{source}_api_key_secret_name`.

> **Security note (carried into the page):** the daemon ships with `api.addrs.addr.name=.*` + `api.addrs.addr.regex=true`, which whitelists *all caller IPs*. Combined with the public LoadBalancer Service, the API is internet-facing and the only access control is the random API key. **Production deployments should front the daemon with a Kubernetes NetworkPolicy, a private (`internal`-mode) LoadBalancer, or a VPN gateway**, and consider tightening `api.addrs.addr.*` to a specific caller IP or range.

No `runtime/files/*` sidecars by default. If an operator needs custom scanner policies, they author `runtime/files/zap-context.xml` (or analogue) and the runtime mounts it via a ConfigMap referenced from `main.tf` — the skill emits the reference but never the file body.

### Sub-shape B: CI/CD-step (no canonical follower yet)

`runtime_provisioner: terraform-null-cicd-step`. Provider stack: `hashicorp/null` only. The runtime is a no-op smoke-test placeholder; `runtime/install.sh` prints the operator-facing setup-already-done message at apply and exits cleanly. The actual DAST scanning is operator-authored at the CI/CD step layer (e.g. `zap-baseline.py` in a GitHub Actions workflow), and the connector page documents how the operator wires their CI to drop scan output where the connector ingests from.

Required fields when CI/CD-step: `runtime_provisioner`, `ci_step_setup_message`. Optional: `ci_workflow_pointers` (default `["./examples/end-to-end-demo/.github/workflows/scan.yml"]`).

No `runtime/files/*` for this sub-shape — CI workflow YAML lives in `examples/end-to-end-demo/`, outside the connector tree, because it spans multiple connectors.

### `runtime/install.sh` shape

Daemon: standard `terraform init` + `terraform apply -auto-approve` wrapper, with TF_VAR exports for `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EKS_CLUSTER_NAME`, plus optional `NAMESPACE_NAME`, `{SOURCE_UPPER}_IMAGE`, `SERVICE_PORT`. Prints the LoadBalancer-pending caveat after apply.

CI/CD-step: a heredoc message about CI-layer setup, the `ci_workflow_pointers` list, and a smoke-test `terraform apply` that resolves the no-op sentinel.

### Page §Source provisioning section template

For daemon: a paragraph documenting that the module deploys an `{source}` daemon container with a public LoadBalancer Service, the security note (verbatim), the required runtime inputs at a glance (`aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `eks_cluster_name`), the apply command, and the LoadBalancer-pending re-apply note.

For CI/CD-step: a short paragraph noting the runtime is a no-op placeholder for structural parity, with a cross-link to `examples/end-to-end-demo/.github/workflows/scan.yml` as the reference CI integration. The smoke-test `terraform apply` is documented for completeness.

*Rendered from `.claude/skills/provision-source/references/dast.md`. Source of truth lives in the skill file.*

## generate-connector: DAST reference

Facts the generate-connector skill needs to emit a DAST connector module. DAST sources emit findings against deployed targets. The HWM is scan-scoped, not record-level.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST consuming scan reports rather than the live API, `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A. The catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The ZAP traceability row marks these three N/A. Do NOT bind them in this case.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

### Default severity

`medium`. Generate `src/connectors/{source}/severity.yml` covering the documented vocabulary (typically four levels: `Informational`, `Low`, `Medium`, `High`) mapped to the standardized four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: src/connectors/{source}/severity.yml
```

### Incremental strategy

Scan-id-based, NOT record-level `updated_at`. Encode in `config.yml` under a `hwm_kind: scan_id` knob (or `hwm_kind: artefact_prefix` for CLI variants):

- **Server-based** (ZAP daemon / API): the scan ID is the high-water mark. The connector orchestrates scans per deployment and reads alerts back after scan completion. Encode the scan-orchestration mode (`scan-and-read` vs `read-only`) explicitly in `config.yml`.
- **CI/CD-step** (e.g. `zap-baseline.py`): the artefact file (object-storage prefix or pipeline artefact) is the high-water mark. Encode the prefix and report format (JSON / SARIF) in `config.yml`.

The `src/platform/` HWM helpers expose a `scan_id` mode in addition to the column-based default; use it.

### Deduplication key

`(target, alert_id, uri_path)` per the DAST capability scope, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["target"], row["alert_id"], row["uri_path"])
```

- `target`: the scanned deployment (host, base URL).
- `alert_id`: the scanner-internal rule identifier.
- `uri_path`: disambiguates multiple hits of the same rule across paths of the same target.

### Target Silver tables

`silver.findings` discriminated by `category="dast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "dast"` literally.

`transform.py` MUST emit a join against `silver.deployments` to resolve `target` (URL, host, port, path-prefix) into `application_id`. Unmatched targets are emitted unchanged for inventory-gap analysis (this is a deliberate completeness signal: do NOT drop rows; do NOT raise a DQ failure on the unmatched path). Code structure:

```python
silver_df = bronze_df.join(
    spark.table("silver.deployments"),
    on=match_target_expr,
    how="left",
)
```

The exact match expression depends on the `target` structure of the source. The connector page documents it. Generate the join, do not stub it.

### Authentication norms

Style-dependent:

- **Server-based**: API key (e.g. `X-ZAP-API-Key` header for ZAP). `ingest.py` reads it via the helper in `src/platform/`; `config.yml` references the secret-scope key name.
- **CI/CD-step / CLI-artefact**: no native auth on output files; access governed by object-storage IAM. `ingest.py` uses the autoloader / cloud-storage helpers; no auth code emitted.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **DAST scan-report ingestion is typically artefact-driven**. Autoloader-style on the object-storage prefix is the standard pattern. This is the documented exception to the preference order; justify in a top-of-file comment in `ingest.py`.
- Server-based DAST consuming a live API uses the SDK or dlt path.

### Quirks

- **Target vs file.** DAST findings reference a URL, not a repository file. The transform-time join against `silver.deployments` is mandatory. Do NOT attempt application linkage at ingest. The generator MUST wire the join (see Target Silver tables above).
- **Inventory-gap analysis.** Unmatched targets are emitted unchanged. This is intentional. Do NOT generate filter logic that drops them.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. The connector treats scans as the unit of incremental work. Record-level updates within a scan are not exposed by the source, so the transform MUST NOT attempt them.
- **No record-level `updated_at`.** This is the headline DAST quirk. The HWM is `scan_id` (or artefact filename). Encode it explicitly; do not fall back to a column-based HWM.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them. Encode the chosen mode in `config.yml`. Emit the orchestration helpers from `src/platform/` in `ingest.py` only when the source is in scan-and-read mode.

### Databricks-side production-shape

In addition to the eight-file core, generate-connector emits the **Databricks-side production-shape** for DAST connectors. The skill reads `operational.yml.databricks_runtime` to interpolate the templates.

The DAST `databricks_runtime` schema covers seventeen fields and encodes BOTH sub-shapes (CI/CD-step CLI artefact + server daemon) so a single deployment can carry both at once: `secret_scope`, `bronze_schema`, `bronze_tables`, `cron_schedule` (default `0 */15 * * * ?` — every 15 min), `uc_catalog_var`, `job_name`, `default_target`, `default_catalog`, `secret_env_vars`, `tool_source_label`, `entry_wrappers` (`false` for OWASP ZAP — `resources/job.yml` points at `../ingest.py` directly), `bronze_volume` (e.g. `zap_artifacts`), `bronze_volume_storage_location` (e.g. `s3://${var.artifact_bucket}/zap/`), `cicd_prefix` (CI/CD-step path), `scan_orchestration_mode` (server path: `scan-and-read` or `read-only`), `daemon_secrets` (server-path secret-scope keys), and `hwm_kind` (`scan_id` or `artefact_prefix`; OWASP ZAP defaults to `artefact_prefix`).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from `databricks_runtime.secret_env_vars`. Daemon-path entries dominate (e.g. `ZAP_URL → zap_url`, `ZAP_API_KEY → zap_api_key`); CI/CD-step deployments use bucket-only secrets and the entry list narrows accordingly.
- **`scripts/install.sh`** — three-step end-to-end installer (load-secrets → `databricks bundle run {job_name}` → verify). The verify step counts rows in `{bronze_schema}.findings` and in `silver.findings WHERE tool_source = '{tool_source_label}' AND category = 'dast'`.
- **Top-level `install.sh`** — the orchestrator. DAST source-side runtime varies: the daemon path emits a non-trivial `runtime/install.sh` (provider stack `aws` + `kubernetes` + `random`), while the CI/CD-step path uses `hashicorp/null` and the runtime is a no-op smoke-test.
- **`sql/<envelope>.sql`** — N/A for DAST. The OWASP ZAP follower does not emit a `sql/` directory; bronze tables are populated by `ingest.py` directly (Auto Loader on the `cicd_prefix` for the CI/CD-step path; REST writes for the daemon path).
- **`resources/` extras** — alongside `resources/{source}-job.yml` (15-min cron, no entry wrappers), DAST emits `resources/schemas.yml` (bronze only) and `resources/volumes.yml` (REQUIRED — UC Volume of type `EXTERNAL` backing the `cicd_prefix`, with `storage_location` matching `bronze_volume_storage_location`). `resources/connection.yml` and `resources/pipeline.yml` are N/A — DAST authenticates via API key through `dbutils.secrets`, not a UC connection.
- **No `*_entry.py` wrappers** — `entry_wrappers=false` for OWASP ZAP. The `resources/job.yml` `notebook_path` points at `../ingest.py` and `../transform.py` directly. A future DAST source needing notebook-widget wrappers (e.g. complex scan orchestration) would set `entry_wrappers=true` and inherit the SCM-shaped template.
- **Connector page §4–§7 templates** — §Secrets (table mapping the daemon-path env-var/secret-key pairs with the load-secrets command), §Run the job (notebook job named `{job_name}` running every 15 min; two tasks — `ingest` over `cicd_prefix` or REST against the daemon, then `transform` Bronze → silver.findings), §Verify (Bronze row counts plus a category-and-tool-source filtered Silver count), and §Troubleshooting (daemon `401 Unauthorized` with the `ZAP_API_KEY` rotation path; 0-rows-after-success split between the CI/CD-step and daemon paths; missing application linkage when the `silver.deployments` join did not match the `target` URL).

*Rendered from `.claude/skills/generate-connector/references/dast.md`. Source-of-truth lives in the skill file.*

## validate-implementation: DAST reference

Facts the validate-implementation skill needs to populate the Validation table for a DAST connector. DAST sources emit findings against deployed targets. The HWM is scan-scoped, not record-level. The CLI-artefact ingestion path is the documented N/A profile for the auth / pagination / rate-limit REQ-IDs.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The OWASP ZAP column of the traceability matrix is the authoritative per-source row for this category. `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` read `N/A`; the rest read `PASS`.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS`
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-AUTH`, N/A: quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit."
- `REQ-ING-PAG`, N/A: same rationale.
- `REQ-ING-RL`, N/A: same rationale.

For server-based DAST consuming a live API (rather than scan-report artefacts), the same N/A profile applies because the incremental work for the connector is scan-scoped. There is no API pagination across findings within a scan, and rate limits do not bind on scan-report reads. If a deployment exercises a paginated live-API endpoint, bind tests for the affected REQ-IDs and mark them `PASS`; otherwise retain the N/A profile from the catalog.

### Default severity

`medium` configurable default per `mkdocs/docs/connectors/dast/index.md` § "Capability scope". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented vocabulary (typically `Informational`, `Low`, `Medium`, `High`) and asserting that undocumented values fall through with a data-quality warning per the catalog requirement text.

### Incremental strategy

Scan-id-based, NOT record-level `updated_at`, per `mkdocs/docs/connectors/dast/index.md` § "Capability scope". The connector encodes `hwm_kind: scan_id` (server-based) or `hwm_kind: artefact_prefix` (CI/CD CLI). The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the chosen mode. Record-level resume is NOT exercised because the source does not expose it.

### Deduplication key

`(target, alert_id, uri_path)` per `mkdocs/docs/connectors/dast/index.md` § "Canonical mapping contribution" (Silver finding scope `(application_id, target, alert_id)`). The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

### Target Silver tables

`silver.findings` discriminated by `category="dast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test additionally verifies the join against `silver.deployments` to resolve `target` into `application_id`. Unmatched targets are NOT dropped (the test asserts they pass through unchanged for inventory-gap analysis, per `mkdocs/docs/connectors/dast/index.md` § "Capability scope": "Unmatched URLs are emitted for inventory-gap analysis.").

### Authentication norms

Style-dependent per `mkdocs/docs/connectors/dast/index.md` § "Capability scope": server-based uses an API key (e.g. `X-ZAP-API-Key` header); CI/CD-step / CLI-artefact has no native auth (object-storage IAM governs access). The test suite omits `REQ-ING-AUTH` for CLI-artefact connectors per the documented N/A profile in the catalog.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. DAST scan-report ingestion is typically artefact-driven (autoloader-style on the object-storage prefix). This is the documented exception. The validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

### Quirks

- **Target vs file.** `REQ-TRF-MAP` asserts the transform-time join against `silver.deployments`. Application linkage at ingest is forbidden. The test fails if an `application_id` is resolved before transform.
- **Inventory-gap analysis.** The `REQ-TRF-MAP` (or a dedicated `REQ-DQ`) test asserts that unmatched targets are emitted unchanged. Filter logic that drops them is a `FAIL`.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. `REQ-DEDUP` asserts that re-emission across scans collapses through the dedup key without double-counting.
- **No record-level `updated_at`.** This is the headline DAST quirk. `REQ-ING-HWM` exercises `scan_id` (or `artefact_prefix`) advancement, NOT a column-based HWM.
- **Scan orchestration vs report collection.** Server-based scan-and-read mode exercises `REQ-ING-HWM` against scan-id advancement plus the orchestration helpers. Report-only mode binds the same REQ-ID against the artefact-prefix HWM.

*Rendered from `.claude/skills/validate-implementation/references/dast.md`. Source-of-truth lives in the skill file.*
