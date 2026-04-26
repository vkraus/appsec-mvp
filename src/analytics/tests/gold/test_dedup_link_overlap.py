"""Unit tests for ``gold.dedup_link_overlap`` aggregation logic.

Pure-Python coverage of :func:`compute_overlap_rows`. The Spark driver
path in the notebook is exercised on the Databricks job cluster;
CLAUDE.md "Don'ts" prohibits a local SparkSession in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.analytics.notebooks.gold.dedup_link_overlap import (
    compute_overlap_rows,
)

NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(days=30)


def _suppress(scope: str, target: str) -> dict:
    """Build a synthetic suppression rule (active until FUTURE)."""
    return {
        "rule_id": f"r-{scope}-{target}",
        "scope": scope,
        "target_pattern": target,
        "expires_at": FUTURE,
        "reason": "test",
        "created_by": "test@example.com",
        "created_at": NOW,
    }


def _sast(
    tool_source: str,
    repository_id: str = "myorg/repo-1",
    file_path: str = "src/app.py",
    start_line: int = 42,
    cwe_id: str | None = "CWE-79",
) -> dict:
    return {
        "category": "sast",
        "tool_source": tool_source,
        "repository_id": repository_id,
        "file_path": file_path,
        "start_line": start_line,
        "cwe_id": cwe_id,
        "cve_id": None,
        "rule_id_native": f"{tool_source}-rule-1",
        "url": None,
    }


def _sca(
    tool_source: str,
    repository_id: str = "myorg/repo-1",
    cve_id: str | None = "CVE-2024-1234",
) -> dict:
    return {
        "category": "sca",
        "tool_source": tool_source,
        "repository_id": repository_id,
        "file_path": None,
        "start_line": None,
        "cwe_id": None,
        "cve_id": cve_id,
        "rule_id_native": f"{tool_source}-rule-1",
        "url": None,
    }


def _secrets(
    tool_source: str,
    repository_id: str = "myorg/repo-1",
    file_path: str = "src/secrets.py",
    rule_id_native: str = "aws-access-key",
) -> dict:
    return {
        "category": "secrets",
        "tool_source": tool_source,
        "repository_id": repository_id,
        "file_path": file_path,
        "start_line": None,
        "cwe_id": None,
        "cve_id": None,
        "rule_id_native": rule_id_native,
        "url": None,
    }


def _dast(
    tool_source: str,
    url: str = "https://app.example.com/login",
    rule_id_native: str = "xss-reflected",
) -> dict:
    return {
        "category": "dast",
        "tool_source": tool_source,
        "repository_id": None,
        "file_path": None,
        "start_line": None,
        "cwe_id": None,
        "cve_id": None,
        "rule_id_native": rule_id_native,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Typical case — one linked pair per category.


def test_sast_two_tools_same_dedup_tuple_yields_one_pair() -> None:
    findings = [
        _sast(tool_source="semgrep"),
        _sast(tool_source="sonarqube"),
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == [
        {
            "tool_source_a": "semgrep",
            "tool_source_b": "sonarqube",
            "category": "sast",
            "linked_pair_count": 1,
        }
    ]


def test_sca_two_tools_same_cve_yields_one_pair() -> None:
    findings = [
        _sca(tool_source="dependency_track"),
        _sca(tool_source="snyk"),  # hypothetical second SCA tool
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == [
        {
            "tool_source_a": "dependency_track",
            "tool_source_b": "snyk",
            "category": "sca",
            "linked_pair_count": 1,
        }
    ]


# ---------------------------------------------------------------------------
# Incomplete dedup tuple — no pair counted.


def test_sast_with_null_cwe_yields_no_pair() -> None:
    # Without cwe_id the dedup tuple is incomplete; cross-tool linkage
    # is not canonical so the pair must NOT be counted.
    findings = [
        _sast(tool_source="semgrep", cwe_id=None),
        _sast(tool_source="sonarqube", cwe_id=None),
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == []


def test_sca_with_null_cve_yields_no_pair() -> None:
    findings = [
        _sca(tool_source="dependency_track", cve_id=None),
        _sca(tool_source="snyk", cve_id=None),
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == []


# ---------------------------------------------------------------------------
# Multiple linkage groups — counts sum within a (tool_a, tool_b, category).


def test_sast_multiple_linkage_groups_sum_pair_count() -> None:
    findings = [
        # Group 1: (myorg/repo-1, src/app.py, 42, CWE-79)
        _sast(tool_source="semgrep"),
        _sast(tool_source="sonarqube"),
        # Group 2: (myorg/repo-1, src/auth.py, 10, CWE-89)
        _sast(
            tool_source="semgrep",
            file_path="src/auth.py",
            start_line=10,
            cwe_id="CWE-89",
        ),
        _sast(
            tool_source="sonarqube",
            file_path="src/auth.py",
            start_line=10,
            cwe_id="CWE-89",
        ),
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == [
        {
            "tool_source_a": "semgrep",
            "tool_source_b": "sonarqube",
            "category": "sast",
            "linked_pair_count": 2,
        }
    ]


# ---------------------------------------------------------------------------
# Same tool twice on same dedup tuple — alphabetical pair condition (a<b)
# implicitly excludes intra-tool overlap (not a CROSS-tool pair).


def test_same_tool_twice_on_same_tuple_yields_no_cross_pair() -> None:
    findings = [
        _sast(tool_source="semgrep"),
        _sast(tool_source="semgrep"),  # second semgrep finding, same tuple
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == []


# ---------------------------------------------------------------------------
# Suppression — muted findings drop the pair count to zero.


def test_suppression_drops_pair_count_to_zero() -> None:
    findings = [
        _sast(tool_source="semgrep"),
        _sast(tool_source="sonarqube"),
    ]
    rules = [_suppress("tool_source", "sonarqube")]
    out = compute_overlap_rows(findings, suppression_rules=rules, now=NOW)
    # Without sonarqube there is no cross-tool pair on this tuple.
    assert out == []


def test_suppression_does_not_affect_unrelated_pair() -> None:
    findings = [
        _sast(tool_source="semgrep"),
        _sast(tool_source="sonarqube"),
    ]
    # Suppress a tool that isn't in the data — pair must remain.
    rules = [_suppress("tool_source", "trufflehog")]
    out = compute_overlap_rows(findings, suppression_rules=rules, now=NOW)
    assert out == [
        {
            "tool_source_a": "semgrep",
            "tool_source_b": "sonarqube",
            "category": "sast",
            "linked_pair_count": 1,
        }
    ]


# ---------------------------------------------------------------------------
# Empty / off-spec inputs.


def test_empty_findings_yields_empty_output() -> None:
    assert compute_overlap_rows([], suppression_rules=[], now=NOW) == []


def test_scm_and_waf_categories_are_silently_ignored() -> None:
    # scm and waf have no meaningful cross-tool overlap in the MVP and
    # are not in CATEGORY_DEDUP_KEYS. Findings in those categories must
    # be silently ignored — no pair rows emitted, no errors raised.
    findings = [
        {
            "category": "scm",
            "tool_source": "github",
            "repository_id": "myorg/repo-1",
            "file_path": None,
            "start_line": None,
            "cwe_id": None,
            "cve_id": None,
            "rule_id_native": "branch-protection",
            "url": None,
        },
        {
            "category": "scm",
            "tool_source": "gitlab",
            "repository_id": "myorg/repo-1",
            "file_path": None,
            "start_line": None,
            "cwe_id": None,
            "cve_id": None,
            "rule_id_native": "branch-protection",
            "url": None,
        },
        {
            "category": "waf",
            "tool_source": "aws_waf",
            "repository_id": None,
            "file_path": None,
            "start_line": None,
            "cwe_id": None,
            "cve_id": None,
            "rule_id_native": "managed-rule-1",
            "url": "https://app.example.com/",
        },
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == []


# ---------------------------------------------------------------------------
# Secrets and DAST: confirm the helper applies the right per-category tuple.


def test_secrets_two_tools_same_repo_file_rule_yields_one_pair() -> None:
    findings = [
        _secrets(tool_source="trufflehog"),
        _secrets(tool_source="gitleaks"),  # hypothetical second secrets tool
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == [
        {
            "tool_source_a": "gitleaks",
            "tool_source_b": "trufflehog",
            "category": "secrets",
            "linked_pair_count": 1,
        }
    ]


def test_dast_two_tools_same_url_rule_yields_one_pair() -> None:
    findings = [
        _dast(tool_source="owasp_zap"),
        _dast(tool_source="burp"),  # hypothetical second DAST tool
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    assert out == [
        {
            "tool_source_a": "burp",
            "tool_source_b": "owasp_zap",
            "category": "dast",
            "linked_pair_count": 1,
        }
    ]


# ---------------------------------------------------------------------------
# Multi-category — output is sorted by (category, tool_a, tool_b).


def test_multi_category_output_sorted_deterministically() -> None:
    findings = [
        _sast(tool_source="semgrep"),
        _sast(tool_source="sonarqube"),
        _sca(tool_source="dependency_track"),
        _sca(tool_source="snyk"),
        _dast(tool_source="owasp_zap"),
        _dast(tool_source="burp"),
    ]
    out = compute_overlap_rows(findings, suppression_rules=[], now=NOW)
    categories_in_order = [r["category"] for r in out]
    # Sorted: dast < sast < sca alphabetically.
    assert categories_in_order == ["dast", "sast", "sca"]
    assert all(r["linked_pair_count"] == 1 for r in out)
    assert all(r["tool_source_a"] < r["tool_source_b"] for r in out)


# ---------------------------------------------------------------------------
# Spark-applied path — skip-marked per CLAUDE.md.


@pytest.mark.skip(
    reason="notebook driver path is Spark-applied; runs on the Databricks job cluster, not in local pytest (per CLAUDE.md)"
)
def test_notebook_spark_driver() -> None:
    raise AssertionError("unreachable — test is skip-marked")
