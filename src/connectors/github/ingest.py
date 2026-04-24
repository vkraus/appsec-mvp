"""GitHub SCM ingestion via the PyGithub SDK.

Per thesis §2.4.1 (Source SDK category): auth, rate-limiting, and pagination
are delegated to the client library. This module composes PyGithub calls
against org repositories, repo commits, and repo pull requests, yielding
raw JSON (`raw_data`) for downstream bronze writes.

Platform-integrated security findings (Advanced Security, Dependabot, secret
scanning) are out of scope for the MVP.
"""

from collections.abc import Iterator
from datetime import datetime

from github import Auth, Github, GithubRetry

from src.common.contract import BatchDescriptor, ConnectorState

# When the GitHub bronze write is implemented, call
# ``src.common.bronze_schema.with_envelope`` on the dataframe before
# ``.writeTo`` so repositories, commits, and pulls carry the uniform
# section 2.2.2 envelope from the first write. See OWASP ZAP and
# Semgrep for the pattern.


def github_client(token: str) -> Github:
    """Construct a PyGithub client with GitHub-aware retry.

    Uses ``GithubRetry`` (PyGithub's own subclass) instead of a plain
    ``urllib3`` ``Retry`` so GitHub's 403 secondary rate-limit responses
    (with ``Retry-After`` / ``X-RateLimit-Reset`` headers) are retried
    correctly, not just the 429/5xx responses that ``urllib3`` handles
    out of the box.
    """
    return Github(auth=Auth.Token(token), retry=GithubRetry(total=5))


def fetch_org_repositories(gh: Github, org: str) -> Iterator[dict]:
    """Yield raw_data for each repository in `org`."""
    for repo in gh.get_organization(org).get_repos():
        yield repo.raw_data


def fetch_repo_commits(gh: Github, repo: str, since: str) -> Iterator[dict]:
    """Yield raw_data for each commit in `repo` at or after `since`.

    `since` is an ISO-8601 timestamp (e.g. ``2026-04-01T00:00:00Z``); it is
    parsed into a timezone-aware `datetime` before being passed to PyGithub.
    """
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    if since_dt.tzinfo is None:
        raise ValueError(f"`since` must be a timezone-aware ISO-8601 timestamp: {since!r}")
    for commit in gh.get_repo(repo).get_commits(since=since_dt):
        yield commit.raw_data


def fetch_repo_pulls(gh: Github, repo: str) -> Iterator[dict]:
    """Yield raw_data for all pull requests in `repo`, newest-updated first.

    `get_pulls` has no server-side `since` filter; consumers that want
    incremental ingestion iterate until `updated_at` falls below their HWM
    and break. That wiring lives outside this module.
    """
    pulls = gh.get_repo(repo).get_pulls(state="all", sort="updated", direction="desc")
    for pr in pulls:
        yield pr.raw_data


def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper. Dispatches to fetch_org_repositories.

    The contract prescribes ``(run_id, state) -> BatchDescriptor``. State carries
    the org name under ``extra["org"]``, the GitHub token under ``extra["token"]``,
    and the target Unity Catalog under ``extra["catalog"]``. The catalog is
    populated by the DAB entry script from the ``target_catalog`` job parameter
    (resolved to ``${var.catalog}`` at deploy time per thesis section 2.3.2).
    The HWM value is the ISO-8601 timestamp of the last successful run and is
    forwarded to fetch_repo_commits as ``since``.

    Per-subject fan-out (repositories, then commits, then pulls) is intentionally
    not done here. The wrapper reports the repository-list batch only. The
    downstream fetchers are invoked by the DAB job as separate tasks.
    """
    extra = state.get("extra") or {}
    token = extra.get("token")
    org = extra.get("org")
    catalog = extra.get("catalog")
    if not token or not org or not catalog:
        raise ValueError(
            "github.ingest requires state['extra']['token'], ['org'], and ['catalog']"
        )

    gh = github_client(token)
    repos = list(fetch_org_repositories(gh, org))
    return {
        "run_id": run_id,
        "source": "github",
        "record_count": len(repos),
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{catalog}.bronze_github.repositories",
    }
