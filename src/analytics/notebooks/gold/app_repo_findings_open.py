# Databricks notebook source
# ruff: noqa: F821 — dbutils, spark are injected by the Databricks notebook runtime
"""View `gold.app_repo_findings_open` — joined open findings × app_repo_mapping.

Backs the `silver_online.app_repo_findings` Online Table (Phase 3 OLTP) so
the pre-merge gate can do a single point-lookup by `repository_id` to fetch
the open findings for that repo plus the owning application.

This is a SQL VIEW, not a materialised table, because:
  - Online Table sync handles materialisation row-side at the serving tier;
  - re-projecting from the underlying Silver tables on every batch refresh
    would write data we never read except via the Online Table replica.

The view excludes findings with no repository linkage and findings whose
repository has no application mapping (those are not actionable for the
pre-merge gate, which is keyed on (repo, pr) and resolves to a single app).
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## Inputs
# MAGIC
# MAGIC - Widget `target_catalog` (UC catalog name; defaults to the bundle var).

# COMMAND ----------

dbutils.widgets.text("target_catalog", "")  # noqa: F821
target_catalog = dbutils.widgets.get("target_catalog")  # noqa: F821
if not target_catalog:
    raise ValueError("target_catalog widget is required")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or replace the view

# COMMAND ----------

view_sql = f"""
CREATE OR REPLACE VIEW {target_catalog}.gold.app_repo_findings_open AS
SELECT
  f.finding_id,
  f.repository_id,
  m.application_id,
  f.tool_source,
  f.category,
  f.severity_canonical,
  f.cwe_id,
  f.cve_id,
  f.rule_id_native,
  f.file_path,
  f.start_line,
  f.url,
  f.first_seen_at,
  f.last_seen_at
FROM {target_catalog}.silver.findings f
JOIN {target_catalog}.silver.app_repo_mapping m
  ON f.repository_id = m.repository_id
WHERE f.status_canonical = 'open'
  AND f.repository_id IS NOT NULL
"""
spark.sql(view_sql)  # noqa: F821
print(f"created view {target_catalog}.gold.app_repo_findings_open")
