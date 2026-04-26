"""Unit tests for ``gold.cwe_owasp_heatmap`` aggregation logic.

Pure-Python coverage of :func:`compute_heatmap_rows` and the canonical
OWASP Top 10:2021 → CWE primary mapping. The Spark driver section of
the notebook is exercised on the Databricks job cluster, not locally
(CLAUDE.md "Don'ts" prohibits a local SparkSession).

The notebook file is a Databricks-source-formatted .py with top-level
``dbutils.widgets.get(...)`` and ``spark.read.table(...)`` calls below
the ``# COMMAND ----------`` separators, so a normal ``import`` would
fail locally (those globals are runtime-injected on Databricks). We
instead read the file, slice off the first ``# COMMAND ----------``
onward, and exec the helpers-only prefix into a fresh module namespace.
This mirrors :mod:`src.analytics.tests.gold.test_coverage_matrix`.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the notebook's pure-Python helpers without triggering Spark.

_NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / "analytics" / "notebooks" / "gold" / "cwe_owasp_heatmap.py"
)


def _load_helpers() -> types.ModuleType:
    """Exec only the pure-Python helper section of the notebook."""
    src = _NOTEBOOK_PATH.read_text(encoding="utf-8")
    marker = "# COMMAND ----------"
    head, sep, _ = src.partition(marker)
    assert sep, f"expected '{marker}' in {_NOTEBOOK_PATH}"
    module = types.ModuleType("cwe_owasp_heatmap_helpers")
    module.__file__ = str(_NOTEBOOK_PATH)
    exec(compile(head, str(_NOTEBOOK_PATH), "exec"), module.__dict__)
    return module


_helpers = _load_helpers()
compute_heatmap_rows = _helpers.compute_heatmap_rows
_classify_cwe = _helpers._classify_cwe
OWASP_2021_CWE_TO_CATEGORY = _helpers.OWASP_2021_CWE_TO_CATEGORY
OWASP_2021_A01_BROKEN_ACCESS_CONTROL = _helpers.OWASP_2021_A01_BROKEN_ACCESS_CONTROL
OWASP_2021_A02_CRYPTOGRAPHIC_FAILURES = _helpers.OWASP_2021_A02_CRYPTOGRAPHIC_FAILURES
OWASP_2021_A03_INJECTION = _helpers.OWASP_2021_A03_INJECTION
OWASP_2021_A10_SERVER_SIDE_REQUEST_FORGERY = _helpers.OWASP_2021_A10_SERVER_SIDE_REQUEST_FORGERY
UNMAPPED_APPLICATION_ID = _helpers.UNMAPPED_APPLICATION_ID
UNMAPPED_OWASP_CATEGORY = _helpers.UNMAPPED_OWASP_CATEGORY


# ---------------------------------------------------------------------------
# Fixtures

NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=30)


def _finding(
    finding_id: str,
    repository_id: str | None,
    cwe_id: str | None,
    status: str = "open",
    tool_source: str = "semgrep",
    category: str = "sast",
    file_path: str | None = None,
) -> dict:
    return {
        "finding_id": finding_id,
        "repository_id": repository_id,
        "cwe_id": cwe_id,
        "status_canonical": status,
        "tool_source": tool_source,
        "category": category,
        "file_path": file_path,
    }


def _mapping(application_id: str, repository_id: str) -> dict:
    return {"application_id": application_id, "repository_id": repository_id}


def _rule(scope: str, target: str, expires: datetime = FUTURE, rule_id: str = "r1") -> dict:
    return {
        "rule_id": rule_id,
        "scope": scope,
        "target_pattern": target,
        "expires_at": expires,
        "reason": "test",
        "created_by": "test@example.com",
        "created_at": NOW,
    }


def _by_key(rows: list[dict]) -> dict[tuple, dict]:
    """Index output rows by their natural key for stable lookup in asserts."""
    return {
        (r["application_id"], r["owasp_category"], r["cwe_id"]): r for r in rows
    }


# ---------------------------------------------------------------------------
# OWASP 2021 mapping integrity — guard against typos and accidental edits.


def test_owasp_2021_mapping_covers_all_ten_categories() -> None:
    categories_seen = set(OWASP_2021_CWE_TO_CATEGORY.values())
    assert categories_seen == {
        "A01", "A02", "A03", "A04", "A05",
        "A06", "A07", "A08", "A09", "A10",
    }


def test_a10_ssrf_is_cwe_918_only() -> None:
    # OWASP 2021 A10 Server-Side Request Forgery has exactly one mapped
    # CWE per the Foundation's primary mapping.
    assert OWASP_2021_A10_SERVER_SIDE_REQUEST_FORGERY == frozenset({"CWE-918"})
    assert OWASP_2021_CWE_TO_CATEGORY["CWE-918"] == "A10"


def test_a01_includes_canonical_access_control_cwes() -> None:
    # Spec mentions CWE-22 (path traversal), CWE-285 (improper authz),
    # CWE-639 (auth bypass via user-controlled key) — all A01.
    for cwe in ("CWE-22", "CWE-285", "CWE-639"):
        assert cwe in OWASP_2021_A01_BROKEN_ACCESS_CONTROL
        assert OWASP_2021_CWE_TO_CATEGORY[cwe] == "A01"


def test_a03_includes_canonical_injection_cwes() -> None:
    # SQLi (CWE-89), XSS (CWE-79), command injection (CWE-78), generic
    # injection root (CWE-74) — all A03.
    for cwe in ("CWE-74", "CWE-78", "CWE-79", "CWE-89"):
        assert cwe in OWASP_2021_A03_INJECTION
        assert OWASP_2021_CWE_TO_CATEGORY[cwe] == "A03"


def test_a02_includes_canonical_crypto_cwes() -> None:
    # Broken/risky crypto algorithm (CWE-327), cleartext transmission
    # (CWE-319) — both A02.
    for cwe in ("CWE-319", "CWE-327"):
        assert cwe in OWASP_2021_A02_CRYPTOGRAPHIC_FAILURES
        assert OWASP_2021_CWE_TO_CATEGORY[cwe] == "A02"


def test_no_cwe_double_assigned() -> None:
    # The notebook's _build_cwe_to_category raises on import if a CWE
    # appears in two categories; this test cross-validates against a
    # representative subset to surface drift if the OWASP source is
    # re-imported with conflicts.
    seen: dict[str, str] = {}
    sets = [
        ("A01", OWASP_2021_A01_BROKEN_ACCESS_CONTROL),
        ("A02", OWASP_2021_A02_CRYPTOGRAPHIC_FAILURES),
        ("A03", OWASP_2021_A03_INJECTION),
        ("A10", OWASP_2021_A10_SERVER_SIDE_REQUEST_FORGERY),
    ]
    for cat, s in sets:
        for cwe in s:
            assert cwe not in seen, (
                f"{cwe} double-assigned to {seen[cwe]} and {cat}"
            )
            seen[cwe] = cat


# ---------------------------------------------------------------------------
# _classify_cwe


def test_classify_known_cwe_returns_category() -> None:
    assert _classify_cwe("CWE-89") == "A03"


def test_classify_null_cwe_returns_unmapped() -> None:
    assert _classify_cwe(None) == UNMAPPED_OWASP_CATEGORY


def test_classify_unknown_cwe_returns_unmapped() -> None:
    # CWE-99999 is not on any OWASP 2021 list.
    assert _classify_cwe("CWE-99999") == UNMAPPED_OWASP_CATEGORY


# ---------------------------------------------------------------------------
# compute_heatmap_rows — typical scenarios


def test_typical_heatmap_two_apps_three_categories() -> None:
    # 10 findings: APP-1 sees 3 SQLi (A03), 2 path-traversal (A01),
    # 1 SSRF (A10). APP-2 sees 2 XSS (A03), 1 weak-crypto (A02), 1
    # auth-bypass (A07). All open. Verify the count matrix.
    app_repo = [
        _mapping("APP-1", "repo-1"),
        _mapping("APP-2", "repo-2"),
    ]
    findings = [
        _finding("f1", "repo-1", "CWE-89"),  # A03
        _finding("f2", "repo-1", "CWE-89"),  # A03
        _finding("f3", "repo-1", "CWE-89"),  # A03
        _finding("f4", "repo-1", "CWE-22"),  # A01
        _finding("f5", "repo-1", "CWE-22"),  # A01
        _finding("f6", "repo-1", "CWE-918"),  # A10
        _finding("f7", "repo-2", "CWE-79"),  # A03
        _finding("f8", "repo-2", "CWE-79"),  # A03
        _finding("f9", "repo-2", "CWE-327"),  # A02
        _finding("f10", "repo-2", "CWE-287"),  # A07
    ]

    rows = compute_heatmap_rows(findings, app_repo)
    indexed = _by_key(rows)

    assert indexed[("APP-1", "A03", "CWE-89")]["finding_count"] == 3
    assert indexed[("APP-1", "A01", "CWE-22")]["finding_count"] == 2
    assert indexed[("APP-1", "A10", "CWE-918")]["finding_count"] == 1
    assert indexed[("APP-2", "A03", "CWE-79")]["finding_count"] == 2
    assert indexed[("APP-2", "A02", "CWE-327")]["finding_count"] == 1
    assert indexed[("APP-2", "A07", "CWE-287")]["finding_count"] == 1
    # Total of 6 distinct (app, category, cwe) groups.
    assert len(rows) == 6


def test_unknown_cwe_buckets_as_unmapped() -> None:
    findings = [_finding("f1", "repo-1", "CWE-99999")]
    rows = compute_heatmap_rows(findings, [_mapping("APP-1", "repo-1")])

    assert len(rows) == 1
    assert rows[0]["application_id"] == "APP-1"
    assert rows[0]["owasp_category"] == UNMAPPED_OWASP_CATEGORY
    assert rows[0]["cwe_id"] == "CWE-99999"
    assert rows[0]["finding_count"] == 1


def test_null_cwe_buckets_as_unmapped() -> None:
    findings = [_finding("f1", "repo-1", None)]
    rows = compute_heatmap_rows(findings, [_mapping("APP-1", "repo-1")])

    assert len(rows) == 1
    assert rows[0]["application_id"] == "APP-1"
    assert rows[0]["owasp_category"] == UNMAPPED_OWASP_CATEGORY
    assert rows[0]["cwe_id"] is None
    assert rows[0]["finding_count"] == 1


def test_closed_findings_excluded() -> None:
    findings = [
        _finding("f1", "repo-1", "CWE-89", status="open"),
        _finding("f2", "repo-1", "CWE-89", status="closed"),
        _finding("f3", "repo-1", "CWE-89", status="resolved"),
    ]
    rows = compute_heatmap_rows(findings, [_mapping("APP-1", "repo-1")])

    indexed = _by_key(rows)
    assert indexed[("APP-1", "A03", "CWE-89")]["finding_count"] == 1


def test_suppression_by_application_id_excludes_findings() -> None:
    findings = [
        _finding("f1", "repo-1", "CWE-89"),
        _finding("f2", "repo-2", "CWE-89"),
    ]
    app_repo = [
        _mapping("APP-1", "repo-1"),
        _mapping("APP-2", "repo-2"),
    ]
    rules = [_rule("application_id", "APP-1")]

    rows = compute_heatmap_rows(findings, app_repo, rules, now=NOW)
    indexed = _by_key(rows)

    # APP-1's finding is muted; APP-2's still flows through.
    assert ("APP-1", "A03", "CWE-89") not in indexed
    assert indexed[("APP-2", "A03", "CWE-89")]["finding_count"] == 1


def test_suppression_by_tool_source_excludes_findings() -> None:
    findings = [
        _finding("f1", "repo-1", "CWE-89", tool_source="semgrep"),
        _finding("f2", "repo-1", "CWE-89", tool_source="sonarqube"),
    ]
    app_repo = [_mapping("APP-1", "repo-1")]
    rules = [_rule("tool_source", "semgrep")]

    rows = compute_heatmap_rows(findings, app_repo, rules, now=NOW)
    indexed = _by_key(rows)

    # Only the sonarqube finding survives.
    assert indexed[("APP-1", "A03", "CWE-89")]["finding_count"] == 1


def test_unmapped_repository_routes_to_unmapped_application() -> None:
    findings = [
        _finding("f1", "repo-orphan", "CWE-89"),  # repo not in mapping
        _finding("f2", None, "CWE-89"),  # repo_id is null
    ]
    app_repo = [_mapping("APP-1", "repo-1")]

    rows = compute_heatmap_rows(findings, app_repo)
    indexed = _by_key(rows)

    assert (
        indexed[(UNMAPPED_APPLICATION_ID, "A03", "CWE-89")]["finding_count"] == 2
    )


def test_repository_mapped_to_multiple_apps_duplicates_count() -> None:
    # One repo linked to two applications: each app sees the finding.
    findings = [_finding("f1", "repo-1", "CWE-89")]
    app_repo = [
        _mapping("APP-1", "repo-1"),
        _mapping("APP-2", "repo-1"),
    ]

    rows = compute_heatmap_rows(findings, app_repo)
    indexed = _by_key(rows)

    assert indexed[("APP-1", "A03", "CWE-89")]["finding_count"] == 1
    assert indexed[("APP-2", "A03", "CWE-89")]["finding_count"] == 1


def test_empty_findings_returns_empty_output() -> None:
    rows = compute_heatmap_rows([], [_mapping("APP-1", "repo-1")])
    assert rows == []


def test_empty_findings_and_empty_mapping_returns_empty_output() -> None:
    assert compute_heatmap_rows([], []) == []


def test_expired_suppression_rule_does_not_filter() -> None:
    findings = [_finding("f1", "repo-1", "CWE-89")]
    app_repo = [_mapping("APP-1", "repo-1")]
    rules = [
        _rule(
            "application_id",
            "APP-1",
            expires=NOW - timedelta(days=1),
        )
    ]

    rows = compute_heatmap_rows(findings, app_repo, rules, now=NOW)
    indexed = _by_key(rows)
    assert indexed[("APP-1", "A03", "CWE-89")]["finding_count"] == 1


# ---------------------------------------------------------------------------
# Spark-applied path — skip-marked per CLAUDE.md.


@pytest.mark.skip(
    reason="Notebook Spark application runs on the Databricks job cluster, "
    "not in local pytest (per CLAUDE.md)."
)
def test_notebook_spark_application() -> None:
    raise AssertionError("unreachable — test is skip-marked")
