"""Unit tests for ``gold.coverage_matrix`` aggregation.

Pure-Python coverage of :func:`compute_coverage_rows`. The Spark driver
section of the notebook is exercised on the Databricks job cluster, not
locally (CLAUDE.md "Don'ts" prohibits a local SparkSession).

The notebook file is a Databricks-source-formatted .py with top-level
``dbutils.widgets.get(...)`` and ``spark.read.table(...)`` calls below
the ``# COMMAND ----------`` separators, so a normal ``import`` would
fail locally (those globals are runtime-injected on Databricks). We
instead read the file, slice everything before the FIRST COMMAND
separator (the helper-only prefix), and exec it into a fresh module
namespace via :func:`_load_helpers`. That gives us
:func:`compute_coverage_rows` and :data:`CANONICAL_CATEGORIES` without
ever touching Spark.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the notebook's pure-Python helpers without triggering Spark.
#
# The notebook file is a Databricks-source-formatted .py — it has top-level
# `dbutils.widgets.get(...)` and `spark.read.table(...)` calls below the
# `# COMMAND ----------` separators. We can't simply `import` it locally
# because dbutils and spark are notebook-runtime globals.
#
# Strategy: read the file, slice off everything from the first
# `# COMMAND ----------` separator that starts the Spark driver section
# onward, exec the helpers-only prefix into a fresh module namespace.

_NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / "analytics" / "notebooks" / "gold" / "coverage_matrix.py"
)


def _load_helpers() -> types.ModuleType:
    """Exec only the pure-Python helper section of the notebook."""
    src = _NOTEBOOK_PATH.read_text(encoding="utf-8")
    marker = "# COMMAND ----------"
    # The helpers are everything before the FIRST COMMAND separator.
    head, sep, _ = src.partition(marker)
    assert sep, f"expected '{marker}' in {_NOTEBOOK_PATH}"
    module = types.ModuleType("coverage_matrix_helpers")
    module.__file__ = str(_NOTEBOOK_PATH)
    exec(compile(head, str(_NOTEBOOK_PATH), "exec"), module.__dict__)
    return module


_helpers = _load_helpers()
compute_coverage_rows = _helpers.compute_coverage_rows
CANONICAL_CATEGORIES = _helpers.CANONICAL_CATEGORIES
DEFAULT_STALENESS_THRESHOLD_DAYS = _helpers.DEFAULT_STALENESS_THRESHOLD_DAYS


# ---------------------------------------------------------------------------
# Fixtures

NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)


def _repo(rid: str) -> dict:
    return {"repository_id": rid}


def _finding(repo: str, category: str, last_seen: datetime) -> dict:
    return {
        "repository_id": repo,
        "category": category,
        "last_seen_at": last_seen,
    }


# ---------------------------------------------------------------------------
# Constants


def test_canonical_categories_are_the_four_appsec_categories() -> None:
    # Lock the canonical set; downstream Online Tables and dashboards
    # depend on this exact tuple.
    assert CANONICAL_CATEGORIES == ("sast", "sca", "secrets", "scm")


def test_default_threshold_is_30_days() -> None:
    assert DEFAULT_STALENESS_THRESHOLD_DAYS == 30


# ---------------------------------------------------------------------------
# Shape — dense matrix


def test_three_repos_four_categories_produces_twelve_rows() -> None:
    repos = [_repo("r1"), _repo("r2"), _repo("r3")]
    rows = compute_coverage_rows(repos, [], NOW)
    assert len(rows) == 12


def test_empty_repos_produces_no_rows() -> None:
    rows = compute_coverage_rows([], [], NOW)
    assert rows == []


def test_dense_matrix_one_row_per_repo_category_pair() -> None:
    repos = [_repo("r1"), _repo("r2")]
    rows = compute_coverage_rows(repos, [], NOW)
    pairs = {(r["repository_id"], r["category"]) for r in rows}
    expected = {(rid, cat) for rid in ("r1", "r2") for cat in CANONICAL_CATEGORIES}
    assert pairs == expected


# ---------------------------------------------------------------------------
# Last-scan reduction


def test_empty_findings_means_all_last_scan_null_and_stale() -> None:
    repos = [_repo("r1"), _repo("r2")]
    rows = compute_coverage_rows(repos, [], NOW)
    assert all(r["last_scan_at"] is None for r in rows)
    assert all(r["is_stale"] is True for r in rows)


def test_typical_mixed_findings_produces_correct_matrix() -> None:
    repos = [_repo("r1"), _repo("r2"), _repo("r3")]
    findings = [
        # r1: sast scan 5 days ago (fresh), no others
        _finding("r1", "sast", NOW - timedelta(days=5)),
        # r2: secrets 50 days ago (stale), scm 1 day ago (fresh)
        _finding("r2", "secrets", NOW - timedelta(days=50)),
        _finding("r2", "scm", NOW - timedelta(days=1)),
        # r3: nothing
    ]
    rows = compute_coverage_rows(repos, findings, NOW)
    assert len(rows) == 12

    by_pair = {(r["repository_id"], r["category"]): r for r in rows}

    # r1 sast — fresh
    assert by_pair[("r1", "sast")]["last_scan_at"] == NOW - timedelta(days=5)
    assert by_pair[("r1", "sast")]["is_stale"] is False
    # r1 sca — never ran
    assert by_pair[("r1", "sca")]["last_scan_at"] is None
    assert by_pair[("r1", "sca")]["is_stale"] is True

    # r2 secrets — stale (50d > 30d)
    assert by_pair[("r2", "secrets")]["last_scan_at"] == NOW - timedelta(days=50)
    assert by_pair[("r2", "secrets")]["is_stale"] is True
    # r2 scm — fresh
    assert by_pair[("r2", "scm")]["is_stale"] is False

    # r3 — every category null and stale
    for cat in CANONICAL_CATEGORIES:
        assert by_pair[("r3", cat)]["last_scan_at"] is None
        assert by_pair[("r3", cat)]["is_stale"] is True


def test_multiple_scans_in_same_category_only_latest_counts() -> None:
    # A repo with three sast scans — only the most recent wins.
    repos = [_repo("r1")]
    findings = [
        _finding("r1", "sast", NOW - timedelta(days=20)),
        _finding("r1", "sast", NOW - timedelta(days=2)),  # latest
        _finding("r1", "sast", NOW - timedelta(days=10)),
    ]
    rows = compute_coverage_rows(repos, findings, NOW)
    sast_row = next(r for r in rows if r["category"] == "sast")
    assert sast_row["last_scan_at"] == NOW - timedelta(days=2)
    assert sast_row["is_stale"] is False


def test_findings_with_unknown_category_are_skipped() -> None:
    # A finding with category outside the canonical four must not appear
    # in the matrix and must not pollute any cell.
    repos = [_repo("r1")]
    findings = [
        _finding("r1", "dast", NOW - timedelta(days=1)),  # off-canon
        _finding("r1", "sast", NOW - timedelta(days=10)),
    ]
    rows = compute_coverage_rows(repos, findings, NOW)
    cats = {r["category"] for r in rows}
    assert cats == set(CANONICAL_CATEGORIES)
    sast_row = next(r for r in rows if r["category"] == "sast")
    assert sast_row["last_scan_at"] == NOW - timedelta(days=10)


def test_findings_for_unknown_repo_are_silently_dropped() -> None:
    # silver.findings rows for a repository that's not in silver.repositories
    # (e.g. ingested before the repo row landed) must NOT appear in the
    # matrix — matrix is indexed by silver.repositories.
    repos = [_repo("r1")]
    findings = [
        _finding("r-orphan", "sast", NOW - timedelta(days=1)),
        _finding("r1", "sca", NOW - timedelta(days=2)),
    ]
    rows = compute_coverage_rows(repos, findings, NOW)
    repo_ids = {r["repository_id"] for r in rows}
    assert repo_ids == {"r1"}


def test_finding_with_null_repository_id_is_dropped() -> None:
    # silver.findings.repository_id is nullable (e.g. tool-source findings
    # with no SCM context); these must not break the cross-join.
    repos = [_repo("r1")]
    findings = [
        {"repository_id": None, "category": "sast", "last_seen_at": NOW},
        _finding("r1", "sast", NOW - timedelta(days=2)),
    ]
    rows = compute_coverage_rows(repos, findings, NOW)
    sast_row = next(r for r in rows if r["category"] == "sast")
    assert sast_row["last_scan_at"] == NOW - timedelta(days=2)


# ---------------------------------------------------------------------------
# Staleness boundary


def test_scan_29_days_ago_is_fresh_with_default_threshold() -> None:
    repos = [_repo("r1")]
    findings = [_finding("r1", "sast", NOW - timedelta(days=29))]
    rows = compute_coverage_rows(repos, findings, NOW)  # default 30d
    sast_row = next(r for r in rows if r["category"] == "sast")
    assert sast_row["is_stale"] is False


def test_scan_31_days_ago_is_stale_with_default_threshold() -> None:
    repos = [_repo("r1")]
    findings = [_finding("r1", "sast", NOW - timedelta(days=31))]
    rows = compute_coverage_rows(repos, findings, NOW)
    sast_row = next(r for r in rows if r["category"] == "sast")
    assert sast_row["is_stale"] is True


def test_threshold_days_is_emitted_on_every_row() -> None:
    repos = [_repo("r1"), _repo("r2")]
    rows = compute_coverage_rows(repos, [], NOW, threshold_days=7)
    assert all(r["staleness_threshold_days"] == 7 for r in rows)


def test_custom_threshold_changes_staleness_boundary() -> None:
    # 10-day-old scan: stale at threshold=7, fresh at threshold=30.
    repos = [_repo("r1")]
    findings = [_finding("r1", "sast", NOW - timedelta(days=10))]

    rows_strict = compute_coverage_rows(repos, findings, NOW, threshold_days=7)
    sast_strict = next(r for r in rows_strict if r["category"] == "sast")
    assert sast_strict["is_stale"] is True

    rows_loose = compute_coverage_rows(repos, findings, NOW, threshold_days=30)
    sast_loose = next(r for r in rows_loose if r["category"] == "sast")
    assert sast_loose["is_stale"] is False


def test_now_value_shifts_staleness_boundary() -> None:
    # Same scan timestamp; advancing 'now' makes a fresh row stale.
    repos = [_repo("r1")]
    scan_time = NOW - timedelta(days=20)
    findings = [_finding("r1", "sast", scan_time)]

    rows_now = compute_coverage_rows(repos, findings, NOW)  # 20d gap < 30d
    assert next(r for r in rows_now if r["category"] == "sast")["is_stale"] is False

    later = NOW + timedelta(days=15)  # gap is now 35d > 30d
    rows_later = compute_coverage_rows(repos, findings, later)
    assert next(r for r in rows_later if r["category"] == "sast")["is_stale"] is True


def test_scan_exactly_at_threshold_boundary_is_stale() -> None:
    # Strict less-than: scan_at exactly equal to (now - threshold) is stale.
    # Matches the Spark predicate `last_scan_at < current_timestamp - INTERVAL`.
    repos = [_repo("r1")]
    findings = [_finding("r1", "sast", NOW - timedelta(days=30))]
    rows = compute_coverage_rows(repos, findings, NOW)
    sast_row = next(r for r in rows if r["category"] == "sast")
    # 30 days ago == cutoff exactly; predicate is `<`, so equal-to-cutoff
    # is NOT stale. (Verifies the strict inequality.)
    assert sast_row["is_stale"] is False


# ---------------------------------------------------------------------------
# Spark-applied path — skip-marked per CLAUDE.md.


@pytest.mark.skip(
    reason="Notebook driver is Spark-applied; runs on the Databricks job "
    "cluster, not in local pytest (per CLAUDE.md)"
)
def test_notebook_driver_spark() -> None:
    raise AssertionError("unreachable — test is skip-marked")
