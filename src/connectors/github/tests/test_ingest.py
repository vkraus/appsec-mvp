"""Tests for the PyGithub-backed GitHub connector.

No HTTP is mocked; PyGithub is faked at the object-graph level. REQ markers
bind framework-contract tests (src/platform/) to the requirement catalog at
mkdocs/docs/platform/reference/catalog.md. Per references/scm.md the
entity-only MVP binds the seven always-applicable REQ-IDs; the three
finding-only REQ-IDs (REQ-TRF-SEV, REQ-TRF-STS, REQ-DEDUP) are out of scope
until GHAS finding ingestion ships.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.github.ingest import (
    fetch_org_repositories,
    fetch_repo_commits,
    fetch_repo_pulls,
    github_client,
    ingest,
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


@pytest.mark.requirement("REQ-ING-PAG")
def test_fetch_org_repositories_yields_raw_data_per_repo():
    """Pagination: PyGithub's PaginatedList drives keyset traversal across
    the org; the fetcher yields every page's items without data loss or
    duplication.
    """
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


@pytest.mark.requirement("REQ-ING-HWM")
def test_fetch_repo_commits_passes_since_as_datetime():
    """HWM resume: the ISO-8601 `since` marker is forwarded to PyGithub as a
    timezone-aware datetime, so the second run fetches only commits newer
    than the persisted high-water mark.
    """
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


@pytest.mark.requirement("REQ-ING-RL")
def test_github_client_configures_retry_policy():
    """Rate-limit handling: PyGithub's `GithubRetry` is installed on the
    client so 403 secondary rate-limit responses (with `Retry-After` /
    `X-RateLimit-Reset`) are retried with backoff rather than propagating
    as errors. The plain urllib3 Retry only covers 429/5xx, which is why
    `GithubRetry` is required.
    """
    from github import GithubRetry

    with patch("src.connectors.github.ingest.Github") as mock_gh:
        github_client("test-token")

    kwargs = mock_gh.call_args.kwargs
    retry = kwargs["retry"]
    assert isinstance(retry, GithubRetry)
    assert retry.total == 5


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_resolves_token_from_state_and_rejects_missing_secret():
    """Auth resolution: the wrapper reads credentials from `state['extra']`
    (the Databricks secret-scope values are injected there by the DAB entry
    script). Missing token/org/catalog raises a ValueError with a clear
    message rather than silently failing downstream.
    """
    # Happy path: token resolved, github_client called with it.
    with patch("src.connectors.github.ingest.github_client") as mock_client, \
         patch("src.connectors.github.ingest.fetch_org_repositories", return_value=iter([])):
        mock_client.return_value = MagicMock()
        descriptor = ingest(
            run_id="run-1",
            state={
                "source": "github",
                "run_id": "run-1",
                "extra": {"token": "s3cret", "org": "acme", "catalog": "appsec_dev"},
            },
        )
    mock_client.assert_called_once_with("s3cret")
    assert descriptor["bronze_table"] == "appsec_dev.bronze_github.repositories"
    assert descriptor["source"] == "github"

    # Sad path: missing token yields a clear ValueError, not a silent failure.
    with pytest.raises(ValueError, match="token"):
        ingest(
            run_id="run-2",
            state={
                "source": "github",
                "run_id": "run-2",
                "extra": {"org": "acme", "catalog": "appsec_dev"},
            },
        )


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
