-- Cross-source canonical silver tables, owned by the platform layer.
-- Applied by the platform-bootstrap job (DAB has no native `tables` resource type).
--
-- Usage from the platform-bootstrap job:
--   USE CATALOG ${var.catalog};
--   <this script>

-- Canonical findings table — every scanner connector writes here.
-- Columns are connector-agnostic; per-source projections live in silver_<source>.findings.
CREATE TABLE IF NOT EXISTS silver.findings (
  finding_id         STRING NOT NULL,
  tool_source        STRING NOT NULL,
  category           STRING NOT NULL,
  severity_canonical STRING NOT NULL,
  status_canonical   STRING NOT NULL,
  cwe_id             STRING,
  rule_id_native     STRING NOT NULL,
  trigger_context    STRING NOT NULL,
  repository_id      STRING,
  file_path          STRING,
  start_line         INT,
  url                STRING,
  first_seen_at      TIMESTAMP NOT NULL,
  last_seen_at       TIMESTAMP NOT NULL
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
-- repository_id values that resolve here.
CREATE TABLE IF NOT EXISTS silver.repositories (
  repository_id    STRING NOT NULL,
  scm_source       STRING NOT NULL,    -- "github" | "gitlab"
  org              STRING NOT NULL,
  name             STRING NOT NULL,
  full_name        STRING NOT NULL,    -- "<org>/<name>"
  url              STRING NOT NULL,
  default_branch   STRING,
  archived         BOOLEAN,
  visibility       STRING,             -- "public" | "private" | "internal"
  first_seen_at    TIMESTAMP NOT NULL,
  last_seen_at     TIMESTAMP NOT NULL
) USING DELTA;

-- Application <-> repository mapping — populated by the CMDB connector
-- (servicenow). Joins business applications (CMDB) to repositories (SCM).
CREATE TABLE IF NOT EXISTS silver.app_repo (
  app_id            STRING NOT NULL,
  repository_id     STRING NOT NULL,
  source            STRING NOT NULL,    -- "servicenow_cmdb" | "manual" | ...
  first_seen_at     TIMESTAMP NOT NULL,
  last_seen_at      TIMESTAMP NOT NULL
) USING DELTA;
