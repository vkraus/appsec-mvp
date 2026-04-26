"""ServiceNow ingestion tests.

Binds the ingest-side REQ-IDs that apply to the CMDB / ServiceNow profile
under the Lakeflow Connect ingestion path
(``operational.yml.databricks_runtime.ingestion_path = lakeflow_connect``):

- REQ-ING-AUTH: the contract wrapper rejects missing service-account
  credentials with a clear ``ValueError``, even though live ingestion is
  owned by Lakeflow Connect.
- REQ-ING-PAG / REQ-ING-RL / REQ-ING-HWM: delegated to Lakeflow Connect; the
  connector validates the pipeline declaration structurally via
  ``test_pipeline_yml_declares_lakeflow_ingestion``. The validate-implementation
  skill marks the three REQs as N/A on this connector with that rationale.

REQ-TRF-SEV / REQ-TRF-STS / REQ-DEDUP are N/A for CMDB and intentionally NOT
bound here per ``references/cmdb.md``.

No local SparkSession is instantiated — pure-Python contracts only per the
CLAUDE.md architectural rules.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from src.connectors.servicenow.ingest import ingest_contract

# ----- framework-contract --------------------------------------------------


def test_ingest_contract_signature() -> None:
    """The contract wrapper signature is ``(run_id, state)`` per §2.4.1."""
    sig = inspect.signature(ingest_contract)
    assert list(sig.parameters) == ["run_id", "state"]


# ----- REQ-ING-AUTH --------------------------------------------------------


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_credentials() -> None:
    """REQ-ING-AUTH: missing username / password surfaces as a clear
    ``ValueError`` rather than a silent failure.

    Even though Lakeflow Connect owns live ingestion (see
    ``resources/pipeline.yml``), the contract wrapper validates
    ``state['extra']`` so a misconfigured DAB job fails fast rather than
    entering the ingestion path with empty credentials.
    """
    with pytest.raises(ValueError, match="base_url, username, password, catalog"):
        ingest_contract(
            "rid-missing-creds",
            {
                "source": "servicenow",
                "run_id": "rid-missing-creds",
                "extra": {
                    "base_url": "https://dev123456.service-now.com",
                    "catalog": "appsec_dev",
                },
            },
        )


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_catalog() -> None:
    """REQ-ING-AUTH (partial): catalog is required to resolve the Bronze
    table prefix; omission is reported rather than papered over."""
    with pytest.raises(ValueError):
        ingest_contract(
            "rid-missing-catalog",
            {
                "source": "servicenow",
                "run_id": "rid-missing-catalog",
                "extra": {
                    "base_url": "https://dev123456.service-now.com",
                    "username": "svc-appsec",
                    "password": "redacted",
                },
            },
        )


# ----- structural assertion: REQ-ING-PAG / RL / HWM delegation ------------


def test_pipeline_yml_declares_lakeflow_ingestion() -> None:
    """REQ-ING-PAG / REQ-ING-RL / REQ-ING-HWM are delegated to Lakeflow Connect.

    This structural test asserts that ``resources/pipeline.yml`` declares the
    expected LFC pipeline shape — connection name, target schema, and source
    objects. The validate-implementation skill marks the three REQs as N/A
    with rationale pointing to this test.
    """
    pipeline_path = Path(__file__).resolve().parent.parent / "resources" / "pipeline.yml"
    spec = yaml.safe_load(pipeline_path.read_text())
    pipelines = spec["resources"]["pipelines"]
    assert "servicenow_ingest" in pipelines
    pipeline = pipelines["servicenow_ingest"]
    assert pipeline["target"] == "bronze_servicenow"
    ingestion = pipeline["ingestion_definition"]
    assert ingestion["connection_name"] == "servicenow"
    objects = ingestion["objects"]
    assert len(objects) >= 1
    destination_tables = {o["table"]["destination_table"] for o in objects}
    assert "business_applications" in destination_tables


# ----- live-only paths — skip unless live env present --------------------


@pytest.mark.integration
@pytest.mark.skip(
    reason="live-only: requires a ServiceNow instance and service-account credentials"
)
def test_run_ingest_pipeline_live_against_pdi() -> None:
    """End-to-end ingest against a live ServiceNow PDI. Live-only."""
    raise AssertionError("unreachable — test is skip-marked")
