"""GitLab transform REQ-bound tests.

Dual-role source (SCM reference): entities always, findings when the
deployment is on Ultimate. These tests bind the mapping, severity, status,
timestamp, data-quality, and dedup REQs from the SCM slate to the pure-Python
projection helpers in ``src/connectors/gitlab/transform.py`` and to the
declarative YAML lookups in ``src/connectors/gitlab/severity.yml`` and
``src/connectors/gitlab/status.yml``.

- REQ-TRF-MAP  — every consumed source field projects correctly onto Silver
- REQ-TRF-SEV  — severity lookup covers every documented source value
- REQ-TRF-STS  — status lookup covers every documented source value
- REQ-TRF-TS   — timestamp normalisation lands in UTC
- REQ-DQ       — unmapped severity values fall through to the configured default
- REQ-DEDUP    — dedup-key tuple matches the finding-shape discriminator
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.connectors.gitlab.transform import (
    merge_request_to_pull_request,
    parse_iso_utc,
    project_to_repository,
    protected_branch_to_policy,
    vulnerability_to_finding,
)
from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.silver import normalize_severity, normalize_status

_REPO_ROOT = Path(__file__).parents[4]
_SEVERITY_PATH = _REPO_ROOT / "src" / "connectors" / "gitlab" / "severity.yml"
_STATUS_PATH = _REPO_ROOT / "src" / "connectors" / "gitlab" / "status.yml"
_MAPPING_PATH = _REPO_ROOT / "src" / "connectors" / "gitlab" / "mapping.yml"
_FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def severity_map() -> SeverityMap:
    return load_yaml(SeverityMap, _SEVERITY_PATH)


@pytest.fixture(scope="module")
def status_map() -> StatusMap:
    return load_yaml(StatusMap, _STATUS_PATH)


@pytest.fixture(scope="module")
def mapping_doc() -> dict:
    with open(_MAPPING_PATH) as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# REQ-TRF-MAP: Silver projections hold for every ingested endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_project_to_repository_projects_expected_fields() -> None:
    """Every consumed /projects field lands on silver.repositories correctly.

    Integer ``id`` becomes the string ``repository_id`` (natural_key per
    connector page § Quirks), ``path_with_namespace`` becomes ``full_name``,
    ``last_activity_at`` is the freshest timestamp (populates ``updated_at``).
    """
    raw = json.loads((_FIX / "projects.json").read_text())
    out = [project_to_repository(r) for r in raw]
    by_id = {r["repository_id"]: r for r in out}
    assert set(by_id) == {"200", "201"}
    assert by_id["200"]["full_name"] == "acme/payments-api"
    assert by_id["200"]["default_branch"] == "main"
    assert by_id["200"]["updated_at"] == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-MAP")
def test_merge_request_to_pull_request_projects_expected_fields() -> None:
    """Merge requests map to pull_requests with the ``iid -> number`` rename
    and ``source = "gitlab"`` stamped per connector page § Quirks."""
    raw = json.loads((_FIX / "merge_requests.json").read_text())
    rows = [merge_request_to_pull_request(200, r) for r in raw]

    by_num = {r["number"]: r for r in rows}
    assert set(by_num) == {17, 18}

    merged = by_num[17]
    assert merged["state"] == "merged"
    assert merged["merged_at"] == datetime(2026, 4, 18, 14, 22, tzinfo=UTC)
    assert merged["target_branch"] == "main"
    assert merged["source"] == "gitlab"
    assert merged["author_username"] == "alice"
    assert merged["repository_id"] == "200"

    open_mr = by_num[18]
    assert open_mr["state"] == "opened"
    assert open_mr["merged_at"] is None  # null round-trip


@pytest.mark.requirement("REQ-TRF-MAP")
def test_protected_branch_to_policy_reduces_access_levels() -> None:
    """allowed_to_push / allowed_to_merge arrays reduce to the highest
    canonical role per the connector page § Enumerations mapping."""
    raw = json.loads((_FIX / "protected_branches.json").read_text())
    rows = [protected_branch_to_policy(200, b) for b in raw]
    by_name = {r["branch_name"]: r for r in rows}
    assert by_name["main"]["allowed_to_push"] == "maintainer"
    # main has two merge access levels — the highest (40, Maintainer) wins
    assert by_name["main"]["allowed_to_merge"] == "maintainer"
    # release/* escalates push to Admin only
    assert by_name["release/*"]["allowed_to_push"] == "admin"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_mapping_yml_declares_dual_blocks(mapping_doc: dict) -> None:
    """SCM reference § Quirks: ``mapping.yml`` MUST carry two top-level
    blocks (entities and findings) when the source populates both."""
    assert "entities" in mapping_doc
    assert "findings" in mapping_doc
    # Entity block covers the four silver targets documented in the SCM reference.
    assert set(mapping_doc["entities"]) >= {
        "repositories",
        "commits",
        "pull_requests",
        "branch_policies",
    }


# ---------------------------------------------------------------------------
# REQ-TRF-SEV / REQ-TRF-STS: lookup files cover every documented source value.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_covers_every_documented_value(severity_map: SeverityMap) -> None:
    """Connector page § Enumerations documents six severity values. Every
    one must resolve through the lookup to a canonical four-level bucket
    (info / unknown fall through to the configured default per the page's
    Quirks section)."""
    documented = ["info", "unknown", "low", "medium", "high", "critical"]
    for src in documented:
        resolved = normalize_severity(src, severity_map)
        assert resolved in {"critical", "high", "medium", "low"}, (src, resolved)

    assert normalize_severity("critical", severity_map) == "critical"
    assert normalize_severity("high", severity_map) == "high"
    assert normalize_severity("medium", severity_map) == "medium"
    assert normalize_severity("low", severity_map) == "low"
    # info/unknown fall through to the connector-configured default (low).
    assert normalize_severity("info", severity_map) == "low"
    assert normalize_severity("unknown", severity_map) == "low"


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_lookup_covers_every_documented_value(status_map: StatusMap) -> None:
    """Connector page § Enumerations documents four lifecycle states. Every
    one must resolve through the lookup."""
    assert normalize_status("detected", status_map) == "open"
    assert normalize_status("confirmed", status_map) == "confirmed"
    assert normalize_status("dismissed", status_map) == "false_positive"
    assert normalize_status("resolved", status_map) == "resolved"


# ---------------------------------------------------------------------------
# REQ-TRF-TS: timestamps land in UTC.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_parse_iso_utc_roundtrips_timezone_aware() -> None:
    """GitLab emits UTC ISO-8601 with trailing Z; the transform lands a
    timezone-aware UTC datetime regardless of the input suffix form
    (connector page § Incremental hook)."""
    zulu = parse_iso_utc("2026-04-20T10:00:00.000Z")
    offset = parse_iso_utc("2026-04-20T10:00:00+00:00")
    assert zulu == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    assert offset == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    assert zulu.tzinfo is not None and offset.tzinfo is not None


@pytest.mark.requirement("REQ-TRF-TS")
def test_parse_iso_utc_nulls_passthrough() -> None:
    """Nullable timestamp fields (``merged_at``, ``location.start_line``)
    must round-trip as None without raising."""
    assert parse_iso_utc(None) is None


# ---------------------------------------------------------------------------
# REQ-DQ: unmapped inputs warn through to a configurable default.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_unknown_severity_falls_through_to_default(severity_map: SeverityMap) -> None:
    """An undocumented severity (e.g. a future ``trivial``) falls through to
    the shared default (``info``) rather than corrupting Silver with the raw
    source value. The YAML-driven lookup is authoritative; Python only reads
    it, so the default is a one-line config change per deployment."""
    assert normalize_severity("trivial", severity_map) == "info"
    # Documented values never fall through.
    for doc in ("critical", "high", "medium", "low", "info", "unknown"):
        assert normalize_severity(doc, severity_map) != "info" or doc in ("info", "unknown")


@pytest.mark.requirement("REQ-DQ")
def test_unknown_status_falls_through_to_default(status_map: StatusMap) -> None:
    """Undocumented lifecycle states fall through to ``open`` — the safer
    default because operators see unprocessed findings and can adjudicate
    them rather than having them silently suppressed."""
    assert normalize_status("archived_pending_purge", status_map) == "open"


# ---------------------------------------------------------------------------
# REQ-DEDUP: transform branches on report_type to pick the dedup-key tuple.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_branches_on_finding_shape() -> None:
    """SCM reference § Deduplication key: transform.py MUST branch on the
    finding-shape discriminator (``report_type`` -> category) and emit
    ``dedup_links`` rows keyed by the matching tuple.

    - sast / secret: (repository_id, file_path, start_line, rule_id_native)
    - sca:           (repository_id, package_name, cve_id)
    """
    raw = json.loads((_FIX / "vulnerabilities.json").read_text())
    by_id = {r["id"]: r for r in raw}

    sast = vulnerability_to_finding(200, by_id[5001])
    assert sast["category"] == "sast"
    assert sast["dedup_key"] == ("200", "src/auth/tokens.py", 42, "Predictable pseudorandom number generator (PRNG)")

    secret = vulnerability_to_finding(200, by_id[5002])
    assert secret["category"] == "secret"
    assert secret["dedup_key"] == ("200", ".env.sample", 3, "AWS Access Key committed")

    sca = vulnerability_to_finding(200, by_id[5003])
    assert sca["category"] == "sca"
    assert sca["package_name"] == "lodash"
    assert sca["cwe_id"] == "CVE-2024-12345"
    assert sca["dedup_key"] == ("200", "lodash", "CVE-2024-12345")

    # SCA finding without a top-level ``cve`` must fall back to the first
    # ``cve``-typed entry in ``identifiers`` per connector page § Resource
    # schema excerpt. Mis-branching here corrupts dedup_links.
    sca_fallback = vulnerability_to_finding(200, by_id[5005])
    assert sca_fallback["cwe_id"] == "CVE-2023-99999"
    assert sca_fallback["dedup_key"] == ("200", "django", "CVE-2023-99999")


@pytest.mark.requirement("REQ-DEDUP")
def test_sast_and_secret_dedup_keys_are_disjoint() -> None:
    """Two findings with identical (file, line) but different report_type
    MUST NOT collapse onto each other: sast/secret tuples include
    rule_id_native as the fourth element, so identical code locations with
    different rules stay distinct."""
    raw = json.loads((_FIX / "vulnerabilities.json").read_text())
    by_id = {r["id"]: r for r in raw}

    sast = vulnerability_to_finding(200, by_id[5001])
    # Synthesize a secret finding at the same (file, line) but different rule.
    sibling = dict(by_id[5001])
    sibling["id"] = 5999
    sibling["report_type"] = "secret_detection"
    sibling["name"] = "Synthetic secret at same location"
    secret = vulnerability_to_finding(200, sibling)

    assert sast["dedup_key"] != secret["dedup_key"], "distinct rules must not collapse"


@pytest.mark.skip(reason="pending live fixtures (B follow-up)")
@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_links_across_gitlab_and_semgrep() -> None:
    """Cross-tool overlap (same SAST finding reported by GitLab SAST and by
    Semgrep CI) requires real multi-tool data to exercise the ``dedup_links``
    linkage. Validate-implementation drives this against a live GitLab
    Ultimate tenancy with Semgrep CI also configured."""
