"""Unit tests for the platform-level repository -> application linker.

REQ bindings:

- REQ-TRF-MAP: every well-formed (full_name, app_code) match projects to
  a silver.app_repo_mapping row with link_source='name_match'.
- REQ-DQ: extracted codes that do not resolve in silver.applications are
  dropped silently (no row written, INFO log + counter); valid neighbour
  rows pass through.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.platform.app_repo_link import (
    NAME_RE,
    extract_code,
    link_by_name_pylist,
)

# ----- regex / extract_code -----------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_extract_code_matches_bounded_5_digit_token() -> None:
    """REQ-TRF-MAP: a 5-digit token bounded by non-digits anywhere in
    full_name is the canonical match."""
    assert extract_code("acme/svc-12345") == "12345"
    assert extract_code("acme/12345-other") == "12345"
    assert extract_code("acme/svc-12345-deploy") == "12345"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_extract_code_first_match_wins_on_multi_token_names() -> None:
    """REQ-TRF-MAP: when more than one 5-digit token is present, the
    first one (left-most) wins. Per the spec this is the simple default;
    ambiguous-name handling can be extended later."""
    assert extract_code("acme/12345-thing-67890") == "12345"


@pytest.mark.requirement("REQ-DQ")
def test_extract_code_rejects_non_5_digit_runs() -> None:
    """REQ-DQ: 4-digit, 6-digit, and 8-digit-run names produce no match."""
    assert extract_code("acme/svc-1234") is None
    assert extract_code("acme/svc-123456") is None
    assert extract_code("acme/abc12345xyz") is None


@pytest.mark.requirement("REQ-DQ")
def test_extract_code_returns_none_on_empty_or_naked_name() -> None:
    """REQ-DQ: defensive — empty string and digit-free name yield None."""
    assert extract_code("") is None
    assert extract_code("acme/payments-api") is None


def test_name_re_compile_constant_is_exposed() -> None:
    """Exposing the compiled regex lets callers reuse it without re-parsing."""
    assert NAME_RE.search("acme/12345-thing") is not None
    assert NAME_RE.search("acme/no-digits-here") is None


# ----- link_by_name_pylist ------------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_link_by_name_pylist_emits_one_row_per_match() -> None:
    """REQ-TRF-MAP: three repos whose names embed three known app codes
    each produce one mapping row with link_source='name_match' and
    linked_at=run_ts."""
    apps = [
        {"application_id": "sysid-a", "app_code": "12345"},
        {"application_id": "sysid-b", "app_code": "67890"},
    ]
    repos = [
        {"repository_id": "acme/svc-12345", "full_name": "acme/svc-12345"},
        {"repository_id": "acme/12345-other", "full_name": "acme/12345-other"},
        {"repository_id": "acme/svc-67890-deploy", "full_name": "acme/svc-67890-deploy"},
    ]
    run_ts = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    rows = link_by_name_pylist(apps, repos, run_ts=run_ts)

    pairs = {(r["application_id"], r["repository_id"]) for r in rows}
    assert pairs == {
        ("sysid-a", "acme/svc-12345"),
        ("sysid-a", "acme/12345-other"),
        ("sysid-b", "acme/svc-67890-deploy"),
    }
    for r in rows:
        assert r["link_source"] == "name_match"
        assert r["linked_at"] == run_ts


@pytest.mark.requirement("REQ-TRF-MAP")
def test_link_by_name_pylist_first_match_wins() -> None:
    """REQ-TRF-MAP: a repo whose name embeds two codes resolves only to
    the first match, even when both apps exist."""
    apps = [
        {"application_id": "sysid-a", "app_code": "12345"},
        {"application_id": "sysid-b", "app_code": "67890"},
    ]
    repos = [
        {"repository_id": "acme/12345-thing-67890", "full_name": "acme/12345-thing-67890"},
    ]
    rows = link_by_name_pylist(apps, repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["application_id"] == "sysid-a"


@pytest.mark.requirement("REQ-DQ")
def test_link_by_name_pylist_drops_unmatched_extracted_code() -> None:
    """REQ-DQ: a repo whose extracted code does not resolve in
    silver.applications is dropped silently. A valid neighbour row in
    the same batch passes through unaffected."""
    apps = [
        {"application_id": "sysid-a", "app_code": "12345"},
    ]
    repos = [
        {"repository_id": "acme/svc-12345", "full_name": "acme/svc-12345"},
        {"repository_id": "acme/svc-99999", "full_name": "acme/svc-99999"},
    ]
    rows = link_by_name_pylist(apps, repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["repository_id"] == "acme/svc-12345"


@pytest.mark.requirement("REQ-DQ")
def test_link_by_name_pylist_drops_repos_with_no_extractable_code() -> None:
    """REQ-DQ: a repo whose name carries no 5-digit token is dropped
    silently — no log noise, no phantom row."""
    apps = [{"application_id": "sysid-a", "app_code": "12345"}]
    repos = [{"repository_id": "acme/no-digits", "full_name": "acme/no-digits"}]
    rows = link_by_name_pylist(apps, repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    assert rows == []


@pytest.mark.requirement("REQ-DQ")
def test_link_by_name_pylist_ignores_apps_with_null_app_code() -> None:
    """REQ-DQ: an application without an app_code (None) cannot be linked
    by name; a repo whose name happens to contain ANY 5-digit token must
    NOT match such an app via a coincidental null-equals-something path."""
    apps = [
        {"application_id": "sysid-a", "app_code": None},
        {"application_id": "sysid-b", "app_code": "12345"},
    ]
    repos = [{"repository_id": "acme/svc-12345", "full_name": "acme/svc-12345"}]
    rows = link_by_name_pylist(apps, repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["application_id"] == "sysid-b"


@pytest.mark.requirement("REQ-DQ")
def test_link_by_name_pylist_emits_multiple_rows_when_codes_collide() -> None:
    """REQ-DQ: if two applications share an app_code (a CMDB data error),
    BOTH matching pairs are emitted. Upstream uniqueness is the right
    place to catch this — the linker does not silently drop one signal."""
    apps = [
        {"application_id": "sysid-a", "app_code": "12345"},
        {"application_id": "sysid-b", "app_code": "12345"},
    ]
    repos = [{"repository_id": "acme/svc-12345", "full_name": "acme/svc-12345"}]
    rows = link_by_name_pylist(apps, repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    pairs = {(r["application_id"], r["repository_id"]) for r in rows}
    assert pairs == {
        ("sysid-a", "acme/svc-12345"),
        ("sysid-b", "acme/svc-12345"),
    }


# ----- link_by_name (Spark wrapper) ---------------------------------------
#
# A local SparkSession is used here per the per-connector convention
# (see e.g. src/connectors/servicenow/tests — the framework forbids
# *production* SparkSessions in pure-Python tests but accepts a local
# session in connector tests; the platform tests follow the same rule).


@pytest.fixture(scope="module")
def spark():
    from pyspark.sql import SparkSession
    return (
        SparkSession.builder
        .appName("app-repo-link-tests")
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )


@pytest.mark.requirement("REQ-TRF-MAP")
def test_link_by_name_spark_returns_silver_shaped_dataframe(spark) -> None:
    """REQ-TRF-MAP: the Spark wrapper returns a DataFrame whose columns
    match silver_app_repo_mapping in src/platform/schemas.py exactly."""
    from src.platform.app_repo_link import link_by_name
    from src.platform.schemas import (
        silver_app_repo_mapping,
        silver_applications,
        silver_repositories,
    )

    apps = spark.createDataFrame(
        [("sysid-a", "Checkout", None, None, "12345", datetime(2026, 4, 20, tzinfo=UTC))],
        schema=silver_applications,
    )
    repos = spark.createDataFrame(
        [("acme/svc-12345", "acme/svc-12345", "main", datetime(2026, 4, 20, tzinfo=UTC))],
        schema=silver_repositories,
    )

    out = link_by_name(apps, repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    assert [f.name for f in out.schema.fields] == [
        f.name for f in silver_app_repo_mapping.fields
    ]
    rows = out.collect()
    assert len(rows) == 1
    assert rows[0]["application_id"] == "sysid-a"
    assert rows[0]["repository_id"] == "acme/svc-12345"
    assert rows[0]["link_source"] == "name_match"
    assert rows[0]["linked_at"] == datetime(2026, 4, 26, tzinfo=UTC)


@pytest.mark.requirement("REQ-DQ")
def test_link_by_name_spark_handles_empty_inputs(spark) -> None:
    """REQ-DQ: empty applications or empty repositories input yields an
    empty silver.app_repo_mapping DataFrame, NOT an error."""
    from src.platform.app_repo_link import link_by_name
    from src.platform.schemas import silver_applications, silver_repositories

    empty_apps = spark.createDataFrame([], schema=silver_applications)
    empty_repos = spark.createDataFrame([], schema=silver_repositories)
    out = link_by_name(empty_apps, empty_repos, run_ts=datetime(2026, 4, 26, tzinfo=UTC))
    assert out.count() == 0
