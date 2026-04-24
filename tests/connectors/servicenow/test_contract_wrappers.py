"""Verify servicenow.ingest and servicenow.transform expose the section 2.4.1 contract."""
from __future__ import annotations

import inspect

import pytest


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_wrapper_has_contract_signature() -> None:
    from src.connectors.servicenow import ingest as mod

    sig = inspect.signature(mod.ingest)
    params = list(sig.parameters)
    assert params == ["run_id", "state"], params


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_wrapper_returns_batch_descriptor_for_lakeflow_delegation() -> None:
    from src.connectors.servicenow import ingest as mod
    from src.platform.contract import BatchDescriptor

    batch: BatchDescriptor = mod.ingest(
        run_id="r1",
        state={
            "source": "servicenow",
            "run_id": "r1",
            "extra": {"catalog": "appsec"},
        },
    )
    assert batch["source"] == "servicenow"
    assert batch["run_id"] == "r1"
    # Lakeflow Connect delegates the actual ingestion to the DAB pipeline.
    # The wrapper reports zero records processed in-process.
    assert batch["record_count"] == 0
    assert batch["bronze_table"].endswith("bronze_servicenow.business_applications")


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_transform_wrapper_has_contract_signature() -> None:
    from src.connectors.servicenow import transform as mod

    sig = inspect.signature(mod.transform)
    params = list(sig.parameters)
    assert params == ["bronze_df"], params
