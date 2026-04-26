# Standard Mapping Requirements

The standard Silver layer schemas commit the framework to a single vendor agnostic entity and finding model. This page states, per schema, the requirement the implementation **SHALL** satisfy when mapping a source record into Silver.

## Silver Entity Mapping Requirements

Entity tables (applications, repositories, teams, commits, pull requests, pipeline runs, dependencies, branch policies) are populated from the entity emitting sources in the selection. The implementation **SHALL** union over the native fields these sources expose according to the table below. Every standard field maps to the source field shown in the corresponding column, with the derivation on the right. Fields marked as framework generated are assigned by the connector or transformation layer, not read from the source.

### Silver Entity Pattern field derivation across entity emitting sources

| Standard field | ServiceNow CMDB | GitHub | GitLab | Derivation |
|---|---|---|---|---|
| `id` | (generated) | (generated) | (generated) | surrogate key, framework assigned |
| `natural_key` | `sys_id` | `node_id` | `id` (`path_with_namespace` for repos) | the stable primary key in the source |
| `source_system` | `"servicenow"` | `"github"` | `"gitlab"` | literal per connector |
| `valid_from` | `sys_created_on` | `created_at` | `created_at` | creation timestamp |
| `valid_to` | (framework SCD2) | (framework SCD2) | (framework SCD2) | set on supersedure |
| Domain columns | `name`, `business_criticality`, `operational_status`, `owned_by`, ... | `full_name`, `default_branch`, `visibility`, `language`, ... | `path_with_namespace`, `default_branch`, `visibility`, `archived`, ... | attributes specific to the entity type |

## Silver Finding Mapping Requirements

All findings are populated into the single Silver Finding table `silver.findings`, discriminated by a `category` column. The implementation **SHALL** union over the native fields these sources expose according to the tables below. Standard fields marked "N/A" for a given source are stored as `NULL` in records from that source. This is the intended union over sources behavior, and the `mapping.yml` for each source makes each assignment explicit, including the `category` value of the record. The three tables group sources by finding structure. The first covers code level sources (SAST and secrets). The second covers package level and platform integrated sources (SCA, GitHub and GitLab platform native findings). The third covers runtime edge-event sources (WAF), which project each event as one finding row.

### Silver Finding derivation: code level sources (SAST and secrets)

Rows whose fields are N/A for all three sources are omitted. They appear in the next table.

| Standard field | SonarQube | Semgrep | TruffleHog |
|---|---|---|---|
| `finding_id` | (generated) | (generated) | (generated) |
| `source_finding_id` | `key` | `id` (Cloud) / `check_id`+`path`+`line` (CLI) | `DetectorType`+`commit`+`file`+`line` |
| `source_tool` | `"sonarqube"` | `"semgrep"` | `"trufflehog"` |
| `repository_id` | `component` (project) | `repository.name` / git path | `SourceMetadata.Data.Git.repository` |
| `severity` | `severity` (BLOCKER … INFO) | `severity` (CLI or Cloud) | N/A (convention=high) |
| `status` | `status` + `resolution` | `triage_state` | N/A |
| `rule_id` | `rule` | `rule_name` (Cloud) / `check_id` (CLI) | `DetectorName` |
| `file_path` | `component` (extract) | `location.file_path` / `path` | `SourceMetadata.Data.Git.file` |
| `line_number` | `line` | `location.line` / `start.line` | `SourceMetadata.Data.Git.line` |
| `secret_type` | N/A | N/A | `DetectorName` |
| `validity_status` | N/A | N/A | `Verified` + `VerificationError` |
| `detected_at` | `creationDate` | `first_seen` (Cloud) | `SourceMetadata.Data.Git.timestamp` |
| `resolved_at` | (on status transition) | (on `triage_state` transition) | N/A (full-reload) |

### Silver Finding derivation: package level and platform sources

Dependency-Track produces package vulnerability findings. GitHub and GitLab expose platform native findings spanning Dependabot (SCA), code scanning (SAST), and secret scanning.

| Standard field | Dependency-Track | GitHub / GitLab (platform) |
|---|---|---|
| `finding_id` | (generated) | (generated) |
| `source_finding_id` | `component.uuid` + `vulnerability.vulnId` | `number` (GH) / `id` (GL) |
| `source_tool` | `"dependency-track"` | `"github"` / `"gitlab"` |
| `repository_id` | `project` (via PURL or project prop) | repo reference |
| `severity` | `vulnerability.severity` (CRITICAL … UNASSIGNED) | `rule.security_severity_level` (GH) / `severity` (GL) |
| `status` | (derived from analyzer + resolution) | `state` (GH) / `state` (GL) |
| `rule_id` | `vulnerability.vulnId` | `rule.id` |
| `cve_id` | `vulnerability.vulnId` (CVE-*) | `security_advisory.cve_id` (Dependabot) |
| `file_path` | N/A | `most_recent_instance.location.path` |
| `line_number` | N/A | `most_recent_instance.location.start_line` |
| `package_name` | `component.name` | `dependency.package.name` (Dependabot) |
| `package_version` | `component.version` | `dependency.package.version` (Dependabot) |
| `ecosystem` | `component.purl` (extract) | `dependency.package.ecosystem` |
| `secret_type` | N/A | `secret_type` (GH Secret Scanning) |
| `validity_status` | N/A | `validity` (GH Secret Scanning) |
| `detected_at` | `attribution.attributedOn` | `created_at` |
| `resolved_at` | (on project audit) | `fixed_at` / `resolved_at` |

### Silver Finding derivation: runtime edge-event sources (WAF)

WAF connectors (AWS WAF) project each edge event as one finding row on `silver.findings`. The per-event projection follows the trufflehog convention for sources without a native lifecycle: severity is **derived** from the action via an action-keyed lookup, status is the literal `open` and never transitions, and `finding_id` is a deterministic SHA-256 hash so re-deliveries collapse at the Bronze-to-Silver MERGE. WAF telemetry beyond the canonical record — `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself — is intentionally dropped. Operators query the upstream WAF logs (S3 / CloudWatch) directly when they need that detail.

| Standard field | AWS WAF |
|---|---|
| `finding_id` | (derived) SHA-256 of `(webaclId, httpRequest.requestId, timestamp)` |
| `tool_source` | `"aws_waf"` |
| `category` | `"waf"` |
| `severity_canonical` | derived from `action` via `severity.yml` (block→high, count→medium, challenge→low, captcha→low, allow→low) |
| `status_canonical` | literal `"open"` (no native lifecycle) |
| `rule_id_native` | `terminatingRuleId` |
| `url` | `httpRequest.uri` |
| `repository_id` | N/A (WebACLs are not repo-scoped; Gold-side aggregations bucket WAF rows under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping — out of scope for the MVP) |
| `cwe_id` / `cve_id` | N/A |
| `file_path` / `start_line` | N/A |
| `first_seen_at` / `last_seen_at` | `timestamp` (epoch ms → UTC datetime at transform) |

`REQ-DEDUP` is N/A for WAF: WAF rows do not share dedup tuples with SAST / SCA / secret / DAST findings, so no `dedup_links` rows are emitted. Replay deduplication (recovering from re-delivered events) is achieved by the deterministic `finding_id` collapsing onto the same row at MERGE, not by a `dedup_links` entry.

## Severity and Status Normalization Requirements

The implementation **SHALL** harmonize the native severity scale of each source to the standard four level model (`critical`, `high`, `medium`, `low`) through a lookup table for each source. The table is co-located with the connector at [`src/connectors/{source}/severity.yml`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors). Each lookup **SHALL** cover every documented source value. Undocumented source values fall through to a configurable default (`medium` unless the `config.yml` for the connector overrides it) and **SHALL** trigger a data quality warning. A null or missing source severity is mapped to `medium` and similarly flagged.

The implementation **SHALL** translate the native lifecycle state of each source to the standard five state model (`open`, `confirmed`, `resolved`, `false_positive`, `wontfix`) through an analogous lookup at [`src/connectors/{source}/status.yml`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors).

Both severity and status lookup tables **SHALL** be maintained as configuration files rather than code so that vocabulary updates do not require a pipeline redeploy.

All source timestamps **SHALL** be converted to UTC during the Bronze to Silver transformation. Formats specific to each source (ISO 8601 with or without offsets, Unix epoch in seconds or milliseconds, and tool specific strings) **SHALL** be parsed during schema mapping and stored as UTC datetime columns.
