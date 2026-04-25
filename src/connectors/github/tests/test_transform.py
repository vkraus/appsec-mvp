import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.connectors.github.transform import repositories_to_silver


FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def spark():
    return SparkSession.builder.appName("gh-tests").master("local[2]").getOrCreate()


def test_repositories_to_silver(spark):
    raw = json.loads((FIX / "repositories.json").read_text())
    out = {r["repository_id"]: r for r in repositories_to_silver(spark, raw).collect()}
    assert set(out) == {"acme/payments-api", "acme/loyalty-web"}
    assert out["acme/payments-api"]["default_branch"] == "main"
    assert out["acme/payments-api"]["updated_at"] == datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
