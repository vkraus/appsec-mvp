# Databricks notebook source
"""Databricks entry point for the GitHub transform task.

Thin dispatcher: reads the bronze Delta table for the configured
target_catalog and hands the dataframe to
src.connectors.github.transform.transform, which parses
``_raw_payload`` and projects onto silver_repositories. The DAG wiring
(depends_on: ingest, retries per section 2.4.2) lives in
resources/github-job.yml.
"""

from pyspark.sql import SparkSession

from src.connectors.github.transform import transform

# COMMAND ----------

dbutils.widgets.text("source_name", "github")
dbutils.widgets.text("target_catalog", "")
dbutils.widgets.text("hwm_reset", "false")

source_name = dbutils.widgets.get("source_name")
target_catalog = dbutils.widgets.get("target_catalog")

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()
bronze_table = f"{target_catalog}.bronze_github.repositories"
bronze_df = spark.read.table(bronze_table)

# COMMAND ----------

silver_df = transform(bronze_df)
print(silver_df.count())
