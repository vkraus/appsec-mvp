# Databricks notebook source
# ruff: noqa: F821 — dbutils is injected by the Databricks notebook runtime
# Notebook entry point for the sonarqube-connector job's ``transform`` task.
#
# Driven by ``src/connectors/sonarqube/resources/job.yml``. Reads the job
# parameters as Databricks notebook widgets, loads the bronze issues table
# off Unity Catalog, and delegates to
# ``src.connectors.sonarqube.transform.transform`` per the framework
# contract (thesis section 2.4.1; ``src/platform/contract.py``).
#
# Server-based SAST sub-shape per
# ``.claude/skills/generate-connector/references/sast.md`` —
# ``databricks_runtime.entry_wrappers=true``: this wrapper exists so the
# transform task can run as a notebook on the DAB job cluster while the
# pure-Python ``src/connectors/sonarqube/transform.py`` module stays
# unit-testable without a live ``SparkSession`` from ``dbutils``.

# COMMAND ----------

# pyright: reportMissingImports=false
from src.connectors.sonarqube.transform import transform

# COMMAND ----------

dbutils.widgets.text("source_name", "sonarqube")
dbutils.widgets.text("target_catalog", "appsec_dev")

source_name = dbutils.widgets.get("source_name")
target_catalog = dbutils.widgets.get("target_catalog")

# COMMAND ----------

# Bronze envelope is read from ``{catalog}.bronze_sonarqube.issues``;
# ``transform`` parses ``_raw_payload`` against the SonarQube issue schema,
# applies severity / status lookups, splits component, and projects onto
# silver.findings.
bronze_table = f"{target_catalog}.bronze_sonarqube.issues"
silver_table = f"{target_catalog}.silver.findings"

bronze_df = spark.read.table(bronze_table)
silver_df = transform(bronze_df)

# COMMAND ----------

(silver_df.write.mode("append").option("mergeSchema", "false").saveAsTable(silver_table))

print(f"sonarqube transform complete: bronze={bronze_table} -> silver={silver_table}")
