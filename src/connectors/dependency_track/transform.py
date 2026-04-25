"""Bronze-to-silver transform for Dependency-Track.

Per thesis section 4 Future Work, the Spark-side declarative transform for
Dependency-Track onto ``silver.findings`` is not yet wired into the job.
This module honors the section 2.4.1 contract ``transform(bronze_df) ->
silver_df`` by returning an empty ``silver_findings`` DataFrame so
downstream orchestration can chain the call without a runtime error.

Pure-Python per-record mapping lives in ``flatten_to_silver_row`` below —
it encodes the SCA dedup key ``(repository_id, package_name, cve_id)``
literally, covers the severity/status lookups declared in
``mapping.yml``, and is exercised by the unit tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import yaml
from pyspark.sql import DataFrame

from src.platform.schemas import silver_findings

_DEFAULT_SEVERITY = "medium"


def load_lookup(path: str) -> dict[str, str]:
    """Load a severity or status YAML lookup from disk.

    The mapping files are authoritative; Python only reads them. See
    CLAUDE.md under "Architectural rules".
    """
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def normalize_severity(
    native: str | None, cvss_v3: float | None, lookup: dict[str, str]
) -> str:
    """Return the canonical severity.

    Precedence (matches mapping.yml):
    1. Lookup on native label when present and mapped.
    2. CVSS v3 derivation rule (>=9.0 critical, >=7.0 high, >=4.0 medium,
       >0.0 low, 0.0 / None -> default).
    3. ``_DEFAULT_SEVERITY`` ("medium") with an implied data-quality
       warning — UNASSIGNED falls here per the connector page Quirks.
    """
    if native is not None:
        mapped = lookup.get(native)
        if mapped is not None:
            return mapped
    if cvss_v3 is not None:
        try:
            score = float(cvss_v3)
        except (TypeError, ValueError):
            score = None
        if score is not None:
            if score >= 9.0:
                return "critical"
            if score >= 7.0:
                return "high"
            if score >= 4.0:
                return "medium"
            if score > 0.0:
                return "low"
    return _DEFAULT_SEVERITY


def normalize_status(_finding: dict, lookup: dict[str, str]) -> str:
    """Return the canonical status.

    Dependency-Track's /finding endpoint carries a finding-level
    ``analysis.state`` (NOT_SET, EXPLOITABLE, IN_TRIAGE, FALSE_POSITIVE,
    NOT_AFFECTED, RESOLVED) plus a ``suppressed`` boolean. The status
    lookup encodes that vocabulary; the default for NOT_SET is "open".
    """
    analysis = _finding.get("analysis") or {}
    suppressed = _finding.get("isSuppressed") or analysis.get("suppressed")
    if suppressed:
        return "wontfix"
    state = analysis.get("state")
    return lookup.get(state, "open") if state else "open"


def normalize_attributed_on(value: str | None) -> datetime | None:
    """Parse the ISO-8601 ``attributedOn`` to a timezone-aware UTC datetime.

    Accepts both ``Z``-terminated and ``+00:00``-terminated forms. Naive
    strings are rejected per the framework's timestamp contract.
    """
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"attributedOn must be timezone-aware: {value!r}")
    return parsed.astimezone(UTC)


def build_dedup_key(row: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return the SCA dedup tuple (repository_id, package_name, cve_id).

    This matches the SCA capability surface at
    mkdocs/docs/connectors/sca/index.md and the canonical Silver Finding
    shape at mkdocs/docs/platform/reference/canonical-mapping.md.
    """
    return (row.get("repository_id"), row.get("package_name"), row.get("cve_id"))


def flatten_to_silver_row(
    bronze_row: dict[str, Any],
    severity_lookup: dict[str, str],
    status_lookup: dict[str, str],
) -> dict[str, Any]:
    """Project one bronze payload to a silver.findings-shaped dict.

    Applies severity/status normalization, derives the synthetic
    ``finding_id`` from the dedup tuple, and preserves the trigger_context
    as ``periodic`` (Dependency-Track is exclusively periodic-global).
    """
    repo_id, pkg_name, cve_id = build_dedup_key(bronze_row)
    attributed_ts = normalize_attributed_on(bronze_row.get("attributed_on"))
    severity = normalize_severity(
        bronze_row.get("severity_native"),
        bronze_row.get("cvss_v3"),
        severity_lookup,
    )
    status = normalize_status(bronze_row, status_lookup)
    # finding_id: synthetic, stable across runs — built from the dedup
    # anchor plus the advisory source so per-source attribution is
    # preserved until the dedup stage collapses duplicates.
    advisory_source = bronze_row.get("advisory_source") or "UNKNOWN"
    finding_id = (
        f"dependency-track::{repo_id}::{pkg_name}::"
        f"{cve_id or bronze_row.get('vuln_id_native')}@{advisory_source}"
    )
    cwe_id = bronze_row.get("cwe_id")
    return {
        "finding_id": finding_id,
        "tool_source": "dependency_track",
        "category": "sca",
        "severity_canonical": severity,
        "status_canonical": status,
        "cwe_id": str(cwe_id) if cwe_id is not None else None,
        "rule_id_native": bronze_row.get("vuln_id_native"),
        "trigger_context": "periodic",
        "repository_id": repo_id,
        "file_path": None,
        "start_line": None,
        "url": None,
        "first_seen_at": attributed_ts,
        "last_seen_at": attributed_ts,
    }


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper. Returns an empty silver_findings frame.

    The real mapping is driven by ``mapping.yml`` plus the
    ``flatten_to_silver_row`` helper above; wiring that into a Spark
    pipeline is tracked under thesis section 4 Future Work.
    """
    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)
