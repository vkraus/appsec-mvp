"""Platform-level repository -> application name-based linker.

The 5-digit business application code (``app_code`` on
``silver.applications``) is the join key. Operators name repositories with
the code embedded as a bounded 5-digit token (e.g. ``acme/payments-12345``)
and this module extracts it, joins to ``silver.applications.app_code``,
and emits ``silver.app_repo_mapping`` rows tagged ``link_source='name_match'``.

The Spark entry point is ``link_by_name``; ``link_by_name_pylist`` is the
pure-Python sibling used by unit tests, mirroring the ``*_to_silver``
pattern in connector transforms.

Layering: this module imports only from ``src.platform.schemas``. It does
not depend on any connector module; the linker job runs as its own
DAB job (``app-repo-link``) downstream of the transforms that populate
``silver.applications`` and ``silver.repositories``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Bounded 5-digit token. Look-around requires non-alphanumeric (or string
# edge) on both sides, so the code must stand alone — rejects shorter
# runs ("1234"), longer runs ("123456"), and digits embedded in
# alphanumerics ("abc12345xyz").
NAME_RE = re.compile(r"(?<![A-Za-z0-9])(\d{5})(?![A-Za-z0-9])")


def extract_code(full_name: str | None) -> str | None:
    """Return the first 5-digit code in ``full_name``, or ``None``.

    Matches a bounded 5-digit token anywhere in the string. First match
    wins per the spec — operators rarely embed multiple codes in one name,
    and silently picking one is preferable to skipping the row entirely.
    """
    if not full_name:
        return None
    m = NAME_RE.search(full_name)
    return m.group(1) if m else None


def link_by_name_pylist(
    applications: list[dict[str, Any]],
    repositories: list[dict[str, Any]],
    *,
    run_ts: datetime,
) -> list[dict[str, Any]]:
    """Pure-Python sibling of ``link_by_name`` for unit tests.

    Builds a multimap from ``app_code`` to ``application_id`` (one code
    can resolve to multiple apps in degenerate CMDB data — see test
    ``...emits_multiple_rows_when_codes_collide``), then emits one
    mapping row per (matched repo, matching app) pair. Rows are tagged
    ``link_source='name_match'`` and ``linked_at=run_ts``.

    Counters are logged at INFO so the production job surfaces match
    rates without polluting WARNING/ERROR streams.
    """
    apps_by_code: dict[str, list[str]] = {}
    for app in applications:
        code = app.get("app_code")
        if code is None:
            continue
        apps_by_code.setdefault(code, []).append(app["application_id"])

    rows: list[dict[str, Any]] = []
    n_no_code = 0
    n_unknown_code = 0
    n_matched = 0

    for repo in repositories:
        code = extract_code(repo.get("full_name"))
        if code is None:
            n_no_code += 1
            continue
        app_ids = apps_by_code.get(code)
        if not app_ids:
            n_unknown_code += 1
            logger.info(
                "app_repo_link: unmatched code %s for repo %s",
                code,
                repo["repository_id"],
            )
            continue
        for application_id in app_ids:
            rows.append(
                {
                    "application_id": application_id,
                    "repository_id": repo["repository_id"],
                    "link_source": "name_match",
                    "linked_at": run_ts,
                }
            )
            n_matched += 1

    logger.info(
        "app_repo_link: matched=%d unknown_code=%d no_code=%d",
        n_matched,
        n_unknown_code,
        n_no_code,
    )
    return rows
