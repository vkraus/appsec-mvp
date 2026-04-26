# Databricks notebook source
"""Databricks entry point for the github ingest task.

Thin dispatcher: reads the three DAB job parameters (source_name,
target_catalog, hwm_reset) via dbutils widgets, resolves the Databricks
job_run_id from the notebook context, loads the connector state, and
calls src.connectors.github.ingest.ingest(run_id, state).

The transform task is a separate notebook (transform_entry.py) wired in
src/connectors/github/resources/job.yml with depends_on: ingest per
thesis section 2.4.2.
"""

from src.connectors.github.ingest import ingest

# COMMAND ----------

dbutils.widgets.text("source_name", "github")
dbutils.widgets.text("target_catalog", "")
dbutils.widgets.text("hwm_reset", "false")

source_name = dbutils.widgets.get("source_name")
target_catalog = dbutils.widgets.get("target_catalog")
hwm_reset = dbutils.widgets.get("hwm_reset").lower() == "true"

# COMMAND ----------

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
run_id = ctx.tags().apply("runId") if "runId" in ctx.tags().keySet() else ctx.jobId().get()

# COMMAND ----------

state = {
    "source": source_name,
    "hwm_value": None if hwm_reset else None,
    "extra": {
        "token": dbutils.secrets.get(scope="mvp-connectors", key="github_token"),
        "org": dbutils.secrets.get(scope="mvp-connectors", key="github_org"),
        "catalog": target_catalog,
    },
}

# COMMAND ----------

descriptor = ingest(run_id=str(run_id), state=state)
print(descriptor)
