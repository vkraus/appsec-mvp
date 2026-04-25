-- Cross-source canonical silver tables, owned by the platform layer.
-- Applied by the platform-bootstrap job (DAB has no native `tables` resource type).
--
-- Usage from the platform-bootstrap job:
--   USE CATALOG ${var.catalog};
--   <this script>
--
-- Authority: `src/platform/schemas.py` is the runtime authority — transforms
-- write rows shaped by those PySpark structs. The DDL below MUST match the
-- structs column-for-column (name, type, nullability) so writes succeed at
-- bootstrap. A contract test under `src/platform/tests/test_silver_ddl.py`
-- asserts the two stay aligned.
--
-- Deferred widening: per the Databricks-centric redesign, several entity
-- tables are intentionally narrower in the MVP than the thesis target. When
-- a connector transform is extended (e.g. the github transform learning to
-- populate `scm_source` / `org` / `name` / `url` / `archived` / `visibility`
-- on `silver.repositories`), widen the matching schema in `schemas.py` first
-- and let the contract test drive the corresponding DDL change here. Do not
-- widen one side without the other.

-- Canonical findings table — every scanner connector writes here.
-- Columns are connector-agnostic; per-source projections live in
-- silver_<source>.findings.
CREATE TABLE IF NOT EXISTS silver.findings (
  finding_id         STRING NOT NULL,
  tool_source        STRING NOT NULL,
  category           STRING NOT NULL,
  severity_canonical STRING NOT NULL,
  status_canonical   STRING NOT NULL,
  cwe_id             STRING,
  cve_id             STRING,
  rule_id_native     STRING NOT NULL,
  trigger_context    STRING NOT NULL,
  repository_id      STRING,
  file_path          STRING,
  start_line         INT,
  url                STRING,
  first_seen_at      TIMESTAMP NOT NULL,
  last_seen_at       TIMESTAMP NOT NULL
) USING DELTA;

-- Per-finding code/URL location — produced by the SAST/SCA/secret/DAST
-- transforms when a finding has location detail richer than the projection
-- that lands on silver.findings.
CREATE TABLE IF NOT EXISTS silver.finding_location (
  finding_id     STRING NOT NULL,
  repository_id  STRING,
  commit_sha     STRING,
  file_path      STRING,
  start_line     INT,
  end_line       INT,
  url            STRING
) USING DELTA;

-- High-water-mark state table — every connector writes here.
CREATE TABLE IF NOT EXISTS silver.hwm (
  key        STRING NOT NULL,
  subkey     STRING NOT NULL,
  value      STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
) USING DELTA;

-- Canonical repository entity — populated by SCM connectors (github, gitlab).
-- Required by the SCM-first data dependency: scanner findings reference
-- `repository_id` values that resolve here.
--
-- MVP shape: narrow (4 cols). The connector-page docs describe a wider
-- target shape (scm_source / org / name / url / archived / visibility /
-- first_seen_at / last_seen_at) that lands when the github transform is
-- extended. Until then, this DDL matches `silver_repositories` in
-- `src/platform/schemas.py`.
CREATE TABLE IF NOT EXISTS silver.repositories (
  repository_id    STRING NOT NULL,
  full_name        STRING NOT NULL,    -- "<org>/<name>"
  default_branch   STRING,
  updated_at       TIMESTAMP NOT NULL
) USING DELTA;

-- Canonical application entity — populated by CMDB connectors (servicenow).
CREATE TABLE IF NOT EXISTS silver.applications (
  application_id  STRING NOT NULL,
  name            STRING NOT NULL,
  owner_email     STRING,
  criticality     STRING,
  updated_at      TIMESTAMP NOT NULL
) USING DELTA;

-- Application <-> repository mapping — populated by the CMDB connector
-- (servicenow). Joins business applications (CMDB) to repositories (SCM).
--
-- Naming note: the table name is `silver.app_repo_mapping`, matching what
-- `src/connectors/servicenow/transform.py` and `mapping.yml` write today
-- and what `silver_app_repo_mapping` in `schemas.py` declares. An earlier
-- iteration of the redesign called this `silver.app_repo` with range columns
-- (`first_seen_at` / `last_seen_at` / `source`); that rename is still on the
-- backlog and not yet wired through the transform layer.
CREATE TABLE IF NOT EXISTS silver.app_repo_mapping (
  application_id  STRING NOT NULL,
  repository_id   STRING NOT NULL,
  linked_at       TIMESTAMP NOT NULL
) USING DELTA;

-- WAF event stream — populated by the AWS WAF connector. Event-shape, NOT
-- finding-shape; deliberately separate from `silver.findings` per the WAF
-- category reference (`mkdocs/docs/connectors/waf/`). Schema matches
-- `silver_waf_events` declared inline in `src/connectors/aws_waf/transform.py`.
CREATE TABLE IF NOT EXISTS silver.waf_events (
  event_id            STRING NOT NULL,
  tool_source         STRING NOT NULL,
  category            STRING NOT NULL,
  timestamp           TIMESTAMP NOT NULL,
  webacl_arn          STRING NOT NULL,
  application_id      STRING,
  rule_id             STRING,
  rule_type           STRING,
  action              STRING NOT NULL,
  severity_canonical  STRING NOT NULL,
  status_canonical    STRING,
  source_ip           STRING,
  country             STRING,
  request_uri         STRING,
  http_method         STRING,
  response_code       INT,
  sampling_weight     BIGINT,
  ingested_at         TIMESTAMP NOT NULL
) USING DELTA;
