"""Contract types for the connector ingest/transform wrappers.

Validates the TypedDict shape prescribed by thesis section 2.4.1.
"""

from __future__ import annotations

import pytest

from src.platform.contract import BatchDescriptor, ConnectorState


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_connector_state_accepts_hwm_and_metadata() -> None:
    state: ConnectorState = {
        "source": "github",
        "hwm_value": "2026-04-24T00:00:00Z",
        "run_id": "abc123",
        "extra": {"org": "acme"},
    }
    assert state["source"] == "github"
    assert state["hwm_value"] == "2026-04-24T00:00:00Z"


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_batch_descriptor_reports_record_count_and_advanced_hwm() -> None:
    batch: BatchDescriptor = {
        "run_id": "abc123",
        "source": "github",
        "record_count": 42,
        "new_hwm_value": "2026-04-25T00:00:00Z",
        "bronze_table": "appsec.bronze_github.repositories",
    }
    assert batch["record_count"] == 42
    assert batch["new_hwm_value"] == "2026-04-25T00:00:00Z"
