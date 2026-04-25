"""Dependency-Track ingestion.

Server-based SCA source. Polls the Dependency-Track REST API for projects,
then per-project for findings, using `attribution.attributedOn` as the
high-water mark. Records are flattened per-finding: one bronze row per
(project, component, vulnerability) triple.

Ingestion tooling preference (thesis §2.4.1): Lakeflow Connect → Databricks
SDK → dlt. Dependency-Track has no Lakeflow connector and is not a
first-party SaaS exposed by the Databricks SDK, so this connector targets
dlt's REST source. Live HTTP is performed only inside
``run_ingest_pipeline``; the pure-Python helpers (`build_api_url`,
`classify_project`, `extract_ecosystem_from_purl`, `extract_cve_id`,
`select_finding_hwm`) drive unit-testable logic and are covered under
``tests/connectors/dependency_track/``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.common.contract import BatchDescriptor, ConnectorState

_PURL_ECOSYSTEM_RE = re.compile(r"^pkg:([^/]+)/")

# CVE-like advisory identifiers that land in silver `cve_id` unchanged.
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)


def build_api_url(base_url: str, path_template: str, **params: str) -> str:
    """Compose a Dependency-Track REST URL from the config-declared template.

    The endpoint templates in ``config.yml`` carry named placeholders (e.g.
    ``/api/v1/finding/project/{uuid}``). This helper substitutes them while
    stripping the trailing slash on ``base_url`` to avoid double-slashes.
    """
    path = path_template.format(**params) if params else path_template
    return f"{base_url.rstrip('/')}{path}"


def classify_project(project: dict, allowed_classifiers: Iterable[str]) -> bool:
    """Return True iff the project should be ingested.

    Inactive projects are excluded by default; the project classifier must
    be in the configured ``classifier_filter`` (APPLICATION, CONTAINER by
    default). Per mkdocs/docs/connectors/sca/dependency-track.md §
    "Enumerations".
    """
    if not project.get("active", True):
        return False
    classifier = project.get("classifier")
    return classifier in set(allowed_classifiers)


def extract_ecosystem_from_purl(purl: str | None) -> str | None:
    """Return the ecosystem token from a PURL, or None if unparseable.

    Dependency-Track does not expose ecosystem as a discrete field; it lives
    between ``pkg:`` and the first ``/`` in the component PURL. Example:
    ``pkg:pypi/requests@2.28.0`` -> ``pypi``. See the Quirks section of
    the connector page.
    """
    if not purl:
        return None
    m = _PURL_ECOSYSTEM_RE.match(purl)
    return m.group(1) if m else None


def extract_cve_id(vulnerability: dict) -> str | None:
    """Return the CVE-id to pin to silver.findings.cve_id.

    Dependency-Track ``vulnerability.vulnId`` is the advisory identifier;
    the advisory source (NVD, OSV, GHSA, VULNDB) determines whether the
    id is already a CVE. When ``source == "NVD"`` the vulnId is the CVE
    id. For OSV and GITHUB, the referenced CVE (when present) sits under
    ``aliases`` — we pick the first CVE-shaped entry.
    """
    vuln_id = vulnerability.get("vulnId") or ""
    if _CVE_RE.match(vuln_id):
        return vuln_id.upper()
    for alias in vulnerability.get("aliases") or []:
        candidate = alias if isinstance(alias, str) else alias.get("vulnId", "")
        if _CVE_RE.match(candidate or ""):
            return candidate.upper()
    return None


def select_finding_hwm(findings: Iterable[dict]) -> str | None:
    """Return the max ``attribution.attributedOn`` across findings, or None.

    Used by the ingest driver to advance the per-project high-water mark
    after a successful page read. Dependency-Track emits an ISO-8601 UTC
    string; lexicographic max is safe for the Z-terminated format.
    """
    best: str | None = None
    for f in findings:
        ts = (f.get("attribution") or {}).get("attributedOn")
        if ts is None:
            continue
        if best is None or ts > best:
            best = ts
    return best


def flatten_finding(project: dict, finding: dict) -> dict:
    """Return the per-row bronze payload for one Dependency-Track finding.

    Captures every field consumed by the mapping (see mapping.yml) and
    leaves enrichment (NVD detail, EPSS, KEV) to downstream stages per
    the SCA category reference.
    """
    component = finding.get("component") or {}
    vulnerability = finding.get("vulnerability") or {}
    attribution = finding.get("attribution") or {}
    analysis = finding.get("analysis") or {}
    purl = component.get("purl")
    return {
        "project_uuid": project.get("uuid"),
        "project_name": project.get("name"),
        "project_version": project.get("version"),
        "repository_id": (project.get("properties") or {}).get("repository_id"),
        "component_uuid": component.get("uuid"),
        "package_name": component.get("name"),
        "package_version": component.get("version"),
        "purl": purl,
        "ecosystem": extract_ecosystem_from_purl(purl),
        "vuln_id_native": vulnerability.get("vulnId"),
        "cve_id": extract_cve_id(vulnerability),
        "advisory_source": vulnerability.get("source"),
        "severity_native": vulnerability.get("severity"),
        "cvss_v3": vulnerability.get("cvssV3"),
        "cwe_id": vulnerability.get("cweId"),
        "analyzer_identity": attribution.get("analyzerIdentity"),
        "attributed_on": attribution.get("attributedOn"),
        "analysis": analysis,
        "isSuppressed": finding.get("isSuppressed", False),
    }


def run_ingest_pipeline(
    spark,
    base_url: str,
    api_key: str,
    bronze_table: str,
    *,
    run_id: str,
    hwm_value: str | None,
    classifier_filter: Iterable[str] = ("APPLICATION", "CONTAINER"),
) -> None:
    """Databricks entry point — backed by the dlt REST source.

    Kept thin: the actual dlt pipeline is declared in a separate notebook
    alongside the job; this function is the source-specific primitive
    that the contract wrapper calls. Live HTTP is not exercised in unit
    tests (CLAUDE.md "No local Spark"). See the job bundle fragment at
    ``resources/dependency_track-job.yml``.
    """
    raise NotImplementedError(
        "Live Dependency-Track ingestion runs on Databricks via the "
        "dlt REST source declared in resources/dependency_track-job.yml"
    )


def ingest_contract(run_id: str, state: ConnectorState) -> BatchDescriptor:
    """Framework contract wrapper for Dependency-Track.

    State-carried ``extra`` keys: ``base_url``, ``api_key``, ``catalog``,
    optional ``bronze_table`` override, optional ``classifier_filter``.
    The DAB job driver populates these from bundle variables and the
    secret scope.
    """
    extra = state.get("extra") or {}
    base_url = extra.get("base_url")
    api_key = extra.get("api_key")
    catalog = extra.get("catalog")
    if not base_url or not api_key or not catalog:
        raise ValueError(
            "dependency_track.ingest_contract requires state['extra'] "
            "with base_url, api_key, catalog"
        )
    bronze_table = (
        extra.get("bronze_table") or f"{catalog}.bronze_dependency_track.findings"
    )
    spark = extra.get("spark")
    classifier_filter = extra.get("classifier_filter") or ("APPLICATION", "CONTAINER")
    run_ingest_pipeline(
        spark,
        base_url,
        api_key,
        bronze_table,
        run_id=run_id,
        hwm_value=state.get("hwm_value"),
        classifier_filter=classifier_filter,
    )
    return {
        "run_id": run_id,
        "source": "dependency_track",
        "record_count": 0,
        "new_hwm_value": state.get("hwm_value"),
        "bronze_table": bronze_table,
    }
