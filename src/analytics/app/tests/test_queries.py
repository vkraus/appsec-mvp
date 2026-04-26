"""Tests for ``src/analytics/app/queries.py``.

Mocks the ``databricks.sql`` connection / cursor so we can verify:
- The SQL strings hit the right Online Tables.
- The score formula is applied correctly.
- ``fetch_findings`` short-circuits on empty input.
- ``connect()`` raises a clear error when env vars are missing.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.analytics.app import queries


# --- helpers ---


class _MockCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self._rows


class _MockConn:
    def __init__(self, rows: list[tuple]) -> None:
        self._cursor = _MockCursor(rows)

    def cursor(self) -> _MockCursor:
        return self._cursor


# --- fetch_score ---


def test_fetch_score_happy_path_computes_score() -> None:
    """1 critical + 1 high + 0 medium = 1*10 + 1*3 = 13."""
    rows = [
        ("critical", 1, "2026-04-25"),
        ("high", 1, "2026-04-25"),
        ("medium", 0, "2026-04-25"),
        ("low", 0, "2026-04-25"),
    ]
    conn = _MockConn(rows)

    result = queries.fetch_score("APP-001", conn)
    assert result is not None
    assert result["application_id"] == "APP-001"
    assert result["score"] == 13
    assert result["severity_breakdown"] == {
        "critical": 1,
        "high": 1,
        "medium": 0,
        "low": 0,
    }
    assert result["snapshot_date"] == "2026-04-25"


def test_fetch_score_unknown_app_returns_none() -> None:
    """No rows from the cursor → None."""
    conn = _MockConn([])
    result = queries.fetch_score("UNKNOWN", conn)
    assert result is None


def test_fetch_score_sql_targets_gold_online() -> None:
    """The SQL must read from gold_online.app_risk_posture (the Online Table)."""
    conn = _MockConn([("low", 5, "2026-04-25")])
    queries.fetch_score("APP-001", conn)

    executed_sql, executed_params = conn.cursor().executed[0]
    assert "gold_online.app_risk_posture" in executed_sql
    assert "MAX(snapshot_date)" in executed_sql
    assert executed_params == ("APP-001", "APP-001")


def test_fetch_score_score_formula_only_critical() -> None:
    """5 critical + 0 anything else = 50."""
    rows = [
        ("critical", 5, "2026-04-25"),
        ("high", 0, "2026-04-25"),
        ("medium", 0, "2026-04-25"),
        ("low", 0, "2026-04-25"),
    ]
    result = queries.fetch_score("APP-001", _MockConn(rows))
    assert result["score"] == 50


def test_fetch_score_ignores_unknown_severity_buckets() -> None:
    """A bogus severity row does not crash and does not affect the score."""
    rows = [
        ("info", 7, "2026-04-25"),
        ("medium", 2, "2026-04-25"),
    ]
    result = queries.fetch_score("APP-001", _MockConn(rows))
    assert result["score"] == 2
    assert result["severity_breakdown"]["medium"] == 2


# --- fetch_findings ---


def test_fetch_findings_empty_list_short_circuits() -> None:
    """Empty input returns [] without touching the cursor."""
    conn = MagicMock()
    result = queries.fetch_findings([], conn)
    assert result == []
    conn.cursor.assert_not_called()


def test_fetch_findings_builds_in_clause_with_placeholders() -> None:
    """Three ids → SQL has three placeholders against silver_online."""
    rows = [
        ("F-1", "high", "repo-A", "APP-001"),
        ("F-2", "low", "repo-A", "APP-001"),
    ]
    conn = _MockConn(rows)

    result = queries.fetch_findings(["F-1", "F-2", "F-3"], conn)

    executed_sql, executed_params = conn.cursor().executed[0]
    assert "silver_online.app_repo_findings" in executed_sql
    assert executed_sql.count("?") == 3
    assert executed_params == ("F-1", "F-2", "F-3")
    assert len(result) == 2
    assert result[0]["finding_id"] == "F-1"
    assert result[0]["severity_canonical"] == "high"


def test_fetch_findings_returns_dict_per_row() -> None:
    """Each cursor row is converted to a stable dict shape."""
    rows = [("F-9", "critical", "repo-Z", "APP-099")]
    result = queries.fetch_findings(["F-9"], _MockConn(rows))
    assert result == [
        {
            "finding_id": "F-9",
            "severity_canonical": "critical",
            "repository_id": "repo-Z",
            "application_id": "APP-099",
        }
    ]


# --- connect ---


def test_connect_raises_when_env_vars_missing(monkeypatch) -> None:
    """Missing any of the three env vars raises a clear RuntimeError."""
    for var in (
        "DATABRICKS_SERVER_HOSTNAME",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(RuntimeError, match="DATABRICKS_SERVER_HOSTNAME"):
        with queries.connect():
            pass  # pragma: no cover


def test_connect_calls_dbsql_with_env_vars(monkeypatch) -> None:
    """When env vars are set, ``connect`` calls ``databricks.sql.connect``."""
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "host.example")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")
    monkeypatch.setenv("DATABRICKS_TOKEN", "tok-xyz")

    fake_conn = MagicMock()
    fake_dbsql = MagicMock()
    fake_dbsql.connect.return_value = fake_conn

    fake_module = MagicMock()
    fake_module.sql = fake_dbsql

    with patch.dict("sys.modules", {"databricks": fake_module, "databricks.sql": fake_dbsql}):
        with queries.connect() as conn:
            assert conn is fake_conn

    fake_dbsql.connect.assert_called_once_with(
        server_hostname="host.example",
        http_path="/sql/1.0/warehouses/abc",
        access_token="tok-xyz",
    )
    fake_conn.close.assert_called_once()


@pytest.mark.skip(reason="Live test — requires real DATABRICKS_* env + warehouse")
def test_live_connect_against_real_warehouse() -> None:  # pragma: no cover
    """Open a connection and run SELECT 1 — manual / on-cluster only."""
    assert os.environ.get("DATABRICKS_SERVER_HOSTNAME"), "set env vars first"
    raise NotImplementedError
