"""Unit tests for ``gold.app_risk_posture_daily``.

Covers the pure-Python aggregation helper :func:`compute_posture_rows`.
The Spark-applied write path runs on the Databricks job cluster, not in
local pytest (per CLAUDE.md "no local SparkSession").
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.analytics.notebooks.gold.app_risk_posture_daily import (
    UNMAPPED_SENTINEL,
    compute_posture_rows,
)

NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(days=1)
SNAPSHOT = date(2026, 4, 26)


def _finding(
    *,
    finding_id: str,
    repository_id: str | None,
    severity: str,
    status: str,
    tool_source: str = "semgrep",
    category: str = "sast",
) -> dict:
    return {
        "finding_id": finding_id,
        "repository_id": repository_id,
        "severity_canonical": severity,
        "status_canonical": status,
        "tool_source": tool_source,
        "category": category,
    }


def _mapping(application_id: str, repository_id: str) -> dict:
    return {"application_id": application_id, "repository_id": repository_id}


def _rule(
    scope: str,
    target: str,
    *,
    expires: datetime = FUTURE,
    rule_id: str = "r1",
) -> dict:
    return {
        "rule_id": rule_id,
        "scope": scope,
        "target_pattern": target,
        "expires_at": expires,
        "reason": "test",
        "created_by": "test@example.com",
        "created_at": NOW,
    }


def _by_key(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["application_id"], r["severity_canonical"]): r for r in rows}


# ---------------------------------------------------------------------------
# Typical case: 5 findings × 2 apps × 2 severities


def test_typical_case_aggregates_counts() -> None:
    findings = [
        _finding(finding_id="f1", repository_id="r1", severity="critical", status="open"),
        _finding(finding_id="f2", repository_id="r1", severity="critical", status="open"),
        _finding(finding_id="f3", repository_id="r1", severity="high", status="resolved"),
        _finding(finding_id="f4", repository_id="r2", severity="critical", status="open"),
        _finding(finding_id="f5", repository_id="r2", severity="high", status="open"),
    ]
    mapping = [_mapping("APP-1", "r1"), _mapping("APP-2", "r2")]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=mapping,
        suppression_rules=[],
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    assert len(rows) == 4
    assert by[("APP-1", "critical")]["open_count"] == 2
    assert by[("APP-1", "critical")]["closed_count"] == 0
    assert by[("APP-1", "high")]["open_count"] == 0
    assert by[("APP-1", "high")]["closed_count"] == 1
    assert by[("APP-2", "critical")]["open_count"] == 1
    assert by[("APP-2", "high")]["open_count"] == 1
    # Every row carries the snapshot_date stamp.
    assert all(r["snapshot_date"] == SNAPSHOT for r in rows)


# ---------------------------------------------------------------------------
# Empty findings → empty output


def test_empty_findings_produces_empty_output() -> None:
    rows = compute_posture_rows(
        findings_rows=[],
        app_repo_rows=[_mapping("APP-1", "r1")],
        suppression_rules=[],
        snapshot_date=SNAPSHOT,
        now=NOW,
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Unmapped repository → __UNMAPPED__ sentinel


def test_unmapped_repository_emits_sentinel() -> None:
    findings = [
        _finding(finding_id="f1", repository_id="ghost-repo", severity="high", status="open"),
        _finding(finding_id="f2", repository_id="r1", severity="high", status="open"),
    ]
    mapping = [_mapping("APP-1", "r1")]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=mapping,
        suppression_rules=[],
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    assert (UNMAPPED_SENTINEL, "high") in by
    assert by[(UNMAPPED_SENTINEL, "high")]["open_count"] == 1
    assert by[(UNMAPPED_SENTINEL, "high")]["closed_count"] == 0
    assert by[("APP-1", "high")]["open_count"] == 1


def test_null_repository_emits_sentinel() -> None:
    findings = [
        _finding(finding_id="f1", repository_id=None, severity="critical", status="open"),
    ]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=[],
        suppression_rules=[],
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    assert by[(UNMAPPED_SENTINEL, "critical")]["open_count"] == 1


# ---------------------------------------------------------------------------
# Suppression by tool_source (pre-join scope, but applied post-join)


def test_suppression_by_tool_source_excludes_findings() -> None:
    findings = [
        _finding(
            finding_id="f1",
            repository_id="r1",
            severity="critical",
            status="open",
            tool_source="semgrep",
        ),
        _finding(
            finding_id="f2",
            repository_id="r1",
            severity="critical",
            status="open",
            tool_source="sonarqube",
        ),
    ]
    mapping = [_mapping("APP-1", "r1")]
    rules = [_rule("tool_source", "semgrep")]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=mapping,
        suppression_rules=rules,
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    # Only the sonarqube finding survives.
    assert by[("APP-1", "critical")]["open_count"] == 1


# ---------------------------------------------------------------------------
# Suppression by application_id (post-join scope) — proves the join
# happens before suppression


def test_suppression_by_application_id_excludes_findings() -> None:
    findings = [
        _finding(finding_id="f1", repository_id="r1", severity="critical", status="open"),
        _finding(finding_id="f2", repository_id="r2", severity="critical", status="open"),
    ]
    mapping = [_mapping("APP-1", "r1"), _mapping("APP-2", "r2")]
    rules = [_rule("application_id", "APP-1")]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=mapping,
        suppression_rules=rules,
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    assert ("APP-1", "critical") not in by
    assert by[("APP-2", "critical")]["open_count"] == 1


def test_expired_suppression_rule_does_not_filter() -> None:
    findings = [
        _finding(finding_id="f1", repository_id="r1", severity="critical", status="open"),
    ]
    mapping = [_mapping("APP-1", "r1")]
    rules = [_rule("application_id", "APP-1", expires=PAST)]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=mapping,
        suppression_rules=rules,
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    assert by[("APP-1", "critical")]["open_count"] == 1


# ---------------------------------------------------------------------------
# Closed counts: resolved + wontfix + false_positive; open is exact


def test_closed_count_includes_resolved_wontfix_false_positive() -> None:
    findings = [
        _finding(finding_id="f1", repository_id="r1", severity="high", status="open"),
        _finding(finding_id="f2", repository_id="r1", severity="high", status="resolved"),
        _finding(finding_id="f3", repository_id="r1", severity="high", status="wontfix"),
        _finding(finding_id="f4", repository_id="r1", severity="high", status="false_positive"),
        # A status outside both sets — must be counted in NEITHER bucket.
        _finding(finding_id="f5", repository_id="r1", severity="high", status="reopened"),
    ]
    mapping = [_mapping("APP-1", "r1")]

    rows = compute_posture_rows(
        findings_rows=findings,
        app_repo_rows=mapping,
        suppression_rules=[],
        snapshot_date=SNAPSHOT,
        now=NOW,
    )

    by = _by_key(rows)
    assert by[("APP-1", "high")]["open_count"] == 1
    assert by[("APP-1", "high")]["closed_count"] == 3


# ---------------------------------------------------------------------------
# Spark-applied path — skip-marked per CLAUDE.md.


@pytest.mark.skip(
    reason=(
        "The notebook's spark.createDataFrame + saveAsTable path runs on the "
        "Databricks job cluster, not in local pytest (per CLAUDE.md)."
    )
)
def test_notebook_spark_write_path() -> None:
    raise AssertionError("unreachable — test is skip-marked")
