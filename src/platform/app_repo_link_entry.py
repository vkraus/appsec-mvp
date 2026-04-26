# Databricks notebook source
# ruff: noqa: F821, I001
# - F821: dbutils, spark are injected by the Databricks notebook runtime
# - I001: imports are intentionally split across notebook cells (# COMMAND ----------)
"""Notebook entry point for the app-repo-link job.

Reads silver.applications and silver.repositories from the target catalog,
calls src.platform.app_repo_link.link_by_name, and MERGES the result
into silver.app_repo_mapping with composite key
(application_id, repository_id, link_source). Re-runs are idempotent:
unchanged links keep their existing linked_at; new links land with the
current job run timestamp; rows that disappear (e.g. repo renamed away
from a 5-digit code) are NOT deleted — that responsibility is reserved
for a future reconciliation pass when the cmdb_rel_ci signal lands.
"""
from datetime import UTC, datetime

# COMMAND ----------

# pyright: reportMissingImports=false
from src.platform.app_repo_link import link_by_name

# COMMAND ----------

dbutils.widgets.text("target_catalog", "appsec_dev")
target_catalog = dbutils.widgets.get("target_catalog")

# COMMAND ----------

apps_table  = f"{target_catalog}.silver.applications"
repos_table = f"{target_catalog}.silver.repositories"
out_table   = f"{target_catalog}.silver.app_repo_mapping"

apps  = spark.read.table(apps_table)
repos = spark.read.table(repos_table)

# COMMAND ----------

run_ts = datetime.now(tz=UTC)
linked = link_by_name(apps, repos, run_ts=run_ts)

# Stage as a Spark temp view and MERGE in SQL — this is the simplest
# idempotent path and avoids requiring the delta-spark Python module
# on the cluster classpath.
linked.createOrReplaceTempView("_app_repo_link_staging")

spark.sql(f"""
    MERGE INTO {out_table} AS t
    USING _app_repo_link_staging AS s
    ON  t.application_id = s.application_id
    AND t.repository_id  = s.repository_id
    AND t.link_source    = s.link_source
    WHEN MATCHED THEN UPDATE SET
        linked_at = s.linked_at
    WHEN NOT MATCHED THEN INSERT (application_id, repository_id, link_source, linked_at)
        VALUES (s.application_id, s.repository_id, s.link_source, s.linked_at)
""")

print(
    f"app_repo_link complete: apps={apps_table} repos={repos_table} -> {out_table}"
)
