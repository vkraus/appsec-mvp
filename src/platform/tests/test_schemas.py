from pyspark.sql.types import IntegerType, StringType, TimestampType

from src.platform.schemas import (
    silver_app_repo_mapping,
    silver_applications,
    silver_finding_location,
    silver_findings,
    silver_repositories,
)


def test_silver_findings_has_canonical_fields():
    fields = {f.name: f.dataType for f in silver_findings.fields}
    assert fields["finding_id"] == StringType()
    assert fields["tool_source"] == StringType()
    assert fields["category"] == StringType()
    assert fields["severity_canonical"] == StringType()
    assert fields["status_canonical"] == StringType()
    assert fields["cwe_id"] == StringType()  # nullable
    assert fields["cve_id"] == StringType()  # nullable; CVE identifier distinct from CWE class
    assert fields["rule_id_native"] == StringType()
    assert fields["repository_id"] == StringType()  # nullable for dast
    assert fields["file_path"] == StringType()  # nullable for dast
    assert fields["start_line"] == IntegerType()  # nullable for dast
    assert fields["url"] == StringType()  # nullable for sast
    assert fields["first_seen_at"] == TimestampType()
    assert fields["last_seen_at"] == TimestampType()


def test_silver_applications_has_cmdb_fields():
    fields = {f.name for f in silver_applications.fields}
    assert fields == {
        "application_id",
        "name",
        "owner_email",
        "criticality",
        "app_code",
        "updated_at",
    }


def test_silver_repositories_keyed_by_full_name():
    fields = {f.name for f in silver_repositories.fields}
    assert "repository_id" in fields  # canonical key, = full_name for github
    assert "full_name" in fields
    assert "default_branch" in fields
    assert "updated_at" in fields


def test_silver_app_repo_mapping_links_cmdb_to_scm():
    fields = {f.name for f in silver_app_repo_mapping.fields}
    assert fields == {"application_id", "repository_id", "link_source", "linked_at"}


def test_silver_finding_location_covers_code_and_url():
    fields = {f.name for f in silver_finding_location.fields}
    assert fields == {
        "finding_id",
        "repository_id",
        "commit_sha",
        "file_path",
        "start_line",
        "end_line",
        "url",
    }
