-- Catalog is created per environment (dev, staging, prod) and selected
-- by the DAB bundle variable ${var.catalog} at deploy time. This
-- script takes the catalog as the current USE context and creates
-- the standard schema layout inside it.
--
-- Usage (from a DAB job):
--   USE CATALOG ${var.catalog};
--   <this script>

CREATE SCHEMA IF NOT EXISTS bronze_github;
CREATE SCHEMA IF NOT EXISTS bronze_servicenow;
CREATE SCHEMA IF NOT EXISTS bronze_owasp_zap;
CREATE SCHEMA IF NOT EXISTS bronze_semgrep;

CREATE SCHEMA IF NOT EXISTS silver_github;
CREATE SCHEMA IF NOT EXISTS silver_servicenow;
-- cross-source silver (findings, app_repo, hwm)
CREATE SCHEMA IF NOT EXISTS silver;

-- cross-source analytics. Table names encode the analytic.
CREATE SCHEMA IF NOT EXISTS gold;

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

CREATE TABLE IF NOT EXISTS silver.hwm (
  key STRING NOT NULL,
  subkey STRING NOT NULL,
  value STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
) USING DELTA;
