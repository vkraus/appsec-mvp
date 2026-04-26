"""GitLab transform: bronze envelope rows -> silver entity frames + silver.findings.

Dual-role per the SCM reference: entities populate
``silver.repositories`` / ``silver.commits`` / ``silver.pull_requests`` /
``silver.branch_policies``, and (on GitLab Ultimate) the Vulnerabilities API
emits SAST, Secret Detection, Dependency Scanning, DAST, and Container
Scanning findings interleaved on a single endpoint. ``report_type`` is the
shape discriminator per the connector page § Quirks, and ``transform.py``
branches on it to emit the correct ``(dedup-key tuple)`` per shape:

- sast / secret_detection -> (repository_id, file_path, start_line, rule_id)
- dependency_scanning     -> (repository_id, package_name, cve_id)

Severity (``info``, ``unknown``, ``low``, ``medium``, ``high``, ``critical``)
and status (``detected``, ``confirmed``, ``dismissed``, ``resolved``) are
normalized through the ``config/severity/gitlab.yml`` and
``config/status/gitlab.yml`` lookup tables per the canonical mapping
requirements.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pyspark.sql import DataFrame

from src.platform.schemas import silver_findings

# ---------------------------------------------------------------------------
# Pure-Python projections (used by unit tests and bronze-bypass entry points).
# The Spark entry point ``transform`` below is the framework-contract
# signature; production jobs call that.
# ---------------------------------------------------------------------------


# Maps GitLab Vulnerabilities API ``report_type`` to the canonical ``category``
# column in ``silver.findings`` per the connector page § Enumerations.
_REPORT_TYPE_TO_CATEGORY = {
    "sast": "sast",
    "secret_detection": "secret",
    "dependency_scanning": "sca",
    "dast": "dast",
    "container_scanning": "container",
}


def parse_iso_utc(ts: str | None) -> datetime | None:
    """Parse a GitLab ISO-8601 timestamp to a timezone-aware UTC datetime.

    Returns ``None`` for missing timestamps so nullable fields round-trip
    cleanly through the transform.
    """
    if ts is None:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _extract_cwe_id(raw: dict[str, Any]) -> str | None:
    """Extract a CWE class identifier from a GitLab vulnerability row.

    Returns ``"CWE-NNN"`` for the first CWE-typed identifier in
    ``identifiers``; ``None`` if none present. CVE-typed identifiers go
    to ``cve_id`` instead (silver_findings has both columns).
    """
    for ident in raw.get("identifiers") or []:
        if (ident.get("external_type") or "").lower() == "cwe":
            value = ident.get("external_id") or ident.get("name")
            if value:
                value_str = str(value)
                return value_str if value_str.upper().startswith("CWE-") else f"CWE-{value_str}"
    return None


def project_to_repository(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a GitLab ``/projects`` row to a ``silver.repositories`` row.

    Per the connector page § Quirks the stable integer ``id`` is used as the
    ``natural_key`` / ``repository_id``; ``path_with_namespace`` is kept as
    a display column alongside. ``last_activity_at`` is the freshest
    timestamp GitLab exposes, so it feeds ``updated_at`` in Silver when
    present; otherwise the record's ``updated_at`` is used.
    """
    updated_raw = raw.get("last_activity_at") or raw.get("updated_at")
    return {
        "repository_id": str(raw["id"]),
        "full_name": raw["path_with_namespace"],
        "default_branch": raw.get("default_branch"),
        "updated_at": parse_iso_utc(updated_raw),
    }


def merge_request_to_pull_request(project_id: int | str, raw: dict[str, Any]) -> dict[str, Any]:
    """Project a GitLab merge-request row to a ``silver.pull_requests`` row.

    GitLab's *merge request* is GitHub's *pull request* (connector page §
    Quirks). ``iid`` is the project-scoped MR number and maps to
    ``pull_request.number``. ``source`` is stamped ``gitlab`` so downstream
    gold-layer views can filter per platform.
    """
    return {
        "repository_id": str(project_id),
        "number": raw["iid"],
        "state": raw["state"],
        "merged_at": parse_iso_utc(raw.get("merged_at")),
        "created_at": parse_iso_utc(raw.get("created_at")),
        "updated_at": parse_iso_utc(raw.get("updated_at")),
        "source_branch": raw.get("source_branch"),
        "target_branch": raw.get("target_branch"),
        "author_username": (raw.get("author") or {}).get("username"),
        "source": "gitlab",
    }


# GitLab access-level integer -> canonical policy vocabulary.
# From connector page § Enumerations: 0=No access, 30=Developer, 40=Maintainer, 60=Admin.
_ACCESS_LEVEL_TO_ROLE = {
    0: "no_access",
    30: "developer",
    40: "maintainer",
    60: "admin",
}


def protected_branch_to_policy(project_id: int | str, raw: dict[str, Any]) -> dict[str, Any]:
    """Project a protected-branch row to a ``silver.branch_policies`` row.

    ``allowed_to_push`` and ``allowed_to_merge`` are arrays of access-level
    entries; the transform reduces each to the highest-privilege canonical
    role, which matches how gold-layer policy checks consume the column.
    """

    def _highest(entries: list[dict[str, Any]] | None) -> str | None:
        if not entries:
            return None
        levels = [e.get("access_level") for e in entries if e.get("access_level") is not None]
        if not levels:
            return None
        return _ACCESS_LEVEL_TO_ROLE.get(max(levels))

    return {
        "repository_id": str(project_id),
        "branch_name": raw["name"],
        "allowed_to_push": _highest(raw.get("push_access_levels")),
        "allowed_to_merge": _highest(raw.get("merge_access_levels")),
    }


def _dedup_key_for(category: str, row: dict[str, Any]) -> tuple:
    """Return the finding-shape-specific dedup key tuple.

    Encodes the tuples from the SCM reference § Deduplication key verbatim.
    This is the branch that must stay in lockstep with the ``category``
    discriminator; mis-branching corrupts ``dedup_links``.
    """
    if category in ("sast", "secret"):
        return (
            row.get("repository_id"),
            row.get("file_path"),
            row.get("start_line"),
            row.get("rule_id_native"),
        )
    if category == "sca":
        return (
            row.get("repository_id"),
            row.get("package_name"),
            row.get("cve_id"),  # canonical SCA dedup tuple per silver-finding-mapping-requirements
        )
    # dast / container / other: fall back to the finding_id as the dedup key.
    return (row.get("finding_id"),)


def vulnerability_to_finding(project_id: int | str, raw: dict[str, Any]) -> dict[str, Any]:
    """Project a Vulnerabilities-API row to a ``silver.findings`` row.

    The ``cve`` field is promoted when present; otherwise the connector
    falls back to the first ``CVE``-typed entry in ``identifiers`` per the
    connector page § Resource schema excerpt. Severity and status are left
    as raw source values here; callers pass the ``(raw, severity_canonical,
    status_canonical)`` triple through ``normalize_severity`` /
    ``normalize_status`` to resolve them through the YAML lookups.
    """
    cve = raw.get("cve")
    if not cve:
        for ident in raw.get("identifiers") or []:
            if (ident.get("external_type") or "").lower() == "cve":
                cve = ident.get("external_id") or ident.get("name")
                break

    report_type = raw.get("report_type") or ""
    category = _REPORT_TYPE_TO_CATEGORY.get(report_type, report_type or "other")

    location = raw.get("location") or {}
    finding = {
        "finding_id": f"gitlab-vuln-{raw['id']}",
        "tool_source": "gitlab",
        "category": category,
        "report_type": report_type,
        "severity_native": raw.get("severity"),
        "status_native": raw.get("state"),
        "cwe_id": _extract_cwe_id(raw),
        "cve_id": cve,
        "rule_id_native": raw.get("name"),
        "repository_id": str(project_id),
        "file_path": location.get("file"),
        "start_line": location.get("start_line"),
        "package_name": (location.get("dependency") or {}).get("package", {}).get("name"),
        "url": None,
        "first_seen_at": parse_iso_utc(raw.get("created_at")),
        "last_seen_at": parse_iso_utc(raw.get("updated_at")),
        "trigger_context": "periodic",
    }
    finding["dedup_key"] = _dedup_key_for(category, finding)
    return finding


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper: bronze rows -> silver frame.

    The full Spark mapping against the GitLab bronze tables is pending (the
    bronze ingestion notebook is emitted by the DAB job defined in
    ``resources/gitlab-job.yml``). This wrapper honours the section 2.4.1
    signature ``transform(bronze_df) -> silver_df`` by returning an empty
    ``silver_findings`` frame so the orchestration layer can chain without
    a runtime error. Replace with a full mapping once the Vulnerabilities-API
    bronze schema is stable.
    """
    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)
