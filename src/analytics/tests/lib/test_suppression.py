"""Unit tests for the analytics-side suppression helper.

Pure-Python coverage of rule-matching semantics. The Spark-applied
:func:`apply_suppression_rules` wrapper is exercised on the Databricks
job cluster; CLAUDE.md "Don'ts" prohibits a local SparkSession in tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.analytics.lib.suppression import (
    is_row_suppressed,
    is_rule_active,
    rule_matches_value,
)


NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(days=1)


def _rule(
    scope: str,
    target: str,
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


# ---------------------------------------------------------------------------
# is_rule_active


def test_active_rule_is_active() -> None:
    assert is_rule_active(_rule("category", "sast"), NOW) is True


def test_expired_rule_is_inactive() -> None:
    assert is_rule_active(_rule("category", "sast", expires=PAST), NOW) is False


def test_rule_expiring_exactly_at_now_is_inactive() -> None:
    # Strict greater-than: a rule whose expires_at == now is treated as expired.
    assert is_rule_active(_rule("category", "sast", expires=NOW), NOW) is False


# ---------------------------------------------------------------------------
# rule_matches_value


def test_literal_match() -> None:
    assert rule_matches_value(_rule("tool_source", "semgrep"), "semgrep") is True


def test_literal_mismatch() -> None:
    assert rule_matches_value(_rule("tool_source", "semgrep"), "sonarqube") is False


def test_none_value_never_matches() -> None:
    assert rule_matches_value(_rule("tool_source", "semgrep"), None) is False


def test_trailing_wildcard_matches_exact_prefix() -> None:
    assert rule_matches_value(_rule("repository_id", "myorg/*"), "myorg") is True


def test_trailing_wildcard_matches_subpath() -> None:
    assert rule_matches_value(_rule("repository_id", "myorg/*"), "myorg/repo") is True


def test_trailing_wildcard_does_not_match_other_prefix() -> None:
    assert rule_matches_value(_rule("repository_id", "myorg/*"), "otherorg/repo") is False


def test_trailing_wildcard_distinguishes_repo_vs_repository() -> None:
    # `myorg/*` must NOT match `myorganization` — wildcard semantics are
    # delimiter-aware via the explicit `prefix + "/"` check.
    assert rule_matches_value(_rule("repository_id", "myorg/*"), "myorganization") is False


# ---------------------------------------------------------------------------
# is_row_suppressed


def test_no_rules_means_no_suppression() -> None:
    row = {"tool_source": "semgrep", "category": "sast", "repository_id": "r/x"}
    assert is_row_suppressed(row, rules=[], now=NOW) is False


def test_single_matching_rule_suppresses() -> None:
    row = {"tool_source": "semgrep"}
    rules = [_rule("tool_source", "semgrep")]
    assert is_row_suppressed(row, rules, now=NOW) is True


def test_single_non_matching_rule_does_not_suppress() -> None:
    row = {"tool_source": "semgrep"}
    rules = [_rule("tool_source", "sonarqube")]
    assert is_row_suppressed(row, rules, now=NOW) is False


def test_expired_rule_never_suppresses() -> None:
    row = {"tool_source": "semgrep"}
    rules = [_rule("tool_source", "semgrep", expires=PAST)]
    assert is_row_suppressed(row, rules, now=NOW) is False


def test_rule_with_irrelevant_scope_is_skipped() -> None:
    # Rule scoped to application_id, but findings df has no application_id
    # column at this call site (pre-join with app_repo_mapping).
    row = {"tool_source": "semgrep", "category": "sast"}
    rules = [_rule("application_id", "APP-1")]
    assert is_row_suppressed(row, rules, now=NOW) is False


def test_multiple_rules_any_match_suppresses() -> None:
    row = {"tool_source": "semgrep", "category": "sast"}
    rules = [
        _rule("tool_source", "sonarqube", rule_id="r1"),  # mismatch
        _rule("category", "sast", rule_id="r2"),  # match
    ]
    assert is_row_suppressed(row, rules, now=NOW) is True


def test_wildcard_rule_in_row_suppression() -> None:
    row = {"repository_id": "myorg/repo-1"}
    rules = [_rule("repository_id", "myorg/*")]
    assert is_row_suppressed(row, rules, now=NOW) is True


def test_post_join_application_id_rule_works() -> None:
    # After Gold-side join with app_repo_mapping, application_id is on
    # the joined df and rules with scope=application_id should match.
    row = {
        "tool_source": "semgrep",
        "repository_id": "myorg/repo-1",
        "application_id": "APP-1",
    }
    rules = [_rule("application_id", "APP-1")]
    assert is_row_suppressed(row, rules, now=NOW) is True


def test_default_now_uses_current_time() -> None:
    # Smoke test: when now is omitted, a rule expiring far in the past is
    # treated as inactive against the actual current time.
    row = {"tool_source": "semgrep"}
    rules = [_rule("tool_source", "semgrep", expires=datetime(2000, 1, 1, tzinfo=timezone.utc))]
    assert is_row_suppressed(row, rules) is False


# ---------------------------------------------------------------------------
# Spark-applied path — skip-marked per CLAUDE.md.


@pytest.mark.skip(reason="apply_suppression_rules is Spark-applied; runs on the Databricks job cluster, not in local pytest (per CLAUDE.md)")
def test_apply_suppression_rules_spark() -> None:
    raise AssertionError("unreachable — test is skip-marked")
