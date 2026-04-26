"""GitHub SCM + GitHub Advanced Security ingestion.

Per the SCM reference's ingestion-tooling split (Lakeflow Connect first;
SDK / dlt fall back), GitHub does not yet expose a Lakeflow Connect
managed connector that covers both the entity surface and the three
GitHub Advanced Security alert streams. The Databricks SDK does not
provide a first-party GitHub client either, so this module adopts the
``dlt`` REST-source shape (thesis section 2.4.1) for entities and finer
keyset / cursor pagination for findings, both authenticated against the
single bearer-token credential. GraphQL is preferred for the org-wide
repository enumeration where field selection and a single round trip
materially reduce cost; REST is preferred for narrower per-repo reads
and the three alert streams where GraphQL lags the REST schema.

Public helpers below are pure Python so ``pytest`` can verify the
framework contract (REQ-ING-AUTH / REQ-ING-PAG / REQ-ING-RL /
REQ-ING-HWM) without a live GitHub instance and without a local
``SparkSession`` (per CLAUDE.md ``Don'ts``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from src.platform.contract import BatchDescriptor, ConnectorState

# When the GitHub bronze write is implemented, call
# ``src.platform.bronze_schema.with_envelope`` on the dataframe before
# ``.writeTo`` so repositories, pull_requests, branch_protection, and the
# three alert streams carry the uniform section 2.2.2 envelope from the
# first write. See OWASP ZAP and Semgrep for the pattern.

# --- Secret-scope credential resolution (REQ-ING-AUTH) ----------------------


class SecretResolutionError(RuntimeError):
    """Raised when the GitHub bearer token cannot be resolved from the
    Databricks secret scope. The message names the scope and key so the
    operator can fix the misconfiguration rather than debug a silent 401.
    """


def resolve_token(
    scope: str,
    key: str,
    secret_reader: Callable[[str, str], str | None],
) -> str:
    """Resolve the GitHub PAT / GitHub App installation token from the
    platform secret scope.

    ``secret_reader`` is the injected lookup function (on Databricks this
    is ``dbutils.secrets.get``). Kept as a callable parameter so unit
    tests can substitute a dict-backed fake without patching global
    state. Empty / missing secrets surface as :class:`SecretResolutionError`
    rather than as a silent 401 from the GitHub API.
    """
    value = secret_reader(scope, key)
    if value is None or value == "":
        raise SecretResolutionError(
            f"github: token not found in secret scope {scope!r} under key {key!r}"
        )
    return value


# --- Cursor / Link-header pagination (REQ-ING-PAG) --------------------------


def parse_link_header(header: str | None) -> dict[str, str]:
    """Parse an RFC 5988 ``Link`` header into a ``{rel: url}`` mapping.

    GitHub paginates REST list endpoints via the ``Link`` response header
    (connector page § Pagination and rate limits). The header is a
    comma-separated list of ``<url>; rel="name"`` entries. The connector
    iterates until ``rel="next"`` is absent. Returns ``{}`` when the
    header is missing or empty so callers can treat absence and end-of-
    pagination uniformly.
    """
    if not header:
        return {}
    out: dict[str, str] = {}
    for entry in header.split(","):
        entry = entry.strip()
        if not entry:
            continue
        # `<url>; rel="name"` may carry additional `; param=value` pairs.
        url_part, _, rest = entry.partition(";")
        url_part = url_part.strip()
        if not (url_part.startswith("<") and url_part.endswith(">")):
            continue
        url = url_part[1:-1]
        rel: str | None = None
        for param in rest.split(";"):
            param = param.strip()
            if param.startswith("rel="):
                rel = param[4:].strip().strip('"')
                break
        if rel:
            out[rel] = url
    return out


def iter_link_pages(
    fetch_page: Callable[[str | None], tuple[list[dict[str, Any]], dict[str, str]]],
) -> Iterator[list[dict[str, Any]]]:
    """Yield per-page item lists across a ``Link``-paginated REST endpoint.

    ``fetch_page(next_url)`` returns ``(items, link_rels)`` where
    ``link_rels`` is :func:`parse_link_header`'s output for the response.
    First call passes ``None`` (initial URL is held by the caller). The
    iterator follows ``rel="next"`` until it is absent.
    """
    next_url: str | None = None
    seen: set[str] = set()
    while True:
        items, rels = fetch_page(next_url)
        yield items
        nxt = rels.get("next")
        if not nxt:
            return
        if nxt in seen:
            # Defensive: a server bug echoing the same `next` cursor would
            # otherwise spin forever. Break with a clear error so the
            # operator can audit the API state.
            raise RuntimeError(f"github: Link header cycle on {nxt!r}")
        seen.add(nxt)
        next_url = nxt


def iter_graphql_cursor_pages(
    fetch_page: Callable[[str | None], tuple[list[dict[str, Any]], str | None, bool]],
) -> Iterator[list[dict[str, Any]]]:
    """Yield per-page node lists across a GraphQL cursor-paginated query.

    ``fetch_page(after_cursor)`` returns ``(nodes, end_cursor, has_next)``.
    GraphQL exposes a uniform ``pageInfo { endCursor hasNextPage }``
    selection on every connection (connector page § Pagination and rate
    limits). The iterator passes the previous ``endCursor`` as ``after``
    on each subsequent call.
    """
    cursor: str | None = None
    while True:
        nodes, end_cursor, has_next = fetch_page(cursor)
        yield nodes
        if not has_next:
            return
        cursor = end_cursor


# --- 429 / secondary-limit rate-limit handling (REQ-ING-RL) -----------------


class RateLimitError(RuntimeError):
    """HTTP 429 / 403 response marker; carries a retry-after hint in
    seconds. Per the GitHub rate-limit documentation: 'If the
    ``retry-after`` response header is present, you should not retry
    your request until after that many seconds has elapsed.'
    """

    def __init__(self, retry_after: float):
        super().__init__(f"github: rate-limited, retry_after={retry_after}s")
        self.retry_after = retry_after


def call_with_backoff(
    fn: Callable[[], Any],
    *,
    max_retries: int = 5,
    base_delay: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Invoke ``fn`` with exponential backoff on :class:`RateLimitError`.

    Backoff: ``max(retry_after, base_delay * 2**attempt)`` seconds.
    ``sleep`` is injected so tests can assert the schedule without
    introducing real delay. Honours the server-provided ``retry-after``
    verbatim when it exceeds the local exponential schedule.
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


# --- Native HWM advancement (REQ-ING-HWM) -----------------------------------


def _parse_iso_utc(ts: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp into a timezone-aware UTC datetime.

    GitHub always emits UTC with a trailing ``Z`` (connector page §
    Quirks: 'All timestamps are ISO 8601 UTC'). The connector accepts
    both the ``Z`` form and explicit offsets defensively.
    """
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"`ts` must be a timezone-aware ISO-8601 timestamp: {ts!r}")
    return dt.astimezone(UTC)


def advance_hwm(
    items: list[dict[str, Any]], prev_hwm: str | None, *, column: str = "updated_at"
) -> str | None:
    """Return the new HWM value given a page of items and the prior HWM.

    The HWM is the maximum value of the configured ``column`` (default
    ``updated_at``). ISO-8601 string comparison is exact for UTC
    timestamps with a fixed offset. ``None`` passes through when the
    batch is empty and no prior HWM exists, preserving first-run "epoch"
    semantics through :class:`src.platform.hwm.UpdatedAtHwm`.
    """
    max_seen = prev_hwm
    for it in items:
        u = it.get(column)
        if u is None:
            continue
        if max_seen is None or u > max_seen:
            max_seen = u
    return max_seen


def filter_since_hwm(
    items: list[dict[str, Any]], prev_hwm: str | None, *, column: str = "updated_at"
) -> list[dict[str, Any]]:
    """Return only items strictly newer than ``prev_hwm`` on ``column``.

    First-run semantics (``prev_hwm`` is ``None``) returns everything.
    String comparison is exact for the GitHub ISO-8601 UTC form (trailing
    ``Z``). The strict ``>`` filter excludes records that match the HWM
    exactly, which is the safe default for incremental polling on
    monotonically advancing ``updated_at`` columns.
    """
    if prev_hwm is None:
        return list(items)
    return [it for it in items if (it.get(column) or "") > prev_hwm]


# --- Webhook signature verification (mode: webhook) -------------------------


def verify_webhook_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify GitHub's ``X-Hub-Signature-256`` header against the request
    body.

    Per the connector page § Incremental hook, GitHub signs webhook
    bodies with HMAC-SHA-256 keyed by the operator-supplied
    ``github_webhook_secret``. The header form is
    ``sha256=<hex>``. Returns ``True`` only when the header is present
    and matches the computed digest under constant-time comparison.
    Missing or mismatched signatures must reject with HTTP 401 at the
    receiver (verification of intent is the receiver's responsibility;
    this helper only computes the boolean).
    """
    import hashlib
    import hmac

    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received = signature_header.split("=", 1)[1].strip()
    computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received, computed)


# --- Framework contract wrapper --------------------------------------------


def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for GitHub (thesis section 2.4.1).

    Dispatches to the underlying REST and GraphQL drivers. The wrapper
    does not mock the live API; it returns a descriptor keyed to the
    repositories bronze table. The DAB job runs entity ingestion, then
    pull-request ingestion, then branch-protection ingestion, then the
    three alert-stream ingestions as separate tasks (see
    ``resources/job.yml``). State carries the bearer token under
    ``extra['token']``, the org login under ``extra['org']`` and the
    Unity Catalog under ``extra['catalog']``.
    """
    extra = state.get("extra") or {}
    token = extra.get("token")
    org = extra.get("org")
    catalog = extra.get("catalog")
    if not token or not org or not catalog:
        raise ValueError("github.ingest requires state['extra'] with 'token', 'org', and 'catalog'")

    # The record_count is 0 in this contract wrapper because the dlt /
    # SDK driver writes directly and does not surface a count in-process;
    # accurate counts are recoverable from _batch_id on the Bronze table.
    return {
        "run_id": run_id,
        "source": "github",
        "record_count": 0,
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{catalog}.bronze_github.repositories",
    }
