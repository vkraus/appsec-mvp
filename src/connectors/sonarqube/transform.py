"""SonarQube connector — transform scaffolding.

The full implementation is out of scope for the Databricks-centric
redesign. This module exists so the connector folder structure is
discoverable end-to-end (resources, scripts, runtime, tests).
"""

from pyspark.sql import DataFrame


def transform(bronze_df: DataFrame) -> DataFrame:
    raise NotImplementedError(
        "SonarQube transform is scaffolding only. Implementation is tracked "
        "as a separate follow-on task — see the redesign spec's "
        "'Out of scope' section."
    )
