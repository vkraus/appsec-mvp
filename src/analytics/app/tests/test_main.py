"""Tests for the FastAPI route handlers in ``src/analytics/app/main.py``.

The Databricks SQL helpers (``queries.fetch_score`` / ``queries.fetch_findings``)
are patched per-test via ``unittest.mock.patch`` so the handlers are exercised
without a live connector.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.analytics.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _autouse_patch_connect(patch_connect):
    """Apply the shared ``patch_connect`` fixture to every test in this module."""
    yield


# --- /v1/score ---


def test_get_score_happy_path() -> None:
    """A known application_id returns 200 with score breakdown."""
    fake_payload = {
        "application_id": "APP-001",
        "score": 13,
        "severity_breakdown": {"critical": 1, "high": 1, "medium": 0, "low": 0},
        "snapshot_date": "2026-04-25",
    }
    with patch(
        "src.analytics.app.main.queries.fetch_score",
        return_value=fake_payload,
    ):
        response = client.get("/v1/score", params={"app_id": "APP-001"})

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] == "APP-001"
    assert body["score"] == 13
    assert body["severity_breakdown"]["critical"] == 1
    assert body["snapshot_date"] == "2026-04-25"


def test_get_score_unknown_app_returns_404() -> None:
    """An unknown application_id (None from fetch_score) returns 404."""
    with patch(
        "src.analytics.app.main.queries.fetch_score",
        return_value=None,
    ):
        response = client.get("/v1/score", params={"app_id": "DOES-NOT-EXIST"})

    assert response.status_code == 404
    assert "DOES-NOT-EXIST" in response.json()["detail"]


def test_get_score_missing_app_id_returns_422() -> None:
    """FastAPI rejects a missing required query param with 422."""
    response = client.get("/v1/score")
    assert response.status_code == 422


# --- /v1/precommit ---


def test_post_precommit_allows_when_no_findings_exceed_threshold() -> None:
    """An all-medium candidate list under the default 'high' threshold passes."""
    findings = [
        {
            "finding_id": "F-1",
            "severity_canonical": "medium",
            "repository_id": "repo-A",
            "application_id": "APP-001",
        },
        {
            "finding_id": "F-2",
            "severity_canonical": "low",
            "repository_id": "repo-A",
            "application_id": "APP-001",
        },
    ]
    with patch(
        "src.analytics.app.main.queries.fetch_findings",
        return_value=findings,
    ):
        response = client.post(
            "/v1/precommit",
            params={"repo": "repo-A", "pr_id": "42"},
            json={"candidate_finding_ids": ["F-1", "F-2"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["allow"] is True
    assert body["blocking_findings"] == []
    assert "allow" in body["policy_summary"].lower()


def test_post_precommit_blocks_when_high_severity_present() -> None:
    """A 'high' candidate finding under the default 'high' threshold blocks."""
    findings = [
        {
            "finding_id": "F-1",
            "severity_canonical": "high",
            "repository_id": "repo-A",
            "application_id": "APP-001",
        },
        {
            "finding_id": "F-2",
            "severity_canonical": "low",
            "repository_id": "repo-A",
            "application_id": "APP-001",
        },
    ]
    with patch(
        "src.analytics.app.main.queries.fetch_findings",
        return_value=findings,
    ):
        response = client.post(
            "/v1/precommit",
            params={"repo": "repo-A", "pr_id": "42"},
            json={"candidate_finding_ids": ["F-1", "F-2"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["allow"] is False
    assert len(body["blocking_findings"]) == 1
    assert body["blocking_findings"][0]["finding_id"] == "F-1"
    assert "block" in body["policy_summary"].lower()


def test_post_precommit_empty_candidates_allows() -> None:
    """An empty candidate list short-circuits to allow=True without DB call."""
    response = client.post(
        "/v1/precommit",
        params={"repo": "repo-A", "pr_id": "42"},
        json={"candidate_finding_ids": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["allow"] is True
    assert body["blocking_findings"] == []


def test_post_precommit_rejects_non_list_body() -> None:
    """A non-list candidate_finding_ids returns 400."""
    response = client.post(
        "/v1/precommit",
        params={"repo": "repo-A", "pr_id": "42"},
        json={"candidate_finding_ids": "F-1"},
    )
    assert response.status_code == 400


# --- live tests (skipped per CLAUDE.md "no live cluster in unit tests") ---


@pytest.mark.skip(reason="Live test — requires DATABRICKS_* env vars + Online Tables")
def test_live_get_score() -> None:  # pragma: no cover
    """Hit the deployed App against a real Online Table — manual run only."""
    raise NotImplementedError


@pytest.mark.skip(reason="Live test — requires DATABRICKS_* env vars + Online Tables")
def test_live_post_precommit() -> None:  # pragma: no cover
    """Hit the deployed App against a real Online Table — manual run only."""
    raise NotImplementedError
