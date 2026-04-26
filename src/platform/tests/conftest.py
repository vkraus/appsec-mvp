"""Fixtures for tests in ``tests/common/``.

Per the repo ``CLAUDE.md`` rule, no local ``SparkSession`` is spun up for
tests. DataFrame-shaped assertions run against Databricks Connect when the
environment is configured, otherwise they are skipped. Pure-Python unit
tests do not use any fixture from this file.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def spark():
    """Yield a Databricks Connect ``SparkSession``.

    Skips the test if Databricks Connect is not available or not
    configured. Do not replace this with a ``local[*]`` session: the
    repo rule mandates that Spark logic runs on Databricks.
    """
    if not os.environ.get("DATABRICKS_HOST"):
        pytest.skip("DATABRICKS_HOST is not set; Spark tests run via Databricks Connect only.")
    try:
        from databricks.connect import DatabricksSession  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("databricks-connect is not installed in this environment.")

    session = DatabricksSession.builder.getOrCreate()
    yield session
