"""Databricks SQL query helpers for the AppSec analytics App.

Both helpers take an open ``databricks.sql`` connection so the route handlers
can manage connection lifecycle (and the unit tests can pass a mock).

Connection params are read from environment variables:
- ``DATABRICKS_SERVER_HOSTNAME``
- ``DATABRICKS_HTTP_PATH``
- ``DATABRICKS_TOKEN``
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

# ``databricks.sql`` is imported lazily inside ``connect`` so the module is
# importable without the connector in environments where only the helpers
# are needed (e.g. the unit-test suite mocks both query helpers directly).


@contextmanager
def connect() -> Iterator[Any]:
    """Yield a Databricks SQL connection from environment-supplied params.

    Caller is responsible for using this as a context manager so the
    connection is closed on exit. Raises ``RuntimeError`` if any of the
    required environment variables are missing.
    """
    hostname = os.environ.get("DATABRICKS_SERVER_HOSTNAME")
    http_path = os.environ.get("DATABRICKS_HTTP_PATH")
    token = os.environ.get("DATABRICKS_TOKEN")
    missing = [
        name
        for name, value in (
            ("DATABRICKS_SERVER_HOSTNAME", hostname),
            ("DATABRICKS_HTTP_PATH", http_path),
            ("DATABRICKS_TOKEN", token),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Missing required Databricks SQL env vars: {', '.join(missing)}"
        )

    from databricks import sql as dbsql  # local import — see module docstring

    conn = dbsql.connect(
        server_hostname=hostname,
        http_path=http_path,
        access_token=token,
    )
    try:
        yield conn
    finally:
        conn.close()


def fetch_score(application_id: str, conn: Any) -> dict[str, Any] | None:
    """Fetch the latest open-finding severity breakdown for ``application_id``.

    Reads from ``gold_online.app_risk_posture`` (the Online Table replica of
    ``gold.app_risk_posture_daily``), restricted to the most recent
    ``snapshot_date`` for the given application.

    Returns ``None`` if no rows are found (i.e. unknown ``application_id``).
    Otherwise returns ``{ application_id, score, severity_breakdown, snapshot_date }``
    with ``score`` computed via the canonical formula:

        score = critical*10 + high*3 + medium*1 + low*0
    """
    sql = """
        SELECT
          severity_canonical,
          open_count,
          snapshot_date
        FROM gold_online.app_risk_posture
        WHERE application_id = ?
          AND snapshot_date = (
            SELECT MAX(snapshot_date)
            FROM gold_online.app_risk_posture
            WHERE application_id = ?
          )
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (application_id, application_id))
        rows = cursor.fetchall()

    if not rows:
        return None

    breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    snapshot_date = None
    for row in rows:
        sev = _row_get(row, "severity_canonical", 0)
        cnt = _row_get(row, "open_count", 1)
        snap = _row_get(row, "snapshot_date", 2)
        if snap is not None:
            snapshot_date = snap
        if sev in breakdown:
            breakdown[sev] = int(cnt or 0)

    score = (
        breakdown["critical"] * 10
        + breakdown["high"] * 3
        + breakdown["medium"] * 1
        + breakdown["low"] * 0
    )

    return {
        "application_id": application_id,
        "score": score,
        "severity_breakdown": breakdown,
        "snapshot_date": str(snapshot_date) if snapshot_date is not None else None,
    }


def fetch_findings(finding_ids: list[str], conn: Any) -> list[dict[str, Any]]:
    """Fetch finding rows from ``silver_online.app_repo_findings`` by id.

    Returns one dict per matched finding with keys
    ``finding_id``, ``severity_canonical``, ``repository_id``, ``application_id``.
    Returns ``[]`` for an empty input list (no SQL is executed).
    """
    if not finding_ids:
        return []

    placeholders = ",".join(["?"] * len(finding_ids))
    sql = f"""
        SELECT
          finding_id,
          severity_canonical,
          repository_id,
          application_id
        FROM silver_online.app_repo_findings
        WHERE finding_id IN ({placeholders})
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(finding_ids))
        rows = cursor.fetchall()

    return [
        {
            "finding_id": _row_get(row, "finding_id", 0),
            "severity_canonical": _row_get(row, "severity_canonical", 1),
            "repository_id": _row_get(row, "repository_id", 2),
            "application_id": _row_get(row, "application_id", 3),
        }
        for row in rows
    ]


def _row_get(row: Any, key: str, idx: int) -> Any:
    """Read a column from a Databricks SQL Row by name, falling back to index.

    The connector returns rows as named tuples (``Row``) in normal use, but
    the unit tests pass plain tuples through the mock — the index path is
    the safety net for those.
    """
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[idx]
    except (IndexError, TypeError, KeyError):
        return None
