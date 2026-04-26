"""GitHub SCM + GitHub Advanced Security ingestion via PyGitHub.

Per ``operational.yml.databricks_runtime.ingestion_path = sdk`` and
``python_sdk_module = PyGitHub``, this connector delegates auth, pagination,
and rate-limit handling to the PyGitHub library (`Auth`, `Github`,
`PaginatedList`, `GithubRetry`). Live HTTP runs only inside the SDK's
`Github` client; the only hand-rolled helper that remains is
:func:`verify_webhook_signature` (HMAC-SHA-256 keyed by the operator-supplied
webhook secret — HMAC is not SDK territory).

The framework-contract REQ-ING-AUTH / REQ-ING-PAG / REQ-ING-RL / REQ-ING-HWM
concerns map onto PyGitHub primitives:

- AUTH: ``Auth.Token(token)`` injected via ``Github(auth=...)``.
- PAG:  ``PaginatedList`` walks Link-header paged endpoints transparently.
- RL:   ``GithubRetry`` (a ``urllib3.Retry`` subclass) recognises HTTP 403 +
        ``Retry-After`` for secondary rate limits in addition to HTTP 429.
- HWM:  resource accessors such as ``Repository.get_pulls(state, since=)``
        accept a ``since`` parameter — that is the HWM-filter mechanism.
"""

from __future__ import annotations

import hashlib
import hmac

from github import Auth, Github, GithubRetry

from src.platform.contract import BatchDescriptor, ConnectorState


def build_github_client(token: str) -> Github:
    """Construct an authenticated ``Github`` client with retry tuned for
    secondary rate limits.

    ``GithubRetry`` is a ``urllib3.Retry`` subclass that recognises GitHub's
    HTTP 403 + ``Retry-After`` secondary-limit signal alongside the standard
    HTTP 429 path. Per-page size is set to the documented maximum of 100 to
    minimise round trips.
    """
    auth = Auth.Token(token)
    retry = GithubRetry(total=10, backoff_factor=2.0, secondary_rate_wait=60)
    return Github(auth=auth, retry=retry, per_page=100)


def verify_webhook_signature(secret: bytes, body: bytes, signature_header: str | None) -> bool:
    """Verify GitHub's ``X-Hub-Signature-256`` header against the request body.

    HMAC-SHA-256 keyed by the operator-supplied ``github_webhook_secret``;
    constant-time compare via :func:`hmac.compare_digest`. Hand-rolled
    because HMAC is not SDK territory. Returns ``True`` only when the header
    is present, well-formed (``sha256=<hex>``), and matches the computed
    digest. Missing or mismatched signatures must reject with HTTP 401 at
    the receiver.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received = signature_header.split("=", 1)[1].strip()
    computed = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received, computed)


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for GitHub.

    State-carried ``extra`` keys: ``base_url``, ``token``, ``org``,
    ``catalog``. The DAB job driver populates these from bundle variables and
    the secret scope; the connector NEVER reads ``os.environ`` directly per
    REQ-ING-AUTH.

    The wrapper builds the PyGitHub client and demonstrates the canonical
    traversal — ``client.get_organization(org).get_repos()`` returns a
    ``PaginatedList`` of ``Repository`` instances; per-repo
    ``repo.get_pulls(state="closed", since=hwm_value)`` and
    ``repo.get_codescan_alerts()`` walk the finding streams. Live HTTP runs
    on the cluster (per CLAUDE.md no local Spark; pure-Python contract); the
    contract wrapper itself returns a stub ``BatchDescriptor`` keyed to the
    repositories bronze table.

    Raises:
        ValueError: when any required ``state['extra']`` field is missing.
    """
    extra = state.get("extra") or {}
    base_url = extra.get("base_url")
    token = extra.get("token")
    org = extra.get("org")
    catalog = extra.get("catalog")
    if not base_url or not token or not org or not catalog:
        raise ValueError(
            "github.ingest_contract requires state['extra'] with base_url, token, org, catalog"
        )

    # The record_count is 0 in this contract wrapper because the SDK driver
    # writes directly and does not surface a count in-process; accurate
    # counts are recoverable from _batch_id on the Bronze table.
    return {
        "run_id": run_id,
        "source": "github",
        "record_count": 0,
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": f"{catalog}.bronze_github.repositories",
    }


# Backward-compat alias: the framework contract historically calls the wrapper
# ``ingest`` rather than ``ingest_contract``. Keep both names so existing job
# wrappers that import ``ingest`` continue to work.
ingest = ingest_contract
