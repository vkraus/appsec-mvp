"""GitLab SCM + platform-security ingestion via the python-gitlab SDK.

Per thesis section 2.4.1 (Source SDK category) and the SCM reference's
ingestion-tooling split: authentication, keyset pagination, rate limiting,
and server-side ``updated_after`` filters are delegated to the SDK client.
This module composes python-gitlab calls against projects, commits, merge
requests, protected branches, and (on Ultimate) vulnerabilities, yielding
raw attribute dicts (``attributes``) for downstream bronze writes.

Finding-path toggle: when ``gitlab_finding_path == "vulnerabilities_api"``
(Ultimate tier) the connector pulls from ``/projects/{id}/vulnerabilities``
directly. For non-Ultimate tiers the operator sets it to ``"artifacts"``
and findings are walked through the jobs-artifacts endpoint instead; the
artifact-walking path is out of scope for this module and belongs in a
separate sibling module when operators select it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from src.platform.contract import BatchDescriptor, ConnectorState

# When the GitLab bronze write is implemented, call
# ``src.platform.bronze_schema.with_envelope`` on the dataframe before
# ``.writeTo`` so projects, commits, merge requests, protected branches,
# and vulnerabilities carry the uniform section 2.2.2 envelope from the
# first write. See OWASP ZAP and Semgrep for the pattern.


def gitlab_client(
    token: str,
    base_url: str = "https://gitlab.com",
    *,
    per_page: int = 100,
    timeout: int = 30,
):
    """Construct a python-gitlab client against ``base_url`` with keyset-friendly defaults.

    The SDK exposes an ``http_backend`` with ``requests``-style retries; callers
    may raise the retry count for long-running group-wide scans. The default
    ``per_page`` is the REST API's maximum (100) to minimize round trips.
    ``base_url`` defaults to the SaaS tenancy; self-managed deployments pass
    their ingress URL here (see connector page § Prerequisites).
    """
    import gitlab  # type: ignore[import-not-found]

    return gitlab.Gitlab(url=base_url, private_token=token, per_page=per_page, timeout=timeout)


def _parse_iso_utc(ts: str) -> datetime:
    """Parse a GitLab ISO-8601 timestamp into a timezone-aware UTC datetime.

    GitLab always emits UTC (connector page § Incremental hook), but the
    trailing ``Z`` form is also accepted defensively.
    """
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"`ts` must be a timezone-aware ISO-8601 timestamp: {ts!r}")
    return dt


def fetch_group_projects(gl, group_path: str) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for each project under ``group_path``.

    Uses ``get_all=True`` to exhaust keyset pagination under the hood. Projects
    are addressable by stable integer ``id`` and mutable ``path_with_namespace``
    (connector page § Quirks). The framework stores ``id`` as ``natural_key``.
    """
    group = gl.groups.get(group_path)
    for project in group.projects.list(get_all=True, include_subgroups=True):
        yield project.attributes


def fetch_project_commits(gl, project_id: int | str, since: str) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for commits in ``project_id`` at or after ``since``.

    ``since`` is an ISO-8601 timestamp; it is validated to be timezone-aware
    before being handed to the SDK as the ``since=`` query parameter.
    """
    since_dt = _parse_iso_utc(since)
    project = gl.projects.get(project_id)
    for commit in project.commits.list(since=since_dt.isoformat(), get_all=True):
        yield commit.attributes


def fetch_project_merge_requests(
    gl, project_id: int | str, updated_after: str | None = None
) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for merge requests in ``project_id``.

    When ``updated_after`` is supplied the server filters by ``updated_at``
    (the documented high-water-mark column); otherwise all merge requests
    are returned. Uses keyset pagination via ``get_all=True``.
    """
    project = gl.projects.get(project_id)
    kwargs: dict[str, Any] = {"state": "all", "order_by": "updated_at", "sort": "desc"}
    if updated_after is not None:
        _parse_iso_utc(updated_after)  # validate early
        kwargs["updated_after"] = updated_after
    for mr in project.mergerequests.list(get_all=True, **kwargs):
        yield mr.attributes


def fetch_project_protected_branches(gl, project_id: int | str) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for each protected branch in ``project_id``.

    Protected branches carry ``allowed_to_push`` / ``allowed_to_merge`` access
    level arrays; the translation to canonical policy vocabulary happens in
    ``transform.py`` per the connector page § Enumerations.
    """
    project = gl.projects.get(project_id)
    for branch in project.protectedbranches.list(get_all=True):
        yield branch.attributes


def fetch_project_vulnerabilities(
    gl, project_id: int | str, updated_after: str | None = None
) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for vulnerabilities in ``project_id`` (Ultimate only).

    The Vulnerabilities API interleaves SAST, Secret Detection, Dependency
    Scanning, DAST, and Container Scanning findings on the same endpoint;
    ``report_type`` is the discriminator consumed by ``transform.py``.

    Requires GitLab Ultimate; on lower tiers operators select the artifact-
    walking path via the ``gitlab_finding_path`` Terraform variable
    (connector page § Quirks).
    """
    project = gl.projects.get(project_id)
    kwargs: dict[str, Any] = {}
    if updated_after is not None:
        _parse_iso_utc(updated_after)
        kwargs["updated_after"] = updated_after
    for vuln in project.vulnerabilities.list(get_all=True, **kwargs):
        yield vuln.attributes


def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper. Dispatches to fetch_group_projects.

    The contract prescribes ``(run_id, state) -> BatchDescriptor``. ``state``
    carries the GitLab token under ``extra["token"]``, the base URL under
    ``extra["base_url"]`` (defaults to SaaS), the target group path under
    ``extra["group"]``, and the Unity Catalog under ``extra["catalog"]``.

    Per-subject fan-out (projects, then commits, then merge requests, then
    protected branches, then vulnerabilities) is intentionally not done here.
    The wrapper reports the project-list batch only. Downstream fetchers are
    invoked by the DAB job as separate tasks.
    """
    extra = state.get("extra") or {}
    token = extra.get("token")
    group = extra.get("group")
    catalog = extra.get("catalog")
    if not token or not group or not catalog:
        raise ValueError(
            "gitlab.ingest requires state['extra']['token'], ['group'], and ['catalog']"
        )
    base_url = extra.get("base_url") or "https://gitlab.com"

    gl = gitlab_client(token, base_url)
    projects = list(fetch_group_projects(gl, group))
    return {
        "run_id": run_id,
        "source": "gitlab",
        "record_count": len(projects),
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{catalog}.bronze_gitlab.projects",
    }
