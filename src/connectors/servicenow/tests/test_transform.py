"""ServiceNow transform tests.

Binds the transform-side REQ-IDs that apply to the CMDB / ServiceNow
profile per ``mkdocs/docs/platform/reference/catalog.md``:

- REQ-TRF-MAP: every consumed field on ``cmdb_ci_business_app`` and
  ``sys_user_group`` projects onto the canonical Silver entity shape;
  the application-to-repository link surfaces in
  ``silver.app_repo_mapping`` only when ``u_repository_id`` is populated.
- REQ-TRF-TS: instance-local datetimes (``YYYY-MM-DD HH:MM:SS``) are
  converted to UTC; naive results are NEVER returned. Verified against
  both UTC and Europe/Berlin instance timezones.
- REQ-DQ: empty-string field values coerce to ``None`` for nullable
  Silver columns (the page § Quirks contract); applications without a
  populated ``u_repository_id`` fall through unlinked rather than
  landing as half-formed mapping rows.

REQ-TRF-SEV / REQ-TRF-STS / REQ-DEDUP are N/A for CMDB and intentionally
NOT bound here per ``references/cmdb.md``.

No local SparkSession is instantiated; the schema-only assertions read the
StructType definitions from ``transform`` directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.connectors.servicenow.transform import (
    normalise_app_repo_link,
    normalise_application,
    normalise_servicenow_datetime,
    normalise_team,
    silver_app_repo_mapping,
    silver_applications,
    silver_teams,
)

FIX = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# ----- REQ-TRF-MAP ---------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_normalise_application_projects_canonical_fields() -> None:
    """REQ-TRF-MAP: every consumed ``cmdb_ci_business_app`` field lands on
    the canonical ``silver.applications`` shape.

    Reference fields (``owned_by`` / ``used_by``) flow through as opaque
    sys_id strings; resolution against ``silver.teams`` is a Silver-side
    join, not a transform-time API call (per the page § Quirks).
    """
    raw = _load_fixture("cmdb_ci_business_app.json")["result"][0]
    row = normalise_application(raw, "UTC")

    assert row["application_id"] == "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    assert row["name"] == "Checkout Frontend"
    assert row["short_description"] == "Customer-facing checkout web application"
    assert row["business_criticality"] == "1 - most critical"
    assert row["operational_status"] == "operational"
    assert row["owned_by"] == "abcdef0123456789abcdef0123456789"
    assert row["used_by"] == "fedcba9876543210fedcba9876543210"
    assert row["valid_from"] == datetime(2024, 9, 15, 8, 30, 0, tzinfo=UTC)
    assert row["updated_at"] == datetime(2026, 4, 20, 14, 22, 11, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-MAP")
def test_normalise_team_projects_canonical_fields() -> None:
    """REQ-TRF-MAP: every consumed ``sys_user_group`` field lands on the
    canonical ``silver.teams`` shape."""
    raw = _load_fixture("sys_user_group.json")["result"][0]
    row = normalise_team(raw, "UTC")

    assert row["team_id"] == "abcdef0123456789abcdef0123456789"
    assert row["name"] == "Payments Platform Team"
    assert row["description"] == "Owns the payment processing services"
    assert row["email"] == "payments-team@example.com"
    assert row["manager"] == "11111111111111111111111111111111"
    assert row["updated_at"] == datetime(2026, 4, 15, 9, 0, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-MAP")
def test_normalise_app_repo_link_emits_mapping_row_when_repo_id_present() -> None:
    """REQ-TRF-MAP: a populated ``u_repository_id`` projects onto a
    ``silver.app_repo_mapping`` row carrying ``application_id``,
    ``repository_id``, and ``linked_at``."""
    raw = _load_fixture("cmdb_ci_business_app.json")["result"][0]
    row = normalise_app_repo_link(raw, "UTC")
    assert row is not None
    assert row["application_id"] == "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    assert row["repository_id"] == "acme/checkout-frontend"
    assert row["linked_at"] == datetime(2026, 4, 20, 14, 22, 11, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-MAP")
def test_silver_schemas_are_entity_shaped_not_finding_shaped() -> None:
    """REQ-TRF-MAP guard: the target schemas are entity-shaped — finding
    columns (``finding_id``, ``severity_canonical``, ``status_canonical``)
    MUST NOT appear. CMDB sources emit entities, not findings."""
    for schema in (silver_applications, silver_teams, silver_app_repo_mapping):
        col_names = {f.name for f in schema.fields}
        assert "finding_id" not in col_names
        assert "severity_canonical" not in col_names
        assert "status_canonical" not in col_names
        assert "cwe_id" not in col_names

    # Entity-shape markers MUST be present on the application schema.
    app_cols = {f.name for f in silver_applications.fields}
    assert {"application_id", "name", "owned_by", "updated_at"} <= app_cols


# ----- REQ-TRF-TS ----------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_servicenow_datetime_normalises_utc_instance_to_utc() -> None:
    """REQ-TRF-TS: a UTC-configured instance produces datetimes whose UTC
    representation matches the wire string verbatim."""
    out = normalise_servicenow_datetime("2026-04-20 14:22:11", "UTC")
    assert out == datetime(2026, 4, 20, 14, 22, 11, tzinfo=UTC)
    assert out.tzinfo is UTC


@pytest.mark.requirement("REQ-TRF-TS")
def test_servicenow_datetime_converts_europe_berlin_to_utc() -> None:
    """REQ-TRF-TS: an instance configured for ``Europe/Berlin`` (CEST in
    April, UTC+02:00) shifts BACK by two hours when normalised to UTC.

    A silent UTC-skew bug — failing to convert — would land
    ``12:00:00`` Berlin local as ``12:00:00`` UTC, two hours ahead of
    reality. This test pins the conversion behaviour.
    """
    raw = _load_fixture("cmdb_ci_business_app_instance_local_timestamps.json")["result"][0]
    row = normalise_application(raw, "Europe/Berlin")
    # 2026-04-20 12:00:00 Europe/Berlin (CEST, UTC+02:00) -> 10:00:00 UTC.
    assert row["updated_at"] == datetime(2026, 4, 20, 10, 0, 0, tzinfo=UTC)
    assert row["updated_at"].tzinfo is UTC


@pytest.mark.requirement("REQ-TRF-TS")
def test_servicenow_datetime_accepts_zoneinfo_instance() -> None:
    """REQ-TRF-TS: callers may pass a pre-instantiated ``ZoneInfo`` rather
    than the IANA name string; both resolve to the same conversion."""
    out = normalise_servicenow_datetime("2026-04-20 12:00:00", ZoneInfo("Europe/Berlin"))
    assert out == datetime(2026, 4, 20, 10, 0, 0, tzinfo=UTC)


@pytest.mark.requirement("REQ-TRF-TS")
def test_servicenow_datetime_returns_none_for_empty_or_missing() -> None:
    """REQ-TRF-TS edge case: empty strings and ``None`` -> ``None``; do
    NOT raise on optional timestamp columns."""
    assert normalise_servicenow_datetime(None, "UTC") is None
    assert normalise_servicenow_datetime("", "UTC") is None


@pytest.mark.requirement("REQ-TRF-TS")
def test_servicenow_datetime_rejects_unrecognised_format() -> None:
    """REQ-TRF-TS defensive: a non-native format is rejected loudly so the
    UTC-skew bug class cannot be reintroduced via shape changes upstream."""
    with pytest.raises(ValueError):
        normalise_servicenow_datetime("2026-04-20T14:22:11Z", "UTC")  # ISO-8601


# ----- REQ-DQ --------------------------------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_empty_string_values_coerce_to_none_on_application() -> None:
    """REQ-DQ: empty-string values (the ServiceNow null sentinel per the
    page § Quirks) coerce to ``None`` for all nullable Silver columns —
    the schema stays honest and downstream DQ expectations don't see
    spurious empty strings."""
    raw = _load_fixture("cmdb_ci_business_app_empty_field_coercion.json")["result"][0]
    row = normalise_application(raw, "UTC")
    assert row["short_description"] is None
    assert row["business_criticality"] is None
    assert row["owned_by"] is None
    assert row["used_by"] is None
    # Non-empty fields are preserved.
    assert row["application_id"] == "4e5f60718293a4b5c6d7e8f9aabbccdd"
    assert row["name"] == "Sparse Application Record"
    assert row["operational_status"] == "operational"


@pytest.mark.requirement("REQ-DQ")
def test_team_empty_string_values_coerce_to_none() -> None:
    """REQ-DQ: empty-string sentinel coercion applies on the team
    projection too — ``description`` / ``email`` / ``manager`` may all
    be unset on a sparse group record."""
    raw = _load_fixture("sys_user_group.json")["result"][1]
    row = normalise_team(raw, "UTC")
    assert row["description"] is None
    assert row["email"] is None
    assert row["manager"] is None
    assert row["team_id"] == "fedcba9876543210fedcba9876543210"
    assert row["name"] == "Customer Experience Team"


@pytest.mark.requirement("REQ-DQ")
def test_application_without_repo_link_does_not_emit_mapping_row() -> None:
    """REQ-DQ: applications WITHOUT a populated ``u_repository_id`` MUST
    NOT land in ``silver.app_repo_mapping`` — they remain in
    ``silver.applications`` only.

    The unmatched-bucket contract is documented on the connector page;
    half-formed mapping rows with null ``repository_id`` would violate
    the silver-side schema and obscure DQ alerting."""
    # The third record in the primary fixture has u_repository_id="".
    raw = _load_fixture("cmdb_ci_business_app.json")["result"][2]
    assert raw["u_repository_id"] == ""
    assert normalise_app_repo_link(raw, "UTC") is None


@pytest.mark.requirement("REQ-DQ")
def test_application_natural_key_is_non_null_on_every_record() -> None:
    """REQ-DQ: ``sys_id`` is the natural key for entity dedup at upsert
    time — it MUST NOT be null on any valid record. A production Lakeflow
    expectation would enforce this; the fixtures model the invariant."""
    records = _load_fixture("cmdb_ci_business_app.json")["result"]
    for raw in records:
        row = normalise_application(raw, "UTC")
        assert row["application_id"], f"sys_id is null on record: {raw!r}"


# ----- N/A REQs are NOT bound here — confirmed by absence ------------------
#
# Per references/cmdb.md and the catalog.md ServiceNow column:
#   - REQ-TRF-SEV: N/A (no findings emitted; lookup is empty)
#   - REQ-TRF-STS: N/A (no finding lifecycle)
#   - REQ-DEDUP:   N/A (entity dedup is via natural key sys_id, not
#                  cross-tool dedup_links)
#
# These REQ-IDs MUST NOT carry @pytest.mark.requirement bindings in this
# suite — the validate-implementation skill expects N/A cells on the
# traceability matrix.
