"""SonarQube bronze ingest.

Server-based SAST source. Paginated REST pulls against the SonarQube Web API
at ``/api/issues/search`` and ``/api/hotspots/search``, with native
``updateDate`` high-water mark. Rule metadata (``/api/rules/search``) and
project inventory (``/api/projects/search``) are pulled as side tables.

Per ``references/sast.md`` (generate-connector category reference), the
ingestion-tooling preference for server-based SAST is
Lakeflow Connect -> Databricks SDK -> dlt. The canonical SonarQube Web API
is a paginated REST surface with a server-side ``createdAfter`` filter and a
1-indexed ``p``/``ps`` pagination model. The SDK has no first-party client
for SonarQube, and Lakeflow Connect does not ship a SonarQube ingestion
definition; this module accordingly adopts the ``dlt`` REST-source shape
(thesis section 2.4.1), honouring the framework contract at
``src.platform.contract``.

The public helpers below are pure Python so ``pytest`` can verify the
framework contract (REQ-ING-* / REQ-TRF-* / REQ-DQ / REQ-DEDUP) without a
live SonarQube instance and without a local ``SparkSession`` (per
CLAUDE.md ``Don'ts``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

from src.platform.contract import BatchDescriptor, ConnectorState

# --- Secret-scope credential resolution (REQ-ING-AUTH) ---------------------


class SecretResolutionError(RuntimeError):
    """Raised when the SonarQube API token cannot be resolved from the
    Databricks secret scope. The message names the scope and key so the
    operator can fix the misconfiguration rather than debug a silent 401.
    """


def resolve_token(
    scope: str,
    key: str,
    secret_reader: Callable[[str, str], str | None],
) -> str:
    """Resolve the SonarQube API token from the platform secret scope.

    ``secret_reader`` is the injected lookup function (on Databricks this is
    ``dbutils.secrets.get``). Kept as a callable parameter so unit tests can
    substitute a dict-backed fake without patching global state.
    """
    value = secret_reader(scope, key)
    if value is None or value == "":
        raise SecretResolutionError(
            f"sonarqube: token not found in secret scope {scope!r} under key {key!r}"
        )
    return value


# --- Paginated REST traversal (REQ-ING-PAG) --------------------------------


def iter_issue_pages(
    fetch_page: Callable[[int, int], dict[str, Any]],
    *,
    page_size: int = 500,
) -> Iterator[list[dict[str, Any]]]:
    """Yield issue lists across all pages returned by
    ``/api/issues/search``, respecting the 1-indexed ``p``/``ps`` model
    (see sonarqube.md, section "Pagination and rate limits").

    Completion is driven by ``paging.total`` on the first page, which is
    authoritative. Ten-thousand-record cap handling (date-window partitioning)
    is delegated to the caller per the Quirk documented on the connector
    page; this iterator does not silently paper over that cap.
    """
    first = fetch_page(1, page_size)
    total = int(first.get("paging", {}).get("total", 0))
    issues = first.get("issues") or []
    yield issues
    if total <= page_size:
        return
    if total > 10_000:
        # Cap awareness: surface the situation via a RuntimeError so the
        # operator partitions by creationDate window (see Quirk on page).
        raise RuntimeError(
            f"sonarqube: /api/issues/search total={total} exceeds the 10,000 "
            "cap; partition the query by createdAfter/createdBefore"
        )
    pages_remaining = -(-total // page_size) - 1  # ceil div, minus first
    for idx in range(2, 2 + pages_remaining):
        page = fetch_page(idx, page_size)
        yield page.get("issues") or []


# --- 429 rate-limit handling (REQ-ING-RL) ----------------------------------


class RateLimitError(RuntimeError):
    """HTTP 429 response marker; carries a retry-after hint in seconds."""

    def __init__(self, retry_after: float):
        super().__init__(f"sonarqube: HTTP 429, retry_after={retry_after}s")
        self.retry_after = retry_after


def call_with_backoff(
    fn: Callable[[], Any],
    *,
    max_retries: int = 5,
    base_delay: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Invoke ``fn`` with exponential backoff on ``RateLimitError``.

    Backoff: ``base_delay * 2**attempt`` seconds (plus any server-provided
    ``retry_after`` hint). ``sleep`` is injected so tests can assert the
    retry schedule without introducing real delay.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except RateLimitError as rl:
            if attempt >= max_retries:
                raise
            delay = max(rl.retry_after, base_delay * (2**attempt))
            sleep(delay)
            attempt += 1


# --- Native HWM advancement (REQ-ING-HWM) ----------------------------------


def advance_hwm(issues: list[dict[str, Any]], prev_hwm: str | None) -> str | None:
    """Return the new HWM value given a page of issues and the prior HWM.

    The HWM is the maximum ``updateDate`` seen so far, as an ISO-8601 string.
    ``None`` passes through when the batch is empty and no prior HWM exists,
    so the first run's "epoch" semantics are preserved (see
    src/platform/hwm.UpdatedAtHwm).
    """
    max_seen = prev_hwm
    for i in issues:
        u = i.get("updateDate")
        if u is None:
            continue
        if max_seen is None or u > max_seen:
            max_seen = u
    return max_seen


def filter_since_hwm(
    issues: list[dict[str, Any]], prev_hwm: str | None
) -> list[dict[str, Any]]:
    """Return only issues strictly newer than ``prev_hwm``. ``None``
    (first run) returns everything. String comparison is exact for UTC
    ISO-8601 timestamps with a fixed offset.
    """
    if prev_hwm is None:
        return list(issues)
    return [i for i in issues if (i.get("updateDate") or "") > prev_hwm]


# --- Framework contract wrapper --------------------------------------------


def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for SonarQube (thesis section 2.4.1).

    The wrapper does not mock the live API; it returns a descriptor keyed
    to the ``/api/issues/search`` bronze table. The underlying REST driver
    (``dlt`` REST source on the DAB job cluster) reads ``extra['token']``
    and ``extra['base_url']`` off the ConnectorState and streams rows into
    the Bronze Delta table. State is advanced via :func:`advance_hwm` and
    persisted by the DAB entry script.
    """
    extra = state.get("extra") or {}
    token = extra.get("token")
    base_url = extra.get("base_url")
    catalog = extra.get("catalog")
    if not token or not base_url or not catalog:
        raise ValueError(
            "sonarqube.ingest requires state['extra'] with "
            "'token', 'base_url', and 'catalog'"
        )

    # The record_count is 0 in this contract wrapper because the dlt REST
    # source writes directly and does not surface a count in-process;
    # accurate counts are recoverable from _batch_id on the Bronze table.
    return {
        "run_id": run_id,
        "source": "sonarqube",
        "record_count": 0,
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{catalog}.bronze_sonarqube.issues",
    }
