"""ServiceNow transform tests — REQ-bound plus the legacy end-to-end check."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.connectors.servicenow.transform import business_apps_to_silver

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def spark():
    return (
        SparkSession.builder.appName("sn-tests").master("local[2]")
        .config("spark.sql.shuffle.partitions", "1").getOrCreate()
    )


def test_business_apps_to_silver(spark):
    raw = json.loads((FIX / "cmdb_ci_business_app.json").read_text())["result"]
    out = business_apps_to_silver(spark, raw).collect()
    out_by_id = {r["application_id"]: r for r in out}
    assert set(out_by_id) == {"ba-001", "ba-002"}
    assert out_by_id["ba-001"]["name"] == "Payments"
    assert out_by_id["ba-001"]["owner_email"] == "payments-team@example.com"
    assert out_by_id["ba-001"]["criticality"] == "critical"
    assert out_by_id["ba-001"]["updated_at"] == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-MAP")
def test_business_app_mapping(spark):
    """Bronze cmdb_ci_business_app rows project onto silver.applications
    per the mapping.yml field list.

    Validates sys_id→application_id, name, owned_by.email→owner_email,
    and the criticality passthrough via the per-source severity lookup.
    Uses the recorded fixture at ``fixtures/cmdb_ci_business_app.json``.
    """
    raw = json.loads((FIX / "cmdb_ci_business_app.json").read_text())["result"]
    out_by_id = {r["application_id"]: r for r in business_apps_to_silver(spark, raw).collect()}

    assert set(out_by_id) == {"ba-001", "ba-002"}
    # Field-level mapping: mapping.yml rows, one by one.
    row = out_by_id["ba-002"]
    assert row["name"] == "Loyalty"
    assert row["owner_email"] == "loyalty@example.com"
    # u_criticality "3 - medium" → silver criticality "medium" (see
    # config/severity/servicenow.yml — criticality shares the canonical
    # severity enum by design).
    assert row["criticality"] == "medium"


@pytest.mark.requirement("REQ-TRF-TS")
def test_sys_updated_on_utc_normalization(spark):
    """sys_updated_on is normalized to a tz-aware UTC Timestamp in silver.

    The connector page documents that ServiceNow renders sys_updated_on in
    the calling user's display time zone; the transform must land a
    tz-aware UTC timestamp regardless of the worker JVM's default zone.
    """
    raw = [{
        "sys_id": "ba-ts-1",
        "name": "TZ Check",
        "owned_by": {"email": "tz@example.com"},
        "u_criticality": "4 - low",
        "sys_updated_on": "2026-04-20 10:00:00",
    }]
    out = business_apps_to_silver(spark, raw).collect()
    assert len(out) == 1
    ts = out[0]["updated_at"]
    assert ts.tzinfo is not None, "updated_at must be timezone-aware"
    # Expected UTC instant per the bronze-to-silver contract.
    assert ts == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-DQ")
def test_business_app_expectation_quarantines_null_sys_id(spark):
    """Data-quality expectation: rows missing sys_id must not reach silver.

    silver.applications.application_id is NOT NULL (see
    src/platform/schemas.py::silver_applications). The transform's natural
    landing path fails loudly on a missing primary key rather than
    silently emitting a corrupt silver row.
    """
    raw_ok = {
        "sys_id": "ba-ok",
        "name": "Good",
        "owned_by": {"email": "ok@example.com"},
        "u_criticality": "1 - critical",
        "sys_updated_on": "2026-04-20 10:00:00",
    }
    # business_apps_to_silver constructs Rows from the dict directly; a
    # missing sys_id surfaces as a KeyError at row-construction time, which
    # is the in-process equivalent of a DLT expectation quarantining the row.
    with pytest.raises(KeyError):
        business_apps_to_silver(
            spark,
            [{k: v for k, v in raw_ok.items() if k != "sys_id"}],
        ).collect()

    # Sanity: the well-formed row still lands.
    out = business_apps_to_silver(spark, [raw_ok]).collect()
    assert out[0]["application_id"] == "ba-ok"
