"""GitLab ingest REQ-bound tests.

The GitLab connector delegates ingestion to the python-gitlab SDK (per the
SCM reference's ingestion-tooling split: SDK for entities where a managed
Lakeflow Connect integration is not present, SDK for findings because the
Vulnerabilities API wants fine-grained pagination control). The framework
contract that the REQs constrain is expressed in ``config.yml`` plus the
canonical helpers in ``src/platform/``; these tests bind the four ingest-side
REQs from the SCM slate to the declarative artefacts that drive the SDK
fetchers.

- REQ-ING-AUTH — auth block references secret-scope keys, never literals
- REQ-ING-PAG  — pagination strategy is keyset with a configurable page size
- REQ-ING-RL   — rate-limit posture is expressed through the job's retry
                  policy on the ingest task
- REQ-ING-HWM  — updated_at is the documented high-water-mark column and
                  survives a resume via the common UpdatedAtHwm store
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from src.connectors.gitlab.ingest import (
    _parse_iso_utc,
    fetch_group_projects,
    fetch_project_commits,
    fetch_project_merge_requests,
    fetch_project_protected_branches,
    fetch_project_vulnerabilities,
    ingest,
)
from src.platform.config import ConnectorConfig, load_yaml
from src.platform.hwm import HwmStore, UpdatedAtHwm

_REPO_ROOT = Path(__file__).parents[4]
_CONFIG_PATH = _REPO_ROOT / "src" / "connectors" / "gitlab" / "config.yml"
_JOB_PATH = _REPO_ROOT / "src" / "connectors" / "gitlab" / "resources" / "job.yml"
_FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers that fake python-gitlab's manager objects. The SDK exposes paginated
# resources via ``manager.list(get_all=True, ...)`` returning objects whose
# ``attributes`` dict matches the JSON API response.
# ---------------------------------------------------------------------------


def _elem(attrs: dict):
    """A fake python-gitlab object exposing ``.attributes``."""
    return SimpleNamespace(attributes=attrs)


def _manager(items: list[dict]):
    """A fake python-gitlab manager that records ``list`` kwargs."""
    mgr = MagicMock()
    mgr.list.return_value = [_elem(it) for it in items]
    return mgr


@pytest.fixture(scope="module")
def gitlab_config() -> ConnectorConfig:
    return load_yaml(ConnectorConfig, _CONFIG_PATH)


# ---------------------------------------------------------------------------
# REQ-bound tests
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-AUTH")
def test_auth_secret_resolution(gitlab_config: ConnectorConfig) -> None:
    """Auth keys reference secret-scope names, never plaintext credentials.

    GitLab uses bearer authentication with a personal / project / group
    access token (connector page § API surface). The config must carry only
    ``*_secret`` pointers so deploys resolve the real token from the
    Databricks secret scope at runtime.
    """
    assert gitlab_config.auth.type == "bearer"
    assert gitlab_config.auth.token_secret, "token_secret must be set"
    key = gitlab_config.auth.token_secret
    # A plaintext token would typically contain punctuation/length that a
    # secret-scope key doesn't. These asserts keep obvious leakage out.
    assert " " not in key
    assert "@" not in key
    assert ":" not in key
    assert len(key) < 64


@pytest.mark.requirement("REQ-ING-PAG")
def test_keyset_pagination_two_pages(gitlab_config: ConnectorConfig) -> None:
    """GitLab uses keyset pagination; the SDK fetchers exhaust multi-page results.

    Simulates a two-page fetch by returning concatenated items from a single
    ``list(get_all=True)`` call (which is how python-gitlab surfaces
    keyset-paginated endpoints — the SDK resolves ``Link: rel="next"``
    internally). Two distinct pages' worth of projects round-trip without
    data loss or duplication.
    """
    assert gitlab_config.pagination.strategy == "keyset"
    page_size = gitlab_config.pagination.page_size
    assert page_size == 100, "per_page must default to REST API max (100)"

    page_one = json.loads((_FIX / "projects.json").read_text())
    page_two = [
        {
            "id": 202,
            "path_with_namespace": "acme/billing-ops",
            "default_branch": "main",
            "visibility": "private",
            "archived": False,
            "last_activity_at": "2026-04-20T11:00:00.000Z",
            "created_at": "2024-05-01T09:00:00.000Z",
            "updated_at": "2026-04-20T11:00:00.000Z",
        }
    ]
    mgr = _manager(page_one + page_two)
    group = MagicMock()
    group.projects = mgr
    gl = MagicMock()
    gl.groups.get.return_value = group

    result = list(fetch_group_projects(gl, "acme"))

    ids = [r["id"] for r in result]
    assert ids == [200, 201, 202], "no data loss and no duplicates across keyset pages"
    # Keyset semantics are captured by ``get_all=True`` (SDK follows next-cursor)
    kwargs = mgr.list.call_args.kwargs
    assert kwargs.get("get_all") is True


@pytest.mark.requirement("REQ-ING-RL")
def test_429_backoff_retries() -> None:
    """Ingest task carries a retry policy so HTTP 429s from GitLab
    are absorbed by the Lakeflow job's built-in retry loop.

    GitLab.com enforces 2000 req/min/user with sub-limits on search and raw
    blob endpoints (connector page § Pagination and rate limits); self-managed
    instances expose configurable limits. The job fragment's ingest task must
    declare ``max_retries`` >= 1 and a non-zero ``min_retry_interval_millis``
    so the framework retries with a bounded delay rather than failing the run
    on a transient quota hit.
    """
    with open(_JOB_PATH) as fh:
        job = yaml.safe_load(fh)
    tasks = job["resources"]["jobs"]["gitlab-connector"]["tasks"]
    ingest_task = next(t for t in tasks if t["task_key"] == "ingest")
    assert ingest_task["max_retries"] >= 1
    assert ingest_task["min_retry_interval_millis"] >= 1000
    assert ingest_task.get("retry_on_timeout") is True


@pytest.mark.requirement("REQ-ING-HWM")
def test_updated_at_hwm_resume(gitlab_config: ConnectorConfig, tmp_path) -> None:
    """HWM column is updated_at; UpdatedAtHwm round-trips it across runs.

    GitLab's ``updated_at`` is always UTC (connector page § Incremental hook),
    so no time-zone normalisation is needed. The first ingest writes the max
    observed ``updated_at``; the next run reads it back and supplies it as
    the server-side ``updated_after`` filter. Round-tripping a timezone-aware
    timestamp through the shared ``UpdatedAtHwm`` is the framework-level
    contract for this behaviour.
    """
    assert gitlab_config.hwm.strategy == "updated_at"
    assert gitlab_config.hwm.column == "updated_at"

    store = HwmStore(tmp_path / "hwm.json")
    hwm = UpdatedAtHwm(key="gitlab::projects", store=store)

    # First run: epoch sentinel
    assert hwm.read() == datetime(1970, 1, 1, tzinfo=UTC)

    # End of run 1: persist the max observed updated_at from the projects fixture
    observed_max = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    hwm.write(observed_max)

    # Run 2 resumes from the persisted value
    resumed = hwm.read()
    assert resumed == observed_max
    assert resumed.tzinfo is not None, "HWM must survive as timezone-aware"

    # The resumed timestamp is ingestable as the ``updated_after`` filter on
    # the merge-requests fetcher without validation error.
    _parse_iso_utc(resumed.isoformat())


# ---------------------------------------------------------------------------
# Fetcher-shape tests: confirm the SDK calls and surface matches the contract.
# Not REQ-bound but defend the ingest wrapper against SDK-signature drift.
# ---------------------------------------------------------------------------


def test_fetch_project_merge_requests_passes_updated_after() -> None:
    mrs = json.loads((_FIX / "merge_requests.json").read_text())
    mgr = _manager(mrs)
    project = MagicMock()
    project.mergerequests = mgr
    gl = MagicMock()
    gl.projects.get.return_value = project

    result = list(fetch_project_merge_requests(gl, 200, "2026-04-18T00:00:00+00:00"))
    assert [r["iid"] for r in result] == [17, 18]
    kwargs = mgr.list.call_args.kwargs
    assert kwargs["updated_after"] == "2026-04-18T00:00:00+00:00"
    assert kwargs["state"] == "all"
    assert kwargs["order_by"] == "updated_at"


def test_fetch_project_merge_requests_rejects_naive_updated_after() -> None:
    gl = MagicMock()
    with pytest.raises(ValueError):
        list(fetch_project_merge_requests(gl, 200, "2026-04-18"))


def test_fetch_project_protected_branches_iterates_all() -> None:
    branches = json.loads((_FIX / "protected_branches.json").read_text())
    mgr = _manager(branches)
    project = MagicMock()
    project.protectedbranches = mgr
    gl = MagicMock()
    gl.projects.get.return_value = project

    result = list(fetch_project_protected_branches(gl, 200))
    assert [b["name"] for b in result] == ["main", "release/*"]


def test_fetch_project_vulnerabilities_without_filter() -> None:
    vulns = json.loads((_FIX / "vulnerabilities.json").read_text())
    mgr = _manager(vulns)
    project = MagicMock()
    project.vulnerabilities = mgr
    gl = MagicMock()
    gl.projects.get.return_value = project

    result = list(fetch_project_vulnerabilities(gl, 200))
    assert len(result) == 5
    # No updated_after filter is supplied when state has no HWM yet.
    kwargs = mgr.list.call_args.kwargs
    assert "updated_after" not in kwargs


def test_fetch_project_commits_parses_iso_since() -> None:
    mgr = _manager([{"id": "deadbeefcafebabe", "short_id": "deadbeef"}])
    project = MagicMock()
    project.commits = mgr
    gl = MagicMock()
    gl.projects.get.return_value = project

    result = list(fetch_project_commits(gl, 200, "2026-04-01T00:00:00Z"))
    assert [c["id"] for c in result] == ["deadbeefcafebabe"]
    kwargs = mgr.list.call_args.kwargs
    assert kwargs["since"].startswith("2026-04-01T00:00:00")


def test_ingest_wrapper_requires_state_extras() -> None:
    with pytest.raises(ValueError):
        ingest("run-1", {"source": "gitlab", "run_id": "run-1"})


@pytest.mark.skip(reason="pending live fixtures (B follow-up)")
@pytest.mark.requirement("REQ-ING-AUTH")
def test_expired_token_produces_clear_error() -> None:
    """Requires a real python-gitlab client and a revoked PAT to exercise the
    401/403 path end-to-end. Synthesized fixtures cannot distinguish
    SDK-level auth-error wrapping from network errors; validate-implementation
    covers this on a live GitLab test tenancy.
    """
