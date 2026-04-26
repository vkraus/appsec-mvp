"""Tests for ``src/analytics/app/policy.py``.

Pure-Python — no Spark, no SQL, no FastAPI. Exercises:

- ``evaluate`` at each canonical threshold.
- Empty findings → allow.
- ``load_policy`` happy path + missing-file + malformed key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analytics.app.policy import (
    DEFAULT_THRESHOLD,
    SEVERITY_RANK,
    evaluate,
    load_policy,
)


# --- evaluate ---


def _f(finding_id: str, severity: str) -> dict:
    return {
        "finding_id": finding_id,
        "severity_canonical": severity,
        "repository_id": "repo-A",
        "application_id": "APP-001",
    }


def test_evaluate_threshold_critical_allows_high_blocks_critical() -> None:
    """threshold='critical' lets high through; only critical blocks."""
    findings = [_f("F-1", "high"), _f("F-2", "critical"), _f("F-3", "low")]
    allow, blocking, summary = evaluate(
        findings, {"block_severity_threshold": "critical"}
    )
    assert allow is False
    assert [f["finding_id"] for f in blocking] == ["F-2"]
    assert "block" in summary.lower()


def test_evaluate_threshold_critical_allows_when_no_critical() -> None:
    """threshold='critical' with no critical findings → allow."""
    findings = [_f("F-1", "high"), _f("F-2", "medium")]
    allow, blocking, summary = evaluate(
        findings, {"block_severity_threshold": "critical"}
    )
    assert allow is True
    assert blocking == []
    assert "critical" in summary.lower() or "allow" in summary.lower()


def test_evaluate_threshold_high_blocks_high_and_critical() -> None:
    """threshold='high' blocks both high and critical."""
    findings = [_f("F-1", "high"), _f("F-2", "critical"), _f("F-3", "low")]
    allow, blocking, summary = evaluate(
        findings, {"block_severity_threshold": "high"}
    )
    assert allow is False
    blocked_ids = {f["finding_id"] for f in blocking}
    assert blocked_ids == {"F-1", "F-2"}
    assert "block" in summary.lower()


def test_evaluate_threshold_medium_blocks_medium_and_above() -> None:
    """threshold='medium' blocks medium, high, critical."""
    findings = [_f("F-1", "medium"), _f("F-2", "low")]
    allow, blocking, _ = evaluate(findings, {"block_severity_threshold": "medium"})
    assert allow is False
    assert [f["finding_id"] for f in blocking] == ["F-1"]


def test_evaluate_empty_findings_allows() -> None:
    """An empty candidate list always allows."""
    allow, blocking, summary = evaluate([], {"block_severity_threshold": "high"})
    assert allow is True
    assert blocking == []
    assert "allow" in summary.lower()


def test_evaluate_unknown_severity_treated_as_info() -> None:
    """A finding with an unrecognised severity does not block."""
    findings = [_f("F-1", "BANANA"), _f("F-2", "low")]
    allow, blocking, _ = evaluate(findings, {"block_severity_threshold": "high"})
    assert allow is True
    assert blocking == []


def test_evaluate_severity_case_insensitive() -> None:
    """Uppercase severity values are normalised to lowercase before ranking."""
    findings = [_f("F-1", "CRITICAL")]
    allow, blocking, _ = evaluate(findings, {"block_severity_threshold": "high"})
    assert allow is False
    assert [f["finding_id"] for f in blocking] == ["F-1"]


def test_evaluate_unknown_threshold_falls_back_to_default() -> None:
    """A nonsense threshold falls back to the default ('high')."""
    findings = [_f("F-1", "high")]
    allow, blocking, _ = evaluate(findings, {"block_severity_threshold": "BANANA"})
    # Default is 'high', so a high finding blocks.
    assert allow is False
    assert [f["finding_id"] for f in blocking] == ["F-1"]


# --- load_policy ---


def test_load_policy_happy_path(tmp_path: Path) -> None:
    """A well-formed YAML loads through unchanged (lowercased)."""
    policy_path = tmp_path / "policy.yml"
    policy_path.write_text("block_severity_threshold: critical\n", encoding="utf-8")

    policy = load_policy(policy_path)
    assert policy["block_severity_threshold"] == "critical"


def test_load_policy_missing_file_returns_default(tmp_path: Path) -> None:
    """A missing policy file falls back to the default threshold."""
    policy = load_policy(tmp_path / "does-not-exist.yml")
    assert policy["block_severity_threshold"] == DEFAULT_THRESHOLD


def test_load_policy_missing_key_uses_default(tmp_path: Path) -> None:
    """A YAML file with no ``block_severity_threshold`` key uses the default."""
    policy_path = tmp_path / "policy.yml"
    policy_path.write_text("some_other_key: 42\n", encoding="utf-8")

    policy = load_policy(policy_path)
    assert policy["block_severity_threshold"] == DEFAULT_THRESHOLD


def test_load_policy_invalid_threshold_falls_back(tmp_path: Path) -> None:
    """An unrecognised threshold value falls back to the default."""
    policy_path = tmp_path / "policy.yml"
    policy_path.write_text(
        "block_severity_threshold: banana\n", encoding="utf-8"
    )

    policy = load_policy(policy_path)
    assert policy["block_severity_threshold"] == DEFAULT_THRESHOLD


def test_load_policy_empty_file_returns_default(tmp_path: Path) -> None:
    """An empty YAML file falls back to the default threshold."""
    policy_path = tmp_path / "policy.yml"
    policy_path.write_text("", encoding="utf-8")

    policy = load_policy(policy_path)
    assert policy["block_severity_threshold"] == DEFAULT_THRESHOLD


def test_default_policy_yml_loads(tmp_path: Path) -> None:
    """The shipped default policy.yml parses to a valid threshold."""
    shipped = Path(__file__).parent.parent / "policy.yml"
    assert shipped.exists(), "shipped policy.yml must exist alongside the App"
    policy = load_policy(shipped)
    assert policy["block_severity_threshold"] in SEVERITY_RANK


@pytest.mark.skip(reason="Live test placeholder — policy.yml read in deployed App")
def test_live_load_policy_in_deployed_app() -> None:  # pragma: no cover
    raise NotImplementedError
