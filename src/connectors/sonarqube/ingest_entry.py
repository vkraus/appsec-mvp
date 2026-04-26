# Databricks notebook source
# ruff: noqa: F821 — dbutils is injected by the Databricks notebook runtime
# Notebook entry point for the sonarqube-connector job's ``ingest`` task.
#
# Driven by ``src/connectors/sonarqube/resources/job.yml``. Reads the job
# parameters as Databricks notebook widgets, fetches the SonarQube
# credentials from the Databricks secret scope, and delegates to
# ``src.connectors.sonarqube.ingest.ingest`` per the framework contract
# (thesis section 2.4.1; ``src/platform/contract.py``).
#
# Server-based SAST sub-shape per
# ``.claude/skills/generate-connector/references/sast.md`` —
# ``databricks_runtime.entry_wrappers=true``: this wrapper exists so the
# ingest task can run as a notebook on the DAB job cluster while the
# pure-Python ``src/connectors/sonarqube/ingest.py`` module stays
# unit-testable without ``dbutils`` or a live SonarQube instance.

# COMMAND ----------

# pyright: reportMissingImports=false
from src.connectors.sonarqube.ingest import ingest

# COMMAND ----------

# Job parameters (declared in resources/job.yml):
#   - source_name      → identity passed through to the framework wrapper
#   - target_catalog   → Unity Catalog catalog the connector writes to
#   - hwm_reset        → "true" forces a first-run pull on the next invocation
dbutils.widgets.text("source_name", "sonarqube")
dbutils.widgets.text("target_catalog", "appsec_dev")
dbutils.widgets.text("hwm_reset", "false")

source_name = dbutils.widgets.get("source_name")
target_catalog = dbutils.widgets.get("target_catalog")
hwm_reset = dbutils.widgets.get("hwm_reset").lower() == "true"

# COMMAND ----------

# Resolve credentials from the platform secret scope. The scope name and
# secret keys are operational data declared in
# src/connectors/sonarqube/operational.yml (databricks_runtime.secret_scope,
# secret_env_vars).
SECRET_SCOPE = "mvp-connectors"
base_url = dbutils.secrets.get(scope=SECRET_SCOPE, key="sonarqube_url")
token = dbutils.secrets.get(scope=SECRET_SCOPE, key="sonarqube_token")

# COMMAND ----------

run_id = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().jobId().get()
    if hasattr(dbutils, "notebook")
    else "interactive"
)

state = {
    "source": source_name,
    "run_id": str(run_id),
    "hwm_value": None if hwm_reset else None,  # HWM persistence is Future Work
    "extra": {
        "token": token,
        "base_url": base_url,
        "catalog": target_catalog,
    },
}

# COMMAND ----------

descriptor = ingest(run_id=str(run_id), state=state)
print(f"sonarqube ingest complete: {descriptor}")
