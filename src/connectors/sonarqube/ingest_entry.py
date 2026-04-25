# Databricks notebook source — ingest entry point for the sonarqube-connector job.
# Driven by src/connectors/sonarqube/resources/job.yml.

# COMMAND ----------
from src.connectors.sonarqube.ingest import ingest

# Skeleton: full job orchestration lands when the connector is implemented.
print("sonarqube ingest_entry — scaffolding")
