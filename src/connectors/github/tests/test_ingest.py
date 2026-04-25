"""Tests for the PyGithub-backed GitHub connector.

No HTTP is mocked; PyGithub is faked at the object-graph level.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.connectors.github.ingest import (
    fetch_org_repositories,
    fetch_repo_commits,
    fetch_repo_pulls,
    github_client,
)


def _paginated(items):
    """Return a MagicMock that iterates `items` the way PyGithub's PaginatedList does."""
    pl = MagicMock()
    pl.__iter__.return_value = iter(items)
    return pl


def _elem(raw_data: dict):
    """A fake PyGithub element (Repository/Commit/PullRequest) exposing `.raw_data`."""
    e = SimpleNamespace()
    e.raw_data = raw_data
    return e


def test_fetch_org_repositories_yields_raw_data_per_repo():
    repos = [
        _elem({"id": 100, "full_name": "acme/a", "default_branch": "main"}),
        _elem({"id": 101, "full_name": "acme/b", "default_branch": "main"}),
    ]
    org = MagicMock()
    org.get_repos.return_value = _paginated(repos)
    gh = MagicMock()
    gh.get_organization.return_value = org

    result = list(fetch_org_repositories(gh, "acme"))

    assert [r["full_name"] for r in result] == ["acme/a", "acme/b"]
    gh.get_organization.assert_called_once_with("acme")
    org.get_repos.assert_called_once_with()


def test_fetch_repo_commits_passes_since_as_datetime():
    commits = [_elem({"sha": "abc", "commit": {"message": "x"}})]
    repo = MagicMock()
    repo.get_commits.return_value = _paginated(commits)
    gh = MagicMock()
    gh.get_repo.return_value = repo

    result = list(fetch_repo_commits(gh, "acme/a", "2026-04-01T00:00:00Z"))

    assert [c["sha"] for c in result] == ["abc"]
    gh.get_repo.assert_called_once_with("acme/a")
    # `since` must be passed to PyGithub as a datetime, not a string.
    kwargs = repo.get_commits.call_args.kwargs
    assert isinstance(kwargs["since"], datetime)
    assert kwargs["since"] == datetime(2026, 4, 1, tzinfo=UTC)


def test_fetch_repo_pulls_requests_all_states_sorted_by_updated():
    pulls = [
        _elem({"number": 2, "updated_at": "2026-04-20T10:00:00Z"}),
        _elem({"number": 1, "updated_at": "2026-04-19T10:00:00Z"}),
    ]
    repo = MagicMock()
    repo.get_pulls.return_value = _paginated(pulls)
    gh = MagicMock()
    gh.get_repo.return_value = repo

    result = list(fetch_repo_pulls(gh, "acme/a"))

    assert [p["number"] for p in result] == [2, 1]
    repo.get_pulls.assert_called_once_with(state="all", sort="updated", direction="desc")


def test_github_client_returns_github_instance():
    from github import Github

    gh = github_client("test-token")

    assert isinstance(gh, Github)


def test_fetch_repo_commits_rejects_malformed_since():
    repo = MagicMock()
    repo.get_commits.return_value = _paginated([])
    gh = MagicMock()
    gh.get_repo.return_value = repo

    with pytest.raises(ValueError):
        list(fetch_repo_commits(gh, "acme/a", "not-a-timestamp"))


def test_fetch_repo_commits_rejects_naive_since():
    repo = MagicMock()
    repo.get_commits.return_value = _paginated([])
    gh = MagicMock()
    gh.get_repo.return_value = repo

    with pytest.raises(ValueError):
        list(fetch_repo_commits(gh, "acme/a", "2026-04-01"))
