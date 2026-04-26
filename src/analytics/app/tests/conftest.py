"""Shared test fixtures for the analytics App.

The route-handler tests in ``test_main.py`` need ``queries.connect`` patched
so the FastAPI handlers can run without a real Databricks SQL connection.
The query-helper tests in ``test_queries.py`` exercise ``connect`` directly
and must NOT be patched. We therefore make ``patch_connect`` an opt-in
fixture (autouse only inside ``test_main.py`` via a local autouse alias).
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest


class _NullConnection:
    def cursor(self):  # pragma: no cover — never called when fetchers are mocked
        raise NotImplementedError("fetch_score / fetch_findings should be mocked")

    def close(self) -> None:
        return None


@contextmanager
def _null_connect():
    yield _NullConnection()


@pytest.fixture
def patch_connect():
    """Replace ``queries.connect`` so route handlers don't open a real SQL conn."""
    with patch("src.analytics.app.queries.connect", _null_connect):
        yield
