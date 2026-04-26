"""GitHub transform REQ-bound tests.

Dual-role source per the SCM reference: entity rows always (repositories,
pull_requests, branch_policies); finding rows from three GitHub Advanced
Security alert streams (code scanning, secret scanning, Dependabot)
discriminated by the ``category`` column on ``silver.findings``.

These tests bind the mapping, severity, status, timestamp, data-quality,
and dedup REQs from the SCM slate to the pure-Python projection helpers
in ``src/connectors/github/transform.py`` and to the declarative YAML
lookups in ``src/connectors/github/severity.yml`` and
``src/connectors/github/status.yml``.

- REQ-TRF-MAP  — every consumed source field projects correctly onto Silver
- REQ-TRF-SEV  — severity lookup covers every documented source value
- REQ-TRF-STS  — status lookup covers every documented source value
- REQ-TRF-TS   — timestamp normalisation lands in UTC
- REQ-DQ       — unmapped severity / status falls through to the configured
                 default rather than crashing or corrupting silver.findings
- REQ-DEDUP    — dedup-key tuple matches the finding-shape discriminator

Pure-logic tests run without Spark. The framework-contract Spark
``transform`` wrapper currently returns an empty silver.findings frame
(see transform.py docstring); the silver-schema-bound assertion is
deferred to validate-implementation against a live bronze fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.connectors.github.transform import (
    branch_protection_to_silver,
    code_scanning_alert_to_finding,
    dependabot_alert_to_finding,
    parse_iso_utc,
    pull_request_to_silver,
    repository_to_silver,
    secret_scanning_alert_to_finding,
)
from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.silver import normalize_severity, normalize_status

_REPO_ROOT = Path(__file__).parents[4]
_SEVERITY_PATH = _REPO_ROOT / "src" / "connectors" / "github" / "severity.yml"
_STATUS_PATH = _REPO_ROOT / "src" / "connectors" / "github" / "status.yml"
_MAPPING_PATH = _REPO_ROOT / "src" / "connectors" / "github" / "mapping.yml"
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
def test_repository_to_silver_projects_expected_fields() -> None:
    """REQ-TRF-MAP: every consumed GraphQL repository field lands on
    ``silver.repositories`` correctly. The opaque GraphQL ``id``
    (node_id) becomes ``repository_id`` (natural key per canonical
    mapping); ``nameWithOwner`` becomes ``full_name``;
    ``defaultBranchRef.name`` becomes ``default_branch``; ``updatedAt``
    becomes ``updated_at``.
    """
    raw = json.loads((_FIX / "repositories.json").read_text())
    out = [repository_to_silver(r) for r in raw]
    by_id = {r["repository_id"]: r for r in out}
    assert set(by_id) == {
        "MDEwOlJlcG9zaXRvcnkxMjM0NTY3OA==",
        "MDEwOlJlcG9zaXRvcnkyMzQ1Njc4OQ==",
    }
    one = by_id["MDEwOlJlcG9zaXRvcnkxMjM0NTY3OA=="]
    assert one["full_name"] == "acme/payments-api"
    assert one["default_branch"] == "main"
    assert one["updated_at"] == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-MAP")
def test_pull_request_to_silver_projects_expected_fields() -> None:
    """REQ-TRF-MAP: pull-request fields project to ``silver.pull_requests``
    with ``head.sha`` / ``head.ref`` / ``base.ref`` / ``user.login``
    flattened from the nested objects, ``merged_at`` round-tripping as
    ``None`` for open PRs, and ``source = "github"`` stamped per the SCM
    reference's per-platform discriminator convention.
    """
    raw = json.loads((_FIX / "pull_requests.json").read_text())
    rows = [pull_request_to_silver("repo-id-1", r) for r in raw]
    by_num = {r["number"]: r for r in rows}
    assert set(by_num) == {17, 18}

    closed = by_num[17]
    assert closed["state"] == "closed"
    assert closed["merged_at"] == datetime(2026, 4, 18, 14, 22, tzinfo=UTC)
    assert closed["target_branch"] == "main"
    assert closed["source"] == "github"
    assert closed["author_username"] == "alice"
    assert closed["repository_id"] == "repo-id-1"
    assert closed["head_sha"] == "d0f1e2a3b4c5d6e7f8091a2b3c4d5e6f70819283"

    open_pr = by_num[18]
    assert open_pr["state"] == "open"
    assert open_pr["merged_at"] is None  # null round-trip


@pytest.mark.requirement("REQ-TRF-MAP")
def test_branch_protection_to_silver_projects_expected_fields() -> None:
    """REQ-TRF-MAP: branch-protection fields project to
    ``silver.branch_policies``; nested ``required_pull_request_reviews``
    and ``required_status_checks`` flatten to scalar columns per the
    connector page § Resource schema excerpt.
    """
    raw = json.loads((_FIX / "branch_protection.json").read_text())
    row = branch_protection_to_silver("repo-id-1", "main", raw)

    assert row["repository_id"] == "repo-id-1"
    assert row["branch_name"] == "main"
    assert row["required_approving_reviews"] == 2
    assert row["dismiss_stale_reviews"] is True
    assert row["strict_status_checks"] is True
    assert row["required_status_check_contexts"] == ["ci/build", "ci/test", "security/codeql"]
    assert row["enforce_admins"] is True


@pytest.mark.requirement("REQ-TRF-MAP")
def test_code_scanning_projection_uses_security_severity_level(
    severity_map: SeverityMap, status_map: StatusMap
) -> None:
    """REQ-TRF-MAP: the code-scanning projection takes severity from
    ``rule.security_severity_level`` (not the rule-level ``severity``)
    per the connector page § Enumerations: 'The framework treats
    ``rule.security_severity_level`` as authoritative; ignoring this
    distinction would produce a connector that systematically
    mis-classifies high-severity findings as ``medium``.'
    """
    raw = json.loads((_FIX / "code_scanning_alerts.json").read_text())
    by_num = {a["number"]: a for a in raw}

    finding = code_scanning_alert_to_finding("repo-id-1", by_num[101], severity_map, status_map)
    # Native rule.severity is ``warning``; security_severity_level is ``high``.
    # The mapping must take the latter path; ``warning`` would resolve to medium.
    assert finding["severity_canonical"] == "high"
    assert finding["category"] == "sast"
    assert finding["tool_source"] == "github"
    assert finding["rule_id_native"] == "py/sql-injection"
    assert finding["file_path"] == "src/api/db.py"
    assert finding["start_line"] == 87
    assert finding["url"] == "https://github.com/acme/payments-api/security/code-scanning/101"

    # And the critical-rule alert resolves identity-style.
    crit = code_scanning_alert_to_finding("repo-id-1", by_num[102], severity_map, status_map)
    assert crit["severity_canonical"] == "critical"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_secret_scanning_projection_follows_locations(
    severity_map: SeverityMap, status_map: StatusMap
) -> None:
    """REQ-TRF-MAP: secret-scanning alerts do not embed file path / line
    on the alert object itself; the connector follows ``locations_url``
    once per alert and stores the first location's ``path`` and
    ``start_line`` (connector page § Quirks).
    """
    raw = json.loads((_FIX / "secret_scanning_alerts.json").read_text())
    by_num = {a["number"]: a for a in raw}

    finding = secret_scanning_alert_to_finding("repo-id-1", by_num[7], severity_map, status_map)
    assert finding["category"] == "secret"
    assert finding["rule_id_native"] == "aws_access_key_id"
    assert finding["file_path"] == ".env.sample"
    assert finding["start_line"] == 3
    assert finding["severity_canonical"] == "high"  # connector page § Enumerations


@pytest.mark.requirement("REQ-TRF-MAP")
def test_dependabot_projection_extracts_cve_and_package(
    severity_map: SeverityMap, status_map: StatusMap
) -> None:
    """REQ-TRF-MAP: Dependabot alerts carry the CVE identifier on
    ``security_advisory.cve_id`` and the vulnerable package on
    ``dependency.package.{name,ecosystem}``. The transform projects them
    onto ``silver.findings.cve_id`` / ``package_name`` / ``ecosystem``
    per the connector page § Resource schema excerpt.
    """
    raw = json.loads((_FIX / "dependabot_alerts.json").read_text())
    by_num = {a["number"]: a for a in raw}

    finding = dependabot_alert_to_finding("repo-id-1", by_num[22], severity_map, status_map)
    assert finding["category"] == "sca"
    assert finding["package_name"] == "lodash"
    assert finding["ecosystem"] == "npm"
    assert finding["cve_id"] == "CVE-2024-12345"
    assert finding["severity_canonical"] == "high"
    assert finding["rule_id_native"] == "CVE-2024-12345"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_mapping_yml_declares_dual_blocks(mapping_doc: dict) -> None:
    """SCM reference § Quirks: ``mapping.yml`` MUST carry two top-level
    blocks (entities and findings) when the source populates both.
    GitHub does so (entities + GitHub Advanced Security findings).
    """
    assert "entities" in mapping_doc
    assert "findings" in mapping_doc
    # Entity block covers the three silver targets documented in the SCM reference.
    assert set(mapping_doc["entities"]) >= {
        "repositories",
        "pull_requests",
        "branch_policies",
    }
    # Finding block covers all three GitHub Advanced Security shapes.
    assert set(mapping_doc["findings"]["shapes"]) == {
        "code_scanning",
        "secret_scanning",
        "dependabot",
    }


# ---------------------------------------------------------------------------
# REQ-TRF-SEV: severity lookup covers every documented source value.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_covers_every_documented_value(severity_map: SeverityMap) -> None:
    """REQ-TRF-SEV: every documented severity value resolves through the
    lookup to one of the canonical four levels. The connector page §
    Enumerations documents two source vocabularies for code scanning
    (``rule.security_severity_level``: critical/high/medium/low; and
    ``rule.severity``: error/warning/note) plus the Dependabot vocabulary
    (``security_vulnerability.severity``: low/medium/high/critical).
    Secret scanning has no native severity field.
    """
    documented_authoritative = ["critical", "high", "medium", "low"]
    documented_rule_level = ["error", "warning", "note"]
    for src in documented_authoritative + documented_rule_level:
        resolved = normalize_severity(src, severity_map)
        assert resolved in {"critical", "high", "medium", "low"}, (src, resolved)

    # Identity mapping for the authoritative form.
    assert normalize_severity("critical", severity_map) == "critical"
    assert normalize_severity("high", severity_map) == "high"
    assert normalize_severity("medium", severity_map) == "medium"
    assert normalize_severity("low", severity_map) == "low"
    # Rule-level vocabulary maps to the closest canonical equivalent.
    assert normalize_severity("error", severity_map) == "high"
    assert normalize_severity("warning", severity_map) == "medium"
    assert normalize_severity("note", severity_map) == "low"


# ---------------------------------------------------------------------------
# REQ-TRF-STS: status lookup covers every documented source value.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_lookup_covers_every_documented_value(status_map: StatusMap) -> None:
    """REQ-TRF-STS: every documented lifecycle state (across the three
    alert streams) resolves through the lookup. Connector page §
    Enumerations documents:

    - code scanning: ``open`` / ``closed`` / ``dismissed`` / ``fixed``
    - secret scanning: ``open`` / ``resolved`` (refined by ``resolution``)
    - Dependabot: ``open`` / ``dismissed`` / ``auto_dismissed`` / ``fixed``
    """
    # Code scanning
    assert normalize_status("open", status_map) == "open"
    assert normalize_status("closed", status_map) == "resolved"
    assert normalize_status("dismissed", status_map) == "wontfix"
    assert normalize_status("fixed", status_map) == "resolved"

    # Dependabot
    assert normalize_status("auto_dismissed", status_map) == "wontfix"

    # Secret-scanning composites (state + resolution)
    assert normalize_status("resolved-false_positive", status_map) == "false_positive"
    assert normalize_status("resolved-wont_fix", status_map) == "wontfix"
    assert normalize_status("resolved-revoked", status_map) == "resolved"
    assert normalize_status("resolved-used_in_tests", status_map) == "false_positive"

    # Bare ``resolved`` (used by secret scanning when no resolution is supplied).
    assert normalize_status("resolved", status_map) == "resolved"


# ---------------------------------------------------------------------------
# REQ-TRF-TS: timestamps land in UTC.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_parse_iso_utc_roundtrips_timezone_aware() -> None:
    """REQ-TRF-TS: GitHub emits UTC ISO-8601 with trailing ``Z``; the
    transform lands a timezone-aware UTC datetime regardless of the
    input suffix form (connector page § Quirks: 'All timestamps are ISO
    8601 UTC').
    """
    zulu = parse_iso_utc("2026-04-20T10:00:00Z")
    offset = parse_iso_utc("2026-04-20T10:00:00+00:00")
    assert zulu == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    assert offset == datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    assert zulu.tzinfo is not None
    assert offset.tzinfo is not None


@pytest.mark.requirement("REQ-TRF-TS")
def test_parse_iso_utc_nullable_passthrough() -> None:
    """REQ-TRF-TS: nullable timestamp fields (``merged_at``, ``fixed_at``,
    ``dismissed_at``, ``auto_dismissed_at``, ``resolved_at``) round-trip
    as ``None`` without raising.
    """
    assert parse_iso_utc(None) is None


@pytest.mark.requirement("REQ-TRF-TS")
def test_finding_timestamps_land_utc(severity_map: SeverityMap, status_map: StatusMap) -> None:
    """REQ-TRF-TS: ``first_seen_at`` (created_at) and ``last_seen_at``
    (updated_at) on every finding shape are timezone-aware UTC datetimes.
    """
    cs_raw = json.loads((_FIX / "code_scanning_alerts.json").read_text())[0]
    cs = code_scanning_alert_to_finding("repo-id-1", cs_raw, severity_map, status_map)
    assert cs["first_seen_at"] == datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    assert cs["last_seen_at"] == datetime(2026, 4, 19, 9, 15, tzinfo=UTC)
    assert cs["first_seen_at"].tzinfo is not None

    dep_raw = json.loads((_FIX / "dependabot_alerts.json").read_text())[0]
    dep = dependabot_alert_to_finding("repo-id-1", dep_raw, severity_map, status_map)
    assert dep["first_seen_at"] == datetime(2026, 4, 5, 14, 0, tzinfo=UTC)
    assert dep["last_seen_at"] == datetime(2026, 4, 18, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# REQ-DQ: unmapped inputs warn through to a configurable default.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_unknown_severity_falls_through_to_default(severity_map: SeverityMap) -> None:
    """REQ-DQ: an undocumented severity (e.g. a future ``moderate``) falls
    through to the shared default (``info``) rather than corrupting
    silver.findings with the raw source value. The YAML-driven lookup is
    authoritative; Python only reads it, so the default is a one-line
    config change per deployment.
    """
    assert normalize_severity("moderate", severity_map) == "info"


@pytest.mark.requirement("REQ-DQ")
def test_unknown_status_falls_through_to_open(status_map: StatusMap) -> None:
    """REQ-DQ: undocumented lifecycle states fall through to ``open``,
    the safer default. Operators see unprocessed findings and can
    adjudicate them rather than having them silently suppressed.
    """
    assert normalize_status("archived_pending_purge", status_map) == "open"


# ---------------------------------------------------------------------------
# REQ-DEDUP: transform branches on category to pick the dedup-key tuple.
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_branches_on_finding_shape(
    severity_map: SeverityMap, status_map: StatusMap
) -> None:
    """REQ-DEDUP: the transform branches on the finding-shape
    discriminator (``category``) and emits the matching dedup-key tuple
    per the connector page § Quirks:

    - sast (code scanning):    (repository_id, file_path, start_line, rule_id)
    - secret (secret scanning):(repository_id, secret_type, file_path, line_number)
    - sca (Dependabot):        (repository_id, package_name, cve_id)
    """
    cs_raw = json.loads((_FIX / "code_scanning_alerts.json").read_text())[0]
    sec_raw = json.loads((_FIX / "secret_scanning_alerts.json").read_text())[0]
    dep_raw = json.loads((_FIX / "dependabot_alerts.json").read_text())[0]

    cs = code_scanning_alert_to_finding("repo-id-1", cs_raw, severity_map, status_map)
    assert cs["category"] == "sast"
    assert cs["dedup_key"] == (
        "repo-id-1",
        "src/api/db.py",
        87,
        "py/sql-injection",
    )

    sec = secret_scanning_alert_to_finding("repo-id-1", sec_raw, severity_map, status_map)
    assert sec["category"] == "secret"
    assert sec["dedup_key"] == (
        "repo-id-1",
        "aws_access_key_id",
        ".env.sample",
        3,
    )

    dep = dependabot_alert_to_finding("repo-id-1", dep_raw, severity_map, status_map)
    assert dep["category"] == "sca"
    assert dep["dedup_key"] == (
        "repo-id-1",
        "lodash",
        "CVE-2024-12345",
    )


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_keys_disjoint_across_shapes(
    severity_map: SeverityMap, status_map: StatusMap
) -> None:
    """REQ-DEDUP: two findings whose key-tuple structures differ MUST
    NOT collapse onto each other. The category-specific tuple shape
    is itself the partitioning key — sast tuples have 4 elements with
    a ``rule_id`` last; secret tuples have 4 elements with a
    ``secret_type`` second; sca tuples have 3 elements ending in
    ``cve_id``. Mis-branching here corrupts ``dedup_links``.
    """
    cs_raw = json.loads((_FIX / "code_scanning_alerts.json").read_text())[0]
    sec_raw = json.loads((_FIX / "secret_scanning_alerts.json").read_text())[0]
    dep_raw = json.loads((_FIX / "dependabot_alerts.json").read_text())[0]

    cs = code_scanning_alert_to_finding("R", cs_raw, severity_map, status_map)
    sec = secret_scanning_alert_to_finding("R", sec_raw, severity_map, status_map)
    dep = dependabot_alert_to_finding("R", dep_raw, severity_map, status_map)

    keys = {cs["dedup_key"], sec["dedup_key"], dep["dedup_key"]}
    # All three shape tuples are distinct.
    assert len(keys) == 3


@pytest.mark.skip(reason="pending live fixtures (B follow-up)")
@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_links_across_github_and_semgrep() -> None:
    """Cross-tool overlap (same SAST finding reported by GitHub code
    scanning and by Semgrep CI) requires real multi-tool data to
    exercise the ``dedup_links`` linkage. validate-implementation drives
    this against a live tenancy with both scanners enabled.
    """
