"""SonarQube connector — ingest scaffolding.

The full implementation is out of scope for the Databricks-centric
redesign. This module exists so the connector folder structure is
discoverable end-to-end (resources, scripts, runtime, tests).
"""

from src.platform.contract import BatchDescriptor, ConnectorState


def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor:
    raise NotImplementedError(
        "SonarQube ingest is scaffolding only. Implementation is tracked "
        "as a separate follow-on task — see the redesign spec's "
        "'Out of scope' section."
    )
