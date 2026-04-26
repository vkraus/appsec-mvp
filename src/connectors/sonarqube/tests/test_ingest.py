"""SonarQube ingest-side framework-contract tests.

Binds REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL, REQ-ING-HWM from the
requirement catalog (mkdocs/docs/platform/reference/catalog.md). All
tests are pure-Python; no live SonarQube instance and no local
SparkSession (per CLAUDE.md "Don'ts").
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from src.connectors.sonarqube.ingest import (
    RateLimitError,
    SecretResolutionError,
    advance_hwm,
    call_with_backoff,
    filter_since_hwm,
    ingest,
    iter_issue_pages,
    resolve_token,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIX / name).read_text())


# --- REQ-ING-AUTH: secret-scope credential resolution ----------------------


@pytest.mark.requirement("REQ-ING-AUTH")
def test_token_resolution_from_secret_scope() -> None:
    """REQ-ING-AUTH: the connector reads the SonarQube token from the
    configured secret scope and key; a missing value raises
    :class:`SecretResolutionError` rather than silently returning None.
    """
    reader = lambda scope, key: {  # noqa: E731
        ("mvp-connectors", "sonarqube_token"): "tok-123",
    }.get((scope, key))

    tok = resolve_token("mvp-connectors", "sonarqube_token", reader)

    assert tok == "tok-123"


@pytest.mark.requirement("REQ-ING-AUTH")
def test_token_resolution_surface_missing_secret() -> None:
    """REQ-ING-AUTH: invalid or absent credentials surface a clear error."""
    with pytest.raises(SecretResolutionError, match="mvp-connectors"):
        resolve_token("mvp-connectors", "sonarqube_token", lambda s, k: None)


# --- REQ-ING-PAG: pagination ------------------------------------------------


@pytest.mark.requirement("REQ-ING-PAG")
def test_page_index_pagination_two_pages() -> None:
    """REQ-ING-PAG: pagination traverses two pages without loss or
    duplication, driven by ``paging.total`` on the first page.
    """
    pages = [_load("issues_page1.json"), _load("issues_page2.json")]
    seen_indices: list[int] = []

    def fetch_page(p: int, ps: int) -> dict[str, Any]:
        seen_indices.append(p)
        assert ps == 2, ps
        return pages[p - 1]

    batches = list(iter_issue_pages(fetch_page, page_size=2))
    assert seen_indices == [1, 2]

    all_keys = [i["key"] for b in batches for i in b]
    # No loss (all 3 present), no duplication.
    assert sorted(all_keys) == [
        "AYx1aaaaaaaaaaaaaaa1",
        "AYx1aaaaaaaaaaaaaaa2",
        "AYx1aaaaaaaaaaaaaaa3",
    ]
    assert len(all_keys) == len(set(all_keys))


@pytest.mark.requirement("REQ-ING-PAG")
def test_pagination_surfaces_10k_cap_rather_than_silently_truncating() -> None:
    """REQ-ING-PAG: when ``paging.total`` exceeds the 10k hard cap, the
    iterator raises rather than silently dropping records; the operator
    partitions by createdAfter/createdBefore per the connector-page
    Quirk.
    """
    first = {"paging": {"total": 10_500}, "issues": [{"key": "x"}]}

    def fetch_page(p: int, ps: int) -> dict[str, Any]:
        return first

    with pytest.raises(RuntimeError, match="10,000"):
        list(iter_issue_pages(fetch_page, page_size=500))


# --- REQ-ING-RL: HTTP 429 backoff -------------------------------------------


@pytest.mark.requirement("REQ-ING-RL")
def test_429_backoff_retries() -> None:
    """REQ-ING-RL: the 429 handler retries with exponential backoff until
    success. Sleep is injected; the test asserts both retry count and the
    delay schedule.
    """
    calls: list[int] = []
    sleeps: list[float] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise RateLimitError(retry_after=0.0)
        return "ok"

    result = call_with_backoff(fn, max_retries=5, base_delay=0.1, sleep=sleeps.append)

    assert result == "ok"
    assert len(calls) == 3  # two failures, one success
    # Exponential: 0.1 * 2**0 = 0.1, 0.1 * 2**1 = 0.2
    assert sleeps == [pytest.approx(0.1), pytest.approx(0.2)]


@pytest.mark.requirement("REQ-ING-RL")
def test_429_respects_server_retry_after_hint() -> None:
    """REQ-ING-RL: when the server supplies a retry-after value larger than
    the exponential schedule, the larger value wins.
    """
    calls: list[int] = []
    sleeps: list[float] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RateLimitError(retry_after=5.0)
        return "ok"

    call_with_backoff(fn, base_delay=0.1, sleep=sleeps.append)

    assert sleeps == [pytest.approx(5.0)]


@pytest.mark.requirement("REQ-ING-RL")
def test_429_gives_up_after_max_retries() -> None:
    """REQ-ING-RL: backoff does not loop forever; after ``max_retries`` the
    error propagates to the caller.
    """

    def fn() -> str:
        raise RateLimitError(retry_after=0.0)

    with pytest.raises(RateLimitError):
        call_with_backoff(fn, max_retries=2, base_delay=0.0, sleep=lambda s: None)


# --- REQ-ING-HWM: resume across two runs ------------------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_updated_after_hwm_resume() -> None:
    """REQ-ING-HWM: on the second run, ``updateDate`` acts as the HWM and
    only new or changed records are returned.
    """
    first_run = _load("issues_page1.json")["issues"]

    # Run 1: no HWM. Everything returns; HWM advances to the max updateDate.
    new_hwm_after_run1 = advance_hwm(first_run, None)
    assert new_hwm_after_run1 == "2026-04-20T11:30:00+0000"

    # Simulate a mid-run change: one record bumped to after the HWM, one
    # unchanged (matches HWM exactly; strict '>' filter excludes it).
    second_run = [
        {"key": "AYx1aaaaaaaaaaaaaaa1", "updateDate": "2026-04-22T10:00:00+0000"},
        {"key": "AYx1aaaaaaaaaaaaaaa2", "updateDate": "2026-04-20T11:30:00+0000"},
    ]
    resumed = filter_since_hwm(second_run, new_hwm_after_run1)

    assert [i["key"] for i in resumed] == ["AYx1aaaaaaaaaaaaaaa1"]
    new_hwm_after_run2 = advance_hwm(resumed, new_hwm_after_run1)
    assert new_hwm_after_run2 == "2026-04-22T10:00:00+0000"


@pytest.mark.requirement("REQ-ING-HWM")
def test_hwm_first_run_returns_everything() -> None:
    """REQ-ING-HWM: first-run semantics — no HWM means every record passes
    the filter.
    """
    batch = _load("issues_page1.json")["issues"]

    resumed = filter_since_hwm(batch, None)

    assert len(resumed) == len(batch)


# --- Contract-surface smoke test --------------------------------------------


def test_ingest_wrapper_has_contract_signature() -> None:
    """``ingest(run_id, state)`` exposes the thesis section 2.4.1 surface."""
    sig = inspect.signature(ingest)
    assert list(sig.parameters) == ["run_id", "state"]


def test_ingest_wrapper_requires_extra_fields() -> None:
    """Missing extras raise ValueError rather than returning a
    half-populated descriptor.
    """
    with pytest.raises(ValueError, match="requires"):
        ingest("run-1", {"source": "sonarqube", "run_id": "run-1", "extra": {}})
