"""Connector test configuration: patch PySpark's TimestampType.fromInternal
to return UTC-aware datetimes so that collected timestamps can be compared
to timezone-aware Python datetimes regardless of the machine's local timezone.

On Databricks clusters the JVM timezone is always UTC; locally it may differ.
This patch makes tests portable, matching the established pattern in
tests/connectors/github/conftest.py.
"""

import datetime as _dt

import pytest
from pyspark.sql.types import TimestampType as _TimestampType


def _utc_from_internal(self, ts: int):  # type: ignore[override]
    """Return a UTC-aware datetime instead of a local-naive one."""
    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(
        ts // 1000000, tz=_dt.timezone.utc
    ).replace(microsecond=ts % 1000000)


@pytest.fixture(scope="session", autouse=True)
def _patch_timestamp_from_internal():
    """Patch TimestampType.fromInternal for the test session."""
    original = _TimestampType.fromInternal
    _TimestampType.fromInternal = _utc_from_internal
    yield
    _TimestampType.fromInternal = original
