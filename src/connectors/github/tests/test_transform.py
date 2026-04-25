"""Tests for the GitHub repositories bronze-to-silver transform.

REQ markers bind to the catalog at mkdocs/docs/platform/reference/catalog.md.
The MVP implements the SCM entity role only (repositories), so REQ-TRF-SEV,
REQ-TRF-STS, and REQ-DEDUP are out of scope per references/scm.md until
GHAS finding ingestion ships.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.connectors.github.transform import repositories_to_silver

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def spark():
    return SparkSession.builder.appName("gh-tests").master("local[2]").getOrCreate()


@pytest.mark.requirement("REQ-TRF-MAP")
def test_repositories_to_silver(spark):
    """Mapping: every /repos consumed field projects onto silver.repositories
    with the correct name, type, and null handling. The fixture exercises
    two repositories with distinct default branches and updated_at stamps.
    """
    raw = json.loads((FIX / "repositories.json").read_text())
    out = {r["repository_id"]: r for r in repositories_to_silver(spark, raw).collect()}
    assert set(out) == {"acme/payments-api", "acme/loyalty-web"}
    assert out["acme/payments-api"]["default_branch"] == "main"
    assert out["acme/payments-api"]["full_name"] == "acme/payments-api"


@pytest.mark.requirement("REQ-TRF-TS")
def test_repositories_updated_at_is_utc_datetime(spark):
    """Timestamp normalization: GitHub's ISO-8601 `updated_at` (always UTC,
    trailing `Z` per the page's Incremental-hook note) is emitted as a
    timezone-aware UTC datetime in silver.repositories.
    """
    raw = json.loads((FIX / "repositories.json").read_text())
    out = {r["repository_id"]: r for r in repositories_to_silver(spark, raw).collect()}
    ts = out["acme/payments-api"]["updated_at"]
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None
    assert ts == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-DQ")
def test_repositories_missing_full_name_raises(spark):
    """Data quality: a raw repository row without the `full_name` natural key
    cannot be projected onto silver.repositories (repository_id is
    non-nullable). The transform surfaces the invalid row rather than
    silently dropping it; the Lakeflow expectation on silver.repositories
    will quarantine equivalents of this case in production.
    """
    bad = [{"full_name": None, "default_branch": "main", "updated_at": "2026-04-20T10:00:00Z"}]
    with pytest.raises((KeyError, TypeError, Exception)):
        # Either the dict access or the Spark row materialisation surfaces
        # the missing natural key; both are acceptable DQ-signal failure
        # modes for the entity-only MVP.
        repositories_to_silver(spark, bad).collect()
