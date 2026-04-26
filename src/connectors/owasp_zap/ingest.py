"""OWASP ZAP bronze ingest — hybrid (CI/CD artefact + daemon REST API).

Two ingestion paths land in the same bronze table, discriminated at write
time by a ``trigger_context`` column:

- ``trigger_context="cicd"`` — ``zap-baseline.py`` / ``zap-full-scan.py``
  / ``zap-api-scan.py`` JSON reports under ``s3://<bucket>/cicd/zap/``;
  Auto Loader streams new files as they appear. There is no native
  authentication on the report files; access is governed by the bucket
  IAM policy. ``REQ-ING-AUTH`` is N/A for this path.
- ``trigger_context="on_demand"`` — the long-lived ZAP daemon REST API
  (``http://<host>:<port>/JSON/...``). Authentication is the ``apikey``
  query parameter, configured at daemon startup with
  ``-config api.key=<KEY>``. ``REQ-ING-AUTH`` applies on the daemon path.

The CI/CD-step artefact path is the canonical ingestion pattern for the
DAST category; per ``references/dast.md`` § "Ingestion-tooling
preference" autoloader-style on the object-storage prefix is the
DOCUMENTED EXCEPTION to the standard Lakeflow Connect -> SDK -> dlt
preference order. The daemon REST path uses ``urllib.request`` against
the daemon's loopback / VPC-private endpoint with the secret-scrubbed
URL convention documented in §3 Quirks of the connector page.

State / HWM:

- CI/CD-step path keys on ``hwm_kind: artefact_prefix`` (the most
  recently ingested object key under ``cicd/zap/``).
- Daemon path keys on ``hwm_kind: scan_id`` (the largest numeric
  ``scanId`` read for ``(target, scan_kind)``). Daemon restarts reset
  the counter; the connector treats that as an HWM reset.

The two HWMs advance independently — ``state.hwm`` discriminates by
``path`` (``cicd_artefact`` or ``daemon``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

from src.platform.bronze_schema import with_envelope
from src.platform.contract import BatchDescriptor, ConnectorState

_LOG = logging.getLogger(__name__)

# Documented ZAP risk vocabulary; used for sanity-checking inputs before
# severity normalisation. Undocumented values fall through to the default
# at the lookup stage (see severity.yml).
DOCUMENTED_RISKS: tuple[str, ...] = ("Informational", "Low", "Medium", "High")

# Documented scan kinds the connector orchestrates on the daemon path.
DOCUMENTED_SCAN_KINDS: tuple[str, ...] = ("spider", "ascan")

# REST endpoint templates for the daemon path. Note the apikey is a
# query parameter — the documented anti-CSRF defence — NOT a header.
# `_scrub_apikey` strips it before logging.
ZAP_ENDPOINTS = {
    "spider_action_scan": "/JSON/spider/action/scan/",
    "spider_view_status": "/JSON/spider/view/status/",
    "ascan_action_scan": "/JSON/ascan/action/scan/",
    "ascan_view_status": "/JSON/ascan/view/status/",
    "alert_view_alerts": "/JSON/alert/view/alerts/",
    "alert_view_summary": "/JSON/alert/view/alertsSummary/",
    "core_view_sites": "/JSON/core/view/sites/",
    "core_view_version": "/JSON/core/view/version/",
}


def classify_trigger(path_or_url: str, *, cicd_marker: str = "/cicd/zap/") -> str:
    """Map an ingest source path/URL to the canonical ``trigger_context``.

    Returns ``"cicd"`` for object-storage prefixes carrying the documented
    ``cicd_marker`` substring, ``"on_demand"`` for HTTP/HTTPS daemon URLs.
    Raises ``ValueError`` for inputs that match neither — misclassified
    sources MUST surface immediately rather than silently land in Bronze
    with an ambiguous ``trigger_context``.

    The discriminator drives the per-path HWM (``artefact_prefix`` vs
    ``scan_id``) and the REQ-ING-AUTH applicability (N/A for cicd; bound
    for on_demand). See `mkdocs/docs/connectors/dast/owasp-zap.md` §3.
    """
    if not isinstance(path_or_url, str) or not path_or_url:
        raise ValueError(f"owasp_zap.classify_trigger: empty input {path_or_url!r}")
    object_storage_schemes = ("s3://", "s3a://", "abfss://", "gs://")
    if path_or_url.startswith(object_storage_schemes) and cicd_marker in path_or_url:
        return "cicd"
    if path_or_url.startswith(("http://", "https://")):
        return "on_demand"
    raise ValueError(
        f"owasp_zap.classify_trigger: cannot route {path_or_url!r} — "
        f"expected an object-storage URI containing {cicd_marker!r} "
        "or an http(s) ZAP daemon URL"
    )


def _scrub_apikey(url: str) -> str:
    """Return ``url`` with the ZAP ``apikey`` query parameter elided.

    The connector MUST scrub ``apikey`` from any logged URL — per §3
    Quirks of the connector page, the API key is a query-string parameter
    rather than a header, so it would otherwise leak into URL-flavour
    structured logs. Used by the secret scrubber and on every retry-log
    emission.
    """
    out = []
    for part in url.split("&"):
        if part.startswith("apikey=") or "?apikey=" in part:
            head, _, _tail = part.partition("apikey=")
            out.append(head + "apikey=***")
        else:
            out.append(part)
    return "&".join(out)


def build_alerts_url(
    base_url: str,
    *,
    baseurl: str,
    apikey: str,
    start: int = 0,
    count: int = 5000,
) -> str:
    """Return the GET URL for ``/JSON/alert/view/alerts/``.

    Offset/limit pagination via ``start`` / ``count`` per the connector
    page. The reference page-size value is ``5000`` (matches the example
    in the ZAP API docs). The connector iterates ``start += count`` until
    a short page (or empty response) terminates the loop.
    """
    qs = urlencode({"baseurl": baseurl, "start": start, "count": count, "apikey": apikey})
    return f"{base_url.rstrip('/')}{ZAP_ENDPOINTS['alert_view_alerts']}?{qs}"


def iter_paged_alerts(
    fetch_json,
    base_url: str,
    *,
    baseurl: str,
    apikey: str,
    page_size: int = 5000,
) -> Iterator[dict[str, Any]]:
    """Yield ZAP alerts from ``/JSON/alert/view/alerts/`` with offset/limit
    pagination.

    ``fetch_json`` is an injected callable ``(url) -> dict`` so the
    pagination loop can be unit-tested without a live ZAP daemon. The
    loop terminates when the server returns a short page (``len < count``)
    or an empty page — the documented end-of-results signal for offset
    pagination on this endpoint.

    REQ-ING-PAG: applies on the daemon path; the CI/CD artefact path
    has no pagination (one report per pipeline run).
    """
    start = 0
    while True:
        url = build_alerts_url(
            base_url,
            baseurl=baseurl,
            apikey=apikey,
            start=start,
            count=page_size,
        )
        _LOG.debug("ZAP page fetch: %s", _scrub_apikey(url))
        page = fetch_json(url) or {}
        alerts = page.get("alerts") or []
        if not alerts:
            return
        yield from alerts
        if len(alerts) < page_size:
            return
        start += page_size


def split_uri_for_dedup(uri: str | None) -> tuple[str | None, str | None]:
    """Split a ZAP ``uri`` into ``(target, uri_path)`` for the dedup tuple.

    Per references/dast.md the dedup key is ``(target, alert_id, uri_path)``;
    ``uri`` is the full URI emitted by ZAP (e.g. ``https://app.test/api/x?y=1``)
    and the connector splits it into:

    - ``target`` — scheme + host + port (joins against silver.deployments).
    - ``uri_path`` — path + query (per-path disambiguator).

    Returns ``(None, None)`` on empty input. The split is stable: a
    bare host with no path becomes ``("https://host", "/")``.
    """
    if not uri or not isinstance(uri, str):
        return (None, None)
    # Manual split rather than urlparse to avoid losing IPv6 brackets etc.
    scheme_end = uri.find("://")
    if scheme_end < 0:
        return (None, uri)
    rest_start = scheme_end + 3
    path_start = uri.find("/", rest_start)
    if path_start < 0:
        return (uri, "/")
    return (uri[:path_start], uri[path_start:])


def select_alert_name(alert: dict[str, Any]) -> str | None:
    """Read the human-readable rule name from a ZAP alert object.

    Reads ``name`` first, then falls back to ``alert``, then to ``pluginId``
    /``pluginid`` for safety. Per §3 Quirks of the connector page, the
    REST API and JSON-report flavours of the alert object inconsistently
    populate the two name fields.
    """
    for key in ("name", "alert", "pluginid", "pluginId"):
        v = alert.get(key)
        if v:
            return str(v)
    return None


def normalise_cwe_id(raw: Any) -> str | None:
    """Project ZAP ``cweid`` onto a canonical CWE string column.

    Returns ``None`` for missing values and the documented ZAP placeholders
    (``""``, ``"0"``, ``"-1"``). Per §3 Quirks: both ``cweid`` and ``wascid``
    use ``-1`` as a string sentinel when unmapped — the transform converts
    this to ``NULL`` before writing to Silver.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s in {"", "0", "-1"}:
        return None
    return s


def run_ingest_pipeline(
    spark,
    *,
    cicd_bucket: str | None,
    cicd_prefix: str | None,
    bronze_table: str,
    run_id: str,
    new_hwm_value: str | None = None,
) -> None:
    """Databricks entry point for the CI/CD-step artefact path.

    Reads JSON reports from ``s3://<bucket>/<cicd_prefix>`` recursively
    via Spark (Auto Loader-style) and stamps the bronze envelope. Each
    Bronze row is a single ZAP scan-report document; transform.py
    explodes ``site -> alerts -> instances`` into Silver rows.

    The daemon REST path is wired through :func:`iter_paged_alerts`
    rather than this Spark loader — the daemon path is driver-side
    (one HTTP loop) and the bulk Bronze write is left to the caller.
    """
    from pyspark.sql import functions as F

    if not cicd_bucket or not cicd_prefix:
        raise ValueError(
            "owasp_zap CI/CD-step ingest requires both bucket and prefix; "
            f"got bucket={cicd_bucket!r} prefix={cicd_prefix!r}"
        )

    df = (
        spark.read.format("json")
        .option("recursiveFileLookup", "true")
        .load(f"s3://{cicd_bucket}/{cicd_prefix}")
    )
    df = df.withColumn("trigger_context", F.lit("cicd"))
    df = with_envelope(
        df,
        source_system="owasp_zap",
        batch_id=run_id,
        # HWM = most-recently-ingested object key under cicd/zap/.
        # Auto Loader's checkpoint is the primary mechanism; the
        # recorded value is a secondary backfill-audit signal.
        hwm_value=new_hwm_value,
    )
    df.writeTo(bronze_table).append()


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for OWASP ZAP.

    The CI/CD-step artefact path keeps its source-specific signature
    (spark session, bucket, prefix, bronze table). The contract wrapper
    is invoked by the DAB job driver, which reads the non-contract
    arguments from bundle variables via ``state["extra"]``.

    REQ-ING-AUTH: the daemon path requires the ``apikey`` query
    parameter; its absence is a hard error rather than a silent skip.
    The CI/CD-step path is N/A under the catalog matrix — no auth
    check is enforced for that path because access is governed by
    object-storage IAM at the workspace level.
    """
    extra = state.get("extra") or {}
    spark = extra.get("spark")
    catalog = extra.get("catalog")
    cicd_bucket = extra.get("cicd_bucket") or extra.get("bucket")
    cicd_prefix = extra.get("cicd_prefix", "cicd/zap/")
    # Optional daemon-path knobs; only enforced when the caller
    # explicitly asks for the on-demand path.
    trigger_context = extra.get("trigger_context", "cicd")
    zap_api_url = extra.get("zap_api_url")
    zap_api_key = extra.get("zap_api_key")

    if spark is None or not catalog:
        raise ValueError("owasp_zap.ingest_contract requires state['extra'] with spark and catalog")

    # REQ-ING-AUTH guard for the daemon path. The api key is the only
    # documented mechanism (query parameter, NOT a header).
    if trigger_context == "on_demand" and (not zap_api_url or not zap_api_key):
        raise ValueError(
            "owasp_zap.ingest_contract on_demand path requires "
            "state['extra']['zap_api_url'] and state['extra']['zap_api_key']; "
            "ZAP rejects requests with a missing or wrong apikey "
            "(refusing to run rather than silently fail)"
        )

    bronze_table = extra.get("bronze_table") or f"{catalog}.bronze_owasp_zap.findings"

    if trigger_context == "cicd":
        run_ingest_pipeline(
            spark,
            cicd_bucket=cicd_bucket,
            cicd_prefix=cicd_prefix,
            bronze_table=bronze_table,
            run_id=run_id,
            new_hwm_value=state.get("hwm_value"),
        )
    # The on_demand branch is exercised by iter_paged_alerts under the
    # caller's driver loop (no Spark write here — the daemon path is
    # one HTTP loop wide and the bulk write is downstream).

    return {
        "run_id": run_id,
        "source": "owasp_zap",
        "record_count": 0,  # write-directly shape; count not surfaced in-process
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
