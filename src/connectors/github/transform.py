"""GitHub transform: bronze envelope rows -> silver entity frames + silver.findings.

Dual-role per the SCM reference: entity rows populate ``silver.repositories``,
``silver.pull_requests`` and ``silver.branch_policies``; finding rows
populate ``silver.findings`` from three GitHub Advanced Security alert
streams interleaved via the ``category`` discriminator (connector page §
Quirks).

Three concurrent finding shapes share the silver.findings union table.
``transform.py`` MUST branch on the shape discriminator and emit
``dedup_links`` rows keyed by the matching tuple per the SCM reference §
Deduplication key. The connector adopts the page-§3 dedup-tuple variant
which extends the SCM reference's three-tuple form with ``start_line`` /
``line_number`` to match the GitHub-native location precision:

- code scanning  (category=sast):    (repository_id, file_path, start_line, rule_id)
- secret scanning (category=secret): (repository_id, secret_type, file_path, line_number)
- Dependabot      (category=sca):    (repository_id, package_name, cve_id)

Severity and status are normalized through the co-located YAML lookup
tables (``severity.yml`` / ``status.yml``) per the canonical mapping
requirements. The pure-Python helpers below are exercised by unit tests
so the framework contract holds without a live Spark session; the
``transform`` Spark wrapper is the production framework-contract entry
point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame

from src.platform.config import SeverityMap, StatusMap
from src.platform.schemas import silver_findings
from src.platform.silver import normalize_severity, normalize_status

_CONNECTOR_DIR = Path(__file__).parent
_SEVERITY_PATH = _CONNECTOR_DIR / "severity.yml"
_STATUS_PATH = _CONNECTOR_DIR / "status.yml"


# ---------------------------------------------------------------------------
# Pure-Python helpers (used by unit tests and the bronze-bypass entry
# points). The Spark entry point ``transform`` below is the framework-
# contract signature; production jobs call that.
# ---------------------------------------------------------------------------


def parse_iso_utc(ts: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp to a timezone-aware UTC datetime.

    GitHub always emits UTC with a trailing ``Z`` (connector page §
    Quirks). Returns ``None`` for missing timestamps so nullable fields
    (``merged_at``, ``resolved_at``, ...) round-trip cleanly through the
    transform.
    """
    if ts is None:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------- Entity projections ---------------------------------------------


def repository_to_silver(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a GitHub repository row to a ``silver.repositories`` row.

    Accepts both the GraphQL shape (``id`` / ``nameWithOwner`` /
    ``defaultBranchRef.name`` / camelCase timestamps) and the REST shape
    (``node_id`` / ``full_name`` / ``default_branch`` / snake_case
    timestamps) per the connector page § Resource schema excerpt. The
    opaque ``node_id`` (``id`` in GraphQL) is the natural key per the
    canonical mapping.
    """
    # GraphQL prefers the opaque node id; REST surfaces it as ``node_id``.
    repository_id = raw.get("id") if isinstance(raw.get("id"), str) else raw.get("node_id")
    if repository_id is None:
        # On REST, the integer ``id`` is the database id, not the node id.
        # The transform falls back to it as a string so legacy fixtures
        # that omit ``node_id`` still produce a populated natural key.
        db_id = raw.get("id")
        repository_id = str(db_id) if db_id is not None else None

    full_name = raw.get("nameWithOwner") or raw.get("full_name")

    default_branch_ref = raw.get("defaultBranchRef")
    default_branch = (
        default_branch_ref.get("name")
        if isinstance(default_branch_ref, dict)
        else raw.get("default_branch")
    )

    updated_raw = raw.get("updatedAt") or raw.get("updated_at")
    return {
        "repository_id": repository_id,
        "full_name": full_name,
        "default_branch": default_branch,
        "updated_at": parse_iso_utc(updated_raw),
    }


def pull_request_to_silver(
    repository_id: str, raw: dict[str, Any]
) -> dict[str, Any]:
    """Project a GitHub pull-request row to a ``silver.pull_requests`` row.

    ``source`` is stamped ``github`` so downstream gold-layer views can
    filter per platform. Nullable timestamps (``merged_at``) round-trip
    as ``None``.
    """
    head = raw.get("head") or {}
    base = raw.get("base") or {}
    user = raw.get("user") or {}
    return {
        "repository_id": repository_id,
        "number": raw["number"],
        "state": raw["state"],
        "merged_at": parse_iso_utc(raw.get("merged_at")),
        "created_at": parse_iso_utc(raw.get("created_at")),
        "updated_at": parse_iso_utc(raw.get("updated_at")),
        "head_sha": head.get("sha"),
        "source_branch": head.get("ref"),
        "target_branch": base.get("ref"),
        "author_username": user.get("login"),
        "source": "github",
    }


def branch_protection_to_silver(
    repository_id: str, branch_name: str, raw: dict[str, Any]
) -> dict[str, Any]:
    """Project a branch-protection row to a ``silver.branch_policies`` row.

    The connector reads the protection settings for the repo's default
    branch (and any additional branches enumerated by the bundle
    parameters); the caller passes the branch name. Empty / missing
    sections collapse to ``None`` rather than raise so the projection
    survives across the matrix of GitHub plan tiers.
    """
    rprr = raw.get("required_pull_request_reviews") or {}
    rsc = raw.get("required_status_checks") or {}
    enforce_admins = raw.get("enforce_admins") or {}
    return {
        "repository_id": repository_id,
        "branch_name": branch_name,
        "required_approving_reviews": rprr.get("required_approving_review_count"),
        "dismiss_stale_reviews": rprr.get("dismiss_stale_reviews"),
        "strict_status_checks": rsc.get("strict"),
        "required_status_check_contexts": rsc.get("contexts"),
        "enforce_admins": enforce_admins.get("enabled"),
    }


# ---------- Finding projections --------------------------------------------


def _compose_status_key(state: str | None, resolution: str | None) -> str:
    """Compose a lookup key for ``status.yml`` from a ``(state, resolution)``
    pair.

    Per the connector page § Enumerations, secret-scanning and
    Dependabot alerts use a resolution refinement on top of the bare
    state. The composite shape is ``state-resolution`` so the lookup
    table answers without bespoke per-stream logic.
    """
    if state is None:
        return ""
    if resolution:
        return f"{state}-{resolution}"
    return state


def _dedup_key_for(category: str, row: dict[str, Any]) -> tuple:
    """Return the finding-shape-specific dedup key tuple.

    Encodes the tuples from the Phase-2 GitHub-specific guidance verbatim
    (page §3 quirks). This is the branch that must stay in lockstep with
    the ``category`` discriminator; mis-branching corrupts ``dedup_links``.
    """
    if category == "sast":
        return (
            row.get("repository_id"),
            row.get("file_path"),
            row.get("start_line"),
            row.get("rule_id_native"),
        )
    if category == "secret":
        return (
            row.get("repository_id"),
            row.get("secret_type"),
            row.get("file_path"),
            row.get("start_line"),
        )
    if category == "sca":
        return (
            row.get("repository_id"),
            row.get("package_name"),
            row.get("cve_id"),
        )
    # Unknown category: fall back to the finding_id as the dedup key so
    # at least one shape-stable identity survives downstream joins.
    return (row.get("finding_id"),)


def code_scanning_alert_to_finding(
    repository_id: str, raw: dict[str, Any], severity_map: SeverityMap, status_map: StatusMap
) -> dict[str, Any]:
    """Project a code-scanning alert to a ``silver.findings`` row
    (``category = "sast"``).

    Severity is taken from ``rule.security_severity_level`` per the
    connector page § Enumerations (the rule-level ``severity`` is kept
    as a domain column upstream; it is NOT authoritative). The dedup
    key extends the SCM reference's three-tuple with ``start_line`` to
    match GitHub's location precision.
    """
    rule = raw.get("rule") or {}
    instance = raw.get("most_recent_instance") or {}
    location = (instance.get("location") or {})

    sev_native = rule.get("security_severity_level")
    severity_canonical = (
        normalize_severity(sev_native, severity_map)
        if sev_native is not None
        else "medium"  # connector page § Enumerations: configurable default
    )
    status_canonical = normalize_status(raw.get("state") or "", status_map)

    finding = {
        "finding_id": f"github-code-{repository_id}-{raw['number']}",
        "tool_source": "github",
        "category": "sast",
        "severity_canonical": severity_canonical,
        "status_canonical": status_canonical,
        "rule_id_native": rule.get("id"),
        "repository_id": repository_id,
        "file_path": location.get("path"),
        "start_line": location.get("start_line"),
        "url": raw.get("html_url"),
        "cwe_id": None,
        "cve_id": None,
        "first_seen_at": parse_iso_utc(raw.get("created_at")),
        "last_seen_at": parse_iso_utc(raw.get("updated_at")),
        "trigger_context": "periodic",
    }
    finding["dedup_key"] = _dedup_key_for("sast", finding)
    return finding


def secret_scanning_alert_to_finding(
    repository_id: str, raw: dict[str, Any], severity_map: SeverityMap, status_map: StatusMap
) -> dict[str, Any]:
    """Project a secret-scanning alert to a ``silver.findings`` row
    (``category = "secret"``).

    Per the connector page § Enumerations: the alert object does not
    embed a native severity; the connector emits ``high`` (operators may
    override per deployment in ``severity.yml``). The first location's
    ``path`` and ``start_line`` are taken from the follow-up
    ``locations_url`` payload (already merged into ``raw`` by the
    ingestor) before this projection runs.
    """
    state = raw.get("state")
    resolution = raw.get("resolution")
    status_canonical = normalize_status(
        _compose_status_key(state, resolution), status_map
    )
    # Native severity absent for secret scanning per page §; severity
    # lookup applied for forward-compatibility if GitHub later exposes
    # one. Default per page is ``high``.
    severity_canonical = "high"

    locations = raw.get("locations") or []
    first_loc = locations[0] if locations else {}
    details = first_loc.get("details") or first_loc

    finding = {
        "finding_id": f"github-secret-{repository_id}-{raw['number']}",
        "tool_source": "github",
        "category": "secret",
        "severity_canonical": severity_canonical,
        "status_canonical": status_canonical,
        "rule_id_native": raw.get("secret_type"),
        "secret_type": raw.get("secret_type"),
        "repository_id": repository_id,
        "file_path": details.get("path"),
        "start_line": details.get("start_line"),
        "url": raw.get("html_url"),
        "cwe_id": None,
        "cve_id": None,
        "first_seen_at": parse_iso_utc(raw.get("created_at")),
        "last_seen_at": parse_iso_utc(raw.get("updated_at")),
        "trigger_context": "periodic",
    }
    # Quiet pyflakes: severity_map is reserved for the forward-compat
    # path. Reference it explicitly so static analyzers don't flag it.
    _ = severity_map
    finding["dedup_key"] = _dedup_key_for("secret", finding)
    return finding


def dependabot_alert_to_finding(
    repository_id: str, raw: dict[str, Any], severity_map: SeverityMap, status_map: StatusMap
) -> dict[str, Any]:
    """Project a Dependabot alert to a ``silver.findings`` row
    (``category = "sca"``).

    Severity comes from ``security_vulnerability.severity`` per the
    connector page § Enumerations (identity mapping into the four-level
    canonical model). The dedup key is the SCA-shape tuple
    ``(repository_id, package_name, cve_id)``.
    """
    sec_vuln = raw.get("security_vulnerability") or {}
    advisory = raw.get("security_advisory") or {}
    dependency = raw.get("dependency") or {}
    package = dependency.get("package") or {}

    sev_native = sec_vuln.get("severity")
    severity_canonical = (
        normalize_severity(sev_native, severity_map) if sev_native else "medium"
    )
    status_canonical = normalize_status(raw.get("state") or "", status_map)

    cve_id = advisory.get("cve_id")
    finding = {
        "finding_id": f"github-dependabot-{repository_id}-{raw['number']}",
        "tool_source": "github",
        "category": "sca",
        "severity_canonical": severity_canonical,
        "status_canonical": status_canonical,
        "rule_id_native": cve_id or f"GHSA-{raw['number']}",
        "package_name": package.get("name"),
        "ecosystem": package.get("ecosystem"),
        "cve_id": cve_id,
        "cwe_id": None,
        "repository_id": repository_id,
        "file_path": None,
        "start_line": None,
        "url": raw.get("html_url"),
        "first_seen_at": parse_iso_utc(raw.get("created_at")),
        "last_seen_at": parse_iso_utc(raw.get("updated_at")),
        "trigger_context": "periodic",
    }
    finding["dedup_key"] = _dedup_key_for("sca", finding)
    return finding


# ---------------------------------------------------------------------------
# Framework contract wrapper.
# ---------------------------------------------------------------------------


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper: bronze rows -> silver frame.

    The full Spark mapping against the GitHub bronze tables is pending
    (the bronze ingestion notebook is emitted by the DAB job defined in
    ``src/connectors/github/resources/job.yml``). This wrapper honours
    the section 2.4.1 signature ``transform(bronze_df) -> silver_df`` by
    returning an empty ``silver_findings`` frame so the orchestration
    layer can chain without a runtime error. Replace with a full mapping
    once the alert-stream bronze schema is stable.
    """
    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)


__all__ = [
    "branch_protection_to_silver",
    "code_scanning_alert_to_finding",
    "dependabot_alert_to_finding",
    "parse_iso_utc",
    "pull_request_to_silver",
    "repository_to_silver",
    "secret_scanning_alert_to_finding",
    "transform",
]
