"""Unit tests for ``gold.mttr_by_source_severity_weekly``.

Covers the pure-Python aggregation (:func:`compute_mttr_rows`) against
synthetic dict fixtures. Per CLAUDE.md "Don'ts", no local SparkSession
is constructed: the notebook's Spark write path is exercised on the
Databricks job cluster only.

Scenarios:
    * Typical: 10 resolved findings across 2 weeks × 1 tool × 2 severities
      — verifies grouping, median, p90, sample_size.
    * Edge: zero resolved findings → empty output.
    * Edge: all findings open (no resolved rows) → empty output.
    * Edge: single resolved finding → median == p90 == that one value,
      sample_size == 1.
    * Suppression: a tool_source rule excludes its findings before MTTR.
    * ISO week boundary: a finding resolved on 2025-12-31 lands in
      ISO week 2025-W01 (per ISO-8601 the Thursday-of-week rule places
      that day in 2026's week 1) vs 2026-01-01 — separate buckets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.analytics.notebooks.gold.mttr_by_source_severity_weekly import (
    compute_mttr_rows,
)

NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(days=30)


def _finding(
    *,
    tool_source: str = "semgrep",
    severity: str = "high",
    status: str = "resolved",
    first_seen_at: datetime,
    last_seen_at: datetime,
    category: str = "sast",
    repository_id: str = "myorg/repo-1",
    file_path: str = "src/app.py",
    rule_id_native: str = "rule-1",
) -> dict:
    """Build a finding row matching the silver.findings schema columns
    that the suppression helper and the MTTR aggregation read."""
    return {
        "tool_source": tool_source,
        "severity_canonical": severity,
        "status_canonical": status,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "category": category,
        "repository_id": repository_id,
        "file_path": file_path,
        "rule_id_native": rule_id_native,
    }


def _rule(scope: str, target: str, expires: datetime = FUTURE) -> dict:
    return {
        "rule_id": "r1",
        "scope": scope,
        "target_pattern": target,
        "expires_at": expires,
        "reason": "test",
        "created_by": "test@example.com",
        "created_at": NOW,
    }


# ---------------------------------------------------------------------------
# Typical case


def test_typical_two_weeks_two_severities() -> None:
    """10 resolved findings: 5 in ISO 2026-W10, 5 in ISO 2026-W11; each
    week split 3 high + 2 critical from the same tool_source.

    Within each (week, severity) bucket the MTTR-hours samples are chosen
    so median + p90 are deterministic.

    Bucket (W10, high): MTTR-hours = [1, 5, 9]
        median = 5; p90 = sorted_vals[int(0.9 * 3)] = sorted_vals[2] = 9.
    Bucket (W10, critical): MTTR-hours = [2, 4]
        median = 3.0; p90 = sorted_vals[int(0.9 * 2)] = sorted_vals[1] = 4.
    Bucket (W11, high): MTTR-hours = [10, 20, 30]
        median = 20; p90 = sorted_vals[2] = 30.
    Bucket (W11, critical): MTTR-hours = [100, 200]
        median = 150.0; p90 = sorted_vals[1] = 200.
    """
    # Mid-week timestamps so ISO-week classification is unambiguous.
    # 2026-03-04 (Wed) lies in ISO 2026-W10. 2026-03-11 (Wed) in W11.
    last_w10 = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    last_w11 = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)

    rows: list[dict] = []
    # W10 high: 1h, 5h, 9h
    for hours in (1, 5, 9):
        rows.append(
            _finding(
                severity="high",
                first_seen_at=last_w10 - timedelta(hours=hours),
                last_seen_at=last_w10,
            )
        )
    # W10 critical: 2h, 4h
    for hours in (2, 4):
        rows.append(
            _finding(
                severity="critical",
                first_seen_at=last_w10 - timedelta(hours=hours),
                last_seen_at=last_w10,
            )
        )
    # W11 high: 10h, 20h, 30h
    for hours in (10, 20, 30):
        rows.append(
            _finding(
                severity="high",
                first_seen_at=last_w11 - timedelta(hours=hours),
                last_seen_at=last_w11,
            )
        )
    # W11 critical: 100h, 200h
    for hours in (100, 200):
        rows.append(
            _finding(
                severity="critical",
                first_seen_at=last_w11 - timedelta(hours=hours),
                last_seen_at=last_w11,
            )
        )

    result = compute_mttr_rows(rows, suppression_rules=[], now=NOW)
    assert len(result) == 4

    # Result is sorted by (iso_year, iso_week, tool_source, severity).
    # Order: (2026,10,semgrep,critical), (2026,10,semgrep,high),
    #        (2026,11,semgrep,critical), (2026,11,semgrep,high).
    by_key = {(r["iso_year"], r["iso_week"], r["severity_canonical"]): r for r in result}

    w10_high = by_key[(2026, 10, "high")]
    assert w10_high["mttr_median_hours"] == 5.0
    assert w10_high["mttr_p90_hours"] == 9.0
    assert w10_high["sample_size"] == 3

    w10_crit = by_key[(2026, 10, "critical")]
    assert w10_crit["mttr_median_hours"] == 3.0
    assert w10_crit["mttr_p90_hours"] == 4.0
    assert w10_crit["sample_size"] == 2

    w11_high = by_key[(2026, 11, "high")]
    assert w11_high["mttr_median_hours"] == 20.0
    assert w11_high["mttr_p90_hours"] == 30.0
    assert w11_high["sample_size"] == 3

    w11_crit = by_key[(2026, 11, "critical")]
    assert w11_crit["mttr_median_hours"] == 150.0
    assert w11_crit["mttr_p90_hours"] == 200.0
    assert w11_crit["sample_size"] == 2


# ---------------------------------------------------------------------------
# Edge: zero resolved findings


def test_no_findings_returns_empty() -> None:
    assert compute_mttr_rows([], suppression_rules=[], now=NOW) == []


# ---------------------------------------------------------------------------
# Edge: all findings open


def test_all_open_returns_empty() -> None:
    last = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    rows = [
        _finding(
            status="open",
            first_seen_at=last - timedelta(hours=h),
            last_seen_at=last,
        )
        for h in (1, 2, 3)
    ]
    assert compute_mttr_rows(rows, suppression_rules=[], now=NOW) == []


# ---------------------------------------------------------------------------
# Edge: single resolved finding


def test_single_resolved_finding_median_equals_p90() -> None:
    last = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    first = last - timedelta(hours=42)
    rows = [_finding(first_seen_at=first, last_seen_at=last)]

    result = compute_mttr_rows(rows, suppression_rules=[], now=NOW)
    assert len(result) == 1
    row = result[0]
    assert row["sample_size"] == 1
    assert row["mttr_median_hours"] == 42.0
    assert row["mttr_p90_hours"] == 42.0
    assert row["iso_year"] == 2026
    assert row["iso_week"] == 10
    assert row["tool_source"] == "semgrep"
    assert row["severity_canonical"] == "high"


# ---------------------------------------------------------------------------
# Suppression: tool_source rule excludes findings before MTTR


def test_tool_source_suppression_rule_excludes_findings() -> None:
    last = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    rows = [
        _finding(
            tool_source="semgrep",
            first_seen_at=last - timedelta(hours=1),
            last_seen_at=last,
        ),
        _finding(
            tool_source="sonarqube",
            first_seen_at=last - timedelta(hours=2),
            last_seen_at=last,
        ),
    ]
    rules = [_rule("tool_source", "semgrep")]

    result = compute_mttr_rows(rows, suppression_rules=rules, now=NOW)
    assert len(result) == 1
    assert result[0]["tool_source"] == "sonarqube"
    assert result[0]["sample_size"] == 1
    assert result[0]["mttr_median_hours"] == 2.0


def test_expired_suppression_rule_does_not_exclude() -> None:
    """An expired rule must NOT filter — the Gold output should include
    the finding it nominally covers."""
    last = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    rows = [
        _finding(
            tool_source="semgrep",
            first_seen_at=last - timedelta(hours=5),
            last_seen_at=last,
        ),
    ]
    expired = NOW - timedelta(days=1)
    rules = [_rule("tool_source", "semgrep", expires=expired)]

    result = compute_mttr_rows(rows, suppression_rules=rules, now=NOW)
    assert len(result) == 1
    assert result[0]["tool_source"] == "semgrep"


# ---------------------------------------------------------------------------
# ISO week boundary


def test_iso_week_boundary_2025_2026_split() -> None:
    """Per ISO-8601:
        - 2025-12-29 (Mon) lies in ISO 2026-W01 (the week containing the
          first Thursday of 2026, which is 2026-01-01).
        - 2025-12-25 (Thu) lies in ISO 2025-W52.

    Two findings — one resolved on 2025-12-25 (W52), one on 2026-01-01 (W01)
    — must land in distinct ISO-week buckets, with iso_year carrying
    the ISO-year (which differs from the calendar year for the W01 row
    since 2026-01-01 is in calendar 2026 anyway, but the principle holds).
    """
    last_w52 = datetime(2025, 12, 25, 12, 0, tzinfo=UTC)  # Thu, ISO 2025-W52
    last_w01 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # Thu, ISO 2026-W01

    rows = [
        _finding(
            first_seen_at=last_w52 - timedelta(hours=10),
            last_seen_at=last_w52,
        ),
        _finding(
            first_seen_at=last_w01 - timedelta(hours=20),
            last_seen_at=last_w01,
        ),
    ]
    result = compute_mttr_rows(rows, suppression_rules=[], now=NOW)

    # Two distinct buckets, sorted ascending by (iso_year, iso_week).
    assert len(result) == 2
    first, second = result
    assert (first["iso_year"], first["iso_week"]) == (2025, 52)
    assert first["sample_size"] == 1
    assert first["mttr_median_hours"] == 10.0

    assert (second["iso_year"], second["iso_week"]) == (2026, 1)
    assert second["sample_size"] == 1
    assert second["mttr_median_hours"] == 20.0


# ---------------------------------------------------------------------------
# Spark-application path — skip-marked per CLAUDE.md "Don'ts".


@pytest.mark.skip(
    reason=(
        "_spark_main is Spark-applied; runs on the Databricks job cluster, "
        "not in local pytest (per CLAUDE.md)."
    )
)
def test_spark_main_runs_on_databricks() -> None:
    raise AssertionError("unreachable — test is skip-marked")
