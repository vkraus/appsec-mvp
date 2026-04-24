"""Envelope helper for bronze writes per thesis section 2.2.2."""
from __future__ import annotations

import pytest

from src.common.bronze_schema import BRONZE_ENVELOPE_COLUMNS, with_envelope


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
def test_envelope_columns_are_the_prescribed_five() -> None:
    assert BRONZE_ENVELOPE_COLUMNS == (
        "_ingestion_timestamp",
        "_source_system",
        "_batch_id",
        "_raw_payload",
        "_hwm_value",
    )


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
@pytest.mark.integration
def test_with_envelope_adds_four_base_columns_when_hwm_is_none(spark) -> None:
    df = spark.createDataFrame([("a",), ("b",)], ["col1"])
    out = with_envelope(
        df,
        source_system="owasp_zap",
        batch_id="run-123",
        hwm_value=None,
    )
    added = set(out.columns) - set(df.columns)
    assert added == {
        "_ingestion_timestamp",
        "_source_system",
        "_batch_id",
        "_raw_payload",
    }
    row = out.select("_source_system", "_batch_id").first()
    assert row["_source_system"] == "owasp_zap"
    assert row["_batch_id"] == "run-123"


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
@pytest.mark.integration
def test_with_envelope_adds_hwm_column_when_provided(spark) -> None:
    df = spark.createDataFrame([("a",)], ["col1"])
    out = with_envelope(
        df,
        source_system="owasp_zap",
        batch_id="run-123",
        hwm_value="2026-04-24T00:00:00Z",
    )
    assert "_hwm_value" in out.columns
    assert out.select("_hwm_value").first()["_hwm_value"] == "2026-04-24T00:00:00Z"


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
@pytest.mark.integration
def test_with_envelope_raw_payload_is_json_of_source_columns(spark) -> None:
    import json

    df = spark.createDataFrame([("zap-alert-1", "high")], ["alert_id", "risk"])
    out = with_envelope(
        df,
        source_system="owasp_zap",
        batch_id="run-123",
        hwm_value=None,
    )
    payload_str = out.select("_raw_payload").first()["_raw_payload"]
    payload = json.loads(payload_str)
    assert payload == {"alert_id": "zap-alert-1", "risk": "high"}
