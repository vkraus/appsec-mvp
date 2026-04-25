import json
from datetime import datetime, timezone
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
    assert out_by_id["ba-001"]["updated_at"] == datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
