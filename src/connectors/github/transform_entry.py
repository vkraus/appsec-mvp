# Databricks notebook source
# ruff: noqa: F821 — dbutils is injected by the Databricks notebook runtime
"""Databricks entry point for the github transform task."""

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
