"""GitHub ingest-side framework-contract tests.

Binds REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL, REQ-ING-HWM from the
requirement catalog (mkdocs/docs/platform/reference/catalog.md). All
tests are pure-Python; no live GitHub instance and no local Spark
session.

The GitHub connector spans REST and GraphQL surfaces under a single
bearer-token credential. The framework contract that the REQs constrain
is expressed in ``config.yml`` plus the canonical helpers in
``src/platform/``; these tests bind the four ingest-side REQs from the
SCM slate to the declarative artefacts and the per-surface fetchers.

- REQ-ING-AUTH — auth block references secret-scope keys, never literals
- REQ-ING-PAG  — REST Link-header and GraphQL cursor pagination both
                 traverse multi-page responses without loss or duplication
- REQ-ING-RL   — rate-limit posture absorbs HTTP 429/403 with bounded
                 backoff and respects the server-side ``retry-after``
                 hint per the GitHub rate-limit documentation
- REQ-ING-HWM  — ``updated_at`` is the documented high-water-mark column
                 and survives a resume via the common UpdatedAtHwm store
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.connectors.github.ingest import (
    RateLimitError,
    SecretResolutionError,
    _parse_iso_utc,
    advance_hwm,
    call_with_backoff,
    filter_since_hwm,
    ingest,
    iter_graphql_cursor_pages,
    iter_link_pages,
    parse_link_header,
    resolve_token,
    verify_webhook_signature,
)
from src.platform.config import ConnectorConfig, load_yaml
from src.platform.hwm import HwmStore, UpdatedAtHwm

_REPO_ROOT = Path(__file__).parents[4]
_CONFIG_PATH = _REPO_ROOT / "src" / "connectors" / "github" / "config.yml"
_JOB_PATH = _REPO_ROOT / "src" / "connectors" / "github" / "resources" / "job.yml"
_FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def github_config() -> ConnectorConfig:
    return load_yaml(ConnectorConfig, _CONFIG_PATH)


# ---------------------------------------------------------------------------
# REQ-ING-AUTH: secret-scope credential resolution
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-AUTH")
def test_auth_secret_references_only(github_config: ConnectorConfig) -> None:
    """REQ-ING-AUTH: ``config.yml``'s auth block carries only secret-scope
    key names, never plaintext credentials.

    GitHub uses bearer authentication with a fine-grained PAT, classic
    PAT, OAuth user token, or GitHub App installation token (connector
    page § API surface). The config must surface only ``*_secret``
    pointers so deploys resolve the real token from the Databricks
    secret scope at runtime.
    """
    assert github_config.auth.type == "bearer"
    assert github_config.auth.token_secret, "token_secret must be set"
    key = github_config.auth.token_secret
    # A plaintext bearer token would carry GitHub's ``ghp_`` / ``github_pat_``
    # prefix and be much longer than a secret-scope key name.
    assert " " not in key
    assert "@" not in key
    assert ":" not in key
    assert not key.startswith("ghp_")
    assert not key.startswith("github_pat_")
    assert len(key) < 64


@pytest.mark.requirement("REQ-ING-AUTH")
def test_token_resolution_from_secret_scope() -> None:
    """REQ-ING-AUTH: the connector reads the GitHub token from the
    configured secret scope and key; a missing value raises
    :class:`SecretResolutionError` rather than silently returning None
    (which would surface as a confusing 401 several layers downstream).
    """
    reader = lambda scope, key: {  # noqa: E731
        ("mvp-connectors", "github_token"): "ghp_synthesized-test-token",
    }.get((scope, key))

    tok = resolve_token("mvp-connectors", "github_token", reader)
    assert tok == "ghp_synthesized-test-token"

    with pytest.raises(SecretResolutionError, match="mvp-connectors"):
        resolve_token("mvp-connectors", "github_token", lambda s, k: None)


# ---------------------------------------------------------------------------
# REQ-ING-PAG: REST Link-header and GraphQL cursor pagination
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-PAG")
def test_link_header_two_pages_no_loss_no_duplicates(
    github_config: ConnectorConfig,
) -> None:
    """REQ-ING-PAG: the REST Link-header iterator traverses two pages
    without loss or duplication.

    GitHub paginates list endpoints via the ``Link`` response header
    (connector page § Pagination and rate limits). The iterator follows
    ``rel="next"`` until the header omits it. Per-page size is the
    documented maximum of 100 to minimise round trips.
    """
    assert github_config.pagination.strategy == "cursor"
    assert github_config.pagination.page_size == 100, "per_page must default to 100"

    page_one_alerts = json.loads((_FIX / "code_scanning_alerts.json").read_text())[:2]
    page_two_alerts = json.loads((_FIX / "code_scanning_alerts.json").read_text())[2:]

    next_url_p1 = "https://api.github.com/repos/acme/payments-api/code-scanning/alerts?page=2"
    pages = [
        (page_one_alerts, {"next": next_url_p1}),
        (page_two_alerts, {}),  # no rel=next -> end of iteration
    ]
    seen_urls: list[str | None] = []

    def fetch_page(next_url: str | None):
        seen_urls.append(next_url)
        return pages.pop(0)

    batches = list(iter_link_pages(fetch_page))
    assert seen_urls == [None, next_url_p1]

    all_numbers = [a["number"] for b in batches for a in b]
    # No loss (all 3 alerts present), no duplication.
    assert sorted(all_numbers) == [101, 102, 103]
    assert len(all_numbers) == len(set(all_numbers))


@pytest.mark.requirement("REQ-ING-PAG")
def test_link_header_parser_extracts_rel_next() -> None:
    """REQ-ING-PAG: the Link parser handles the canonical multi-rel
    header form ``<url>; rel="next", <url>; rel="last"`` per RFC 5988.
    Absent headers return ``{}`` so callers treat absence and
    end-of-pagination uniformly.
    """
    header = (
        '<https://api.github.com/repositories/12345/issues?page=2>; rel="next", '
        '<https://api.github.com/repositories/12345/issues?page=10>; rel="last"'
    )
    parsed = parse_link_header(header)
    assert parsed["next"] == "https://api.github.com/repositories/12345/issues?page=2"
    assert parsed["last"] == "https://api.github.com/repositories/12345/issues?page=10"

    assert parse_link_header(None) == {}
    assert parse_link_header("") == {}


@pytest.mark.requirement("REQ-ING-PAG")
def test_graphql_cursor_pagination_two_pages() -> None:
    """REQ-ING-PAG: the GraphQL cursor iterator traverses two pages
    without loss or duplication, driven by ``pageInfo.hasNextPage`` per
    the connector page § Pagination and rate limits.
    """
    repos = json.loads((_FIX / "repositories.json").read_text())
    extra_repo = {
        "id": "MDEwOlJlcG9zaXRvcnkzNDU2Nzg5MA==",
        "databaseId": 34567890,
        "nameWithOwner": "acme/billing-ops",
        "defaultBranchRef": {"name": "main"},
        "isPrivate": True,
        "isArchived": False,
        "isDisabled": False,
        "visibility": "PRIVATE",
        "createdAt": "2024-05-01T09:00:00Z",
        "updatedAt": "2026-04-20T11:00:00Z",
        "pushedAt": "2026-04-20T10:55:00Z",
    }

    pages = [
        (repos, "cursor-1", True),  # page 1 -> hasNextPage=True, endCursor="cursor-1"
        ([extra_repo], "cursor-2", False),  # page 2 -> hasNextPage=False
    ]
    seen_cursors: list[str | None] = []

    def fetch_page(after: str | None):
        seen_cursors.append(after)
        return pages.pop(0)

    batches = list(iter_graphql_cursor_pages(fetch_page))
    assert seen_cursors == [None, "cursor-1"]

    ids = [n["databaseId"] for b in batches for n in b]
    assert ids == [12345678, 23456789, 34567890]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# REQ-ING-RL: HTTP 429 / 403 backoff
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-RL")
def test_429_backoff_exponential_schedule() -> None:
    """REQ-ING-RL: the 429 handler retries with exponential backoff until
    success. Sleep is injected; the test asserts both retry count and
    the delay schedule.

    GitHub enforces 5,000 requests per hour for personal access tokens
    (connector page § Pagination and rate limits) plus secondary limits
    on concurrent and per-minute bursts; on `HTTP 403` / `HTTP 429` the
    connector honors the ``retry-after`` header verbatim.
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
    assert sleeps == [pytest.approx(0.1), pytest.approx(0.2)]


@pytest.mark.requirement("REQ-ING-RL")
def test_429_respects_server_retry_after_hint() -> None:
    """REQ-ING-RL: when the server supplies a retry-after value larger
    than the exponential schedule, the larger value wins. Per the GitHub
    docs, 'If the ``retry-after`` response header is present, you should
    not retry your request until after that many seconds has elapsed.'
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
def test_job_fragment_declares_retries() -> None:
    """REQ-ING-RL: the ingest task in the bundle fragment declares
    ``max_retries >= 1`` and a non-zero ``min_retry_interval_millis`` so
    the framework retries with bounded delay rather than failing the run
    on a transient quota hit.
    """
    with open(_JOB_PATH) as fh:
        job = yaml.safe_load(fh)
    tasks = job["resources"]["jobs"]["github-connector"]["tasks"]
    ingest_task = next(t for t in tasks if t["task_key"] == "ingest")
    assert ingest_task["max_retries"] >= 1
    assert ingest_task["min_retry_interval_millis"] >= 1000
    assert ingest_task.get("retry_on_timeout") is True


# ---------------------------------------------------------------------------
# REQ-ING-HWM: resume across two runs
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_updated_at_hwm_resume(github_config: ConnectorConfig, tmp_path) -> None:
    """REQ-ING-HWM: ``updated_at`` is the documented HWM column and
    round-trips across runs through the common ``UpdatedAtHwm`` store.

    GitHub's ``updated_at`` is always UTC (connector page § Quirks: 'All
    timestamps are ISO 8601 UTC'), so no time-zone normalisation is
    needed at the HWM boundary. The first run writes the max observed
    ``updated_at``; the next run reads it back and supplies it as the
    server-side filter.
    """
    assert github_config.hwm.strategy == "updated_at"
    assert github_config.hwm.column == "updated_at"

    store = HwmStore(tmp_path / "hwm.json")
    hwm = UpdatedAtHwm(key="github::repositories", store=store)

    # First run: epoch sentinel
    assert hwm.read() == datetime(1970, 1, 1, tzinfo=UTC)

    # End of run 1: persist the max observed updated_at
    observed_max = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    hwm.write(observed_max)

    # Run 2 resumes from the persisted value
    resumed = hwm.read()
    assert resumed == observed_max
    assert resumed.tzinfo is not None, "HWM must survive as timezone-aware"

    # The resumed timestamp parses through the connector's ISO helper
    # without raising (i.e. it's ingestable as the server-side filter).
    _parse_iso_utc(resumed.isoformat())


@pytest.mark.requirement("REQ-ING-HWM")
def test_advance_hwm_and_filter_strict_greater_than() -> None:
    """REQ-ING-HWM: ``advance_hwm`` returns the max ``updated_at`` across
    a batch; ``filter_since_hwm`` excludes records whose ``updated_at``
    matches the HWM exactly (strict ``>`` filter).
    """
    items = json.loads((_FIX / "code_scanning_alerts.json").read_text())

    new_hwm = advance_hwm(items, None)
    assert new_hwm == "2026-04-19T09:15:00Z"  # the max in the fixture

    # Run 2: the previously-seen alert is excluded by the strict filter
    second = filter_since_hwm(items, new_hwm)
    assert second == [], "no alert is strictly newer than the prior HWM"

    # First-run semantics: prev_hwm is None -> everything passes.
    assert len(filter_since_hwm(items, None)) == len(items)


# ---------------------------------------------------------------------------
# Webhook signature verification (mode: webhook).
# Not REQ-bound but mandatory per connector page § Quirks.
# ---------------------------------------------------------------------------


def test_webhook_signature_verification_round_trip() -> None:
    """``X-Hub-Signature-256`` is HMAC-SHA-256 of the raw body keyed by
    the operator-supplied ``github_webhook_secret``. The verifier must
    accept correctly-signed bodies and reject mismatched / missing
    signatures (connector page § Quirks).
    """
    import hashlib
    import hmac

    body = b'{"action":"opened","number":42}'
    secret = "synthesized-webhook-secret"
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, f"sha256={digest}", secret) is True
    assert verify_webhook_signature(body, "sha256=00deadbeef", secret) is False
    assert verify_webhook_signature(body, None, secret) is False
    assert verify_webhook_signature(body, "sha1=" + digest, secret) is False


# ---------------------------------------------------------------------------
# Contract-surface smoke tests.
# ---------------------------------------------------------------------------


def test_ingest_wrapper_has_contract_signature() -> None:
    """``ingest(run_id, state)`` exposes the thesis section 2.4.1 surface."""
    sig = inspect.signature(ingest)
    assert list(sig.parameters) == ["run_id", "state"]


def test_ingest_wrapper_requires_extra_fields() -> None:
    """Missing extras raise ValueError rather than returning a
    half-populated descriptor."""
    with pytest.raises(ValueError, match="requires"):
        ingest("run-1", {"source": "github", "run_id": "run-1", "extra": {}})


@pytest.mark.skip(reason="pending live fixtures (B follow-up)")
@pytest.mark.requirement("REQ-ING-AUTH")
def test_expired_token_produces_clear_error() -> None:
    """Requires a real GitHub PAT (revoked) to exercise the 401/403 path
    end-to-end. Synthesized fixtures cannot distinguish SDK-level
    auth-error wrapping from network errors; validate-implementation
    covers this on a live GitHub test tenancy.
    """
